//! Fast, geometry-only continuity for visible health bars.
//! A track ID is not a champion identity or proof of board ownership.
use crate::{bars::Marker,profile::{rgb,Rect}};
use agente_tft_capture_core::FrameEnvelope;
use serde::Serialize;

#[derive(Clone)]
struct Previous {id:u64,rect:Rect,color:String,last_ms:u64}

#[derive(Debug,Serialize)]
pub struct TrackedBar {
    pub track_id:u64,pub source_marker_id:usize,pub rect:Rect,pub color:String,
    pub border_fraction:f32,pub ownership_verified:bool,
    /// Search region under a Little Legend status bar, not a segmented sprite.
    pub avatar_body_proposal:Option<Rect>,
}

#[derive(Default)]
pub struct FastMarkerTrack {
    epoch:Option<u64>,last_ms:Option<u64>,next_id:u64,previous:Vec<Previous>,
}

fn center(rect:Rect)->(i64,i64){
    (i64::from(rect.x)+i64::from(rect.width)/2,
     i64::from(rect.y)+i64::from(rect.height)/2)
}

impl FastMarkerTrack {
    pub fn update(&mut self,markers:&[Marker],epoch:u64,at:u64)->Vec<TrackedBar>{
        if self.epoch!=Some(epoch) || self.last_ms.is_some_and(|last|at<last){
            self.previous.clear();
        }
        self.epoch=Some(epoch);
        self.last_ms=Some(at);
        self.previous.retain(|track|at.saturating_sub(track.last_ms)<=1500);
        let mut possible=Vec::new();
        for (i,marker) in markers.iter().enumerate(){
            let (x,y)=center(marker.rect);
            for (j,track) in self.previous.iter().enumerate(){
                if track.color!=marker.color {continue;}
                let (old_x,old_y)=center(track.rect);
                let distance=(x-old_x).pow(2)+(y-old_y).pow(2);
                // Little Legends can dash across the arena between 250 ms
                // observations. Their bar has a distinctive color and can
                // tolerate more motion than a unit bar without joining teams.
                let limit:i64=if marker.color=="purple" {160} else {80};
                if distance<=limit*limit {possible.push((distance,i,j));}
            }
        }
        possible.sort_unstable();
        let mut assigned=vec![None;markers.len()];
        let mut used=vec![false;self.previous.len()];
        for (_,i,j) in possible {
            if assigned[i].is_none() && !used[j] {
                assigned[i]=Some(self.previous[j].id);
                used[j]=true;
            }
        }
        let mut result=Vec::with_capacity(markers.len());
        for (i,marker) in markers.iter().enumerate(){
            let id=assigned[i].unwrap_or_else(||{
                self.next_id+=1;
                self.next_id
            });
            result.push(TrackedBar{track_id:id,source_marker_id:marker.id,
                rect:marker.rect,color:marker.color.clone(),
                border_fraction:marker.border_fraction,ownership_verified:false,
                avatar_body_proposal:(marker.color=="purple").then(||{
                    let body_width=marker.rect.width.saturating_mul(9)/5;
                    Rect{x:marker.rect.x.saturating_sub((body_width-marker.rect.width)/2),
                         y:marker.rect.y+marker.rect.height+
                           marker.rect.width.saturating_mul(6)/5,
                         width:body_width,height:body_width}
                })});
        }
        let mut next:Vec<Previous>=self.previous.iter().enumerate()
            .filter(|(index,_)|!used[*index]).map(|(_,row)|row.clone()).collect();
        next.extend(result.iter().map(|row|Previous{id:row.track_id,rect:row.rect,
            color:row.color.clone(),last_ms:at}));
        self.previous=next;
        result
    }
}

