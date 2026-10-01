//! Observations only. Empty, unknown and an unresolved seasonal offer are distinct.
use agente_tft_capture_core::{FrameEnvelope, PixelRect};
use agente_tft_image_preprocess::GrayImage;
use agente_tft_ocr_tesseract::{TesseractOcr, TextWord};
use agente_tft_perception_hud::{HudField, HudOcrEngine, HudPreprocessConfig};
use serde::Serialize;
use crate::layout::{contains, crop, score, ScreenLayout};
use crate::recovery::{route, RecoveryProfile, RecoveryTrace, Tile};

#[derive(Debug, Clone, Serialize)]
pub struct Attempt {
    pub scale: u8,
    pub text: Option<String>,
    pub confidence: Option<f32>,
    pub reason: String,
}
#[derive(Debug, Clone, Serialize)]
pub struct SlotRead {
    pub slot: u8,
    pub status: String,
    pub observed_name: Option<String>,
    pub observed_cost: Option<u16>,
    pub name_confidence: Option<f32>,
    pub cost_confidence: Option<f32>,
    pub unit_id: Option<String>,
    pub catalog_status: String,
    pub catalog_base_cost: Option<u8>,
    pub empty_similarity: Option<f32>,
    pub name_attempts: Vec<Attempt>,
    pub cost_attempts: Vec<Attempt>,
}
#[derive(Debug, Clone, Serialize)]
pub struct ScreenRead {
    pub timestamp_ms: u64,
    pub layout_id: String,
    pub panel_status: String,
    pub panel_anchor_similarities: Vec<Option<f32>>,
    pub slots: Vec<SlotRead>,
    pub ocr_process_calls: u8,
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub recovery: Option<RecoveryTrace>,
}

fn base_slot(slot: u8, status: &str, similarity: Option<f32>) -> SlotRead {
    SlotRead { slot, status: status.into(), observed_name: None, observed_cost: None,
        name_confidence: None, cost_confidence: None, unit_id: None, catalog_status: "not_bound".into(),
        catalog_base_cost: None, empty_similarity: similarity, name_attempts: vec![], cost_attempts: vec![] }
}

pub fn normalize(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase()
}

fn attempt(words: &[TextWord], tile: Tile, scale: u8, threshold: f32, ambiguous: bool) -> Attempt {
    if ambiguous {
        return Attempt { scale, text: None, confidence: None, reason: "atlas_assignment_conflict".into() };
    }
    let mut selected: Vec<_> = words.iter().filter(|w| contains(tile.rect,
        PixelRect { x: w.x, y: w.y, width: w.width, height: w.height })).collect();
    selected.sort_by_key(|w| w.x);
    if selected.is_empty() {
        return Attempt { scale, text: None, confidence: None, reason: "no_text".into() };
    }
    let text = selected.iter().map(|w| w.text.as_str()).collect::<Vec<_>>().join(" ");
    // Minimum WORD score, not an average hiding an uncertain token.
    let confidence = selected.iter().map(|w| w.confidence).fold(1.0, f32::min);
    let valid = if tile.field == 0 {
        text.chars().count() <= 80 && text.chars().filter(|c| c.is_alphabetic()).count() >= 2
            && text.chars().all(|c| c.is_alphabetic() || c.is_whitespace() || "'-.’".contains(c))
    } else {
        !text.is_empty() && text.len() <= 2 && text.bytes().all(|b| b.is_ascii_digit())
    };
    Attempt { scale, text: Some(text), confidence: Some(confidence),
        reason: if !valid { "invalid_text" } else if confidence < threshold { "below_min_confidence" } else { "eligible" }.into() }
}

fn agree(attempts: &[Attempt]) -> (Option<String>, Option<f32>) {
    if attempts.len() != 2 || attempts.iter().any(|v| v.reason != "eligible") { return (None, None); }
    let (Some(x), Some(y)) = (&attempts[0].text, &attempts[1].text) else { return (None, None); };
    if normalize(x) != normalize(y) { return (None, None); }
    (Some(x.clone()), Some(attempts[0].confidence.unwrap().min(attempts[1].confidence.unwrap())))
}

