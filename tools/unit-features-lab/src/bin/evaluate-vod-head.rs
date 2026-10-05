//! Reuse the expensive frozen embeddings; evaluate a supervised head and emit
//! a diverse disagreement queue. Unreviewed predictions never become labels.
use agente_tft_unit_features_lab::training::Head;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashSet},
    fs,
    path::PathBuf,
    time::Instant,
};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn run() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 5 {
        return Err(
            "use COLLECTION_DIRECTORY DINO_HEAD_JSON AUDIT_JSON OUTPUT_NEW_DIRECTORY".into(),
        );
    }
    let root = PathBuf::from(&args[1]);
    let out = PathBuf::from(&args[4]);
    if out.exists() {
        return Err("new output directory required".into());
    }
    let report: Value = serde_json::from_slice(&fs::read(root.join("report.json"))?)?;
    let model_bytes = fs::read(&args[2])?;
    let model: Value = serde_json::from_slice(&model_bytes)?;
    if report["status"] != "complete"
        || model["feature_mode"] != "dino"
        || model["encoder_sha256"] != report["encoder_sha256"]
        || model["crop_transform"].as_str().unwrap_or("raw") != "raw"
    {
        return Err("incomplete collection or incompatible encoder/head".into());
    }
    let head: Head = serde_json::from_value(model["head"].clone())?;
    let raw = fs::read(root.join("embeddings.f32le"))?;
    let digest = format!("{:x}", Sha256::digest(&raw));
    if report["embeddings_sha256"] != digest
        || report["embedding_dimensions"] != head.dimensions
        || raw.len()
            != report["embedding_rows"].as_u64().ok_or("rows")? as usize * head.dimensions * 4
    {
        return Err("feature cache integrity/shape mismatch".into());
    }
    let audit: Value = serde_json::from_slice(&fs::read(&args[3])?)?;
    if audit["source_id"] != report["source_id"]
        || audit["model_predictions_used_as_labels"] != false
    {
        return Err("audit provenance mismatch".into());
    }
    let mut truths = BTreeMap::new();
    for r in audit["labels"].as_array().ok_or("audit labels")? {
        let sha = r["pixel_sha256"].as_str().ok_or("audit hash")?;
        let id = r["unit_id"].as_str().ok_or("audit identity")?;
        if truths.insert(sha, id).is_some() {
            return Err("duplicate audit crop".into());
        }
    }
    let mut seen = HashSet::new();
    let mut slots = HashSet::new();
    let mut queue = Vec::new();
    let mut evaluated = Vec::new();
    let mut counts = BTreeMap::<String, (usize, usize, usize)>::new();
    let mut total = 0usize;
    let mut disagreements = 0usize;
    let mut inference_ms = 0.;
    for line in fs::read_to_string(root.join("observations.jsonl"))?.lines() {
        let frame: Value = serde_json::from_str(line)?;
        for u in frame["units"].as_array().ok_or("units")? {
            let index = u["embedding_row"].as_u64().ok_or("embedding row")? as usize;
            let offset = index
                .checked_mul(head.dimensions * 4)
                .ok_or("offset overflow")?;
            let bytes = raw
                .get(offset..offset + head.dimensions * 4)
                .ok_or("embedding bounds")?;
            let vector: Vec<f32> = bytes
                .chunks_exact(4)
                .map(|b| f32::from_le_bytes(b.try_into().unwrap()))
                .collect();
            let start = Instant::now();
            let p = head.probabilities(&vector)?;
            inference_ms += start.elapsed().as_secs_f64() * 1000.;
            let mut order: Vec<_> = (0..p.len()).collect();
            order.sort_by(|&a, &b| p[b].total_cmp(&p[a]).then(a.cmp(&b)));
            let predicted = &head.labels[order[0]];
            let old = u["candidates"][0]["unit_id"]
                .as_str()
                .unwrap_or("__unknown__");
            let sha = u["pixel_sha256"].as_str().ok_or("pixel hash")?;
            let different = predicted != old;
            total += 1;
            disagreements += usize::from(different);
            if let Some(truth) = truths.get(sha) {
                if seen.insert(sha.to_owned()) {
                    let c = counts.entry((*truth).to_owned()).or_default();
                    c.0 += 1;
                    c.1 += usize::from(*truth == predicted);
                    c.2 += usize::from(*truth == old);
                    evaluated.push(json!({"pixel_sha256":sha,"label":truth,"classifier":predicted,"nearest_gallery":old,
                        "source_seconds_nominal":frame["source_seconds_nominal"],"crop":u["crop"]}));
                }
            }
            let minute = frame["source_seconds_nominal"]
                .as_u64()
                .ok_or("timestamp")?
                / 60;
            if different && slots.insert((predicted.clone(), minute)) && queue.len() < 1000 {
                queue.push(json!({"source_id":frame["source_id"],"source_seconds_nominal":frame["source_seconds_nominal"],
                    "crop":u["crop"],"box":u["box"],"pixel_sha256":sha,"classifier_candidate":predicted,"gallery_candidate":old,
                    "uncalibrated_softmax":p[order[0]],"margin":p[order[0]]-p[order[1]],"training_label":null,
                    "review_required":true}));
            }
        }
    }
    if seen.len() != truths.len() {
        return Err("audit contains crops absent from collection".into());
    }
    fs::create_dir_all(&out)?;
    let result = json!({"schema_version":1,"source_id":report["source_id"],"frames":report["frames"],"unit_crops":total,
        "disagreements":disagreements,"review_queue":queue.len(),"reviewed_unique_crops":seen.len(),"per_class_counts_total_head_gallery":counts,
        "head_correct":counts.values().map(|x|x.1).sum::<usize>(),"gallery_correct":counts.values().map(|x|x.2).sum::<usize>(),
        "head_inference_total_ms":inference_ms,"head_inference_mean_ms":inference_ms/total.max(1) as f64,
        "timing_excludes_encoder_capture_and_decode":true,"runtime_approved":false,"head_sha256":format!("{:x}",Sha256::digest(&model_bytes)),
        "audit":evaluated,"limitations":["Assistant visual audit is not independent human ground truth.",
        "Audit metrics apply only to reviewed crops, not all VOD crops.","The queue favors disagreement and is not a random accuracy sample.",
        "Uncalibrated classifier outputs are candidates; no coaching activation."]});
    fs::write(out.join("report.json"), serde_json::to_vec_pretty(&result)?)?;
    fs::write(
        out.join("review-queue.json"),
        serde_json::to_vec_pretty(&queue)?,
    )?;
    println!("{}", result);
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("VOD_HEAD_EVALUATION_ERROR: {e}");
        std::process::exit(1);
    }
}
