use agente_tft_capture_core::RoiFrame;
use agente_tft_contracts::{Confidence, ObservationSource, Observed};
use agente_tft_image_preprocess::{preprocess_for_numeric_ocr, GrayImage};
use agente_tft_state_fusion::HudObservationBatch;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HudField {
    Stage,
    Gold,
    Hp,
    Level,
    Xp,
}

#[derive(Debug, Clone, PartialEq)]
pub struct OcrCandidate {
    pub field: HudField,
    pub text: String,
    pub confidence: Confidence,
    pub observed_at_ms: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HudParseError {
    Empty,
    InvalidCharacters,
    InvalidNumber,
    OutOfRange,
    InvalidStage,
}

#[derive(Debug, Clone, PartialEq)]
pub struct RecognizedText {
    pub text: String,
    pub confidence: Confidence,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct HudPreprocessConfig {
    pub upscale_factor: u8,
    pub invert: bool,
}

impl Default for HudPreprocessConfig {
    fn default() -> Self {
        Self {
            upscale_factor: 3,
            invert: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HudReadError {
    Preprocess(String),
    Recognizer(String),
    Parse(HudParseError),
}

pub trait HudOcrEngine {
    fn recognize(
        &mut self,
        field: HudField,
        image: &GrayImage,
    ) -> Result<Option<RecognizedText>, String>;
}

pub fn read_roi_with_ocr(
    engine: &mut impl HudOcrEngine,
    field: HudField,
    roi: &RoiFrame,
    config: HudPreprocessConfig,
) -> Result<Option<HudObservationBatch>, HudReadError> {
    let image = preprocess_for_numeric_ocr(roi, config.upscale_factor, config.invert)
        .map_err(|e| HudReadError::Preprocess(e.to_string()))?;

    let Some(recognized) = engine
        .recognize(field, &image)
        .map_err(HudReadError::Recognizer)?
    else {
        return Ok(None);
    };

    let candidate = OcrCandidate {
        field,
        text: recognized.text,
        confidence: recognized.confidence,
        observed_at_ms: roi.captured_at_ms,
    };

    parse_candidate(candidate)
        .map(Some)
        .map_err(HudReadError::Parse)
}

pub fn parse_candidate(candidate: OcrCandidate) -> Result<HudObservationBatch, HudParseError> {
    let mut batch = HudObservationBatch {
        observed_at_ms: candidate.observed_at_ms,
        ..HudObservationBatch::default()
    };

    match candidate.field {
        HudField::Stage => {
            let value = parse_stage(&candidate.text)?;
            batch.stage = Some(observed(
                value,
                candidate.confidence,
                candidate.observed_at_ms,
            ));
        }
        HudField::Gold => {
            let value = parse_u16_bounded(&candidate.text, 0, 999)?;
            batch.gold = Some(observed(
                value,
                candidate.confidence,
                candidate.observed_at_ms,
            ));
        }
        HudField::Hp => {
            let value = parse_u16_bounded(&candidate.text, 0, 100)?;
            batch.hp = Some(observed(
                value,
                candidate.confidence,
                candidate.observed_at_ms,
            ));
        }
        HudField::Level => {
            let value = parse_u8_bounded(&candidate.text, 1, 12)?;
            batch.level = Some(observed(
                value,
                candidate.confidence,
                candidate.observed_at_ms,
            ));
        }
        HudField::Xp => {
            let value = parse_u16_bounded(&candidate.text, 0, 999)?;
            batch.xp = Some(observed(
                value,
                candidate.confidence,
                candidate.observed_at_ms,
            ));
        }
    }

    Ok(batch)
}

pub fn merge_batches(batches: impl IntoIterator<Item = HudObservationBatch>) -> HudObservationBatch {
    let mut merged = HudObservationBatch::default();

    for batch in batches {
        merged.observed_at_ms = merged.observed_at_ms.max(batch.observed_at_ms);
        if batch.hp.is_some() {
            merged.hp = batch.hp;
        }
        if batch.gold.is_some() {
            merged.gold = batch.gold;
        }
        if batch.level.is_some() {
            merged.level = batch.level;
        }
        if batch.xp.is_some() {
            merged.xp = batch.xp;
        }
        if batch.stage.is_some() {
            merged.stage = batch.stage;
        }
    }

    merged
}

pub fn parse_stage(raw: &str) -> Result<String, HudParseError> {
    let cleaned = normalize_text(raw)?;
    let normalized = cleaned
        .replace('–', "-")
        .replace('—', "-")
        .replace('−', "-")
        .replace('_', "-")
        .replace(' ', "-");

    let parts: Vec<_> = normalized
        .split('-')
        .filter(|part| !part.is_empty())
        .collect();

    if parts.len() != 2 {
        return Err(HudParseError::InvalidStage);
    }

    let stage: u8 = parts[0]
        .parse()
        .map_err(|_| HudParseError::InvalidStage)?;
    let round: u8 = parts[1]
        .parse()
        .map_err(|_| HudParseError::InvalidStage)?;

    // Keep the parser conservative. TFT stage/round conventions can evolve,
    // but impossible OCR garbage should never enter GameState.
    if !(1..=20).contains(&stage) || !(1..=20).contains(&round) {
        return Err(HudParseError::InvalidStage);
    }

    Ok(format!("{stage}-{round}"))
}

pub fn parse_u16_bounded(raw: &str, min: u16, max: u16) -> Result<u16, HudParseError> {
    let cleaned = normalize_digits(raw)?;
    let value: u16 = cleaned
        .parse()
        .map_err(|_| HudParseError::InvalidNumber)?;

    if !(min..=max).contains(&value) {
        return Err(HudParseError::OutOfRange);
    }

    Ok(value)
}

pub fn parse_u8_bounded(raw: &str, min: u8, max: u8) -> Result<u8, HudParseError> {
    let cleaned = normalize_digits(raw)?;
    let value: u8 = cleaned
        .parse()
        .map_err(|_| HudParseError::InvalidNumber)?;

    if !(min..=max).contains(&value) {
        return Err(HudParseError::OutOfRange);
    }

    Ok(value)
}

fn normalize_digits(raw: &str) -> Result<String, HudParseError> {
    let cleaned = normalize_text(raw)?;
    let compact: String = cleaned
        .chars()
        .filter(|ch| !ch.is_whitespace())
        .collect();

    if compact.is_empty() {
        return Err(HudParseError::Empty);
    }

    if !compact.chars().all(|ch| ch.is_ascii_digit()) {
        return Err(HudParseError::InvalidCharacters);
    }

    Ok(compact)
}

fn normalize_text(raw: &str) -> Result<String, HudParseError> {
    let cleaned = raw.trim().to_string();
    if cleaned.is_empty() {
        return Err(HudParseError::Empty);
    }
    Ok(cleaned)
}

fn observed<T>(value: T, confidence: Confidence, observed_at_ms: u64) -> Observed<T> {
    Observed {
        value,
        confidence,
        source: ObservationSource::Vision,
        observed_at_ms,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate(field: HudField, text: &str, confidence: f32) -> OcrCandidate {
        OcrCandidate {
            field,
            text: text.into(),
            confidence: Confidence::new(confidence).unwrap(),
            observed_at_ms: 123,
        }
    }

    #[test]
    fn parses_gold() {
        let batch = parse_candidate(candidate(HudField::Gold, " 50 ", 0.93)).unwrap();
        let gold = batch.gold.unwrap();
        assert_eq!(gold.value, 50);
        assert_eq!(gold.confidence.value(), 0.93);
        assert_eq!(gold.source, ObservationSource::Vision);
    }

    #[test]
    fn rejects_hp_above_100() {
        assert_eq!(
            parse_candidate(candidate(HudField::Hp, "101", 0.99)).unwrap_err(),
            HudParseError::OutOfRange
        );
    }

    #[test]
    fn rejects_non_digit_numeric_field() {
        assert_eq!(
            parse_candidate(candidate(HudField::Gold, "5O", 0.99)).unwrap_err(),
            HudParseError::InvalidCharacters
        );
    }

    #[test]
    fn normalizes_stage_separators() {
        assert_eq!(parse_stage("4 — 2").unwrap(), "4-2");
        assert_eq!(parse_stage("4_2").unwrap(), "4-2");
        assert_eq!(parse_stage("4 2").unwrap(), "4-2");
    }

    #[test]
    fn rejects_invalid_stage() {
        assert_eq!(parse_stage("abc").unwrap_err(), HudParseError::InvalidStage);
        assert_eq!(parse_stage("0-2").unwrap_err(), HudParseError::InvalidStage);
    }


    struct FakeRecognizer {
        text: Option<String>,
        confidence: f32,
        seen_width: Option<u32>,
        seen_height: Option<u32>,
    }

    impl HudOcrEngine for FakeRecognizer {
        fn recognize(
            &mut self,
            _field: HudField,
            image: &GrayImage,
        ) -> Result<Option<RecognizedText>, String> {
            self.seen_width = Some(image.width);
            self.seen_height = Some(image.height);

            Ok(self.text.clone().map(|text| RecognizedText {
                text,
                confidence: Confidence::new(self.confidence).unwrap(),
            }))
        }
    }

    fn roi_fixture() -> RoiFrame {
        use agente_tft_capture_core::{PixelFormat, PixelRect};

        RoiFrame {
            source_frame_id: 1,
            captured_at_ms: 777,
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

    #[test]
    fn roi_flows_through_preprocess_and_recognizer() {
        let mut engine = FakeRecognizer {
            text: Some("50".into()),
            confidence: 0.94,
            seen_width: None,
            seen_height: None,
        };

        let batch = read_roi_with_ocr(
            &mut engine,
            HudField::Gold,
            &roi_fixture(),
            HudPreprocessConfig {
                upscale_factor: 3,
                invert: false,
            },
        )
        .unwrap()
        .unwrap();

        assert_eq!(engine.seen_width, Some(6));
        assert_eq!(engine.seen_height, Some(3));
        assert_eq!(batch.gold.unwrap().value, 50);
        assert_eq!(batch.observed_at_ms, 777);
    }

    #[test]
    fn recognizer_none_produces_no_observation() {
        let mut engine = FakeRecognizer {
            text: None,
            confidence: 0.0,
            seen_width: None,
            seen_height: None,
        };

        let result = read_roi_with_ocr(
            &mut engine,
            HudField::Gold,
            &roi_fixture(),
            HudPreprocessConfig::default(),
        )
        .unwrap();

        assert!(result.is_none());
    }

    #[test]
    fn recognizer_text_still_passes_domain_validation() {
        let mut engine = FakeRecognizer {
            text: Some("999".into()),
            confidence: 0.99,
            seen_width: None,
            seen_height: None,
        };

        let error = read_roi_with_ocr(
            &mut engine,
            HudField::Hp,
            &roi_fixture(),
            HudPreprocessConfig::default(),
        )
        .unwrap_err();

        assert_eq!(error, HudReadError::Parse(HudParseError::OutOfRange));
    }

    #[test]
    fn merge_keeps_latest_present_field_values() {
        let gold = parse_candidate(candidate(HudField::Gold, "50", 0.9)).unwrap();
        let hp = parse_candidate(candidate(HudField::Hp, "73", 0.95)).unwrap();

        let merged = merge_batches([gold, hp]);
        assert_eq!(merged.gold.unwrap().value, 50);
        assert_eq!(merged.hp.unwrap().value, 73);
    }
}
