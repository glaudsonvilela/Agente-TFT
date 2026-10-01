//! Pixel projection is a UI profile, not a champion roster or game patch.
use agente_tft_capture_core::{FrameEnvelope, PixelRect, RoiFrame};
use agente_tft_image_preprocess::{to_luma, GrayImage};
use agente_tft_visual_match::{DescriptorConfig, TemplateIndex, VisualMatchError};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Anchor {
    pub rect: PixelRect,
    pub grid_width: u16,
    pub grid_height: u16,
    pub pixels: Vec<u8>,
    pub min_similarity: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SlotLayout {
    pub slot: u8,
    pub card: PixelRect,
    pub name: PixelRect,
    pub cost: PixelRect,
    pub empty_region: PixelRect,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScreenLayout {
    pub schema_version: u32,
    pub id: String,
    pub topology_id: String,
    pub reference_width: u32,
    pub reference_height: u32,
    pub locale: String,
    pub panel_anchors: Vec<Anchor>,
    pub slots: Vec<SlotLayout>,
    pub empty_template: Anchor,
    pub empty_max_mean: f32,
    pub min_text_confidence: f32,
}

pub fn contains(outer: PixelRect, inner: PixelRect) -> bool {
    inner.width > 0 && inner.height > 0 && inner.x >= outer.x && inner.y >= outer.y
        && inner.x.checked_add(inner.width).zip(outer.x.checked_add(outer.width)).is_some_and(|(a,b)| a<=b)
        && inner.y.checked_add(inner.height).zip(outer.y.checked_add(outer.height)).is_some_and(|(a,b)| a<=b)
}

impl ScreenLayout {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != 1 || self.topology_id != "standard-shop-five-v1"
            || self.id.trim().is_empty() || self.id.len()>100 || self.locale.trim().is_empty()
            || self.reference_width==0 || self.reference_height==0
            || self.reference_width>8192 || self.reference_height>8192 || self.slots.len()!=5
            || self.panel_anchors.len()!=2 || !self.min_text_confidence.is_finite()
            || !(0.70..=1.0).contains(&self.min_text_confidence)
            || !self.empty_max_mean.is_finite() || !(0.0..=80.0).contains(&self.empty_max_mean) {
            return Err("invalid shop UI profile or budgets".into());
        }
        let screen=PixelRect {x:0,y:0,width:self.reference_width,height:self.reference_height};
        for a in self.panel_anchors.iter().chain(std::iter::once(&self.empty_template)) {
            if !contains(screen,a.rect) || a.grid_width==0 || a.grid_height==0
                || a.grid_width>64 || a.grid_height>64
                || a.pixels.len()!=a.grid_width as usize*a.grid_height as usize
                || !a.min_similarity.is_finite() || !(0.70..=1.0).contains(&a.min_similarity) {
                return Err("invalid structural anchor".into());
            }
            a.index()?;
        }
        for (i,s) in self.slots.iter().enumerate() {
            if s.slot as usize!=i || !contains(screen,s.card)
                || ![s.name,s.cost,s.empty_region].into_iter().all(|r| contains(s.card,r))
                || s.name.width>256 || s.cost.width>64 || s.name.height>64 || s.cost.height>64 {
                return Err("invalid/unsorted shop slot geometry".into());
            }
            if i>0 && self.slots[i-1].card.x+self.slots[i-1].card.width>s.card.x {
                return Err("shop cards overlap".into());
            }
            if s.name.x+s.name.width>s.cost.x { return Err("name/cost regions overlap".into()); }
        }
        Ok(())
    }
}

impl Anchor {
    pub fn index(&self) -> Result<TemplateIndex,String> {
        let mut index=TemplateIndex::new(DescriptorConfig{width:self.grid_width,height:self.grid_height})
            .map_err(|e|e.to_string())?;
        let image=GrayImage {width:self.grid_width as u32,height:self.grid_height as u32,
            stride_bytes:self.grid_width as u32,pixels:self.pixels.clone()};
        index.insert_image("structural_marker",&image).map_err(|e|e.to_string())?;
        Ok(index)
    }
}

/// Exact pixel extraction avoids f32 round-trip drift on seeded text boundaries.
pub fn crop(frame:&FrameEnvelope, rect:PixelRect) -> Result<RoiFrame,String> {
    if !contains(PixelRect{x:0,y:0,width:frame.width,height:frame.height},rect) {
        return Err("ROI outside frame".into());
    }
    let bpp=frame.pixel_format.bytes_per_pixel();
    let stride=rect.width as usize*bpp;
    let mut pixels=Vec::with_capacity(stride*rect.height as usize);
    for y in rect.y..rect.y+rect.height {
        let start=y as usize*frame.stride_bytes as usize+rect.x as usize*bpp;
        pixels.extend_from_slice(&frame.pixels[start..start+stride]);
    }
    Ok(RoiFrame {source_frame_id:frame.frame_id,captured_at_ms:frame.captured_at_ms,rect,
        stride_bytes:stride as u32,pixel_format:frame.pixel_format,bytes_per_pixel:bpp,pixels})
}

pub fn score(frame:&FrameEnvelope, rect:PixelRect, index:&TemplateIndex) -> Result<(Option<f32>,f32),String> {
    let gray=to_luma(&crop(frame,rect)?).map_err(|e|e.to_string())?;
    let mean=gray.pixels.iter().map(|&v|v as f64).sum::<f64>()/gray.pixels.len() as f64;
    let score=match index.classify(&gray) {
        Ok(Some(r))=>Some(r.best.similarity),
        Ok(None)|Err(VisualMatchError::FlatImage)=>None,
        Err(e)=>return Err(e.to_string()),
    };
    Ok((score,mean as f32))
}
