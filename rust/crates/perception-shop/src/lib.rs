use agente_tft_capture_core::{extract_roi, CaptureError, FrameEnvelope, NormalizedRect};
use agente_tft_contracts::{Confidence, ObservationSource, Observed, ShopSlot};
use agente_tft_image_preprocess::to_luma;
use agente_tft_visual_match::{MatchResult, TemplateIndex, VisualMatchError};
use serde::{Deserialize, Serialize};
use thiserror::Error;

pub const SHOP_LAYOUT_SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Error)]
pub enum ShopPerceptionError {
    #[error("invalid shop layout: {0}")]
    InvalidLayout(String),
    #[error("capture error: {0}")]
    Capture(#[from] CaptureError),
    #[error("visual matcher error: {0}")]
    Visual(#[from] VisualMatchError),
    #[error("invalid calibration: {0}")]
    InvalidCalibration(String),
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ShopSlotRegion {
    pub slot: u8,
    pub rect: NormalizedRect,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ShopLayout {
    pub schema_version: u32,
    pub name: String,
    pub reference_width: u32,
    pub reference_height: u32,
    pub slots: Vec<ShopSlotRegion>,
}

impl ShopLayout {
    pub fn validate(&self) -> Result<(), ShopPerceptionError> {
        if self.schema_version != SHOP_LAYOUT_SCHEMA_VERSION {
            return Err(ShopPerceptionError::InvalidLayout(format!(
                "unsupported schema_version {}",
                self.schema_version
            )));
        }
        if self.name.trim().is_empty() {
            return Err(ShopPerceptionError::InvalidLayout(
                "name cannot be empty".into(),
            ));
        }
        if self.reference_width == 0 || self.reference_height == 0 {
            return Err(ShopPerceptionError::InvalidLayout(
                "reference dimensions must be > 0".into(),
            ));
        }
        if self.slots.is_empty() {
            return Err(ShopPerceptionError::InvalidLayout(
                "at least one shop slot is required".into(),
            ));
        }

        let mut seen = std::collections::BTreeSet::new();
        for slot in &self.slots {
            slot.rect
                .validate()
                .map_err(|e| ShopPerceptionError::InvalidLayout(e.to_string()))?;
            if !seen.insert(slot.slot) {
                return Err(ShopPerceptionError::InvalidLayout(format!(
                    "duplicate shop slot {}",
                    slot.slot
                )));
            }
        }

        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct RawUnitMatch {
    pub unit_id: String,
    pub similarity: f32,
    pub margin: f32,
}

pub trait UnitClassifier {
    fn classify(
        &self,
        image: &agente_tft_image_preprocess::GrayImage,
    ) -> Result<Option<RawUnitMatch>, ShopPerceptionError>;
}

impl UnitClassifier for TemplateIndex {
    fn classify(
        &self,
        image: &agente_tft_image_preprocess::GrayImage,
    ) -> Result<Option<RawUnitMatch>, ShopPerceptionError> {
        let result: Option<MatchResult> = TemplateIndex::classify(self, image)?;
        Ok(result.map(|result| RawUnitMatch {
            unit_id: result.best.id,
            similarity: result.best.similarity,
            margin: result.margin,
        }))
    }
}

pub trait MatchCalibrator {
    fn calibrate(
        &self,
        raw: &RawUnitMatch,
    ) -> Result<Option<Confidence>, ShopPerceptionError>;
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct LogisticCalibration {
    pub bias: f32,
    pub similarity_weight: f32,
    pub margin_weight: f32,
    pub min_confidence: f32,
}

impl LogisticCalibration {
    pub fn validate(self) -> Result<(), ShopPerceptionError> {
        let values = [
            self.bias,
            self.similarity_weight,
            self.margin_weight,
            self.min_confidence,
        ];
        if values.iter().any(|v| !v.is_finite()) {
            return Err(ShopPerceptionError::InvalidCalibration(
                "all calibration values must be finite".into(),
            ));
        }
        if !(0.0..=1.0).contains(&self.min_confidence) {
            return Err(ShopPerceptionError::InvalidCalibration(
                "min_confidence must be in [0,1]".into(),
            ));
        }
        Ok(())
    }

    fn probability(self, raw: &RawUnitMatch) -> Result<f32, ShopPerceptionError> {
        self.validate()?;
        if !raw.similarity.is_finite() || !raw.margin.is_finite() {
            return Err(ShopPerceptionError::InvalidCalibration(
                "raw visual scores must be finite".into(),
            ));
        }

        let z = self.bias
            + self.similarity_weight * raw.similarity
            + self.margin_weight * raw.margin;
        let probability = if z >= 0.0 {
            1.0 / (1.0 + (-z).exp())
        } else {
            let ez = z.exp();
            ez / (1.0 + ez)
        };
        Ok(probability.clamp(0.0, 1.0))
    }
}

impl MatchCalibrator for LogisticCalibration {
    fn calibrate(
        &self,
        raw: &RawUnitMatch,
    ) -> Result<Option<Confidence>, ShopPerceptionError> {
        let probability = self.probability(raw)?;
        if probability < self.min_confidence {
            return Ok(None);
        }
        Ok(Some(
            Confidence::new(probability)
                .map_err(|e| ShopPerceptionError::InvalidCalibration(e.to_string()))?,
        ))
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct ShopSlotDiagnostic {
    pub slot: u8,
    pub unit_id: Option<String>,
    pub similarity: Option<f32>,
    pub margin: Option<f32>,
    pub confidence: Option<f32>,
    pub accepted: bool,
}

#[derive(Debug, Clone, PartialEq)]
pub struct ShopPerceptionResult {
    pub observations: Vec<Observed<ShopSlot>>,
    pub diagnostics: Vec<ShopSlotDiagnostic>,
}

pub struct ShopPerception<C, K> {
    layout: ShopLayout,
    classifier: C,
    calibrator: K,
}

impl<C, K> ShopPerception<C, K>
where
    C: UnitClassifier,
    K: MatchCalibrator,
{
    pub fn new(
        layout: ShopLayout,
        classifier: C,
        calibrator: K,
    ) -> Result<Self, ShopPerceptionError> {
        layout.validate()?;
        Ok(Self {
            layout,
            classifier,
            calibrator,
        })
    }

    pub fn layout(&self) -> &ShopLayout {
        &self.layout
    }

    pub fn perceive(
        &self,
        frame: &FrameEnvelope,
    ) -> Result<ShopPerceptionResult, ShopPerceptionError> {
        frame.validate()?;
        let mut observations = Vec::with_capacity(self.layout.slots.len());
        let mut diagnostics = Vec::with_capacity(self.layout.slots.len());

        for region in &self.layout.slots {
            let roi = extract_roi(frame, region.rect)?;
            let gray = to_luma(&roi)?;
            let raw = self.classifier.classify(&gray)?;

            match raw {
                None => {
                    diagnostics.push(ShopSlotDiagnostic {
                        slot: region.slot,
                        unit_id: None,
                        similarity: None,
                        margin: None,
                        confidence: None,
                        accepted: false,
                    });
                }
                Some(raw) => {
                    let calibrated = self.calibrator.calibrate(&raw)?;
                    let confidence = calibrated.map(|c| c.value());

                    diagnostics.push(ShopSlotDiagnostic {
                        slot: region.slot,
                        unit_id: Some(raw.unit_id.clone()),
                        similarity: Some(raw.similarity),
                        margin: Some(raw.margin),
                        confidence,
                        accepted: calibrated.is_some(),
                    });

                    if let Some(confidence) = calibrated {
                        observations.push(Observed {
                            value: ShopSlot {
                                slot: region.slot,
                                unit_id: Some(raw.unit_id),
                            },
                            confidence,
                            source: ObservationSource::Vision,
                            observed_at_ms: frame.captured_at_ms,
                        });
                    }
                }
            }
        }

        Ok(ShopPerceptionResult {
            observations,
            diagnostics,
        })
    }
}

#[cfg(test)]
mod tests {
    use agente_tft_capture_core::PixelFormat;
    use agente_tft_image_preprocess::GrayImage;

    use super::*;

    #[derive(Clone)]
    struct FakeClassifier {
        result: Option<RawUnitMatch>,
    }

    impl UnitClassifier for FakeClassifier {
        fn classify(
            &self,
            _image: &GrayImage,
        ) -> Result<Option<RawUnitMatch>, ShopPerceptionError> {
            Ok(self.result.clone())
        }
    }

    #[derive(Clone)]
    struct FixedCalibrator(Option<Confidence>);

    impl MatchCalibrator for FixedCalibrator {
        fn calibrate(
            &self,
            _raw: &RawUnitMatch,
        ) -> Result<Option<Confidence>, ShopPerceptionError> {
            Ok(self.0)
        }
    }

    fn layout() -> ShopLayout {
        ShopLayout {
            schema_version: SHOP_LAYOUT_SCHEMA_VERSION,
            name: "fixture".into(),
            reference_width: 10,
            reference_height: 10,
            slots: vec![ShopSlotRegion {
                slot: 0,
                rect: NormalizedRect::new(0.0, 0.0, 1.0, 1.0).unwrap(),
            }],
        }
    }

    fn frame() -> FrameEnvelope {
        FrameEnvelope {
            frame_id: 1,
            captured_at_ms: 100,
            width: 2,
            height: 1,
            stride_bytes: 8,
            pixel_format: PixelFormat::Rgba8,
            source_id: "fixture".into(),
            pixels: vec![
                0, 0, 0, 255,
                255, 255, 255, 255,
            ],
        }
    }

    #[test]
    fn accepted_calibrated_match_enters_observations() {
        let perception = ShopPerception::new(
            layout(),
            FakeClassifier {
                result: Some(RawUnitMatch {
                    unit_id: "TFT_Unit_A".into(),
                    similarity: 0.95,
                    margin: 0.20,
                }),
            },
            FixedCalibrator(Some(Confidence::new(0.91).unwrap())),
        )
        .unwrap();

        let result = perception.perceive(&frame()).unwrap();
        assert_eq!(result.observations.len(), 1);
        assert_eq!(
            result.observations[0].value.unit_id.as_deref(),
            Some("TFT_Unit_A")
        );
        assert_eq!(result.observations[0].confidence.value(), 0.91);
    }

    #[test]
    fn uncalibrated_match_never_enters_state_observation() {
        let perception = ShopPerception::new(
            layout(),
            FakeClassifier {
                result: Some(RawUnitMatch {
                    unit_id: "TFT_Unit_A".into(),
                    similarity: 0.95,
                    margin: 0.01,
                }),
            },
            FixedCalibrator(None),
        )
        .unwrap();

        let result = perception.perceive(&frame()).unwrap();
        assert!(result.observations.is_empty());
        assert!(!result.diagnostics[0].accepted);
    }

    #[test]
    fn logistic_calibration_requires_explicit_fitted_parameters() {
        let calibration = LogisticCalibration {
            bias: -5.0,
            similarity_weight: 6.0,
            margin_weight: 3.0,
            min_confidence: 0.80,
        };
        let raw = RawUnitMatch {
            unit_id: "A".into(),
            similarity: 0.99,
            margin: 0.40,
        };

        let confidence = calibration.calibrate(&raw).unwrap().unwrap();
        assert!(confidence.value() >= 0.80);
    }

    #[test]
    fn duplicate_slots_are_rejected() {
        let mut invalid = layout();
        invalid.slots.push(invalid.slots[0].clone());
        assert!(invalid.validate().is_err());
    }
}
