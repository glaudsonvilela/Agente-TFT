//! Compact stage localization, independent of seasonal champion/item catalogs.
//! Both known HUD positions are read at two scales. Conflicting values abstain.
use agente_tft_capture_core::{extract_roi, FrameEnvelope, NormalizedRect};
use agente_tft_contracts::Confidence;
use agente_tft_perception_hud::{
    parse_candidate, parse_stage, HudField, HudOcrEngine, HudPreprocessConfig, OcrCandidate,
    RobustHudRead,
};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
pub struct Candidate {
    name: String,
    rect: NormalizedRect,
}

#[derive(Deserialize)]
pub struct Config {
    schema_version: u32,
    reference_width: u32,
    reference_height: u32,
    candidates: Vec<Candidate>,
}

impl Config {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != 1
            || (self.reference_width, self.reference_height) != (1920, 1080)
            || self.candidates.is_empty()
            || self.candidates.len() > 4
        {
            return Err("invalid stage localization profile".into());
        }
        for (index, candidate) in self.candidates.iter().enumerate() {
            candidate.rect.validate().map_err(|e| e.to_string())?;
            if candidate.name.is_empty()
                || candidate.rect.width > 0.1
                || candidate.rect.height > 0.1
                || self.candidates[..index]
                    .iter()
                    .any(|c| c.name == candidate.name || c.rect == candidate.rect)
            {
                return Err("invalid/duplicate stage candidate".into());
            }
        }
        Ok(())
    }
}

#[derive(Clone)]
pub struct Observation {
    pub read: Option<RobustHudRead>,
    pub details: Value,
    pub cache_hit: bool,
}

pub struct Reader {
    config: Config,
    cached: Option<(Vec<u8>, Observation, u64, u64)>,
}

impl Reader {
    pub fn new(config: Config) -> Result<Self, String> {
        config.validate()?;
        Ok(Self {
            config,
            cached: None,
        })
    }

