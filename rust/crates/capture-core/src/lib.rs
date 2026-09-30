use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum PixelFormat {
    Rgba8,
    Bgra8,
    Rgb8,
}

impl PixelFormat {
    pub const fn bytes_per_pixel(self) -> usize {
        match self {
            Self::Rgba8 | Self::Bgra8 => 4,
            Self::Rgb8 => 3,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FrameEnvelope {
    pub frame_id: u64,
    pub captured_at_ms: u64,
    pub width: u32,
    pub height: u32,
    pub stride_bytes: u32,
    pub pixel_format: PixelFormat,
    pub source_id: String,
    #[serde(skip)]
    pub pixels: Vec<u8>,
}

impl FrameEnvelope {
    pub fn validate(&self) -> Result<(), CaptureError> {
        if self.width == 0 || self.height == 0 {
            return Err(CaptureError::InvalidDimensions);
        }

        let min_stride = self.width as usize * self.pixel_format.bytes_per_pixel();
        if self.stride_bytes as usize < min_stride {
            return Err(CaptureError::InvalidStride);
        }

        let expected_min = self.stride_bytes as usize * self.height as usize;
        if self.pixels.len() < expected_min {
            return Err(CaptureError::BufferTooSmall {
                actual: self.pixels.len(),
                expected_min,
            });
        }

        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CaptureCapabilities {
    pub source_id: String,
    pub source_kind: CaptureSourceKind,
    pub can_seek: bool,
    pub has_real_time_clock: bool,
    pub max_fps_hint: Option<u16>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CaptureSourceKind {
    Replay,
    StaticFrame,
    Desktop,
    WindowsTft,
}

#[derive(Debug, Error)]
pub enum CaptureError {
    #[error("capture source reached end of stream")]
    EndOfStream,
    #[error("capture source is temporarily unavailable")]
    TemporarilyUnavailable,
    #[error("invalid frame dimensions")]
    InvalidDimensions,
    #[error("frame stride is smaller than the packed pixel width")]
    InvalidStride,
    #[error("frame buffer too small: got {actual}, expected at least {expected_min}")]
    BufferTooSmall { actual: usize, expected_min: usize },
    #[error("capture backend error: {0}")]
    Backend(String),
}

pub trait CaptureSource: Send {
    fn capabilities(&self) -> CaptureCapabilities;
    fn next_frame(&mut self) -> Result<FrameEnvelope, CaptureError>;
}

pub struct StaticFrameSource {
    source_id: String,
    frame: FrameEnvelope,
    emitted: bool,
}

impl StaticFrameSource {
    pub fn new(source_id: impl Into<String>, mut frame: FrameEnvelope) -> Result<Self, CaptureError> {
        let source_id = source_id.into();
        frame.source_id = source_id.clone();
        frame.validate()?;
        Ok(Self {
            source_id,
            frame,
            emitted: false,
        })
    }
}

impl CaptureSource for StaticFrameSource {
    fn capabilities(&self) -> CaptureCapabilities {
        CaptureCapabilities {
            source_id: self.source_id.clone(),
            source_kind: CaptureSourceKind::StaticFrame,
            can_seek: false,
            has_real_time_clock: false,
            max_fps_hint: None,
        }
    }

    fn next_frame(&mut self) -> Result<FrameEnvelope, CaptureError> {
        if self.emitted {
            return Err(CaptureError::EndOfStream);
        }
        self.emitted = true;
        Ok(self.frame.clone())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn frame() -> FrameEnvelope {
        FrameEnvelope {
            frame_id: 1,
            captured_at_ms: 100,
            width: 2,
            height: 2,
            stride_bytes: 8,
            pixel_format: PixelFormat::Rgba8,
            source_id: "test".into(),
            pixels: vec![0; 16],
        }
    }

    #[test]
    fn valid_frame_passes_validation() {
        assert!(frame().validate().is_ok());
    }

    #[test]
    fn too_small_buffer_is_rejected() {
        let mut f = frame();
        f.pixels.truncate(5);
        assert!(matches!(
            f.validate(),
            Err(CaptureError::BufferTooSmall { .. })
        ));
    }

    #[test]
    fn static_source_emits_one_frame_then_eof() {
        let mut source = StaticFrameSource::new("fixture", frame()).unwrap();
        assert_eq!(source.capabilities().source_kind, CaptureSourceKind::StaticFrame);
        assert!(source.next_frame().is_ok());
        assert!(matches!(source.next_frame(), Err(CaptureError::EndOfStream)));
    }
}
