//! S5 opt-in: one numerical field per image/process; geometry selected by appearance.
//! No expected values, result-driven retries, season constants or state writes.
use agente_tft_capture_core::{FrameEnvelope, PixelRect};
use agente_tft_image_preprocess::GrayImage;
use agente_tft_ocr_tesseract::{TesseractOcr, TextWord};
use agente_tft_perception_hud::{HudField, HudOcrEngine, HudPreprocessConfig};
use serde::Deserialize;

use crate::controls::{ControlsProfile, ControlsRead, NumericRead};
use crate::layout::{contains, crop, ScreenLayout};
use crate::recovery::{intersects, route, Tile};
use crate::screen::{agree, attempt};

#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NumberRect { pub x: u32, pub y: u32, pub width: u32, pub height: u32 }
impl From<NumberRect> for PixelRect {
    fn from(r: NumberRect) -> Self { Self { x:r.x, y:r.y, width:r.width, height:r.height } }
}
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NumberRegion { pub appearance: String, pub rect: NumberRect }
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NumberField { pub id: String, pub control_id: String, pub regions: Vec<NumberRegion> }
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NumbersProfile {
    pub schema_version: u32,
    pub id: String,
    pub controls_profile_id: String,
    pub fields: Vec<NumberField>,
}

impl NumbersProfile {
    pub fn validate(&self, controls: &ControlsProfile, layout: &ScreenLayout) -> Result<(), String> {
        if self.schema_version != 1 || self.id.trim().is_empty() || self.id.len()>100
            || self.controls_profile_id != controls.id || self.fields.len()!=3 {
            return Err("numeric policy identity/count mismatch".into());
        }
        let definitions: [(&str, &str, &[&str]); 3] = [
            ("buy_xp_price", "buy_xp", &["active_appearance", "dimmed_appearance"]),
            ("refresh_price", "refresh", &["active_appearance", "dimmed_appearance", "free_refresh_appearance"]),
            ("refresh_free_count", "refresh", &["free_refresh_appearance"]),
        ];
        let screen = PixelRect { x:0, y:0, width:layout.reference_width, height:layout.reference_height };
        let mut previous: Vec<(&str, &str, &str, PixelRect)> = Vec::new();
        for (field, (id, control, states)) in self.fields.iter().zip(definitions) {
            if field.id != id || field.control_id != control
                || field.regions.iter().map(|r|r.appearance.as_str()).collect::<Vec<_>>() != states {
                return Err("numeric field/state identity or order mismatch".into());
            }
            for region in &field.regions {
                let rect: PixelRect = region.rect.into();
                if rect.width==0 || rect.height==0 || rect.width>256 || rect.height>96
                    || !contains(screen, rect)
                    || layout.slots.iter().any(|s|intersects(rect, s.card))
                    || controls.controls.iter().any(|s|intersects(rect, s.rect)) {
                    return Err("numeric region outside screen or overlaps a card/visual".into());
                }
                for (other_id, other_control, other_state, other_rect) in &previous {
                    let simultaneous = field.control_id != *other_control || region.appearance == *other_state;
                    if field.id != *other_id && simultaneous && intersects(rect, *other_rect) {
                        return Err("simultaneous numeric fields overlap".into());
                    }
                }
                previous.push((&field.id, &field.control_id, &region.appearance, rect));
            }
        }
        Ok(())
    }

    fn selected(&self, id: &str, appearance: &str) -> Result<PixelRect, String> {
        self.fields.iter().find(|f| f.id==id)
            .and_then(|f|f.regions.iter().find(|r|r.appearance==appearance))
            .map(|r|r.rect.into()).ok_or_else(||"no numeric box for observed appearance".into())
    }
}

pub fn read_numbers(frame: &FrameEnvelope, controls: &ControlsProfile, policy: &NumbersProfile,
    out: &mut ControlsRead, engine: &TesseractOcr) -> Result<(), String> {
    read_with(frame, controls, policy, out, engine, |image|engine.recognize_text_block(image))
}

fn read_with<E, F>(frame: &FrameEnvelope, controls: &ControlsProfile, policy: &NumbersProfile,
    out: &mut ControlsRead, engine: &E, mut recognize: F) -> Result<(), String>
where E: HudOcrEngine, F: FnMut(&GrayImage) -> Result<Vec<TextWord>, String> {
    if !out.numeric_fields.is_empty() || out.ocr_process_calls!=0 || !out.routing.is_empty()
        || out.controls.len()!=controls.controls.len() || out.profile!=controls.id
        || out.timestamp_ms!=frame.captured_at_ms {
        return Err("isolated numbers require a fresh matching visual observation".into());
    }
    for (spec, visual) in controls.controls.iter().zip(&out.controls) {
        for (default_rect, suffix) in [(spec.price_rect,"price"), (spec.free_count_rect,"free_count")] {
            let Some(default_rect) = default_rect else {continue;};
            let id = format!("{}_{}", spec.id, suffix);
            let enabled = visual.status=="observed"
                && (suffix=="price" || visual.appearance.as_deref()==Some("free_refresh_appearance"));
            let rect = if enabled {
                policy.selected(&id, visual.appearance.as_deref().ok_or("observed appearance missing")?)?
            } else {default_rect};
            let mut field = NumericRead { id, rect, status:if enabled {"unknown"}else{"not_observed"}.into(),
                value:None, confidence:None, attempts:vec![] };
            if enabled {
                let roi = crop(frame, rect)?;
                let index = out.numeric_fields.len();
                for scale in [3,4] {
                    let image = engine.prepare_roi(HudField::Level, &roi,
                        HudPreprocessConfig {upscale_factor:scale, invert:true}).map_err(|e|format!("{e:?}"))?;
                    if u64::from(image.width)*u64::from(image.height)>1_000_000 {
                        return Err("isolated numeric image budget exceeded".into());
                    }
                    // Only this field's pixels and the existing preparation border.
                    // Another control's contents, presence or geometry cannot enter this call.
                    let tile = Tile {slot:index, field:1, rect:PixelRect {
                        x:0,y:0,width:image.width,height:image.height }};
                    out.ocr_process_calls += 1;
                    let words = recognize(&image)?;
                    let (conflicts, trace) = route(&words, &[tile], scale);
                    out.routing.push(trace);
                    field.attempts.push(attempt(&words, tile, scale, controls.min_text_confidence, conflicts[0]));
                }
                let (text, confidence) = agree(&field.attempts);
                field.value=text.and_then(|t|t.parse().ok());
                field.confidence=confidence;
                if field.value.is_some() {field.status="observed".into();}
            }
            out.numeric_fields.push(field);
        }
    }
    Ok(())
}

#[cfg(test)]
#[path="control_numbers_tests.rs"]
mod tests;
