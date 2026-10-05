//! Supervised lightweight heads on frozen native features. No pseudo-label training.
use super::*;
use serde::{Deserialize, Serialize};

const COLOR_DIM: usize = 4 * 52;

fn augment_training(samples: &mut Vec<Sample>) -> Result<usize> {
    let originals: Vec<_> = samples
        .iter()
        .filter(|s| s.split == "train")
        .cloned()
        .collect();
    let mut added = 0;
    for original in originals {
        for mode in ["mirror", "dim", "bright", "mask"] {
            let mut s = original.clone();
            match mode {
                "mirror" => {
                    for y in 0..HEIGHT {
                        for x in 0..WIDTH {
                            for c in 0..3 {
                                s.crop.rgb[(y * WIDTH + x) * 3 + c] =
                                    original.crop.rgb[(y * WIDTH + WIDTH - 1 - x) * 3 + c];
                            }
                        }
                    }
                }
                "mask" => {
                    if s.crop.foreground()?.empty {
                        continue;
                    }
                }
                _ => {
                    let scale = if mode == "dim" { 0.75 } else { 1.25 };
                    for v in &mut s.crop.rgb {
                        *v = (*v as f32 * scale).round().clamp(0., 255.) as u8;
                    }
                }
            }
            s.key = format!("{}@augmentation:{mode}", s.key);
            samples.push(s);
            added += 1;
        }
    }
    Ok(added)
}

/// Spatial HSV histogram with separate achromatic bins. Square-root frequencies
/// give a Hellinger embedding. This describes the central crop, not a true mask.
pub fn colors(crop: &UnitCrop) -> Vec<f32> {
    let mut out = vec![0f32; COLOR_DIM];
    for y in 0..120 {
        for x in 16..112 {
            let p = (y * WIDTH + x) * 3;
            let r = crop.rgb[p] as f32 / 255.;
            let g = crop.rgb[p + 1] as f32 / 255.;
            let b = crop.rgb[p + 2] as f32 / 255.;
            let hi = r.max(g).max(b);
            let lo = r.min(g).min(b);
            let d = hi - lo;
            let s = if hi > 0. { d / hi } else { 0. };
            let bin = if s < 0.12 || hi < 0.08 {
                48 + ((hi * 4.) as usize).min(3)
            } else {
                let h = if hi == r {
                    (g - b) / d
                } else if hi == g {
                    (b - r) / d + 2.
                } else {
                    (r - g) / d + 4.
                };
                let hue = ((h.rem_euclid(6.) * 2.) as usize).min(11);
                hue * 4 + usize::from(s >= 0.5) * 2 + usize::from(hi >= 0.5)
            };
            let cell = (y / 60) * 2 + (x - 16) / 48;
            out[cell * 52 + bin] += 1.;
        }
    }
    for x in &mut out {
        *x = x.sqrt();
    }
    normalize(&mut out);
    out
}

#[derive(Clone, Serialize, Deserialize)]
pub struct Head {
    pub labels: Vec<String>,
    pub dimensions: usize,
    pub weights: Vec<f32>,
    pub biases: Vec<f32>,
}
impl Head {
    pub fn probabilities(&self, x: &[f32]) -> Result<Vec<f32>> {
        if self.labels.len() < 2
            || x.len() != self.dimensions
            || self.weights.len() != self.labels.len() * self.dimensions
            || self.biases.len() != self.labels.len()
            || x.iter()
                .chain(&self.weights)
                .chain(&self.biases)
                .any(|v| !v.is_finite())
        {
            return Err("invalid classifier dimensions/nonfinite values".into());
        }
        let mut scores: Vec<f32> = self
            .weights
            .chunks_exact(self.dimensions)
            .zip(&self.biases)
            .map(|(w, b)| w.iter().zip(x).map(|(a, b)| a * b).sum::<f32>() + b)
            .collect();
        let max = scores.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        scores.iter_mut().for_each(|v| *v = (*v - max).exp());
        let sum: f32 = scores.iter().sum();
        if !sum.is_finite() || sum <= 0. {
            return Err("nonfinite classifier output".into());
        }
        scores.iter_mut().for_each(|v| *v /= sum);
        Ok(scores)
    }
}

