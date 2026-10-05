//! Prioritize an annotation-only collection with a frozen classifier.
//!
//! Predictions are review hints only. This binary never writes labels or trains.
use agente_tft_image_preprocess::unit_features::UnitCrop;
use agente_tft_unit_features_lab::{
    crop_transform::CropTransform, embedding_batch_size, embeddings,
    training::Head, Result,
};
use ort::session::Session;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    fs,
    path::{Path, PathBuf},
    time::Instant,
};

fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn string<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key]
        .as_str()
        .ok_or_else(|| format!("missing {key}").into())
}
fn read_sealed(spec: &Value, key: &str) -> Result<Vec<u8>> {
    let bytes = fs::read(string(spec, key)?)?;
    if hash(&bytes) != string(spec, &format!("{key}_sha256"))? {
        return Err(format!("{key} checksum mismatch").into());
    }
    Ok(bytes)
}
fn percentile(values: &[f64], p: f64) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let mut v = values.to_vec();
    v.sort_by(f64::total_cmp);
    v[((v.len() - 1) as f64 * p).round() as usize]
}

#[derive(Clone)]
struct CropRecord {
    source_seconds: u64,
    crop_path: PathBuf,
    crop_relative: String,
    pixel_sha256: String,
    box_value: Value,
    review_frame: Option<String>,
}

fn load_crop(path: &Path, expected_pixel_sha256: &str) -> Result<UnitCrop> {
    let rgb = image::open(path)?.to_rgb8();
    if rgb.width() != 128 || rgb.height() != 144 {
        return Err("annotation crop must be 128x144".into());
    }
    let raw = rgb.into_raw();
    if hash(&raw) != expected_pixel_sha256 {
        return Err("annotation crop pixel checksum mismatch".into());
    }
    Ok(UnitCrop { rgb: raw })
}

fn evenly_sample<T: Clone>(rows: &[T], limit: usize) -> Vec<T> {
    if rows.len() <= limit {
        return rows.to_vec();
    }
    if limit <= 1 {
        return vec![rows[0].clone()];
    }
    let mut positions = HashSet::new();
    for i in 0..limit {
        positions.insert(((i * (rows.len() - 1)) as f64 / (limit - 1) as f64).round() as usize);
    }
    let mut p: Vec<_> = positions.into_iter().collect();
    p.sort_unstable();
    p.into_iter().map(|i| rows[i].clone()).collect()
}

