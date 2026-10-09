//! TFT-specific decoding of raw YOLO detection heads.
//!
//! The network supplies proposals. This crate owns letterbox inversion,
//! spatial evidence, duplicate resolution, and stable visual tracks. It does
//! not turn a model prediction into a training label.

use std::collections::{HashMap, VecDeque};

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Rect {
    pub x0: f32,
    pub y0: f32,
    pub x1: f32,
    pub y1: f32,
}

impl Rect {
    pub fn area(self) -> f32 {
        (self.x1 - self.x0).max(0.0) * (self.y1 - self.y0).max(0.0)
    }

    pub fn iou(self, other: Self) -> f32 {
        let intersection = Self {
            x0: self.x0.max(other.x0),
            y0: self.y0.max(other.y0),
            x1: self.x1.min(other.x1),
            y1: self.y1.min(other.y1),
        }
        .area();
        intersection / (self.area() + other.area() - intersection).max(1e-6)
    }

    fn center(self) -> (f32, f32) {
        ((self.x0 + self.x1) * 0.5, (self.y0 + self.y1) * 0.5)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Region {
    Board,
    Bench,
    Opponent,
    Hud,
    Any,
}

#[derive(Clone, Copy, Debug)]
pub struct ClassSpec {
    pub threshold: f32,
    pub limit: usize,
    /// Classes in the same group compete for one physical object.
    pub exclusion_group: u8,
    pub expected_region: Region,
}

#[derive(Clone, Copy, Debug)]
pub struct RegionBounds {
    pub region: Region,
    /// Coordinates normalized by the full frame dimensions.
    pub rect: Rect,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Detection {
    pub class_id: usize,
    pub anchor: usize,
    pub rect: Rect,
    pub raw_score: f32,
    pub score: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct HeadShape {
    pub classes: usize,
    pub anchors: usize,
    pub input_width: usize,
    pub input_height: usize,
    pub frame_width: usize,
    pub frame_height: usize,
}

/// Stable C boundary for the Python capture process. The neural network runs
/// outside this crate; all proposal decoding and suppression run here.
#[repr(C)]
#[derive(Clone, Copy, Debug, Default)]
pub struct CDetection {
    pub class_id: u32,
    pub anchor: u32,
    pub x0: f32,
    pub y0: f32,
    pub x1: f32,
    pub y1: f32,
    pub raw_score: f32,
    pub score: f32,
}

/// Returns the number of decoded boxes, or -1 for an invalid contract.
/// All pointers must reference their declared lengths. No data is retained.
#[no_mangle]
pub unsafe extern "C" fn tft_decode_yolo_head(
    head: *const f32,
    head_len: usize,
    classes: usize,
    anchors: usize,
    input_width: usize,
    input_height: usize,
    frame_width: usize,
    frame_height: usize,
    thresholds: *const f32,
    limits: *const u32,
    out: *mut CDetection,
    out_capacity: usize,
) -> isize {
    if head.is_null()
        || thresholds.is_null()
        || limits.is_null()
        || out.is_null()
        || classes == 0
        || classes > 256
        || anchors == 0
        || out_capacity == 0
        || out_capacity > 4096
        || (classes + 4).checked_mul(anchors) != Some(head_len)
    {
        return -1;
    }
    let head = std::slice::from_raw_parts(head, head_len);
    let thresholds = std::slice::from_raw_parts(thresholds, classes);
    let limits = std::slice::from_raw_parts(limits, classes);
    let specs: Vec<_> = thresholds
        .iter()
        .zip(limits)
        .enumerate()
        .map(|(id, (&threshold, &limit))| ClassSpec {
            threshold,
            limit: limit as usize,
            exclusion_group: id as u8,
            expected_region: Region::Any,
        })
        .collect();
    let shape = HeadShape {
        classes,
        anchors,
        input_width,
        input_height,
        frame_width,
        frame_height,
    };
    let Ok(found) = decode(head, shape, &specs, &[], 0.45) else {
        return -1;
    };
    if found.len() > out_capacity {
        return -1;
    }
    let out = std::slice::from_raw_parts_mut(out, out_capacity);
    for (slot, item) in out.iter_mut().zip(&found) {
        *slot = CDetection {
            class_id: item.class_id as u32,
            anchor: item.anchor as u32,
            x0: item.rect.x0,
            y0: item.rect.y0,
            x1: item.rect.x1,
            y1: item.rect.y1,
            raw_score: item.raw_score,
            score: item.score,
        };
    }
    found.len() as isize
}

/// Read a [4 + classes, anchors] YOLO head. Scores are uncalibrated evidence.
/// Region bounds are supplied by the active TFT screen profile, so a new HUD
/// layout changes configuration rather than model code.
pub fn decode(
    head: &[f32],
    shape: HeadShape,
    classes: &[ClassSpec],
    regions: &[RegionBounds],
    iou_threshold: f32,
) -> Result<Vec<Detection>, &'static str> {
    if shape.classes == 0
        || shape.anchors == 0
        || shape.input_width == 0
        || shape.input_height == 0
        || shape.frame_width == 0
        || shape.frame_height == 0
        || classes.len() != shape.classes
        || head.len() != (shape.classes + 4) * shape.anchors
        || !iou_threshold.is_finite()
        || !(0.0..=1.0).contains(&iou_threshold)
        || classes
            .iter()
            .any(|spec| !spec.threshold.is_finite() || !(0.0..=1.0).contains(&spec.threshold))
    {
        return Err("invalid YOLO head contract");
    }
    let fw = shape.frame_width as f32;
    let fh = shape.frame_height as f32;
    let scale = (shape.input_width as f32 / fw).min(shape.input_height as f32 / fh);
    let resized_width = (fw * scale).round();
    let resized_height = (fh * scale).round();
    let pad_x = ((shape.input_width as f32 - resized_width) / 2.0).floor();
    let pad_y = ((shape.input_height as f32 - resized_height) / 2.0).floor();
    let at = |channel: usize, anchor: usize| head[channel * shape.anchors + anchor];
    let mut proposals = Vec::new();
    for (class_id, spec) in classes.iter().enumerate() {
        if spec.limit == 0 {
            continue;
        }
        let mut class_proposals = Vec::new();
        for anchor in 0..shape.anchors {
            let raw_score = at(class_id + 4, anchor);
            if !raw_score.is_finite() || raw_score < spec.threshold {
                continue;
            }
            let (x, y, width, height) =
                (at(0, anchor), at(1, anchor), at(2, anchor), at(3, anchor));
            if ![x, y, width, height].iter().all(|v| v.is_finite()) || width <= 0.0 || height <= 0.0
            {
                continue;
            }
            let rect = Rect {
                x0: ((x - width * 0.5 - pad_x) / scale).clamp(0.0, fw),
                y0: ((y - height * 0.5 - pad_y) / scale).clamp(0.0, fh),
                x1: ((x + width * 0.5 - pad_x) / scale).clamp(0.0, fw),
                y1: ((y + height * 0.5 - pad_y) / scale).clamp(0.0, fh),
            };
            if rect.x1 - rect.x0 < 8.0 || rect.y1 - rect.y0 < 8.0 {
                continue;
            }
            let (cx, cy) = rect.center();
            let in_region = spec.expected_region == Region::Any
                || regions.iter().any(|r| {
                    r.region == spec.expected_region
                        && cx / fw >= r.rect.x0
                        && cx / fw <= r.rect.x1
                        && cy / fh >= r.rect.y0
                        && cy / fh <= r.rect.y1
                });
            // A soft spatial prior keeps unusual scenes visible for review.
            let score = raw_score
                * if in_region || regions.is_empty() {
                    1.0
                } else {
                    0.65
                };
            class_proposals.push(Detection {
                class_id,
                anchor,
                rect,
                raw_score,
                score,
            });
        }
        class_proposals.sort_by(|a, b| b.score.total_cmp(&a.score));
        // More than the final class limit can be needed before NMS.
        proposals.extend(
            class_proposals
                .into_iter()
                .take(spec.limit.saturating_mul(8)),
        );
    }
    proposals.sort_by(|a, b| b.score.total_cmp(&a.score));
    let mut accepted: Vec<Detection> = Vec::new();
    let mut counts = vec![0usize; classes.len()];
    for candidate in proposals {
        if counts[candidate.class_id] >= classes[candidate.class_id].limit {
            continue;
        }
        let group = classes[candidate.class_id].exclusion_group;
        if accepted.iter().any(|previous| {
            classes[previous.class_id].exclusion_group == group
                && previous.rect.iou(candidate.rect) > iou_threshold
        }) {
            continue;
        }
        counts[candidate.class_id] += 1;
        accepted.push(candidate);
    }
    Ok(accepted)
}

#[derive(Clone, Debug)]
pub struct IdentityEvidence {
    pub track_id: u64,
    pub at_ms: u64,
    /// The full class distribution retains alternatives for later frames.
    pub scores: Vec<f32>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct IdentityResult {
    pub track_id: u64,
    pub best_class: usize,
    pub best_score: f32,
    pub runner_up_score: f32,
    pub observations: usize,
}

/// Combine readings of the same tracked character. All candidates remain
/// inspectable; a low margin never becomes a hard identity or a training label.
pub struct IdentityMemory {
    window_ms: u64,
    max_observations: usize,
    history: HashMap<u64, VecDeque<IdentityEvidence>>,
}

impl IdentityMemory {
    pub fn new(window_ms: u64, max_observations: usize) -> Self {
        Self {
            window_ms,
            max_observations: max_observations.max(1),
            history: HashMap::new(),
        }
    }

    pub fn update(&mut self, evidence: IdentityEvidence) -> Option<IdentityResult> {
        if evidence.scores.is_empty()
            || evidence.scores.iter().any(|s| !s.is_finite() || *s < 0.0)
            || evidence.scores.iter().sum::<f32>() <= 0.0
        {
            return None;
        }
        let track_id = evidence.track_id;
        let at_ms = evidence.at_ms;
        let classes = evidence.scores.len();
        let history = self.history.entry(track_id).or_default();
        if history.back().is_some_and(|last| {
            evidence.at_ms <= last.at_ms || evidence.scores.len() != last.scores.len()
        }) {
            // A scene cut or a reused ID must not carry identity from a past unit.
            history.clear();
        }
        history.push_back(evidence);
        while history.len() > self.max_observations
            || history
                .front()
                .is_some_and(|first| at_ms.saturating_sub(first.at_ms) > self.window_ms)
        {
            history.pop_front();
        }
        let mut totals = vec![0.0f32; classes];
        for row in history.iter() {
            let sum: f32 = row.scores.iter().sum();
            for (total, score) in totals.iter_mut().zip(&row.scores) {
                *total += (*score / sum).max(1e-6).ln();
            }
        }
        let peak = totals.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        let values: Vec<f32> = totals.iter().map(|v| (v - peak).exp()).collect();
        let normalizer: f32 = values.iter().sum();
        let probabilities: Vec<f32> = values.iter().map(|v| v / normalizer).collect();
        let mut order: Vec<usize> = (0..classes).collect();
        order.sort_by(|a, b| probabilities[*b].total_cmp(&probabilities[*a]));
        Some(IdentityResult {
            track_id,
            best_class: order[0],
            best_score: probabilities[order[0]],
            runner_up_score: order.get(1).map_or(0.0, |index| probabilities[*index]),
            observations: history.len(),
        })
    }

    pub fn expire(&mut self, now_ms: u64) {
        self.history.retain(|_, rows| {
            rows.back()
                .is_some_and(|last| now_ms.saturating_sub(last.at_ms) <= self.window_ms)
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn spec(region: Region) -> ClassSpec {
        ClassSpec {
            threshold: 0.2,
            limit: 2,
            exclusion_group: 1,
            expected_region: region,
        }
    }

    #[test]
    fn inverts_letterbox_and_prefers_bench_region() {
        // 1920x1080 is resized to 640x360 with 140 px top padding.
        let mut head = vec![0.0; 6 * 2];
        let put = |data: &mut Vec<f32>, channel: usize, anchor: usize, value: f32| {
            data[channel * 2 + anchor] = value;
        };
        for anchor in 0..2 {
            put(&mut head, 0, anchor, 160.0);
            put(&mut head, 1, anchor, 350.0);
            put(&mut head, 2, anchor, 50.0);
            put(&mut head, 3, anchor, 50.0);
        }
        put(&mut head, 4, 0, 0.9);
        put(&mut head, 5, 1, 0.8);
        let found = decode(
            &head,
            HeadShape {
                classes: 2,
                anchors: 2,
                input_width: 640,
                input_height: 640,
                frame_width: 1920,
                frame_height: 1080,
            },
            &[spec(Region::Board), spec(Region::Bench)],
            &[RegionBounds {
                region: Region::Bench,
                rect: Rect {
                    x0: 0.0,
                    y0: 0.5,
                    x1: 1.0,
                    y1: 0.9,
                },
            }],
            0.45,
        )
        .unwrap();
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].class_id, 1);
        assert!((found[0].rect.y0 - 555.0).abs() < 1.0);
    }

    #[test]
    fn temporal_identity_keeps_alternatives_and_resets_reused_track() {
        let mut memory = IdentityMemory::new(2000, 4);
        let push = |memory: &mut IdentityMemory, at_ms, scores| {
            memory
                .update(IdentityEvidence {
                    track_id: 7,
                    at_ms,
                    scores,
                })
                .unwrap()
        };
        assert_eq!(push(&mut memory, 100, vec![0.6, 0.4]).best_class, 0);
        let combined = push(&mut memory, 200, vec![0.3, 0.7]);
        assert_eq!(combined.observations, 2);
        assert!(combined.best_score < 0.7);
        let restarted = push(&mut memory, 200, vec![0.1, 0.9]);
        assert_eq!(restarted.observations, 1);
        assert_eq!(restarted.best_class, 1);
    }
}