fn atlas(frame: &FrameEnvelope, layout: &ScreenLayout, engine: &TesseractOcr, skip: &[bool], scale: u8)
    -> Result<(GrayImage, Vec<Tile>), String> {
    let mut pieces = Vec::new();
    let (mut name_w, mut cost_w, mut row_h) = (0u32, 0u32, 0u32);
    for (i, slot) in layout.slots.iter().enumerate() {
        if skip[i] { continue; }
        for (field, rect) in [(0, slot.name), (1, slot.cost)] {
            let roi = crop(frame, rect)?;
            // Selects the existing gray preparation, not the numeric parser.
            let image = engine.prepare_roi(HudField::Level, &roi,
                HudPreprocessConfig { upscale_factor: scale, invert: true })
                .map_err(|e| format!("text preparation: {e:?}"))?;
            if field == 0 { name_w = name_w.max(image.width); } else { cost_w = cost_w.max(image.width); }
            row_h = row_h.max(image.height);
            pieces.push((i, field, image));
        }
    }
    let width = name_w + cost_w + 60;
    let height = (row_h + 20) * 5 + 20;
    if width as u64 * height as u64 > 4_000_000 { return Err("shop atlas too large".into()); }
    let mut image = GrayImage { width, height, stride_bytes: width, pixels: vec![255; (width * height) as usize] };
    let mut tiles = Vec::new();
    for (slot, field, piece) in pieces {
        let x = if field == 0 { 10 } else { name_w + 40 };
        let y = 10 + slot as u32 * (row_h + 20);
        for row in 0..piece.height as usize {
            let dest = (y as usize + row) * width as usize + x as usize;
            let src = row * piece.stride_bytes as usize;
            image.pixels[dest..dest + piece.width as usize].copy_from_slice(&piece.pixels[src..src + piece.width as usize]);
        }
        tiles.push(Tile { slot, field, rect: PixelRect { x, y, width: piece.width, height: piece.height } });
    }
    Ok((image, tiles))
}

