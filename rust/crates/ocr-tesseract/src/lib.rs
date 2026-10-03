use std::{io::Write, process::{Command, Stdio}};

use agente_tft_capture_core::RoiFrame;
use agente_tft_contracts::Confidence;
use agente_tft_image_preprocess::{preprocess_for_numeric_ocr, GrayImage};
use agente_tft_perception_hud::{
    parse_xp_current, HudField, HudOcrEngine, HudPreprocessConfig, HudReadError, RecognizedText,
};
mod numeric_gray;
mod text_block;
#[cfg(windows)]
mod resident_windows;
pub use text_block::{TextBlockOcrEngine,TextWord};
#[cfg(windows)]
pub use resident_windows::ResidentTesseractOcr;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TesseractConfig {
    pub binary: String,
    pub language: String,
}

impl Default for TesseractConfig {
    fn default() -> Self {
        Self { binary: "tesseract".into(), language: "eng".into() }
    }
}

#[derive(Clone)]
pub struct TesseractOcr {
    config: TesseractConfig,
    numeric_gray: bool,
}

impl TesseractOcr {
    pub fn new(config: TesseractConfig) -> Self {
        Self { config, numeric_gray: false }
    }

    /// Diagnostic opt-in. Default/legacy backends and stage/HP stay unchanged.
    pub fn with_numeric_gray(mut self) -> Self {
        self.numeric_gray = true;
        self
    }

    fn uses_gray(&self, field: HudField) -> bool {
        self.numeric_gray && matches!(field, HudField::Gold | HudField::Level | HudField::Xp)
    }

    pub fn profile_for(&self, field: HudField) -> &'static str {
        if !self.uses_gray(field) { "legacy_binary" }
        else if field == HudField::Gold { "numeric_gray_gold_v3" }
        else { "numeric_gray_line_v3" }
    }

    fn psm_for(&self, field: HudField) -> &'static str {
        if field == HudField::Stage || self.uses_gray(field) { "7" } else { "8" }
    }

    fn accept_text(&self, field: HudField, text: &str) -> bool {
        !self.uses_gray(field) || field != HudField::Xp
            || (text.contains('/') && parse_xp_current(text).is_ok())
    }

    pub fn available(&self) -> bool {
        Command::new(&self.config.binary).arg("--version")
            .stdout(Stdio::null()).stderr(Stdio::null()).status()
            .map(|status| status.success()).unwrap_or(false)
    }

    /// Shared process adapter for numeric HUD and spatial text blocks.
    /// Supervising the caller's process group remains the runner's responsibility.
    fn run_tsv(&self, image: &GrayImage, psm: &str, whitelist: Option<&str>) -> Result<String, String> {
        let pgm = encode_pgm(image)?;
        let mut command = Command::new(&self.config.binary);
        command.args(["stdin", "stdout", "--psm", psm, "-l", &self.config.language]);
        if let Some(value) = whitelist {
            command.args(["-c", value]);
        }
        let mut child = command.arg("tsv").stdin(Stdio::piped())
            .stdout(Stdio::piped()).stderr(Stdio::piped()).spawn()
            .map_err(|e| format!("failed to start tesseract: {e}"))?;
        let write_result = child.stdin.take().ok_or_else(|| "tesseract stdin unavailable".to_string())
            .and_then(|mut input| input.write_all(&pgm).map_err(|e| format!("failed writing OCR image: {e}")));
        if let Err(error) = write_result {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
        let output = child.wait_with_output().map_err(|e| format!("failed waiting for tesseract: {e}"))?;
        if !output.status.success() {
            return Err(format!("tesseract exited with {}: {}", output.status,
                String::from_utf8_lossy(&output.stderr).trim()));
        }
        String::from_utf8(output.stdout).map_err(|e| format!("tesseract TSV was not UTF-8: {e}"))
    }
}

impl Default for TesseractOcr {
    fn default() -> Self { Self::new(TesseractConfig::default()) }
}

fn whitelist_for(field: HudField) -> &'static str {
    match field {
        HudField::Stage => "tessedit_char_whitelist=0123456789-",
        HudField::Xp => "tessedit_char_whitelist=0123456789/",
        HudField::Gold | HudField::Hp | HudField::Level => "tessedit_char_whitelist=0123456789",
    }
}

impl HudOcrEngine for TesseractOcr {
    fn prepare_roi(&self, field: HudField, roi: &RoiFrame, config: HudPreprocessConfig) -> Result<GrayImage, HudReadError> {
        if self.uses_gray(field) {
            numeric_gray::prepare(field, roi, config)
        } else {
            preprocess_for_numeric_ocr(roi, config.upscale_factor, config.invert)
                .map_err(|e| HudReadError::Preprocess(e.to_string()))
        }
    }

    fn recognize(&mut self, field: HudField, image: &GrayImage) -> Result<Option<RecognizedText>, String> {
        let tsv = self.run_tsv(image, self.psm_for(field), Some(whitelist_for(field)))?;
        Ok(parse_tsv(&tsv)?.filter(|r| self.accept_text(field, &r.text)))
    }
}

