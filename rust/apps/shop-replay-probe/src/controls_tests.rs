use super::*;
use crate::recovery::Tile;
use crate::screen::{agree, attempt};
use agente_tft_ocr_tesseract::TextWord;

fn profile() -> ControlsProfile {
    serde_json::from_str(include_str!("../../../../configs/ui/match001-shop-controls-v1.json")).unwrap()
}
fn layout() -> ScreenLayout {
    serde_json::from_str(include_str!("../../../../configs/ui/match001-desktop-1920x1080-ptbr-v1.json")).unwrap()
}
fn recovery() -> RecoveryProfile {
    serde_json::from_str(include_str!("../../../../configs/ui/match001-shop-recovery-v2.json")).unwrap()
}
fn reader(p: ControlsProfile) -> Result<ControlsReader, String> { ControlsReader::new(p, &layout(), &recovery()) }
fn frame() -> FrameEnvelope {
    FrameEnvelope { frame_id: 1, captured_at_ms: 250, source_id: "synthetic".into(), width: 1920,
        height: 1080, stride_bytes: 7680, pixel_format: PixelFormat::Rgba8, pixels: vec![0; 1920*1080*4] }
}
fn paint(f: &mut FrameEnvelope, spec: &ControlSpec, which: usize) {
    let rgb = &spec.templates[which].rgb;
    for y in 0..spec.rect.height {
        for x in 0..spec.rect.width {
            let index = ((y*spec.grid_height as u32/spec.rect.height)*spec.grid_width as u32
                + x*spec.grid_width as u32/spec.rect.width) as usize*3;
            let at = (spec.rect.y+y) as usize*f.stride_bytes as usize+(spec.rect.x+x) as usize*4;
            f.pixels[at..at+3].copy_from_slice(&rgb[index..index+3]);
        }
    }
}

