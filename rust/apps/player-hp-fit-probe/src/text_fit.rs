//! HP3 candidate: fit the text envelope inside the existing HP ROI.
//! No new reader, labels, position search, value repair or profile activation.
use std::cell::RefCell;
use agente_tft_capture_core::{PixelRect, RoiFrame};
use agente_tft_image_preprocess::GrayImage;
use agente_tft_perception_hud::{HudField, HudOcrEngine, HudPreprocessConfig, HudReadError, RecognizedText};
use serde::{Deserialize, Serialize};

pub const HP_TEXT_FIT_PROFILE: &str = "hp_text_fit_v1";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TextFitTrace {
    pub profile: String,
    pub applied: bool,
    pub reason: String,
    pub original_rect: PixelRect,
    pub fitted_rect: PixelRect,
    pub foreground_threshold: u8,
    pub foreground_pixels: usize,
    pub scale: u8,
}

/// The entire foreground union is retained, including disconnected minus signs.
/// This is an appearance heuristic; very faint strokes can still be missed.
/// Failures return the original ROI, never an invented crop or numeric value.
pub fn fit_hp_text(roi: &RoiFrame, scale: u8) -> Result<(RoiFrame, TextFitTrace), String> {
    let w = roi.rect.width as usize;
    let h = roi.rect.height as usize;
    let bpp = roi.pixel_format.bytes_per_pixel();
    if w == 0 || h == 0 || w > 96 || h > 96 || roi.bytes_per_pixel != bpp
        || (roi.stride_bytes as usize) < w*bpp
        || roi.pixels.len() < roi.stride_bytes as usize*h
        || !(1..=8).contains(&scale)
        || roi.rect.x.checked_add(roi.rect.width).is_none()
        || roi.rect.y.checked_add(roi.rect.height).is_none()
    { return Err("invalid/budget-exceeding HP text fit ROI".into()); }
    let mut gray = Vec::with_capacity(w*h);
    for y in 0..h { for x in 0..w {
        let at = y*roi.stride_bytes as usize+x*bpp;
        let p = &roi.pixels[at..at+3];
        let lo = *p.iter().min().unwrap() as i16;
        let hi = *p.iter().max().unwrap() as i16;
        gray.push((2*lo-hi).clamp(0,255) as u8);
    }}
    let lo = *gray.iter().min().unwrap();
    let hi = *gray.iter().max().unwrap();
    let threshold = 100.max((u16::from(hi)*55/100) as u8);
    let mut trace = TextFitTrace {
        profile: HP_TEXT_FIT_PROFILE.into(), applied: false, reason: "low_contrast".into(),
        original_rect: roi.rect, fitted_rect: roi.rect,
        foreground_threshold: threshold, foreground_pixels: 0, scale,
    };
    if hi < 100 || hi.saturating_sub(lo) < 80 { return Ok((roi.clone(),trace)); }
    let (mut left,mut top,mut right,mut bottom) = (w,h,0usize,0usize);
    for y in 0..h { for x in 0..w {
        if gray[y*w+x] >= threshold {
            trace.foreground_pixels += 1;
            left=left.min(x);top=top.min(y);right=right.max(x);bottom=bottom.max(y);
        }
    }}
    if trace.foreground_pixels < 3 || trace.foreground_pixels*5 > w*h*4 {
        trace.reason="insufficient_or_flat_foreground".into();return Ok((roi.clone(),trace));
    }
    if left==0 || top==0 || right+1==w || bottom+1==h {
        trace.reason="foreground_at_input_edge".into();return Ok((roi.clone(),trace));
    }
    left=left.saturating_sub(2);top=top.saturating_sub(2);
    right=(right+3).min(w);bottom=(bottom+3).min(h);
    let rect=PixelRect {x:roi.rect.x+left as u32,y:roi.rect.y+top as u32,
        width:(right-left) as u32,height:(bottom-top) as u32};
    if rect==roi.rect {trace.reason="already_fitted".into();return Ok((roi.clone(),trace));}
    let stride=rect.width as usize*bpp;
    let mut pixels=Vec::with_capacity(stride*rect.height as usize);
    for y in top..bottom {
        let start=y*roi.stride_bytes as usize+left*bpp;
        pixels.extend_from_slice(&roi.pixels[start..start+stride]);
    }
    trace.applied=true;trace.reason="foreground_union_plus_two_pixel_margin".into();trace.fitted_rect=rect;
    Ok((RoiFrame {source_frame_id:roi.source_frame_id,captured_at_ms:roi.captured_at_ms,rect,
        stride_bytes:stride as u32,pixel_format:roi.pixel_format,bytes_per_pixel:bpp,pixels},trace))
}

