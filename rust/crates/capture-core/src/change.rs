use crate::RoiFrame;

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ChangeConfig {
    /// Compare one byte every N bytes. Higher values reduce CPU usage.
    pub sample_step: usize,
    /// Normalized mean absolute difference in [0, 1].
    pub threshold: f32,
}

impl Default for ChangeConfig {
    fn default() -> Self {
        Self {
            sample_step: 16,
            threshold: 0.02,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ChangeResult {
    pub changed: bool,
    pub score: f32,
}

#[derive(Debug)]
pub struct RegionChangeDetector {
    config: ChangeConfig,
    previous: Vec<u8>,
}

impl RegionChangeDetector {
    pub fn new(config: ChangeConfig) -> Self {
        Self {
            config: ChangeConfig {
                sample_step: config.sample_step.max(1),
                threshold: config.threshold.clamp(0.0, 1.0),
            },
            previous: Vec::new(),
        }
    }

    pub fn observe(&mut self, roi: &RoiFrame) -> ChangeResult {
        if self.previous.len() != roi.pixels.len() {
            self.previous.clone_from(&roi.pixels);
            return ChangeResult {
                changed: true,
                score: 1.0,
            };
        }

        let mut diff_sum: u64 = 0;
        let mut samples: u64 = 0;

        for idx in (0..roi.pixels.len()).step_by(self.config.sample_step) {
            diff_sum += roi.pixels[idx].abs_diff(self.previous[idx]) as u64;
            samples += 1;
        }

        self.previous.clone_from(&roi.pixels);

        let score = if samples == 0 {
            0.0
        } else {
            (diff_sum as f32 / samples as f32) / 255.0
        };

        ChangeResult {
            changed: score >= self.config.threshold,
            score,
        }
    }

    pub fn reset(&mut self) {
        self.previous.clear();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::PixelRect;

    fn roi(value: u8) -> RoiFrame {
        RoiFrame {
            source_frame_id: 1,
            captured_at_ms: 0,
            rect: PixelRect {
                x: 0,
                y: 0,
                width: 2,
                height: 2,
            },
            stride_bytes: 8,
            bytes_per_pixel: 4,
            pixels: vec![value; 16],
        }
    }

    #[test]
    fn first_observation_is_always_changed() {
        let mut detector = RegionChangeDetector::new(ChangeConfig::default());
        assert!(detector.observe(&roi(10)).changed);
    }

    #[test]
    fn identical_region_is_not_changed() {
        let mut detector = RegionChangeDetector::new(ChangeConfig::default());
        detector.observe(&roi(10));
        let second = detector.observe(&roi(10));
        assert!(!second.changed);
        assert_eq!(second.score, 0.0);
    }

    #[test]
    fn large_difference_triggers_change() {
        let mut detector = RegionChangeDetector::new(ChangeConfig {
            sample_step: 1,
            threshold: 0.1,
        });
        detector.observe(&roi(0));
        assert!(detector.observe(&roi(255)).changed);
    }
}
