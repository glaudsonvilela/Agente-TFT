use agente_tft_capture_core::{CaptureError, PixelFormat, RoiFrame};

pub mod unit_features;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GrayImage {
    pub width: u32,
    pub height: u32,
    pub stride_bytes: u32,
    pub pixels: Vec<u8>,
}

impl GrayImage {
    pub fn validate(&self) -> Result<(), CaptureError> {
        if self.width == 0 || self.height == 0 {
            return Err(CaptureError::InvalidDimensions);
        }
        if self.stride_bytes < self.width {
            return Err(CaptureError::InvalidStride);
        }
        let expected = self.stride_bytes as usize * self.height as usize;
        if self.pixels.len() < expected {
            return Err(CaptureError::BufferTooSmall {
                actual: self.pixels.len(),
                expected_min: expected,
            });
        }
        Ok(())
    }
}

pub fn to_luma(roi: &RoiFrame) -> Result<GrayImage, CaptureError> {
    if roi.rect.width == 0 || roi.rect.height == 0 {
        return Err(CaptureError::InvalidDimensions);
    }

    let width = roi.rect.width;
    let height = roi.rect.height;
    let mut out = Vec::with_capacity(width as usize * height as usize);

    for row in 0..height as usize {
        let base = row * roi.stride_bytes as usize;
        for col in 0..width as usize {
            let idx = base + col * roi.bytes_per_pixel;
            let pixel = &roi.pixels[idx..idx + roi.bytes_per_pixel];

            let (r, g, b) = match roi.pixel_format {
                PixelFormat::Rgba8 | PixelFormat::Rgb8 => (pixel[0], pixel[1], pixel[2]),
                PixelFormat::Bgra8 => (pixel[2], pixel[1], pixel[0]),
            };

            // ITU-R BT.601 integer approximation.
            let y = ((77u16 * r as u16 + 150u16 * g as u16 + 29u16 * b as u16) >> 8) as u8;
            out.push(y);
        }
    }

    let image = GrayImage {
        width,
        height,
        stride_bytes: width,
        pixels: out,
    };
    image.validate()?;
    Ok(image)
}

pub fn stretch_contrast(image: &GrayImage) -> Result<GrayImage, CaptureError> {
    image.validate()?;

    let mut min_value = u8::MAX;
    let mut max_value = u8::MIN;

    for row in 0..image.height as usize {
        let start = row * image.stride_bytes as usize;
        let end = start + image.width as usize;
        for &value in &image.pixels[start..end] {
            min_value = min_value.min(value);
            max_value = max_value.max(value);
        }
    }

    if min_value == max_value {
        return Ok(image.clone());
    }

    let range = (max_value - min_value) as u16;
    let mut out = image.clone();

    for row in 0..image.height as usize {
        let start = row * image.stride_bytes as usize;
        let end = start + image.width as usize;
        for value in &mut out.pixels[start..end] {
            *value = (((value.saturating_sub(min_value)) as u16 * 255) / range) as u8;
        }
    }

    Ok(out)
}

pub fn mean_threshold(image: &GrayImage, invert: bool) -> Result<GrayImage, CaptureError> {
    image.validate()?;

    let mut sum: u64 = 0;
    let mut count: u64 = 0;

    for row in 0..image.height as usize {
        let start = row * image.stride_bytes as usize;
        let end = start + image.width as usize;
        for &value in &image.pixels[start..end] {
            sum += value as u64;
            count += 1;
        }
    }

    let threshold = if count == 0 { 0 } else { (sum / count) as u8 };
    let mut out = image.clone();

    for row in 0..image.height as usize {
        let start = row * image.stride_bytes as usize;
        let end = start + image.width as usize;
        for value in &mut out.pixels[start..end] {
            let foreground = *value >= threshold;
            *value = match (foreground, invert) {
                (true, false) | (false, true) => 255,
                _ => 0,
            };
        }
    }

    Ok(out)
}

