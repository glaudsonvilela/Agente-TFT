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


fn chained_temporal_track(
    observations: &[ObservationUnit],
    initial: ObservationUnit,
    max_persistence: u64,
    max_distance: f32,
) -> Result<Vec<ObservationUnit>> {
    let start_time = initial.time;
    let mut last_center = center(&initial.boxv)?;
    let mut track = vec![initial];

    // Follow only timestamps that actually exist in the dense collection.
    // Position is updated after every match so modest bench movement does not
    // break the track merely because it moved away from the purchase position.
    let mut times: Vec<u64> = observations
        .iter()
        .filter(|u| u.time > start_time && u.time <= start_time + max_persistence)
        .map(|u| u.time)
        .collect();
    times.sort_unstable();
    times.dedup();

    for t in times {
        let mut best: Option<(f32, ObservationUnit)> = None;
        for u in observations.iter().filter(|u| u.time == t) {
            let d = distance(last_center, center(&u.boxv)?);
            if d <= max_distance && best.as_ref().is_none_or(|(old, _)| d < *old) {
                best = Some((d, u.clone()));
            }
        }
        if let Some((_, unit)) = best {
            last_center = center(&unit.boxv)?;
            track.push(unit);
        }
    }
    Ok(track)
}


fn is_board_unit(unit: &ObservationUnit) -> Result<bool> {
    let a = unit.boxv.as_array().ok_or("box array")?;
    if a.len() != 4 {
        return Err("box size".into());
    }
    let y = a[1].as_f64().ok_or("box y")?;
    Ok((250.0..665.0).contains(&y))
}

fn unique_pixels(track: Vec<ObservationUnit>) -> Vec<ObservationUnit> {
    let mut seen = HashSet::<String>::new();
    track
        .into_iter()
        .filter(|u| seen.insert(u.pixel.clone()))
        .collect()
}

fn chained_board_track(
    observations: &[ObservationUnit],
    initial: ObservationUnit,
    end_time: u64,
    max_distance: f32,
) -> Result<Vec<ObservationUnit>> {
    let mut last_center = center(&initial.boxv)?;
    let start_time = initial.time;
    let mut track = vec![initial];
    let mut times: Vec<u64> = observations
        .iter()
        .filter(|u| u.time > start_time && u.time <= end_time)
        .map(|u| u.time)
        .collect();
    times.sort_unstable();
    times.dedup();
    for t in times {
        let mut best: Option<(f32, ObservationUnit)> = None;
        for u in observations.iter().filter(|u| u.time == t) {
            if !is_board_unit(u)? {
                continue;
            }
            let d = distance(last_center, center(&u.boxv)?);
            if d <= max_distance && best.as_ref().is_none_or(|(old, _)| d < *old) {
                best = Some((d, u.clone()));
            }
        }
        if let Some((_, unit)) = best {
            last_center = center(&unit.boxv)?;
            track.push(unit);
        }
    }
    Ok(track)
}

fn new_board_emergence_track(
    observations: &[ObservationUnit],
    before_t: u64,
    after_t: u64,
    max_persistence: u64,
    max_distance: f32,
    min_unique: usize,
) -> Result<Option<Vec<ObservationUnit>>> {
    let baseline: Vec<_> = observations
        .iter()
        .filter(|u| u.time == before_t)
        .filter_map(|u| match is_board_unit(u) {
            Ok(true) => Some(Ok(u.clone())),
            Ok(false) => None,
            Err(e) => Some(Err(e)),
        })
        .collect::<Result<_>>()?;

    let mut times: Vec<u64> = observations
        .iter()
        .filter(|u| u.time > after_t && u.time <= after_t + max_persistence)
        .map(|u| u.time)
        .collect();
    times.sort_unstable();
    times.dedup();

    for t in times {
        let mut starters = Vec::<ObservationUnit>::new();
        for u in observations.iter().filter(|u| u.time == t) {
            if !is_board_unit(u)? {
                continue;
            }
            let c = center(&u.boxv)?;
            let existed_before = baseline.iter().any(|b| {
                center(&b.boxv)
                    .map(|bc| distance(c, bc) <= max_distance)
                    .unwrap_or(false)
            });
            if !existed_before {
                starters.push(u.clone());
            }
        }
        if starters.is_empty() {
            continue;
        }

        let mut qualifying = Vec::<Vec<ObservationUnit>>::new();
        for starter in starters {
            let track = unique_pixels(chained_board_track(
                observations,
                starter,
                after_t + max_persistence,
                max_distance,
            )?);
            if track.len() >= min_unique {
                qualifying.push(track);
            }
        }
        // Fail closed: exactly one newly emerged board track must persist.
        return Ok(if qualifying.len() == 1 {
            Some(qualifying.remove(0))
        } else {
            None
        });
    }
    Ok(None)
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
        let track = chained_temporal_track(
            &observation_units,
            ObservationUnit {
                time: after_t,
                crop: s(initial, "crop")?.to_owned(),
                pixel: s(initial, "pixel_sha256")?.to_owned(),
                boxv: initial_box.clone(),
            },
            max_persistence,
            max_distance,
        )?;

        let mut unique = unique_pixels(track);
        let mut tracking_mode = "bench_chained";
        if unique.len() < min_confirmed {
            if let Some(board_track) = new_board_emergence_track(
                &observation_units,
                before_t,
                after_t,
                max_persistence,
                max_distance,
                min_confirmed,
            )? {
                unique = board_track;
                tracking_mode = "new_board_emergence";
            }
        }
        if unique.len() < min_confirmed {
            *rejected
                .entry("insufficient_bench_and_board_temporal_unique_crops".into())
                .or_default() += 1;
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
                    "tracking_mode":tracking_mode,
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
            "A direct bench track is preferred; when absent, exactly one newly emerged board track may continue the purchase evidence.",
            "No unseen class can be created by this policy."
        ]
    });
    fs::write(out.join("report.json"), serde_json::to_vec_pretty(&summary)?)?;
    println!("{summary}");
    Ok(())
}


