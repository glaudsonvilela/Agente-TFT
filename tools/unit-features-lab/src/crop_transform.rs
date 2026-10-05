//! Versioned image preparation shared by training and native inference tools.
use crate::Result;
use agente_tft_capture_core::{FrameEnvelope, PixelFormat, PixelRect};
use agente_tft_image_preprocess::unit_features::{UnitCrop, HEIGHT, WIDTH};
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub enum CropTransform {
    #[default]
    #[serde(rename = "raw")]
    Raw,
    #[serde(rename = "center_88x120_v1")]
    Center88x120V1,
    #[serde(rename = "upper_88x80_v1")]
    Upper88x80V1,
    #[serde(rename = "top_88x104_v1")]
    Top88x104V1,
}

impl CropTransform {
    pub fn name(self) -> &'static str {
        match self {
            Self::Raw => "raw",
            Self::Center88x120V1 => "center_88x120_v1",
            Self::Upper88x80V1 => "upper_88x80_v1",
            Self::Top88x104V1 => "top_88x104_v1",
        }
    }

    pub fn apply(self, crop: &UnitCrop) -> Result<UnitCrop> {
        if crop.rgb.len() != WIDTH * HEIGHT * 3 {
            return Err("invalid native unit crop size".into());
        }
        if self == Self::Raw {
            return Ok(crop.clone());
        }
        let frame = FrameEnvelope {
            frame_id: 0,
            captured_at_ms: 0,
            width: WIDTH as u32,
            height: HEIGHT as u32,
            stride_bytes: WIDTH as u32 * 3,
            pixel_format: PixelFormat::Rgb8,
            source_id: self.name().into(),
            pixels: crop.rgb.clone(),
        };
        Ok(UnitCrop::from_frame(
            &frame,
            PixelRect {
                x: 20,
                y: if self == Self::Top88x104V1 { 0 } else { 24 },
                width: 88,
                height: match self {
                    Self::Upper88x80V1 => 80,
                    Self::Top88x104V1 => 104,
                    _ => 120,
                },
            },
        )?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn removes_top_item_strip_and_side_context_without_mutating_original() {
        let mut crop = UnitCrop {
            rgb: [255, 0, 0].repeat(WIDTH * HEIGHT),
        };
        for y in 24..HEIGHT {
            for x in 20..108 {
                crop.rgb[(y * WIDTH + x) * 3..(y * WIDTH + x) * 3 + 3]
                    .copy_from_slice(&[0, 200, 0]);
            }
        }
        let out = CropTransform::Center88x120V1.apply(&crop).unwrap();
        assert!(out.rgb.chunks_exact(3).all(|p| p == [0, 200, 0]));
        assert_eq!(&crop.rgb[..3], &[255, 0, 0]);
        assert_eq!(CropTransform::Raw.apply(&crop).unwrap().rgb, crop.rgb);
    }

    #[test]
    fn corrupt_crops_and_unknown_transform_versions_are_rejected() {
        let crop = UnitCrop { rgb: vec![0; 7] };
        assert!(CropTransform::Raw.apply(&crop).is_err());
        assert!(CropTransform::Center88x120V1.apply(&crop).is_err());
        assert!(CropTransform::Upper88x80V1.apply(&crop).is_err());
        assert!(CropTransform::Top88x104V1.apply(&crop).is_err());
        assert!(serde_json::from_str::<CropTransform>("\"center_v99\"").is_err());
    }

    #[test]
    fn upper_region_excludes_the_lower_body_without_reintroducing_item_strip() {
        let mut crop = UnitCrop {
            rgb: [255, 0, 0].repeat(WIDTH * HEIGHT),
        };
        for y in 24..104 {
            for x in 20..108 {
                crop.rgb[(y * WIDTH + x) * 3..(y * WIDTH + x) * 3 + 3]
                    .copy_from_slice(&[0, 200, 0]);
            }
        }
        let upper = CropTransform::Upper88x80V1.apply(&crop).unwrap();
        assert!(upper.rgb.chunks_exact(3).all(|p| p == [0, 200, 0]));
        let center = CropTransform::Center88x120V1.apply(&crop).unwrap();
        assert!(center.rgb.chunks_exact(3).any(|p| p == [255, 0, 0]));
    }

    #[test]
    fn top_region_preserves_high_heads_and_excludes_lower_context() {
        let mut crop = UnitCrop {
            rgb: [255, 0, 0].repeat(WIDTH * HEIGHT),
        };
        for y in 0..104 {
            for x in 20..108 {
                crop.rgb[(y * WIDTH + x) * 3..(y * WIDTH + x) * 3 + 3].copy_from_slice(if y < 24 {
                    &[0, 0, 255]
                } else {
                    &[0, 200, 0]
                });
            }
        }
        let top = CropTransform::Top88x104V1.apply(&crop).unwrap();
        assert_eq!(&top.rgb[..3], &[0, 0, 255]);
        assert!(!top.rgb.chunks_exact(3).any(|p| p == [255, 0, 0]));
        let upper = CropTransform::Upper88x80V1.apply(&crop).unwrap();
        assert!(upper.rgb.chunks_exact(3).all(|p| p == [0, 200, 0]));
    }
}
