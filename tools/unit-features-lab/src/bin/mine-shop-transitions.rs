//! Annotation aid: visible shop names and disappearing cards are review cues,
//! never identity labels or proof of purchase.
use agente_tft_unit_features_lab::{
    ocr_names::{match_name, name_indexes},
    Result,
};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{HashMap, VecDeque},
    fs,
    path::PathBuf,
    process::Command,
};

#[derive(Clone, Debug)]
struct NameRun {
    ids: Vec<String>,
    confirmations: u8,
    min_good_confidence: f32,
    first_ms: u64,
    last_ms: u64,
    last_frame_hash: String,
}

fn advance_name_run(
    old: Option<NameRun>,
    ids: Option<&Vec<String>>,
    confidence: Option<f32>,
    portrait: f32,
    time_ms: u64,
    frame_hash: &str,
) -> Option<NameRun> {
    if portrait < 0.10 {
        return None;
    }
    let Some(ids) = ids else {
        return old.filter(|run| time_ms.saturating_sub(run.last_ms) <= 750);
    };
    let good = confidence.is_some_and(|c| c.is_finite() && c >= 85.0);
    if let Some(mut run) = old {
        if run.ids == *ids && time_ms.saturating_sub(run.last_ms) <= 750 {
            if good && run.last_frame_hash != frame_hash {
                if run.confirmations == 0 {
                    run.min_good_confidence = confidence.unwrap();
                } else {
                    run.min_good_confidence = run.min_good_confidence.min(confidence.unwrap());
                }
                run.confirmations = run.confirmations.saturating_add(1);
            }
            run.last_ms = time_ms;
            run.last_frame_hash = frame_hash.into();
            return Some(run);
        }
    }
    Some(NameRun {
        ids: ids.clone(),
        confirmations: u8::from(good),
        min_good_confidence: if good { confidence.unwrap() } else { 0. },
        first_ms: time_ms,
        last_ms: time_ms,
        last_frame_hash: frame_hash.into(),
    })
}

fn bench_count(frame: &Value) -> usize {
    frame["units"].as_array().map_or(0, |units| {
        units
            .iter()
            .filter(|u| {
                let x = u["box"][0].as_i64();
                let y = u["box"][1].as_i64();
                x.is_some_and(|x| (300..=1450).contains(&x))
                    && y.is_some_and(|y| (665..=760).contains(&y))
            })
            .count()
    })
}

fn bench_reference<'a>(
    history: &'a VecDeque<(u64, Value)>,
    now_ms: u64,
) -> Option<(u64, &'a Value)> {
    history
        .iter()
        .filter(|(ms, _)| now_ms.saturating_sub(*ms) <= 1000)
        .max_by_key(|(ms, frame)| (bench_count(frame), *ms))
        .map(|(ms, frame)| (*ms, frame))
}

fn slot_words(tsv: &str) -> Vec<Vec<(String, f32)>> {
    let mut slots = vec![Vec::new(); 5];
    for row in tsv.lines().skip(1) {
        let c: Vec<_> = row.splitn(12, '\t').collect();
        if c.len() != 12 || c[0] != "5" || c[11].is_empty() {
            continue;
        }
        if c[9].parse::<u32>().unwrap_or(0) < 18 {
            continue; // Small cursor/price fragments, not name-height glyphs.
        }
        let (Ok(x), Ok(confidence)) = (c[6].parse::<u32>(), c[10].parse::<f32>()) else {
            continue;
        };
        // OCR uses a 2x strip; ignore each card's right-hand price/icon area.
        let x = x / 2;
        let slot = (x / 202) as usize;
        if slot < 5 && x % 202 < 165 {
            slots[slot].push((c[11].into(), confidence));
        }
    }
    slots
}

fn disappearances(
    before: &[Option<Vec<String>>],
    after: &[Option<Vec<String>>],
    gap_ms: u64,
) -> Vec<usize> {
    if before.len() != 5 || after.len() != 5 || !(1..=2000).contains(&gap_ms) {
        return vec![];
    }
    let stable = before
        .iter()
        .zip(after)
        .filter(|(a, b)| a.is_some() && a == b)
        .count();
    if stable < 3 {
        return vec![];
    }
    (0..5)
        .filter(|&i| before[i].is_some() && after[i].is_none())
        .collect()
}

