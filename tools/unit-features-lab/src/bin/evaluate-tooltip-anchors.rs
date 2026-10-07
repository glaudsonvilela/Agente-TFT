//! Measure a frozen visual head on game-derived tooltip labels from held-out sources.
//! No label is allowed back into training and no model weights are changed.
use agente_tft_image_preprocess::unit_features::{normalize, UnitCrop};
use agente_tft_unit_features_lab::{
    crop_transform::CropTransform,
    embedding_batch_size, embeddings,
    training::{colors, Head},
    Result,
};
use ort::session::Session;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashSet},
    fs,
    path::{Path, PathBuf},
    time::Instant,
};

fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn str_field<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key]
        .as_str()
        .ok_or_else(|| format!("missing {key}").into())
}
fn sealed(spec: &Value, key: &str) -> Result<Vec<u8>> {
    let bytes = fs::read(str_field(spec, key)?)?;
    if hash(&bytes) != str_field(spec, &format!("{key}_sha256"))? {
        return Err(format!("{key} checksum mismatch").into());
    }
    Ok(bytes)
}
fn validate_anchor(row: &Value, source: &str) -> Result<()> {
    if row["source_id"] != source
        || row["partition"] != "evaluation_unlabeled"
        || row["training_eligible"] != false
        || row["human_review_required"] != false
        || row["model_prediction_used_as_label"] != false
        || row["label_source"] != "autonomous_tooltip_temporal_consensus_v1"
        || row["evidence"]["exact_catalog_name_ocr"] != true
        || row["evidence"]["temporal_confirmations"]
            .as_u64()
            .unwrap_or(0)
            < 2
    {
        return Err("held-out tooltip anchor provenance mismatch".into());
    }
    Ok(())
}
fn load_crop(root: &Path, row: &Value) -> Result<UnitCrop> {
    let relative = Path::new(str_field(row, "crop")?);
    if relative.is_absolute()
        || relative
            .components()
            .any(|part| matches!(part, std::path::Component::ParentDir))
    {
        return Err("crop path escapes collection".into());
    }
    let rgb = image::open(root.join(relative))?.to_rgb8();
    if (rgb.width(), rgb.height()) != (128, 144) {
        return Err("crop geometry".into());
    }
    let pixels = rgb.into_raw();
    if hash(&pixels) != str_field(row, "pixel_sha256")? {
        return Err("crop pixel hash mismatch".into());
    }
    Ok(UnitCrop { rgb: pixels })
}

