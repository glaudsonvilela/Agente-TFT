//! HP1: seeded visual badge localization, signed OCR and causal freshness.
//! Replay diagnostic only: no account identity, GameState writes or promotion.
use std::collections::HashSet;
use agente_tft_capture_core::{FrameEnvelope, PixelFormat, PixelRect, RoiFrame};
use agente_tft_perception_hud::{HudField, HudOcrEngine, HudPreprocessConfig};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BadgeProfile {
    pub schema_version: u32,
    pub name: String,
    pub reference_width: u32,
    pub reference_height: u32,
    pub search_rect: PixelRect,
    pub anchor_width: u32,
    pub anchor_height: u32,
    pub gold_points: Vec<[u32; 2]>,
    pub dark_points: Vec<[u32; 2]>,
    pub min_gold_fraction: f32,
    pub min_dark_fraction: f32,
    pub nms_radius_px: u32,
    pub max_raw_peaks: usize,
    pub hp_offset_x: u32,
    pub hp_offset_y: u32,
    pub hp_width: u32,
    pub hp_height: u32,
    pub max_hp_abs: i16,
    pub min_confidence: f32,
}
fn inside(r: PixelRect, w: u32, h: u32) -> bool {
    r.width > 0 && r.height > 0 && r.x.checked_add(r.width).is_some_and(|x| x <= w)
        && r.y.checked_add(r.height).is_some_and(|y| y <= h)
}
impl BadgeProfile {
    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != 1 || self.name.trim().is_empty() || self.name.len() > 100
            || self.reference_width > 8192 || self.reference_height > 8192
            || !inside(self.search_rect, self.reference_width, self.reference_height)
            || u64::from(self.search_rect.width) * u64::from(self.search_rect.height) > 1_000_000
            || !(1..=96).contains(&self.anchor_width) || !(1..=96).contains(&self.anchor_height)
            || self.anchor_width > self.search_rect.width || self.anchor_height > self.search_rect.height
            || !(1..=4096).contains(&self.max_raw_peaks) || !(1..=96).contains(&self.nms_radius_px)
            || !(1..=96).contains(&self.hp_width) || !(1..=96).contains(&self.hp_height)
            || self.hp_offset_x > 192 || self.hp_offset_y > 192 || !(1..=300).contains(&self.max_hp_abs)
        { return Err("invalid/excessive badge profile geometry or budgets".into()); }
        for value in [self.min_gold_fraction, self.min_dark_fraction, self.min_confidence] {
            if !value.is_finite() || !(0.70..=1.0).contains(&value) {
                return Err("badge/reader thresholds must be finite in [0.70,1]".into());
            }
        }
        for points in [&self.gold_points, &self.dark_points] {
            let unique: HashSet<_> = points.iter().copied().collect();
            if points.is_empty() || points.len() > 128 || unique.len() != points.len()
                || points.iter().any(|[x,y]| *x >= self.anchor_width || *y >= self.anchor_height)
            { return Err("invalid/duplicate anchor sample points".into()); }
        }
        if self.gold_points.iter().any(|p| self.dark_points.contains(p)) {
            return Err("gold and dark anchor points overlap".into());
        }
        Ok(())
    }
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct BadgeCandidate {
    pub anchor: PixelRect,
    pub hp_rect: PixelRect,
    /// Uncalibrated structural score, NOT OCR confidence or identity probability.
    pub marker_score: f32,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Localization {
    pub candidates: Vec<BadgeCandidate>,
    pub raw_peaks: usize,
    pub budget_exceeded: bool,
}
fn rgb(frame: &FrameEnvelope, x: u32, y: u32) -> [i16;3] {
    let i = y as usize * frame.stride_bytes as usize + x as usize * frame.pixel_format.bytes_per_pixel();
    let p = &frame.pixels[i..i+3];
    match frame.pixel_format {
        PixelFormat::Bgra8 => [p[2] as i16,p[1] as i16,p[0] as i16],
        _ => [p[0] as i16,p[1] as i16,p[2] as i16],
    }
}
fn is_gold([r,g,b]: [i16;3]) -> bool {
    r >= 110 && g >= 90 && r >= g && r-g <= 85 && g-b >= 25 && r-b >= 35
}
/// Scan a bounded list region. No row index, nickname, avatar or HP value selects it.
pub fn locate(frame: &FrameEnvelope, p: &BadgeProfile) -> Result<Localization,String> {
    p.validate()?;
    if (frame.width,frame.height) != (p.reference_width,p.reference_height) {
        return Err("badge profile resolution mismatch; no implicit resizing".into());
    }
    frame.validate().map_err(|e| e.to_string())?;
    let r = p.search_rect;
    let w = r.width as usize;
    let h = r.height as usize;
    let mut gold = vec![false;w*h];
    let mut dark = gold.clone();
    for y in 0..h { for x in 0..w {
        let c = rgb(frame,r.x+x as u32,r.y+y as u32);
        gold[y*w+x] = is_gold(c);
        dark[y*w+x] = c.iter().all(|v| *v <= 90);
    }}
    // One-pixel tolerance for antialiasing/JPEG, fixed independently of HP labels.
    let mut tolerant = vec![false;w*h];
    for y in 0..h { for x in 0..w {
        tolerant[y*w+x] = (y.saturating_sub(1)..=(y+1).min(h-1)).any(|yy|
            (x.saturating_sub(1)..=(x+1).min(w-1)).any(|xx| gold[yy*w+xx]));
    }}
    let mut peaks = Vec::new();
    for y in 0..=h-p.anchor_height as usize { for x in 0..=w-p.anchor_width as usize {
        let mut hits = 0usize;
        let mut impossible = false;
        for (i,[dx,dy]) in p.gold_points.iter().enumerate() {
            hits += usize::from(tolerant[(y+*dy as usize)*w+x+*dx as usize]);
            let best_possible = (hits+p.gold_points.len()-i-1) as f32 / p.gold_points.len() as f32;
            if best_possible < p.min_gold_fraction { impossible = true; break; }
        }
        if impossible { continue; }
        let g = hits as f32 / p.gold_points.len() as f32;
        let d = p.dark_points.iter().filter(|[dx,dy]| dark[(y+*dy as usize)*w+x+*dx as usize]).count() as f32 / p.dark_points.len() as f32;
        if g < p.min_gold_fraction || d < p.min_dark_fraction { continue; }
        let anchor = PixelRect{x:r.x+x as u32,y:r.y+y as u32,width:p.anchor_width,height:p.anchor_height};
        let hp_rect = PixelRect{x:anchor.x+p.hp_offset_x,y:anchor.y+p.hp_offset_y,width:p.hp_width,height:p.hp_height};
        if !inside(hp_rect,frame.width,frame.height) { continue; }
        peaks.push(BadgeCandidate{anchor,hp_rect,marker_score:0.8*g+0.2*d});
        if peaks.len() > p.max_raw_peaks {
            return Ok(Localization{raw_peaks:peaks.len(),candidates:vec![],budget_exceeded:true});
        }
    }}
    let raw_peaks = peaks.len();
    peaks.sort_by(|a,b| b.marker_score.total_cmp(&a.marker_score)
        .then_with(|| (a.anchor.y,a.anchor.x).cmp(&(b.anchor.y,b.anchor.x))));
    let mut candidates: Vec<BadgeCandidate> = Vec::new();
    for c in peaks {
        if !candidates.iter().any(|b| b.anchor.x.abs_diff(c.anchor.x) <= p.nms_radius_px
            && b.anchor.y.abs_diff(c.anchor.y) <= p.nms_radius_px) { candidates.push(c); }
    }
    Ok(Localization{candidates,raw_peaks,budget_exceeded:false})
}
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all="snake_case")]
pub enum HpStatus { Accepted, NegativeDisplay, BadgeNotFound, BadgeAmbiguous, SearchBudgetExceeded, OcrUncertain, OcrConflict, ReadError }
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HpAttempt {
    pub scale: u8,
    pub text: Option<String>,
    pub confidence: Option<f32>,
    pub parsed_signed: Option<i16>,
    pub reason: String,
    pub error: Option<String>,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HpRead {
    pub frame_id: u64,
    pub timestamp_ms: u64,
    pub status: HpStatus,
    pub signed_hp: Option<i16>,
    pub hp: Option<u16>,
    pub confidence: Option<f32>,
    pub location: Localization,
    pub attempts: Vec<HpAttempt>,
    pub error: Option<String>,
}
impl HpRead {
    pub fn failure(id:u64,at:u64,error:String) -> Self {
        Self{frame_id:id,timestamp_ms:at,status:HpStatus::ReadError,signed_hp:None,hp:None,confidence:None,
            location:Localization{candidates:vec![],raw_peaks:0,budget_exceeded:false},attempts:vec![],error:Some(error)}
    }
}
pub fn parse_signed_hp(text: &str, max: i16) -> Option<i16> {
    if !(1..=300).contains(&max) || text.len() > 32 { return None; }
    let t: String = text.chars().filter(|c| !c.is_whitespace()).collect();
    let digits = t.strip_prefix('-').unwrap_or(&t);
    if digits.is_empty() || digits.len() > 3 || !digits.bytes().all(|b| b.is_ascii_digit()) { return None; }
    t.parse::<i16>().ok().filter(|v| *v >= -max && *v <= max)
}
fn crop(frame:&FrameEnvelope,r:PixelRect) -> RoiFrame {
    let bpp = frame.pixel_format.bytes_per_pixel();
    let stride = r.width as usize*bpp;
    let mut pixels = Vec::with_capacity(stride*r.height as usize);
    for y in r.y..r.y+r.height {
        let start = y as usize*frame.stride_bytes as usize+r.x as usize*bpp;
        pixels.extend_from_slice(&frame.pixels[start..start+stride]);
    }
    RoiFrame{source_frame_id:frame.frame_id,captured_at_ms:frame.captured_at_ms,rect:r,
        stride_bytes:stride as u32,pixel_format:frame.pixel_format,bytes_per_pixel:bpp,pixels}
}
/// Requires the existing Tesseract engine configured with with_numeric_gray().
/// Gold selects neutral-color preprocessing; Stage selects ONLY the backend
/// digits-minus whitelist/PSM7. Neither stage nor gold parsers are used.
/// The observation stays HP: preserving '-' prevents -7 becoming +7.
pub fn read_player_hp<E:HudOcrEngine>(engine:&mut E,frame:&FrameEnvelope,p:&BadgeProfile) -> HpRead {
    let location = match locate(frame,p) {
        Ok(v) => v,
        Err(e) => return HpRead::failure(frame.frame_id,frame.captured_at_ms,e),
    };
    let mut out = HpRead{frame_id:frame.frame_id,timestamp_ms:frame.captured_at_ms,status:HpStatus::BadgeNotFound,
        signed_hp:None,hp:None,confidence:None,location,attempts:vec![],error:None};
    if out.location.budget_exceeded { out.status=HpStatus::SearchBudgetExceeded; return out; }
    if out.location.candidates.len()>1 { out.status=HpStatus::BadgeAmbiguous; return out; }
    let Some(c) = out.location.candidates.first() else { return out; };
    let roi = crop(frame,c.hp_rect);
    out.attempts = read_attempts(engine,&roi,p);
    if out.attempts.iter().any(|a| a.error.is_some()) {
        out.status=HpStatus::ReadError;
        out.error=Some("HP backend/preparation failure; inspect attempts".into());
        return out;
    }
    let accepted: Vec<_> = out.attempts.iter().filter(|a| a.reason=="candidate").collect();
    if accepted.len()!=2 { out.status=HpStatus::OcrUncertain; return out; }
    if accepted[0].parsed_signed!=accepted[1].parsed_signed { out.status=HpStatus::OcrConflict; return out; }
    let value = accepted[0].parsed_signed.unwrap();
    out.signed_hp=Some(value);
    out.confidence=Some(accepted.iter().map(|a| a.confidence.unwrap()).fold(1.0,f32::min));
    if value<0 { out.status=HpStatus::NegativeDisplay; }
    else { out.status=HpStatus::Accepted; out.hp=Some(value as u16); }
    out
}
fn read_attempts<E:HudOcrEngine>(engine:&mut E,roi:&RoiFrame,p:&BadgeProfile) -> Vec<HpAttempt> {
    [3,4].into_iter().map(|scale| {
        let mut a = HpAttempt{scale,text:None,confidence:None,parsed_signed:None,reason:"no_text".into(),error:None};
        let result = engine.prepare_roi(HudField::Gold,roi,HudPreprocessConfig{upscale_factor:scale,invert:true})
            .map_err(|e| format!("{e:?}")).and_then(|image| engine.recognize(HudField::Stage,&image));
        match result {
            Err(e) => { a.reason="backend_or_preprocess_error".into(); a.error=Some(e); }
            Ok(None) => {},
            Ok(Some(r)) => {
                a.parsed_signed=parse_signed_hp(&r.text,p.max_hp_abs);
                a.text=Some(r.text);
                a.confidence=Some(r.confidence.value());
                a.reason = if a.parsed_signed.is_none() {"domain_invalid"}
                    else if r.confidence.value()<p.min_confidence {"below_min_confidence"} else {"candidate"}.into();
            }
        }
        a
    }).collect()
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StableHp { pub value:u16, pub confidence:f32, pub observed_at_ms:u64 }
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HpFreshness {
    pub current: Option<StableHp>,
    pub last_good: Option<StableHp>,
    pub age_ms: Option<u64>,
    pub stale: bool,
    pub confirmations: u32,
}
/// Per-source/session tracker. Never reuse across recordings or accounts.
pub struct HpTracker {
    max_gap_ms:u64, max_age_ms:u64, last:Option<(u64,u64)>,
    pending:Option<(u16,u32,f32)>, good:Option<StableHp>,
}
impl HpTracker {
    pub fn new(max_gap_ms:u64,max_age_ms:u64) -> Result<Self,String> {
        if max_gap_ms==0 || max_age_ms<max_gap_ms { return Err("invalid HP temporal limits".into()); }
        Ok(Self{max_gap_ms,max_age_ms,last:None,pending:None,good:None})
    }
    pub fn observe(&mut self,r:&HpRead) -> Result<HpFreshness,String> {
        if let Some((id,at)) = self.last {
            if r.frame_id<=id || r.timestamp_ms<=at { return Err("duplicate/out-of-order HP observation".into()); }
            if r.timestamp_ms-at>self.max_gap_ms { self.pending=None; }
        }
        self.last=Some((r.frame_id,r.timestamp_ms));
        let mut current=None;
        if r.status==HpStatus::Accepted {
            match (r.hp,r.confidence) {
                (Some(hp),Some(c)) if c.is_finite() && (0.70..=1.0).contains(&c) => {
                    let (count,conf) = match self.pending {
                        Some((v,n,old)) if v==hp => (n.saturating_add(1),old.min(c)),
                        _ => (1,c),
                    };
                    self.pending=Some((hp,count,conf));
                    if count>=2 {
                        current=Some(StableHp{value:hp,confidence:conf,observed_at_ms:r.timestamp_ms});
                        self.good=current.clone();
                    }
                }
                _ => { self.pending=None; }
            }
        } else { self.pending=None; }
        let age=self.good.as_ref().map(|v| r.timestamp_ms-v.observed_at_ms);
        Ok(HpFreshness{current,last_good:self.good.clone(),age_ms:age,
            stale:age.map(|v| v>self.max_age_ms).unwrap_or(true),
            confirmations:self.pending.map(|(_,n,_)| n).unwrap_or(0)})
    }
}
#[cfg(test)]
mod tests;