fn metrics(head: &Head, rows: &[(&Sample, &Vec<f32>)]) -> Result<Value> {
    let mut per_class: BTreeMap<String, (u64, u64)> = BTreeMap::new();
    let mut confusion: BTreeMap<String, u64> = BTreeMap::new();
    let mut predictions = Vec::new();
    let mut loss = 0.;
    for (sample, x) in rows {
        let p = head.probabilities(x)?;
        let k = (0..p.len())
            .max_by(|&a, &b| p[a].total_cmp(&p[b]).then(b.cmp(&a)))
            .unwrap();
        let correct = head.labels[k] == sample.label;
        let counts = per_class.entry(sample.label.clone()).or_default();
        counts.0 += 1;
        counts.1 += u64::from(correct);
        if !correct {
            *confusion
                .entry(format!("{} -> {}", sample.label, head.labels[k]))
                .or_default() += 1;
        }
        let truth = head.labels.iter().position(|s| s == &sample.label);
        loss -= truth.map(|i| p[i]).unwrap_or(0.).max(1e-12).ln() as f64;
        predictions.push(json!({"image":sample.image,"key":sample.key,"label":sample.label,
            "predicted":head.labels[k],"softmax_score_uncalibrated":p[k],"identity_verified":false}));
    }
    let named: Vec<_> = per_class
        .iter()
        .filter(|(id, _)| id.as_str() != "__unknown__")
        .collect();
    let macro_recall = if named.is_empty() {
        0.
    } else {
        named
            .iter()
            .map(|(_, (n, c))| *c as f64 / *n as f64)
            .sum::<f64>()
            / named.len() as f64
    };
    Ok(
        json!({"samples":rows.len(),"named":named.iter().map(|(_,p)|p.0).sum::<u64>(),
        "named_top1_correct":named.iter().map(|(_,p)|p.1).sum::<u64>(),"named_macro_recall":macro_recall,
        "cross_entropy":loss/rows.len().max(1) as f64,"per_class":per_class,"confusions":confusion,"predictions":predictions}),
    )
}

fn fit(samples: &[Sample], features: &[Vec<f32>]) -> Result<(Head, usize, Vec<Value>)> {
    let train: Vec<_> = samples
        .iter()
        .zip(features)
        .filter(|(s, _)| s.split == "train")
        .collect();
    let validation: Vec<_> = samples
        .iter()
        .zip(features)
        .filter(|(s, _)| s.split == "validation")
        .collect();
    let mut labels: Vec<_> = train.iter().map(|(s, _)| s.label.clone()).collect();
    labels.sort();
    labels.dedup();
    let dimensions = features.first().ok_or("empty features")?.len();
    let mut head = Head {
        weights: vec![0.; labels.len() * dimensions],
        biases: vec![0.; labels.len()],
        dimensions,
        labels,
    };
    let mut counts = vec![0usize; head.labels.len()];
    let targets: Vec<_> = train
        .iter()
        .map(|(s, _)| head.labels.binary_search(&s.label).unwrap())
        .collect();
    for &i in &targets {
        counts[i] += 1;
    }
    // Fixed class-balanced full-batch gradient descent; only validation selects
    // an epoch. Test examples never take part in gradient/checkpoint selection.
    let mut best: Option<(f64, f64, usize, Head)> = None;
    let mut history = Vec::new();
    for epoch in 1..=800 {
        let mut dw = vec![0.; head.weights.len()];
        let mut db = vec![0.; head.labels.len()];
        for ((_, x), &target) in train.iter().zip(&targets) {
            let p = head.probabilities(x)?;
            let weight = 1. / (counts[target] * head.labels.len()) as f32;
            for k in 0..head.labels.len() {
                let error = (p[k] - if k == target { 1. } else { 0. }) * weight;
                db[k] += error;
                for (g, value) in dw[k * dimensions..(k + 1) * dimensions].iter_mut().zip(*x) {
                    *g += error * value;
                }
            }
        }
        for (w, g) in head.weights.iter_mut().zip(dw) {
            *w -= 2. * (g + 0.001 * *w);
        }
        for (b, g) in head.biases.iter_mut().zip(db) {
            *b -= 2. * g;
        }
        if [50, 100, 200, 400, 800].contains(&epoch) {
            let m = metrics(&head, &validation)?;
            let score = m["named_macro_recall"].as_f64().ok_or("validation score")?;
            let loss = m["cross_entropy"].as_f64().ok_or("validation loss")?;
            history.push(
                json!({"epoch":epoch,"validation_macro_recall":score,"validation_loss":loss}),
            );
            if best
                .as_ref()
                .is_none_or(|(s, l, _, _)| score > *s || score == *s && loss < *l)
            {
                best = Some((score, loss, epoch, head.clone()));
            }
        }
    }
    let (_, _, epoch, head) = best.ok_or("no selected classifier")?;
    Ok((head, epoch, history))
}

