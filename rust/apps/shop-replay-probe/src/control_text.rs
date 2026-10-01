//! Button prices/counts use pixels, not template labels, roster costs or defaults.
use agente_tft_capture_core::{FrameEnvelope, PixelRect};
use agente_tft_image_preprocess::GrayImage;
use agente_tft_ocr_tesseract::TesseractOcr;
use agente_tft_perception_hud::{HudField, HudOcrEngine, HudPreprocessConfig};

use crate::controls::{ControlsProfile, ControlsRead, NumericRead};
use crate::layout::crop;
use crate::recovery::{route, Tile};
use crate::screen::{agree, attempt};

pub fn read_numbers(frame: &FrameEnvelope, profile: &ControlsProfile, out: &mut ControlsRead,
    engine: &TesseractOcr) -> Result<(), String> {
    let mut enabled = Vec::new();
    for (spec, observed) in profile.controls.iter().zip(&out.controls) {
        let present = observed.status == "observed";
        for (rect, suffix, should_read) in [
            (spec.price_rect, "price", present),
            (spec.free_count_rect, "free_count", present && observed.appearance.as_deref() == Some("free_refresh_appearance")),
        ] {
            if let Some(rect) = rect {
                out.numeric_fields.push(NumericRead { id: format!("{}_{}", spec.id, suffix), rect,
                    status: if should_read { "unknown" } else { "not_observed" }.into(),
                    value: None, confidence: None, attempts: vec![] });
                enabled.push(should_read);
            }
        }
    }
    if !enabled.iter().any(|v| *v) { return Ok(()); }
    for scale in [3, 4] {
        let mut pieces = Vec::new();
        let (mut width, mut row_height) = (0u32, 0u32);
        for (i, field) in out.numeric_fields.iter().enumerate().filter(|(i,_)| enabled[*i]) {
            let piece = engine.prepare_roi(HudField::Level, &crop(frame, field.rect)?,
                HudPreprocessConfig { upscale_factor: scale, invert: true }).map_err(|e| format!("{e:?}"))?;
            width = width.max(piece.width); row_height = row_height.max(piece.height);
            pieces.push((i, piece));
        }
        width += 20;
        let height = (row_height+20) * out.numeric_fields.len() as u32 + 20;
        if width as u64 * height as u64 > 1_000_000 { return Err("controls text atlas too large".into()); }
        let mut atlas = GrayImage { width, height, stride_bytes: width, pixels: vec![255; (width*height) as usize] };
        let mut tiles = Vec::new();
        for (i, piece) in pieces {
            let (x,y) = (10, 10 + i as u32 * (row_height+20));
            for row in 0..piece.height as usize {
                let dst = (y as usize+row)*width as usize+x as usize;
                let src = row*piece.stride_bytes as usize;
                atlas.pixels[dst..dst+piece.width as usize].copy_from_slice(&piece.pixels[src..src+piece.width as usize]);
            }
            tiles.push(Tile { slot: i, field: 1, rect: PixelRect { x,y,width: piece.width,height: piece.height } });
        }
        out.ocr_process_calls += 1;
        let words = match engine.recognize_text_block(&atlas) {
            Ok(words) => words,
            Err(error) => { out.error = Some(error); break; }
        };
        let (bad, trace) = route(&words, &tiles, scale);
        out.routing.push(trace);
        for (tile, conflict) in tiles.into_iter().zip(bad) {
            out.numeric_fields[tile.slot].attempts.push(attempt(&words, tile, scale, profile.min_text_confidence, conflict));
        }
    }
    for (i, field) in out.numeric_fields.iter_mut().enumerate() {
        if !enabled[i] { continue; }
        if out.error.is_some() { field.status = "read_error".into(); continue; }
        let (text, confidence) = agree(&field.attempts);
        field.value = text.and_then(|t| t.parse().ok());
        field.confidence = confidence;
        field.status = if field.value.is_some() { "observed" } else { "unknown" }.into();
    }
    Ok(())
}
