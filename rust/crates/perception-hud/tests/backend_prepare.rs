use agente_tft_capture_core::{PixelFormat, PixelRect, RoiFrame};
use agente_tft_contracts::Confidence;
use agente_tft_image_preprocess::GrayImage;
use agente_tft_perception_hud::*;
struct Backend { confidence: f32, calls: usize }
impl HudOcrEngine for Backend {
    fn prepare_roi(&self, _: HudField, _: &RoiFrame, _: HudPreprocessConfig) -> Result<GrayImage,HudReadError> {
        Ok(GrayImage { width:1,height:1,stride_bytes:1,pixels:vec![123] })
    }
    fn recognize(&mut self, _: HudField, image: &GrayImage) -> Result<Option<RecognizedText>,String> {
        assert_eq!(image.pixels,vec![123]); self.calls+=1;
        Ok(Some(RecognizedText { text:"8".into(),confidence:Confidence::new(self.confidence).unwrap() }))
    }
}
fn roi()->RoiFrame {
    RoiFrame { source_frame_id:1,captured_at_ms:20,rect:PixelRect{x:0,y:0,width:1,height:1},
        stride_bytes:4,pixel_format:PixelFormat::Rgba8,bytes_per_pixel:4,pixels:vec![0,0,0,255] }
}
#[test] fn both_readers_use_backend_preparation_without_bypassing_confidence() {
    let mut e=Backend{confidence:0.9,calls:0};
    let read=read_roi_robust(&mut e,HudField::Level,&roi(),&HudReadPolicy::default()).unwrap().unwrap();
    assert_eq!(e.calls,3); assert_eq!(read.batch.level.unwrap().value,8);
    let read=read_roi_with_ocr(&mut e,HudField::Level,&roi(),HudPreprocessConfig::default()).unwrap().unwrap();
    assert_eq!(read.level.unwrap().value,8);
    e.confidence=0.69;
    assert!(read_roi_robust(&mut e,HudField::Level,&roi(),&HudReadPolicy::default()).unwrap().is_none());
}
#[test] fn default_policy_is_not_relaxed() {
    let p=HudReadPolicy::default(); assert_eq!(p.min_confidence,0.70);assert_eq!(p.ambiguity_margin,0.03);
}