/// A vivid purple status bar near the arena is a Little Legend proposal.
/// It does not establish which player's avatar is present.
pub fn detect_avatar_bars(frame:&FrameEnvelope,scan:Rect)->Vec<Marker>{
    if !scan.valid(frame.width,frame.height){return Vec::new();}
    #[derive(Clone)] struct Group{x:u32,y:u32,end_x:u32,last_y:u32}
    let mut groups:Vec<Group>=Vec::new();
    for y in scan.y..scan.y+scan.height {
        let mut x=scan.x;
        while x<scan.x+scan.width {
            let [red,green,blue]=rgb(frame,x,y);
            if !(red>=135 && blue>=145 && green<=90 &&
                 red.saturating_sub(green)>=65 && blue.saturating_sub(green)>=80 &&
                 red.abs_diff(blue)<=100) {x+=1;continue;}
            let start=x;
            x+=1;
            while x<scan.x+scan.width {
                let [red,green,blue]=rgb(frame,x,y);
                if !(red>=135 && blue>=145 && green<=90 &&
                     red.saturating_sub(green)>=65 && blue.saturating_sub(green)>=80 &&
                     red.abs_diff(blue)<=100) {break;}
                x+=1;
            }
            let width=x-start;
            if !(30..=65).contains(&width){continue;}
            if let Some(group)=groups.iter_mut().rev().find(|group|
                    group.last_y+1==y && group.x.abs_diff(start)<=5 &&
                    group.end_x.abs_diff(x)<=5) {
                group.last_y=y;
                group.x=group.x.min(start);
                group.end_x=group.end_x.max(x);
            }else if groups.len()<4096 {
                groups.push(Group{x:start,y,end_x:x,last_y:y});
            }
        }
    }
    let mut result=Vec::new();
    for group in groups {
        let height=group.last_y-group.y+1;
        if !(5..=18).contains(&height) || group.y<scan.y+2 {continue;}
        let width=group.end_x-group.x;
        // The live bar has a one or two pixel colored rim below its dark
        // outline. JPEG video can add another row. Search only immediately
        // above the fill rather than assuming the adjacent row is black.
        let dark=(group.y.saturating_sub(3)..group.y)
            .map(|border_y|(group.x..group.end_x).filter(|x|{
                let pixel=rgb(frame,*x,border_y);
                pixel.iter().all(|channel|*channel<=50)
            }).count())
            .max().unwrap_or(0);
        if dark*5<width as usize*3 {continue;}
        result.push(Marker{id:1000+result.len(),rect:Rect{x:group.x,y:group.y,width,height},
            color:"purple".into(),border_fraction:dark as f32/width as f32,
            unit_id:None,ground_point:None,board_cell:None});
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use agente_tft_capture_core::PixelFormat;
    fn marker(x:u32,color:&str)->Marker {
        Marker{id:0,rect:Rect{x,y:100,width:50,height:4},color:color.into(),
            border_fraction:0.95,unit_id:None,ground_point:None,board_cell:None}
    }
    #[test]
    fn keeps_track_across_motion_and_separates_bar_colors(){
        let mut tracker=FastMarkerTrack::default();
        let first=tracker.update(&[marker(100,"green"),marker(300,"red")],0,1000);
        let moved=tracker.update(&[marker(115,"green"),marker(285,"red")],0,1200);
        assert_eq!(first.iter().map(|row|row.track_id).collect::<Vec<_>>(),
                   moved.iter().map(|row|row.track_id).collect::<Vec<_>>());
        let other=tracker.update(&[marker(116,"red")],0,1400);
        assert_ne!(other[0].track_id,first[0].track_id);
        assert!(!other[0].ownership_verified);
    }
    #[test]
    fn expires_old_tracks_and_resets_on_epoch_change(){
        let mut tracker=FastMarkerTrack::default();
        let first=tracker.update(&[marker(100,"green")],0,1000)[0].track_id;
        let late=tracker.update(&[marker(100,"green")],0,2600)[0].track_id;
        let reset=tracker.update(&[marker(100,"green")],1,2700)[0].track_id;
        assert_ne!(first,late);
        assert_ne!(late,reset);
    }
    #[test]
    fn short_detection_gap_keeps_identity_without_inventing_a_visible_bar(){
        let mut tracker=FastMarkerTrack::default();
        let first=tracker.update(&[marker(100,"green")],0,1000)[0].track_id;
        assert!(tracker.update(&[],0,1200).is_empty());
        assert_eq!(tracker.update(&[marker(105,"green")],0,1300)[0].track_id,first);
    }
    #[test]
    fn avatar_dash_retains_track_but_unit_jump_does_not(){
        let mut tracker=FastMarkerTrack::default();
        let avatar=tracker.update(&[marker(100,"purple")],0,1000)[0].track_id;
        assert_eq!(tracker.update(&[marker(220,"purple")],0,1250)[0].track_id,avatar);
        let unit=tracker.update(&[marker(100,"green")],0,1500)[0].track_id;
        assert_ne!(tracker.update(&[marker(220,"green")],0,1750)[0].track_id,unit);
    }
    #[test]
    fn vivid_bordered_purple_bar_is_an_avatar_proposal_only(){
        let (width,height)=(200u32,200u32);
        let mut pixels=vec![0u8;(width*height*3) as usize];
        for y in 40..49 {for x in 65..107 {
            let offset=((y*width+x)*3) as usize;
            pixels[offset..offset+3].copy_from_slice(&[190,25,210]);
        }}
        let frame=FrameEnvelope{frame_id:1,captured_at_ms:1,width,height,
            stride_bytes:width*3,pixel_format:PixelFormat::Rgb8,
            source_id:"test".into(),pixels};
        let proposals=detect_avatar_bars(&frame,Rect{x:0,y:0,width,height});
        assert_eq!(proposals.len(),1);
        assert_eq!(proposals[0].color,"purple");
        assert_eq!(proposals[0].rect,Rect{x:65,y:40,width:42,height:9});
        let tracks=FastMarkerTrack::default().update(&proposals,0,1);
        assert_eq!(tracks[0].avatar_body_proposal,
                   Some(Rect{x:49,y:99,width:75,height:75}));
    }
    #[test]
    fn avatar_outline_may_be_two_pixels_above_jpeg_fill(){
        let (width,height)=(200u32,100u32);
        let mut pixels=vec![100u8;(width*height*3) as usize];
        for y in 40..49 {for x in 65..107 {
            let offset=((y*width+x)*3) as usize;
            pixels[offset..offset+3].copy_from_slice(&[190,25,210]);
        }}
        for x in 65..107 {
            let offset=((38*width+x)*3) as usize;
            pixels[offset..offset+3].copy_from_slice(&[21,5,32]);
        }
        let frame=FrameEnvelope{frame_id:1,captured_at_ms:1,width,height,
            stride_bytes:width*3,pixel_format:PixelFormat::Rgb8,
            source_id:"test".into(),pixels};
        assert_eq!(detect_avatar_bars(&frame,Rect{x:0,y:0,width,height}).len(),1);
    }
}