fn encode_pgm(image: &GrayImage) -> Result<Vec<u8>, String> {
    image.validate().map_err(|e| format!("invalid grayscale image: {e}"))?;
    let header = format!("P5\n{} {}\n255\n", image.width, image.height);
    let mut out = Vec::with_capacity(header.len() + image.width as usize * image.height as usize);
    out.extend_from_slice(header.as_bytes());
    for row in 0..image.height as usize {
        let start = row * image.stride_bytes as usize;
        out.extend_from_slice(&image.pixels[start..start + image.width as usize]);
    }
    Ok(out)
}

// Preserve the legacy numeric aggregation and filtering behavior.
fn parse_tsv(tsv: &str) -> Result<Option<RecognizedText>, String> {
    let mut text = String::new();
    let mut weighted_confidence = 0.0_f32;
    let mut total_weight = 0usize;
    for (index, line) in tsv.lines().enumerate() {
        if index == 0 || line.trim().is_empty() { continue; }
        let columns: Vec<_> = line.splitn(12, '\t').collect();
        if columns.len() < 12 { continue; }
        let confidence: f32 = match columns[10].parse() {
            Ok(value) if value >= 0.0 => value,
            _ => continue,
        };
        let word = columns[11].trim();
        if word.is_empty() { continue; }
        if !text.is_empty() { text.push(' '); }
        text.push_str(word);
        let weight = word.chars().count().max(1);
        weighted_confidence += confidence * weight as f32;
        total_weight += weight;
    }
    if text.trim().is_empty() || total_weight == 0 { return Ok(None); }
    let confidence = (weighted_confidence / total_weight as f32 / 100.0).clamp(0.0, 1.0);
    let confidence = Confidence::new(confidence).map_err(|e| format!("invalid tesseract confidence: {e}"))?;
    Ok(Some(RecognizedText { text: text.trim().to_string(), confidence }))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn xp_whitelist_preserves_fraction_and_other_fields_stay_strict() {
        assert!(whitelist_for(HudField::Xp).ends_with("0123456789/"));
        assert!(whitelist_for(HudField::Stage).ends_with("0123456789-"));
        for field in [HudField::Gold, HudField::Hp, HudField::Level] {
            assert!(whitelist_for(field).ends_with("0123456789"));
            assert!(!whitelist_for(field).contains('/'));
        }
    }
    #[test]
    fn pgm_encoder_strips_gray_stride_padding() {
        let image = GrayImage { width:2, height:2, stride_bytes:4, pixels:vec![10,20,99,99,30,40,99,99] };
        let encoded = encode_pgm(&image).unwrap();
        assert!(encoded.starts_with(b"P5\n2 2\n255\n"));
        assert!(encoded.ends_with(&[10,20,30,40]));
    }
    #[test]
    fn parses_tesseract_tsv_and_weighted_confidence() {
        let tsv = concat!("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n",
            "1\t1\t0\t0\t0\t0\t0\t0\t10\t10\t-1\t\n", "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t90.0\t50\n");
        let out = parse_tsv(tsv).unwrap().unwrap();
        assert_eq!(out.text,"50");
        assert!((out.confidence.value()-0.90).abs()<0.001);
    }
    #[test]
    fn ignores_negative_confidence_rows() {
        let tsv = concat!("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n",
            "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t-1\tgarbage\n");
        assert!(parse_tsv(tsv).unwrap().is_none());
    }
    #[test]
    fn default_binary_is_tesseract() { assert_eq!(TesseractConfig::default().binary,"tesseract"); }
    #[test]
    fn gray_profile_is_opt_in_and_stage_hp_stay_legacy() {
        let old=TesseractOcr::default(); let new=TesseractOcr::default().with_numeric_gray();
        for field in [HudField::Gold,HudField::Level,HudField::Xp] {
            assert_eq!(old.psm_for(field),"8"); assert_eq!(old.profile_for(field),"legacy_binary");
            assert_eq!(new.psm_for(field),"7"); assert!(new.uses_gray(field));
        }
        for field in [HudField::Stage,HudField::Hp] {
            assert_eq!(new.psm_for(field),old.psm_for(field)); assert!(!new.uses_gray(field));
        }
    }
    #[test]
    fn full_fraction_profile_rejects_missing_or_invalid_slash() {
        let new=TesseractOcr::default().with_numeric_gray();
        for text in ["010","10","0/0","0/10/20","20/10"] { assert!(!new.accept_text(HudField::Xp,text)); }
        for text in ["0/10","20/68"," 6 / 10 "] { assert!(new.accept_text(HudField::Xp,text)); }
        assert!(TesseractOcr::default().accept_text(HudField::Xp,"10"));
    }
    #[test]
    fn real_tesseract_blank_smoke_when_available() {
        let mut engine=TesseractOcr::default().with_numeric_gray();
        if !engine.available() {
            assert!(std::env::var_os("TFT_REQUIRE_OCR_SMOKE").is_none(),"required tesseract missing");
            return;
        }
        let blank=GrayImage { width:80,height:40,stride_bytes:80,pixels:vec![255;3200] };
        assert!(engine.recognize(HudField::Xp,&blank).unwrap().is_none());
    }
}