    pub fn observe(
        &mut self,
        frame: &FrameEnvelope,
        engine: &mut impl HudOcrEngine,
    ) -> Result<Observation, String> {
        let rois = self
            .config
            .candidates
            .iter()
            .map(|c| extract_roi(frame, c.rect))
            .collect::<Result<Vec<_>, _>>()
            .map_err(|e| e.to_string())?;
        let signature: Vec<u8> = rois
            .iter()
            .flat_map(|roi| roi.pixels.iter().copied())
            .collect();
        if let Some((pixels, observation, source_id, source_ms)) = &self.cached {
            if *pixels == signature {
                let mut observation = observation.clone();
                observation.cache_hit = true;
                if let Some(read) = &mut observation.read {
                    read.batch.observed_at_ms = frame.captured_at_ms;
                    if let Some(stage) = &mut read.batch.stage {
                        stage.observed_at_ms = frame.captured_at_ms;
                    }
                }
                observation.details["cache_delivery"] = json!({"exact_roi_rgb":true,
                    "source_frame_id":source_id,"source_ms":source_ms,"delivered_frame_id":frame.frame_id});
                return Ok(observation);
            }
        }
        let mut values = Vec::<String>::new();
        let mut accepted = None;
        let mut attempts = Vec::new();
        for (candidate, roi) in self.config.candidates.iter().zip(&rois) {
            let mut agreeing = Vec::new();
            // The small TFT stage glyph loses its leading digit at 4x on some
            // native replays. The 2x/3x pair preserves it more consistently.
            for scale in [2, 3] {
                let config = HudPreprocessConfig {
                    upscale_factor: scale,
                    invert: true,
                };
                // Neutral grayscale preparation; recognition retains stage's
                // hyphen whitelist and parser, never the level parser.
                let image = engine
                    .prepare_roi(HudField::Level, roi, config)
                    .map_err(|e| format!("{e:?}"))?;
                let recognized = engine.recognize(HudField::Stage, &image)?;
                let mut trace =
                    json!({"candidate":candidate.name,"scale":scale,"text":null,"confidence":null});
                if let Some(text) = recognized {
                    trace["text"] = json!(text.text);
                    trace["confidence"] = json!(text.confidence.value());
                    let compact: String =
                        text.text.chars().filter(|c| !c.is_whitespace()).collect();
                    if text.confidence.value() >= 0.80 && compact.matches('-').count() == 1 {
                        if let Ok(value) = parse_stage(&compact) {
                            if !values.contains(&value) {
                                values.push(value.clone());
                            }
                            agreeing.push((value, text.confidence.value()));
                        }
                    }
                }
                attempts.push(trace);
            }
            if agreeing.len() == 2 && agreeing[0].0 == agreeing[1].0 && accepted.is_none() {
                accepted = Some((
                    candidate,
                    agreeing[0].0.clone(),
                    agreeing[0].1.min(agreeing[1].1),
                ));
            }
        }
        let mut details = json!({"profile":"stage_localization_v1","attempts":attempts,
            "temporal_consensus":false,"reason":"no_scale_consensus"});
        let read = if values.len() > 1 {
            details["reason"] = json!("conflicting_candidates");
            None
        } else if let Some((candidate, value, confidence)) = accepted {
            let confidence = Confidence::new(confidence).map_err(|e| e.to_string())?;
            let batch = parse_candidate(OcrCandidate {
                field: HudField::Stage,
                text: value.clone(),
                confidence,
                observed_at_ms: frame.captured_at_ms,
            })
            .map_err(|e| format!("{e:?}"))?;
            details["reason"] = json!("two_scale_consensus");
            details["selected_candidate"] = json!(candidate.name);
            details["normalized_rect"] = json!(candidate.rect);
            Some(RobustHudRead {
                batch,
                recognized_text: value,
                confidence,
                preprocess: HudPreprocessConfig {
                    upscale_factor: 2,
                    invert: true,
                },
                attempts_made: rois.len() * 2,
            })
        } else {
            None
        };
        let observation = Observation {
            read,
            details,
            cache_hit: false,
        };
        self.cached = Some((
            signature,
            observation.clone(),
            frame.frame_id,
            frame.captured_at_ms,
        ));
        Ok(observation)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use agente_tft_capture_core::{PixelFormat, RoiFrame};
    use agente_tft_image_preprocess::GrayImage;
    use agente_tft_perception_hud::{HudReadError, RecognizedText};
    use std::collections::VecDeque;

    struct Fake(VecDeque<Option<RecognizedText>>);
    impl HudOcrEngine for Fake {
        fn prepare_roi(
            &self,
            field: HudField,
            _: &RoiFrame,
            _: HudPreprocessConfig,
        ) -> Result<GrayImage, HudReadError> {
            assert_eq!(field, HudField::Level);
            Ok(GrayImage {
                width: 1,
                height: 1,
                stride_bytes: 1,
                pixels: vec![255],
            })
        }
        fn recognize(
            &mut self,
            field: HudField,
            _: &GrayImage,
        ) -> Result<Option<RecognizedText>, String> {
            assert_eq!(field, HudField::Stage);
            Ok(self.0.pop_front().expect("unexpected OCR call"))
        }
    }
    fn fake(values: &[Option<(&str, f32)>]) -> Fake {
        Fake(
            values
                .iter()
                .map(|entry| {
                    entry.map(|(text, confidence)| RecognizedText {
                        text: text.into(),
                        confidence: Confidence::new(confidence).unwrap(),
                    })
                })
                .collect(),
        )
    }
    fn setup() -> (Reader, FrameEnvelope) {
        let config: Config = serde_json::from_str(include_str!(
            "../../../configs/hud/tft-1920x1080-match001-v4-stage-recovery.json"
        ))
        .unwrap();
        (
            Reader::new(config).unwrap(),
            FrameEnvelope {
                frame_id: 1,
                captured_at_ms: 500,
                width: 1920,
                height: 1080,
                stride_bytes: 5760,
                pixel_format: PixelFormat::Rgb8,
                source_id: "test".into(),
                pixels: vec![0; 1920 * 1080 * 3],
            },
        )
    }
    #[test]
    fn initial_stage_uses_its_own_location_and_requires_both_scales() {
        let (mut reader, frame) = setup();
        let mut ocr = fake(&[None, None, Some(("1-4", 0.97)), Some(("1-4", 0.93))]);
        let result = reader.observe(&frame, &mut ocr).unwrap();
        assert_eq!(result.read.unwrap().batch.stage.unwrap().value, "1-4");
        assert_eq!(result.details["selected_candidate"], "initial");
        let cached = reader.observe(&frame, &mut ocr).unwrap();
        assert!(cached.cache_hit);
    }
    #[test]
    fn conflicting_candidates_low_confidence_and_nonliteral_hyphens_abstain() {
        for values in [
            [
                Some(("2-1", 0.96)),
                Some(("2-1", 0.97)),
                Some(("1-4", 0.98)),
                Some(("1-4", 0.98)),
            ],
            [None, None, Some(("1-4", 0.79)), Some(("1-4", 0.97))],
            [None, None, Some(("1 4", 0.97)), Some(("1 4", 0.97))],
            [None, None, None, None],
        ] {
            let (mut reader, frame) = setup();
            assert!(reader
                .observe(&frame, &mut fake(&values))
                .unwrap()
                .read
                .is_none());
        }
    }
    #[test]
    fn cache_observes_changes_at_the_initial_location_too() {
        let (mut reader, mut frame) = setup();
        reader.observe(&frame, &mut fake(&[None; 4])).unwrap();
        // Inside the initial-stage rectangle, outside the old fixed rectangle.
        frame.pixels[(10 * 1920 + 830) * 3] = 255;
        let result = reader
            .observe(
                &frame,
                &mut fake(&[None, None, Some(("1-1", 0.97)), Some(("1-1", 0.98))]),
            )
            .unwrap();
        assert!(!result.cache_hit);
        assert_eq!(result.read.unwrap().recognized_text, "1-1");
    }
}
