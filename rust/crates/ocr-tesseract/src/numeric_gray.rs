//! Opt-in preprocessing for the measured white numeric HUD, not a new default.
use agente_tft_capture_core::RoiFrame;
use agente_tft_image_preprocess::{stretch_contrast, GrayImage};
use agente_tft_perception_hud::{HudField, HudPreprocessConfig, HudReadError};

const BORDER: u32 = 10;
const MAX_INPUT_PIXELS: usize = 1_048_576;
const MAX_OUTPUT_PIXELS: usize = 16_777_216;

fn error(message: &str) -> HudReadError {
    HudReadError::Preprocess(message.into())
}

pub(super) fn prepare(
    field: HudField,
    roi: &RoiFrame,
    config: HudPreprocessConfig,
) -> Result<GrayImage, HudReadError> {
    let width = roi.rect.width;
    let height = roi.rect.height;
    let bpp = roi.pixel_format.bytes_per_pixel();
    let row_bytes = (width as usize).checked_mul(bpp).ok_or_else(|| error("row overflow"))?;
    let input_pixels = (width as usize).checked_mul(height as usize).ok_or_else(|| error("input overflow"))?;
    let required = (roi.stride_bytes as usize).checked_mul(height as usize).ok_or_else(|| error("buffer overflow"))?;
    if width == 0 || height == 0 || input_pixels > MAX_INPUT_PIXELS
        || roi.bytes_per_pixel != bpp || (roi.stride_bytes as usize) < row_bytes
        || roi.pixels.len() < required || !(1..=8).contains(&config.upscale_factor)
    {
        return Err(error("invalid or excessive numeric ROI"));
    }
    let mut gray = GrayImage { width, height, stride_bytes: width, pixels: Vec::with_capacity(input_pixels) };
    for row in 0..height as usize {
        for col in 0..width as usize {
            let at = row * roi.stride_bytes as usize + col * bpp;
            let p = &roi.pixels[at..at + bpp];
            // Gold text is neutral/white; the adjacent coin is chromatic.
            // Continuous achromatic projection, with no position or label lookup.
            let value = if field == HudField::Gold {
                let lo = *p[..3].iter().min().unwrap() as i16;
                let hi = *p[..3].iter().max().unwrap() as i16;
                (2 * lo - hi).clamp(0, 255) as u8
            } else {
                let (r, g, b) = match roi.pixel_format {
                    agente_tft_capture_core::PixelFormat::Bgra8 => (p[2], p[1], p[0]),
                    _ => (p[0], p[1], p[2]),
                };
                ((77u16 * r as u16 + 150u16 * g as u16 + 29u16 * b as u16) >> 8) as u8
            };
            gray.pixels.push(value);
        }
    }
    let gray = stretch_contrast(&gray).map_err(|e| error(&e.to_string()))?;
    resize_and_pad(&gray, config.upscale_factor, config.invert)
}

fn cubic(distance: f64) -> f64 {
    let x = distance.abs();
    if x <= 1.0 {
        1.5 * x * x * x - 2.5 * x * x + 1.0
    } else if x < 2.0 {
        -0.5 * x * x * x + 2.5 * x * x - 4.0 * x + 2.0
    } else {
        0.0
    }
}

fn resize_and_pad(image: &GrayImage, factor: u8, invert: bool) -> Result<GrayImage, HudReadError> {
    image.validate().map_err(|e| error(&e.to_string()))?;
    if !(1..=8).contains(&factor) { return Err(error("scale must be 1..8")); }
    let w = image.width.checked_mul(factor as u32).ok_or_else(|| error("width overflow"))?;
    let h = image.height.checked_mul(factor as u32).ok_or_else(|| error("height overflow"))?;
    let width = w.checked_add(2 * BORDER).ok_or_else(|| error("border overflow"))?;
    let height = h.checked_add(2 * BORDER).ok_or_else(|| error("border overflow"))?;
    let size = (width as usize).checked_mul(height as usize).filter(|n| *n <= MAX_OUTPUT_PIXELS)
        .ok_or_else(|| error("numeric output exceeds pixel budget"))?;
    let background = if invert { 255 } else { 0 };
    let mut pixels = vec![background; size];
    // Catmull-Rom cubic, pixel-center mapping, clamped source boundaries.
    // Unlike the legacy path, do not binarize before interpolation.
    for y in 0..h {
        let sy = (y as f64 + 0.5) / factor as f64 - 0.5;
        let iy = sy.floor() as i64;
        for x in 0..w {
            let sx = (x as f64 + 0.5) / factor as f64 - 0.5;
            let ix = sx.floor() as i64;
            let mut value = 0.0;
            for dy in -1..=2 {
                let yy = (iy + dy).clamp(0, image.height as i64 - 1) as usize;
                let wy = cubic(sy - (iy + dy) as f64);
                for dx in -1..=2 {
                    let xx = (ix + dx).clamp(0, image.width as i64 - 1) as usize;
                    value += image.pixels[yy * image.stride_bytes as usize + xx] as f64
                        * wy * cubic(sx - (ix + dx) as f64);
                }
            }
            let value = value.round().clamp(0.0, 255.0) as u8;
            let at = (y + BORDER) as usize * width as usize + (x + BORDER) as usize;
            pixels[at] = if invert { 255 - value } else { value };
        }
    }
    Ok(GrayImage { width, height, stride_bytes: width, pixels })
}