/// Use only with the HP1 adapter and an inner numeric-gray Tesseract engine.
/// HP1 requests Gold preparation for neutral-color projection and Stage OCR
/// for the signed-digit whitelist. The inner backend's behavior is unchanged.
pub struct HpTextFitOcr<E> { inner:E, traces:RefCell<Vec<TextFitTrace>> }
impl<E> HpTextFitOcr<E> {
    pub fn new(inner:E)->Self {Self{inner,traces:RefCell::new(Vec::new())}}
    pub fn take_traces(&self)->Vec<TextFitTrace> {std::mem::take(&mut *self.traces.borrow_mut())}
}
impl<E:HudOcrEngine> HudOcrEngine for HpTextFitOcr<E> {
    fn prepare_roi(&self,field:HudField,roi:&RoiFrame,config:HudPreprocessConfig)->Result<GrayImage,HudReadError> {
        if field!=HudField::Gold {return self.inner.prepare_roi(field,roi,config);}
        let (fit,trace)=fit_hp_text(roi,config.upscale_factor).map_err(HudReadError::Preprocess)?;
        let mut traces=self.traces.borrow_mut();
        if traces.len()>=8 {traces.remove(0);}
        traces.push(trace);drop(traces);
        self.inner.prepare_roi(field,&fit,config)
    }
    fn recognize(&mut self,field:HudField,image:&GrayImage)->Result<Option<RecognizedText>,String> {
        self.inner.recognize(field,image)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use agente_tft_capture_core::PixelFormat;
    fn roi()->RoiFrame {RoiFrame {source_frame_id:9,captured_at_ms:123,
        rect:PixelRect{x:100,y:200,width:44,height:25},stride_bytes:44*4,
        pixel_format:PixelFormat::Rgba8,bytes_per_pixel:4,pixels:vec![0;44*25*4]}}
    fn pixel(r:&mut RoiFrame,x:usize,y:usize,c:[u8;4]) {
        let i=y*r.stride_bytes as usize+x*4;r.pixels[i..i+4].copy_from_slice(&c);
    }
    fn marked()->RoiFrame {
        let mut r=roi();
        for y in 6..22 {for x in 21..32 {pixel(&mut r,x,y,[230,230,230,255]);}}
        // Disconnected minus is part of the envelope; no component is discarded.
        for y in 15..17 {for x in 13..19 {pixel(&mut r,x,y,[230,230,230,255]);}}
        r
    }
    #[test] fn fit_preserves_disconnected_minus_source_pixels_and_metadata() {
        let r=marked();let (f,t)=fit_hp_text(&r,3).unwrap();
        assert!(t.applied);assert_eq!(f.rect,PixelRect{x:111,y:204,width:23,height:20});
        assert_eq!((f.source_frame_id,f.captured_at_ms),(9,123));
        for y in 0..20 {for x in 0..23 {
            let src=(y+4)*176+(x+11)*4;let dst=y*92+x*4;
            assert_eq!(&f.pixels[dst..dst+4],&r.pixels[src..src+4]);
        }}
    }
    #[test] fn flat_and_input_edge_foreground_are_not_trimmed() {
        let r=roi();assert!(!fit_hp_text(&r,4).unwrap().1.applied);
        let mut r=marked();pixel(&mut r,0,10,[230,230,230,255]);
        assert_eq!(fit_hp_text(&r,3).unwrap().1.reason,"foreground_at_input_edge");
    }
    #[test] fn source_color_formats_and_padding_agree() {
        let r=marked();let expected=fit_hp_text(&r,3).unwrap().1;
        let mut b=r.clone();b.pixel_format=PixelFormat::Bgra8;
        for p in b.pixels.chunks_exact_mut(4) {p.swap(0,2);}
        assert_eq!(fit_hp_text(&b,3).unwrap().1,expected);
        let mut b=r.clone();b.pixel_format=PixelFormat::Rgb8;b.bytes_per_pixel=3;b.stride_bytes=44*3+7;b.pixels.clear();
        for row in r.pixels.chunks_exact(176) {for p in row.chunks_exact(4) {b.pixels.extend_from_slice(&p[..3]);}b.pixels.extend([77;7]);}
        assert_eq!(fit_hp_text(&b,3).unwrap().1,expected);
    }
    #[test] fn chromatic_border_does_not_expand_text_envelope() {
        let mut r=marked();pixel(&mut r,0,0,[230,200,90,255]);
        assert_eq!(fit_hp_text(&r,3).unwrap().1.fitted_rect,fit_hp_text(&marked(),3).unwrap().1.fitted_rect);
    }
    #[test] fn fit_does_not_depend_on_frame_id_or_timestamp() {
        let r=marked();let mut other=r.clone();other.source_frame_id=500;other.captured_at_ms=800;
        assert_eq!(fit_hp_text(&r,3).unwrap().1,fit_hp_text(&other,3).unwrap().1);
    }
    #[test] fn invalid_buffers_scale_and_geometry_fail() {
        let mut r=marked();r.pixels.clear();assert!(fit_hp_text(&r,3).is_err());
        let mut r=marked();r.rect.width=1000;assert!(fit_hp_text(&r,3).is_err());
        let mut r=marked();r.rect.x=u32::MAX;assert!(fit_hp_text(&r,3).is_err());
        assert!(fit_hp_text(&marked(),0).is_err());
    }
    #[test] fn trace_round_trips() {
        let t=fit_hp_text(&marked(),4).unwrap().1;
        assert_eq!(serde_json::from_str::<TextFitTrace>(&serde_json::to_string(&t).unwrap()).unwrap(),t);
    }
}
