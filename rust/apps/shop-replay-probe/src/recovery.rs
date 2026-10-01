//! S2: opt-in panel evidence and field-local atlas routing, not season data.
use agente_tft_capture_core::{FrameEnvelope, PixelRect};
use agente_tft_ocr_tesseract::TextWord;
use serde::{Deserialize, Serialize};
use crate::layout::{contains, score, Anchor, ScreenLayout};

#[derive(Debug, Clone, Deserialize)]
pub struct RecoveryProfile {
    pub schema_version: u32,
    pub id: String,
    pub parent_layout_id: String,
    pub anchors: Vec<Anchor>,
}

/// Half-open rectangles; widening arithmetic avoids overflow at the u32 edge.
pub fn intersects(a: PixelRect, b: PixelRect) -> bool {
    a.width > 0 && a.height > 0 && b.width > 0 && b.height > 0
        && (a.x as u64) < b.x as u64 + b.width as u64
        && (b.x as u64) < a.x as u64 + a.width as u64
        && (a.y as u64) < b.y as u64 + b.height as u64
        && (b.y as u64) < a.y as u64 + a.height as u64
}

impl RecoveryProfile {
    pub fn validate(&self, layout: &ScreenLayout) -> Result<(), String> {
        if self.schema_version != 1 || self.id.trim().is_empty() || self.id.len() > 100
            || self.parent_layout_id != layout.id || self.anchors.len() != 2 {
            return Err("invalid recovery profile or parent UI mismatch".into());
        }
        let screen = PixelRect { x: 0, y: 0, width: layout.reference_width, height: layout.reference_height };
        for anchor in &self.anchors {
            if !contains(screen, anchor.rect) || anchor.grid_width == 0 || anchor.grid_height == 0
                || anchor.grid_width > 64 || anchor.grid_height > 64
                || anchor.pixels.len() != anchor.grid_width as usize * anchor.grid_height as usize
                || !anchor.min_similarity.is_finite() || !(0.95..=1.0).contains(&anchor.min_similarity)
                || layout.slots.iter().any(|slot| intersects(anchor.rect, slot.card)) {
                return Err("recovery anchors must be bounded, high-threshold and outside offers".into());
            }
            anchor.index()?;
        }
        if intersects(self.anchors[0].rect, self.anchors[1].rect) {
            return Err("recovery anchors must be spatially distinct".into());
        }
        Ok(())
    }

    pub fn panel_scores(&self, frame: &FrameEnvelope) -> Result<Vec<Option<f32>>, String> {
        self.anchors.iter().map(|a| score(frame, a.rect, &a.index()?).map(|v| v.0)).collect()
    }

    pub fn accepts(&self, scores: &[Option<f32>]) -> bool {
        scores.len() == self.anchors.len() && self.anchors.iter().zip(scores)
            .all(|(anchor, value)| value.is_some_and(|v| v >= anchor.min_similarity))
    }
}

