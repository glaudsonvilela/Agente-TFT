use std::collections::VecDeque;

use agente_tft_capture_core::{PixelFormat, PixelRect, RoiFrame};
use agente_tft_contracts::Confidence;
use agente_tft_image_preprocess::GrayImage;
use agente_tft_perception_hud::{
    read_roi_robust, HudField, HudOcrEngine, HudPreprocessConfig, HudReadPolicy, RecognizedText,
};

struct SequenceRecognizer {
    outputs: VecDeque<Result<Option<RecognizedText>, String>>,
}

impl SequenceRecognizer {
    fn from_values(values: &[(Option<&str>, f32)]) -> Self {
        let outputs = values
            .iter()
            .map(|(text, confidence)| {
                Ok(text.map(|text| RecognizedText {
                    text: text.to_string(),
                    confidence: Confidence::new(*confidence).unwrap(),
                }))
            })
            .collect();
        Self { outputs }
    }
}

impl HudOcrEngine for SequenceRecognizer {
    fn recognize(
        &mut self,
        _field: HudField,
        _image: &GrayImage,
    ) -> Result<Option<RecognizedText>, String> {
        self.outputs
            .pop_front()
            .unwrap_or_else(|| Ok(None))
    }
}

fn roi_fixture() -> RoiFrame {
    RoiFrame {
        source_frame_id: 1,
        captured_at_ms: 900,
        rect: PixelRect {
            x: 0,
            y: 0,
            width: 2,
            height: 1,
        },
        stride_bytes: 8,
        pixel_format: PixelFormat::Rgba8,
        bytes_per_pixel: 4,
        pixels: vec![
            0, 0, 0, 255,
            255, 255, 255, 255,
        ],
    }
}

fn policy() -> HudReadPolicy {
    HudReadPolicy {
        attempts: vec![
            HudPreprocessConfig {
                upscale_factor: 2,
                invert: false,
            },
            HudPreprocessConfig {
                upscale_factor: 3,
                invert: true,
            },
            HudPreprocessConfig {
                upscale_factor: 4,
                invert: false,
            },
        ],
        min_confidence: 0.70,
        ambiguity_margin: 0.03,
        ..HudReadPolicy::default()
    }
}

#[test]
fn chooses_highest_confidence_valid_candidate() {
    let mut engine = SequenceRecognizer::from_values(&[
        (Some("48"), 0.80),
        (Some("50"), 0.92),
        (Some("50"), 0.88),
    ]);

    let read = read_roi_robust(&mut engine, HudField::Gold, &roi_fixture(), &policy())
        .unwrap()
        .unwrap();

    assert_eq!(read.batch.gold.unwrap().value, 50);
    assert_eq!(read.recognized_text, "50");
    assert_eq!(read.confidence.value(), 0.92);
    assert_eq!(read.attempts_made, 3);
}

#[test]
fn invalid_high_confidence_value_is_rejected_by_domain_gate() {
    let mut engine = SequenceRecognizer::from_values(&[
        (Some("999"), 0.99),
        (Some("73"), 0.91),
        (None, 0.0),
    ]);

    let read = read_roi_robust(&mut engine, HudField::Hp, &roi_fixture(), &policy())
        .unwrap()
        .unwrap();

    assert_eq!(read.batch.hp.unwrap().value, 73);
}

#[test]
fn conflicting_near_equal_candidates_are_suppressed() {
    let mut engine = SequenceRecognizer::from_values(&[
        (Some("48"), 0.91),
        (Some("50"), 0.90),
        (None, 0.0),
    ]);

    let read = read_roi_robust(&mut engine, HudField::Gold, &roi_fixture(), &policy())
        .unwrap();

    assert!(read.is_none());
}

#[test]
fn low_confidence_reads_are_suppressed() {
    let mut engine = SequenceRecognizer::from_values(&[
        (Some("50"), 0.50),
        (Some("50"), 0.60),
        (None, 0.0),
    ]);

    assert!(read_roi_robust(&mut engine, HudField::Gold, &roi_fixture(), &policy())
        .unwrap()
        .is_none());
}
