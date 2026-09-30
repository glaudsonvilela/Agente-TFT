use agente_tft_capture_core::FrameEnvelope;
use agente_tft_contracts::{GameEventKind, GameState};
use agente_tft_perception_core::ConsensusConfig;
use agente_tft_perception_shop::{
    MatchCalibrator, ShopPerception, ShopPerceptionError, ShopSlotDiagnostic, UnitClassifier,
};
use agente_tft_state_fusion::{ShopObservationBatch, StateFusion};
use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ShopFrameResult {
    pub frame_id: u64,
    pub captured_at_ms: u64,
    pub complete_snapshot: bool,
    pub diagnostics: Vec<ShopSlotDiagnostic>,
    pub events: Vec<GameEventKind>,
    pub state_revision: u64,
}

pub struct ShopPipeline<C, K> {
    perception: ShopPerception<C, K>,
    fusion: StateFusion,
}

impl<C, K> ShopPipeline<C, K>
where
    C: UnitClassifier,
    K: MatchCalibrator,
{
    pub fn new(
        perception: ShopPerception<C, K>,
        now_ms: u64,
        consensus: ConsensusConfig,
    ) -> Self {
        Self {
            perception,
            fusion: StateFusion::new(now_ms, consensus),
        }
    }

    pub fn state(&self) -> &GameState {
        self.fusion.state()
    }

    pub fn perception(&self) -> &ShopPerception<C, K> {
        &self.perception
    }

    pub fn process_frame(
        &mut self,
        frame: &FrameEnvelope,
    ) -> Result<ShopFrameResult, ShopPerceptionError> {
        let result = self.perception.perceive(frame)?;
        let expected = self.perception.layout().slots.len();
        let complete_snapshot =
            result.observations.len() == expected
                && result.diagnostics.iter().all(|diagnostic| diagnostic.accepted);

        let events = if complete_snapshot {
            self.fusion.apply_shop(ShopObservationBatch {
                observed_at_ms: frame.captured_at_ms,
                slots: result.observations,
            })
        } else {
            Vec::new()
        };

        Ok(ShopFrameResult {
            frame_id: frame.frame_id,
            captured_at_ms: frame.captured_at_ms,
            complete_snapshot,
            diagnostics: result.diagnostics,
            events,
            state_revision: self.fusion.state().revision,
        })
    }
}

#[cfg(test)]
mod tests {
    use std::{
        cell::RefCell,
        collections::VecDeque,
        rc::Rc,
    };

    use agente_tft_capture_core::{NormalizedRect, PixelFormat};
    use agente_tft_contracts::Confidence;
    use agente_tft_image_preprocess::GrayImage;
    use agente_tft_perception_shop::{
        MatchCalibrator, RawUnitMatch, ShopLayout, ShopPerception, ShopSlotRegion,
        SHOP_LAYOUT_SCHEMA_VERSION,
    };

    use super::*;

    #[derive(Clone)]
    struct SequenceClassifier {
        values: Rc<RefCell<VecDeque<Option<RawUnitMatch>>>>,
    }

    impl UnitClassifier for SequenceClassifier {
        fn classify(
            &self,
            _image: &GrayImage,
        ) -> Result<Option<RawUnitMatch>, ShopPerceptionError> {
            Ok(self.values.borrow_mut().pop_front().flatten())
        }
    }

    #[derive(Clone)]
    struct FixedCalibration;

    impl MatchCalibrator for FixedCalibration {
        fn calibrate(
            &self,
            raw: &RawUnitMatch,
        ) -> Result<Option<Confidence>, ShopPerceptionError> {
            if raw.margin < 0.05 {
                Ok(None)
            } else {
                Ok(Some(Confidence::new(0.95).unwrap()))
            }
        }
    }

    fn layout() -> ShopLayout {
        ShopLayout {
            schema_version: SHOP_LAYOUT_SCHEMA_VERSION,
            name: "fixture".into(),
            reference_width: 4,
            reference_height: 1,
            slots: vec![
                ShopSlotRegion {
                    slot: 0,
                    rect: NormalizedRect::new(0.0, 0.0, 0.5, 1.0).unwrap(),
                },
                ShopSlotRegion {
                    slot: 1,
                    rect: NormalizedRect::new(0.5, 0.0, 0.5, 1.0).unwrap(),
                },
            ],
        }
    }

    fn frame(id: u64, at: u64) -> FrameEnvelope {
        FrameEnvelope {
            frame_id: id,
            captured_at_ms: at,
            width: 4,
            height: 1,
            stride_bytes: 16,
            pixel_format: PixelFormat::Rgba8,
            source_id: "fixture".into(),
            pixels: vec![
                0, 0, 0, 255,
                30, 30, 30, 255,
                200, 200, 200, 255,
                255, 255, 255, 255,
            ],
        }
    }

    fn raw(id: &str, margin: f32) -> Option<RawUnitMatch> {
        Some(RawUnitMatch {
            unit_id: id.into(),
            similarity: 0.95,
            margin,
        })
    }

    fn pipeline(values: Vec<Option<RawUnitMatch>>) -> ShopPipeline<SequenceClassifier, FixedCalibration> {
        let classifier = SequenceClassifier {
            values: Rc::new(RefCell::new(values.into())),
        };
        let perception = ShopPerception::new(layout(), classifier, FixedCalibration).unwrap();

        ShopPipeline::new(
            perception,
            0,
            ConsensusConfig {
                min_confidence: 0.80,
                confirmations: 2,
                max_gap_ms: 500,
            },
        )
    }

    #[test]
    fn partial_snapshot_never_reaches_state() {
        let mut pipeline = pipeline(vec![
            raw("A", 0.20),
            raw("B", 0.01), // rejected by calibration
        ]);

        let result = pipeline.process_frame(&frame(1, 100)).unwrap();
        assert!(!result.complete_snapshot);
        assert!(pipeline.state().player.shop.is_empty());
        assert_eq!(pipeline.state().revision, 0);
    }

    #[test]
    fn two_complete_equal_snapshots_are_promoted() {
        let mut pipeline = pipeline(vec![
            raw("A", 0.20),
            raw("B", 0.20),
            raw("A", 0.20),
            raw("B", 0.20),
        ]);

        let first = pipeline.process_frame(&frame(1, 100)).unwrap();
        assert!(first.complete_snapshot);
        assert_eq!(first.state_revision, 0);

        let second = pipeline.process_frame(&frame(2, 150)).unwrap();
        assert!(second.complete_snapshot);
        assert_eq!(pipeline.state().player.shop.len(), 2);
        assert_eq!(second.state_revision, 1);
        assert!(second
            .events
            .iter()
            .any(|event| matches!(event, GameEventKind::ShopChanged)));
    }

    #[test]
    fn contradictory_complete_snapshot_restarts_consensus() {
        let mut pipeline = pipeline(vec![
            raw("A", 0.20),
            raw("B", 0.20),
            raw("C", 0.20),
            raw("D", 0.20),
        ]);

        pipeline.process_frame(&frame(1, 100)).unwrap();
        pipeline.process_frame(&frame(2, 150)).unwrap();

        assert!(pipeline.state().player.shop.is_empty());
    }
}
