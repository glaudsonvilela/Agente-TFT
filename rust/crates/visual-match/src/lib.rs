use agente_tft_image_preprocess::GrayImage;
use thiserror::Error;

#[derive(Debug, Error, PartialEq)]
pub enum VisualMatchError {
    #[error("descriptor dimensions must be greater than zero")]
    InvalidDescriptorDimensions,
    #[error("input image is invalid: {0}")]
    InvalidImage(String),
    #[error("image has no visual variance")]
    FlatImage,
    #[error("template id cannot be empty")]
    EmptyTemplateId,
    #[error("template descriptor size does not match index configuration")]
    DescriptorSizeMismatch,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DescriptorConfig {
    pub width: u16,
    pub height: u16,
}

impl Default for DescriptorConfig {
    fn default() -> Self {
        Self {
            width: 16,
            height: 16,
        }
    }
}

impl DescriptorConfig {
    pub fn len(self) -> Result<usize, VisualMatchError> {
        if self.width == 0 || self.height == 0 {
            return Err(VisualMatchError::InvalidDescriptorDimensions);
        }
        Ok(self.width as usize * self.height as usize)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct VisualDescriptor {
    values: Vec<f32>,
}

impl VisualDescriptor {
    pub fn from_gray(
        image: &GrayImage,
        config: DescriptorConfig,
    ) -> Result<Self, VisualMatchError> {
        image
            .validate()
            .map_err(|e| VisualMatchError::InvalidImage(e.to_string()))?;
        let len = config.len()?;
        let sampled = resize_to_grid(image, config);
        debug_assert_eq!(sampled.len(), len);

        let mean = sampled.iter().map(|&v| v as f32).sum::<f32>() / sampled.len() as f32;
        let mut values: Vec<f32> = sampled
            .into_iter()
            .map(|value| value as f32 - mean)
            .collect();

        let norm = values
            .iter()
            .map(|value| value * value)
            .sum::<f32>()
            .sqrt();

        if !norm.is_finite() || norm <= f32::EPSILON {
            return Err(VisualMatchError::FlatImage);
        }

        for value in &mut values {
            *value /= norm;
        }

        Ok(Self { values })
    }

    pub fn len(&self) -> usize {
        self.values.len()
    }

    pub fn is_empty(&self) -> bool {
        self.values.is_empty()
    }
}

#[derive(Debug, Clone, PartialEq)]
struct TemplateEntry {
    id: String,
    descriptor: VisualDescriptor,
}

#[derive(Debug, Clone, PartialEq)]
pub struct MatchCandidate {
    pub id: String,
    /// Cosine similarity in [-1, 1]. This is a raw score, not a calibrated confidence.
    pub similarity: f32,
}

#[derive(Debug, Clone, PartialEq)]
pub struct MatchResult {
    pub best: MatchCandidate,
    pub runner_up: Option<MatchCandidate>,
    /// Difference between top-1 and top-2 similarity. This is also an uncalibrated score.
    pub margin: f32,
}

#[derive(Debug, Clone)]
pub struct TemplateIndex {
    config: DescriptorConfig,
    entries: Vec<TemplateEntry>,
}

impl TemplateIndex {
    pub fn new(config: DescriptorConfig) -> Result<Self, VisualMatchError> {
        config.len()?;
        Ok(Self {
            config,
            entries: Vec::new(),
        })
    }

    pub fn config(&self) -> DescriptorConfig {
        self.config
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn insert_image(
        &mut self,
        id: impl Into<String>,
        image: &GrayImage,
    ) -> Result<(), VisualMatchError> {
        let descriptor = VisualDescriptor::from_gray(image, self.config)?;
        self.insert_descriptor(id, descriptor)
    }

    pub fn insert_descriptor(
        &mut self,
        id: impl Into<String>,
        descriptor: VisualDescriptor,
    ) -> Result<(), VisualMatchError> {
        let id = id.into();
        if id.trim().is_empty() {
            return Err(VisualMatchError::EmptyTemplateId);
        }
        if descriptor.len() != self.config.len()? {
            return Err(VisualMatchError::DescriptorSizeMismatch);
        }

        if let Some(existing) = self.entries.iter_mut().find(|entry| entry.id == id) {
            existing.descriptor = descriptor;
        } else {
            self.entries.push(TemplateEntry { id, descriptor });
        }
        Ok(())
    }

    pub fn classify(
        &self,
        image: &GrayImage,
    ) -> Result<Option<MatchResult>, VisualMatchError> {
        if self.entries.is_empty() {
            return Ok(None);
        }

        let descriptor = VisualDescriptor::from_gray(image, self.config)?;
        let mut ranked: Vec<MatchCandidate> = self
            .entries
            .iter()
            .map(|entry| MatchCandidate {
                id: entry.id.clone(),
                similarity: cosine(&descriptor, &entry.descriptor),
            })
            .collect();

        ranked.sort_by(|a, b| b.similarity.total_cmp(&a.similarity));
        let best = ranked.remove(0);
        let runner_up = ranked.into_iter().next();
        let margin = runner_up
            .as_ref()
            .map(|second| best.similarity - second.similarity)
            .unwrap_or(2.0);

        Ok(Some(MatchResult {
            best,
            runner_up,
            margin,
        }))
    }
}

fn resize_to_grid(image: &GrayImage, config: DescriptorConfig) -> Vec<u8> {
    let out_w = config.width as usize;
    let out_h = config.height as usize;
    let src_w = image.width as usize;
    let src_h = image.height as usize;
    let mut out = Vec::with_capacity(out_w * out_h);

    for oy in 0..out_h {
        let sy = ((oy as f32 + 0.5) * src_h as f32 / out_h as f32)
            .floor()
            .min((src_h - 1) as f32) as usize;
        let row = sy * image.stride_bytes as usize;

        for ox in 0..out_w {
            let sx = ((ox as f32 + 0.5) * src_w as f32 / out_w as f32)
                .floor()
                .min((src_w - 1) as f32) as usize;
            out.push(image.pixels[row + sx]);
        }
    }

    out
}

fn cosine(a: &VisualDescriptor, b: &VisualDescriptor) -> f32 {
    a.values
        .iter()
        .zip(&b.values)
        .map(|(x, y)| x * y)
        .sum::<f32>()
        .clamp(-1.0, 1.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn image(values: &[u8], width: u32, height: u32) -> GrayImage {
        GrayImage {
            width,
            height,
            stride_bytes: width,
            pixels: values.to_vec(),
        }
    }

    #[test]
    fn identical_template_scores_near_one() {
        let a = image(&[0, 10, 20, 30], 2, 2);
        let b = image(&[30, 20, 10, 0], 2, 2);

        let mut index = TemplateIndex::new(DescriptorConfig {
            width: 2,
            height: 2,
        })
        .unwrap();
        index.insert_image("a", &a).unwrap();
        index.insert_image("b", &b).unwrap();

        let result = index.classify(&a).unwrap().unwrap();
        assert_eq!(result.best.id, "a");
        assert!(result.best.similarity > 0.999);
        assert!(result.margin > 0.5);
    }

    #[test]
    fn brightness_offset_does_not_change_descriptor_direction() {
        let a = image(&[10, 20, 30, 40], 2, 2);
        let shifted = image(&[50, 60, 70, 80], 2, 2);

        let da = VisualDescriptor::from_gray(
            &a,
            DescriptorConfig {
                width: 2,
                height: 2,
            },
        )
        .unwrap();
        let db = VisualDescriptor::from_gray(
            &shifted,
            DescriptorConfig {
                width: 2,
                height: 2,
            },
        )
        .unwrap();

        assert!(cosine(&da, &db) > 0.999);
    }

    #[test]
    fn flat_image_is_rejected() {
        let flat = image(&[20, 20, 20, 20], 2, 2);
        assert_eq!(
            VisualDescriptor::from_gray(
                &flat,
                DescriptorConfig {
                    width: 2,
                    height: 2,
                }
            )
            .unwrap_err(),
            VisualMatchError::FlatImage
        );
    }

    #[test]
    fn insert_replaces_existing_template_id() {
        let a = image(&[0, 10, 20, 30], 2, 2);
        let b = image(&[30, 10, 20, 0], 2, 2);
        let mut index = TemplateIndex::new(DescriptorConfig {
            width: 2,
            height: 2,
        })
        .unwrap();

        index.insert_image("unit", &a).unwrap();
        index.insert_image("unit", &b).unwrap();

        assert_eq!(index.len(), 1);
        assert_eq!(index.classify(&b).unwrap().unwrap().best.id, "unit");
    }
}
