use std::{env, process::ExitCode};

use agente_tft_capture_core::{CaptureError, CaptureSource};
use agente_tft_capture_replay::ReplayVideoSource;

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("{message}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let mut args = env::args().skip(1);
    let Some(path) = args.next() else {
        return Err(usage());
    };

    if path == "-h" || path == "--help" {
        println!("{}", usage());
        return Ok(());
    }

    let target_fps: u16 = args
        .next()
        .as_deref()
        .unwrap_or("5")
        .parse()
        .map_err(|_| "target_fps must be an integer > 0".to_string())?;

    let max_frames: u64 = args
        .next()
        .as_deref()
        .unwrap_or("300")
        .parse()
        .map_err(|_| "max_frames must be an integer > 0".to_string())?;

    if target_fps == 0 || max_frames == 0 {
        return Err("target_fps and max_frames must be greater than zero".into());
    }

    let mut source =
        ReplayVideoSource::open(&path, target_fps).map_err(|e| format!("open failed: {e}"))?;

    let metadata = source.metadata().clone();
    let mut frames = 0u64;
    let mut first_ts = None;
    let mut last_ts = None;

    while frames < max_frames {
        match source.next_frame() {
            Ok(frame) => {
                first_ts.get_or_insert(frame.captured_at_ms);
                last_ts = Some(frame.captured_at_ms);
                frames += 1;
            }
            Err(CaptureError::EndOfStream) => break,
            Err(e) => return Err(format!("decode failed after {frames} frames: {e}")),
        }
    }

    let output = serde_json::json!({
        "path": source.path().display().to_string(),
        "width": metadata.width,
        "height": metadata.height,
        "source_fps": metadata.source_fps,
        "target_fps": target_fps,
        "frames_read": frames,
        "first_timestamp_ms": first_ts,
        "last_timestamp_ms": last_ts,
        "reached_limit": frames == max_frames
    });

    println!(
        "{}",
        serde_json::to_string_pretty(&output)
            .map_err(|e| format!("failed to format output: {e}"))?
    );

    Ok(())
}

fn usage() -> String {
    [
        "Usage:",
        "  agente-tft-replay-inspect <video> [target_fps] [max_frames]",
        "",
        "Defaults:",
        "  target_fps = 5",
        "  max_frames = 300",
        "",
        "Example:",
        "  cargo run --manifest-path rust/Cargo.toml -p agente-tft-replay-inspect -- partida.mp4 10 600",
    ]
    .join("\n")
}
