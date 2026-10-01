//! Bounded structural marker proposals. Color is not ownership; length is not HP.
use agente_tft_capture_core::FrameEnvelope;
use serde::{Deserialize,Serialize};
use crate::profile::{rgb,Rect};

#[derive(Debug,Clone,Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BarPolicy {
    pub min_width:u32,pub max_width:u32,pub min_height:u32,pub max_height:u32,pub max_gap:u32,
    pub min_fill_fraction:f32,pub min_border_fraction:f32,pub dark_max:u8,pub min_channel:u8,
    pub green_margin:u8,pub red_margin:u8,pub max_runs:usize,pub max_candidates:usize,
}
impl BarPolicy {
    pub fn validate(&self)->Result<(),String> {
        if self.min_width<8 || self.min_width>self.max_width || self.max_width>128
            || self.min_height<2 || self.min_height>self.max_height || self.max_height>10 || self.max_gap>2
            || !self.min_fill_fraction.is_finite() || !(0.75..=1.0).contains(&self.min_fill_fraction)
            || !self.min_border_fraction.is_finite() || !(0.75..=1.0).contains(&self.min_border_fraction)
            || self.dark_max>100 || self.min_channel<60 || self.green_margin<15 || self.red_margin<15
            || self.max_runs==0 || self.max_runs>8192 || self.max_candidates==0 || self.max_candidates>128 {
            return Err("invalid bar detector limits".into());
        }
        Ok(())
    }
}
#[derive(Debug,Clone,Serialize)]
pub struct Marker {
    pub id:usize,pub rect:Rect,pub color:String,pub border_fraction:f32,
    pub unit_id:Option<String>,pub ground_point:Option<[f32;2]>,pub board_cell:Option<[u8;2]>,
}
fn colored(p:[u8;3],red:bool,c:&BarPolicy)->bool {
    let [r,g,b]=p.map(i16::from);
    if red {r>=i16::from(c.min_channel) && r-g>=i16::from(c.red_margin) && r-b>=i16::from(c.red_margin)}
    else {g>=i16::from(c.min_channel) && g-r>=i16::from(c.green_margin) && g-b>=i16::from(c.green_margin)}
}
fn border(pixels:&[[u8;3]],w:u32,y:u32,x:u32,len:u32,dark:u8)->f32 {
    let n=(x..x+len).filter(|xx|pixels[(y*w+xx) as usize].iter().all(|v|*v<=dark)).count();
    n as f32/len as f32
}
pub fn detect(f:&FrameEnvelope,r:Rect,c:&BarPolicy)->Result<Vec<Marker>,String> {
    c.validate()?;f.validate().map_err(|e|e.to_string())?;
    if !r.valid(f.width,f.height) || u64::from(r.width)*u64::from(r.height)>2_000_000 {
        return Err("invalid marker scan region".into());
    }
    let mut pixels=Vec::with_capacity((r.width*r.height) as usize);
    for y in r.y..r.y+r.height {for x in r.x..r.x+r.width {pixels.push(rgb(f,x,y));}}
    let mut result=Vec::new();let mut total_runs=0usize;
    for red in [false,true] {
        let mut groups:Vec<Rect>=Vec::new();
        let mut active:Vec<usize>=Vec::new();
        for y in 0..r.height {
            let xs:Vec<u32>=(0..r.width).filter(|x|colored(pixels[(y*r.width+x) as usize],red,c)).collect();
            let mut runs=Vec::new();let mut i=0;
            while i<xs.len() {
                let start=i;i+=1;
                while i<xs.len() && xs[i]-xs[i-1]<=c.max_gap+1 {i+=1;}
                let width=xs[i-1]-xs[start]+1;
                if width>=c.min_width && width<=c.max_width && (i-start) as f32/width as f32>=c.min_fill_fraction {
                    runs.push(Rect{x:xs[start],y,width,height:1});
                }
            }
            total_runs+=runs.len();
            if total_runs>c.max_runs {return Err("bar scan run budget exceeded; no partial success".into());}
            let mut next=Vec::new();
            for run in runs {
                let compatible:Vec<usize>=active.iter().copied().filter(|&j| {
                    let g=groups[j];g.y+g.height==y && g.x.abs_diff(run.x)<=3
                        && (g.x+g.width).abs_diff(run.x+run.width)<=3 && !next.contains(&j)
                }).collect();
                if compatible.len()==1 {
                    let j=compatible[0];let g=&mut groups[j];let end=(g.x+g.width).max(run.x+run.width);
                    g.x=g.x.min(run.x);g.width=end-g.x;g.height+=1;next.push(j);
                } else {next.push(groups.len());groups.push(run);}
            }
            active=next;
        }
        for b in groups {
            if b.height<c.min_height || b.height>c.max_height || b.width>c.max_width
                || b.width<4*b.height || b.y<3 || b.y+b.height+3>r.height {continue;}
            let top=(b.y-3..b.y).map(|y|border(&pixels,r.width,y,b.x,b.width,c.dark_max)).fold(0.0,f32::max);
            let bottom=(b.y+b.height..b.y+b.height+3).map(|y|border(&pixels,r.width,y,b.x,b.width,c.dark_max)).fold(0.0,f32::max);
            let quality=top.min(bottom);
            if quality<c.min_border_fraction {continue;}
            if result.len()>=c.max_candidates {return Err("bar candidate budget exceeded; no partial success".into());}
            result.push(Marker{id:0,rect:Rect{x:b.x+r.x,y:b.y+r.y,width:b.width,height:b.height},
                color:if red {"red"}else{"green"}.into(),border_fraction:quality,
                unit_id:None,ground_point:None,board_cell:None});
        }
    }
    result.sort_by_key(|m|(m.rect.y,m.rect.x,m.color.clone()));
    for (id,m) in result.iter_mut().enumerate() {m.id=id;}
    Ok(result)
}
