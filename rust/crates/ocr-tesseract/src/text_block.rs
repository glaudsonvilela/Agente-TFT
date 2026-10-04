//! Spatial text uses the same process/backend as numeric HUD; no season vocabulary.
use agente_tft_image_preprocess::GrayImage;
use super::TesseractOcr;
#[cfg(any(windows,target_os="linux"))]
use super::ResidentTesseractOcr;

#[derive(Debug, Clone, PartialEq)]
pub struct TextWord {
    pub text: String,
    pub confidence: f32,
    pub x: u32,
    pub y: u32,
    pub width: u32,
    pub height: u32,
}

impl TesseractOcr {
    /// One TSV call for a block of rows. Callers retain boxes when assigning fields.
    pub fn recognize_text_block(&self, image: &GrayImage) -> Result<Vec<TextWord>, String> {
        if image.width as u64 * image.height as u64 > 4_000_000 {
            return Err("text atlas pixel budget exceeded".into());
        }
        parse_words(&self.run_tsv(image, "6", None)?, image.width, image.height)
    }
}

pub trait TextBlockOcrEngine {
    fn recognize_text_block(&mut self, image:&GrayImage)->Result<Vec<TextWord>,String>;
}

impl TextBlockOcrEngine for TesseractOcr {
    fn recognize_text_block(&mut self,image:&GrayImage)->Result<Vec<TextWord>,String>{
        TesseractOcr::recognize_text_block(self,image)
    }
}

#[cfg(any(windows,target_os="linux"))]
impl TextBlockOcrEngine for ResidentTesseractOcr {
    fn recognize_text_block(&mut self,image:&GrayImage)->Result<Vec<TextWord>,String>{
        if image.width as u64 * image.height as u64 > 4_000_000 {
            return Err("text atlas pixel budget exceeded".into());
        }
        parse_words(&self.run_tsv_custom(image,6,None)?,image.width,image.height)
    }
}

pub(crate) fn parse_words(tsv: &str, width: u32, height: u32) -> Result<Vec<TextWord>, String> {
    if tsv.len() > 2 * 1024 * 1024 { return Err("TSV byte budget exceeded".into()); }
    let mut words = Vec::new();
    for line in tsv.lines().skip(1).filter(|line| !line.is_empty()) {
        let c: Vec<_> = line.splitn(12, '\t').collect();
        if c.first() != Some(&"5") { continue; }
        if c.len() != 12 { return Err("malformed word row".into()); }
        let confidence: f32 = c[10].parse().map_err(|_| "invalid word confidence")?;
        if !confidence.is_finite() || !(0.0..=100.0).contains(&confidence) {
            return Err("invalid word confidence".into());
        }
        let parse = |i: usize| c[i].parse::<u32>().map_err(|_| "invalid word box".to_string());
        let (x,y,w,h) = (parse(6)?,parse(7)?,parse(8)?,parse(9)?);
        if w==0 || h==0 || x.checked_add(w).map_or(true,|r| r>width)
            || y.checked_add(h).map_or(true,|r| r>height) {
            return Err("word box outside atlas".into());
        }
        if c[11].trim().is_empty() { continue; }
        if words.len() >= 256 || c[11].len() > 256 { return Err("word budget exceeded".into()); }
        words.push(TextWord { text:c[11].trim().into(), confidence:confidence/100.0,
            x,y,width:w,height:h });
    }
    Ok(words)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn tsv(conf: &str, text: &str) -> String {
        format!("header\n5\t1\t1\t1\t1\t1\t10\t20\t40\t12\t{conf}\t{text}\n")
    }
    #[test]
    fn names_preserve_unicode_and_coordinates() {
        let w=parse_words(&tsv("90", "Rek'Sai"),100,80).unwrap();
        assert_eq!(w[0].text,"Rek'Sai"); assert_eq!(w[0].y,20); assert_eq!(w[0].confidence,0.9);
    }
    #[test]
    fn invalid_confidence_and_geometry_fail_closed() {
        for conf in ["nan","inf","-1","101"] { assert!(parse_words(&tsv(conf,"A"),100,80).is_err()); }
        assert!(parse_words(&tsv("90","A"),20,80).is_err());
    }
    #[test]
    fn hierarchy_rows_are_not_words() {
        assert!(parse_words("header\n1\tanything\n",100,80).unwrap().is_empty());
    }
}
