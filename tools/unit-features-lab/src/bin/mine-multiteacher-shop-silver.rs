//! Rescue sub-gold shop events with conservative multi-teacher consensus.
//!
//! This tool never creates gold labels and never bootstraps unseen classes.
//! A low-confidence exact shop-name proposal can become low-weight silver only
//! when strong purchase/bench evidence, frozen classifier, supervised retrieval,
//! and temporal crop repetition all agree.

use agente_tft_image_preprocess::unit_features::UnitCrop;
use agente_tft_unit_features_lab::{
    crop_transform::CropTransform, embedding_batch_size, embeddings, load_samples,
    training::Head, Result, Sample,
};
use ort::session::Session;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashMap, HashSet},
    fs,
    path::{Path, PathBuf},
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
fn center(v: &Value) -> Result<(f32, f32)> {
    let a = v.as_array().ok_or("box array")?;
    if a.len() != 4 {
        return Err("box size".into());
    }
    let mut n = [0f32; 4];
    for (i, x) in a.iter().enumerate() {
        n[i] = x.as_f64().ok_or("box number")? as f32;
    }
    Ok(((n[0] + n[2]) * 0.5, (n[1] + n[3]) * 0.5))
}
fn distance(a: (f32, f32), b: (f32, f32)) -> f32 {
    ((a.0 - b.0).powi(2) + (a.1 - b.1).powi(2)).sqrt()
}
fn load_crop(path: &Path, expected: &str) -> Result<UnitCrop> {
    let rgb = image::open(path)?.to_rgb8();
    if (rgb.width(), rgb.height()) != (128, 144) {
        return Err("crop geometry must be 128x144".into());
    }
    let raw = rgb.into_raw();
    if hash(&raw) != expected {
        return Err("crop pixel checksum mismatch".into());
    }
    Ok(UnitCrop { rgb: raw })
}

#[derive(Clone)]
struct ObservationUnit {
    time: u64,
    crop: String,
    pixel: String,
    boxv: Value,
}

#[derive(Clone)]
struct TeacherDecision {
    label: String,
    classifier_label: String,
    classifier_probability: f32,
    classifier_margin: f32,
    retrieval_label: String,
    retrieval_similarity: f32,
    retrieval_margin: f32,
    retrieval_threshold: f32,
    passes: bool,
}

fn teacher_decision(
    feature: &[f32],
    target: &str,
    head: &Head,
    train: &[(&Sample, &Vec<f32>)],
    threshold_by_target: &HashMap<String, f32>,
    min_margin: f32,
) -> Result<TeacherDecision> {
    let p = head.probabilities(feature)?;
    let mut order: Vec<_> = (0..p.len()).collect();
    order.sort_by(|&a, &b| p[b].total_cmp(&p[a]).then(a.cmp(&b)));
    if order.len() < 2 {
        return Err("classifier has fewer than two classes".into());
    }
    let classifier_label = head.labels[order[0]].clone();
    let classifier_probability = p[order[0]];
    let classifier_margin = p[order[0]] - p[order[1]];

    let mut best_by_class = HashMap::<String, f32>::new();
    for (sample, support) in train {
        let sim = cosine(feature, support)?;
        best_by_class
            .entry(sample.label.clone())
            .and_modify(|x| *x = x.max(sim))
            .or_insert(sim);
    }
    let mut ranked: Vec<_> = best_by_class.into_iter().collect();
    ranked.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
    if ranked.len() < 2 {
        return Err("retrieval has fewer than two classes".into());
    }
    let retrieval_label = ranked[0].0.clone();
    let retrieval_similarity = ranked[0].1;
    let retrieval_margin = ranked[0].1 - ranked[1].1;
    let retrieval_threshold = *threshold_by_target
        .get(target)
        .ok_or("target lacks calibrated supervised retrieval support")?;

    let passes = classifier_label == target
        && classifier_margin >= min_margin
        && retrieval_label == target
        && retrieval_similarity >= retrieval_threshold
        && retrieval_margin >= min_margin;

    Ok(TeacherDecision {
        label: target.to_owned(),
        classifier_label,
        classifier_probability,
        classifier_margin,
        retrieval_label,
        retrieval_similarity,
        retrieval_margin,
        retrieval_threshold,
        passes,
    })
}