#[test]
fn ui_and_recovery_id_are_required() {
    let mut p = profile(); p.parent_layout_id = "other".into(); assert!(reader(p).is_err());
    let mut p = profile(); p.recovery_profile_id = "other".into(); assert!(reader(p).is_err());
}
#[test]
fn invalid_thresholds_and_pixel_budgets_fail() {
    let mut p = profile(); p.controls[0].max_rgb_mae = 13.0; assert!(reader(p).is_err());
    let mut p = profile(); p.min_text_confidence = 0.69; assert!(reader(p).is_err());
    let mut p = profile(); p.controls[0].min_similarity = f32::NAN; assert!(reader(p).is_err());
    let mut p = profile(); p.controls[0].templates[0].rgb.pop(); assert!(reader(p).is_err());
}
#[test]
fn controls_cannot_overlap_cards_or_each_other() {
    let mut p = profile(); p.controls[0].rect = layout().slots[0].name; assert!(reader(p).is_err());
    let mut p = profile(); p.controls[1].rect = p.controls[0].rect; assert!(reader(p).is_err());
    let mut p = profile(); p.controls[0].rect.x = u32::MAX; assert!(reader(p).is_err());
}
#[test]
fn seeded_lock_has_no_fabricated_closed_example() {
    let p = profile(); assert_eq!(p.controls[0].templates.len(), 1);
    assert_eq!(p.controls[0].templates[0].state, "unlocked_appearance");
    let r = reader(p).unwrap().read_visual(&frame(), true).unwrap();
    assert_eq!(r.controls[0].status, "unknown"); assert!(r.controls[0].appearance.is_none());
}
#[test]
fn distinct_appearances_are_observed_without_action_permission() {
    let p = profile(); let engine = reader(p.clone()).unwrap();
    for index in [0, 1] {
        let mut f = frame(); paint(&mut f, &p.controls[1], index);
        let result = engine.read_visual(&f, true).unwrap();
        assert_eq!(result.controls[1].appearance.as_deref(), Some(p.controls[1].templates[index].state.as_str()));
        assert!(result.controls.iter().all(|c| c.action_allowed.is_none()));
    }
}
#[test]
fn refresh_active_dimmed_and_free_stay_distinct() {
    let p = profile(); let engine = reader(p.clone()).unwrap();
    for index in 0..3 {
        let mut f = frame(); paint(&mut f, &p.controls[2], index);
        let r = engine.read_visual(&f, true).unwrap();
        assert_eq!(r.controls[2].appearance.as_deref(), Some(p.controls[2].templates[index].state.as_str()));
    }
}
#[test]
fn conflicting_eligible_states_abstain() {
    let mut p = profile(); let mut second = p.controls[0].templates[0].clone();
    second.state = "locked_appearance".into(); p.controls[0].templates.push(second);
    let mut f = frame(); paint(&mut f, &p.controls[0], 0);
    let r = reader(p).unwrap().read_visual(&f, true).unwrap();
    assert_eq!(r.controls[0].status, "ambiguous"); assert!(r.controls[0].appearance.is_none());
}
#[test]
fn hidden_panel_overrides_even_exact_control_pixels() {
    let p = profile(); let mut f = frame();
    for spec in &p.controls { paint(&mut f, spec, 0); }
    let r = reader(p).unwrap().read_visual(&f, false).unwrap();
    assert!(r.controls.iter().all(|c| c.status == "unavailable" && c.scores.is_empty()));
    assert_eq!(r.ocr_process_calls, 0); assert!(!r.temporal_confirmation);
}
#[test]
fn resolution_and_buffer_errors_are_operational() {
    let engine = reader(profile()).unwrap();
    let mut f = frame(); f.width = 1280; assert!(engine.read_visual(&f, true).is_err());
    let mut f = frame(); f.pixels.truncate(3); assert!(engine.read_visual(&f, true).is_err());
}
#[test]
fn bgra_and_rgb_padding_preserve_signature() {
    let p = profile(); let mut f = frame(); paint(&mut f, &p.controls[1], 0);
    let expected = sample(&f, &p.controls[1]);
    for pixel in f.pixels.chunks_exact_mut(4) { pixel.swap(0,2); }
    f.pixel_format = PixelFormat::Bgra8; assert_eq!(sample(&f, &p.controls[1]), expected);
    for pixel in f.pixels.chunks_exact_mut(4) { pixel.swap(0,2); }
    let mut rgb = Vec::new();
    for row in f.pixels.chunks_exact(7680) {
        for pixel in row.chunks_exact(4) { rgb.extend_from_slice(&pixel[..3]); }
        rgb.extend([99;7]);
    }
    f.pixels = rgb; f.pixel_format = PixelFormat::Rgb8; f.stride_bytes = 1920*3+7;
    assert_eq!(sample(&f, &p.controls[1]), expected);
}
#[test]
fn numeric_zero_is_observed_not_missing_or_assumed() {
    let tile = Tile { slot: 0, field: 1, rect: PixelRect { x:0,y:0,width:40,height:30 } };
    let w = TextWord { text:"0".into(), confidence:0.9,x:5,y:5,width:10,height:12 };
    let attempts = [attempt(&[w.clone()], tile, 3, 0.7, false), attempt(&[w], tile, 4, 0.7, false)];
    assert_eq!(agree(&attempts).0.as_deref(), Some("0"));
    assert!(agree(&[attempt(&[],tile,3,0.7,false), attempt(&[],tile,4,0.7,false)]).0.is_none());
}
#[test]
fn numeric_weak_conflicting_or_crossing_text_is_not_accepted() {
    let tile = Tile { slot: 0, field: 1, rect: PixelRect { x:0,y:0,width:40,height:30 } };
    let mut w = TextWord { text:"4".into(), confidence:0.9,x:5,y:5,width:10,height:12 };
    let first = attempt(&[w.clone()], tile, 3, 0.7, false);
    w.confidence = 0.69;
    assert!(agree(&[first.clone(), attempt(&[w.clone()],tile,4,0.7,false)]).0.is_none());
    w.confidence = 0.95; w.text = "2".into();
    assert!(agree(&[first, attempt(&[w.clone()],tile,4,0.7,false)]).0.is_none());
    assert_eq!(attempt(&[w],tile,4,0.7,true).reason, "atlas_assignment_conflict");
}
