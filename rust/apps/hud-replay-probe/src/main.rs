mod media;
mod probe;

use std::{env, fs, io::Write, path::{Path, PathBuf}, process::ExitCode};
use agente_tft_hud_runtime::HudLayout;
use agente_tft_ocr_tesseract::TesseractOcr;
use serde_json::{json, Value};
use probe::{LabelKind, Plan};

const USAGE: &str = "Usage: agente-tft-hud-replay-probe <video> <hud-layout.json> <labels.json> [--prelabels] [--numeric-gray] [--image-root <annotation-directory>] [--output <NEW-report.json>]\nOnly labeled timestamps are decoded; no full replay scan. --prelabels reports agreement, NEVER ground-truth accuracy. --image-root reads the existing image paths relative to that directory; video then identifies the source only.";

fn main() -> ExitCode {
    match run() {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::from(2),
        Err(e) => { eprintln!("HUD_PROBE_ERROR: {e}"); ExitCode::FAILURE }
    }
}

fn read_json(path: &Path) -> Result<Value, String> {
    let text = fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))
}

fn run() -> Result<bool, String> {
    let mut args = env::args().skip(1);
    let first = args.next().ok_or(USAGE)?;
    if first == "--help" || first == "-h" { println!("{USAGE}"); return Ok(true); }
    let video = PathBuf::from(first);
    let layout_path = PathBuf::from(args.next().ok_or(USAGE)?);
    let labels_path = PathBuf::from(args.next().ok_or(USAGE)?);
    let mut kind = LabelKind::Annotations;
    let mut image_root = None;
    let mut output_path = None;
    let mut numeric_gray = false;
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--numeric-gray" if !numeric_gray => numeric_gray = true,
            "--prelabels" if kind == LabelKind::Annotations => kind = LabelKind::Prelabels,
            "--image-root" if image_root.is_none() => image_root = Some(PathBuf::from(args.next().ok_or("missing --image-root value")?)),
            "--output" if output_path.is_none() => output_path = Some(PathBuf::from(args.next().ok_or("missing --output value")?)),
            _ => return Err(format!("unknown or duplicate argument {arg}\n{USAGE}")),
        }
    }
    let layout: HudLayout = serde_json::from_value(read_json(&layout_path)?).map_err(|e| e.to_string())?;
    probe::validate_layout(&layout)?;
    let plan = Plan::parse(&read_json(&labels_path)?, kind, &video)?;
    let image_root = image_root.map(|p| p.canonicalize().map_err(|e| format!("image root: {e}"))).transpose()?;
    if image_root.is_none() && !video.is_file() { return Err(format!("video not found: {}", video.display())); }
    if let Some(root) = &image_root {
        if !root.is_dir() { return Err("image root must be a directory".into()); }
        // Validate confinement before launching OCR; missing images become explicit decode errors.
        for sample in &plan.samples { media::relative_image_path(root, sample.image.as_deref())?; }
    }
    let mut engine = TesseractOcr::default();
    if numeric_gray { engine = engine.with_numeric_gray(); }
    if !engine.available() { return Err("tesseract is unavailable; install it before probing".into()); }
    // Reserve exclusively: never overwrite labels, an earlier report, or another input.
    let mut output = match &output_path {
        Some(path) => Some(fs::OpenOptions::new().write(true).create_new(true).open(path).map_err(|e| format!("cannot create NEW report {}: {e}", path.display()))?),
        None => None,
    };
    let mut records = Vec::new();
    for (index, sample) in plan.samples.iter().enumerate() {
        eprintln!("HUD_PROBE {}/{} timestamp_ms={}", index+1, plan.samples.len(), sample.timestamp_ms);
        let decoded = match &image_root {
            Some(root) => media::relative_image_path(root, sample.image.as_deref())
                .and_then(|path| media::decode(&path, None, sample.timestamp_ms)),
            None => media::decode(&video, Some(sample.timestamp_ms), sample.timestamp_ms),
        }.and_then(|frame| {
            if (frame.width, frame.height) != (layout.reference_width, layout.reference_height) {
                Err(format!("resolution mismatch: {}x{} vs {}x{}; no automatic resize", frame.width, frame.height, layout.reference_width, layout.reference_height))
            } else { Ok(frame) }
        });
        for expected in &sample.expected {
            let mut record = match &decoded {
                Ok(frame) => probe::evaluate(&mut engine, &layout, frame, sample.timestamp_ms, expected, kind),
                Err(error) => probe::failure(sample.timestamp_ms, expected, kind, "decode_error", error),
            };
            record["ocr_profile"] = json!(engine.profile_for(expected.field));
            println!("{record}");
            records.push(record);
        }
    }
    let complete = records.iter().all(|r| r["error"].is_null());
    let summary = json!({
        "type": "summary", "schema_version": 1,
        "ocr_profile": if numeric_gray { "numeric_gray_v3" } else { "legacy_v2" },
        "label_kind": kind.name(), "metric_kind": kind.metric_name(),
        "promotion_gate": "not_evaluated_diagnostic_only", "execution_complete": complete,
        "source_video": plan.source_video, "video_argument": video,
        "source_identity_check": "basename_only", "video_sha256_verified": false,
        "labels": labels_path, "layout_path": layout_path, "layout": layout,
        "image_root": image_root,
        "frame_time_basis": if image_root.is_some() { "annotation_image_timestamp" } else { "requested_ffmpeg_seek_timestamp" },
        "decoded_pts_verified": false, "temporal_consensus": false,
        "frames_in_labels": plan.frames_in_labels, "frames_selected": plan.samples.len(),
        "frames_skipped_without_hud_labels": plan.frames_in_labels-plan.samples.len(),
        "records": records.len(), "fields": probe::summarize(&records, kind)
    });
    if let Some(file) = output.as_mut() {
        serde_json::to_writer_pretty(&mut *file, &json!({"summary":summary, "records":records})).map_err(|e| e.to_string())?;
        file.write_all(b"\n").map_err(|e| e.to_string())?;
        file.sync_all().map_err(|e| e.to_string())?;
    }
    println!("{summary}");
    if let Some(path) = output_path { eprintln!("HUD_PROBE_REPORT={}", path.display()); }
    Ok(complete)
}