// Empty cards have a dark silhouette. OCR absence alone can mean a cursor,
// tooltip or low-confidence name; require disappearance of the portrait too.
fn shop_portrait_brightness(frame: &image::RgbImage) -> Vec<f32> {
    (0..5)
        .map(|slot| {
            let mut bright = 0;
            for y in 941..1001 {
                for x in (552 + slot * 202 + 35)..(552 + slot * 202 + 155) {
                    if frame.get_pixel(x, y).0.iter().any(|v| *v > 55) {
                        bright += 1;
                    }
                }
            }
            bright as f32 / (120 * 60) as f32
        })
        .collect()
}
fn portrait_disappeared(before: f32, after: f32) -> bool {
    before.is_finite() && after.is_finite() && before >= 0.10 && (0.0..=0.02).contains(&after)
}

fn new_bench_proposals(before: &Value, after: &Value) -> Vec<Value> {
    let units = |f: &Value| f["units"].as_array().cloned().unwrap_or_default();
    let previous = units(before);
    units(after).into_iter().filter(|u| {
        let Some(b) = u["box"].as_array() else {return false;};
        if b.len()!=4 {return false;}
        let (Some(x),Some(y))=(b[0].as_i64(),b[1].as_i64()) else {return false;};
        if !(300..=1450).contains(&x) || !(665..=760).contains(&y) {return false;}
        !previous.iter().any(|p| match (p["box"][0].as_i64(),p["box"][1].as_i64()) {
            (Some(px),Some(py)) => (x-px).abs()<40 && (y-py).abs()<40,
            _=>false,
        })
    }).map(|u|json!({"crop":u["crop"],"box":u["box"],"marker_id":u["marker_id"],"pixel_sha256":u["pixel_sha256"],"identity_confirmed":false})).collect()
}

