//! Raw trait text from the fixed left panel. Names are bound to the seasonal
//! catalog later; OCR here cannot establish an owned champion identity.
use agente_tft_capture_core::{FrameEnvelope, PixelRect};
use agente_tft_image_preprocess::{to_luma, upscale_nearest};
use agente_tft_ocr_tesseract::TextBlockOcrEngine;
use serde_json::{json, Value};
use crate::layout::crop;

pub const PANEL: PixelRect = PixelRect { x: 118, y: 245, width: 150, height: 540 };
const BANDS: [PixelRect; 2] = [
    PixelRect { x: 118, y: 245, width: 150, height: 220 },
    PixelRect { x: 118, y: 465, width: 150, height: 320 },
];
const SCALE: u8 = 4;

pub fn observe<E: TextBlockOcrEngine>(frame: &FrameEnvelope, engine: &mut E) -> Result<Value, String> {
    let mut words = Vec::new();
    for band in BANDS {
        let roi = crop(frame, band)?;
        let gray = to_luma(&roi).map_err(|e| e.to_string())?;
        let enlarged = upscale_nearest(&gray, SCALE).map_err(|e| e.to_string())?;
        words.extend(engine.recognize_text_block(&enlarged)?.into_iter()
            .filter(|word| word.confidence >= 0.25)
            .map(|word| json!({
                "text": word.text,
                "confidence": word.confidence,
                "box": [band.x + word.x / SCALE as u32,
                        band.y + word.y / SCALE as u32,
                        band.x + (word.x + word.width + SCALE as u32 - 1) / SCALE as u32,
                        band.y + (word.y + word.height + SCALE as u32 - 1) / SCALE as u32],
            })));
    }
    Ok(json!({"status": "raw_ocr", "basis": "fixed_left_trait_panel_v1",
              "frame_id": frame.frame_id, "source_ms": frame.captured_at_ms,
              "panel": [PANEL.x, PANEL.y, PANEL.width, PANEL.height],
              "words": words, "identity_verified": false}))
}
