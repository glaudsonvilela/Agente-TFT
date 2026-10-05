//! Reviewed exemplars on frozen embeddings. Only training rows enter the index.
use crate::{training::metrics_with_predictor, Result, Sample};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{fs, path::Path, time::Instant};

#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
pub enum Pooling {
    #[serde(rename = "class_max_cosine_v1")]
    Max,
    #[serde(rename = "class_top3_mean_cosine_v1")]
    Top3Mean,
    #[serde(rename = "class_mean_cosine_v1")]
    Mean,
}

#[derive(Clone, Serialize, Deserialize)]
pub struct RetrievalHead {
    labels: Vec<String>,
    dimensions: usize,
    vectors: Vec<Vec<f32>>,
    targets: Vec<usize>,
    support: Vec<(String, String)>,
    pooling: Pooling,
    temperature: f32,
}

fn unit_vector(x: &[f32]) -> Result<Vec<f32>> {
    if x.is_empty() || x.iter().any(|x| !x.is_finite()) {
        return Err("nonfinite/empty retrieval vector".into());
    }
    let norm = x.iter().map(|v| (*v as f64).powi(2)).sum::<f64>().sqrt();
    if !norm.is_finite() || norm <= 1e-12 {
        return Err("zero/invalid retrieval vector".into());
    }
    Ok(x.iter().map(|v| (*v as f64 / norm) as f32).collect())
}

impl RetrievalHead {
    pub fn from_value(value: Value) -> Result<Self> {
        let head: Self = serde_json::from_value(value)?;
        if head.labels.len() < 2
            || head.dimensions == 0
            || head.labels.windows(2).any(|w| w[0] >= w[1])
            || head.vectors.len() != head.targets.len()
            || head.vectors.len() != head.support.len()
            || !head.temperature.is_finite()
            || head.temperature <= 0.
        {
            return Err("invalid retrieval index shape/policy".into());
        }
        let mut counts = vec![0usize; head.labels.len()];
        for (v, &target) in head.vectors.iter().zip(&head.targets) {
            if v.len() != head.dimensions || target >= counts.len() {
                return Err("invalid retrieval support dimensions/target".into());
            }
            let normalized = unit_vector(v)?;
            if v.iter().zip(normalized).any(|(a, b)| (*a - b).abs() > 1e-5) {
                return Err("retrieval support is not normalized".into());
            }
            counts[target] += 1;
        }
        if counts.contains(&0) {
            return Err("retrieval class without training support".into());
        }
        Ok(head)
    }

    fn build(samples: &[Sample], features: &[Vec<f32>], pooling: Pooling) -> Result<Self> {
        if samples.len() != features.len() {
            return Err("sample/feature count mismatch".into());
        }
        let rows: Vec<_> = samples
            .iter()
            .zip(features)
            .filter(|(s, _)| s.split == "train")
            .collect();
        let mut labels: Vec<_> = rows.iter().map(|(s, _)| s.label.clone()).collect();
        labels.sort();
        labels.dedup();
        let head = Self {
            dimensions: rows
                .first()
                .ok_or("empty retrieval training split")?
                .1
                .len(),
            vectors: rows
                .iter()
                .map(|(_, x)| unit_vector(x))
                .collect::<Result<_>>()?,
            targets: rows
                .iter()
                .map(|(s, _)| labels.binary_search(&s.label).unwrap())
                .collect(),
            support: rows
                .iter()
                .map(|(s, _)| (s.image.clone(), s.key.clone()))
                .collect(),
            labels,
            pooling,
            temperature: 0.07,
        };
        Self::from_value(serde_json::to_value(head)?)
    }

    pub fn labels(&self) -> &[String] {
        &self.labels
    }

    pub fn probabilities(&self, query: &[f32]) -> Result<Vec<f32>> {
        if query.len() != self.dimensions {
            return Err("retrieval query dimension mismatch".into());
        }
        let query = unit_vector(query)?;
        let mut classes = vec![Vec::new(); self.labels.len()];
        for (v, &target) in self.vectors.iter().zip(&self.targets) {
            let similarity: f32 = v.iter().zip(&query).map(|(a, b)| a * b).sum();
            classes[target].push(similarity);
        }
        let mut scores = Vec::with_capacity(classes.len());
        for mut values in classes {
            values.sort_by(|a, b| b.total_cmp(a));
            let n = match self.pooling {
                Pooling::Max => 1,
                Pooling::Top3Mean => 3.min(values.len()),
                Pooling::Mean => values.len(),
            };
            scores.push(values[..n].iter().sum::<f32>() / n as f32 / self.temperature);
        }
        let max = scores.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        scores.iter_mut().for_each(|v| *v = (*v - max).exp());
        let total: f32 = scores.iter().sum();
        if !total.is_finite() || total <= 0. {
            return Err("invalid retrieval scores".into());
        }
        scores.iter_mut().for_each(|v| *v /= total);
        Ok(scores)
    }
}

