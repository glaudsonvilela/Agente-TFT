use std::{env, fs, path::PathBuf, process::ExitCode};

use agente_tft_capture_core::{CaptureError, CaptureSource, RoiChangeRouter, RoiProfile};
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

    let Some(video) = args.next() else {
        return Err(usage());
    };
    if video == "-h" || video == "--help" {
        println!("{}", usage());
        return Ok(());
    }

    let profile_path = args
        .next()
        .ok_or_else(usage)
        .map(PathBuf::from)?;

    let target_fps: u16 = args
        .next()
        .as_deref()
        .unwrap_or("5")
        .parse()
        .map_err(|_| "target_fps must be an integer > 0".to_string())?;

    let max_frames: u64 = args
        .next()
        .as_deref()
        .unwrap_or("3000")
        .parse()
        .map_err(|_| "max_frames must be an integer > 0".to_string())?;

    if target_fps == 0 || max_frames == 0 {
        return Err("target_fps and max_frames must be greater than zero".into());
    }

    let raw_profile = fs::read_to_string(&profile_path)
        .map_err(|e| format!("failed to read {}: {e}", profile_path.display()))?;

    let profile: RoiProfile = serde_json::from_str(&raw_profile)
        .map_err(|e| format!("invalid ROI profile JSON: {e}"))?;

    profile
        .validate()
        .map_err(|e| format!("invalid ROI profile: {e}"))?;

    let mut router =
        RoiChangeRouter::new(profile).map_err(|e| format!("router init failed: {e}"))?;
    let mut source =
        ReplayVideoSource::open(&video, target_fps).map_err(|e| format!("open failed: {e}"))?;

    let mut frames_read = 0u64;
    let mut change_events = 0u64;

    while frames_read < max_frames {
        let frame = match source.next_frame() {
            Ok(frame) => frame,
            Err(CaptureError::EndOfStream) => break,
            Err(e) => return Err(format!("decode failed after {frames_read} frames: {e}")),
        };

        let changes = router
            .observe(&frame)
            .map_err(|e| format!("ROI analysis failed on frame {}: {e}", frame.frame_id))?;

        if !changes.is_empty() {
            change_events += changes.len() as u64;

            let payload = serde_json::json!({
                "frame_id": frame.frame_id,
                "timestamp_ms": frame.captured_at_ms,
                "changes": changes.iter().map(|change| serde_json::json!({
                    "roi": format!("{:?}", change.key).to_lowercase(),
                    "score": change.score
                })).collect::<Vec<_>>()
            });

            println!(
                "{}",
                serde_json::to_string(&payload)
                    .map_err(|e| format!("failed to serialize event: {e}"))?
            );
        }

        frames_read += 1;
    }

    eprintln!(
        "{}",
        serde_json::to_string_pretty(&serde_json::json!({
            "summary": {
                "video": video,
                "profile": profile_path.display().to_string(),
                "target_fps": target_fps,
                "frames_read": frames_read,
                "roi_change_events": change_events
            }
        }))
        .map_err(|e| format!("failed to serialize summary: {e}"))?
    );

    Ok(())
}

fn usage() -> String {
    [
        "Usage:",
        "  agente-tft-roi-replay-inspect <video> <roi-profile.json> [target_fps] [max_frames]",
        "",
        "Example:",
        "  cargo run --manifest-path rust/Cargo.toml \\",
        "    -p agente-tft-roi-replay-inspect -- \\",
        "    partida.mp4 configs/roi/my-profile.json 10 6000",
        "",
        "Output:",
        "  JSON Lines on stdout for ROI changes; final summary on stderr.",
    ]
    .join("\n")
}
