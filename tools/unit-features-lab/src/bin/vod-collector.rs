//! Source-linked collection from long VODs. Predictions are NOT training labels.
#![allow(dead_code)]
#[path = "../../../../rust/apps/board-replay-probe/src/bars.rs"]
mod bars;
use agente_tft_unit_features_lab as laboratory;
#[path = "../../../../rust/apps/board-replay-probe/src/profile.rs"]
mod profile;

use agente_tft_capture_core::{FrameEnvelope, PixelFormat, PixelRect};
use agente_tft_image_preprocess::unit_features::UnitCrop;
use ort::session::Session;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashSet},
    fs,
    io::{BufReader, BufWriter, Read, Write},
    path::PathBuf,
    process::{Child, Command, Stdio},
    time::Instant,
};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
struct Decoder(Child);
impl Drop for Decoder {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}
fn hash(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
fn string<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str().ok_or_else(|| format!("missing {k}").into())
}
fn sealed(path: &str, expected: &str) -> Result<Vec<u8>> {
    let bytes = fs::read(path)?;
    if hash(&bytes) != expected {
        return Err("asset hash mismatch".into());
    }
    Ok(bytes)
}
fn percentile(values: &[f64], p: f64) -> f64 {
    if values.is_empty() {
        return 0.;
    }
    let mut v = values.to_vec();
    v.sort_by(f64::total_cmp);
    v[((v.len() - 1) as f64 * p).round() as usize]
}
fn run() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 3 || args[1] != "--spec" {
        return Err("use --spec CONFIG.json".into());
    }
    let spec: Value = serde_json::from_slice(&fs::read(&args[2])?)?;
    let decode_mode = spec["decode_mode"].as_str().unwrap_or("all");
    if !["all", "keyframes"].contains(&decode_mode) {
        return Err("invalid decode mode".into());
    }
    if !["evaluation_unlabeled", "training_pool_unlabeled"].contains(&string(&spec, "partition")?)
        || spec["training_labels_allowed"] != false
    {
        return Err("partition policy".into());
    }
    let seconds = spec["duration_seconds"].as_u64().ok_or("duration")?;
    let interval = spec["sample_interval_seconds"].as_u64().ok_or("interval")?;
    let offset = spec["start_seconds"].as_u64().ok_or("start")?;
    if !(1..=43200).contains(&seconds) || !(1..=60).contains(&interval) {
        return Err("video time budget".into());
    }
    let out = PathBuf::from(string(&spec, "output")?);
    if out.exists() {
        return Err("new output directory required".into());
    }
    let meta: Value = serde_json::from_slice(&sealed(
        string(&spec, "gallery_metadata")?,
        string(&spec, "gallery_metadata_sha256")?,
    )?)?;
    let labels: Vec<String> = serde_json::from_value(meta["labels"].clone())?;
    let dim = meta["dimensions"].as_u64().ok_or("dimension")? as usize;
    if !(1..=4096).contains(&dim) || !(2..=4096).contains(&labels.len()) {
        return Err("gallery budget".into());
    }
    let raw = sealed(string(&spec, "gallery")?, string(&spec, "gallery_sha256")?)?;
    if raw.len() != labels.len() * dim * 4 {
        return Err("gallery shape".into());
    }
    let gallery: Vec<Vec<f32>> = raw
        .chunks_exact(dim * 4)
        .map(|b| {
            b.chunks_exact(4)
                .map(|v| f32::from_le_bytes(v.try_into().unwrap()))
                .collect()
        })
        .collect();
    if gallery.iter().flatten().any(|v| !v.is_finite()) {
        return Err("nonfinite gallery".into());
    }
    let references: Vec<_> = labels
        .iter()
        .zip(&gallery)
        .map(|(l, v)| (l.as_str(), v))
        .collect();
    sealed(string(&spec, "encoder")?, string(&spec, "encoder_sha256")?)?;
    ort::init_from(string(&spec, "onnxruntime")?).commit()?;
    let mut session = Session::builder()?
        .with_intra_threads(1)?
        .with_inter_threads(1)?
        .with_intra_op_spinning(false)?
        .with_inter_op_spinning(false)?
        .commit_from_file(string(&spec, "encoder")?)?;
    let spatial: profile::Profile =
        serde_json::from_slice(&fs::read(string(&spec, "board_profile")?)?)?;
    spatial.validate()?;
    let size = spec["input_size"].as_u64().ok_or("input size")? as usize;
    if !(64..=224).contains(&size) {
        return Err("encoder input budget".into());
    }
    let probe = Command::new("ffprobe")
        .args([
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            string(&spec, "input")?,
        ])
        .output()?;
    let video: Value = serde_json::from_slice(&probe.stdout)?;
    if !probe.status.success()
        || video["streams"][0]["width"] != 1920
        || video["streams"][0]["height"] != 1080
    {
        return Err("collector requires native 1920x1080 input; select a matching profile".into());
    }
    fs::create_dir_all(out.join("crops"))?;
    fs::create_dir_all(out.join("frames"))?;
    let mut ledger = BufWriter::new(fs::File::create(out.join("observations.jsonl"))?);
    let mut vectors = BufWriter::new(fs::File::create(out.join("embeddings.f32le"))?);
    let mut html = BufWriter::new(fs::File::create(out.join("review.html"))?);
    writeln!(html,"<!doctype html><meta charset=utf-8><title>VOD — revisão</title><style>body{{background:#171328;color:#eee;font:15px sans-serif}}img{{max-width:100%}}section{{margin:20px}}.crops img{{width:128px;height:144px}}</style><h1>Revisão de VOD — previsões não são rótulos</h1>")?;
    let stderr = fs::File::create(out.join("decoder.log"))?;
    let mut command = Command::new("ffmpeg");
    command.args(["-nostdin", "-loglevel", "warning", "-threads", "2"]);
    if decode_mode == "keyframes" {
        command.args(["-skip_frame", "nokey"]);
    }
    let mut child = Decoder(
        command
            .args([
                "-nostdin",
                "-loglevel",
                "warning",
                "-threads",
                "2",
                "-ss",
                &offset.to_string(),
                "-i",
                string(&spec, "input")?,
                "-t",
                &seconds.to_string(),
                "-an",
                "-sn",
                "-vf",
                &format!("fps=1/{interval}:start_time=0"),
                "-pix_fmt",
                "rgb24",
                "-f",
                "rawvideo",
                "pipe:1",
            ])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(stderr)
            .spawn()?,
    );
    let mut input = BufReader::new(child.0.stdout.take().ok_or("decoder stdout")?);
    let start = Instant::now();
    let mut timings = Vec::new();
    let mut decode_wait = Vec::new();
    let (mut frames, mut proposals, mut accepted, mut no_markers, mut green_total) =
        (0u64, 0u64, 0u64, 0u64, 0u64);
    let mut top_ids: BTreeMap<String, u64> = BTreeMap::new();
    let mut accept_ids: BTreeMap<String, u64> = BTreeMap::new();
    let mut hashes = HashSet::new();
    let mut review_frames = 0;
    let frame_bytes = 1920 * 1080 * 3;
    let target = seconds.div_ceil(interval);
    while frames < target {
        let read_start = Instant::now();
        let mut pixels = vec![0; frame_bytes];
        let mut received = 0;
        while received < frame_bytes {
            let n = input.read(&mut pixels[received..])?;
            if n == 0 {
                break;
            }
            received += n;
        }
        if received == 0 {
            break;
        }
        if received != frame_bytes {
            return Err("truncated decoded frame".into());
        }
        decode_wait.push(read_start.elapsed().as_secs_f64() * 1000.);
        let t = Instant::now();
        let source_s = offset + frames * interval;
        let frame_sha = hash(&pixels);
        let duplicate = !hashes.insert(frame_sha.clone());
        let frame = FrameEnvelope {
            frame_id: frames,
            captured_at_ms: source_s * 1000,
            width: 1920,
            height: 1080,
            stride_bytes: 1920 * 3,
            pixel_format: PixelFormat::Rgb8,
            source_id: string(&spec, "source_id")?.into(),
            pixels,
        };
        let markers = bars::detect(&frame, spatial.scan_rect, &spatial.bars)?;
        let mut crops = Vec::new();
        for m in markers.iter().filter(|m| m.color == "green") {
            green_total += 1;
            let Some(left) = m
                .rect
                .x
                .checked_add(m.rect.width / 2)
                .and_then(|x| x.checked_sub(64))
            else {
                continue;
            };
            let Some(top) = m.rect.y.checked_add(8) else {
                continue;
            };
            let rect = PixelRect {
                x: left,
                y: top,
                width: 128,
                height: 144,
            };
            if crops.len() >= 37 {
                break;
            }
            if let Ok(crop) = UnitCrop::from_frame(&frame, rect) {
                crops.push((m.id, rect, crop));
            }
        }
        if crops.is_empty() {
            no_markers += 1;
        }
        let detector_ms = t.elapsed().as_secs_f64() * 1000.;
        let mut features = Vec::new();
        for chunk in crops.chunks(4) {
            let batch: Vec<_> = chunk.iter().map(|(_, _, c)| (c.clone(), true)).collect();
            features.extend(laboratory::embeddings(
                &mut session,
                &batch,
                size,
                false,
                false,
            )?);
        }
        let mut rows = Vec::new();
        for ((marker_id, rect, crop), vector) in crops.iter().zip(&features) {
            let mut row = laboratory::rank(vector, &references);
            let digest = hash(&crop.rgb);
            let file = format!("crops/{digest}.png");
            if !out.join(&file).exists() {
                image::save_buffer(out.join(&file), &crop.rgb, 128, 144, image::ColorType::Rgb8)?;
            }
            row["marker_id"] = json!(marker_id);
            row["box"] = json!([rect.x, rect.y, rect.x + 128, rect.y + 144]);
            row["crop"] = json!(file);
            row["pixel_sha256"] = json!(digest);
            row["human_label"] = Value::Null;
            row["training_label_allowed"] = json!(false);
            row["embedding_row"] = json!(proposals + rows.len() as u64);
            for value in vector {
                vectors.write_all(&value.to_le_bytes())?;
            }
            if let Some(id) = row["candidates"][0]["unit_id"].as_str() {
                *top_ids.entry(id.into()).or_default() += 1;
            }
            if let Some(id) = row["candidate_id"].as_str() {
                accepted += 1;
                *accept_ids.entry(id.into()).or_default() += 1;
            }
            rows.push(row);
        }
        let analysis_ms = t.elapsed().as_secs_f64() * 1000.;
        timings.push(analysis_ms);
        proposals += rows.len() as u64;
        // One full frame/minute, independent of model confidence, for blind audit.
        let review = source_s % 60 == 0;
        let full_frame = if review {
            let file = format!("frames/{source_s:06}.png");
            image::save_buffer(
                out.join(&file),
                &frame.pixels,
                1920,
                1080,
                image::ColorType::Rgb8,
            )?;
            review_frames += 1;
            writeln!(html,"<section><h2>{source_s}s</h2><a href='{file}'><img loading='lazy' src='{file}'></a><div class=crops>")?;
            for row in &rows {
                writeln!(
                    html,
                    "<a href='{}'><img loading='lazy' src='{}'></a>",
                    row["crop"].as_str().unwrap(),
                    row["crop"].as_str().unwrap()
                )?;
            }
            writeln!(html, "</div></section>")?;
            Some(file)
        } else {
            None
        };
        writeln!(
            ledger,
            "{}",
            json!({"frame_index":frames,"source_id":spec["source_id"],"source_seconds_nominal":source_s,
            "timestamp_basis":"ffmpeg_fps_grid_not_original_frame_pts","decode_mode":decode_mode,"frame_pixel_sha256":frame_sha,
            "exact_duplicate_frame":duplicate,"markers":markers,"units":rows,"review_frame":full_frame,
            "detection_ms":detector_ms,"analysis_and_crop_save_ms":analysis_ms,"decoder_wait_ms":decode_wait.last(),
            "partition":spec["partition"],"ground_truth":false,"training_label_allowed":false})
        )?;
        frames += 1;
        if frames % 20 == 0 || frames == target {
            ledger.flush()?;
            html.flush()?;
            let progress = json!({"frames":frames,"target_frames":target,"source_seconds_covered":(frames*interval).min(seconds),
                "unit_crops":proposals,"accepted_candidates":accepted,"frames_without_green_proposals":no_markers,
                "elapsed_seconds":start.elapsed().as_secs_f64(),"analysis_ms_p50":percentile(&timings,0.5),
                "analysis_ms_p95":percentile(&timings,0.95),"accuracy_measured":false,"status":"running"});
            fs::write(
                out.join("progress.json"),
                serde_json::to_vec_pretty(&progress)?,
            )?;
            println!("{progress}");
        }
    }
    drop(input);
    let status = child.0.wait()?;
    vectors.flush()?;
    ledger.flush()?;
    html.flush()?;
    let complete = status.success() && frames == target;
    let report = json!({"schema_version":1,"status":if complete{"complete"}else{"incomplete"},"decoder_success":status.success(),
        "source_id":spec["source_id"],"source_url":spec["source_url"],"start_seconds":offset,"requested_seconds":seconds,
        "sample_interval_seconds":interval,"frames":frames,"target_frames":target,"unit_crops":proposals,
        "accepted_candidates":accepted,"frames_without_green_proposals":no_markers,"green_markers":green_total,
        "unique_frame_hashes":hashes.len(),"saved_review_frames":review_frames,"top1_distribution":top_ids,"accepted_distribution":accept_ids,
        "elapsed_seconds":start.elapsed().as_secs_f64(),"analysis_ms_p50":percentile(&timings,0.5),"analysis_ms_p95":percentile(&timings,0.95),
        "decoder_wait_ms_p95":percentile(&decode_wait,0.95),"encoder_sha256":spec["encoder_sha256"],"gallery_sha256":spec["gallery_sha256"],
        "threshold":0.8,"margin":0.08,"accuracy_measured":false,"human_labeled_crops":0,
        "runtime_approved":false,"training_performed":false,"partition":spec["partition"],
        "decode_mode":decode_mode,"embedding_dimensions":dim,"embedding_rows":proposals,
        "embeddings_sha256":hash(&fs::read(out.join("embeddings.f32le"))?),
        "limitations":["Same fixed green-bar detector as the app; no-proposal frames may be menu, combat, overlay or missed units.","Counts of model candidates are not precision/recall or catalog coverage.","Consecutive or duplicate crops are correlated; no pseudolabels enter training.","Sampling does not run inference on every decoded video frame.","Timing includes detector, feature extraction, matching and crop PNG saves, not Windows capture/display."]});
    fs::write(out.join("report.json"), serde_json::to_vec_pretty(&report)?)?;
    fs::write(
        out.join("progress.json"),
        serde_json::to_vec_pretty(&report)?,
    )?;
    println!("{report}");
    if !complete {
        return Err("VOD collection incomplete".into());
    }
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("VOD_COLLECTOR_ERROR: {e}");
        std::process::exit(1);
    }
}
