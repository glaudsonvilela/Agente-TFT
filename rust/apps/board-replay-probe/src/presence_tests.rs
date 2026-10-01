use super::*;
use crate::{foreground,scene::SceneReader};
use agente_tft_capture_core::PixelFormat;
use serde_json::{json,Value};
fn base()->Profile {serde_json::from_str(include_str!("../../../../configs/ui/match001-board-bench-v1.json")).unwrap()}
fn policy()->PresenceProfile {serde_json::from_str(include_str!("../../../../configs/ui/match001-bench-presence-v1.json")).unwrap()}
fn paint(f:&mut FrameEnvelope,r:Rect,color:[u8;3]) {
    for y in r.y..r.y+r.height {for x in r.x..r.x+r.width {
        let i=(y*f.stride_bytes+x*4) as usize;f.pixels[i..i+3].copy_from_slice(&color);
    }}
}
fn texture(f:&mut FrameEnvelope,r:Rect) {
    for y in r.y..r.y+r.height {for x in r.x..r.x+r.width {
        let v=if (x/4+y/4)%2==0 {35}else{70};
        paint(f,Rect{x,y,width:1,height:1},[v,v+5,v+10]);
    }}
}
fn reference()->FrameEnvelope {
    let b=base();let p=policy();
    let mut f=FrameEnvelope{frame_id:1,captured_at_ms:250,width:1920,height:1080,stride_bytes:7680,
        pixel_format:PixelFormat::Rgba8,source_id:"test".into(),pixels:vec![0;1920*1080*4]};
    for r in b.arena_anchors.iter().chain(p.surface_anchors.iter()) {texture(&mut f,*r);}
    for i in 0..9 {texture(&mut f,p.crop(&b,i));}
    f
}
fn read(f:&FrameEnvelope)->PresenceRead {
    let r=reference();let b=base();let p=policy();
    let legacy=SceneReader::new(b.clone(),&r).unwrap().read(f).unwrap();
    PresenceReader::new(b,p,&r).unwrap().read(f,&legacy).unwrap()
}
fn marker(f:&mut FrameEnvelope,x:u32) {paint(f,Rect{x,y:694,width:64,height:4},[20,220,20]);}
fn body(f:&mut FrameEnvelope) {paint(f,Rect{x:395,y:728,width:26,height:69},[180,180,180]);}
#[test] fn empty_texture_is_an_image_level_hypothesis_not_identity() {
    let out=read(&reference());assert!(out.slots.iter().all(|r|r.status=="empty_visual" && r.occupancy==Some(false)));
    assert!(out.slots.iter().all(|r|r.unit_id.is_none() && r.ground_point.is_none()));
    assert!(!out.temporal_confirmation && !out.ownership_established);
}
#[test] fn occupied_requires_joint_bar_body_and_lower_support() {
    let mut f=reference();marker(&mut f,385);body(&mut f);
    let r=read(&f);assert_eq!(r.slots[0].occupancy,Some(true));assert_eq!(r.slots[0].status,"occupied_visual");
    assert!(r.slots[0].unit_id.is_none() && r.slots[0].ground_point.is_none());
}
#[test] fn body_without_bar_never_becomes_a_unit() {
    let mut f=reference();body(&mut f);let r=read(&f);assert_eq!(r.slots[0].occupancy,None);
}
#[test] fn bar_without_body_remains_ambiguous() {
    let mut f=reference();marker(&mut f,385);let r=read(&f);
    assert_eq!(r.slots[0].occupancy,None);assert_eq!(r.slots[0].status,"ambiguous");
}
#[test] fn disconnected_or_short_body_does_not_establish_support() {
    let mut f=reference();marker(&mut f,385);paint(&mut f,Rect{x:395,y:728,width:26,height:25},[180,180,180]);
    assert_eq!(read(&f).slots[0].occupancy,None);
}
#[test] fn multiple_bars_never_select_the_most_confident_one() {
    let mut f=reference();marker(&mut f,385);paint(&mut f,Rect{x:385,y:703,width:64,height:4},[20,220,20]);body(&mut f);
    assert_eq!(read(&f).slots[0].status,"ambiguous");
}
#[test] fn broad_overlay_or_clipped_body_abstains() {
    let mut f=reference();marker(&mut f,385);paint(&mut f,policy().crop(&base(),0),[150,150,150]);
    assert_eq!(read(&f).slots[0].occupancy,None);
}
#[test] fn local_structure_is_separate_from_decorative_arena_matching() {
    let mut f=reference();for r in base().arena_anchors {paint(&mut f,r,[0,0,0]);}
    let r=read(&f);assert_eq!(r.surface_status,"bench_structure_match");
    assert!(r.slots.iter().all(|s|s.occupancy==Some(false)));
}
#[test] fn both_failed_gates_prevent_using_the_empty_reference() {
    let mut f=reference();for r in base().arena_anchors.iter().chain(policy().surface_anchors.iter()) {paint(&mut f,*r,[0,0,0]);}
    let r=read(&f);assert_eq!(r.surface_status,"unresolved");
    assert!(r.slots.iter().all(|s|s.status=="unavailable" && s.appearance.is_none() && s.occupancy.is_none()));
}
#[test] fn bounded_uniform_lighting_change_preserves_shape() {
    let mut f=reference();for px in f.pixels.chunks_exact_mut(4) {for v in &mut px[..3] {*v=v.saturating_add(10);}}
    let r=read(&f);assert_eq!(r.surface_status,"bench_structure_match");
    assert!(r.slots.iter().all(|s|s.status=="empty_visual"));
}
#[test] fn huge_color_offset_is_not_silently_normalized() {
    let mut f=reference();for px in f.pixels.chunks_exact_mut(4) {for v in &mut px[..3] {*v=v.saturating_add(80);}}
    assert_eq!(read(&f).surface_status,"unresolved");
}
#[test] fn flat_patch_cannot_prove_empty_after_offset_fitting() {
    let (s,_)=foreground::compare(&vec![[60;3];100],&vec![[60;3];100],32).unwrap();
    assert!(!policy().empty_ok(&s));assert_eq!(s.correlation,-1.0);
}
#[test] fn component_budget_cannot_return_partial_success() {
    let mask=vec![true,false,false,true,false,false,true,false,false];
    assert!(foreground::components(&mask,Rect{x:0,y:0,width:9,height:1},2).is_err());
    assert!(foreground::compare(&[[0;3]],&[],32).is_err());
}
#[test] fn legacy_read_is_identical_and_not_mutated_by_presence() {
    let b=base();let r=reference();let mut f=r.clone();marker(&mut f,385);body(&mut f);
    let legacy=SceneReader::new(b.clone(),&r).unwrap().read(&f).unwrap();let before=serde_json::to_value(&legacy).unwrap();
    PresenceReader::new(b,policy(),&r).unwrap().read(&f,&legacy).unwrap();
    assert_eq!(before,serde_json::to_value(&legacy).unwrap());
    assert!(legacy.board.iter().all(|c|c.occupancy.is_none()));
}
#[test] fn timestamp_mismatch_cannot_pair_different_frames() {
    let b=base();let r=reference();let mut legacy=SceneReader::new(b.clone(),&r).unwrap().read(&r).unwrap();
    legacy.timestamp_ms+=1;assert!(PresenceReader::new(b,policy(),&r).unwrap().read(&r,&legacy).is_err());
}
#[test] fn pixel_format_and_row_padding_do_not_change_presence() {
    let f=reference();let mut b=f.clone();for p in b.pixels.chunks_exact_mut(4) {p.swap(0,2);}b.pixel_format=PixelFormat::Bgra8;
    assert_eq!(serde_json::to_value(read(&f)).unwrap(),serde_json::to_value(read(&b)).unwrap());
}
#[test] fn profiles_reject_unknown_rules_invalid_geometry_and_looser_thresholds() {
    let mut v:Value=serde_json::from_str(include_str!("../../../../configs/ui/match001-bench-presence-v1.json")).unwrap();
    v["expected_occupancy"]=json!([true]);assert!(serde_json::from_value::<PresenceProfile>(v).is_err());
    let mut p=policy();p.empty_min_correlation=0.5;assert!(p.validate(&base()).is_err());
    let mut p=policy();p.body_width=128;assert!(p.validate(&base()).is_err());
    let mut p=policy();p.max_components=0;assert!(p.validate(&base()).is_err());
}