fn run() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 || args[1] != "--spec" {
        return Err("use --spec EVALUATION.json".into());
    }
    let spec: Value = serde_json::from_slice(&fs::read(&args[2])?)?;
    let output = PathBuf::from(str_field(&spec, "output")?);
    if output.exists() {
        return Err("new output file required".into());
    }
    let model_bytes = sealed(&spec, "model")?;
    let model: Value = serde_json::from_slice(&model_bytes)?;
    let head: Head = serde_json::from_value(model["head"].clone())?;
    let feature_mode = str_field(&model, "feature_mode")?;
    if !["dino", "colors", "dino_colors"].contains(&feature_mode) {
        return Err("unknown held-out feature mode".into());
    }
    let transform: CropTransform = model
        .get("crop_transform")
        .map(|v| serde_json::from_value(v.clone()))
        .transpose()?
        .unwrap_or_default();
    let batch = embedding_batch_size(model.get("embedding_batch_size"))?;
    let side = model["input_size"].as_u64().ok_or("model input size")? as usize;
    let encoder_bytes = sealed(&spec, "encoder")?;
    if model["encoder_sha256"] != hash(&encoder_bytes) {
        return Err("encoder/model mismatch".into());
    }
    let training_bytes = fs::read(str_field(&spec, "training_annotations")?)?;
    if model["annotations_sha256"] != hash(&training_bytes) {
        return Err("model training manifest mismatch".into());
    }
    let training: Value = serde_json::from_slice(&training_bytes)?;
    let sources = spec["sources"].as_array().ok_or("sources array")?;
    if sources.is_empty() {
        return Err("evaluation sources empty".into());
    }
    let mut crops = Vec::new();
    let mut labels = Vec::new();
    let mut source_names = HashSet::new();
    let mut unique_pixels = HashSet::new();
    for source_spec in sources {
        let root = Path::new(str_field(source_spec, "collection")?);
        let report: Value = serde_json::from_slice(&fs::read(root.join("report.json"))?)?;
        if report["status"] != "complete"
            || report["partition"] != "evaluation_unlabeled"
            || report["collection_mode"] != "annotation_only"
            || report["training_performed"] != false
        {
            return Err("evaluation collection provenance mismatch".into());
        }
        let source_id = str_field(&report, "source_id")?;
        source_names.insert(source_id.to_owned());
        let rows: Value = serde_json::from_slice(&fs::read(str_field(source_spec, "anchors")?)?)?;
        for row in rows.as_array().ok_or("anchor list")? {
            validate_anchor(row, source_id)?;
            let pixel = str_field(row, "pixel_sha256")?.to_owned();
            if !unique_pixels.insert(pixel) {
                continue;
            }
            crops.push((transform.apply(&load_crop(root, row)?)?, true));
            labels.push(str_field(row, "unit_id")?.to_owned());
        }
    }
    if crops.is_empty() {
        return Err("no held-out anchors".into());
    }
    for frame in training["frames"].as_array().ok_or("training frames")? {
        if frame["identity_split"] == "train"
            && frame["source_video_id"]
                .as_str()
                .is_some_and(|id| source_names.contains(id))
        {
            return Err("evaluation source overlaps model training split".into());
        }
    }
    ort::init_from(str_field(&spec, "onnxruntime")?).commit()?;
    let mut session = Session::builder()?
        .with_intra_threads(1)?
        .with_inter_threads(1)?
        .with_intra_op_spinning(false)?
        .with_inter_op_spinning(false)?
        .commit_from_file(str_field(&spec, "encoder")?)?;
    let started = Instant::now();
    let mut neural = Vec::new();
    for group in crops.chunks(batch) {
        neural.extend(embeddings(&mut session, group, side, false, false)?);
    }
    let mut features = Vec::with_capacity(crops.len());
    for ((crop, _), embedding) in crops.iter().zip(neural) {
        let color = colors(crop);
        let feature = match feature_mode {
            "dino" => embedding,
            "colors" => color,
            "dino_colors" => {
                let mut joined = embedding;
                joined.extend(color);
                if !normalize(&mut joined) {
                    return Err("invalid combined feature".into());
                }
                joined
            }
            _ => unreachable!(),
        };
        features.push(feature);
    }
    let mut by_label = BTreeMap::<String, (u64, u64, u64)>::new();
    let mut rows = Vec::new();
    for (truth, feature) in labels.iter().zip(&features) {
        let probabilities = head.probabilities(feature)?;
        let top = probabilities
            .iter()
            .enumerate()
            .max_by(|a, b| a.1.total_cmp(b.1))
            .ok_or("empty head")?
            .0;
        let prediction = &head.labels[top];
        let covered = head.labels.contains(truth);
        let correct = prediction == truth;
        let entry = by_label.entry(truth.clone()).or_default();
        entry.0 += 1;
        entry.1 += u64::from(covered);
        entry.2 += u64::from(correct);
        rows.push(
            json!({"truth":truth,"prediction":prediction,"covered":covered,"correct":correct,
            "top_probability_uncalibrated":probabilities[top]}),
        );
    }
    let summary = json!({"schema_version":1,"evaluation_partition":"evaluation_unlabeled",
        "source_ids":source_names,"anchors":labels.len(),"covered_anchors":rows.iter().filter(|r|r["covered"]==true).count(),
        "top1_correct":rows.iter().filter(|r|r["correct"]==true).count(),"by_label":by_label,"rows":rows,
        "model_sha256":hash(&model_bytes),"encoder_sha256":hash(&encoder_bytes),"feature_mode":feature_mode,
        "training_performed":false,"runtime_approved":false,"inference_seconds":started.elapsed().as_secs_f64(),
        "limitations":["Tooltip selection samples are sparse and correlated; these counts are not live-game accuracy.",
        "This source may have influenced prior model selection even though it was excluded from the training split."]});
    fs::write(&output, serde_json::to_vec_pretty(&summary)?)?;
    println!(
        "{}",
        json!({"anchors":labels.len(),"top1_correct":summary["top1_correct"],"training_performed":false})
    );
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("TOOLTIP_EVALUATION_ERROR: {error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn evaluation_anchor_can_never_be_training_eligible() {
        let mut row = json!({"source_id":"vod-eval","partition":"evaluation_unlabeled",
            "training_eligible":false,"human_review_required":false,"model_prediction_used_as_label":false,
            "label_source":"autonomous_tooltip_temporal_consensus_v1",
            "evidence":{"exact_catalog_name_ocr":true,"temporal_confirmations":2}});
        assert!(validate_anchor(&row, "vod-eval").is_ok());
        row["training_eligible"] = json!(true);
        assert!(validate_anchor(&row, "vod-eval").is_err());
    }
}
