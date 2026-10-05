//! Evaluate a sealed, frozen head on reviewed images without fitting any weights.
use agente_tft_unit_features_lab::{
    crop_transform::CropTransform,
    embedding_batch_size, embeddings, load_evaluation_samples,
    retrieval::RetrievalHead,
    training::{metrics_with_predictor, Head},
    Result, Sample,
};

enum FrozenHead {
    Linear(Head),
    Retrieval(RetrievalHead),
}

fn metrics(head: &FrozenHead, rows: &[(&Sample, &Vec<f32>)]) -> Result<Value> {
    match head {
        FrozenHead::Linear(h) => metrics_with_predictor(&h.labels, rows, |x| h.probabilities(x)),
        FrozenHead::Retrieval(h) => {
            metrics_with_predictor(h.labels(), rows, |x| h.probabilities(x))
        }
    }
}
use ort::session::Session;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashSet},
    fs,
    path::Path,
    time::Instant,
};

fn string<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key]
        .as_str()
        .ok_or_else(|| format!("missing {key}").into())
}
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn sealed(spec: &Value, key: &str) -> Result<Vec<u8>> {
    let data = fs::read(string(spec, key)?)?;
    if hash(&data) != string(spec, &format!("{key}_sha256"))? {
        return Err(format!("{key} checksum mismatch").into());
    }
    Ok(data)
}
fn source_tokens(frame: &Value) -> HashSet<String> {
    [
        "source_video_id",
        "match_group",
        "session_id",
        "pixel_sha256",
    ]
    .iter()
    .filter_map(|key| frame[key].as_str().map(|v| format!("{key}:{v}")))
    .collect()
}
fn verify_isolation(training: &Value, evaluation: &Value) -> Result<bool> {
    let mut train = HashSet::new();
    let mut all = HashSet::new();
    for f in training["frames"].as_array().ok_or("training frames")? {
        let tokens = source_tokens(f);
        if f["identity_split"] == "train" {
            train.extend(tokens.iter().cloned());
        }
        all.extend(tokens);
    }
    let mut previously_seen = false;
    for f in evaluation["frames"].as_array().ok_or("evaluation frames")? {
        if f["identity_split"] != "test" {
            return Err("evaluation-only test frames required".into());
        }
        let tokens = source_tokens(f);
        if !train.is_disjoint(&tokens) {
            return Err("evaluation overlaps classifier training source/match/pixels".into());
        }
        previously_seen |= !all.is_disjoint(&tokens);
    }
    Ok(!previously_seen)
}
fn run() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 || args[1] != "--spec" {
        return Err("use --spec EVALUATION_JSON".into());
    }
    let spec_bytes = fs::read(&args[2])?;
    let spec: Value = serde_json::from_slice(&spec_bytes)?;
    let output = Path::new(string(&spec, "output")?);
    if output.exists() {
        return Err("new report required".into());
    }
    let model_bytes = sealed(&spec, "model")?;
    let model: Value = serde_json::from_slice(&model_bytes)?;
    let training_bytes = fs::read(string(&spec, "training_annotations")?)?;
    if model["annotations_sha256"] != hash(&training_bytes) || model["feature_mode"] != "dino" {
        return Err("training manifest or classifier feature mode mismatch".into());
    }
    let training: Value = serde_json::from_slice(&training_bytes)?;
    let annotations_bytes = fs::read(string(&spec, "annotations")?)?;
    let annotation: Value = serde_json::from_slice(&annotations_bytes)?;
    let new_source = verify_isolation(&training, &annotation)?;
    let mut samples = load_evaluation_samples(
        Path::new(string(&spec, "annotations")?),
        Path::new(string(&spec, "images")?),
        Path::new(string(&spec, "reference")?),
    )?;
    if samples.is_empty() {
        return Err("empty evaluation".into());
    }
    let transform: CropTransform = model
        .get("crop_transform")
        .map(|v| serde_json::from_value(v.clone()))
        .transpose()?
        .unwrap_or_default();
    for sample in &mut samples {
        sample.crop = transform.apply(&sample.crop)?;
    }
    let encoder_bytes = sealed(&spec, "encoder")?;
    if model["encoder_sha256"] != hash(&encoder_bytes) {
        return Err("encoder/model mismatch".into());
    }
    let side = model["input_size"].as_u64().ok_or("input size")? as usize;
    if !(64..=224).contains(&side) {
        return Err("input size budget".into());
    }
    let head = match model["classifier_type"].as_str().unwrap_or("linear") {
        "linear" => FrozenHead::Linear(serde_json::from_value(model["head"].clone())?),
        "retrieval_v1" => {
            FrozenHead::Retrieval(RetrievalHead::from_value(model["retrieval"].clone())?)
        }
        _ => return Err("unsupported frozen classifier type".into()),
    };
    let trained_batch = embedding_batch_size(model.get("embedding_batch_size"))?;
    let batch = match spec.get("batch_size") {
        Some(v) => embedding_batch_size(Some(v))?,
        None => trained_batch,
    };
    ort::init_from(string(&spec, "onnxruntime")?).commit()?;
    let mut session = Session::builder()?
        .with_intra_threads(1)?
        .with_inter_threads(1)?
        .with_intra_op_spinning(false)?
        .with_inter_op_spinning(false)?
        .commit_from_file(string(&spec, "encoder")?)?;
    let start = Instant::now();
    let mut features = Vec::new();
    for chunk in samples.chunks(batch) {
        let crops: Vec<_> = chunk.iter().map(|s| (s.crop.clone(), true)).collect();
        features.extend(embeddings(&mut session, &crops, side, false, false)?);
    }
    let rows: Vec<_> = samples.iter().zip(&features).collect();
    let result = metrics(&head, &rows)?;
    let mut conditions: BTreeMap<String, Vec<usize>> = BTreeMap::new();
    for (i, sample) in samples.iter().enumerate() {
        let frame = annotation["frames"]
            .as_array()
            .unwrap()
            .iter()
            .find(|f| f["image"] == sample.image)
            .ok_or("frame binding")?;
        let entity = frame["entities"]
            .as_array()
            .unwrap()
            .iter()
            .find(|e| e["key"] == sample.key);
        let form = entity
            .and_then(|e| e["appearance_state"].as_str())
            .unwrap_or("unspecified");
        let framing = frame["framing"].as_str().unwrap_or("unspecified");
        conditions
            .entry(format!("appearance:{form}"))
            .or_default()
            .push(i);
        conditions
            .entry(format!("framing:{framing}"))
            .or_default()
            .push(i);
    }
    let mut strata = BTreeMap::new();
    for (condition, indices) in conditions {
        let subset: Vec<_> = indices
            .iter()
            .map(|&i| (&samples[i], &features[i]))
            .collect();
        strata.insert(condition, metrics(&head, &subset)?);
    }
    let report = json!({"schema_version":1,"training_performed":false,"head_sha256":hash(&model_bytes),
        "annotations_sha256":hash(&annotations_bytes),"spec_sha256":hash(&spec_bytes),"encoder_sha256":hash(&encoder_bytes),
        "crop_transform":transform.name(),"batch":batch,"training_batch":trained_batch,
        "batch_matches_training":batch==trained_batch,"threads":1,"new_source_relative_to_training_manifest":new_source,
        "evaluation":result,"strata":strata,"inference_seconds":start.elapsed().as_secs_f64(),"runtime_approved":false,
        "limitations":["Assistant-reviewed labels, not independent human ground truth.","Legible proposed crops only; missed or ambiguous units are not recognition successes.","No Windows capture/display or end-to-end latency measurement.","After inspection this source is development evidence, not an untouched final holdout."]});
    fs::write(output, serde_json::to_vec_pretty(&report)?)?;
    println!(
        "{}",
        json!({"named":result["named"],"correct":result["named_top1_correct"],"training_performed":false})
    );
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("CLASSIFIER_EVALUATION_ERROR: {e}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_source_leakage_even_when_match_name_changes() {
        let train = json!({"frames":[{"identity_split":"train","source_video_id":"a","match_group":"one"}]});
        let leaking =
            json!({"frames":[{"identity_split":"test","source_video_id":"a","match_group":"two"}]});
        assert!(verify_isolation(&train, &leaking).is_err());
        let clean = json!({"frames":[{"identity_split":"test","source_video_id":"b","match_group":"three"}]});
        assert!(verify_isolation(&train, &clean).unwrap());
    }
    #[test]
    fn rejects_copied_pixels_from_another_source() {
        let train = json!({"frames":[{"identity_split":"train","source_video_id":"a","pixel_sha256":"same"}]});
        let leaking = json!({"frames":[{"identity_split":"test","source_video_id":"b","pixel_sha256":"same"}]});
        assert!(verify_isolation(&train, &leaking).is_err());
    }
}
