//! S3: UI appearances, not click authorization, season rules or account state.
use std::collections::BTreeSet;

use agente_tft_capture_core::{FrameEnvelope, PixelFormat, PixelRect};
use agente_tft_image_preprocess::GrayImage;
use agente_tft_visual_match::{DescriptorConfig, TemplateIndex, VisualMatchError};
use serde::{Deserialize, Serialize};

use crate::layout::{contains, ScreenLayout};
use crate::recovery::{intersects, RecoveryProfile, RoutingTrace};
use crate::screen::Attempt;

#[derive(Debug, Clone, Deserialize)]
pub struct ControlTemplate {
    pub state: String,
    pub rgb: Vec<u8>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ControlSpec {
    pub id: String,
    pub rect: PixelRect,
    pub grid_width: u16,
    pub grid_height: u16,
    pub min_similarity: f32,
    pub max_rgb_mae: f32,
    pub templates: Vec<ControlTemplate>,
    pub price_rect: Option<PixelRect>,
    pub free_count_rect: Option<PixelRect>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ControlsProfile {
    pub schema_version: u32,
    pub id: String,
    pub parent_layout_id: String,
    pub recovery_profile_id: String,
    pub min_text_confidence: f32,
    pub controls: Vec<ControlSpec>,
}

#[derive(Debug, Clone, Serialize)]
pub struct VisualScore {
    pub state: String,
    pub similarity: Option<f32>,
    pub rgb_mae: f32,
    pub eligible: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct ControlRead {
    pub id: String,
    pub rect: PixelRect,
    pub status: String,
    pub appearance: Option<String>,
    pub scores: Vec<VisualScore>,
    /// Always unknown here: appearance alone cannot authorize an action.
    pub action_allowed: Option<bool>,
}

#[derive(Debug, Clone, Serialize)]
pub struct NumericRead {
    pub id: String,
    pub rect: PixelRect,
    pub status: String,
    pub value: Option<u16>,
    pub confidence: Option<f32>,
    pub attempts: Vec<Attempt>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ControlsRead {
    pub profile: String,
    pub timestamp_ms: u64,
    pub controls: Vec<ControlRead>,
    pub numeric_fields: Vec<NumericRead>,
    pub routing: Vec<RoutingTrace>,
    pub ocr_process_calls: u8,
    pub error: Option<String>,
    pub temporal_confirmation: bool,
}

struct CompiledControl {
    spec: ControlSpec,
    indices: Vec<TemplateIndex>,
}

pub struct ControlsReader {
    pub profile: ControlsProfile,
    controls: Vec<CompiledControl>,
    width: u32,
    height: u32,
}

fn gray(rgb: &[u8], width: u16, height: u16) -> GrayImage {
    let pixels = rgb.chunks_exact(3).map(|p|
        ((77 * p[0] as u16 + 150 * p[1] as u16 + 29 * p[2] as u16) >> 8) as u8).collect();
    GrayImage { width: width as u32, height: height as u32, stride_bytes: width as u32, pixels }
}

impl ControlsReader {
    pub fn new(profile: ControlsProfile, layout: &ScreenLayout, recovery: &RecoveryProfile) -> Result<Self, String> {
        layout.validate()?;
        recovery.validate(layout)?;
        if profile.schema_version != 1 || profile.id.trim().is_empty() || profile.id.len() > 100
            || profile.parent_layout_id != layout.id || profile.recovery_profile_id != recovery.id
            || !profile.min_text_confidence.is_finite() || !(0.70..=1.0).contains(&profile.min_text_confidence)
            || profile.controls.iter().map(|s| s.id.as_str()).collect::<Vec<_>>() != ["lock", "buy_xp", "refresh"] {
            return Err("invalid controls profile, order or UI compatibility".into());
        }
        let screen = PixelRect { x: 0, y: 0, width: layout.reference_width, height: layout.reference_height };
        let mut occupied = Vec::new();
        let mut controls = Vec::new();
        for spec in &profile.controls {
            if !(4..=32).contains(&spec.grid_width) || !(4..=32).contains(&spec.grid_height)
                || !(1..=8).contains(&spec.templates.len()) || !spec.min_similarity.is_finite()
                || !(0.95..=1.0).contains(&spec.min_similarity) || !spec.max_rgb_mae.is_finite()
                || !(0.0..=12.0).contains(&spec.max_rgb_mae) {
                return Err("invalid controls descriptor, threshold or budget".into());
            }
            if (spec.id == "lock" && (spec.price_rect.is_some() || spec.free_count_rect.is_some()))
                || (spec.id != "lock" && spec.price_rect.is_none())
                || (spec.id == "buy_xp" && spec.free_count_rect.is_some())
                || (spec.id == "refresh" && spec.free_count_rect.is_none()) {
                return Err("invalid control numeric fields".into());
            }
            for rect in std::iter::once(spec.rect).chain(spec.price_rect).chain(spec.free_count_rect) {
                if !contains(screen, rect) || rect.width > 256 || rect.height > 96
                    || layout.slots.iter().any(|slot| intersects(rect, slot.card))
                    || occupied.iter().any(|r| intersects(rect, *r)) {
                    return Err("control rectangles must be bounded, disjoint and outside cards".into());
                }
                occupied.push(rect);
            }
            let mut indices = Vec::new();
            for template in &spec.templates {
                let allowed = match spec.id.as_str() {
                    "lock" => ["locked_appearance", "unlocked_appearance"].contains(&template.state.as_str()),
                    "buy_xp" => ["active_appearance", "dimmed_appearance"].contains(&template.state.as_str()),
                    _ => ["active_appearance", "dimmed_appearance", "free_refresh_appearance"].contains(&template.state.as_str()),
                };
                if !allowed || template.rgb.len() != spec.grid_width as usize * spec.grid_height as usize * 3 {
                    return Err("invalid control state or RGB signature".into());
                }
                let mut index = TemplateIndex::new(DescriptorConfig { width: spec.grid_width, height: spec.grid_height })
                    .map_err(|e| e.to_string())?;
                index.insert_image(&template.state, &gray(&template.rgb, spec.grid_width, spec.grid_height))
                    .map_err(|e| e.to_string())?;
                indices.push(index);
            }
            controls.push(CompiledControl { spec: spec.clone(), indices });
        }
        Ok(Self { profile, controls, width: layout.reference_width, height: layout.reference_height })
    }

    pub fn read_visual(&self, frame: &FrameEnvelope, panel_located: bool) -> Result<ControlsRead, String> {
        frame.validate().map_err(|e| e.to_string())?;
        if (frame.width, frame.height) != (self.width, self.height) {
            return Err("controls resolution mismatch; no implicit scaling".into());
        }
        let mut output = ControlsRead { profile: self.profile.id.clone(), timestamp_ms: frame.captured_at_ms,
            controls: vec![], numeric_fields: vec![], routing: vec![], ocr_process_calls: 0,
            error: None, temporal_confirmation: false };
        for control in &self.controls {
            let spec = &control.spec;
            let mut read = ControlRead { id: spec.id.clone(), rect: spec.rect,
                status: if panel_located { "unknown" } else { "unavailable" }.into(),
                appearance: None, scores: vec![], action_allowed: None };
            if panel_located {
                let rgb = sample(frame, spec);
                let image = gray(&rgb, spec.grid_width, spec.grid_height);
                let mut eligible = BTreeSet::new();
                for (template, index) in spec.templates.iter().zip(&control.indices) {
                    let similarity = match index.classify(&image) {
                        Ok(Some(result)) => Some(result.best.similarity),
                        Ok(None) | Err(VisualMatchError::FlatImage) => None,
                        Err(error) => return Err(error.to_string()),
                    };
                    let mae = rgb.iter().zip(&template.rgb).map(|(a,b)| a.abs_diff(*b) as f32).sum::<f32>() / rgb.len() as f32;
                    let accepted = similarity.is_some_and(|s| s >= spec.min_similarity) && mae <= spec.max_rgb_mae;
                    if accepted { eligible.insert(template.state.clone()); }
                    read.scores.push(VisualScore { state: template.state.clone(), similarity, rgb_mae: mae, eligible: accepted });
                }
                match eligible.len() {
                    1 => { read.appearance = eligible.into_iter().next(); read.status = "observed".into(); }
                    0 => {}
                    _ => { read.status = "ambiguous".into(); }
                }
            }
            output.controls.push(read);
        }
        Ok(output)
    }
}

fn sample(frame: &FrameEnvelope, spec: &ControlSpec) -> Vec<u8> {
    let mut rgb = Vec::with_capacity(spec.grid_width as usize * spec.grid_height as usize * 3);
    for y in 0..spec.grid_height as u32 {
        for x in 0..spec.grid_width as u32 {
            // Integer pixel-center sampling, deterministic across machines.
            let sx = spec.rect.x + ((2*x+1) * spec.rect.width / (2*spec.grid_width as u32)).min(spec.rect.width-1);
            let sy = spec.rect.y + ((2*y+1) * spec.rect.height / (2*spec.grid_height as u32)).min(spec.rect.height-1);
            let at = sy as usize * frame.stride_bytes as usize + sx as usize * frame.pixel_format.bytes_per_pixel();
            let p = &frame.pixels[at..at+3];
            if frame.pixel_format == PixelFormat::Bgra8 { rgb.extend([p[2],p[1],p[0]]); } else { rgb.extend_from_slice(p); }
        }
    }
    rgb
}

#[cfg(test)]
#[path = "controls_tests.rs"]
mod tests;