fn run() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 4 {
        return Err("use COLLECTION_DIRECTORY CATALOG_JSON NEW_OUTPUT_DIRECTORY".into());
    }
    let root = PathBuf::from(&args[1]);
    let output = PathBuf::from(&args[3]);
    if output.exists() {
        return Err("new output required".into());
    }
    let report: Value = serde_json::from_slice(&fs::read(root.join("report.json"))?)?;
    if report["status"] != "complete" {
        return Err("complete collection required".into());
    }
    if report["partition"] != "training_pool_unlabeled"
        && report["partition"] != "evaluation_unlabeled"
    {
        return Err("collection partition missing or invalid".into());
    }
    let catalog_bytes = fs::read(&args[2])?;
    let catalog: Value = serde_json::from_slice(&catalog_bytes)?;
    let (names, families) = name_indexes(&catalog)?;
    fs::create_dir_all(output.join("shop-strips"))?;
    let mut ocr_cache = HashMap::<String, String>::new();
    let mut ocr_calls = 0u64;
    let started = std::time::Instant::now();
    let mut frames = Vec::new();
    let mut transitions = Vec::new();
    let mut previous: Option<(
        u64,
        u64,
        Vec<Option<Vec<String>>>,
        Vec<Option<f32>>,
        Vec<Option<Vec<String>>>,
        Vec<f32>,
        Value,
    )> = None;
    let mut name_runs: [Option<NameRun>; 5] = std::array::from_fn(|_| None);
    let mut bench_history: VecDeque<(u64, Value)> = VecDeque::new();
    for line in fs::read_to_string(root.join("observations.jsonl"))?.lines() {
        let frame: Value = serde_json::from_str(line)?;
        if frame["source_id"] != report["source_id"] {
            return Err("mixed source".into());
        }
        let Some(file) = frame["review_frame"].as_str() else {
            continue;
        };
        let time = frame["source_seconds_nominal"]
            .as_u64()
            .ok_or("timestamp")?;
        let time_ms = frame["source_milliseconds_nominal"]
            .as_u64()
            .unwrap_or(time.checked_mul(1000).ok_or("timestamp overflow")?);
        if time_ms / 1000 != time {
            return Err("inconsistent millisecond timestamp".into());
        }
        let rgb = image::open(root.join(file))?.to_rgb8();
        if (rgb.width(), rgb.height()) != (1920, 1080)
            || frame["frame_pixel_sha256"] != format!("{:x}", Sha256::digest(rgb.as_raw()))
        {
            return Err("review frame geometry/pixels mismatch".into());
        }
        let portrait_brightness = shop_portrait_brightness(&rgb);
        let strip = image::imageops::crop_imm(&rgb, 552, 1039, 1002, 39).to_image();
        // Keep pale name glyphs; card borders and price icons break OCR lines.
        let mut mask = image::GrayImage::from_pixel(1002, 39, image::Luma([255]));
        for y in 6..31 {
            for x in 0..1002 {
                let p = strip.get_pixel(x, y).0;
                let lo = *p.iter().min().unwrap();
                let hi = *p.iter().max().unwrap();
                if (5..165).contains(&(x % 202)) && lo >= 130 && hi - lo <= 100 {
                    mask.put_pixel(x, y, image::Luma([0]));
                }
            }
        }
        let strip = image::imageops::resize(&mask, 2004, 78, image::imageops::FilterType::Triangle);
        let path = output.join(format!("shop-strips/{time_ms}.png"));
        strip.save(&path)?;
        // Identical prepared pixels imply identical OCR input. Reuse text only;
        // timestamps, neighboring cards and bench proposals remain frame-local.
        let strip_sha = format!("{:x}", Sha256::digest(strip.as_raw()));
        let tsv = if let Some(tsv) = ocr_cache.get(&strip_sha) {
            tsv.clone()
        } else {
            let result = Command::new("tesseract")
                .arg(&path)
                .args(["stdout", "-l", "eng", "--psm", "6", "tsv"])
                .env("OMP_THREAD_LIMIT", "1")
                .output()?;
            if !result.status.success() {
                return Err("shop OCR failed".into());
            }
            let tsv = String::from_utf8(result.stdout)?;
            if ocr_cache.len() >= 1024 {
                ocr_cache.clear();
            }
            ocr_cache.insert(strip_sha, tsv.clone());
            ocr_calls += 1;
            tsv
        };
        let words = slot_words(&tsv);
        let matched: Vec<_> = words
            .iter()
            .map(|w| match_name(w, &names, &families))
            .collect();
        let identities: Vec<_> = matched
            .iter()
            .map(|m| m.as_ref().map(|(ids, _)| ids.clone()))
            .collect();
        let confidences: Vec<_> = matched
            .iter()
            .map(|m| m.as_ref().map(|(_, confidence)| *confidence))
            .collect();
        // Untranslated text can establish an unchanged neighboring card. It
        // cannot supply an identity for the disappearing card itself.
        let anchors: Vec<_> = words
            .iter()
            .map(|w| {
                if w.is_empty() || w.iter().any(|(_, c)| !c.is_finite() || *c < 70.) {
                    return None;
                }
                let text: String = w
                    .iter()
                    .map(|(s, _)| s.as_str())
                    .collect::<Vec<_>>()
                    .join(" ")
                    .chars()
                    .filter(|c| c.is_alphanumeric())
                    .flat_map(char::to_lowercase)
                    .collect();
                if text.len() < 3 {
                    None
                } else {
                    Some(vec![text])
                }
            })
            .collect();
        let cards:Vec<_>=matched.iter().zip(&words).enumerate().map(|(slot,(m,w))|json!({"slot":slot,"unit_candidates":m.as_ref().map(|x|&x.0),"ocr_name_confidence":m.as_ref().map(|x|x.1),"ocr_words":w})).collect();
        if let Some((
            old_time_ms,
            old_time,
            old_ids,
            old_confidences,
            old_anchors,
            old_portraits,
            old_frame,
        )) = &previous
        {
            let gap_ms = time_ms
                .checked_sub(*old_time_ms)
                .ok_or("nonmonotonic source times")?;
            if gap_ms == 0 {
                return Err("duplicate source timestamp".into());
            }
            for slot in disappearances(old_anchors, &anchors, gap_ms) {
                if old_ids[slot].is_none()
                    || !portrait_disappeared(old_portraits[slot], portrait_brightness[slot])
                {
                    continue;
                }
                let run = name_runs[slot]
                    .as_ref()
                    .filter(|run| old_ids[slot].as_ref() == Some(&run.ids));
                let (reference_ms, reference) =
                    bench_reference(&bench_history, time_ms).unwrap_or((*old_time_ms, old_frame));
                transitions.push(json!({"source_id":report["source_id"],"partition":report["partition"],"before_seconds":old_time,"after_seconds":time,
                    "before_milliseconds":old_time_ms,"after_milliseconds":time_ms,
                    "before_frame":old_frame["review_frame"],"after_frame":file,"before_pixel_sha256":old_frame["frame_pixel_sha256"],"after_pixel_sha256":frame["frame_pixel_sha256"],
                    "shop_slot":slot,"portrait_brightness_before":old_portraits[slot],"portrait_brightness_after":portrait_brightness[slot],
                    "shop_unit_candidates":old_ids[slot],"shop_ocr_name_confidence":old_confidences[slot],
                    "shop_name_distinct_frame_confirmations":run.map_or(0, |run| run.confirmations),
                    "shop_name_min_ocr_confidence":run.map(|run| run.min_good_confidence),
                    "shop_name_confirmation_span_ms":run.map(|run| old_time_ms.saturating_sub(run.first_ms)),
                    "bench_reference_milliseconds":reference_ms,
                    "new_bench_proposals":new_bench_proposals(reference,&frame),
                    "purchase_confirmed":false,"crop_identity_confirmed":false,"review_required":true,"training_label":null}));
            }
        }
        for slot in 0..5 {
            name_runs[slot] = advance_name_run(
                name_runs[slot].take(),
                identities[slot].as_ref(),
                confidences[slot],
                portrait_brightness[slot],
                time_ms,
                frame["frame_pixel_sha256"].as_str().ok_or("frame hash")?,
            );
        }
        frames.push(json!({"source_seconds":time,"source_milliseconds":time_ms,"review_frame":file,"frame_pixel_sha256":frame["frame_pixel_sha256"],"portrait_brightness":portrait_brightness,"cards":cards}));
        bench_history.push_back((time_ms, frame.clone()));
        while bench_history
            .front()
            .is_some_and(|(ms, _)| time_ms.saturating_sub(*ms) > 1000)
        {
            bench_history.pop_front();
        }
        previous = Some((
            time_ms,
            time,
            identities,
            confidences,
            anchors,
            portrait_brightness,
            frame,
        ));
        if frames.len() % 100 == 0 {
            let progress = json!({"status":"running", "frames":frames.len(), "ocr_calls":ocr_calls,
                "transition_proposals":transitions.len(), "elapsed_seconds":started.elapsed().as_secs_f64()});
            fs::write(
                output.join("progress.json"),
                serde_json::to_vec_pretty(&progress)?,
            )?;
            println!("{progress}");
        }
    }
    fs::write(
        output.join("shop-observations.json"),
        serde_json::to_vec_pretty(&frames)?,
    )?;
    fs::write(
        output.join("transition-proposals.json"),
        serde_json::to_vec_pretty(&transitions)?,
    )?;
    let summary = json!({"status":"complete","ocr_cache_capacity":1024,"ocr_calls":ocr_calls,"ocr_cache_hits":frames.len() as u64-ocr_calls,"elapsed_seconds":started.elapsed().as_secs_f64(),"source_id":report["source_id"],"partition":report["partition"],"frames":frames.len(),"transition_proposals":transitions.len(),"automatically_labeled":0,
        "catalog_sha256":format!("{:x}",Sha256::digest(catalog_bytes)),"runtime_approved":false,
        "limitations":["Fixed 1920x1080 full-HUD shop geometry and English OCR; zoom, translated names and overlays can miss cards.",
        "Three neighboring OCR names must remain unchanged within two seconds and portrait brightness must fall from at least 10% to at most 2%; overlays can still imitate an empty card.",
        "New bench proposals remain evidence cues until autonomous consensus proves a unique purchase-to-bench binding.",
        "Generic Lux retains every catalog variant; ambiguous variants remain unknown."]});
    fs::write(
        output.join("report.json"),
        serde_json::to_vec_pretty(&summary)?,
    )?;
    fs::write(
        output.join("progress.json"),
        serde_json::to_vec_pretty(&summary)?,
    )?;
    println!("{summary}");
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("SHOP_TRANSITION_ERROR: {e}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn unreadable_names_do_not_imply_empty_cards() {
        assert!(portrait_disappeared(0.7, 0.0));
        assert!(!portrait_disappeared(0.7, 0.4));
        assert!(!portrait_disappeared(0.0, 0.0));
        assert!(!portrait_disappeared(f32::NAN, 0.0));
    }
    #[test]
    fn name_strip_ignores_observed_cursor_and_price_fragments() {
        let tsv = "header\n5\t1\t1\t1\t1\t1\t20\t24\t56\t26\t96.5\tLux\n5\t1\t1\t1\t1\t2\t218\t12\t26\t14\t40.2\tad\n5\t1\t1\t1\t1\t3\t728\t46\t4\t2\t58.2\t.\n";
        let words = slot_words(tsv);
        assert_eq!(words[0], vec![("Lux".into(), 96.5)]);
        assert!(words[1..].iter().all(Vec::is_empty));
    }
    #[test]
    fn rerolls_sparse_time_and_insufficient_anchors_do_not_propose_purchases() {
        let before = (0..5)
            .map(|i| Some(vec![i.to_string()]))
            .collect::<Vec<_>>();
        let mut after = before.clone();
        after[2] = None;
        assert_eq!(disappearances(&before, &after, 250), vec![2]);
        assert!(disappearances(&before, &after, 3000).is_empty());
        after[0] = Some(vec!["rerolled".into()]);
        after[1] = None;
        assert!(disappearances(&before, &after, 250).is_empty());
        assert!(disappearances(&before, &before, 250).is_empty());
    }
    #[test]
    fn moving_existing_bench_bars_are_not_new_units() {
        let before = json!({"units":[{"box":[950,700,1078,844]}]});
        let after = json!({"units":[{"box":[955,703,1083,847]},{"box":[1100,700,1228,844]},{"box":[1100,400,1228,544]}]});
        let p = new_bench_proposals(&before, &after);
        assert_eq!(p.len(), 1);
        assert_eq!(p[0]["box"][0], 1100);
    }
    #[test]
    fn stable_name_survives_one_occluded_frame_without_counting_it() {
        let id = vec!["DA_18_ElderDragon".into()];
        let mut run = None;
        for (time, hash) in [(1000, "a"), (1250, "b"), (1500, "c")] {
            run = advance_name_run(run, Some(&id), Some(95.), 0.9, time, hash);
        }
        run = advance_name_run(run, None, None, 0.9, 1750, "d");
        run = advance_name_run(run, Some(&id), Some(79.), 0.9, 2000, "e");
        let run = run.unwrap();
        assert_eq!(run.confirmations, 3);
        assert_eq!(run.min_good_confidence, 95.);
        assert_eq!(run.first_ms, 1000);
        assert!(advance_name_run(Some(run), None, None, 0., 2250, "f").is_none());
    }
    #[test]
    fn name_run_starts_confidence_at_first_strong_read() {
        let id = vec!["DA_18_Ashe".into()];
        let run = advance_name_run(None, Some(&id), Some(79.), 0.9, 1000, "a");
        let run = advance_name_run(run, Some(&id), Some(96.), 0.9, 1250, "b").unwrap();
        assert_eq!(run.confirmations, 1);
        assert_eq!(run.min_good_confidence, 96.);
    }
    #[test]
    fn bench_reference_uses_the_last_unoccluded_board() {
        let mut history = VecDeque::from([
            (
                1000,
                json!({"units":[{"box":[462,736,590,880]},{"box":[1073,694,1201,838]}]}),
            ),
            (1250, json!({"units":[{"box":[462,736,590,880]}]})),
        ]);
        let (time, frame) = bench_reference(&history, 1500).unwrap();
        assert_eq!(time, 1000);
        let after = json!({"units":[{"box":[462,736,590,880]},{"box":[1073,694,1201,838]},{"box":[1195,703,1323,847]}]});
        assert_eq!(new_bench_proposals(frame, &after).len(), 1);
        history.push_back((2500, json!({"units":[]})));
        assert_eq!(bench_reference(&history, 2500).unwrap().0, 2500);
    }
}
