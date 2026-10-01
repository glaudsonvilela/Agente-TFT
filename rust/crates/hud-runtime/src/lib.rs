use std::collections::HashSet;

use agente_tft_capture_core::{extract_roi, CaptureError, FrameEnvelope, NormalizedRect};
use agente_tft_contracts::{GameEventKind, GameState};
use agente_tft_perception_core::ConsensusConfig;
use agente_tft_perception_hud::{
    merge_batches, read_roi_robust, HudField, HudOcrEngine, HudReadPolicy,
};
use agente_tft_state_fusion::StateFusion;
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const HUD_LAYOUT_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Error)]
pub enum HudRuntimeError {
    #[error("invalid HUD layout: {0}")]
    InvalidLayout(String),
    #[error("capture error: {0}")]
    Capture(#[from] CaptureError),
    #[error("HUD read failed for {field:?}: {detail}")]
    Read { field: HudField, detail: String },
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HudRegionSpec {
    pub field: HudField,
    pub rect: NormalizedRect,
    #[serde(default)]
    pub policy: HudReadPolicy,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HudLayout {
    pub schema_version: u32,
    pub name: String,
    pub reference_width: u32,
    pub reference_height: u32,
    pub regions: Vec<HudRegionSpec>,
}

impl HudLayout {
    pub fn validate(&self) -> Result<(), HudRuntimeError> {
        if self.schema_version != HUD_LAYOUT_SCHEMA_VERSION {
            return Err(HudRuntimeError::InvalidLayout(format!(
                "unsupported schema_version {}",
                self.schema_version
            )));
        }
        if self.name.trim().is_empty() {
            return Err(HudRuntimeError::InvalidLayout(
                "name cannot be empty".into(),
            ));
        }
        if self.reference_width == 0 || self.reference_height == 0 {
            return Err(HudRuntimeError::InvalidLayout(
                "reference dimensions must be > 0".into(),
            ));
        }
        if self.regions.is_empty() {
            return Err(HudRuntimeError::InvalidLayout(
                "at least one HUD region is required".into(),
            ));
        }

        let mut seen = HashSet::new();
        for region in &self.regions {
            region
                .rect
                .validate()
                .map_err(|e| HudRuntimeError::InvalidLayout(e.to_string()))?;

            if !seen.insert(region.field) {
                return Err(HudRuntimeError::InvalidLayout(format!(
                    "duplicate HUD field {:?}",
                    region.field
                )));
            }

            region.policy.validate().map_err(HudRuntimeError::InvalidLayout)?;
            if !region.policy.min_confidence.is_finite()
                || !(0.0..=1.0).contains(&region.policy.min_confidence)
            {
                return Err(HudRuntimeError::InvalidLayout(format!(
                    "invalid min_confidence for {:?}",
                    region.field
                )));
            }
        }

        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct HudFieldRead {
    pub field: HudField,
    pub recognized_text: String,
    pub confidence: f32,
    pub upscale_factor: u8,
    pub inverted: bool,
    pub attempts_made: usize,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct HudFrameResult {
    pub frame_id: u64,
    pub captured_at_ms: u64,
    pub accepted_reads: Vec<HudFieldRead>,
    pub events: Vec<GameEventKind>,
    pub state_revision: u64,
}

pub struct HudPipeline<E> {
    engine: E,
    layout: HudLayout,
    fusion: StateFusion,
}

impl<E> HudPipeline<E>
where
    E: HudOcrEngine,
{
    pub fn new(
        engine: E,
        layout: HudLayout,
        now_ms: u64,
        consensus: ConsensusConfig,
    ) -> Result<Self, HudRuntimeError> {
        layout.validate()?;
        Ok(Self {
            engine,
            layout,
            fusion: StateFusion::new(now_ms, consensus),
        })
    }

    pub fn layout(&self) -> &HudLayout {
        &self.layout
    }

    pub fn state(&self) -> &GameState {
        self.fusion.state()
    }

    pub fn engine_mut(&mut self) -> &mut E {
        &mut self.engine
    }

    pub fn process_frame(
        &mut self,
        frame: &FrameEnvelope,
    ) -> Result<HudFrameResult, HudRuntimeError> {
        frame.validate()?;

        let mut reads = Vec::new();
        let mut batches = Vec::new();

        for region in &self.layout.regions {
            let roi = extract_roi(frame, region.rect)?;
            let robust = read_roi_robust(
                &mut self.engine,
                region.field,
                &roi,
                &region.policy,
            )
            .map_err(|error| HudRuntimeError::Read {
                field: region.field,
                detail: format!("{error:?}"),
            })?;

            if let Some(robust) = robust {
                reads.push(HudFieldRead {
                    field: region.field,
                    recognized_text: robust.recognized_text,
                    confidence: robust.confidence.value(),
                    upscale_factor: robust.preprocess.upscale_factor,
                    inverted: robust.preprocess.invert,
                    attempts_made: robust.attempts_made,
                });
                batches.push(robust.batch);
            }
        }

        let mut merged = merge_batches(batches);
        merged.observed_at_ms = frame.captured_at_ms;
        let events = self.fusion.apply_hud(merged);

        Ok(HudFrameResult {
            frame_id: frame.frame_id,
            captured_at_ms: frame.captured_at_ms,
            accepted_reads: reads,
            events,
            state_revision: self.fusion.state().revision,
        })
    }
}

#[cfg(test)]
mod tests {
    use std::collections::VecDeque;

    use agente_tft_capture_core::PixelFormat;
    use agente_tft_contracts::Confidence;
    use agente_tft_image_preprocess::GrayImage;
    use agente_tft_perception_hud::{
        HudPreprocessConfig, RecognizedText,
    };

    use super::*;

    struct FakeEngine {
        outputs: VecDeque<Option<RecognizedText>>,
    }

    impl HudOcrEngine for FakeEngine {
        fn recognize(
            &mut self,
            _field: HudField,
            _image: &GrayImage,
        ) -> Result<Option<RecognizedText>, String> {
            Ok(self.outputs.pop_front().flatten())
        }
    }

    fn layout() -> HudLayout {
        HudLayout {
            schema_version: HUD_LAYOUT_SCHEMA_VERSION,
            name: "fixture".into(),
            reference_width: 100,
            reference_height: 100,
            regions: vec![HudRegionSpec {
                field: HudField::Gold,
                rect: NormalizedRect::new(0.0, 0.0, 1.0, 1.0).unwrap(),
                policy: HudReadPolicy {
                    attempts: vec![HudPreprocessConfig {
                        upscale_factor: 1,
                        invert: false,
                    }],
                    min_confidence: 0.7,
                    ambiguity_margin: 0.03,
                    ..HudReadPolicy::default()
                },
            }],
        }
    }

    fn frame(id: u64, at: u64) -> FrameEnvelope {
        FrameEnvelope {
            frame_id: id,
            captured_at_ms: at,
            width: 2,
            height: 1,
            stride_bytes: 8,
            pixel_format: PixelFormat::Rgba8,
            source_id: "fixture".into(),
            pixels: vec![0, 0, 0, 255, 255, 255, 255, 255],
        }
    }

    fn text(value: &str, confidence: f32) -> Option<RecognizedText> {
        Some(RecognizedText {
            text: value.into(),
            confidence: Confidence::new(confidence).unwrap(),
        })
    }

    #[test]
    fn duplicate_fields_are_rejected() {
        let mut invalid = layout();
        invalid.regions.push(invalid.regions[0].clone());
        assert!(invalid.validate().is_err());
    }

    #[test]
    fn pipeline_requires_temporal_consensus_before_state_change() {
        let engine = FakeEngine {
            outputs: VecDeque::from([text("50", 0.95), text("50", 0.96)]),
        };
        let mut pipeline = HudPipeline::new(
            engine,
            layout(),
            0,
            ConsensusConfig {
                min_confidence: 0.8,
                confirmations: 2,
                max_gap_ms: 500,
            },
        )
        .unwrap();

        let first = pipeline.process_frame(&frame(1, 100)).unwrap();
        assert_eq!(first.state_revision, 0);
        assert!(pipeline.state().player.gold.is_none());

        let second = pipeline.process_frame(&frame(2, 150)).unwrap();
        assert_eq!(second.state_revision, 1);
        assert_eq!(pipeline.state().player.gold.as_ref().unwrap().value, 50);
    }

    #[test]
    fn stable_change_produces_gold_event() {
        let engine = FakeEngine {
            outputs: VecDeque::from([
                text("50", 0.95),
                text("50", 0.95),
                text("48", 0.95),
                text("48", 0.95),
            ]),
        };
        let mut pipeline = HudPipeline::new(
            engine,
            layout(),
            0,
            ConsensusConfig {
                min_confidence: 0.8,
                confirmations: 2,
                max_gap_ms: 500,
            },
        )
        .unwrap();

        pipeline.process_frame(&frame(1, 100)).unwrap();
        pipeline.process_frame(&frame(2, 150)).unwrap();
        pipeline.process_frame(&frame(3, 200)).unwrap();
        let result = pipeline.process_frame(&frame(4, 250)).unwrap();

        assert!(result.events.iter().any(|event| matches!(
            event,
            GameEventKind::GoldChanged { from: 50, to: 48 }
        )));
    }
}
