//! Unknown occupancy is not empty. Arena matching is not player identity.
use agente_tft_capture_core::FrameEnvelope;
use serde::Serialize;
use crate::{bars::{detect,Marker},profile::{compare,signature,Profile,Rect,SignatureScore}};

#[derive(Debug,Serialize)]
pub struct BenchRead {
    pub slot:usize,pub rect:Rect,pub ground_pixel:[u32;2],pub evidence:String,
    pub empty_signature:Option<SignatureScore>,pub marker_candidates:Vec<usize>,
    pub unit_id:Option<String>,pub occupancy:Option<bool>,
}
#[derive(Debug,Serialize)]
pub struct CellRead {pub row:u8,pub col:u8,pub screen:[f32;2],pub occupancy:Option<bool>}
#[derive(Debug,Serialize)]
pub struct SceneRead {
    pub timestamp_ms:u64,pub profile:String,pub projection_status:String,pub reference_basis:String,
    pub arena_scores:Vec<SignatureScore>,pub markers:Vec<Marker>,pub bench:Vec<BenchRead>,pub board:Vec<CellRead>,
    pub phase:Option<String>,pub perspective:Option<String>,pub error:Option<String>,
}
pub struct SceneReader {
    profile:Profile,arena_reference:Vec<Vec<[u8;3]>>,bench_reference:Option<Vec<Vec<[u8;3]>>>,
}
impl SceneReader {
    pub fn new(profile:Profile,reference:&FrameEnvelope)->Result<Self,String> {
        profile.validate()?;profile.validate_frame(reference)?;
        let arena_reference:Vec<_>=profile.arena_anchors.iter().map(|r|signature(reference,*r,&profile.signature)).collect();
        // A flat/black reference cannot establish an arena.
        if arena_reference.iter().any(|a| {
            let lo=a.iter().flatten().min().unwrap();let hi=a.iter().flatten().max().unwrap();hi.abs_diff(*lo)<24
        }) {return Err("flat arena reference".into());}
        let bench_reference=(0..9).map(|i|signature(reference,profile.bench_rect(i),&profile.signature)).collect();
        Ok(Self{profile,arena_reference,bench_reference:Some(bench_reference)})
    }
    pub fn from_anchors(profile:Profile,arena_reference:Vec<Vec<[u8;3]>>)->Result<Self,String> {
        profile.validate()?;
        let size=(profile.signature.grid_width*profile.signature.grid_height) as usize;
        if arena_reference.len()!=profile.arena_anchors.len() || arena_reference.iter().any(|r|r.len()!=size) {
            return Err("invalid packaged arena anchors".into());
        }
        Ok(Self{profile,arena_reference,bench_reference:None})
    }
    pub fn read(&self,f:&FrameEnvelope)->Result<SceneRead,String> {
        let p=&self.profile;p.validate_frame(f)?;
        let s=&p.signature;
        let arena_scores:Vec<_>=p.arena_anchors.iter().zip(&self.arena_reference).map(|(r,reference)|
            compare(reference,&signature(f,*r,s),s.change_threshold)).collect();
        let matched=arena_scores.iter().all(|a|a.rgb_mae<=s.arena_max_mae && a.changed_fraction<=s.arena_max_changed_fraction);
        let markers=detect(f,p.scan_rect,&p.bars)?;
        let mut bench=Vec::new();
        for i in 0..9 {
            let rect=p.bench_rect(i);
            let hints:Vec<usize>=if matched {markers.iter().filter(|m|rect.overlaps(m.rect)).map(|m|m.id).collect()}else{vec![]};
            let score=if matched {self.bench_reference.as_ref().map(|r|compare(&r[i],&signature(f,rect,s),s.change_threshold))}else{None};
            let empty_match=score.as_ref().is_some_and(|a|a.rgb_mae<=s.empty_max_mae && a.changed_fraction<=s.empty_max_changed_fraction);
            let evidence=if !matched {"projection_unavailable"}
                else if hints.len()>1 || (empty_match && !hints.is_empty()) {"ambiguous"}
                else if !hints.is_empty() {"bar_candidate"}
                else if empty_match {"empty_reference_match"}else{"unknown"};
            bench.push(BenchRead{slot:i,rect,ground_pixel:[p.bench_centers[i],p.bench_y],evidence:evidence.into(),
                empty_signature:score,marker_candidates:hints,unit_id:None,occupancy:None});
        }
        let board=p.geometry().cells.into_iter().map(|c|CellRead {row:c.position.row,col:c.position.col,
            screen:[c.center.x*f.width as f32,c.center.y*f.height as f32],occupancy:None}).collect();
        Ok(SceneRead{timestamp_ms:f.captured_at_ms,profile:p.id.clone(),projection_status:if matched {"reference_arena_match"}else{"unresolved"}.into(),
            reference_basis:if self.bench_reference.is_some() {"manual_frame"}else{"packaged_arena_anchors"}.into(),
            arena_scores,markers,bench,board,phase:None,perspective:None,error:None})
    }
}