#[cfg(test)]
mod tests {
    use super::*;
    use agente_tft_capture_core::{PixelFormat, PixelRect};
    fn roi() -> RoiFrame {
        RoiFrame { source_frame_id: 1, captured_at_ms: 10,
            rect: PixelRect { x: 0, y: 0, width: 3, height: 1 }, stride_bytes: 12,
            pixel_format: PixelFormat::Rgba8, bytes_per_pixel: 4,
            pixels: vec![0,0,0,255, 230,200,100,255, 240,240,240,255] }
    }
    fn config() -> HudPreprocessConfig { HudPreprocessConfig { upscale_factor: 1, invert: true } }
    #[test] fn gold_suppresses_chromatic_coin_but_keeps_neutral_digit() {
        let out = prepare(HudField::Gold, &roi(), config()).unwrap();
        let start = BORDER as usize * out.width as usize + BORDER as usize;
        assert_eq!(&out.pixels[start..start+3], &[255,255,0]);
    }
    #[test] fn xp_does_not_apply_gold_color_projection() {
        let out = prepare(HudField::Xp, &roi(), config()).unwrap();
        let at = BORDER as usize * out.width as usize + BORDER as usize + 1;
        assert!(out.pixels[at] > 0 && out.pixels[at] < 255);
    }
    #[test] fn grayscale_is_preserved_and_cubic_has_known_values() {
        let image = GrayImage { width: 2, height: 1, stride_bytes: 2, pixels: vec![0,255] };
        let out = resize_and_pad(&image, 2, false).unwrap();
        let start = BORDER as usize * out.width as usize + BORDER as usize;
        assert_eq!(&out.pixels[start..start+4], &[0,52,203,255]);
        assert_eq!((out.width,out.height), (24,22));
    }
    #[test] fn padding_and_polarity_are_explicit() {
        let a = prepare(HudField::Xp, &roi(), config()).unwrap();
        let b = prepare(HudField::Xp, &roi(), HudPreprocessConfig { invert:false, ..config() }).unwrap();
        assert_eq!((a.width,a.height), (23,21));
        assert!(a.pixels.iter().zip(&b.pixels).all(|(&x,&y)| x as u16 + y as u16 == 255));
        assert!(a.pixels[..a.width as usize].iter().all(|&x| x == 255));
    }
    #[test] fn rgb_bgra_and_stride_padding_agree() {
        let expected = prepare(HudField::Xp, &roi(), config()).unwrap();
        let mut bgra=roi(); for p in bgra.pixels.chunks_exact_mut(4) { p.swap(0,2); }
        bgra.pixel_format=PixelFormat::Bgra8;
        assert_eq!(prepare(HudField::Xp,&bgra,config()).unwrap(),expected);
        let mut rgb=roi(); rgb.pixels=vec![0,0,0,230,200,100,240,240,240,99,99,99];
        rgb.pixel_format=PixelFormat::Rgb8;rgb.bytes_per_pixel=3;
        assert_eq!(prepare(HudField::Xp,&rgb,config()).unwrap(),expected);
    }
    #[test] fn invalid_roi_and_scale_return_errors_without_panicking() {
        let mut r=roi();r.pixels.truncate(2);assert!(prepare(HudField::Xp,&r,config()).is_err());
        r=roi();r.stride_bytes=1;assert!(prepare(HudField::Xp,&r,config()).is_err());
        r=roi();r.bytes_per_pixel=1;assert!(prepare(HudField::Xp,&r,config()).is_err());
        for factor in [0,9,255] { assert!(prepare(HudField::Xp,&roi(),HudPreprocessConfig { upscale_factor:factor,..config() }).is_err()); }
    }
}