fn run() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 || args[1] != "--spec" {
        return Err("use --spec PRIORITIZE.json".into());
    }
    let spec_bytes = fs::read(&args[2])?;
    let spec: Value = serde_json::from_slice(&spec_bytes)?;
    let root = PathBuf::from(string(&spec, "collection")?);
    let out = PathBuf::from(string(&spec, "output")?);
    if out.exists() {
        return Err("new output directory required".into());
    }

    let report: Value = serde_json::from_slice(&fs::read(root.join("report.json"))?)?;
    if report["status"] != "complete"
        || report["collection_mode"] != "annotation_only"
        || report["inference_performed"] != false
        || report["training_performed"] != false
    {
        return Err("collection must be complete annotation_only with no prior inference/training".into());
    }

    let model_bytes = read_sealed(&spec, "model")?;
    let model: Value = serde_json::from_slice(&model_bytes)?;
    if model["feature_mode"] != "dino" || model["runtime_approved"] != false {
        return Err("frozen dino candidate expected".into());
    }
    let head: Head = serde_json::from_value(model["head"].clone())?;
    let transform: CropTransform = model
        .get("crop_transform")
        .map(|v| serde_json::from_value(v.clone()))
        .transpose()?
        .unwrap_or_default();
    let batch = embedding_batch_size(model.get("embedding_batch_size"))?;
    let side = model["input_size"].as_u64().ok_or("model input_size")? as usize;
    if !(64..=224).contains(&side) {
        return Err("model input size budget".into());
    }

    let encoder_bytes = read_sealed(&spec, "encoder")?;
    if model["encoder_sha256"] != hash(&encoder_bytes) {
        return Err("encoder/model mismatch".into());
    }
    ort::init_from(string(&spec, "onnxruntime")?).commit()?;
    let mut session = Session::builder()?
        .with_intra_threads(1)?
        .with_inter_threads(1)?
        .with_intra_op_spinning(false)?
        .with_inter_op_spinning(false)?
        .commit_from_file(string(&spec, "encoder")?)?;

    let target_ids: Vec<String> = serde_json::from_value(spec["target_ids"].clone())?;
    if target_ids.is_empty() {
        return Err("target_ids required".into());
    }
    let targets: HashSet<_> = target_ids.iter().cloned().collect();
    let per_target_limit = spec["per_target_limit"].as_u64().unwrap_or(20) as usize;
    let time_bucket = spec["time_bucket_seconds"].as_u64().unwrap_or(10).max(1);
    let context_limit = spec["context_limit"].as_u64().unwrap_or(30) as usize;
    if !(1..=100).contains(&per_target_limit) || !(1..=120).contains(&context_limit) {
        return Err("review queue budget".into());
    }

    let mut crops = Vec::new();
    let mut review_context = Vec::new();
    let observations = fs::read_to_string(root.join("observations.jsonl"))?;
    for line in observations.lines() {
        if line.trim().is_empty() {
            continue;
        }
        let frame: Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        let source_seconds = frame["source_seconds_nominal"].as_u64().ok_or("source seconds")?;
        let review_frame = frame["review_frame"].as_str().map(str::to_owned);
        if let Some(relative) = review_frame.as_ref() {
            let path = root.join(relative);
            if path.is_file() {
                review_context.push(json!({
                    "source_seconds_nominal": source_seconds,
                    "frame_path": path,
                    "frame_relative": relative,
                    "unit_proposals": frame["units"].as_array().map(|v|v.len()).unwrap_or(0),
                    "training_label": null,
                    "review_required": true
                }));
            }
        }
        for u in frame["units"].as_array().ok_or("units")? {
            let relative = u["crop"].as_str().ok_or("crop")?.to_owned();
            let pixel_sha256 = u["pixel_sha256"].as_str().ok_or("pixel hash")?.to_owned();
            let path = root.join(&relative);
            if !path.is_file() {
                return Err("collection crop missing".into());
            }
            crops.push(CropRecord {
                source_seconds,
                crop_path: path,
                crop_relative: relative,
                pixel_sha256,
                box_value: u["box"].clone(),
                review_frame: review_frame.clone(),
            });
        }
    }
    if crops.is_empty() {
        return Err("empty collection crops".into());
    }

    let start = Instant::now();
    let mut inference_ms = Vec::new();
    let mut top1_counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut target_candidates: HashMap<String, Vec<Value>> = HashMap::new();

    for chunk in crops.chunks(batch) {
        let mut prepared = Vec::with_capacity(chunk.len());
        for row in chunk {
            let crop = load_crop(&row.crop_path, &row.pixel_sha256)?;
            prepared.push((transform.apply(&crop)?, true));
        }
        let encode_start = Instant::now();
        let features = embeddings(&mut session, &prepared, side, false, false)?;
        inference_ms.push(encode_start.elapsed().as_secs_f64() * 1000.0);

        for (row, feature) in chunk.iter().zip(features) {
            let p = head.probabilities(&feature)?;
            let mut order: Vec<_> = (0..p.len()).collect();
            order.sort_by(|&a, &b| p[b].total_cmp(&p[a]).then(a.cmp(&b)));
            let top1 = head.labels[order[0]].clone();
            *top1_counts.entry(top1.clone()).or_default() += 1;

            let top3: Vec<_> = order
                .iter()
                .take(3)
                .map(|&i| json!({"unit_id":head.labels[i],"probability_uncalibrated":p[i]}))
                .collect();
            for (rank, &idx) in order.iter().take(3).enumerate() {
                let target = &head.labels[idx];
                if !targets.contains(target) {
                    continue;
                }
                let margin_to_next = if rank + 1 < order.len() {
                    p[idx] - p[order[rank + 1]]
                } else {
                    p[idx]
                };
                target_candidates.entry(target.clone()).or_default().push(json!({
                    "target_id_suggestion": target,
                    "target_rank": rank + 1,
                    "target_probability_uncalibrated": p[idx],
                    "rank_margin_uncalibrated": margin_to_next,
                    "top3": top3,
                    "source_seconds_nominal": row.source_seconds,
                    "time_bucket": row.source_seconds / time_bucket,
                    "crop_path": row.crop_path,
                    "crop_relative": row.crop_relative,
                    "pixel_sha256": row.pixel_sha256,
                    "box": row.box_value,
                    "review_frame_relative": row.review_frame,
                    "training_label": null,
                    "identity_reviewed": false,
                    "model_prediction_used_as_label": false,
                    "training_eligible": false,
                    "review_required": true
                }));
            }
        }
    }

    let mut queue = Vec::new();
    let mut per_target_summary = BTreeMap::new();
    for target in &target_ids {
        let mut rows = target_candidates.remove(target).unwrap_or_default();
        // One best candidate per temporal bucket first, to reduce near-duplicates.
        let mut per_bucket: HashMap<u64, Value> = HashMap::new();
        for row in rows.drain(..) {
            let bucket = row["time_bucket"].as_u64().unwrap_or(0);
            let score = row["target_probability_uncalibrated"].as_f64().unwrap_or(0.0);
            let rank = row["target_rank"].as_u64().unwrap_or(99);
            let replace = per_bucket.get(&bucket).is_none_or(|old| {
                let old_rank = old["target_rank"].as_u64().unwrap_or(99);
                let old_score = old["target_probability_uncalibrated"].as_f64().unwrap_or(0.0);
                rank < old_rank || (rank == old_rank && score > old_score)
            });
            if replace {
                per_bucket.insert(bucket, row);
            }
        }
        let mut diverse: Vec<_> = per_bucket.into_values().collect();
        diverse.sort_by(|a, b| {
            a["target_rank"]
                .as_u64()
                .unwrap_or(99)
                .cmp(&b["target_rank"].as_u64().unwrap_or(99))
                .then_with(|| {
                    b["target_probability_uncalibrated"]
                        .as_f64()
                        .unwrap_or(0.0)
                        .total_cmp(&a["target_probability_uncalibrated"].as_f64().unwrap_or(0.0))
                })
        });
        let before = diverse.len();
        diverse.truncate(per_target_limit);
        per_target_summary.insert(
            target.clone(),
            json!({"diverse_temporal_candidates":before,"queued":diverse.len()}),
        );
        queue.extend(diverse);
    }
    queue.sort_by(|a, b| {
        a["target_id_suggestion"]
            .as_str()
            .unwrap_or("")
            .cmp(b["target_id_suggestion"].as_str().unwrap_or(""))
            .then_with(|| {
                a["target_rank"]
                    .as_u64()
                    .unwrap_or(99)
                    .cmp(&b["target_rank"].as_u64().unwrap_or(99))
            })
            .then_with(|| {
                b["target_probability_uncalibrated"]
                    .as_f64()
                    .unwrap_or(0.0)
                    .total_cmp(&a["target_probability_uncalibrated"].as_f64().unwrap_or(0.0))
            })
    });
    for (i, row) in queue.iter_mut().enumerate() {
        row["review_number"] = json!(i + 1);
    }

    // Topic-driven fallback: sample later review frames even if the weak current
    // classifier never ranks Elder Dragon in its top 3.
    review_context.sort_by_key(|r| r["source_seconds_nominal"].as_u64().unwrap_or(0));
    let max_second = review_context
        .last()
        .and_then(|r| r["source_seconds_nominal"].as_u64())
        .unwrap_or(0);
    let late_start = (max_second as f64 * 0.55).round() as u64;
    let late: Vec<_> = review_context
        .into_iter()
        .filter(|r| r["source_seconds_nominal"].as_u64().unwrap_or(0) >= late_start)
        .collect();
    let context = evenly_sample(&late, context_limit);

    fs::create_dir_all(&out)?;
    fs::write(out.join("queue.json"), serde_json::to_vec_pretty(&queue)?)?;
    fs::write(out.join("context.json"), serde_json::to_vec_pretty(&context)?)?;
    let contact: Vec<_> = queue
        .iter()
        .map(|r| {
            json!({
                "path": r["crop_path"],
                "crop_transform": transform,
                "review_number": r["review_number"],
                "target_id_suggestion": r["target_id_suggestion"],
                "target_rank": r["target_rank"],
                "model_prediction_used_as_label": false,
                "training_eligible": false
            })
        })
        .collect();
    fs::write(
        out.join("contact-sheet-input.json"),
        serde_json::to_vec_pretty(&contact)?,
    )?;

    let result = json!({
        "schema_version":1,
        "source_id":report["source_id"],
        "source_url":report["source_url"],
        "collection_mode":report["collection_mode"],
        "collection_frames":report["frames"],
        "collection_unit_crops":crops.len(),
        "frozen_model_sha256":hash(&model_bytes),
        "encoder_sha256":hash(&encoder_bytes),
        "crop_transform":transform.name(),
        "embedding_batch_size":batch,
        "target_ids":target_ids,
        "per_target":per_target_summary,
        "queued_candidates":queue.len(),
        "late_context_frames":context.len(),
        "top1_distribution":top1_counts,
        "elapsed_seconds":start.elapsed().as_secs_f64(),
        "embedding_batch_ms_p50":percentile(&inference_ms,0.5),
        "embedding_batch_ms_p95":percentile(&inference_ms,0.95),
        "training_performed":false,
        "automatic_labels":false,
        "runtime_approved":false,
        "limitations":[
            "Frozen model outputs are uncalibrated review suggestions, never identity labels.",
            "Top-3 prioritization is biased toward classes already known to the model.",
            "Late-game context is included so Elder Dragon can be found even if the current model misses it.",
            "No accuracy is claimed until crops are visually reviewed against source context."
        ]
    });
    fs::write(out.join("report.json"), serde_json::to_vec_pretty(&result)?)?;
    println!("{result}");
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("ANNOTATION_PRIORITIZE_ERROR: {error}");
        std::process::exit(1);
    }
}
