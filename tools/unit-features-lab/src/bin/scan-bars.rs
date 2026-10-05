//! Inspect localization independently of the neural recognizer.
#![allow(dead_code)]
#[path = "../../../../rust/apps/board-replay-probe/src/bars.rs"]
mod bars;
#[path = "../../../../rust/apps/board-replay-probe/src/profile.rs"]
mod profile;
use agente_tft_capture_core::{FrameEnvelope, PixelFormat};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{fs, path::Path};
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 4 {
        return Err("use FRAME_MANIFEST PROFILE OUTPUT_JSON".into());
    }
    if Path::new(&args[3]).exists() {
        return Err("new output required".into());
    }
    let files: Vec<String> = serde_json::from_slice(&fs::read(&args[1])?)?;
    let p: profile::Profile = serde_json::from_slice(&fs::read(&args[2])?)?;
    let mut output = Vec::new();
    for path in files {
        let rgb = image::open(&path)?.to_rgb8();
        if rgb.width() != p.reference_width || rgb.height() != p.reference_height {
            return Err("profile geometry mismatch".into());
        }
        let f = FrameEnvelope {
            frame_id: 0,
            captured_at_ms: 0,
            width: rgb.width(),
            height: rgb.height(),
            stride_bytes: rgb.width() * 3,
            pixel_format: PixelFormat::Rgb8,
            source_id: path.clone(),
            pixels: rgb.into_raw(),
        };
        let mut legacy = p.bars.clone();
        legacy.allow_dense_ticks = false;
        let mut dense = legacy.clone();
        dense.allow_dense_ticks = true;
        output.push(json!({"image":path,"frame_pixel_sha256":format!("{:x}",Sha256::digest(&f.pixels)),"legacy":bars::detect(&f,p.scan_rect,&legacy)?,"dense":bars::detect(&f,p.scan_rect,&dense)?}));
    }
    fs::write(&args[3], serde_json::to_vec_pretty(&output)?)?;
    println!(
        "{}",
        json!({"frames":output.len(),"identity_labels_generated":0})
    );
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("BAR_SCAN_ERROR: {e}");
        std::process::exit(1);
    }
}
