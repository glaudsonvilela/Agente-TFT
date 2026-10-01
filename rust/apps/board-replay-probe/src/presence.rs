//! B2 bench-only image-level occupancy hypotheses. B1 records stay immutable.
use agente_tft_capture_core::FrameEnvelope;
use serde::{Deserialize,Serialize};
use crate::{foreground::{self,Appearance,Component},profile::{Profile,Rect},scene::SceneRead};

#[derive(Debug,Clone,Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PresenceProfile {
    pub schema_version:u32,pub id:String,pub parent_profile_id:String,pub parent_blob_sha1:String,
    pub surface_anchors:Vec<Rect>,
    pub body_top:u32,pub body_width:u32,pub body_height:u32,
    pub marker_top:u32,pub marker_bottom:u32,pub marker_center_tolerance:u32,pub support_top:u32,
    pub max_color_offset:i16,pub surface_min_correlation:f32,pub surface_max_residual_mae:f32,
    pub surface_max_changed_fraction:f32,pub empty_min_correlation:f32,
    pub empty_max_residual_mae:f32,pub empty_max_changed_fraction:f32,pub residual_threshold:u8,
    pub min_component_pixels:usize,pub min_component_width:u32,pub min_component_height:u32,
    pub max_component_fraction:f32,pub max_components:usize,pub note:String,
}
impl PresenceProfile {
    pub fn crop(&self,p:&Profile,slot:usize)->Rect {
        Rect{x:p.bench_centers[slot].saturating_sub(self.body_width/2),y:self.body_top,
            width:self.body_width,height:self.body_height}
    }
    pub fn validate(&self,p:&Profile)->Result<(),String> {
        p.validate()?;
        // Bound coordinates before any addition or area calculation.
        if self.body_top>=p.reference_height || self.marker_bottom>p.reference_height
            || p.bench_centers.iter().any(|x|*x<self.body_width/2) {
            return Err("presence coordinates outside the reference frame".into());
        }
        if self.schema_version!=1 || self.id.trim().is_empty() || self.id.len()>100
            || self.parent_profile_id!=p.id || self.parent_blob_sha1.len()!=40
            || !self.parent_blob_sha1.bytes().all(|v|v.is_ascii_hexdigit()) || self.surface_anchors.len()!=3
            || !(32..=128).contains(&self.body_width) || !(32..=160).contains(&self.body_height)
            || self.marker_top>=self.marker_bottom || self.marker_bottom>self.body_top+24
            || self.marker_center_tolerance==0 || self.marker_center_tolerance>self.body_width/2
            || self.support_top<=self.body_top || self.support_top>=self.body_top+self.body_height
            || !(0..=40).contains(&self.max_color_offset) || !(24..=32).contains(&self.residual_threshold)
            || !(120..=4096).contains(&self.min_component_pixels)
            || !(10..=64).contains(&self.min_component_width) || !(24..=96).contains(&self.min_component_height)
            || self.max_components==0 || self.max_components>512 || self.note.len()>1024 {
            return Err("invalid bench presence identity/geometry/budget".into());
        }
        for (value,lo,hi) in [(self.surface_min_correlation,0.90,1.0),(self.surface_max_residual_mae,0.0,6.0),
            (self.surface_max_changed_fraction,0.0,0.05),(self.empty_min_correlation,0.98,1.0),
            (self.empty_max_residual_mae,0.0,4.0),(self.empty_max_changed_fraction,0.0,0.01),
            (self.max_component_fraction,0.1,0.70)] {
            if !value.is_finite() || !(lo..=hi).contains(&value) {return Err("invalid bench presence threshold".into());}
        }
        for i in 0..9 {
            let r=self.crop(p,i);
            if !r.valid(p.reference_width,p.reference_height) || (i>0 && r.overlaps(self.crop(p,i-1))) {
                return Err("invalid or overlapping presence crops".into());
            }
        }
        for (i,r) in self.surface_anchors.iter().enumerate() {
            if !r.valid(p.reference_width,p.reference_height) || r.width>128 || r.height>64
                || r.y<self.body_top+self.body_height || self.surface_anchors[..i].iter().any(|a|r.overlaps(*a)) {
                return Err("invalid bench structural anchor".into());
            }
        }
        Ok(())
    }
    pub fn offset_ok(&self,s:&Appearance)->bool {s.offset.iter().all(|v|v.abs()<=self.max_color_offset)}
    pub fn surface_ok(&self,s:&Appearance)->bool {
        self.offset_ok(s) && s.reference_spread>=4.0 && s.correlation>=self.surface_min_correlation
            && s.residual_mae<=self.surface_max_residual_mae && s.changed_fraction<=self.surface_max_changed_fraction
    }
    pub fn empty_ok(&self,s:&Appearance)->bool {
        self.offset_ok(s) && s.reference_spread>=4.0 && s.correlation>=self.empty_min_correlation
            && s.residual_mae<=self.empty_max_residual_mae && s.changed_fraction<=self.empty_max_changed_fraction
    }
    pub fn body_ok(&self,c:&Component,r:Rect)->bool {
        c.pixels>=self.min_component_pixels && c.pixels as f32/((r.width*r.height) as f32)<=self.max_component_fraction
            && c.rect.width>=self.min_component_width && c.rect.height>=self.min_component_height
            && c.rect.x>r.x && c.rect.x+c.rect.width<r.x+r.width
            && c.rect.y>r.y && c.rect.y+c.rect.height<r.y+r.height
            && c.rect.y+c.rect.height>self.support_top
    }
}
#[derive(Debug,Serialize)]
pub struct BenchPresence {
    pub slot:usize,pub crop:Rect,pub status:String,pub occupancy:Option<bool>,
    pub appearance:Option<Appearance>,pub marker_candidates:Vec<usize>,pub body_candidates:Vec<Component>,
    pub components_total:usize,pub reason:String,pub unit_id:Option<String>,pub ground_point:Option<[f32;2]>,
}
#[derive(Debug,Serialize)]
pub struct PresenceRead {
    pub timestamp_ms:u64,pub profile:String,pub surface_status:String,pub surface_scores:Vec<Appearance>,
    pub slots:Vec<BenchPresence>,pub temporal_confirmation:bool,pub ownership_established:bool,
    pub note:String,
}
pub struct PresenceReader {
    base:Profile,policy:PresenceProfile,anchors:Vec<Vec<[u8;3]>>,slots:Vec<Vec<[u8;3]>>,
}
impl PresenceReader {
    pub fn new(base:Profile,policy:PresenceProfile,reference:&FrameEnvelope)->Result<Self,String> {
        policy.validate(&base)?;base.validate_frame(reference)?;
        let anchors=policy.surface_anchors.iter().map(|r|foreground::pixels(reference,*r)).collect();
        let slots=(0..9).map(|i|foreground::pixels(reference,policy.crop(&base,i))).collect();
        Ok(Self{base,policy,anchors,slots})
    }
    pub fn read(&self,f:&FrameEnvelope,legacy:&SceneRead)->Result<PresenceRead,String> {
        self.base.validate_frame(f)?;let p=&self.policy;
        if legacy.timestamp_ms!=f.captured_at_ms || legacy.profile!=self.base.id {
            return Err("presence/legacy frame identity mismatch".into());
        }
        let mut scores=Vec::new();
        for (rect,reference) in p.surface_anchors.iter().zip(&self.anchors) {
            scores.push(foreground::compare(reference,&foreground::pixels(f,*rect),p.residual_threshold)?.0);
        }
        let surface=if legacy.projection_status=="reference_arena_match" {"reference_arena"}
            else if scores.iter().all(|s|p.surface_ok(s)) {"bench_structure_match"}else{"unresolved"};
        let mut slots=Vec::new();
        for i in 0..9 {
            let crop=p.crop(&self.base,i);
            let mut row=BenchPresence{slot:i,crop,status:"unavailable".into(),occupancy:None,appearance:None,
                marker_candidates:vec![],body_candidates:vec![],components_total:0,reason:"surface_unresolved".into(),
                unit_id:None,ground_point:None};
            if surface!="unresolved" {
                let (appearance,mask)=foreground::compare(&self.slots[i],&foreground::pixels(f,crop),p.residual_threshold)?;
                let candidates=foreground::components(&mask,crop,p.max_components)?;
                row.components_total=candidates.len();
                row.body_candidates=candidates.into_iter().filter(|c|p.body_ok(c,crop)).collect();
                let center=f64::from(self.base.bench_centers[i]);
                row.marker_candidates=legacy.markers.iter().filter(|m| {
                    let x=f64::from(m.rect.x)+f64::from(m.rect.width)/2.0;
                    m.rect.y>=p.marker_top && m.rect.y+m.rect.height<=p.marker_bottom
                        && (x-center).abs()<=f64::from(p.marker_center_tolerance)
                }).map(|m|m.id).collect();
                let empty=p.empty_ok(&appearance);
                let any_overlap=legacy.markers.iter().any(|m|crop.overlaps(m.rect));
                let paired=if row.marker_candidates.len()==1 && row.body_candidates.len()==1 {
                    let m=&legacy.markers[row.marker_candidates[0]];let b=&row.body_candidates[0];
                    let mx=f64::from(m.rect.x)+f64::from(m.rect.width)/2.0;
                    let bx=f64::from(b.rect.x)+f64::from(b.rect.width)/2.0;
                    b.rect.y>=m.rect.y+m.rect.height && (mx-bx).abs()<=f64::from(p.marker_center_tolerance)
                }else{false};
                let (status,occupancy,reason)=if !p.offset_ok(&appearance) {
                    ("unknown",None,"appearance_offset_out_of_budget")
                }else if row.marker_candidates.len()>1 || row.body_candidates.len()>1 || (empty && !row.marker_candidates.is_empty()) {
                    ("ambiguous",None,"conflicting_or_multiple_support")
                }else if paired && !empty {
                    ("occupied_visual",Some(true),"single_bar_and_connected_foreground_reaches_support_band")
                }else if empty && !any_overlap && row.marker_candidates.is_empty() && row.body_candidates.is_empty() {
                    ("empty_visual",Some(false),"textured_empty_reference_match_without_marker_or_body")
                }else{("unknown",None,"insufficient_joint_support")};
                row.status=status.into();row.occupancy=occupancy;row.reason=reason.into();row.appearance=Some(appearance);
            }
            slots.push(row);
        }
        Ok(PresenceRead{timestamp_ms:f.captured_at_ms,profile:p.id.clone(),surface_status:surface.into(),surface_scores:scores,slots,
            temporal_confirmation:false,ownership_established:false,
            note:"Image-level bench occupancy hypotheses, not accuracy or champion identity. No board footpoint inferred; no state update.".into()})
    }
}
#[cfg(test)]
#[path="presence_tests.rs"]
mod tests;
