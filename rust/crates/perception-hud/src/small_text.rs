//! Opt-in preprocessing for compact, light HUD glyphs. No labels or game rules.
use agente_tft_capture_core::{CaptureError, PixelFormat, RoiFrame};
use agente_tft_image_preprocess::{preprocess_for_numeric_ocr, stretch_contrast, to_luma, GrayImage};
use serde::{Deserialize, Serialize};
use crate::HudPreprocessConfig;

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HudImageMode {
    #[default]
    LegacyBinary,
    GrayBilinear,
    NeutralGrayBilinear,
}

pub fn prepare(roi: &RoiFrame, config: HudPreprocessConfig, mode: HudImageMode) -> Result<GrayImage, CaptureError> {
    if mode == HudImageMode::LegacyBinary {
        return preprocess_for_numeric_ocr(roi, config.upscale_factor, config.invert);
    }
    validate_roi(roi)?;
    let mut gray = to_luma(roi)?;
    if mode == HudImageMode::NeutralGrayBilinear {
        // White glyphs have low chroma; the gold icon is chromatic. Project the
        // pixels, not recognized characters. This never changes ROI geometry.
        for y in 0..roi.rect.height as usize {
            for x in 0..roi.rect.width as usize {
                let i = y * roi.stride_bytes as usize + x * roi.bytes_per_pixel;
                let p = &roi.pixels[i..i+3];
                let chroma = (*p.iter().max().unwrap() - *p.iter().min().unwrap()) as i16;
                let j = y * gray.stride_bytes as usize + x;
                gray.pixels[j] = (gray.pixels[j] as i16 - 2 * chroma).max(0) as u8;
            }
        }
    }
    let stretched = stretch_contrast(&gray)?;
    let mut scaled = upscale_bilinear(&stretched, config.upscale_factor)?;
    if config.invert {
        for p in &mut scaled.pixels { *p = 255 - *p; }
    }
    // Artificial background AFTER crop/upscale: no neighboring UI enters ROI.
    pad(&scaled, 10, if config.invert { 255 } else { 0 })
}

fn validate_roi(roi: &RoiFrame) -> Result<(), CaptureError> {
    let bpp = match roi.pixel_format { PixelFormat::Rgb8 => 3, _ => 4 };
    let size = (roi.stride_bytes as usize).checked_mul(roi.rect.height as usize);
    if roi.rect.width == 0 || roi.rect.height == 0 || roi.rect.width > 1024 || roi.rect.height > 1024
        || roi.bytes_per_pixel != bpp || roi.stride_bytes < roi.rect.width * bpp as u32
        || size.is_none() || size.unwrap() > roi.pixels.len() {
        return Err(CaptureError::Backend("invalid/bounded small-HUD ROI buffer".into()));
    }
    Ok(())
}

fn axis(out: u32, size: u32, factor: u8) -> (usize, usize, u32) {
    let d = 2 * factor as i64;
    let n = (2 * out as i64 + 1 - factor as i64).clamp(0, (size as i64 - 1) * d);
    let left = n / d;
    (left as usize, (left + 1).min(size as i64 - 1) as usize, (n % d) as u32)
}

pub fn upscale_bilinear(image: &GrayImage, factor: u8) -> Result<GrayImage, CaptureError> {
    image.validate()?;
    if !(1..=8).contains(&factor) { return Err(CaptureError::Backend("small-HUD scale must be 1..8".into())); }
    let width = image.width.checked_mul(factor as u32).ok_or(CaptureError::InvalidDimensions)?;
    let height = image.height.checked_mul(factor as u32).ok_or(CaptureError::InvalidDimensions)?;
    let count = (width as usize).checked_mul(height as usize).filter(|n| *n <= 16_777_216)
        .ok_or_else(|| CaptureError::Backend("small-HUD output exceeds 16 MiB".into()))?;
    let d = 2 * factor as u32;
    let mut pixels = vec![0; count];
    for y in 0..height {
        let (y0, y1, wy) = axis(y, image.height, factor);
        for x in 0..width {
            let (x0, x1, wx) = axis(x, image.width, factor);
            let row0 = y0 * image.stride_bytes as usize;
            let row1 = y1 * image.stride_bytes as usize;
            let top = image.pixels[row0+x0] as u32 * (d-wx) + image.pixels[row0+x1] as u32 * wx;
            let bottom = image.pixels[row1+x0] as u32 * (d-wx) + image.pixels[row1+x1] as u32 * wx;
            pixels[(y*width+x) as usize] = ((top*(d-wy) + bottom*wy + d*d/2)/(d*d)) as u8;
        }
    }
    Ok(GrayImage { width, height, stride_bytes: width, pixels })
}

