use super::*;
use agente_tft_capture_core::{FrameEnvelope,PixelFormat};
use crate::profile::{Rect,rgb,signature};
fn profile()->Profile {serde_json::from_str(include_str!("../../../../configs/ui/match001-board-bench-v1.json")).unwrap()}
fn frame()->FrameEnvelope {FrameEnvelope {frame_id:1,captured_at_ms:250,width:1920,height:1080,
    stride_bytes:7680,pixel_format:PixelFormat::Rgba8,source_id:"synthetic".into(),pixels:vec![0;1920*1080*4]}}
fn paint(f:&mut FrameEnvelope,r:Rect,color:[u8;3]) {
    for y in r.y..r.y+r.height {for x in r.x..r.x+r.width {
        let i=(y*f.stride_bytes+x*4) as usize;f.pixels[i..i+3].copy_from_slice(&color);
    }}
}
fn reference()->FrameEnvelope {
    let mut f=frame();let p=profile();
    for r in &p.arena_anchors {
        paint(&mut f,*r,[40,60,80]);
        paint(&mut f,Rect{width:r.width/2,..*r},[100,140,190]);
    }
    f
}
fn bar(f:&mut FrameEnvelope,x:u32,y:u32,color:[u8;3]) {paint(f,Rect{x,y,width:64,height:4},color);}
#[test] fn stable_topology_and_ui_are_separate() {
    let p=profile();p.validate().unwrap();assert_eq!(p.geometry().cells.len(),28);assert_eq!(p.bench_centers.len(),9);
    let center=p.geometry().cells[0].center;assert!((center.x*1920.0-560.0).abs()<0.01);
}
#[test] fn profile_rejects_overlap_bad_counts_and_resolution() {
    let mut p=profile();p.bench_centers[1]=p.bench_centers[0];assert!(p.validate().is_err());
    let mut p=profile();p.board_rows.reverse();assert!(p.validate().is_err());
    let mut p=profile();p.arena_anchors[0].x=u32::MAX;assert!(p.validate().is_err());
    assert!(profile().validate_frame(&FrameEnvelope{width:1280,..frame()}).is_err());
}
#[test] fn profile_rejects_unknown_fields_and_relaxed_thresholds() {
    let mut v:Value=serde_json::from_str(include_str!("../../../../configs/ui/match001-board-bench-v1.json")).unwrap();
    v["champions"]=json!(["invented"]);assert!(serde_json::from_value::<Profile>(v).is_err());
    let mut p=profile();p.signature.empty_max_changed_fraction=0.9;assert!(p.validate().is_err());
}
#[test] fn green_red_markers_not_blue_tactician_bars() {
    let p=profile();let mut f=frame();bar(&mut f,550,350,[25,220,25]);bar(&mut f,750,350,[220,20,20]);bar(&mut f,950,350,[20,20,220]);
    let b=bars::detect(&f,p.scan_rect,&p.bars).unwrap();assert_eq!(b.len(),2);
    assert!(b.iter().all(|b|b.unit_id.is_none() && b.ground_point.is_none() && b.board_cell.is_none()));
}
#[test] fn green_body_or_button_is_not_a_thin_bar() {
    let p=profile();let mut f=frame();paint(&mut f,Rect{x:700,y:300,width:64,height:16},[25,220,25]);
    assert!(bars::detect(&f,p.scan_rect,&p.bars).unwrap().is_empty());
}
#[test] fn dark_tick_gaps_do_not_split_a_single_marker() {
    let p=profile();let mut f=frame();bar(&mut f,600,300,[20,220,20]);
    for x in [612,624,636,648] {paint(&mut f,Rect{x,y:300,width:1,height:4},[0,0,0]);}
    assert_eq!(bars::detect(&f,p.scan_rect,&p.bars).unwrap().len(),1);
}
#[test] fn black_borders_are_required() {
    let p=profile();let mut f=frame();paint(&mut f,Rect{x:595,y:295,width:80,height:15},[180,180,180]);bar(&mut f,600,300,[20,220,20]);
    assert!(bars::detect(&f,p.scan_rect,&p.bars).unwrap().is_empty());
}
#[test] fn exceeded_budgets_never_return_partial_success() {
    let p=profile();let mut f=frame();bar(&mut f,550,350,[25,220,25]);bar(&mut f,750,350,[220,20,20]);
    let mut c=p.bars.clone();c.max_runs=1;assert!(bars::detect(&f,p.scan_rect,&c).is_err());
    c=p.bars.clone();c.max_candidates=1;assert!(bars::detect(&f,p.scan_rect,&c).is_err());
}
#[test] fn same_empty_appearance_is_not_asserted_occupancy() {
    let p=profile();let r=reference();let reader=SceneReader::new(p,&r).unwrap();let out=reader.read(&r).unwrap();
    assert_eq!(out.projection_status,"reference_arena_match");
    assert!(out.bench.iter().all(|b|b.evidence=="empty_reference_match" && b.occupancy.is_none()));
    assert!(out.board.iter().all(|c|c.occupancy.is_none()));assert!(out.phase.is_none() && out.perspective.is_none());
}
#[test] fn reference_difference_is_not_automatically_a_unit() {
    let p=profile();let r=reference();let reader=SceneReader::new(p.clone(),&r).unwrap();let mut f=r;
    paint(&mut f,p.bench_rect(3),[120,120,120]);let out=reader.read(&f).unwrap();
    assert_eq!(out.bench[3].evidence,"unknown");assert!(out.bench[3].unit_id.is_none());
}
#[test] fn marker_can_be_reported_without_naming_a_champion_or_using_body_center() {
    let p=profile();let r=reference();let reader=SceneReader::new(p,&r).unwrap();let mut f=r;
    bar(&mut f,385,694,[25,220,25]);let out=reader.read(&f).unwrap();
    assert_eq!(out.bench[0].evidence,"bar_candidate");assert!(out.bench[0].occupancy.is_none());
    assert_eq!(out.markers.len(),1);assert!(out.markers[0].ground_point.is_none());
}
#[test] fn two_markers_in_one_bench_box_remain_ambiguous() {
    let p=profile();let r=reference();let reader=SceneReader::new(p,&r).unwrap();let mut f=r;
    bar(&mut f,385,694,[25,220,25]);bar(&mut f,385,712,[25,220,25]);
    assert_eq!(reader.read(&f).unwrap().bench[0].evidence,"ambiguous");
}
#[test] fn foreign_or_hidden_arena_never_reuses_bench_emptiness() {
    let p=profile();let reader=SceneReader::new(p,&reference()).unwrap();let mut f=frame();bar(&mut f,385,694,[25,220,25]);
    let out=reader.read(&f).unwrap();assert_eq!(out.projection_status,"unresolved");
    assert!(out.bench.iter().all(|b|b.evidence=="projection_unavailable" && b.empty_signature.is_none()));
    assert_eq!(out.markers.len(),1);
}
#[test] fn flat_reference_and_truncated_frame_fail_closed() {
    assert!(SceneReader::new(profile(),&frame()).is_err());
    let mut f=reference();f.pixels.truncate(3);assert!(SceneReader::new(profile(),&f).is_err());
}
#[test] fn pixel_formats_and_stride_agree() {
    let p=profile();let f=reference();let a=signature(&f,p.arena_anchors[0],&p.signature);
    let mut b=f.clone();for c in b.pixels.chunks_exact_mut(4) {c.swap(0,2);}b.pixel_format=PixelFormat::Bgra8;
    assert_eq!(a,signature(&b,p.arena_anchors[0],&p.signature));
    let mut c=f.clone();c.pixel_format=PixelFormat::Rgb8;c.stride_bytes=1920*3+7;c.pixels.clear();
    for row in f.pixels.chunks_exact(7680) {for px in row.chunks_exact(4) {c.pixels.extend_from_slice(&px[..3]);}c.pixels.extend([99;7]);}
    c.validate().unwrap();assert_eq!(a,signature(&c,p.arena_anchors[0],&p.signature));assert_eq!(rgb(&f,540,150),rgb(&c,540,150));
}
#[test] fn labels_do_not_enter_frame_plan() {
    let root=Path::new(".");let a=json!({"frames":[{"image":"a.jpg","timestamp_ms":0,"units":["A"]}]});
    let b=json!({"frames":[{"image":"a.jpg","timestamp_ms":0,"units":["B"],"suggestions":{"bench":9}}]});
    assert_eq!(plan(&a,root).unwrap(),plan(&b,root).unwrap());
    assert!(plan(&json!({"frames":[{"image":"a.jpg","timestamp_ms":1},{"image":"b.jpg","timestamp_ms":1}]}),root).is_err());
}
