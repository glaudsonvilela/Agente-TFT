use std::collections::{HashMap, HashSet};

use serde::{Deserialize, Serialize};

use crate::{
    extract_roi, CaptureError, ChangeConfig, FrameEnvelope, NormalizedRect, RegionChangeDetector,
};

#[derive(
    Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize,
)]
#[serde(rename_all = "snake_case")]
pub enum RoiKey {
    Stage,
    Gold,
    Hp,
    LevelXp,
    Shop,
    Bench,
    Board,
    Items,
    Augments,
    PlayerList,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RoiDefinition {
    pub key: RoiKey,
    pub rect: NormalizedRect,
    pub change_threshold: f32,
    pub sample_step: usize,
}

impl RoiDefinition {
    pub fn validate(&self) -> Result<(), CaptureError> {
        self.rect.validate()?;
        if !self.change_threshold.is_finite()
            || !(0.0..=1.0).contains(&self.change_threshold)
        {
            return Err(CaptureError::Backend(format!(
                "invalid change threshold for {:?}",
                self.key
            )));
        }
        if self.sample_step == 0 {
            return Err(CaptureError::Backend(format!(
                "sample_step must be > 0 for {:?}",
                self.key
            )));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RoiProfile {
    pub profile_version: u32,
    pub name: String,
    pub reference_width: u32,
    pub reference_height: u32,
    pub rois: Vec<RoiDefinition>,
}

impl RoiProfile {
    pub fn validate(&self) -> Result<(), CaptureError> {
        if self.profile_version == 0 {
            return Err(CaptureError::Backend(
                "ROI profile_version must be > 0".into(),
            ));
        }
        if self.name.trim().is_empty() {
            return Err(CaptureError::Backend(
                "ROI profile name cannot be empty".into(),
            ));
        }
        if self.reference_width == 0 || self.reference_height == 0 {
            return Err(CaptureError::InvalidDimensions);
        }

        let mut seen = HashSet::new();
        for roi in &self.rois {
            roi.validate()?;
            if !seen.insert(roi.key) {
                return Err(CaptureError::Backend(format!(
                    "duplicate ROI key: {:?}",
                    roi.key
                )));
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RoiChange {
    pub key: RoiKey,
    pub score: f32,
}

pub struct RoiChangeRouter {
    profile: RoiProfile,
    detectors: HashMap<RoiKey, RegionChangeDetector>,
}

impl RoiChangeRouter {
    pub fn new(profile: RoiProfile) -> Result<Self, CaptureError> {
        profile.validate()?;

        let detectors = profile
            .rois
            .iter()
            .map(|roi| {
                (
                    roi.key,
                    RegionChangeDetector::new(ChangeConfig {
                        sample_step: roi.sample_step,
                        threshold: roi.change_threshold,
                    }),
                )
            })
            .collect();

        Ok(Self { profile, detectors })
    }

    pub fn profile(&self) -> &RoiProfile {
        &self.profile
    }

    pub fn observe(
        &mut self,
        frame: &FrameEnvelope,
    ) -> Result<Vec<RoiChange>, CaptureError> {
        let mut changes = Vec::new();

        for definition in &self.profile.rois {
            let roi = extract_roi(frame, definition.rect)?;
            let detector = self
                .detectors
                .get_mut(&definition.key)
                .expect("detector exists for every validated ROI");
            let result = detector.observe(&roi);

            if result.changed {
                changes.push(RoiChange {
                    key: definition.key,
                    score: result.score,
                });
            }
        }

        Ok(changes)
    }

    pub fn reset(&mut self) {
        for detector in self.detectors.values_mut() {
            detector.reset();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::PixelFormat;

    fn profile() -> RoiProfile {
        RoiProfile {
            profile_version: 1,
            name: "fixture".into(),
            reference_width: 4,
            reference_height: 2,
            rois: vec![
                RoiDefinition {
                    key: RoiKey::Gold,
                    rect: NormalizedRect::new(0.0, 0.0, 0.5, 1.0).unwrap(),
                    change_threshold: 0.1,
                    sample_step: 1,
                },
                RoiDefinition {
                    key: RoiKey::Shop,
                    rect: NormalizedRect::new(0.5, 0.0, 0.5, 1.0).unwrap(),
                    change_threshold: 0.1,
                    sample_step: 1,
                },
            ],
        }
    }

    fn frame(left: u8, right: u8, id: u64) -> FrameEnvelope {
        let mut pixels = Vec::new();
        for _row in 0..2 {
            for _ in 0..2 {
                pixels.extend_from_slice(&[left, left, left, 255]);
            }
            for _ in 0..2 {
                pixels.extend_from_slice(&[right, right, right, 255]);
            }
        }
        FrameEnvelope {
            frame_id: id,
            captured_at_ms: id * 100,
            width: 4,
            height: 2,
            stride_bytes: 16,
            pixel_format: PixelFormat::Rgba8,
            source_id: "fixture".into(),
            pixels,
        }
    }

    #[test]
    fn duplicate_roi_keys_are_rejected() {
        let mut p = profile();
        p.rois.push(p.rois[0].clone());
        assert!(p.validate().is_err());
    }

    #[test]
    fn router_reports_only_region_that_changed_after_baseline() {
        let mut router = RoiChangeRouter::new(profile()).unwrap();

        let first = router.observe(&frame(10, 20, 1)).unwrap();
        assert_eq!(first.len(), 2);

        let second = router.observe(&frame(10, 20, 2)).unwrap();
        assert!(second.is_empty());

        let third = router.observe(&frame(10, 250, 3)).unwrap();
        assert_eq!(third.len(), 1);
        assert_eq!(third[0].key, RoiKey::Shop);
    }
}