fn run() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 || args[1] != "--spec" {
        return Err("use --spec MULTITEACHER_SHOP.json".into());
    }
    let spec: Value = serde_json::from_slice(&fs::read(&args[2])?)?;
    let root = PathBuf::from(s(&spec, "collection")?);
    let transitions_path = PathBuf::from(s(&spec, "transitions")?);
    let out = PathBuf::from(s(&spec, "output")?);
    if out.exists() {
        return Err("new output directory required".into());
    }

    let report: Value = serde_json::from_slice(&fs::read(root.join("report.json"))?)?;
    if report["status"] != "complete"
        || report["collection_mode"] != "annotation_only"
        || report["inference_performed"] != false
        || report["training_performed"] != false
    {
        return Err("complete annotation_only collection required".into());
    }
    let source_id = s(&report, "source_id")?.to_owned();

    let target_ids: Vec<String> = serde_json::from_value(spec["target_ids"].clone())?;
    if target_ids.is_empty() {
        return Err("target_ids required".into());
    }
    let targets: HashSet<_> = target_ids.iter().cloned().collect();

    let min_ocr = spec["min_silver_ocr_confidence"].as_f64().unwrap_or(70.0) as f32;
    let gold_ocr = spec["gold_ocr_confidence"].as_f64().unwrap_or(94.0) as f32;
    let max_persistence = spec["max_persistence_seconds"].as_u64().unwrap_or(8);
    let max_distance = spec["max_persistence_distance_px"].as_f64().unwrap_or(70.0) as f32;
    let retrieval_margin = spec["retrieval_safety_margin"].as_f64().unwrap_or(0.03) as f32;
    let teacher_margin = spec["teacher_margin"].as_f64().unwrap_or(0.01) as f32;
    let min_confirmed = spec["min_confirmed_unique_crops"].as_u64().unwrap_or(2) as usize;
    let per_event_limit = spec["per_event_label_limit"].as_u64().unwrap_or(2) as usize;
    let per_target_limit = spec["per_target_label_limit"].as_u64().unwrap_or(24) as usize;
    if !(0.0..gold_ocr).contains(&min_ocr)
        || gold_ocr > 100.0
        || !(2..=20).contains(&max_persistence)
        || !(10.0..=200.0).contains(&max_distance)
        || !(0.005..=0.20).contains(&retrieval_margin)
        || !(0.0..=0.20).contains(&teacher_margin)
        || !(2..=6).contains(&min_confirmed)
        || !(1..=4).contains(&per_event_limit)
        || !(1..=100).contains(&per_target_limit)
    {
        return Err("invalid multi-teacher thresholds".into());
    }

    let model_bytes = read_sealed(&spec, "model")?;
    let model: Value = serde_json::from_slice(&model_bytes)?;
    if model["feature_mode"] != "dino" || model["runtime_approved"] != false {
        return Err("frozen non-runtime DINO model required".into());
    }
    let head: Head = serde_json::from_value(model["head"].clone())?;
    for target in &target_ids {
        if !head.labels.contains(target) {
            return Err(format!("target absent from frozen classifier: {target}").into());
        }
    }
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
    ort::init_from(s(&spec, "onnxruntime")?).commit()?;
    let mut session = Session::builder()?
        .with_intra_threads(1)?
        .with_inter_threads(1)?
        .with_intra_op_spinning(false)?
        .with_inter_op_spinning(false)?
        .commit_from_file(s(&spec, "encoder")?)?;

    let annotations = Path::new(s(&spec, "annotations")?);
    let images = Path::new(s(&spec, "images")?);
    let reference = Path::new(s(&spec, "reference")?);
    let supervised = load_samples(annotations, images, reference)?;
    let train_samples: Vec<&Sample> = supervised
        .iter()
        .filter(|s| s.split == "train" && s.label != "__unknown__")
        .collect();
    if train_samples.is_empty() {
        return Err("no supervised train support".into());
    }

    let mut train_features = Vec::<Vec<f32>>::with_capacity(train_samples.len());
    for chunk in train_samples.chunks(batch) {
        let mut prepared = Vec::with_capacity(chunk.len());
        for sample in chunk {
            prepared.push((transform.apply(&sample.crop)?, true));
        }
        train_features.extend(embeddings(&mut session, &prepared, side, false, false)?);
    }
    let train: Vec<_> = train_samples.iter().copied().zip(&train_features).collect();

    // Calibrate each target against its own supervised support versus all
    // other-class supervised samples. A singleton class is allowed, but the
    // candidate must beat that support vector's strongest impostor by margin.
    let mut threshold_by_target = HashMap::<String, f32>::new();
    let mut calibration = BTreeMap::<String, Value>::new();
    for target in &target_ids {
        let support: Vec<_> = train
            .iter()
            .filter(|(s, _)| s.label == *target)
            .collect();
        if support.is_empty() {
            return Err(format!("target has no supervised support: {target}").into());
        }
        let mut impostor_ceiling = -1.0f32;
        for (_, v) in &support {
            for (other, ov) in &train {
                if other.label == *target {
                    continue;
                }
                impostor_ceiling = impostor_ceiling.max(cosine(v, ov)?);
            }
        }
        let threshold = impostor_ceiling + retrieval_margin;
        if threshold >= 0.999 {
            calibration.insert(
                target.clone(),
                json!({"support":support.len(),"impostor_ceiling":impostor_ceiling,
                    "threshold":threshold,"usable":false}),
            );
            continue;
        }
        threshold_by_target.insert(target.clone(), threshold);
        calibration.insert(
            target.clone(),
            json!({"support":support.len(),"impostor_ceiling":impostor_ceiling,
                "threshold":threshold,"retrieval_safety_margin":retrieval_margin,"usable":true}),
        );
    }
    if threshold_by_target.is_empty() {
        return Err("no target has a usable train-only retrieval calibration".into());
    }

    let mut observation_units = Vec::<ObservationUnit>::new();
    for line in fs::read_to_string(root.join("observations.jsonl"))?.lines() {
        if line.trim().is_empty() {
            continue;
        }
        let frame: Value = serde_json::from_str(line)?;
        let time = frame["source_seconds_nominal"].as_u64().ok_or("observation time")?;
        for u in frame["units"].as_array().ok_or("observation units")? {
            observation_units.push(ObservationUnit {
                time,
                crop: s(u, "crop")?.to_owned(),
                pixel: s(u, "pixel_sha256")?.to_owned(),
                boxv: u["box"].clone(),
            });
        }
    }
    observation_units.sort_by_key(|u| u.time);

    let transitions: Value = serde_json::from_slice(&fs::read(&transitions_path)?)?;
    let transitions = transitions.as_array().ok_or("transition proposals must be an array")?;

    let mut labels = Vec::<Value>::new();
    let mut rejected = BTreeMap::<String, u64>::new();
    let mut event_number = 0u64;

    for row in transitions {
        if row["source_id"].as_str() != Some(source_id.as_str()) {
            return Err("transition source mismatch".into());
        }
        let ids = row["shop_unit_candidates"].as_array().ok_or("shop candidates")?;
        if ids.len() != 1 {
            *rejected.entry("shop_identity_not_unique".into()).or_default() += 1;
            continue;
        }
        let Some(target) = ids[0].as_str() else {
            *rejected.entry("invalid_shop_identity".into()).or_default() += 1;
            continue;
        };
        if !targets.contains(target) {
            *rejected.entry("not_requested_target".into()).or_default() += 1;
            continue;
        }
        if !threshold_by_target.contains_key(target) {
            *rejected.entry("target_calibration_unusable".into()).or_default() += 1;
            continue;
        }

        let conf = row["shop_ocr_name_confidence"].as_f64().ok_or("shop OCR confidence")? as f32;
        if conf < min_ocr || conf >= gold_ocr {
            *rejected.entry("outside_silver_ocr_band".into()).or_default() += 1;
            continue;
        }
        let before = row["portrait_brightness_before"].as_f64().ok_or("portrait before")? as f32;
        let after = row["portrait_brightness_after"].as_f64().ok_or("portrait after")? as f32;
        if before < 0.10 || !(0.0..=0.02).contains(&after) {
            *rejected.entry("portrait_disappearance_not_strong".into()).or_default() += 1;
            continue;
        }
        let before_t = row["before_seconds"].as_u64().ok_or("before seconds")?;
        let after_t = row["after_seconds"].as_u64().ok_or("after seconds")?;
        if after_t <= before_t || after_t - before_t > 2 {
            *rejected.entry("transition_gap_not_dense".into()).or_default() += 1;
            continue;
        }
        let bench = row["new_bench_proposals"].as_array().ok_or("new bench proposals")?;
        if bench.len() != 1 {
            *rejected.entry("new_bench_unit_not_unique".into()).or_default() += 1;
            continue;
        }
        let initial = &bench[0];
        let initial_box = &initial["box"];
        let origin = center(initial_box)?;

        let mut track = Vec::<ObservationUnit>::new();
        track.push(ObservationUnit {
            time: after_t,
            crop: s(initial, "crop")?.to_owned(),
            pixel: s(initial, "pixel_sha256")?.to_owned(),
            boxv: initial_box.clone(),
        });
        for t in ((after_t + 1)..=(after_t + max_persistence)).step_by(1) {
            let mut best: Option<(f32, ObservationUnit)> = None;
            for u in observation_units.iter().filter(|u| u.time == t) {
                let d = distance(origin, center(&u.boxv)?);
                if d <= max_distance
                    && best.as_ref().is_none_or(|(old, _)| d < *old)
                {
                    best = Some((d, u.clone()));
                }
            }
            if let Some((_, unit)) = best {
                track.push(unit);
            }
        }

        let mut unique = Vec::<ObservationUnit>::new();
        let mut seen_pixels = HashSet::<String>::new();
        for u in track {
            if seen_pixels.insert(u.pixel.clone()) {
                unique.push(u);
            }
        }
        if unique.len() < min_confirmed {
            *rejected.entry("insufficient_temporal_unique_crops".into()).or_default() += 1;
            continue;
        }

        let mut confirmed = Vec::<(ObservationUnit, TeacherDecision)>::new();
        for chunk in unique.chunks(batch) {
            let mut prepared = Vec::with_capacity(chunk.len());
            for u in chunk {
                let crop = load_crop(&root.join(&u.crop), &u.pixel)?;
                prepared.push((transform.apply(&crop)?, true));
            }
            let features = embeddings(&mut session, &prepared, side, false, false)?;
            for (u, feature) in chunk.iter().zip(features) {
                let decision = teacher_decision(
                    &feature,
                    target,
                    &head,
                    &train,
                    &threshold_by_target,
                    teacher_margin,
                )?;
                if decision.passes {
                    confirmed.push((u.clone(), decision));
                }
            }
        }
        if confirmed.len() < min_confirmed {
            *rejected.entry("multi_teacher_temporal_consensus_failed".into()).or_default() += 1;
            continue;
        }

        event_number += 1;
        confirmed.sort_by_key(|(u, _)| u.time);
        if confirmed.len() > per_event_limit {
            let first = confirmed.first().cloned().unwrap();
            let last = confirmed.last().cloned().unwrap();
            confirmed = if first.0.pixel == last.0.pixel {
                vec![first]
            } else {
                vec![first, last]
            };
        }

        for (u, d) in confirmed {
            labels.push(json!({
                "source_id":source_id,
                "unit_id":d.label,
                "source_seconds_nominal":u.time,
                "crop":u.crop,
                "crop_path":root.join(&u.crop),
                "pixel_sha256":u.pixel,
                "box":u.boxv,
                "label_source":"silver_auto_shop_multiteacher_temporal_v1",
                "supervision_tier":"silver_auto",
                "recommended_training_weight":0.20,
                "evidence":{
                    "event_number":event_number,
                    "exact_unique_shop_ocr_candidate":true,
                    "shop_ocr_confidence":conf,
                    "gold_ocr_threshold_unchanged":gold_ocr,
                    "portrait_brightness_before":before,
                    "portrait_brightness_after":after,
                    "transition_gap_seconds":after_t-before_t,
                    "unique_new_bench_proposal":true,
                    "temporal_unique_candidates":unique.len(),
                    "temporal_multi_teacher_confirmations":min_confirmed,
                    "frozen_classifier":{
                        "label":d.classifier_label,
                        "probability_uncalibrated":d.classifier_probability,
                        "margin_uncalibrated":d.classifier_margin
                    },
                    "supervised_retrieval":{
                        "label":d.retrieval_label,
                        "similarity":d.retrieval_similarity,
                        "margin":d.retrieval_margin,
                        "train_only_threshold":d.retrieval_threshold
                    }
                },
                "human_review_required":false,
                "model_prediction_used_as_label":false,
                "training_eligible":true
            }));
        }
    }

    // Deduplicate and cap target contribution to prevent one source dominating.
    let mut deduped = Vec::<Value>::new();
    let mut seen = HashSet::<String>::new();
    let mut counts = HashMap::<String, usize>::new();
    labels.sort_by(|a, b| {
        a["unit_id"].as_str().unwrap_or("").cmp(b["unit_id"].as_str().unwrap_or(""))
            .then_with(|| a["source_seconds_nominal"].as_u64().unwrap_or(0)
                .cmp(&b["source_seconds_nominal"].as_u64().unwrap_or(0)))
    });
    for row in labels {
        let pixel = s(&row, "pixel_sha256")?.to_owned();
        let label = s(&row, "unit_id")?.to_owned();
        if !seen.insert(pixel) {
            continue;
        }
        let n = counts.entry(label).or_default();
        if *n >= per_target_limit {
            continue;
        }
        *n += 1;
        deduped.push(row);
    }

    let distribution = deduped.iter().fold(BTreeMap::<String, u64>::new(), |mut m, row| {
        if let Some(id) = row["unit_id"].as_str() {
            *m.entry(id.to_owned()).or_default() += 1;
        }
        m
    });

    fs::create_dir_all(&out)?;
    fs::write(out.join("silver-auto-labels.json"), serde_json::to_vec_pretty(&deduped)?)?;
    let summary = json!({
        "schema_version":1,
        "policy":"silver_auto_shop_multiteacher_temporal_v1",
        "source_id":source_id,
        "target_ids":target_ids,
        "transition_proposals":transitions.len(),
        "silver_auto_labels":deduped.len(),
        "silver_auto_ids":distribution,
        "calibration":calibration,
        "thresholds":{
            "min_silver_ocr_confidence":min_ocr,
            "gold_ocr_confidence_unchanged":gold_ocr,
            "max_persistence_seconds":max_persistence,
            "max_persistence_distance_px":max_distance,
            "retrieval_safety_margin":retrieval_margin,
            "teacher_margin":teacher_margin,
            "min_confirmed_unique_crops":min_confirmed,
            "per_event_label_limit":per_event_limit,
            "per_target_label_limit":per_target_limit
        },
        "rejected":rejected,
        "recommended_training_weight":0.20,
        "human_review_required":false,
        "training_performed":false,
        "runtime_approved":false,
        "limitations":[
            "These are low-weight silver labels, never gold truth.",
            "The original gold OCR threshold remains 94 and is not weakened.",
            "The OCR proposal supplies the candidate identity; frozen classifier and train-only retrieval must independently agree on repeated bench crops.",
            "No unseen class can be created by this policy."
        ]
    });
    fs::write(out.join("report.json"), serde_json::to_vec_pretty(&summary)?)?;
    println!("{summary}");
    Ok(())
}

fn main() {
    if let Err(e) = run() {
        eprintln!("MULTITEACHER_SHOP_SILVER_ERROR: {e}");
        std::process::exit(1);
    }
}