fn pad(image: &GrayImage, border: u32, background: u8) -> Result<GrayImage, CaptureError> {
    image.validate()?;
    let width = image.width.checked_add(2*border).ok_or(CaptureError::InvalidDimensions)?;
    let height = image.height.checked_add(2*border).ok_or(CaptureError::InvalidDimensions)?;
    let mut pixels = vec![background; width as usize * height as usize];
    for y in 0..image.height as usize {
        let source = y * image.stride_bytes as usize;
        let dest = (y+border as usize) * width as usize + border as usize;
        pixels[dest..dest+image.width as usize].copy_from_slice(&image.pixels[source..source+image.width as usize]);
    }
    Ok(GrayImage { width, height, stride_bytes: width, pixels })
}

#[cfg(test)]
mod tests {
    use super::*;
    use agente_tft_capture_core::PixelRect;
    fn roi() -> RoiFrame {
        RoiFrame { source_frame_id:1, captured_at_ms:17,
            rect:PixelRect { x:5,y:6,width:2,height:1 }, stride_bytes:8,
            pixel_format:PixelFormat::Rgba8, bytes_per_pixel:4,
            pixels:vec![200,160,30,255,220,220,220,255] }
    }
    #[test] fn default_mode_preserves_legacy_pixels() {
        let c=HudPreprocessConfig::default();
        assert_eq!(prepare(&roi(),c,HudImageMode::default()).unwrap(),preprocess_for_numeric_ocr(&roi(),c.upscale_factor,c.invert).unwrap());
    }
    #[test] fn bilinear_preserves_intermediate_tones_and_edges() {
        let g=GrayImage { width:2,height:1,stride_bytes:3,pixels:vec![0,100,255] };
        let out=upscale_bilinear(&g,2).unwrap();
        assert_eq!(out.pixels,vec![0,25,75,100,0,25,75,100]);
    }
    #[test] fn bilinear_two_dimensional_rounding() {
        let g=GrayImage { width:2,height:2,stride_bytes:2,pixels:vec![0,100,200,255] };
        assert_eq!(upscale_bilinear(&g,2).unwrap().pixels,vec![0,25,75,100,50,72,117,139,150,167,200,216,200,214,241,255]);
    }
    #[test] fn one_pixel_input_is_safe_and_constant() {
        let g=GrayImage { width:1,height:1,stride_bytes:1,pixels:vec![77] };
        assert_eq!(upscale_bilinear(&g,5).unwrap().pixels,vec![77;25]);
    }
    #[test] fn invalid_scale_is_rejected() {
        let g=GrayImage { width:1,height:1,stride_bytes:1,pixels:vec![77] };
        assert!(upscale_bilinear(&g,0).is_err()); assert!(upscale_bilinear(&g,9).is_err());
    }
    #[test] fn colored_coin_is_suppressed_without_changing_roi() {
        let r=roi(); let before=r.clone();
        let out=prepare(&r,HudPreprocessConfig { upscale_factor:1,invert:true },HudImageMode::NeutralGrayBilinear).unwrap();
        assert_eq!(out.pixels[10*22+10],255); assert_eq!(out.pixels[10*22+11],0);
        assert_eq!((out.width,out.height),(22,21)); assert_eq!(r,before);
    }
    #[test] fn rgb_bgra_and_stride_padding_produce_same_result() {
        let r=roi(); let cfg=HudPreprocessConfig { upscale_factor:3,invert:true };
        let expected=prepare(&r,cfg,HudImageMode::NeutralGrayBilinear).unwrap();
        let mut bgra=r.clone();bgra.pixel_format=PixelFormat::Bgra8;
        for p in bgra.pixels.chunks_exact_mut(4) { p.swap(0,2); }
        assert_eq!(prepare(&bgra,cfg,HudImageMode::NeutralGrayBilinear).unwrap(),expected);
        let mut rgb=r;rgb.pixel_format=PixelFormat::Rgb8;rgb.bytes_per_pixel=3;rgb.stride_bytes=8;
        rgb.pixels=vec![200,160,30,220,220,220,99,99];
        assert_eq!(prepare(&rgb,cfg,HudImageMode::NeutralGrayBilinear).unwrap(),expected);
    }
    #[test] fn bad_roi_buffer_returns_error_not_panic() {
        let mut r=roi();r.pixels.truncate(1);
        assert!(prepare(&r,HudPreprocessConfig::default(),HudImageMode::GrayBilinear).is_err());
        r=roi();r.bytes_per_pixel=1;
        assert!(prepare(&r,HudPreprocessConfig::default(),HudImageMode::GrayBilinear).is_err());
    }
}
