use std::{
    fs,
    process::Command,
};

use agente_tft_capture_core::CaptureSource;
use agente_tft_capture_replay::ReplayVideoSource;

#[test]
fn ffmpeg_decodes_a_synthetic_replay() {
    let ffmpeg_ok = Command::new("ffmpeg")
        .arg("-version")
        .status()
        .map(|s| s.success())
        .unwrap_or(false);
    let ffprobe_ok = Command::new("ffprobe")
        .arg("-version")
        .status()
        .map(|s| s.success())
        .unwrap_or(false);

    if !ffmpeg_ok || !ffprobe_ok {
        eprintln!("ffmpeg/ffprobe unavailable; skipping replay smoke test");
        return;
    }

    let path = std::env::temp_dir().join(format!(
        "agente-tft-replay-smoke-{}.mp4",
        std::process::id()
    ));
    let _ = fs::remove_file(&path);

    let status = Command::new("ffmpeg")
        .args([
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=16x16:r=5:d=0.8",
            "-pix_fmt",
            "yuv420p",
            "-y",
        ])
        .arg(&path)
        .status()
        .expect("failed to launch ffmpeg fixture generator");

    assert!(status.success());

    let mut source = ReplayVideoSource::open(&path, 5).unwrap();
    let frame = source.next_frame().unwrap();

    assert_eq!(frame.width, 16);
    assert_eq!(frame.height, 16);
    assert_eq!(frame.pixels.len(), 16 * 16 * 4);

    let _ = fs::remove_file(&path);
}
