//! UI projection and appearance seeds; no champion vocabulary or combat rules.
use agente_tft_capture_core::{FrameEnvelope, PixelFormat, PixelRect};
use agente_tft_contracts::HexPosition;
use agente_tft_perception_board::{BoardCell, BoardGeometry, NormalizedPoint};
use serde::{Deserialize, Serialize};
use crate::bars::BarPolicy;

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Rect { pub x:u32, pub y:u32, pub width:u32, pub height:u32 }
impl Rect {
    pub fn valid(self, w:u32,h:u32)->bool {
        self.width>0 && self.height>0 && self.x.checked_add(self.width).is_some_and(|x|x<=w)
            && self.y.checked_add(self.height).is_some_and(|y|y<=h)
    }
    pub fn overlaps(self, b:Self)->bool {
        u64::from(self.x)<u64::from(b.x)+u64::from(b.width)
            && u64::from(b.x)<u64::from(self.x)+u64::from(self.width)
            && u64::from(self.y)<u64::from(b.y)+u64::from(b.height)
            && u64::from(b.y)<u64::from(self.y)+u64::from(self.height)
    }
}
impl From<Rect> for PixelRect {
    fn from(r:Rect)->Self { Self{x:r.x,y:r.y,width:r.width,height:r.height} }
}
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Source {pub image:String,pub sha256:String,pub role:String}
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SignaturePolicy {
    pub grid_width:u32,pub grid_height:u32,pub arena_max_mae:f32,
    pub arena_max_changed_fraction:f32,pub empty_max_mae:f32,
    pub empty_max_changed_fraction:f32,pub change_threshold:u8,
}
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Profile {
    pub schema_version:u32,pub id:String,pub board_topology_id:String,pub bench_topology_id:String,
    pub reference_width:u32,pub reference_height:u32,pub reference_image:String,pub reference_sha256:String,
    pub geometry_source:Source,pub board_rows:Vec<[u32;3]>,pub bench_centers:Vec<u32>,pub bench_y:u32,
    pub bench_crop_y:u32,pub bench_crop_width:u32,pub bench_crop_height:u32,
    pub arena_anchors:Vec<Rect>,pub scan_rect:Rect,pub signature:SignaturePolicy,pub bars:BarPolicy,pub note:String,
}
fn sha_shape(s:&str)->bool {s.len()==64 && s.bytes().all(|c|c.is_ascii_hexdigit())}
impl Profile {
    pub fn validate(&self)->Result<(),String> {
        let (w,h)=(self.reference_width,self.reference_height);
        if self.schema_version!=1 || self.id.trim().is_empty() || self.id.len()>100
            || self.board_topology_id!="board-standard-4x7-v1" || self.bench_topology_id!="bench-nine-v1"
            || w==0 || h==0 || w>8192 || h>8192 || self.board_rows.len()!=4 || self.bench_centers.len()!=9
            || self.arena_anchors.len()!=2 || !self.scan_rect.valid(w,h)
            || u64::from(self.scan_rect.width)*u64::from(self.scan_rect.height)>2_000_000
            || self.scan_rect.height<10 || self.bench_crop_width<8 || self.bench_crop_width>256
            || self.bench_crop_height<8 || self.bench_crop_height>256 || self.bench_y>=h
            || !sha_shape(&self.reference_sha256) || !sha_shape(&self.geometry_source.sha256)
            || self.geometry_source.role!="visible_grid_development_seed_not_independent_validation"
            || self.reference_image.trim().is_empty() || self.geometry_source.image.trim().is_empty()
            || self.note.len()>1024 {return Err("invalid spatial profile identity/geometry/budgets".into());}
        let mut last_y=0;
        for [left,right,y] in &self.board_rows {
            if left>=right || *right>=w || *y<=last_y || *y>=h {return Err("invalid board row projection".into());}
            last_y=*y;
        }
        for (i,&x) in self.bench_centers.iter().enumerate() {
            if x<self.bench_crop_width/2 || !self.bench_rect(i).valid(w,h)
                || (i>0 && self.bench_centers[i-1]+self.bench_crop_width>=x) {
                return Err("invalid or overlapping bench columns".into());
            }
        }
        for r in &self.arena_anchors {
            if !r.valid(w,h) || r.width>256 || r.height>256
                || (0..9).any(|i|r.overlaps(self.bench_rect(i))) {
                return Err("invalid arena anchor".into());
            }
        }
        if self.arena_anchors[0].overlaps(self.arena_anchors[1]) {return Err("arena anchors overlap".into());}
        let s=&self.signature;
        if !(8..=64).contains(&s.grid_width) || !(8..=64).contains(&s.grid_height)
            || !s.arena_max_mae.is_finite() || !(0.0..=12.0).contains(&s.arena_max_mae)
            || !s.empty_max_mae.is_finite() || !(0.0..=8.0).contains(&s.empty_max_mae)
            || !s.arena_max_changed_fraction.is_finite() || !(0.0..=0.25).contains(&s.arena_max_changed_fraction)
            || !s.empty_max_changed_fraction.is_finite() || !(0.0..=0.05).contains(&s.empty_max_changed_fraction)
            || !(1..=32).contains(&s.change_threshold) {return Err("invalid signature limits".into());}
        self.bars.validate()?;
        self.geometry().validate().map_err(|e|e.to_string())
    }
    pub fn bench_rect(&self,i:usize)->Rect {
        Rect{x:self.bench_centers[i].saturating_sub(self.bench_crop_width/2),y:self.bench_crop_y,
            width:self.bench_crop_width,height:self.bench_crop_height}
    }
    pub fn geometry(&self)->BoardGeometry {
        let mut cells=Vec::new();
        for (row,[left,right,y]) in self.board_rows.iter().enumerate() {
            for col in 0..7 {
                let x=*left as f32+(*right-*left) as f32*col as f32/6.0;
                cells.push(BoardCell{position:HexPosition{row:row as u8,col:col as u8},
                    center:NormalizedPoint{x:x/self.reference_width as f32,y:*y as f32/self.reference_height as f32}});
            }
        }
        BoardGeometry{schema_version:1,name:self.id.clone(),reference_width:self.reference_width,
            reference_height:self.reference_height,max_assignment_distance:0.025,cells}
    }
    pub fn validate_frame(&self,f:&FrameEnvelope)->Result<(),String> {
        f.validate().map_err(|e|e.to_string())?;
        if (f.width,f.height)!=(self.reference_width,self.reference_height) {
            return Err("spatial projection resolution mismatch; no implicit scaling".into());
        }
        Ok(())
    }
}
/// Call only on a validated frame and in-bounds coordinates.
pub fn rgb(f:&FrameEnvelope,x:u32,y:u32)->[u8;3] {
    let i=y as usize*f.stride_bytes as usize+x as usize*f.pixel_format.bytes_per_pixel();
    let p=&f.pixels[i..i+3];
    match f.pixel_format {PixelFormat::Bgra8=>[p[2],p[1],p[0]],_=>[p[0],p[1],p[2]]}
}
pub fn signature(f:&FrameEnvelope,r:Rect,p:&SignaturePolicy)->Vec<[u8;3]> {
    let mut result=Vec::with_capacity((p.grid_width*p.grid_height) as usize);
    for y in 0..p.grid_height {for x in 0..p.grid_width {
        result.push(rgb(f,r.x+(2*x+1)*r.width/(2*p.grid_width),r.y+(2*y+1)*r.height/(2*p.grid_height)));
    }}
    result
}
#[derive(Debug, Clone, Serialize)]
pub struct SignatureScore {pub rgb_mae:f32,pub changed_fraction:f32}
pub fn compare(a:&[[u8;3]],b:&[[u8;3]],limit:u8)->SignatureScore {
    let mut sum=0u64;let mut changed=0usize;
    for (x,y) in a.iter().zip(b) {
        let d=[x[0].abs_diff(y[0]),x[1].abs_diff(y[1]),x[2].abs_diff(y[2])];
        sum+=d.iter().map(|v|u64::from(*v)).sum::<u64>();
        changed+=usize::from(d.into_iter().any(|v|v>limit));
    }
    SignatureScore{rgb_mae:sum as f32/(a.len()*3) as f32,changed_fraction:changed as f32/a.len() as f32}
}
