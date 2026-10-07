//! Find explicit on-screen unit names to speed up annotation. Cyan outlines only
//! propose associations; a tooltip name is not automatically a crop's label.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, fs, path::PathBuf, process::Command};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
use agente_tft_unit_features_lab::ocr_names::{match_name, name_indexes, Names};

fn tooltip_name_match(
    words: &[(String, f32)],
    names: &Names,
    families: &Names,
) -> Option<(Vec<String>, f32)> {
    if let Some(found) = match_name(words, names, families) {
        return Some(found);
    }
    // The portrait row ends with a coin icon and a one-digit price. Tesseract
    // frequently reads this as `a3`, `e9`, `ain`, or `a`. Remove just that short
    // final glyph group; never truncate an arbitrary name or sentence.
    let (last, prefix) = words.split_last()?;
    let suffix = last.0.as_str();
    if !(suffix.starts_with('a') || suffix.starts_with('e'))
        || suffix.len() > 3
        || prefix.is_empty()
    {
        return None;
    }
    match_name(prefix, names, families)
}

// The selection halo is a broad ellipse below the unit. Some arenas render it
// saturated cyan, others pale blue. Counting blue anywhere in a crop mistakes
// spells and the unit's own colours for a selection. This is an association cue.
fn selection_ring(frame: &image::RgbImage, box_xyxy: &[Value]) -> Option<Value> {
    if box_xyxy.len() != 4 {
        return None;
    }
    let (Some(x1), Some(y1), Some(x2), Some(_)) = (
        box_xyxy[0].as_i64(),
        box_xyxy[1].as_i64(),
        box_xyxy[2].as_i64(),
        box_xyxy[3].as_i64(),
    ) else {
        return None;
    };
    let cx = (x1 + x2) / 2;
    let mut rows = [[0u32; 95]; 2];
    let mut totals = [0u32; 2];
    let mut left = [0u32; 2];
    let mut right = [0u32; 2];
    for dy in 0..95i64 {
        let y = y1 + 70 + dy;
        if y < 0 || y >= frame.height() as i64 {
            continue;
        }
        for dx in 0..110i64 {
            let x = cx - 55 + dx;
            if x < 0 || x >= frame.width() as i64 {
                continue;
            }
            let p = frame.get_pixel(x as u32, y as u32).0;
            let masks = [
                p[0] < 130 && p[1] > 160 && p[2] > 170 && p[1] as i16 - p[0] as i16 > 70,
                p[1] > 170 && p[2] > 180 && p[2] as i16 - p[0] as i16 > 25,
            ];
            for (channel, present) in masks.into_iter().enumerate() {
                if present {
                    totals[channel] += 1;
                    rows[channel][dy as usize] += 1;
                    if dx < 35 {
                        left[channel] += 1;
                    }
                    if dx >= 75 {
                        right[channel] += 1;
                    }
                }
            }
        }
    }
    let percentile = |channel: usize, numerator: u32| -> usize {
        let target = (totals[channel] * numerator).div_ceil(100);
        let mut sum = 0u32;
        for (i, count) in rows[channel].iter().enumerate() {
            sum += count;
            if sum >= target {
                return i;
            }
        }
        94
    };
    let span = |channel: usize| -> usize {
        if totals[channel] > 0 {
            percentile(channel, 90) - percentile(channel, 10)
        } else {
            0
        }
    };
    let cyan_pass = totals[0] >= 250 && left[0] >= 40 && right[0] >= 40 && span(0) >= 30;
    // Pale blue is common in the brighter arenas and ordinary highlights;
    // require substantially more coverage than the saturated cyan channel.
    let pale_pass = totals[1] >= 1000 && left[1] >= 100 && right[1] >= 100 && span(1) >= 30;
    Some(json!({"cyan_pixels":totals[0],"pale_blue_pixels":totals[1],
            "left_arc_pixels":left[0],"right_arc_pixels":right[0],"vertical_span_p10_p90":span(0),
            "pale_left_arc_pixels":left[1],"pale_right_arc_pixels":right[1],"pale_vertical_span_p10_p90":span(1),
            "selection_signal_pixels":if pale_pass {totals[1]} else {totals[0]},
            "selection_halo_style":if pale_pass {"pale_blue"} else if cyan_pass {"saturated_cyan"} else {"none"},
            "shape_pass":cyan_pass || pale_pass}))
}
fn run() -> Result<()> {
    let a: Vec<_> = std::env::args().collect();
    if a.len() != 4 {
        return Err("use COLLECTION_DIRECTORY CATALOG_JSON NEW_OUTPUT_DIRECTORY".into());
    }
    let root = PathBuf::from(&a[1]);
    let out = PathBuf::from(&a[3]);
    if out.exists() {
        return Err("new output required".into());
    }
    let report: Value = serde_json::from_slice(&fs::read(root.join("report.json"))?)?;
    if report["status"] != "complete" && report["status"] != "review_frames_complete" {
        return Err("complete source or verified review-frame index required".into());
    }
    let catalog: Value = serde_json::from_slice(&fs::read(&a[2])?)?;
    let (names, families) = name_indexes(&catalog)?;
    fs::create_dir_all(out.join("rois"))?;
    let mut proposals = Vec::new();
    let mut scanned = 0;
    let observations = fs::read_to_string(root.join("observations.jsonl"))?;
    if report["status"] == "review_frames_complete"
        && report["observations_sha256"] != format!("{:x}", Sha256::digest(observations.as_bytes()))
    {
        return Err("reconciled observation checksum mismatch".into());
    }
    for line in observations.lines() {
        let frame: Value = serde_json::from_str(line)?;
        if frame["source_id"] != report["source_id"] {
            return Err("mixed review source".into());
        }
        let Some(file) = frame["review_frame"].as_str() else {
            continue;
        };
        let rgb = image::open(root.join(file))?.to_rgb8();
        if rgb.width() != 1920 || rgb.height() != 1080 {
            return Err("frame geometry".into());
        }
        if frame["frame_pixel_sha256"] != format!("{:x}", Sha256::digest(rgb.as_raw())) {
            return Err("review frame pixel checksum mismatch".into());
        }
        let roi = image::imageops::crop_imm(&rgb, 1650, 170, 270, 660).to_image();
        let roi_path = out.join(format!("rois/{}.png", frame["source_seconds_nominal"]));
        roi.save(&roi_path)?;
        let result = Command::new("tesseract")
            .arg(&roi_path)
            .args(["stdout", "-l", "eng", "--psm", "6", "tsv"])
            .env("OMP_THREAD_LIMIT", "1")
            .output()?;
        if !result.status.success() {
            return Err("tooltip OCR failed".into());
        }
        scanned += 1;
        let tsv = String::from_utf8(result.stdout)?;
        let mut lines: BTreeMap<String, Vec<(String, f32)>> = BTreeMap::new();
        for row in tsv.lines().skip(1) {
            let c: Vec<_> = row.splitn(12, '\t').collect();
            if c.len() == 12 && c[0] == "5" && !c[11].is_empty() {
                lines
                    .entry(c[1..5].join(":"))
                    .or_default()
                    .push((c[11].into(), c[10].parse().unwrap_or(-1.)));
            }
        }
        let text = lines
            .values()
            .map(|line| {
                line.iter()
                    .map(|(s, _)| s.as_str())
                    .collect::<Vec<_>>()
                    .join(" ")
            })
            .collect::<Vec<_>>()
            .join("\n");
        // Champion panel anchors. Player names alone do not establish a tooltip.
        if !text.contains("Hex") || !text.contains('/') {
            continue;
        }
        let found: Vec<_> = lines
            .values()
            .filter_map(|words| tooltip_name_match(words, &names, &families))
            .collect();
        if found.len() != 1 {
            continue;
        }
        let mut units = Vec::new();
        for u in frame["units"].as_array().ok_or("units")? {
            let crop = image::open(root.join(u["crop"].as_str().ok_or("crop")?))?.to_rgb8();
            let cyan = crop
                .pixels()
                .filter(|p| {
                    p[0] < 100 && p[1] > 160 && p[2] > 160 && p[1] as i16 - p[0] as i16 > 80
                })
                .count();
            let ring = u["box"].as_array().and_then(|b| selection_ring(&rgb, b));
            units.push(json!({"crop":u["crop"],"pixel_sha256":u["pixel_sha256"],"marker_id":u["marker_id"],"box":u["box"],"cyan_pixels":cyan,
                "selection_ring":ring}));
        }
        units.sort_by(|a, b| b["cyan_pixels"].as_u64().cmp(&a["cyan_pixels"].as_u64()));
        let mut rings: Vec<_> = units
            .iter()
            .filter(|u| u["selection_ring"]["shape_pass"] == true)
            .collect();
        rings.sort_by_key(|u| {
            std::cmp::Reverse(
                u["selection_ring"]["selection_signal_pixels"]
                    .as_u64()
                    .unwrap_or(0),
            )
        });
        let dominant = rings.len() > 1
            && rings[0]["selection_ring"]["selection_signal_pixels"]
                .as_u64()
                .unwrap_or(0)
                >= 500
            && rings[0]["selection_ring"]["selection_signal_pixels"]
                .as_u64()
                .unwrap_or(0)
                .saturating_mul(2)
                >= rings[1]["selection_ring"]["selection_signal_pixels"]
                    .as_u64()
                    .unwrap_or(0)
                    .saturating_mul(5);
        let selected = if rings.len() == 1 || dominant {
            Some(rings[0]["marker_id"].clone())
        } else {
            None
        };
        proposals.push(json!({"source_id":report["source_id"],"source_seconds_nominal":frame["source_seconds_nominal"],
            "frame":file,"frame_pixel_sha256":frame["frame_pixel_sha256"],
            "tooltip_unit_id":if found[0].0.len()==1 {Some(&found[0].0[0])} else {None},
            "tooltip_unit_candidates":found[0].0,"identity_requires_variant_review":found[0].0.len()!=1,"ocr_name_confidence":found[0].1,
            "tooltip_text":text,"association_candidates":units,"selected_ring_marker_candidate":selected,
            "selection_ring_status":if rings.len()==1 {"unique_shape_candidate"} else if dominant {"dominant_shape_candidate"} else if rings.is_empty() {"no_shape_candidate"} else {"ambiguous_shape_candidates"},
            "crop_identity_confirmed":false,
            "review_required":true,"training_label":null}));
        println!(
            "{}",
            json!({"scanned":scanned,"tooltip_proposals":proposals.len()})
        );
        fs::write(
            out.join("proposals.json"),
            serde_json::to_vec_pretty(&proposals)?,
        )?;
    }
    fs::write(
        out.join("proposals.json"),
        serde_json::to_vec_pretty(&proposals)?,
    )?;
    fs::write(
        out.join("report.json"),
        serde_json::to_vec_pretty(
            &json!({"source_id":report["source_id"],"source_collection_status":report["status"],"scanned":scanned,
        "proposals":proposals.len(),"automatically_labeled":0,"limitations":["Selection-ring geometry is a cue only; it needs independent temporal repetition before an automatic training label.",
        "Catalog names are matched literally; untranslated aliases can be missed. Generic seasonal names retain every candidate ID.",
        "This is annotation assistance, not a runtime recognition or coaching decision."]}),
        )?,
    )?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn generic_lux_does_not_become_base_form_and_multiword_names_are_complete() {
        let catalog = json!({"entries":[
            {"id":"base","name":"Lux"},{"id":"elderwood","name":"Lux (Sabugueiro)"},
            {"id":"yi","name":"Master Yi"},{"id":"ornn","name":"Ornn"}]});
        let (exact, families) = name_indexes(&catalog).unwrap();
        let words = |s: &str| {
            s.split_whitespace()
                .map(|s| (s.to_owned(), 95.))
                .collect::<Vec<_>>()
        };
        assert_eq!(
            match_name(&words("Lux 5"), &exact, &families).unwrap().0,
            vec!["base", "elderwood"]
        );
        assert_eq!(
            match_name(&words("Lux (Sabugueiro)"), &exact, &families)
                .unwrap()
                .0,
            vec!["elderwood"]
        );
        assert_eq!(
            match_name(&words("Master Yi 4"), &exact, &families)
                .unwrap()
                .0,
            vec!["yi"]
        );
        assert!(match_name(&words("Lux player"), &exact, &families).is_none());
        assert!(match_name(&[("Lux".into(), 65.)], &exact, &families).is_none());
        assert_eq!(
            tooltip_name_match(&words("Master Yi a3"), &exact, &families)
                .unwrap()
                .0,
            vec!["yi"]
        );
        assert_eq!(
            tooltip_name_match(&words("Lux a"), &exact, &families)
                .unwrap()
                .0,
            vec!["base", "elderwood"]
        );
        assert_eq!(
            tooltip_name_match(&words("Ornn e9"), &exact, &families)
                .unwrap()
                .0,
            vec!["ornn"]
        );
        assert!(tooltip_name_match(&words("Lux player"), &exact, &families).is_none());
    }
}
fn main() {
    if let Err(e) = run() {
        eprintln!("TOOLTIP_MINING_ERROR: {e}");
        std::process::exit(1);
    }
}
