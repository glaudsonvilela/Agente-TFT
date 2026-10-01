use std::collections::VecDeque;
use agente_tft_capture_core::{PixelFormat, PixelRect, RoiFrame};
use agente_tft_contracts::Confidence;
use agente_tft_image_preprocess::GrayImage;
use agente_tft_perception_hud::{read_roi_robust, HudField, HudImageMode, HudOcrEngine, HudPreprocessConfig, HudReadPolicy, RecognizedText};

fn roi() -> RoiFrame {
    RoiFrame { source_frame_id:1,captured_at_ms:10,rect:PixelRect{x:0,y:0,width:2,height:1},
        stride_bytes:8,pixel_format:PixelFormat::Rgba8,bytes_per_pixel:4,pixels:vec![0,0,0,255,255,255,255,255] }
}
struct Fake { values:VecDeque<(&'static str,f32)>, psms:Vec<Option<u8>>, sizes:Vec<(u32,u32)> }
impl Fake {
    fn new(v:&[(&'static str,f32)]) -> Self { Self{values:v.iter().copied().collect(),psms:vec![],sizes:vec![]} }
}
impl HudOcrEngine for Fake {
    fn recognize(&mut self,_:HudField,_:&GrayImage)->Result<Option<RecognizedText>,String> {
        Ok(self.values.pop_front().map(|(s,c)| RecognizedText{text:s.into(),confidence:Confidence::new(c).unwrap()}))
    }
    fn recognize_with_psm(&mut self,f:HudField,g:&GrayImage,p:Option<u8>)->Result<Option<RecognizedText>,String> {
        self.psms.push(p);self.sizes.push((g.width,g.height));self.recognize(f,g)
    }
}
fn policy() -> HudReadPolicy {
    HudReadPolicy { attempts:(3..=5).map(|scale| HudPreprocessConfig{upscale_factor:scale,invert:true}).collect(),
        image_mode:HudImageMode::GrayBilinear,page_segmentation:Some(7),require_xp_fraction:true,..HudReadPolicy::default() }
}
#[test] fn old_policy_json_keeps_old_defaults() {
    let p:HudReadPolicy=serde_json::from_str(r#"{"attempts":[],"min_confidence":0.7,"ambiguity_margin":0.03}"#).unwrap();
    assert_eq!(p.image_mode,HudImageMode::LegacyBinary);assert_eq!(p.page_segmentation,None);assert!(!p.require_xp_fraction);
}
#[test] fn new_profile_roundtrip_is_explicit() {
    let p=policy();assert_eq!(serde_json::from_str::<HudReadPolicy>(&serde_json::to_string(&p).unwrap()).unwrap(),p);
    assert_eq!(p.min_confidence,0.70);assert_eq!(p.ambiguity_margin,0.03);
}
#[test] fn line_psm_and_grayscale_are_used_by_robust_reader() {
    let mut f=Fake::new(&[("12/36",0.95),("12/36",0.96),("12/36",0.94)]);
    let r=read_roi_robust(&mut f,HudField::Xp,&roi(),&policy()).unwrap().unwrap();
    assert_eq!(r.batch.xp.unwrap().value,12);assert_eq!(f.psms,vec![Some(7);3]);
    assert_eq!(f.sizes,vec![(26,23),(28,24),(30,25)]);
}
#[test] fn missing_slash_cannot_become_high_confidence_xp() {
    let mut f=Fake::new(&[("010",0.99),("010",0.99),("010",0.99)]);
    assert!(read_roi_robust(&mut f,HudField::Xp,&roi(),&policy()).unwrap().is_none());
}
#[test] fn numeric_xp_legacy_still_works() {
    let mut f=Fake::new(&[("10",0.95),("10",0.95),("10",0.95)]);
    assert_eq!(read_roi_robust(&mut f,HudField::Xp,&roi(),&HudReadPolicy::default()).unwrap().unwrap().batch.xp.unwrap().value,10);
}
#[test] fn all_nearby_distinct_values_are_checked_for_ambiguity() {
    let mut f=Fake::new(&[("12/36",0.96),("12/36",0.95),("14/36",0.94)]);
    assert!(read_roi_robust(&mut f,HudField::Xp,&roi(),&policy()).unwrap().is_none());
}
#[test] fn new_mode_does_not_accept_low_confidence() {
    let mut f=Fake::new(&[("12/36",0.69),("12/36",0.68),("12/36",0.67)]);
    assert!(read_roi_robust(&mut f,HudField::Xp,&roi(),&policy()).unwrap().is_none());
}
#[test] fn fraction_still_obeys_numeric_domain() {
    let mut f=Fake::new(&[("40/36",0.99),("1/0",0.99),("3//36",0.99)]);
    assert!(read_roi_robust(&mut f,HudField::Xp,&roi(),&policy()).unwrap().is_none());
}
#[test] fn invalid_profile_is_rejected_before_ocr() {
    let mut p=policy();p.page_segmentation=Some(255);let mut f=Fake::new(&[]);
    assert!(read_roi_robust(&mut f,HudField::Xp,&roi(),&p).is_err());assert!(f.psms.is_empty());
    p=policy();p.attempts[0].upscale_factor=0;assert!(p.validate().is_err());
    p=policy();p.min_confidence=f32::NAN;assert!(p.validate().is_err());
}
#[test] fn production_config_preserves_stage_and_gates() {
    let cfg:serde_json::Value=serde_json::from_str(include_str!("../../../../configs/hud/tft-1920x1080-match001-v3.json")).unwrap();
    let regions=cfg["regions"].as_array().unwrap();assert!(regions[0].get("policy").is_none());
    for r in &regions[1..] {
        let p:HudReadPolicy=serde_json::from_value(r["policy"].clone()).unwrap();p.validate().unwrap();
        assert_eq!(p.min_confidence,0.7);assert_eq!(p.ambiguity_margin,0.03);assert_eq!(p.page_segmentation,Some(7));
    }
}
