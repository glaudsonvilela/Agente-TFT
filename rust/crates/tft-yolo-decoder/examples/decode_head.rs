//! Inspect a recorded raw YOLO head with the TFT decoder.
//! Usage: cargo run -p agente-tft-yolo-decoder --example decode_head -- head.f32

use agente_tft_yolo_decoder::{decode, ClassSpec, HeadShape, Region};
use std::{env, fs};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = env::args()
        .nth(1)
        .ok_or("expected path to [12,8400] f32 tensor")?;
    let bytes = fs::read(path)?;
    if bytes.len() != 12 * 8400 * 4 {
        return Err("unexpected detector tensor size".into());
    }
    let head: Vec<f32> = bytes
        .chunks_exact(4)
        .map(|chunk| f32::from_le_bytes(chunk.try_into().unwrap()))
        .collect();
    let thresholds = [0.12, 0.10, 0.20, 0.20, 0.20, 0.20, 0.20, 0.20];
    let limits = [16, 12, 8, 8, 1, 1, 1, 5];
    let classes: Vec<_> = thresholds
        .into_iter()
        .zip(limits)
        .enumerate()
        .map(|(index, (threshold, limit))| ClassSpec {
            threshold,
            limit,
            exclusion_group: if index <= 1 { 0 } else { index as u8 },
            expected_region: Region::Any,
        })
        .collect();
    let found = decode(
        &head,
        HeadShape {
            classes: 8,
            anchors: 8400,
            input_width: 640,
            input_height: 640,
            frame_width: 1920,
            frame_height: 1080,
        },
        &classes,
        &[],
        0.45,
    )?;
    for detection in found {
        println!(
            "{} {} {:.4} {:.1} {:.1} {:.1} {:.1}",
            detection.class_id,
            detection.anchor,
            detection.score,
            detection.rect.x0,
            detection.rect.y0,
            detection.rect.x1,
            detection.rect.y1
        );
    }
    Ok(())
}
