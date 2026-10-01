use super::*;
use std::{cell::RefCell,collections::VecDeque};
use agente_tft_contracts::Confidence;
use agente_tft_image_preprocess::GrayImage;
use agente_tft_perception_hud::{RecognizedText,HudReadError};
fn profile()->BadgeProfile {
    serde_json::from_str(include_str!("../../../../configs/player-list/match001-self-badge-v1.json")).unwrap()
}
fn frame()->FrameEnvelope {
    FrameEnvelope{frame_id:1,captured_at_ms:100,width:1920,height:1080,stride_bytes:7680,
        pixel_format:PixelFormat::Rgba8,source_id:"fixture".into(),pixels:vec![0;1920*1080*4]}
}
fn paint(f:&mut FrameEnvelope,x:u32,y:u32,p:&BadgeProfile) {
    for [dx,dy] in &p.gold_points {
        let i=(y+dy) as usize*f.stride_bytes as usize+(x+dx) as usize*4;
        f.pixels[i..i+4].copy_from_slice(&[190,165,80,255]);
    }
}
struct Fake { values:VecDeque<(&'static str,f32)>,calls:usize,prepare:RefCell<Vec<HudField>> }
impl Fake {
    fn new(a:&[(&'static str,f32)])->Self {
        Self{values:a.iter().copied().collect(),calls:0,prepare:RefCell::new(vec![])}
    }
}
impl HudOcrEngine for Fake {
    fn prepare_roi(&self,f:HudField,_:&RoiFrame,_:HudPreprocessConfig)->Result<GrayImage,HudReadError> {
        self.prepare.borrow_mut().push(f);
        Ok(GrayImage{width:1,height:1,stride_bytes:1,pixels:vec![255]})
    }
    fn recognize(&mut self,f:HudField,_:&GrayImage)->Result<Option<RecognizedText>,String> {
        assert_eq!(f,HudField::Stage);self.calls+=1;
        Ok(self.values.pop_front().map(|(s,c)|RecognizedText{text:s.into(),confidence:Confidence::new(c).unwrap()}))
    }
}
fn read(values:&[(&'static str,f32)])->HpRead {
    let p=profile();let mut f=frame();paint(&mut f,1771,340,&p);
    read_player_hp(&mut Fake::new(values),&f,&p)
}
#[test]
fn signed_grammar_preserves_minus() {
    assert_eq!(parse_signed_hp("-7",300),Some(-7));
    assert_eq!(parse_signed_hp("100",300),Some(100));
    for s in ["7-","--7","7/10","301","-301","1-1","","hp7","+7"] {
        assert_eq!(parse_signed_hp(s,300),None,"invalid token {s}");
    }
}
#[test]
fn profile_rejects_bad_budget_and_duplicate_points() {
    let mut p=profile();p.max_raw_peaks=0;assert!(p.validate().is_err());
    let mut p=profile();p.gold_points.push(p.gold_points[0]);assert!(p.validate().is_err());
}
#[test]
fn marker_tracks_different_vertical_positions() {
    let p=profile();
    for y in [180,340,740] {
        let mut f=frame();paint(&mut f,1771,y,&p);
        let l=locate(&f,&p).unwrap();assert_eq!(l.candidates.len(),1);
        assert!(l.candidates[0].anchor.y.abs_diff(y)<=2);
    }
}
#[test]
fn two_markers_abstain_without_ocr() {
    let p=profile();let mut f=frame();paint(&mut f,1771,180,&p);paint(&mut f,1771,500,&p);
    let mut e=Fake::new(&[]);let r=read_player_hp(&mut e,&f,&p);
    assert_eq!(r.status,HpStatus::BadgeAmbiguous);assert_eq!(e.calls,0);
}
#[test]
fn hidden_marker_does_not_read_opponent() {
    let mut e=Fake::new(&[]);
    assert_eq!(read_player_hp(&mut e,&frame(),&profile()).status,HpStatus::BadgeNotFound);
    assert_eq!(e.calls,0);
}
#[test]
fn scale_agreement_accepts_and_negative_never_becomes_unsigned() {
    let p=read(&[("94",0.96),("94",0.91)]);assert_eq!(p.hp,Some(94));assert_eq!(p.confidence,Some(0.91));
    let n=read(&[("-7",0.96),("-7",0.95)]);
    assert_eq!(n.signed_hp,Some(-7));assert_eq!(n.hp,None);assert_eq!(n.status,HpStatus::NegativeDisplay);
}
#[test]
fn dropped_minus_conflict_abstains() {
    assert_eq!(read(&[("-7",0.95),("7",0.95)]).status,HpStatus::OcrConflict);
}
#[test]
fn one_low_confidence_scale_abstains() {
    assert_eq!(read(&[("44",0.28),("44",0.96)]).status,HpStatus::OcrUncertain);
}
#[test]
fn temporal_needs_distinct_frames_and_refreshes_time() {
    let mut t=HpTracker::new(750,1500).unwrap();let mut r=read(&[("94",0.95),("94",0.95)]);
    assert!(t.observe(&r).unwrap().current.is_none());assert!(t.observe(&r).is_err());
    r.frame_id=2;r.timestamp_ms=200;
    assert_eq!(t.observe(&r).unwrap().current.unwrap().observed_at_ms,200);
}
#[test]
fn sparse_frames_do_not_fake_temporal_confirmation() {
    let mut t=HpTracker::new(750,1500).unwrap();let mut r=read(&[("94",0.95),("94",0.95)]);
    t.observe(&r).unwrap();r.frame_id=2;r.timestamp_ms=50100;
    assert!(t.observe(&r).unwrap().current.is_none());
}
#[test]
fn missing_read_keeps_last_good_separate_and_stale() {
    let mut t=HpTracker::new(750,1500).unwrap();let mut r=read(&[("94",0.95),("94",0.95)]);
    t.observe(&r).unwrap();r.frame_id=2;r.timestamp_ms=200;t.observe(&r).unwrap();
    r.frame_id=3;r.timestamp_ms=2000;r.status=HpStatus::BadgeNotFound;r.hp=None;
    let s=t.observe(&r).unwrap();assert!(s.current.is_none());assert_eq!(s.last_good.unwrap().value,94);assert!(s.stale);
}
#[test]
fn rgba_bgra_rgb_and_stride_have_same_location() {
    let p=profile();let mut rgba=frame();paint(&mut rgba,1771,340,&p);
    let expected=locate(&rgba,&p).unwrap();
    let mut bgra=rgba.clone();bgra.pixel_format=PixelFormat::Bgra8;
    for c in bgra.pixels.chunks_exact_mut(4){c.swap(0,2);}
    assert_eq!(locate(&bgra,&p).unwrap(),expected);
    let mut rgb=rgba.clone();rgb.pixel_format=PixelFormat::Rgb8;rgb.stride_bytes=1920*3+7;rgb.pixels.clear();
    for row in rgba.pixels.chunks_exact(1920*4){for c in row.chunks_exact(4){rgb.pixels.extend_from_slice(&c[..3]);}rgb.pixels.extend([99;7]);}
    assert_eq!(locate(&rgb,&p).unwrap(),expected);
}
#[test]
fn resolution_mismatch_fails_before_ocr() {
    let p=profile();let mut f=frame();f.width=1280;
    let mut e=Fake::new(&[]);let r=read_player_hp(&mut e,&f,&p);
    assert_eq!(r.status,HpStatus::ReadError);assert!(r.error.is_some());assert_eq!(e.calls,0);
}
