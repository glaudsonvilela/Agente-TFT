use super::*;
use crate::controls::ControlsReader;
use crate::recovery::RecoveryProfile;
use agente_tft_capture_core::{PixelFormat, RoiFrame};
use agente_tft_perception_hud::{HudReadError, RecognizedText};

fn fixtures() -> (ScreenLayout, ControlsProfile, NumbersProfile, FrameEnvelope) {
    let layout:ScreenLayout=serde_json::from_str(include_str!("../../../../configs/ui/match001-desktop-1920x1080-ptbr-v1.json")).unwrap();
    let mut controls:ControlsProfile=serde_json::from_str(include_str!("../../../../configs/ui/match001-shop-controls-v1.json")).unwrap();
    controls.id="match001-shop-controls-v2".into();
    controls.controls[2].price_rect=Some(PixelRect{x:379,y:1040,width:25,height:27});
    controls.controls[2].free_count_rect=Some(PixelRect{x:465,y:1012,width:19,height:20});
    let policy=serde_json::from_str(include_str!("../../../../configs/ui/match001-shop-isolated-numbers-v1.json")).unwrap();
    let frame=FrameEnvelope{frame_id:1,captured_at_ms:100,width:1920,height:1080,stride_bytes:5760,
        pixel_format:PixelFormat::Rgb8,source_id:"fixture".into(),pixels:vec![0;1920*1080*3]};
    (layout,controls,policy,frame)
}
fn observation(layout:&ScreenLayout, controls:&ControlsProfile, frame:&FrameEnvelope, state:Option<&str>) -> ControlsRead {
    let recovery:RecoveryProfile=serde_json::from_str(include_str!("../../../../configs/ui/match001-shop-recovery-v2.json")).unwrap();
    let mut out=ControlsReader::new(controls.clone(),layout,&recovery).unwrap().read_visual(frame,true).unwrap();
    if let Some(state)=state {
        out.controls[1].status="observed".into();out.controls[1].appearance=Some("active_appearance".into());
        out.controls[2].status="observed".into();out.controls[2].appearance=Some(state.into());
    }
    out
}
struct Fake;
impl HudOcrEngine for Fake {
    fn prepare_roi(&self,_:HudField,r:&RoiFrame,_:HudPreprocessConfig)->Result<GrayImage,HudReadError> {
        Ok(GrayImage{width:r.rect.width,height:r.rect.height,stride_bytes:r.rect.width,
            pixels:r.pixels.chunks_exact(3).map(|p|p[0]).collect()})
    }
    fn recognize(&mut self,_:HudField,_:&GrayImage)->Result<Option<RecognizedText>,String> {panic!("unused")}
}
fn word(text:&str,confidence:f32) -> Vec<TextWord> {
    vec![TextWord{text:text.into(),confidence,x:2,y:2,width:8,height:10}]
}
#[test] fn state_selects_geometry_not_numeric_output() {
    let (l,c,p,_)=fixtures();p.validate(&c,&l).unwrap();
    assert_eq!(p.selected("refresh_price","active_appearance").unwrap().x,387);
    assert_eq!(p.selected("refresh_price","free_refresh_appearance").unwrap().x,379);
    assert!(p.selected("refresh_free_count","active_appearance").is_err());
}
#[test] fn profile_rejects_identity_unknown_keys_and_missing_states() {
    let (l,c,mut p,_)=fixtures();p.controls_profile_id="other".into();assert!(p.validate(&c,&l).is_err());
    let (_,_,mut p,_)=fixtures();p.fields[1].regions.pop();assert!(p.validate(&c,&l).is_err());
    let mut raw:serde_json::Value=serde_json::from_str(include_str!("../../../../configs/ui/match001-shop-isolated-numbers-v1.json")).unwrap();
    raw["fields"][0]["regions"][0]["rect"]["expected"]=serde_json::json!(4);
    assert!(serde_json::from_value::<NumbersProfile>(raw).is_err());
}
#[test] fn geometry_cannot_overlap_cards_visuals_or_other_fields() {
    let (l,c,mut p,_)=fixtures();p.fields[0].regions[0].rect.x=u32::MAX;assert!(p.validate(&c,&l).is_err());
    let (_,_,mut p,_)=fixtures();p.fields[0].regions[0].rect.x=496;p.fields[0].regions[0].rect.y=1029;
    assert!(p.validate(&c,&l).is_err());
    let (_,_,mut p,_)=fixtures();p.fields[2].regions[0].rect=p.fields[1].regions[2].rect;
    assert!(p.validate(&c,&l).is_err());
}
#[test] fn normal_and_free_modes_have_exact_bounded_calls() {
    let (l,c,p,f)=fixtures();
    for (state,expected) in [("active_appearance",4),("free_refresh_appearance",6)] {
        let mut out=observation(&l,&c,&f,Some(state));
        read_with(&f,&c,&p,&mut out,&Fake, |_|Ok(vec![])).unwrap();
        assert_eq!(out.ocr_process_calls,expected);assert_eq!(out.routing.len(),expected as usize);
        assert!(out.numeric_fields.iter().all(|n|n.value.is_none()));
    }
}
#[test] fn hidden_and_ambiguous_controls_produce_no_numeric_calls() {
    let (l,c,p,f)=fixtures();let mut out=observation(&l,&c,&f,None);
    read_with(&f,&c,&p,&mut out,&Fake, |_|panic!("unexpected OCR")).unwrap();
    assert_eq!(out.ocr_process_calls,0);assert!(out.numeric_fields.iter().all(|n|n.status=="not_observed"));
}
#[test] fn zero_and_count_are_read_not_assumed() {
    let (l,c,p,f)=fixtures();let mut out=observation(&l,&c,&f,Some("free_refresh_appearance"));
    let texts=["4","4","0","0","9","9"];let mut i=0;
    read_with(&f,&c,&p,&mut out,&Fake, |_|{let w=word(texts[i],0.95);i+=1;Ok(w)}).unwrap();
    assert_eq!(out.numeric_fields.iter().map(|n|n.value).collect::<Vec<_>>(),[Some(4),Some(0),Some(9)]);
}
#[test] fn cross_scale_conflict_does_not_change_other_fields() {
    let (l,c,p,f)=fixtures();let mut out=observation(&l,&c,&f,Some("active_appearance"));
    let texts=["4","1","2","2"];let mut i=0;
    read_with(&f,&c,&p,&mut out,&Fake, |_|{let w=word(texts[i],0.95);i+=1;Ok(w)}).unwrap();
    assert_eq!(out.numeric_fields[0].value,None);assert_eq!(out.numeric_fields[1].value,Some(2));
}
#[test] fn low_confidence_never_bypasses_consensus() {
    let (l,c,p,f)=fixtures();let mut out=observation(&l,&c,&f,Some("active_appearance"));let mut i=0;
    read_with(&f,&c,&p,&mut out,&Fake, |_|{i+=1;Ok(word("4",if i==2 {0.69}else{0.95}))}).unwrap();
    assert_eq!(out.numeric_fields[0].value,None);
}
#[test] fn xp_input_is_identical_when_refresh_content_state_and_box_change() {
    let (l,c,p,mut f)=fixtures();let mut saved=vec![];
    for (index,state) in ["active_appearance","free_refresh_appearance"].iter().enumerate() {
        for y in 1000..1080 {for x in 350..540 {
            let at=(y*1920+x)*3;f.pixels[at..at+3].fill((index*200) as u8);
        }}
        let mut out=observation(&l,&c,&f,Some(state));let mut images=vec![];
        read_with(&f,&c,&p,&mut out,&Fake, |image|{images.push(image.clone());Ok(vec![])}).unwrap();
        saved.push(images);
    }
    assert_eq!(saved[0][0],saved[1][0]);assert_eq!(saved[0][1],saved[1][1]);
    assert_ne!(saved[0][2],saved[1][2]);
}
#[test] fn existing_visual_observations_are_not_mutated() {
    let (l,c,p,f)=fixtures();let mut out=observation(&l,&c,&f,Some("active_appearance"));
    let before=serde_json::to_value(&out.controls).unwrap();
    read_with(&f,&c,&p,&mut out,&Fake, |_|Ok(vec![])).unwrap();
    assert_eq!(serde_json::to_value(&out.controls).unwrap(),before);
    assert!(read_with(&f,&c,&p,&mut out,&Fake, |_|Ok(vec![])).is_err());
}
#[test] fn backend_failure_is_an_error_not_zero_or_unknown_success() {
    let (l,c,p,f)=fixtures();let mut out=observation(&l,&c,&f,Some("active_appearance"));
    assert!(read_with(&f,&c,&p,&mut out,&Fake, |_|Err("backend down".into())).is_err());
    assert_eq!(out.ocr_process_calls,1);
}
