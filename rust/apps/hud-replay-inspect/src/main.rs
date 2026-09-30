use std::{
    env,
    fs,
    path::PathBuf,
    process::ExitCode,
};

use agente_tft_capture_core::{CaptureError, CaptureSource};
use agente_tft_capture_replay::ReplayVideoSource;
use agente_tft_hud_runtime::{HudLayout, HudPipeline};
use agente_tft_ocr_tesseract::TesseractOcr;
use agente_tft_perception_core::ConsensusConfig;

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
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

    let Some(layout_path) = args.next() else {
        return Err("missing HUD layout path\n\n".to_string() + &usage());
    };

    let target_fps: u16 = args
        .next()
        .as_deref()
        .unwrap_or("5")
        .parse()
        .map_err(|_| "target_fps must be an integer > 0".to_string())?;

    let max_frames: u64 = args
        .next()
        .as_deref()
        .unwrap_or("1800")
        .parse()
        .map_err(|_| "max_frames must be an integer > 0".to_string())?;

    if target_fps == 0 || max_frames == 0 {
        return Err("target_fps and max_frames must be > 0".into());
    }

    let layout = load_layout(PathBuf::from(layout_path))?;
    let ocr = TesseractOcr::default();
    if !ocr.available() {
        return Err(
            "tesseract binary not available. Install it before running HUD replay inspection."
                .into(),
        );
    }

    let mut replay = ReplayVideoSource::open(&video, target_fps)
        .map_err(|e| format!("failed to open replay: {e}"))?;

    let metadata = replay.metadata().clone();
    let mut pipeline = HudPipeline::new(
        ocr,
        layout,
        0,
        ConsensusConfig {
            min_confidence: 0.80,
            confirmations: 2,
            max_gap_ms: 750,
        },
    )
    .map_err(|e| format!("failed to initialize HUD pipeline: {e}"))?;

    let mut frames_read = 0u64;
    let mut emitted = 0u64;
    let mut last_revision = pipeline.state().revision;

    while frames_read < max_frames {
        let frame = match replay.next_frame() {
            Ok(frame) => frame,
            Err(CaptureError::EndOfStream) => break,
            Err(error) => {
                return Err(format!(
                    "replay decode failed after {frames_read} frames: {error}"
                ))
            }
        };
        frames_read += 1;

        let result = pipeline
            .process_frame(&frame)
            .map_err(|e| format!("HUD pipeline failed at frame {}: {e}", frame.frame_id))?;

        let revision_changed = result.state_revision != last_revision;
        if revision_changed || !result.events.is_empty() {
            last_revision = result.state_revision;
            emitted += 1;

            let line = serde_json::json!({
                "type": "hud_update",
                "frame_id": result.frame_id,
                "captured_at_ms": result.captured_at_ms,
                "accepted_reads": result.accepted_reads,
                "events": result.events,
                "state": pipeline.state(),
            });

            println!(
                "{}",
                serde_json::to_string(&line)
                    .map_err(|e| format!("failed serializing HUD update: {e}"))?
            );
        }
    }

    let summary = serde_json::json!({
        "type": "summary",
        "video": video,
        "width": metadata.width,
        "height": metadata.height,
        "source_fps": metadata.source_fps,
        "target_fps": target_fps,
        "frames_read": frames_read,
        "updates_emitted": emitted,
        "final_state_revision": pipeline.state().revision,
        "final_state": pipeline.state(),
    });

    println!(
        "{}",
        serde_json::to_string_pretty(&summary)
            .map_err(|e| format!("failed serializing summary: {e}"))?
    );

    Ok(())
}

fn load_layout(path: PathBuf) -> Result<HudLayout, String> {
    let content = fs::read_to_string(&path)
        .map_err(|e| format!("failed reading HUD layout {}: {e}", path.display()))?;
    let layout: HudLayout = serde_json::from_str(&content)
        .map_err(|e| format!("invalid HUD layout JSON {}: {e}", path.display()))?;
    layout
        .validate()
        .map_err(|e| format!("invalid HUD layout {}: {e}", path.display()))?;
    Ok(layout)
}

fn usage() -> String {
    [
        "Usage:",
        "  agente-tft-hud-replay-inspect <video> <hud-layout.json> [target_fps] [max_frames]",
        "",
        "Defaults:",
        "  target_fps = 5",
        "  max_frames = 1800",
        "",
        "Example:",
        "  cargo run --manifest-path rust/Cargo.toml -p agente-tft-hud-replay-inspect -- \\",
        "    partida.mp4 configs/hud-2560x1440.json 5 1800",
    ]
    .join("\n")
}