pub fn build_experiment(
    samples: &[Sample],
    features: &[Vec<f32>],
    spec: &Value,
    spec_bytes: &[u8],
    output: &Path,
    start: Instant,
    cache_hits: usize,
) -> Result<()> {
    let validation: Vec<_> = samples
        .iter()
        .zip(features)
        .filter(|(s, _)| s.split == "validation")
        .collect();
    if validation.is_empty() {
        return Err("retrieval validation required".into());
    }
    let mut selected: Option<(f64, f64, RetrievalHead)> = None;
    let mut candidates = Vec::new();
    for pooling in [Pooling::Max, Pooling::Top3Mean, Pooling::Mean] {
        let head = RetrievalHead::build(samples, features, pooling)?;
        let m = metrics_with_predictor(head.labels(), &validation, |x| head.probabilities(x))?;
        let score = m["named_macro_recall"].as_f64().ok_or("validation score")?;
        let loss = m["cross_entropy"].as_f64().ok_or("validation loss")?;
        candidates.push(json!({"pooling":pooling,"validation":m}));
        if selected
            .as_ref()
            .is_none_or(|(s, l, _)| score > *s || score == *s && loss < *l)
        {
            selected = Some((score, loss, head));
        }
    }
    let (_, _, head) = selected.ok_or("retrieval selection")?;
    // Test data are consulted only after the index and pooling policy are fixed.
    let tests: Vec<_> = samples
        .iter()
        .zip(features)
        .filter(|(s, _)| s.split == "test")
        .collect();
    let test = metrics_with_predictor(head.labels(), &tests, |x| head.probabilities(x))?;
    let validation = metrics_with_predictor(head.labels(), &validation, |x| head.probabilities(x))?;
    let hash = |b: &[u8]| format!("{:x}", Sha256::digest(b));
    let annotation_bytes = fs::read(spec["annotations"].as_str().ok_or("annotations")?)?;
    let model = json!({"schema_version":1,"feature_mode":"dino","classifier_type":"retrieval_v1",
        "retrieval":head,"encoder_sha256":spec["encoder_sha256"],"annotations_sha256":hash(&annotation_bytes),
        "input_size":spec["input_size"],"crop_transform":spec["crop_transform"],
        "embedding_batch_size":crate::embedding_batch_size(spec.get("embedding_batch_size"))?,
        "runtime_approved":false,"probabilities_calibrated":false});
    let bytes = serde_json::to_vec(&model)?;
    fs::write(output.join("retrieval-head.json"), &bytes)?;
    let report = json!({"schema_version":1,"implementation":"rust_native","training_performed":false,
        "supervised_index_built":true,"backbone_finetuned":false,"gradient_updates":0,
        "selection":"validation_macro_recall_then_loss","candidates":candidates,
        "selected_pooling":head.pooling,"training_support":head.vectors.len(),"training_classes":head.labels.len(),
        "evaluation":{"validation":validation,"test":test},"head_sha256":hash(&bytes),
        "artifact_bytes":bytes.len(),"spec_sha256":hash(spec_bytes),"embedding_cache_hit_batches":cache_hits,
        "elapsed_seconds":start.elapsed().as_secs_f64(),"runtime_approved":false,
        "limitations":["Only reviewed training rows enter the index; no classifier pseudolabels.",
        "No training accuracy is reported because matching an exemplar to itself is trivial.",
        "Validation is small and repeatedly consulted; development tests are not untouched final holdouts.",
        "Cosine similarities are converted to uncalibrated softmax scores with temperature 0.07.",
        "Assistant-reviewed labels are not independent human ground truth.","No Windows capture/display benchmark."]});
    fs::write(
        output.join("report.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    println!(
        "{}",
        json!({"pooling":head.pooling,"validation_correct":validation["named_top1_correct"],"test_correct":test["named_top1_correct"]})
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use agente_tft_image_preprocess::unit_features::UnitCrop;
    fn sample(label: &str, split: &str) -> Sample {
        Sample {
            crop: UnitCrop { rgb: vec![] },
            label: label.into(),
            split: split.into(),
            image: format!("{split}/{label}"),
            key: "unit".into(),
        }
    }
    #[test]
    fn evaluation_examples_never_enter_support_and_order_does_not_change_scores() {
        let mut samples = vec![
            sample("a", "train"),
            sample("b", "train"),
            sample("only_test", "test"),
            sample("only_validation", "validation"),
        ];
        let mut vectors = vec![vec![1., 0.], vec![0., 1.], vec![1., 1.], vec![-1., 0.]];
        for mode in [Pooling::Max, Pooling::Top3Mean, Pooling::Mean] {
            let a = RetrievalHead::build(&samples, &vectors, mode).unwrap();
            assert_eq!(a.labels, vec!["a", "b"]);
            assert_eq!(a.support.len(), 2);
            let p = a.probabilities(&[10., 0.]).unwrap();
            assert!(p[0] > p[1]);
            samples.reverse();
            vectors.reverse();
            let b = RetrievalHead::build(&samples, &vectors, mode).unwrap();
            assert_eq!(p, b.probabilities(&[1., 0.]).unwrap());
        }
    }
    #[test]
    fn invalid_serialized_support_and_invalid_queries_fail_closed() {
        let h = RetrievalHead::build(
            &[sample("a", "train"), sample("b", "train")],
            &[vec![1., 0.], vec![0., 1.]],
            Pooling::Max,
        )
        .unwrap();
        assert!(h.probabilities(&[0., 0.]).is_err());
        assert!(h.probabilities(&[f32::NAN, 0.]).is_err());
        assert!(h.probabilities(&[1.]).is_err());
        for (field, value) in [
            ("targets", json!([0, 9])),
            ("vectors", json!([[2., 0.], [0., 1.]])),
            ("temperature", json!(0)),
        ] {
            let mut v = serde_json::to_value(&h).unwrap();
            v[field] = value;
            assert!(RetrievalHead::from_value(v).is_err());
        }
    }
}
