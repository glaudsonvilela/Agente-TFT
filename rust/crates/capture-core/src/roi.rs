use serde::{Deserialize, Serialize};

use crate::{CaptureError, FrameEnvelope};

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct NormalizedRect {
    pub x: f32,
    pub y: f32,
    pub width: f32,
    pub height: f32,
}

impl NormalizedRect {
    pub fn new(x: f32, y: f32, width: f32, height: f32) -> Result<Self, CaptureError> {
        let rect = Self { x, y, width, height };
        rect.validate()?;
        Ok(rect)
    }

    pub fn validate(&self) -> Result<(), CaptureError> {
        let values = [self.x, self.y, self.width, self.height];
        if values.iter().any(|v| !v.is_finite()) {
            return Err(CaptureError::Backend("ROI contains non-finite values".into()));
        }
        if self.x < 0.0
            || self.y < 0.0
            || self.width <= 0.0
            || self.height <= 0.0
            || self.x + self.width > 1.0
            || self.y + self.height > 1.0
        {
            return Err(CaptureError::Backend(
                "ROI must be fully inside normalized [0,1] coordinates".into(),
            ));
        }
        Ok(())
    }

    pub fn to_pixel_rect(&self, frame_width: u32, frame_height: u32) -> PixelRect {
        let x = (self.x * frame_width as f32).floor() as u32;
        let y = (self.y * frame_height as f32).floor() as u32;

        let right = ((self.x + self.width) * frame_width as f32).ceil() as u32;
        let bottom = ((self.y + self.height) * frame_height as f32).ceil() as u32;

        PixelRect {
            x: x.min(frame_width.saturating_sub(1)),
            y: y.min(frame_height.saturating_sub(1)),
            width: right.min(frame_width).saturating_sub(x),
            height: bottom.min(frame_height).saturating_sub(y),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct PixelRect {
    pub x: u32,
    pub y: u32,
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RoiFrame {
    pub source_frame_id: u64,
    pub captured_at_ms: u64,
    pub rect: PixelRect,
    pub stride_bytes: u32,
    pub pixel_format: crate::PixelFormat,
    pub bytes_per_pixel: usize,
    pub pixels: Vec<u8>,
}

pub fn extract_roi(frame: &FrameEnvelope, roi: NormalizedRect) -> Result<RoiFrame, CaptureError> {
    frame.validate()?;
    roi.validate()?;

    let rect = roi.to_pixel_rect(frame.width, frame.height);
    if rect.width == 0 || rect.height == 0 {
        return Err(CaptureError::InvalidDimensions);
    }

    let bpp = frame.pixel_format.bytes_per_pixel();
    let row_bytes = rect.width as usize * bpp;
    let mut pixels = Vec::with_capacity(row_bytes * rect.height as usize);

    for row in 0..rect.height as usize {
        let src_y = rect.y as usize + row;
        let src_start =
            src_y * frame.stride_bytes as usize + rect.x as usize * bpp;
        let src_end = src_start + row_bytes;
        pixels.extend_from_slice(&frame.pixels[src_start..src_end]);
    }

    Ok(RoiFrame {
        source_frame_id: frame.frame_id,
        captured_at_ms: frame.captured_at_ms,
        rect,
        stride_bytes: row_bytes as u32,
        pixel_format: frame.pixel_format,
        bytes_per_pixel: bpp,
        pixels,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{FrameEnvelope, PixelFormat};

    fn frame() -> FrameEnvelope {
        // 4x2 RGBA, each pixel has a distinct first byte.
        let mut pixels = Vec::new();
        for v in 0u8..8 {
            pixels.extend_from_slice(&[v, 0, 0, 255]);
        }
        FrameEnvelope {
            frame_id: 7,
            captured_at_ms: 99,
            width: 4,
            height: 2,
            stride_bytes: 16,
            pixel_format: PixelFormat::Rgba8,
            source_id: "fixture".into(),
            pixels,
        }
    }

    #[test]
    fn normalized_roi_maps_to_pixels() {
        let roi = NormalizedRect::new(0.25, 0.0, 0.5, 1.0).unwrap();
        assert_eq!(
            roi.to_pixel_rect(4, 2),
            PixelRect {
                x: 1,
                y: 0,
                width: 2,
                height: 2
            }
        );
    }

    #[test]
    fn roi_extracts_expected_pixels() {
        let roi = NormalizedRect::new(0.25, 0.0, 0.5, 1.0).unwrap();
        let out = extract_roi(&frame(), roi).unwrap();
        let first_channels: Vec<u8> = out.pixels.chunks_exact(4).map(|p| p[0]).collect();
        assert_eq!(first_channels, vec![1, 2, 5, 6]);
    }

    #[test]
    fn invalid_roi_is_rejected() {
        assert!(NormalizedRect::new(0.9, 0.0, 0.2, 1.0).is_err());
    }
}