pub fn run_cli() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 || args[1] != "--spec" {
        return Err("use --spec training.json".into());
    }
    let spec_bytes = fs::read(&args[2])?;
    let spec: Value = serde_json::from_slice(&spec_bytes)?;
    let out = PathBuf::from(str_field(&spec, "output")?);
    if out.exists() {
        return Err("new output directory required".into());
    }
    let mut samples = load_samples(
        Path::new(str_field(&spec, "annotations")?),
        Path::new(str_field(&spec, "images")?),
        Path::new(str_field(&spec, "reference")?),
    )?;
    let source_samples = samples.len();
    let augmented = match spec["augmentation"].as_str().unwrap_or("none") {
        "none" => 0,
        "native_domain_v1" => augment_training(&mut samples)?,
        _ => return Err("unknown augmentation policy".into()),
    };
    let encoder_bytes = fs::read(str_field(&spec, "encoder")?)?;
    if hash(&encoder_bytes) != str_field(&spec, "encoder_sha256")? {
        return Err("encoder hash mismatch".into());
    }
    let side = num(&spec, "input_size")? as usize;
    if !(64..=224).contains(&side) {
        return Err("input size budget".into());
    }
    ort::init_from(str_field(&spec, "onnxruntime")?).commit()?;
    let mut session = Session::builder()?
        .with_intra_threads(1)?
        .with_inter_threads(1)?
        .with_intra_op_spinning(false)?
        .with_inter_op_spinning(false)?
        .commit_from_file(str_field(&spec, "encoder")?)?;
    fs::create_dir_all(&out)?;
    let start = Instant::now();
    let mut neural = Vec::new();
    let cache = spec["embedding_cache"].as_str().map(PathBuf::from);
    if let Some(p) = &cache {
        fs::create_dir_all(p)?;
    }
    let mut cache_hits = 0;
    for chunk in samples.chunks(4) {
        let crops: Vec<_> = chunk.iter().map(|s| (s.crop.clone(), true)).collect();
        // Dynamic quantization can depend on the other batch members. Cache
        // the entire ordered batch, not individual pixels under a false key.
        let key = hash(
            format!(
                "rgb-bilinear-imagenet-v1:{}:{side}:{}",
                spec["encoder_sha256"],
                chunk
                    .iter()
                    .map(|s| hash(&s.crop.rgb))
                    .collect::<Vec<_>>()
                    .join(":")
            )
            .as_bytes(),
        );
        let cache_path = cache.as_ref().map(|p| p.join(format!("{key}.json")));
        let features = if let Some(p) = cache_path.as_ref().filter(|p| p.exists()) {
            let value: Value = serde_json::from_slice(&fs::read(p)?)?;
            let vectors: Vec<Vec<f32>> = serde_json::from_value(value["vectors"].clone())?;
            let encoded = serde_json::to_vec(&vectors)?;
            if value["sha256"] != hash(&encoded)
                || vectors.len() != chunk.len()
                || vectors
                    .iter()
                    .any(|v| v.is_empty() || v.iter().any(|x| !x.is_finite()))
            {
                return Err("invalid embedding cache".into());
            }
            cache_hits += 1;
            vectors
        } else {
            let vectors = embeddings(&mut session, &crops, side, false, false)?;
            if let Some(p) = cache_path {
                let sha = hash(&serde_json::to_vec(&vectors)?);
                fs::write(
                    p,
                    serde_json::to_vec(&json!({"sha256":sha,"vectors":vectors}))?,
                )?;
            }
            vectors
        };
        neural.extend(features);
    }
    let color: Vec<_> = samples.iter().map(|s| colors(&s.crop)).collect();
    let combined: Vec<Vec<f32>> = neural
        .iter()
        .zip(&color)
        .map(|(n, c)| {
            let mut v = n.clone();
            v.extend(c);
            normalize(&mut v);
            v
        })
        .collect();
    let mut reports = BTreeMap::new();
    for (name, features) in [
        ("colors", &color),
        ("dino", &neural),
        ("dino_colors", &combined),
    ] {
        if spec["only_dino"] == true && name != "dino" {
            continue;
        }
        let (head, epoch, history) = fit(&samples, features)?;
        let mut evaluation = BTreeMap::new();
        for split in ["train", "validation", "test"] {
            let rows: Vec<_> = samples
                .iter()
                .zip(features)
                .filter(|(s, _)| s.split == split)
                .collect();
            evaluation.insert(split, metrics(&head, &rows)?);
        }
        let model = json!({"schema_version":1,"feature_mode":name,"head":head,"selected_epoch":epoch,
            "encoder_sha256":spec["encoder_sha256"],"annotations_sha256":hash(&fs::read(str_field(&spec,"annotations")?)?),
            "input_size":side,"runtime_approved":false,"probabilities_calibrated":false,"augmentation":spec["augmentation"]});
        let bytes = serde_json::to_vec(&model)?;
        fs::write(out.join(format!("{name}-head.json")), &bytes)?;
        let report = json!({"selected_epoch":epoch,"checkpoints":history,"evaluation":evaluation,
            "artifact_bytes":bytes.len(),"artifact_sha256":hash(&bytes)});
        println!(
            "{}",
            json!({"variant":name,"epoch":epoch,"test_named":report["evaluation"]["test"]["named"],
            "test_correct":report["evaluation"]["test"]["named_top1_correct"]})
        );
        reports.insert(name, report);
    }
    let report = json!({"schema_version":1,"implementation":"rust_native","training_performed":true,
        "backbone_finetuned":false,"training_algorithm":"class_balanced_multiclass_softmax_gradient_descent",
        "learning_rate":2.0,"weight_decay":0.001,"max_epochs":800,"checkpoint_selection":"validation_macro_recall_then_loss",
        "variants":reports,"elapsed_seconds":start.elapsed().as_secs_f64(),"spec_sha256":hash(&spec_bytes),
        "source_samples":source_samples,"synthetic_training_views":augmented,"embedding_cache_hit_batches":cache_hits,
        "encoder_sha256":spec["encoder_sha256"],"runtime_approved":false,
        "limitations":["Existing small assistant-reviewed dataset; no independent human ground truth.",
        "A supervised classification head is trained; frozen DINO weights are unchanged.",
        "Spatial color histograms contain some background; not a segmentation mask.",
        "Softmax scores are uncalibrated; no identity confirmation or coaching activation.",
        "Held-out source separation is enforced; repeated development test use still limits generalization claims.",
        "The new six-hour VOD is not used as training data or automatic labels."]});
    fs::write(out.join("report.json"), serde_json::to_vec_pretty(&report)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn color_histogram_distinguishes_palette_and_position() {
        let red = UnitCrop {
            rgb: [255, 0, 0].repeat(WIDTH * HEIGHT),
        };
        let blue = UnitCrop {
            rgb: [0, 0, 255].repeat(WIDTH * HEIGHT),
        };
        let a = colors(&red);
        let b = colors(&blue);
        assert!(cosine(&a, &b).unwrap().abs() < 1e-6);
        assert!((cosine(&a, &a).unwrap() - 1.).abs() < 1e-6);
        let black = UnitCrop {
            rgb: vec![0; WIDTH * HEIGHT * 3],
        };
        assert!(colors(&black).iter().all(|v| v.is_finite()));
    }
    #[test]
    fn classifier_rejects_invalid_features() {
        let head = Head {
            labels: vec!["a".into(), "b".into()],
            dimensions: 2,
            weights: vec![1., 0., 0., 1.],
            biases: vec![0.; 2],
        };
        assert!(head.probabilities(&[f32::NAN, 1.]).is_err());
        assert!(head.probabilities(&[1.]).is_err());
        let p = head.probabilities(&[1., 0.]).unwrap();
        assert!(p[0] > p[1]);
        assert!((p.iter().sum::<f32>() - 1.).abs() < 1e-6);
    }

    #[test]
    fn augmentation_cannot_modify_validation_or_test() {
        let sample = |split: &str| Sample {
            crop: UnitCrop {
                rgb: [30, 70, 120].repeat(WIDTH * HEIGHT),
            },
            label: "a".into(),
            split: split.into(),
            image: split.into(),
            key: "one".into(),
        };
        let mut samples = vec![sample("train"), sample("validation"), sample("test")];
        let before = samples[1].crop.clone();
        let n = augment_training(&mut samples).unwrap();
        assert!(n >= 3);
        assert_eq!(samples[1].crop, before);
        assert!(samples[3..].iter().all(|s| s.split == "train"));
    }
}