pub fn perceive(frame: &FrameEnvelope, layout: &ScreenLayout, engine: &TesseractOcr,
    recovery: Option<&RecoveryProfile>) -> Result<ScreenRead, String> {
    frame.validate().map_err(|e| e.to_string())?;
    if (frame.width, frame.height) != (layout.reference_width, layout.reference_height) {
        return Err("UI profile resolution mismatch; no silent resize".into());
    }
    if let Some(profile) = recovery { profile.validate(layout)?; }
    let panel_scores = layout.panel_anchors.iter().map(|a| score(frame, a.rect, &a.index()?).map(|x| x.0))
        .collect::<Result<Vec<_>, _>>()?;
    let primary = layout.panel_anchors.iter().zip(&panel_scores)
        .all(|(a, s)| s.is_some_and(|v| v >= a.min_similarity));
    let mut visible = primary;
    let mut trace = recovery.map(|profile| RecoveryTrace { profile: profile.id.clone(),
        panel_source: if primary { "primary_controls" } else { "unresolved" }.into(),
        fallback_scores: vec![], routing: vec![] });
    if !primary {
        if let (Some(profile), Some(diag)) = (recovery, trace.as_mut()) {
            diag.fallback_scores = profile.panel_scores(frame)?;
            visible = profile.accepts(&diag.fallback_scores);
            if visible { diag.panel_source = "structural_fallback".into(); }
        }
    }
    let mut out = ScreenRead { timestamp_ms: frame.captured_at_ms, layout_id: layout.id.clone(),
        panel_status: if visible { "located" } else { "unresolved" }.into(),
        panel_anchor_similarities: panel_scores, slots: vec![], ocr_process_calls: 0, error: None, recovery: trace };
    if !visible {
        out.slots = (0..5).map(|i| base_slot(i, "unavailable", None)).collect();
        return Ok(out);
    }
    let index = layout.empty_template.index()?;
    let mut empty = Vec::new();
    for slot in &layout.slots {
        let (similarity, mean) = score(frame, slot.empty_region, &index)?;
        let is_empty = similarity.is_some_and(|v| v >= layout.empty_template.min_similarity)
            && mean <= layout.empty_max_mean;
        empty.push(is_empty);
        out.slots.push(base_slot(slot.slot, if is_empty { "empty_observed" } else { "unknown" }, similarity));
    }
    if empty.iter().all(|v| *v) { return Ok(out); }
    for scale in [3, 4] {
        let (image, tiles) = atlas(frame, layout, engine, &empty, scale)?;
        out.ocr_process_calls += 1;
        let words = match engine.recognize_text_block(&image) {
            Ok(words) => words,
            Err(error) => { out.error = Some(error); break; }
        };
        let conflicts = if let Some(diag) = out.recovery.as_mut() {
            let (flags, routing) = route(&words, &tiles, scale);
            diag.routing.push(routing);
            flags
        } else {
            // Keep S1 reproducible without the explicit S2 recovery profile.
            let global = words.iter().any(|w| tiles.iter().filter(|tile| contains(tile.rect,
                PixelRect { x: w.x, y: w.y, width: w.width, height: w.height })).count() != 1);
            vec![global; tiles.len()]
        };
        for (tile, ambiguous) in tiles.into_iter().zip(conflicts) {
            let value = attempt(&words, tile, scale, layout.min_text_confidence, ambiguous);
            if tile.field == 0 { out.slots[tile.slot].name_attempts.push(value); }
            else { out.slots[tile.slot].cost_attempts.push(value); }
        }
    }
    for slot in &mut out.slots {
        if slot.status == "empty_observed" { continue; }
        if out.error.is_some() { slot.status = "read_error".into(); continue; }
        (slot.observed_name, slot.name_confidence) = agree(&slot.name_attempts);
        let (cost, confidence) = agree(&slot.cost_attempts);
        slot.observed_cost = cost.and_then(|value| value.parse::<u16>().ok());
        slot.cost_confidence = confidence;
        slot.status = match (slot.observed_name.is_some(), slot.observed_cost.is_some()) {
            (true, true) => "offer_text_readable", (true, false) | (false, true) => "partially_readable", _ => "unknown",
        }.into();
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn a(scale: u8, text: &str, conf: f32) -> Attempt {
        Attempt { scale, text: Some(text.into()), confidence: Some(conf),
            reason: if conf >= 0.7 { "eligible" } else { "below_min_confidence" }.into() }
    }
    #[test]
    fn scale_conflict_or_low_confidence_never_chooses_a_value() {
        assert!(agree(&[a(3, "Alpha", 0.95), a(4, "Beta", 0.99)]).0.is_none());
        assert!(agree(&[a(3, "Alpha", 0.69), a(4, "Alpha", 0.99)]).0.is_none());
    }
    #[test]
    fn names_preserve_apostrophes_and_spaces() {
        assert_eq!(agree(&[a(3, "Rek'Sai", 0.95), a(4, "rek'sai", 0.91)]).0.as_deref(), Some("Rek'Sai"));
        assert_eq!(normalize("  Lobo   Trovogurai "), "lobo trovogurai");
    }
    #[test]
    fn missing_text_is_not_empty_slot() {
        assert_eq!(base_slot(0, "unknown", None).status, "unknown");
        assert!(base_slot(0, "empty_observed", Some(0.99)).unit_id.is_none());
    }
    #[test]
    fn atlas_words_cannot_cross_field_boundary() {
        let tile = Tile { slot: 0, field: 0, rect: PixelRect { x: 0, y: 0, width: 50, height: 30 } };
        let word = TextWord { text: "Alpha".into(), confidence: 0.99, x: 45, y: 5, width: 20, height: 10 };
        assert_eq!(attempt(&[word], tile, 3, 0.7, true).reason, "atlas_assignment_conflict");
    }
    #[test]
    fn unaffected_field_preserves_word_threshold_after_isolation() {
        let tiles = [Tile { slot: 0, field: 0, rect: PixelRect { x: 0, y: 0, width: 50, height: 30 } },
            Tile { slot: 0, field: 1, rect: PixelRect { x: 80, y: 0, width: 20, height: 30 } }];
        let words = [TextWord { text: "Alpha".into(), confidence: 0.69, x: 5, y: 5, width: 35, height: 10 },
            TextWord { text: "1".into(), confidence: 0.99, x: 95, y: 5, width: 15, height: 10 }];
        let (bad, _) = route(&words, &tiles, 3);
        assert_eq!(attempt(&words, tiles[0], 3, 0.7, bad[0]).reason, "below_min_confidence");
        assert_eq!(attempt(&words, tiles[1], 3, 0.7, bad[1]).reason, "atlas_assignment_conflict");
    }
}
