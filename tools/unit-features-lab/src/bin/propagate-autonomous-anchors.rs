//! Conservative propagation from autonomous gold anchors.
//!
//! Gold labels come from game-derived shop/purchase evidence. This tool may
//! emit silver_auto labels only when three signals agree:
//!   1. high DINO cosine similarity to a gold anchor of the same class;
//!   2. frozen classifier predicts the same class with positive margin;
//!   3. the crop is temporally near that class's gold anchor.
//! It never upgrades silver labels to gold and never trains weights.

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

fn s<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key].as_str().ok_or_else(|| format!("missing {key}").into())
}

fn read_sealed(spec: &Value, key: &str) -> Result<Vec<u8>> {
    let bytes = fs::read(s(spec, key)?)?;
    if hash(&bytes) != s(spec, &format!("{key}_sha256"))? {
        return Err(format!("{key} checksum mismatch").into());
    }
    Ok(bytes)
}

fn load_crop(path: &Path, expected_pixel_sha256: &str) -> Result<UnitCrop> {
    let rgb = image::open(path)?.to_rgb8();
    if (rgb.width(), rgb.height()) != (128, 144) {
        return Err("crop geometry must be 128x144".into());
    }
    let raw = rgb.into_raw();
    if hash(&raw) != expected_pixel_sha256 {
        return Err("crop pixel SHA-256 mismatch".into());
    }
    Ok(UnitCrop { rgb: raw })
}

fn cosine(a: &[f32], b: &[f32]) -> Result<f32> {
    if a.len() != b.len() || a.is_empty() {
        return Err("embedding dimension mismatch".into());
    }
    let mut dot = 0f64;
    let mut aa = 0f64;
    let mut bb = 0f64;
    for (&x, &y) in a.iter().zip(b) {
        if !x.is_finite() || !y.is_finite() {
            return Err("nonfinite embedding".into());
        }
        dot += x as f64 * y as f64;
        aa += (x as f64).powi(2);
        bb += (y as f64).powi(2);
    }
    if aa <= 1e-12 || bb <= 1e-12 {
        return Err("zero embedding".into());
    }
    Ok((dot / (aa.sqrt() * bb.sqrt())) as f32)
}

fn center(boxv: &Value) -> Result<(f32, f32)> {
    let a = boxv.as_array().ok_or("box array")?;
    if a.len() != 4 {
        return Err("box size".into());
    }
    let mut n = [0f32; 4];
    for (i, v) in a.iter().enumerate() {
        n[i] = v.as_f64().ok_or("box number")? as f32;
    }
    Ok(((n[0] + n[2]) * 0.5, (n[1] + n[3]) * 0.5))
}

#[derive(Clone)]
struct Record {
    time: u64,
    crop: String,
    path: PathBuf,
    pixel: String,
    boxv: Value,
}

#[derive(Clone)]
struct Anchor {
    label: String,
    time: u64,
    pixel: String,
    crop: String,
    feature: Vec<f32>,
    center: (f32, f32),
}

