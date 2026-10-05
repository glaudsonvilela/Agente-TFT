//! Recover verified review frames across completed and interrupted collection
//! segments. Encoder files are deliberately not reconstructed or certified.
use agente_tft_capture_core::{FrameEnvelope, PixelFormat, PixelRect};
use agente_tft_image_preprocess::unit_features::UnitCrop;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeMap,
    fs,
    path::{Path, PathBuf},
};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn string<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str().ok_or_else(|| format!("missing {k}").into())
}
fn records(text: &str, interrupted: bool) -> Result<(Vec<Value>, bool)> {
    let lines: Vec<_> = text.split_inclusive('\n').collect();
    let mut rows = Vec::new();
    for (i, line) in lines.iter().enumerate() {
        match serde_json::from_str(line) {
            Ok(row) => rows.push(row),
            Err(_) if interrupted && i + 1 == lines.len() && !line.ends_with('\n') => {
                return Ok((rows, true))
            }
            Err(e) => return Err(e.into()),
        }
    }
    Ok((rows, false))
}
fn local_file(root: &Path, relative: &str) -> Result<PathBuf> {
    let p = root.join(relative).canonicalize()?;
    if !p.starts_with(root) {
        return Err("collection path escapes its source directory".into());
    }
    Ok(p)
}
fn verify_frame(root: &Path, row: &mut Value) -> Result<usize> {
    let path = local_file(root, string(row, "review_frame")?)?;
    let rgb = image::open(&path)?.to_rgb8();
    if (rgb.width(), rgb.height()) != (1920, 1080)
        || row["frame_pixel_sha256"] != hash(rgb.as_raw())
    {
        return Err("review frame pixel hash/geometry mismatch".into());
    }
    let frame = FrameEnvelope {
        frame_id: 0,
        captured_at_ms: 0,
        width: 1920,
        height: 1080,
        stride_bytes: 5760,
        pixel_format: PixelFormat::Rgb8,
        source_id: "review-reconciliation".into(),
        pixels: rgb.into_raw(),
    };
    row["review_frame"] = json!(path);
    let units = row["units"].as_array_mut().ok_or("units")?;
    for unit in units.iter_mut() {
        let b = unit["box"].as_array().ok_or("box")?;
        let b: Vec<u32> = b
            .iter()
            .map(|v| {
                v.as_u64()
                    .and_then(|v| u32::try_from(v).ok())
                    .ok_or("coordinate")
            })
            .collect::<std::result::Result<_, _>>()?;
        if b.len() != 4
            || b[2].checked_sub(b[0]) != Some(128)
            || b[3].checked_sub(b[1]) != Some(144)
        {
            return Err("native crop bounds".into());
        }
        let crop = UnitCrop::from_frame(
            &frame,
            PixelRect {
                x: b[0],
                y: b[1],
                width: 128,
                height: 144,
            },
        )?;
        if unit["pixel_sha256"] != hash(&crop.rgb) {
            return Err("crop/frame association mismatch".into());
        }
        let path = local_file(root, string(unit, "crop")?)?;
        let stored = image::open(&path)?.to_rgb8();
        if (stored.width(), stored.height()) != (128, 144)
            || unit["pixel_sha256"] != hash(stored.as_raw())
        {
            return Err("stored crop mismatch".into());
        }
        unit["crop"] = json!(path);
        let obj = unit.as_object_mut().ok_or("unit object")?;
        if let Some(index) = obj.remove("embedding_row") {
            obj.insert("original_embedding_row_unverified".into(), index);
        }
    }
    Ok(units.len())
}
fn verify_grid(
    times: impl Iterator<Item = u64>,
    start: u64,
    duration: u64,
    interval: u64,
) -> Result<()> {
    if interval == 0 || duration == 0 {
        return Err("positive interval and duration required".into());
    }
    let expected = duration.div_ceil(interval);
    let times: Vec<_> = times.collect();
    if times.len() as u64 != expected {
        return Err("missing/extra review frames".into());
    }
    for (i, t) in times.into_iter().enumerate() {
        if start.checked_add((i as u64).checked_mul(interval).ok_or("grid overflow")?) != Some(t) {
            return Err("review timestamp gap".into());
        }
    }
    Ok(())
}
fn run() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 || args[1] != "--spec" {
        return Err("use --spec RECONCILIATION_JSON".into());
    }
    let bytes = fs::read(&args[2])?;
    let spec: Value = serde_json::from_slice(&bytes)?;
    let output = PathBuf::from(string(&spec, "output")?);
    if output.exists() {
        return Err("new output required".into());
    }
    let source = string(&spec, "source_id")?;
    let mut merged = BTreeMap::new();
    let mut provenance = Vec::new();
    let mut crops = 0;
    for part in spec["parts"].as_array().ok_or("parts")? {
        let root = PathBuf::from(part.as_str().ok_or("part path")?).canonicalize()?;
        let complete = root.join("report.json").exists();
        if complete {
            let r: Value = serde_json::from_slice(&fs::read(root.join("report.json"))?)?;
            if r["status"] != "complete" || r["source_id"] != source {
                return Err("incomplete or wrong source report".into());
            }
        } else {
            let marker: Value = serde_json::from_slice(&fs::read(root.join("INTERRUPTED.json"))?)?;
            if marker["exit_code"].as_i64().is_none_or(|x| x == 0) {
                return Err("explicit terminal interruption record required".into());
            }
        }
        let raw = fs::read_to_string(root.join("observations.jsonl"))?;
        let (rows, tail) = records(&raw, !complete)?;
        let count = rows.len();
        for mut row in rows {
            if row["source_id"] != source {
                return Err("mixed source observations".into());
            }
            let time = row["source_seconds_nominal"].as_u64().ok_or("timestamp")?;
            crops += verify_frame(&root, &mut row)?;
            row["source_collection_directory"] = json!(root);
            row["source_collection_completed"] = json!(complete);
            row["original_frame_index"] = row["frame_index"].clone();
            if merged.insert(time, row).is_some() {
                return Err("overlapping segment timestamps".into());
            }
        }
        provenance.push(json!({"directory":root,"original_observations_sha256":hash(raw.as_bytes()),"completed":complete,"valid_records":count,"truncated_tail_ignored":tail}));
    }
    let n = |k: &str| spec[k].as_u64().ok_or("grid integer");
    verify_grid(
        merged.keys().copied(),
        n("start_seconds")?,
        n("duration_seconds")?,
        n("sample_interval_seconds")?,
    )?;
    let mut observations = String::new();
    for (i, (_, mut row)) in merged.into_iter().enumerate() {
        row["frame_index"] = json!(i);
        observations.push_str(&serde_json::to_string(&row)?);
        observations.push('\n');
    }
    let report = json!({"schema_version":1,"status":"review_frames_complete","source_id":source,"source_url":spec["source_url"],
        "spec_sha256":hash(&bytes),"observations_sha256":hash(observations.as_bytes()),"frames":observations.lines().count(),"unit_crops":crops,
        "start_seconds":spec["start_seconds"],"duration_seconds":spec["duration_seconds"],"sample_interval_seconds":spec["sample_interval_seconds"],
        "parts":provenance,"pixels_and_crop_associations_verified":true,"embeddings_reconstructed":false,"training_performed":false,"runtime_approved":false,
        "limitations":["This index certifies saved review frames and crop pixels, not interrupted embedding files.","No identity labels are inferred or confirmed by file integrity checks."]});
    fs::create_dir_all(&output)?;
    fs::write(output.join("observations.jsonl"), observations)?;
    fs::write(
        output.join("report.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    println!(
        "{}",
        json!({"frames":report["frames"],"unit_crops":crops,"status":report["status"]})
    );
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("RECONCILE_COLLECTION_ERROR: {e}");
        std::process::exit(1);
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn tolerates_only_a_terminal_truncated_record_in_explicitly_interrupted_input() {
        let input = "{\"n\":1}\n{\"n\":";
        let (r, t) = records(input, true).unwrap();
        assert_eq!(r.len(), 1);
        assert!(t);
        assert!(records(input, false).is_err());
        assert!(records("bad\n{\"n\":1}\n", true).is_err());
        assert!(records("{\"n\":1}\nbad\n", true).is_err());
        assert!(!records("{\"n\":1}", true).unwrap().1);
    }
    #[test]
    fn timestamps_must_cover_the_requested_grid_without_gaps() {
        assert!(verify_grid([0, 20, 40].into_iter(), 0, 60, 20).is_ok());
        assert!(verify_grid([0, 20, 60].into_iter(), 0, 60, 20).is_err());
        assert!(verify_grid([0, 20].into_iter(), 0, 60, 20).is_err());
        assert!(verify_grid([0].into_iter(), 0, 60, 0).is_err());
    }
}
