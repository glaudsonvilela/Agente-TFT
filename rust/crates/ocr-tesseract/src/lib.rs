use std::{
    io::Write,
    process::{Command, Stdio},
};

use agente_tft_contracts::Confidence;
use agente_tft_image_preprocess::GrayImage;
use agente_tft_perception_hud::{HudField, HudOcrEngine, RecognizedText};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TesseractConfig {
    pub binary: String,
    pub language: String,
}

impl Default for TesseractConfig {
    fn default() -> Self {
        Self {
            binary: "tesseract".into(),
            language: "eng".into(),
        }
    }
}

pub struct TesseractOcr {
    config: TesseractConfig,
}

impl TesseractOcr {
    pub fn new(config: TesseractConfig) -> Self {
        Self { config }
    }

    pub fn available(&self) -> bool {
        Command::new(&self.config.binary)
            .arg("--version")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|status| status.success())
            .unwrap_or(false)
    }
}

impl Default for TesseractOcr {
    fn default() -> Self {
        Self::new(TesseractConfig::default())
    }
}

fn whitelist_for(field: HudField) -> &'static str {
    match field {
        HudField::Stage => "tessedit_char_whitelist=0123456789-",
        // Keep the separator: 0/10 must not silently become 010.
        HudField::Xp => "tessedit_char_whitelist=0123456789/",
        HudField::Gold | HudField::Hp | HudField::Level => {
            "tessedit_char_whitelist=0123456789"
        }
    }
}

fn page_segmentation_for(field: HudField, override_psm: Option<u8>) -> Result<u8, String> {
    let psm = override_psm.unwrap_or(if field == HudField::Stage { 7 } else { 8 });
    if !matches!(psm, 6 | 7 | 8 | 10 | 13) { return Err("unsupported HUD PSM".into()); }
    Ok(psm)
}

impl HudOcrEngine for TesseractOcr {
    fn recognize(
        &mut self,
        field: HudField,
        image: &GrayImage,
    ) -> Result<Option<RecognizedText>, String> {
        self.recognize_with_psm(field, image, None)
    }

    fn recognize_with_psm(
        &mut self, field: HudField, image: &GrayImage, override_psm: Option<u8>,
    ) -> Result<Option<RecognizedText>, String> {
        let psm = page_segmentation_for(field, override_psm)?;
        image
            .validate()
            .map_err(|e| format!("invalid OCR image: {e}"))?;

        let pgm = encode_pgm(image)?;
        let whitelist = whitelist_for(field);

        let mut child = Command::new(&self.config.binary)
            .arg("stdin")
            .arg("stdout")
            .arg("--psm")
            .arg(psm.to_string())
            .arg("-l")
            .arg(&self.config.language)
            .arg("-c")
            .arg(whitelist)
            .arg("tsv")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("failed to start tesseract: {e}"))?;

        {
            let stdin = child
                .stdin
                .as_mut()
                .ok_or_else(|| "tesseract stdin was unavailable".to_string())?;
            stdin
                .write_all(&pgm)
                .map_err(|e| format!("failed writing image to tesseract: {e}"))?;
        }

        let output = child
            .wait_with_output()
            .map_err(|e| format!("failed waiting for tesseract: {e}"))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
            return Err(format!(
                "tesseract exited with {}: {}",
                output.status,
                stderr
            ));
        }

        let tsv = String::from_utf8(output.stdout)
            .map_err(|e| format!("tesseract TSV was not UTF-8: {e}"))?;

        parse_tsv(&tsv)
    }
}

fn encode_pgm(image: &GrayImage) -> Result<Vec<u8>, String> {
    image
        .validate()
        .map_err(|e| format!("invalid grayscale image: {e}"))?;

    let header = format!("P5\n{} {}\n255\n", image.width, image.height);
    let mut out = Vec::with_capacity(
        header.len() + image.width as usize * image.height as usize,
    );
    out.extend_from_slice(header.as_bytes());

    for row in 0..image.height as usize {
        let start = row * image.stride_bytes as usize;
        let end = start + image.width as usize;
        out.extend_from_slice(&image.pixels[start..end]);
    }

    Ok(out)
}