fn run() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 || args[1] != "--spec" {
        return Err("use --spec PROPAGATE.json".into());
    }
    let spec: Value = serde_json::from_slice(&fs::read(&args[2])?)?;
    let root = PathBuf::from(s(&spec, "collection")?);
    let out = PathBuf::from(s(&spec, "output")?);
    if out.exists() {
        return Err("new output directory required".into());
    }

    let report: Value = serde_json::from_slice(&fs::read(root.join("report.json"))?)?;
    if report["status"] != "complete"
        || report["collection_mode"] != "annotation_only"
        || report["training_performed"] != false
        || report["inference_performed"] != false
    {
        return Err("complete annotation_only collection required".into());
    }

    let anchors_doc: Value = serde_json::from_slice(&fs::read(s(&spec, "anchors")?)?)?;
    let anchors_rows = anchors_doc.as_array().ok_or("anchors must be a JSON array")?;
    if anchors_rows.is_empty() {
        return Err("at least one gold anchor required".into());
    }

    let model_bytes = read_sealed(&spec, "model")?;
    let model: Value = serde_json::from_slice(&model_bytes)?;
    if model["feature_mode"] != "dino" || model["runtime_approved"] != false {
        return Err("frozen non-runtime DINO model required".into());
    }
    let head: Head = serde_json::from_value(model["head"].clone())?;
    let transform: CropTransform = model
        .get("crop_transform")
        .map(|v| serde_json::from_value(v.clone()))
        .transpose()?
        .unwrap_or_default();
    let batch = embedding_batch_size(model.get("embedding_batch_size"))?;
    let side = model["input_size"].as_u64().ok_or("model input_size")? as usize;

    let encoder_bytes = read_sealed(&spec, "encoder")?;
    if model["encoder_sha256"] != hash(&encoder_bytes) {
        return Err("encoder/model mismatch".into());
    }

    let max_time_delta = spec["max_time_delta_seconds"].as_u64().unwrap_or(180);
    let min_anchor_similarity = spec["min_anchor_similarity"].as_f64().unwrap_or(0.94) as f32;
    let min_anchor_margin = spec["min_anchor_margin"].as_f64().unwrap_or(0.05) as f32;
    let min_classifier_margin = spec["min_classifier_margin"].as_f64().unwrap_or(0.01) as f32;
    let per_label_limit = spec["per_label_limit"].as_u64().unwrap_or(32) as usize;
    let bucket_seconds = spec["bucket_seconds"].as_u64().unwrap_or(4).max(1);
    let max_anchor_screen_distance = spec["max_anchor_screen_distance_px"].as_f64().unwrap_or(900.0) as f32;
    if !(30..=600).contains(&max_time_delta)
        || !(0.80..=0.9999).contains(&min_anchor_similarity)
        || !(0.0..=0.30).contains(&min_anchor_margin)
        || !(0.0..=0.30).contains(&min_classifier_margin)
        || !(1..=200).contains(&per_label_limit)
        || !(100.0..=2000.0).contains(&max_anchor_screen_distance)
    {
        return Err("invalid propagation thresholds".into());
    }

    ort::init_from(s(&spec, "onnxruntime")?).commit()?;
    let mut session = Session::builder()?
        .with_intra_threads(1)?
        .with_inter_threads(1)?
        .with_intra_op_spinning(false)?
        .with_inter_op_spinning(false)?
        .commit_from_file(s(&spec, "encoder")?)?;

    let mut records = Vec::<Record>::new();
    for line in fs::read_to_string(root.join("observations.jsonl"))?.lines() {
        if line.trim().is_empty() {
            continue;
        }
        let frame: Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        let time = frame["source_seconds_nominal"].as_u64().ok_or("source time")?;
        for u in frame["units"].as_array().ok_or("units")? {
            let crop = s(u, "crop")?.to_owned();
            let pixel = s(u, "pixel_sha256")?.to_owned();
            let path = root.join(&crop);
            if !path.is_file() {
                return Err("collection crop missing".into());
            }
            records.push(Record {
                time,
                crop,
                path,
                pixel,
                boxv: u["box"].clone(),
            });
        }
    }
    if records.is_empty() {
        return Err("empty collection".into());
    }

    // Embed all crops once in collection order.
    let started = Instant::now();
    let mut features = Vec::<Vec<f32>>::with_capacity(records.len());
    for chunk in records.chunks(batch) {
        let mut prepared = Vec::with_capacity(chunk.len());
        for r in chunk {
            let crop = load_crop(&r.path, &r.pixel)?;
            prepared.push((transform.apply(&crop)?, true));
        }
        features.extend(embeddings(&mut session, &prepared, side, false, false)?);
    }
    if features.len() != records.len() {
        return Err("feature count mismatch".into());
    }

    let by_pixel: HashMap<_, _> = records
        .iter()
        .enumerate()
        .map(|(i, r)| (r.pixel.as_str(), i))
        .collect();

    let source_id = s(&report, "source_id")?;
    let mut anchors = Vec::<Anchor>::new();
    let mut gold_pixels = HashSet::<String>::new();
    for row in anchors_rows {
        if row["source_id"].as_str() != Some(source_id)
            || (row["label_source"] != "autonomous_shop_purchase_bench_consensus_v1"
                && row["label_source"] != "autonomous_tooltip_temporal_consensus_v1")
            || row["human_review_required"] != false
            || row["model_prediction_used_as_label"] != false
            || row["training_eligible"] != true
        {
            return Err("gold anchor provenance mismatch".into());
        }
        let label = s(row, "unit_id")?.to_owned();
        if !head.labels.contains(&label) {
            return Err(format!("gold anchor label absent from frozen classifier: {label}").into());
        }
        let pixel = s(row, "pixel_sha256")?.to_owned();
        let &idx = by_pixel.get(pixel.as_str()).ok_or("gold anchor crop absent from collection")?;
        if records[idx].crop != s(row, "crop")? {
            return Err("gold anchor crop path/pixel mismatch".into());
        }
        gold_pixels.insert(pixel.clone());
        anchors.push(Anchor {
            label,
            time: row["source_seconds_nominal"].as_u64().ok_or("anchor time")?,
            pixel,
            crop: records[idx].crop.clone(),
            feature: features[idx].clone(),
            center: center(&records[idx].boxv)?,
        });
    }

    // Same-label anchor self-consistency is evidence. If multiple gold anchors
    // for one class disagree too strongly, propagation for that class is disabled.
    let mut anchor_pair_min = BTreeMap::<String, f32>::new();
    let labels: HashSet<_> = anchors.iter().map(|a| a.label.clone()).collect();
    for label in &labels {
        let same: Vec<_> = anchors.iter().filter(|a| &a.label == label).collect();
        if same.len() >= 2 {
            let mut minimum = 1f32;
            for i in 0..same.len() {
                for j in i + 1..same.len() {
                    minimum = minimum.min(cosine(&same[i].feature, &same[j].feature)?);
                }
            }
            anchor_pair_min.insert(label.clone(), minimum);
        }
    }

    let mut candidates = Vec::<Value>::new();
    let mut rejected = BTreeMap::<String, u64>::new();
    let mut top1_distribution = BTreeMap::<String, u64>::new();

    for (record, feature) in records.iter().zip(&features) {
        if gold_pixels.contains(&record.pixel) {
            continue;
        }

        let p = head.probabilities(feature)?;
        let mut order: Vec<_> = (0..p.len()).collect();
        order.sort_by(|&a, &b| p[b].total_cmp(&p[a]).then(a.cmp(&b)));
        let classifier_label = head.labels[order[0]].clone();
        *top1_distribution.entry(classifier_label.clone()).or_default() += 1;
        let classifier_margin = p[order[0]] - p[order[1]];

        let mut per_label = Vec::<(String, f32, u64, f32, String)>::new();
        for label in &labels {
            let mut best: Option<(f32, u64, f32, String)> = None;
            for a in anchors.iter().filter(|a| &a.label == label) {
                let dt = record.time.abs_diff(a.time);
                if dt > max_time_delta {
                    continue;
                }
                let sim = cosine(feature, &a.feature)?;
                let c = center(&record.boxv)?;
                let screen_distance = ((c.0 - a.center.0).powi(2) + (c.1 - a.center.1).powi(2)).sqrt();
                let replace = best
                    .as_ref()
                    .is_none_or(|(old_sim, old_dt, _, _)| sim > *old_sim || (sim == *old_sim && dt < *old_dt));
                if replace {
                    best = Some((sim, dt, screen_distance, a.crop.clone()));
                }
            }
            if let Some((sim, dt, screen_distance, anchor_crop)) = best {
                per_label.push((label.clone(), sim, dt, screen_distance, anchor_crop));
            }
        }
        if per_label.is_empty() {
            *rejected.entry("outside_temporal_window".into()).or_default() += 1;
            continue;
        }
        per_label.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
        let best = &per_label[0];
        let second_similarity = per_label.get(1).map(|x| x.1).unwrap_or(-1.0);
        let anchor_margin = best.1 - second_similarity;

        if best.1 < min_anchor_similarity {
            *rejected.entry("anchor_similarity_below_threshold".into()).or_default() += 1;
            continue;
        }
        if anchor_margin < min_anchor_margin {
            *rejected.entry("anchor_label_margin_below_threshold".into()).or_default() += 1;
            continue;
        }
        if best.3 > max_anchor_screen_distance {
            *rejected.entry("screen_distance_too_large".into()).or_default() += 1;
            continue;
        }
        if classifier_label != best.0 {
            *rejected.entry("frozen_classifier_disagrees".into()).or_default() += 1;
            continue;
        }
        if classifier_margin < min_classifier_margin {
            *rejected.entry("classifier_margin_below_threshold".into()).or_default() += 1;
            continue;
        }

        // If the class has multiple independent gold anchors, require their
        // own agreement to be no worse than a conservative floor. Classes with
        // one gold anchor remain eligible but are explicitly lower-evidence.
        let gold_anchor_count = anchors.iter().filter(|a| a.label == best.0).count();
        if let Some(pair_min) = anchor_pair_min.get(&best.0) {
            if *pair_min < 0.80 {
                *rejected.entry("gold_anchor_pair_inconsistent".into()).or_default() += 1;
                continue;
            }
        }

        candidates.push(json!({
            "source_id":source_id,
            "unit_id":best.0,
            "source_seconds_nominal":record.time,
            "crop":record.crop,
            "crop_path":record.path,
            "pixel_sha256":record.pixel,
            "box":record.boxv,
            "label_source":"silver_auto_dino_frozen_temporal_consensus_v1",
            "evidence":{
                "gold_anchor_crop":best.4,
                "gold_anchor_count_for_class":gold_anchor_count,
                "gold_anchor_pair_min_similarity":anchor_pair_min.get(&best.0),
                "anchor_cosine_similarity":best.1,
                "anchor_label_margin":anchor_margin,
                "nearest_gold_time_delta_seconds":best.2,
                "anchor_screen_distance_px":best.3,
                "frozen_classifier_label":classifier_label,
                "frozen_classifier_probability_uncalibrated":p[order[0]],
                "frozen_classifier_margin_uncalibrated":classifier_margin
            },
            "human_review_required":false,
            "model_prediction_used_as_label":false,
            "training_eligible":true,
            "supervision_tier":"silver_auto",
            "recommended_training_weight":0.35
        }));
    }

    // Diversity cap: one strongest crop per label/time bucket, then keep best N.
    let mut selected = Vec::<Value>::new();
    let mut per_label_stats = BTreeMap::<String, Value>::new();
    for label in &labels {
        let raw: Vec<_> = candidates
            .iter()
            .filter(|r| r["unit_id"].as_str() == Some(label.as_str()))
            .cloned()
            .collect();
        let mut buckets = HashMap::<u64, Value>::new();
        for row in raw.iter().cloned() {
            let bucket = row["source_seconds_nominal"].as_u64().unwrap_or(0) / bucket_seconds;
            let score = row["evidence"]["anchor_cosine_similarity"].as_f64().unwrap_or(0.0);
            let replace = buckets.get(&bucket).is_none_or(|old| {
                score > old["evidence"]["anchor_cosine_similarity"].as_f64().unwrap_or(0.0)
            });
            if replace {
                buckets.insert(bucket, row);
            }
        }
        let mut diverse: Vec<_> = buckets.into_values().collect();
        diverse.sort_by(|a,b| {
            b["evidence"]["anchor_cosine_similarity"].as_f64().unwrap_or(0.0)
                .total_cmp(&a["evidence"]["anchor_cosine_similarity"].as_f64().unwrap_or(0.0))
                .then_with(|| {
                    b["evidence"]["frozen_classifier_margin_uncalibrated"].as_f64().unwrap_or(0.0)
                        .total_cmp(&a["evidence"]["frozen_classifier_margin_uncalibrated"].as_f64().unwrap_or(0.0))
                })
        });
        let diverse_before_cap = diverse.len();
        diverse.truncate(per_label_limit);
        per_label_stats.insert(label.clone(), json!({
            "gold_anchors":anchors.iter().filter(|a|a.label==*label).count(),
            "raw_consensus_candidates":raw.len(),
            "diverse_before_cap":diverse_before_cap,
            "selected_silver":diverse.len(),
            "gold_anchor_pair_min_similarity":anchor_pair_min.get(label)
        }));
        selected.extend(diverse);
    }

    selected.sort_by(|a,b| {
        a["unit_id"].as_str().unwrap_or("").cmp(b["unit_id"].as_str().unwrap_or(""))
            .then_with(|| a["source_seconds_nominal"].as_u64().unwrap_or(0).cmp(&b["source_seconds_nominal"].as_u64().unwrap_or(0)))
    });

    fs::create_dir_all(&out)?;
    fs::write(out.join("silver-auto-labels.json"), serde_json::to_vec_pretty(&selected)?)?;
    let summary = json!({
        "schema_version":1,
        "policy":"silver_auto_dino_frozen_temporal_consensus_v1",
        "source_id":source_id,
        "collection_unit_crops":records.len(),
        "gold_anchors":anchors.len(),
        "gold_ids":anchors.iter().fold(BTreeMap::<String,u64>::new(),|mut m,a|{*m.entry(a.label.clone()).or_default()+=1;m}),
        "frozen_model_sha256":hash(&model_bytes),
        "encoder_sha256":hash(&encoder_bytes),
        "crop_transform":transform.name(),
        "thresholds":{
            "max_time_delta_seconds":max_time_delta,
            "min_anchor_similarity":min_anchor_similarity,
            "min_anchor_margin":min_anchor_margin,
            "min_classifier_margin":min_classifier_margin,
            "max_anchor_screen_distance_px":max_anchor_screen_distance,
            "bucket_seconds":bucket_seconds,
            "per_label_limit":per_label_limit
        },
        "per_label":per_label_stats,
        "silver_auto_labels":selected.len(),
        "rejected":rejected,
        "top1_distribution":top1_distribution,
        "recommended_training_weight":0.35,
        "human_review_required":false,
        "training_performed":false,
        "runtime_approved":false,
        "elapsed_seconds":started.elapsed().as_secs_f64(),
        "limitations":[
            "Silver labels are not gold truth and must receive lower training weight.",
            "Frozen classifier and DINO anchor similarity share the same encoder family, so temporal evidence is required.",
            "No silver label is admitted outside the configured gold-anchor time window.",
            "No human review is required; ambiguous evidence remains excluded."
        ]
    });
    fs::write(out.join("report.json"), serde_json::to_vec_pretty(&summary)?)?;
    println!("{summary}");
    Ok(())
}

fn main() {
    if let Err(e) = run() {
        eprintln!("AUTONOMOUS_PROPAGATION_ERROR: {e}");
        std::process::exit(1);
    }
}
