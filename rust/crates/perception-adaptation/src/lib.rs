pub mod promotion;
pub use promotion::*;

use agente_tft_capture_core::{extract_roi, FrameEnvelope, NormalizedRect};
use agente_tft_image_preprocess::to_luma;
use agente_tft_perception_health::{
    PerceptionHealthMonitor, PerceptionHealthPolicy, PerceptionHealthSnapshot,
    PerceptionOutcome, PerceptionSample, PerceptionStreamId,
};
use agente_tft_visual_match::{DescriptorConfig, TemplateIndex};
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const PERCEPTION_ADAPTATION_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Error)]
pub enum AdaptationError {
    #[error("invalid ROI search configuration: {0}")]
    InvalidConfig(&'static str),
    #[error("invalid ROI search seed: {0}")]
    InvalidSeed(&'static str),
    #[error("ROI search requires at least one frame")]
    NoFrames,
    #[error("frame dimensions do not match the search seed")]
    FrameDimensionMismatch,
    #[error("capture/ROI error: {0}")]
    Capture(String),
    #[error("anchor template error: {0}")]
    Anchor(String),
    #[error("health monitor error: {0}")]
    Health(String),
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RoiSearchConfig {
    pub max_offset_x_px: u32,
    pub max_offset_y_px: u32,
    pub step_px: u32,
    pub max_candidates: usize,
    pub min_frames: usize,
    pub min_coverage_rate: f32,
    pub min_confidence_p50: f32,
    pub min_anchor_similarity_p50: f32,
    pub min_operational_score_margin: f32,
    pub coverage_weight: f32,
    pub confidence_weight: f32,
    pub anchor_weight: f32,
}

impl Default for RoiSearchConfig {
    fn default() -> Self {
        Self {
            max_offset_x_px: 96,
            max_offset_y_px: 64,
            step_px: 8,
            max_candidates: 81,
            min_frames: 8,
            min_coverage_rate: 0.80,
            min_confidence_p50: 0.70,
            min_anchor_similarity_p50: 0.70,
            min_operational_score_margin: 0.05,
            coverage_weight: 0.40,
            confidence_weight: 0.30,
            anchor_weight: 0.30,
        }
    }
}

impl RoiSearchConfig {
    pub fn validate(&self) -> Result<(), AdaptationError> {
        if self.step_px == 0 {
            return Err(AdaptationError::InvalidConfig("step_px must be > 0"));
        }
        if self.max_candidates == 0 || self.max_candidates > 1024 {
            return Err(AdaptationError::InvalidConfig(
                "max_candidates must be inside 1..=1024",
            ));
        }
        if self.min_frames == 0 || self.min_frames > 10_000 {
            return Err(AdaptationError::InvalidConfig(
                "min_frames must be inside 1..=10000",
            ));
        }
        for value in [
            self.min_coverage_rate,
            self.min_confidence_p50,
            self.min_operational_score_margin,
        ] {
            if !finite_unit(value) {
                return Err(AdaptationError::InvalidConfig(
                    "coverage/confidence/margin must be finite and inside [0,1]",
                ));
            }
        }
        if !self.min_anchor_similarity_p50.is_finite()
            || !(-1.0..=1.0).contains(&self.min_anchor_similarity_p50)
        {
            return Err(AdaptationError::InvalidConfig(
                "anchor similarity must be finite and inside [-1,1]",
            ));
        }
        for value in [
            self.coverage_weight,
            self.confidence_weight,
            self.anchor_weight,
        ] {
            if !value.is_finite() || value < 0.0 {
                return Err(AdaptationError::InvalidConfig(
                    "score weights must be finite and nonnegative",
                ));
            }
        }
        if self.coverage_weight + self.confidence_weight + self.anchor_weight
            <= f32::EPSILON
        {
            return Err(AdaptationError::InvalidConfig(
                "at least one score weight must be positive",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RoiSearchSeed {
    pub search_id: String,
    pub subsystem: String,
    pub field: String,
    pub active_profile_id: String,
    pub reference_width: u32,
    pub reference_height: u32,
    pub active_read_rect: NormalizedRect,
    pub active_anchor_rect: NormalizedRect,
}

impl RoiSearchSeed {
    pub fn validate(&self) -> Result<(), AdaptationError> {
        if [
            &self.search_id,
            &self.subsystem,
            &self.field,
            &self.active_profile_id,
        ]
        .iter()
        .any(|value| value.trim().is_empty() || value.len() > 120)
        {
            return Err(AdaptationError::InvalidSeed(
                "ids must be non-empty and <= 120 bytes",
            ));
        }
        if self.reference_width == 0 || self.reference_height == 0 {
            return Err(AdaptationError::InvalidSeed(
                "reference dimensions must be > 0",
            ));
        }
        self.active_read_rect
            .validate()
            .map_err(|_| AdaptationError::InvalidSeed("invalid read rectangle"))?;
        self.active_anchor_rect
            .validate()
            .map_err(|_| AdaptationError::InvalidSeed("invalid anchor rectangle"))?;
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RoiCandidate {
    pub id: String,
    pub dx_px: i32,
    pub dy_px: i32,
    pub read_rect: NormalizedRect,
    pub anchor_rect: NormalizedRect,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CandidateRejectionReason {
    InsufficientFrames,
    Coverage,
    ConfidenceP50,
    AnchorSimilarityP50,
    AnchorErrors,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RoiCandidateReport {
    pub candidate: RoiCandidate,
    pub health: PerceptionHealthSnapshot,
    pub anchor_samples: usize,
    pub anchor_errors: usize,
    pub anchor_similarity_p50: Option<f32>,
    pub anchor_similarity_p95: Option<f32>,
    pub operational_score: f32,
    pub eligible: bool,
    pub rejection_reasons: Vec<CandidateRejectionReason>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RoiSearchReport {
    pub schema_version: u32,
    pub search_id: String,
    pub active_candidate_id: String,
    pub evaluated_frames: usize,
    pub candidates_generated: usize,
    pub candidates: Vec<RoiCandidateReport>,
    pub shadow_candidate_id: Option<String>,
    pub shadow_candidate_margin: Option<f32>,
    pub note: String,
}

pub trait RoiCandidateProbe {
    fn probe(&mut self, frame: &FrameEnvelope, rect: NormalizedRect) -> PerceptionOutcome;
}

pub struct AnchorTemplate {
    index: TemplateIndex,
}

impl AnchorTemplate {
    pub fn from_frame(
        frame: &FrameEnvelope,
        rect: NormalizedRect,
        config: DescriptorConfig,
    ) -> Result<Self, AdaptationError> {
        let roi = extract_roi(frame, rect)
            .map_err(|error| AdaptationError::Capture(error.to_string()))?;
        let gray = to_luma(&roi)
            .map_err(|error| AdaptationError::Capture(error.to_string()))?;
        let mut index = TemplateIndex::new(config)
            .map_err(|error| AdaptationError::Anchor(error.to_string()))?;
        index
            .insert_image("anchor", &gray)
            .map_err(|error| AdaptationError::Anchor(error.to_string()))?;
        Ok(Self { index })
    }

    pub fn score(
        &self,
        frame: &FrameEnvelope,
        rect: NormalizedRect,
    ) -> Result<f32, AdaptationError> {
        let roi = extract_roi(frame, rect)
            .map_err(|error| AdaptationError::Capture(error.to_string()))?;
        let gray = to_luma(&roi)
            .map_err(|error| AdaptationError::Capture(error.to_string()))?;
        let result = self
            .index
            .classify(&gray)
            .map_err(|error| AdaptationError::Anchor(error.to_string()))?
            .ok_or_else(|| AdaptationError::Anchor("anchor index is empty".into()))?;
        Ok(result.best.similarity)
    }
}

#[derive(Debug, Clone)]
pub struct RoiShadowSearch {
    config: RoiSearchConfig,
    health_policy: PerceptionHealthPolicy,
}

impl RoiShadowSearch {
    pub fn new(
        config: RoiSearchConfig,
        health_policy: PerceptionHealthPolicy,
    ) -> Result<Self, AdaptationError> {
        config.validate()?;
        health_policy
            .validate()
            .map_err(|error| AdaptationError::Health(error.to_string()))?;
        Ok(Self {
            config,
            health_policy,
        })
    }

    pub fn generate_candidates(
        &self,
        seed: &RoiSearchSeed,
    ) -> Result<Vec<RoiCandidate>, AdaptationError> {
        seed.validate()?;
        let mut offsets = Vec::<(i32, i32)>::new();
        let xs = axis_offsets(self.config.max_offset_x_px, self.config.step_px);
        let ys = axis_offsets(self.config.max_offset_y_px, self.config.step_px);
        for &dy in &ys {
            for &dx in &xs {
                if translated(
                    seed.active_read_rect,
                    dx,
                    dy,
                    seed.reference_width,
                    seed.reference_height,
                )
                .is_some()
                    && translated(
                        seed.active_anchor_rect,
                        dx,
                        dy,
                        seed.reference_width,
                        seed.reference_height,
                    )
                    .is_some()
                {
                    offsets.push((dx, dy));
                }
            }
        }
        offsets.sort_by_key(|(dx, dy)| {
            (
                dx.unsigned_abs().saturating_add(dy.unsigned_abs()),
                dy.unsigned_abs(),
                dx.unsigned_abs(),
                *dy,
                *dx,
            )
        });
        offsets.dedup();
        offsets.truncate(self.config.max_candidates);

        Ok(offsets
            .into_iter()
            .map(|(dx, dy)| RoiCandidate {
                id: if dx == 0 && dy == 0 {
                    "active".into()
                } else {
                    format!("dx{:+}_dy{:+}", dx, dy)
                },
                dx_px: dx,
                dy_px: dy,
                read_rect: translated(
                    seed.active_read_rect,
                    dx,
                    dy,
                    seed.reference_width,
                    seed.reference_height,
                )
                .expect("offset was filtered"),
                anchor_rect: translated(
                    seed.active_anchor_rect,
                    dx,
                    dy,
                    seed.reference_width,
                    seed.reference_height,
                )
                .expect("offset was filtered"),
            })
            .collect())
    }

    pub fn evaluate<P: RoiCandidateProbe>(
        &self,
        seed: &RoiSearchSeed,
        frames: &[FrameEnvelope],
        anchor: &AnchorTemplate,
        probe: &mut P,
    ) -> Result<RoiSearchReport, AdaptationError> {
        seed.validate()?;
        if frames.is_empty() {
            return Err(AdaptationError::NoFrames);
        }
        if frames.iter().any(|frame| {
            frame.width != seed.reference_width || frame.height != seed.reference_height
        }) {
            return Err(AdaptationError::FrameDimensionMismatch);
        }

        let candidates = self.generate_candidates(seed)?;
        let mut reports = Vec::with_capacity(candidates.len());

        for candidate in candidates {
            let mut policy = self.health_policy.clone();
            policy.window_capacity = policy.window_capacity.max(frames.len());
            policy.min_samples = self.config.min_frames.min(policy.window_capacity);
            let mut monitor = PerceptionHealthMonitor::new(policy)
                .map_err(|error| AdaptationError::Health(error.to_string()))?;
            let stream = PerceptionStreamId::new(
                seed.subsystem.clone(),
                seed.field.clone(),
                format!(
                    "{}::shadow::{}::{}",
                    seed.active_profile_id, seed.search_id, candidate.id
                ),
            )
            .map_err(|error| AdaptationError::Health(error.to_string()))?;

            let mut anchor_scores = Vec::new();
            let mut anchor_errors = 0usize;
            for frame in frames {
                match anchor.score(frame, candidate.anchor_rect) {
                    Ok(score) if score.is_finite() => anchor_scores.push(score),
                    _ => anchor_errors = anchor_errors.saturating_add(1),
                }
                monitor
                    .observe(PerceptionSample {
                        stream: stream.clone(),
                        observed_at_ms: frame.captured_at_ms,
                        outcome: probe.probe(frame, candidate.read_rect),
                    })
                    .map_err(|error| AdaptationError::Health(error.to_string()))?;
            }

            anchor_scores.sort_by(f32::total_cmp);
            let health = monitor
                .snapshot(&stream, frames.last().unwrap().captured_at_ms)
                .expect("the evaluation inserted at least one sample");
            let anchor_p50 = percentile(&anchor_scores, 0.50);
            let anchor_p95 = percentile(&anchor_scores, 0.95);
            let rejection_reasons = candidate_rejections(
                &self.config,
                frames.len(),
                &health,
                anchor_errors,
                anchor_p50,
            );
            let operational_score =
                operational_score(&self.config, &health, anchor_p50);
            reports.push(RoiCandidateReport {
                candidate,
                health,
                anchor_samples: anchor_scores.len(),
                anchor_errors,
                anchor_similarity_p50: anchor_p50,
                anchor_similarity_p95: anchor_p95,
                operational_score,
                eligible: rejection_reasons.is_empty(),
                rejection_reasons,
            });
        }

        reports.sort_by(|a, b| {
            b.operational_score
                .total_cmp(&a.operational_score)
                .then_with(|| {
                    let ad = a.candidate.dx_px.unsigned_abs()
                        + a.candidate.dy_px.unsigned_abs();
                    let bd = b.candidate.dx_px.unsigned_abs()
                        + b.candidate.dy_px.unsigned_abs();
                    ad.cmp(&bd)
                })
                .then_with(|| a.candidate.id.cmp(&b.candidate.id))
        });

        let eligible: Vec<_> = reports.iter().filter(|report| report.eligible).collect();
        let (shadow_candidate_id, shadow_candidate_margin) =
            match eligible.first().copied() {
                Some(best) if best.candidate.id != "active" => {
                    let runner_score = eligible
                        .get(1)
                        .map(|report| report.operational_score)
                        .unwrap_or(0.0);
                    let margin = (best.operational_score - runner_score).max(0.0);
                    if margin >= self.config.min_operational_score_margin {
                        (Some(best.candidate.id.clone()), Some(margin))
                    } else {
                        (None, Some(margin))
                    }
                }
                _ => (None, None),
            };

        Ok(RoiSearchReport {
            schema_version: PERCEPTION_ADAPTATION_SCHEMA_VERSION,
            search_id: seed.search_id.clone(),
            active_candidate_id: "active".into(),
            evaluated_frames: frames.len(),
            candidates_generated: reports.len(),
            candidates: reports,
            shadow_candidate_id,
            shadow_candidate_margin,
            note: "shadow search only; candidate selection is not profile promotion".into(),
        })
    }
}

fn candidate_rejections(
    config: &RoiSearchConfig,
    frames: usize,
    health: &PerceptionHealthSnapshot,
    anchor_errors: usize,
    anchor_p50: Option<f32>,
) -> Vec<CandidateRejectionReason> {
    let mut reasons = Vec::new();
    if frames < config.min_frames {
        reasons.push(CandidateRejectionReason::InsufficientFrames);
    }
    if health.metrics.coverage_rate.unwrap_or(0.0) < config.min_coverage_rate {
        reasons.push(CandidateRejectionReason::Coverage);
    }
    if health.metrics.confidence_p50.unwrap_or(0.0) < config.min_confidence_p50 {
        reasons.push(CandidateRejectionReason::ConfidenceP50);
    }
    if anchor_p50.unwrap_or(-1.0) < config.min_anchor_similarity_p50 {
        reasons.push(CandidateRejectionReason::AnchorSimilarityP50);
    }
    if anchor_errors > 0 {
        reasons.push(CandidateRejectionReason::AnchorErrors);
    }
    reasons
}

fn operational_score(
    config: &RoiSearchConfig,
    health: &PerceptionHealthSnapshot,
    anchor_p50: Option<f32>,
) -> f32 {
    let coverage = health.metrics.coverage_rate.unwrap_or(0.0);
    let confidence = health.metrics.confidence_p50.unwrap_or(0.0);
    let anchor = ((anchor_p50.unwrap_or(-1.0) + 1.0) / 2.0).clamp(0.0, 1.0);
    let total = config.coverage_weight + config.confidence_weight + config.anchor_weight;
    ((coverage * config.coverage_weight
        + confidence * config.confidence_weight
        + anchor * config.anchor_weight)
        / total)
        .clamp(0.0, 1.0)
}

fn axis_offsets(max: u32, step: u32) -> Vec<i32> {
    let mut values = vec![0i32];
    let mut distance = step;
    while distance <= max {
        values.push(distance as i32);
        values.push(-(distance as i32));
        match distance.checked_add(step) {
            Some(next) => distance = next,
            None => break,
        }
    }
    values
}

fn translated(
    rect: NormalizedRect,
    dx_px: i32,
    dy_px: i32,
    width: u32,
    height: u32,
) -> Option<NormalizedRect> {
    let x = rect.x as f64 + dx_px as f64 / width as f64;
    let y = rect.y as f64 + dy_px as f64 / height as f64;
    NormalizedRect::new(
        x as f32,
        y as f32,
        rect.width,
        rect.height,
    )
    .ok()
}

fn percentile(sorted: &[f32], q: f32) -> Option<f32> {
    if sorted.is_empty() {
        return None;
    }
    let p = (sorted.len() - 1) as f32 * q;
    let lo = p.floor() as usize;
    let hi = p.ceil() as usize;
    Some(sorted[lo] + (sorted[hi] - sorted[lo]) * (p - lo as f32))
}

fn finite_unit(value: f32) -> bool {
    value.is_finite() && (0.0..=1.0).contains(&value)
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use agente_tft_capture_core::{PixelFormat, RoiFrame};
    use agente_tft_contracts::Confidence;

    use super::*;

    fn rect_px(x: u32, y: u32, w: u32, h: u32) -> NormalizedRect {
        NormalizedRect::new(
            x as f32 / 100.0,
            y as f32 / 40.0,
            w as f32 / 100.0,
            h as f32 / 40.0,
        )
        .unwrap()
    }

    fn blank_frame(id: u64, at: u64) -> FrameEnvelope {
        FrameEnvelope {
            frame_id: id,
            captured_at_ms: at,
            width: 100,
            height: 40,
            stride_bytes: 400,
            pixel_format: PixelFormat::Rgba8,
            source_id: "synthetic".into(),
            pixels: vec![0; 100 * 40 * 4],
        }
    }

    fn set_pixel(frame: &mut FrameEnvelope, x: u32, y: u32, value: u8) {
        let at = y as usize * frame.stride_bytes as usize + x as usize * 4;
        frame.pixels[at..at + 4].copy_from_slice(&[value, value, value, 255]);
    }

    fn paint_anchor(frame: &mut FrameEnvelope, x: u32, y: u32) {
        for yy in 0..8 {
            for xx in 0..8 {
                let value = if (xx + yy) % 3 == 0 { 240 } else { 40 };
                set_pixel(frame, x + xx, y + yy, value);
            }
        }
    }

    fn paint_read(frame: &mut FrameEnvelope, x: u32, y: u32) {
        for yy in 0..6 {
            for xx in 0..6 {
                set_pixel(frame, x + xx, y + yy, 245);
            }
        }
    }

    fn seed() -> RoiSearchSeed {
        RoiSearchSeed {
            search_id: "synthetic-shift".into(),
            subsystem: "hud".into(),
            field: "gold".into(),
            active_profile_id: "active-v4".into(),
            reference_width: 100,
            reference_height: 40,
            active_anchor_rect: rect_px(10, 10, 8, 8),
            active_read_rect: rect_px(20, 10, 6, 6),
        }
    }

    fn config() -> RoiSearchConfig {
        RoiSearchConfig {
            max_offset_x_px: 30,
            max_offset_y_px: 0,
            step_px: 10,
            max_candidates: 16,
            min_frames: 3,
            min_coverage_rate: 0.80,
            min_confidence_p50: 0.70,
            min_anchor_similarity_p50: 0.90,
            min_operational_score_margin: 0.03,
            coverage_weight: 0.4,
            confidence_weight: 0.3,
            anchor_weight: 0.3,
        }
    }

    fn health_policy() -> PerceptionHealthPolicy {
        PerceptionHealthPolicy {
            window_capacity: 16,
            min_samples: 3,
            recover_after_good_windows: 1,
            degrade_after_bad_windows: 1,
            ..PerceptionHealthPolicy::default()
        }
    }

    struct BrightProbe;
    impl RoiCandidateProbe for BrightProbe {
        fn probe(&mut self, frame: &FrameEnvelope, rect: NormalizedRect) -> PerceptionOutcome {
            let roi = match extract_roi(frame, rect) {
                Ok(value) => value,
                Err(_) => return PerceptionOutcome::Error,
            };
            let mean = mean_first_channel(&roi);
            if mean > 220.0 {
                PerceptionOutcome::Accepted {
                    confidence: Confidence::new(0.95).unwrap(),
                }
            } else {
                PerceptionOutcome::Unknown
            }
        }
    }

    fn mean_first_channel(roi: &RoiFrame) -> f32 {
        let bpp = roi.bytes_per_pixel;
        let mut sum = 0u64;
        let mut n = 0u64;
        for row in 0..roi.rect.height as usize {
            let start = row * roi.stride_bytes as usize;
            for col in 0..roi.rect.width as usize {
                sum += roi.pixels[start + col * bpp] as u64;
                n += 1;
            }
        }
        sum as f32 / n as f32
    }

    #[test]
    fn candidate_generation_is_bounded_and_keeps_active() {
        let search = RoiShadowSearch::new(config(), health_policy()).unwrap();
        let candidates = search.generate_candidates(&seed()).unwrap();
        assert!(candidates.len() <= 16);
        assert!(candidates.iter().any(|candidate| candidate.id == "active"));
        assert!(candidates.iter().all(|candidate| {
            candidate.read_rect.validate().is_ok()
                && candidate.anchor_rect.validate().is_ok()
        }));
    }

    #[test]
    fn synthetic_shift_is_found_without_expected_value() {
        let mut reference = blank_frame(0, 0);
        paint_anchor(&mut reference, 10, 10);
        paint_read(&mut reference, 20, 10);
        let anchor = AnchorTemplate::from_frame(
            &reference,
            seed().active_anchor_rect,
            DescriptorConfig { width: 8, height: 8 },
        )
        .unwrap();

        let mut frames = Vec::new();
        for (id, at) in [(1, 100), (2, 200), (3, 300)] {
            let mut frame = blank_frame(id, at);
            paint_anchor(&mut frame, 30, 10);
            paint_read(&mut frame, 40, 10);
            frames.push(frame);
        }

        let search = RoiShadowSearch::new(config(), health_policy()).unwrap();
        let report = search
            .evaluate(&seed(), &frames, &anchor, &mut BrightProbe)
            .unwrap();

        assert_eq!(report.shadow_candidate_id.as_deref(), Some("dx+20_dy+0"));
        let winner = report
            .candidates
            .iter()
            .find(|candidate| candidate.candidate.id == "dx+20_dy+0")
            .unwrap();
        assert!(winner.eligible);
        assert_eq!(winner.health.metrics.accepted, 3);
        assert!(winner.anchor_similarity_p50.unwrap() > 0.99);
        assert!(report.note.contains("not profile promotion"));
    }

    #[test]
    fn equal_candidates_are_ambiguous_and_abstain() {
        let mut reference = blank_frame(0, 0);
        paint_anchor(&mut reference, 10, 10);
        let anchor = AnchorTemplate::from_frame(
            &reference,
            seed().active_anchor_rect,
            DescriptorConfig { width: 8, height: 8 },
        )
        .unwrap();

        let mut frames = Vec::new();
        for (id, at) in [(1, 100), (2, 200), (3, 300)] {
            let mut frame = blank_frame(id, at);
            paint_anchor(&mut frame, 0, 10);
            paint_read(&mut frame, 10, 10);
            paint_anchor(&mut frame, 20, 10);
            paint_read(&mut frame, 30, 10);
            frames.push(frame);
        }

        let search = RoiShadowSearch::new(config(), health_policy()).unwrap();
        let report = search
            .evaluate(&seed(), &frames, &anchor, &mut BrightProbe)
            .unwrap();
        assert!(report.shadow_candidate_id.is_none());
        assert!(report.shadow_candidate_margin.unwrap_or(1.0) < 0.03);
    }

    #[test]
    fn active_best_produces_no_shadow_candidate() {
        let mut reference = blank_frame(0, 0);
        paint_anchor(&mut reference, 10, 10);
        paint_read(&mut reference, 20, 10);
        let anchor = AnchorTemplate::from_frame(
            &reference,
            seed().active_anchor_rect,
            DescriptorConfig { width: 8, height: 8 },
        )
        .unwrap();

        let frames = vec![reference.clone(), reference.clone(), reference];
        let search = RoiShadowSearch::new(config(), health_policy()).unwrap();
        let report = search
            .evaluate(&seed(), &frames, &anchor, &mut BrightProbe)
            .unwrap();
        assert!(report.shadow_candidate_id.is_none());
        assert_eq!(report.candidates[0].candidate.id, "active");
    }

    #[test]
    fn search_does_not_accept_too_few_frames() {
        let mut reference = blank_frame(0, 0);
        paint_anchor(&mut reference, 10, 10);
        let anchor = AnchorTemplate::from_frame(
            &reference,
            seed().active_anchor_rect,
            DescriptorConfig { width: 8, height: 8 },
        )
        .unwrap();
        let search = RoiShadowSearch::new(config(), health_policy()).unwrap();
        let report = search
            .evaluate(&seed(), &[reference], &anchor, &mut BrightProbe)
            .unwrap();
        assert!(report.shadow_candidate_id.is_none());
        assert!(report.candidates.iter().all(|candidate| {
            candidate
                .rejection_reasons
                .contains(&CandidateRejectionReason::InsufficientFrames)
        }));
    }

    #[test]
    fn invalid_configuration_is_rejected() {
        let mut bad = config();
        bad.step_px = 0;
        assert!(RoiShadowSearch::new(bad, health_policy()).is_err());
        let mut bad = config();
        bad.min_anchor_similarity_p50 = 2.0;
        assert!(RoiShadowSearch::new(bad, health_policy()).is_err());
    }

    #[test]
    fn candidate_profiles_are_isolated_in_health_streams() {
        let mut reference = blank_frame(0, 0);
        paint_anchor(&mut reference, 10, 10);
        paint_read(&mut reference, 20, 10);
        let anchor = AnchorTemplate::from_frame(
            &reference,
            seed().active_anchor_rect,
            DescriptorConfig { width: 8, height: 8 },
        )
        .unwrap();
        let frames = vec![reference.clone(), reference.clone(), reference];
        let search = RoiShadowSearch::new(config(), health_policy()).unwrap();
        let report = search
            .evaluate(&seed(), &frames, &anchor, &mut BrightProbe)
            .unwrap();
        let mut ids = BTreeMap::new();
        for candidate in report.candidates {
            ids.insert(candidate.health.stream.profile_id.clone(), ());
        }
        assert!(ids.len() > 1);
        assert!(ids.keys().all(|id| id.contains("::shadow::synthetic-shift::")));
    }

    #[test]
    fn report_round_trips_json() {
        let mut reference = blank_frame(0, 0);
        paint_anchor(&mut reference, 10, 10);
        paint_read(&mut reference, 20, 10);
        let anchor = AnchorTemplate::from_frame(
            &reference,
            seed().active_anchor_rect,
            DescriptorConfig { width: 8, height: 8 },
        )
        .unwrap();
        let frames = vec![reference.clone(), reference.clone(), reference];
        let search = RoiShadowSearch::new(config(), health_policy()).unwrap();
        let report = search
            .evaluate(&seed(), &frames, &anchor, &mut BrightProbe)
            .unwrap();
        let text = serde_json::to_string(&report).unwrap();
        let decoded: RoiSearchReport = serde_json::from_str(&text).unwrap();
        assert_eq!(decoded, report);
    }
}