fn parse_tsv(tsv: &str) -> Result<Option<RecognizedText>, String> {
    let mut text = String::new();
    let mut weighted_confidence = 0.0_f32;
    let mut total_weight = 0usize;

    for (index, line) in tsv.lines().enumerate() {
        if index == 0 || line.trim().is_empty() {
            continue;
        }

        let columns: Vec<_> = line.splitn(12, '\t').collect();
        if columns.len() < 12 {
            continue;
        }

        let confidence: f32 = match columns[10].parse() {
            Ok(value) if value >= 0.0 => value,
            _ => continue,
        };

        let word = columns[11].trim();
        if word.is_empty() {
            continue;
        }

        if !text.is_empty() {
            text.push(' ');
        }
        text.push_str(word);

        let weight = word.chars().count().max(1);
        weighted_confidence += confidence * weight as f32;
        total_weight += weight;
    }

    if text.trim().is_empty() || total_weight == 0 {
        return Ok(None);
    }

    let confidence = (weighted_confidence / total_weight as f32 / 100.0).clamp(0.0, 1.0);
    let confidence = Confidence::new(confidence)
        .map_err(|e| format!("invalid tesseract confidence: {e}"))?;

    Ok(Some(RecognizedText {
        text: text.trim().to_string(),
        confidence,
    }))
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
        let image = GrayImage {
            width: 2,
            height: 2,
            stride_bytes: 4,
            pixels: vec![
                10, 20, 99, 99,
                30, 40, 99, 99,
            ],
        };

        let encoded = encode_pgm(&image).unwrap();
        assert!(encoded.starts_with(b"P5\n2 2\n255\n"));
        assert!(encoded.ends_with(&[10, 20, 30, 40]));
    }

    #[test]
    fn parses_tesseract_tsv_and_weighted_confidence() {
        let tsv = concat!(
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n",
            "1\t1\t0\t0\t0\t0\t0\t0\t10\t10\t-1\t\n",
            "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t90.0\t50\n"
        );

        let out = parse_tsv(tsv).unwrap().unwrap();
        assert_eq!(out.text, "50");
        assert!((out.confidence.value() - 0.90).abs() < 0.001);
    }

    #[test]
    fn ignores_negative_confidence_rows() {
        let tsv = concat!(
            "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n",
            "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t-1\tgarbage\n"
        );
        assert!(parse_tsv(tsv).unwrap().is_none());
    }

    #[test]
    fn default_binary_is_tesseract() {
        assert_eq!(TesseractConfig::default().binary, "tesseract");
    }
}

#[cfg(test)]
mod profile_tests {
    use super::*;
    #[test] fn legacy_psm_and_explicit_line_mode_are_distinct() {
        assert_eq!(page_segmentation_for(HudField::Stage,None).unwrap(),7);
        assert_eq!(page_segmentation_for(HudField::Xp,None).unwrap(),8);
        assert_eq!(page_segmentation_for(HudField::Xp,Some(7)).unwrap(),7);
        assert!(page_segmentation_for(HudField::Gold,Some(255)).is_err());
    }
    #[test] fn real_tesseract_blank_line_smoke() {
        let mut engine=TesseractOcr::default();
        if !engine.available() {
            assert!(std::env::var_os("HUD_REQUIRE_MEDIA_TOOLS").is_none(),"required Tesseract missing");
            eprintln!("SKIP: Tesseract not installed"); return;
        }
        let image=GrayImage { width:120,height:70,stride_bytes:120,pixels:vec![255;8400] };
        assert!(engine.recognize_with_psm(HudField::Xp,&image,Some(7)).unwrap().is_none());
    }
}