#[cfg(test)]
mod tests {
    use super::*;

    fn unit(time: u64, x: f64, pixel: &str) -> ObservationUnit {
        ObservationUnit {
            time,
            crop: format!("{pixel}.png"),
            pixel: pixel.to_owned(),
            boxv: json!([x, 700.0, x + 128.0, 844.0]),
        }
    }

    #[test]
    fn chained_tracking_follows_gradual_bench_movement() {
        let initial = unit(10, 100.0, "a");
        let observations = vec![
            unit(12, 150.0, "b"),
            unit(14, 200.0, "c"),
            unit(16, 400.0, "far"),
        ];
        let track = chained_temporal_track(&observations, initial, 8, 70.0).unwrap();
        assert_eq!(track.iter().map(|u| u.pixel.as_str()).collect::<Vec<_>>(), vec!["a", "b", "c"]);
    }


    #[test]
    fn board_emergence_can_follow_direct_bench_to_board_purchase() {
        let observations = vec![
            unit(10, 500.0, "old-board"),
            ObservationUnit {
                time: 14,
                crop: "b.png".into(),
                pixel: "b".into(),
                boxv: json!([900.0, 420.0, 1028.0, 564.0]),
            },
            ObservationUnit {
                time: 16,
                crop: "c.png".into(),
                pixel: "c".into(),
                boxv: json!([920.0, 425.0, 1048.0, 569.0]),
            },
        ];
        let track = new_board_emergence_track(&observations, 10, 12, 8, 70.0, 2)
            .unwrap()
            .unwrap();
        assert_eq!(track.iter().map(|u| u.pixel.as_str()).collect::<Vec<_>>(), vec!["b", "c"]);
    }

    #[test]
    fn board_emergence_rejects_ambiguous_multiple_new_tracks() {
        let observations = vec![
            ObservationUnit {
                time: 14,
                crop: "a.png".into(),
                pixel: "a".into(),
                boxv: json!([800.0, 420.0, 928.0, 564.0]),
            },
            ObservationUnit {
                time: 14,
                crop: "b.png".into(),
                pixel: "b".into(),
                boxv: json!([1100.0, 420.0, 1228.0, 564.0]),
            },
            ObservationUnit {
                time: 16,
                crop: "a2.png".into(),
                pixel: "a2".into(),
                boxv: json!([810.0, 425.0, 938.0, 569.0]),
            },
            ObservationUnit {
                time: 16,
                crop: "b2.png".into(),
                pixel: "b2".into(),
                boxv: json!([1110.0, 425.0, 1238.0, 569.0]),
            },
        ];
        assert!(new_board_emergence_track(&observations, 10, 12, 8, 70.0, 2)
            .unwrap()
            .is_none());
    }

    #[test]
    fn chained_tracking_still_rejects_large_single_jump() {
        let initial = unit(10, 100.0, "a");
        let observations = vec![unit(12, 190.0, "b")];
        let track = chained_temporal_track(&observations, initial, 8, 70.0).unwrap();
        assert_eq!(track.len(), 1);
    }
}

fn main() {
    if let Err(e) = run() {
        eprintln!("MULTITEACHER_SHOP_SILVER_ERROR: {e}");
        std::process::exit(1);
    }
}