#[derive(Debug, Clone, Copy)]
pub struct Tile {
    pub slot: usize,
    pub field: usize,
    pub rect: PixelRect,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AffectedField {
    pub slot: usize,
    pub field: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct AssignmentIssue {
    pub text: String,
    pub confidence: f32,
    pub rect: PixelRect,
    pub affected: Vec<AffectedField>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RoutingTrace {
    pub scale: u8,
    pub orphan_words: usize,
    pub conflicted_fields: Vec<AffectedField>,
    pub issues: Vec<AssignmentIssue>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RecoveryTrace {
    pub profile: String,
    pub panel_source: String,
    pub fallback_scores: Vec<Option<f32>>,
    pub routing: Vec<RoutingTrace>,
}

fn field(tile: &Tile) -> AffectedField {
    AffectedField { slot: tile.slot, field: if tile.field == 0 { "name" } else { "cost" }.into() }
}

/// A crossing word invalidates only the tiles it touches. A gutter-only token
/// is preserved in the trace, not used as text and not broadcast to all slots.
/// Scores/labels do not select which tile receives a word.
pub fn route(words: &[TextWord], tiles: &[Tile], scale: u8) -> (Vec<bool>, RoutingTrace) {
    let mut conflicts = vec![false; tiles.len()];
    let mut trace = RoutingTrace { scale, orphan_words: 0, conflicted_fields: vec![], issues: vec![] };
    for word in words {
        let rect = PixelRect { x: word.x, y: word.y, width: word.width, height: word.height };
        let owners = tiles.iter().filter(|tile| contains(tile.rect, rect)).count();
        let touched: Vec<_> = tiles.iter().enumerate().filter(|(_, tile)| intersects(tile.rect, rect)).collect();
        if owners == 1 && touched.len() == 1 { continue; }
        if touched.is_empty() { trace.orphan_words += 1; }
        let mut affected = Vec::new();
        for (index, tile) in touched {
            conflicts[index] = true;
            affected.push(field(tile));
        }
        trace.issues.push(AssignmentIssue { text: word.text.clone(), confidence: word.confidence, rect, affected });
    }
    trace.conflicted_fields = tiles.iter().zip(&conflicts)
        .filter(|(_, bad)| **bad).map(|(tile, _)| field(tile)).collect();
    (conflicts, trace)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn tile(slot: usize, field: usize, x: u32, y: u32) -> Tile {
        Tile { slot, field, rect: PixelRect { x, y, width: 40, height: 20 } }
    }
    fn word(x: u32, y: u32, width: u32) -> TextWord {
        TextWord { text: "fixture".into(), confidence: 0.95, x, y, width, height: 10 }
    }
    #[test]
    fn contained_word_does_not_create_a_conflict() {
        let (bad, trace) = route(&[word(2, 2, 20)], &[tile(0, 0, 0, 0)], 3);
        assert_eq!(bad, vec![false]); assert!(trace.issues.is_empty());
    }
    #[test]
    fn one_crossing_cost_does_not_poison_the_other_nine_fields() {
        let tiles: Vec<_> = (0..5).flat_map(|s| [tile(s, 0, 0, s as u32 * 40), tile(s, 1, 60, s as u32 * 40)]).collect();
        let (bad, trace) = route(&[word(95, 2, 10)], &tiles, 4);
        assert_eq!(bad.iter().filter(|v| **v).count(), 1);
        assert!(bad[1]); assert_eq!(trace.conflicted_fields, vec![field(&tiles[1])]);
    }
    #[test]
    fn word_spanning_two_fields_invalidates_both_not_a_third() {
        let tiles = [tile(0, 0, 0, 0), tile(0, 1, 60, 0), tile(1, 0, 0, 40)];
        assert_eq!(route(&[word(30, 2, 40)], &tiles, 3).0, vec![true, true, false]);
    }
    #[test]
    fn gutter_token_is_reported_but_not_assigned() {
        let (bad, trace) = route(&[word(45, 2, 5)], &[tile(0, 0, 0, 0), tile(0, 1, 60, 0)], 3);
        assert_eq!(bad, vec![false, false]); assert_eq!(trace.orphan_words, 1);
        assert!(trace.issues[0].affected.is_empty());
    }
    #[test]
    fn crossing_low_confidence_word_still_marks_geometry_ambiguous() {
        let mut w = word(35, 2, 10); w.confidence = 0.1;
        assert_eq!(route(&[w], &[tile(0, 0, 0, 0)], 3).0, vec![true]);
    }
    #[test]
    fn overlapping_tiles_do_not_receive_the_same_word_twice() {
        assert_eq!(route(&[word(12, 2, 10)], &[tile(0, 0, 0, 0), tile(1, 0, 10, 0)], 4).0, vec![true, true]);
    }
    #[test]
    fn half_open_edges_and_large_coordinates_are_safe() {
        assert!(!intersects(tile(0,0,0,0).rect, tile(0,1,40,0).rect));
        assert!(intersects(tile(0,0,u32::MAX-2,0).rect, tile(0,1,u32::MAX-1,0).rect));
    }
}