pub fn upscale_nearest(image: &GrayImage, factor: u8) -> Result<GrayImage, CaptureError> {
    image.validate()?;
    if factor == 0 {
        return Err(CaptureError::Backend(
            "upscale factor must be greater than zero".into(),
        ));
    }
    if factor == 1 {
        return Ok(image.clone());
    }

    let width = image
        .width
        .checked_mul(factor as u32)
        .ok_or_else(|| CaptureError::Backend("upscaled width overflow".into()))?;
    let height = image
        .height
        .checked_mul(factor as u32)
        .ok_or_else(|| CaptureError::Backend("upscaled height overflow".into()))?;

    let mut pixels = vec![0u8; width as usize * height as usize];

    for out_y in 0..height as usize {
        let src_y = out_y / factor as usize;
        let src_row = src_y * image.stride_bytes as usize;
        let out_row = out_y * width as usize;

        for out_x in 0..width as usize {
            let src_x = out_x / factor as usize;
            pixels[out_row + out_x] = image.pixels[src_row + src_x];
        }
    }

    Ok(GrayImage {
        width,
        height,
        stride_bytes: width,
        pixels,
    })
}

pub fn preprocess_for_numeric_ocr(
    roi: &RoiFrame,
    upscale_factor: u8,
    invert: bool,
) -> Result<GrayImage, CaptureError> {
    let gray = to_luma(roi)?;
    let stretched = stretch_contrast(&gray)?;
    let thresholded = mean_threshold(&stretched, invert)?;
    upscale_nearest(&thresholded, upscale_factor)
}

#[cfg(test)]
mod tests {
    use agente_tft_capture_core::{PixelRect, RoiFrame};

    use super::*;

    fn rgba_roi(pixels: Vec<u8>, width: u32, height: u32) -> RoiFrame {
        RoiFrame {
            source_frame_id: 1,
            captured_at_ms: 10,
            rect: PixelRect {
                x: 0,
                y: 0,
                width,
                height,
            },
            stride_bytes: width * 4,
            pixel_format: PixelFormat::Rgba8,
            bytes_per_pixel: 4,
            pixels,
        }
    }

    #[test]
    fn converts_primary_colors_to_expected_luma_order() {
        let roi = rgba_roi(
            vec![
                255, 0, 0, 255, // red
                0, 255, 0, 255, // green
                0, 0, 255, 255, // blue
            ],
            3,
            1,
        );

        let gray = to_luma(&roi).unwrap();
        assert!(gray.pixels[1] > gray.pixels[0]);
        assert!(gray.pixels[0] > gray.pixels[2]);
    }

    #[test]
    fn contrast_stretch_maps_extremes_to_full_range() {
        let image = GrayImage {
            width: 3,
            height: 1,
            stride_bytes: 3,
            pixels: vec![50, 100, 150],
        };

        let stretched = stretch_contrast(&image).unwrap();
        assert_eq!(stretched.pixels, vec![0, 127, 255]);
    }

    #[test]
    fn threshold_produces_binary_pixels() {
        let image = GrayImage {
            width: 4,
            height: 1,
            stride_bytes: 4,
            pixels: vec![0, 10, 240, 255],
        };

        let thresholded = mean_threshold(&image, false).unwrap();
        assert_eq!(thresholded.pixels, vec![0, 0, 255, 255]);
    }

    #[test]
    fn upscale_nearest_replicates_pixels() {
        let image = GrayImage {
            width: 2,
            height: 1,
            stride_bytes: 2,
            pixels: vec![10, 20],
        };

        let upscaled = upscale_nearest(&image, 2).unwrap();
        assert_eq!(upscaled.width, 4);
        assert_eq!(upscaled.height, 2);
        assert_eq!(
            upscaled.pixels,
            vec![10, 10, 20, 20, 10, 10, 20, 20]
        );
    }

    #[test]
    fn numeric_pipeline_returns_requested_scale() {
        let roi = rgba_roi(
            vec![
                0, 0, 0, 255,
                255, 255, 255, 255,
            ],
            2,
            1,
        );

        let processed = preprocess_for_numeric_ocr(&roi, 3, false).unwrap();
        assert_eq!(processed.width, 6);
        assert_eq!(processed.height, 3);
        assert!(processed.pixels.iter().all(|v| *v == 0 || *v == 255));
    }
}
