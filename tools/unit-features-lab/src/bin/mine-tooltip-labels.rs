//! Find explicit on-screen unit names to speed up annotation. Cyan outlines only
//! propose associations; a tooltip name is not automatically a crop's label.
use serde_json::{json, Value};
use std::{collections::BTreeMap, fs, path::PathBuf, process::Command};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn canonical(s: &str) -> String {
    s.chars()
        .filter(|c| c.is_alphanumeric())
        .flat_map(char::to_lowercase)
        .collect()
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
    if report["status"] != "complete" {
        return Err("complete source required".into());
    }
    let catalog: Value = serde_json::from_slice(&fs::read(&a[2])?)?;
    let mut names: BTreeMap<String, Vec<String>> = BTreeMap::new();
    for unit in catalog["entries"].as_array().ok_or("catalog entries")? {
        let name = canonical(unit["name"].as_str().ok_or("name")?);
        names
            .entry(name)
            .or_default()
            .push(unit["id"].as_str().ok_or("id")?.into());
    }
    fs::create_dir_all(out.join("rois"))?;
    let mut proposals = Vec::new();
    let mut scanned = 0;
    for line in fs::read_to_string(root.join("observations.jsonl"))?.lines() {
        let frame: Value = serde_json::from_str(line)?;
        let Some(file) = frame["review_frame"].as_str() else {
            continue;
        };
        let rgb = image::open(root.join(file))?.to_rgb8();
        if rgb.width() != 1920 || rgb.height() != 1080 {
            return Err("frame geometry".into());
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
            .filter_map(|words| {
                let (word, confidence) = words.first()?;
                if *confidence < 70. {
                    return None;
                }
                let ids = names.get(&canonical(word))?;
                if ids.len() != 1 {
                    return None;
                }
                Some((ids[0].clone(), *confidence))
            })
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
            units.push(json!({"crop":u["crop"],"pixel_sha256":u["pixel_sha256"],"marker_id":u["marker_id"],"box":u["box"],"cyan_pixels":cyan}));
        }
        units.sort_by(|a, b| b["cyan_pixels"].as_u64().cmp(&a["cyan_pixels"].as_u64()));
        proposals.push(json!({"source_id":report["source_id"],"source_seconds_nominal":frame["source_seconds_nominal"],
            "frame":file,"frame_pixel_sha256":frame["frame_pixel_sha256"],"tooltip_unit_id":found[0].0,"ocr_name_confidence":found[0].1,
            "tooltip_text":text,"association_candidates":units,"crop_identity_confirmed":false,
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
        serde_json::to_vec_pretty(&json!({"source_id":report["source_id"],"scanned":scanned,
        "proposals":proposals.len(),"automatically_labeled":0,"limitations":["OCR names require review; cyan pixel count is not semantic selection detection.",
        "Portuguese catalog names are matched literally; English aliases and multiword names can be missed.",
        "This is annotation assistance, not a runtime recognition or coaching decision."]}))?,
    )?;
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("TOOLTIP_MINING_ERROR: {e}");
        std::process::exit(1);
    }
}
