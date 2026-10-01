//! Diagnostic-only stage recovery. Numeric v3 decisions are never replaced.
use std::{cell::RefCell, collections::HashSet};
use agente_tft_capture_core::{FrameEnvelope, NormalizedRect, RoiFrame};
use agente_tft_hud_runtime::HudLayout;
use agente_tft_image_preprocess::GrayImage;
use agente_tft_perception_hud::{parse_candidate, parse_stage, HudField, HudOcrEngine,
    HudPreprocessConfig, HudReadError, OcrCandidate, RecognizedText};
use serde_json::{json, Value};
use crate::probe::{self, Expected, LabelKind};

#[derive(Debug)]
pub struct Candidate { name: String, rect: NormalizedRect }
#[derive(Debug)]
pub struct Config { pub source: Value, candidates: Vec<Candidate> }
impl Config {
    pub fn parse(source: Value, layout: &HudLayout) -> Result<Self, String> {
        if source["schema_version"].as_u64() != Some(1)
            || source["reference_width"].as_u64() != Some(layout.reference_width as u64)
            || source["reference_height"].as_u64() != Some(layout.reference_height as u64) {
            return Err("stage recovery schema/resolution mismatch".into());
        }
        let entries = source["candidates"].as_array().ok_or("stage candidates must be an array")?;
        if entries.is_empty() || entries.len() > 4 { return Err("require 1..4 stage candidates".into()); }
        let mut names = HashSet::new();
        let mut candidates: Vec<Candidate> = Vec::new();
        for entry in entries {
            let name = entry["name"].as_str().filter(|n| !n.trim().is_empty() && n.len() <= 48)
                .ok_or("invalid stage candidate name")?.to_string();
            let rect: NormalizedRect = serde_json::from_value(entry["rect"].clone()).map_err(|e| e.to_string())?;
            rect.validate().map_err(|e| e.to_string())?;
            if rect.width > 0.1 || rect.height > 0.1 { return Err("stage candidate exceeds compact ROI budget".into()); }
            if !names.insert(name.clone()) || candidates.iter().any(|c| c.rect == rect) {
                return Err("duplicate stage candidate name or rectangle".into());
            }
            candidates.push(Candidate { name, rect });
        }
        Ok(Self { source, candidates })
    }
}

// Observe the SAME calls made by the existing robust reader. No extra OCR passes.
struct Traced<'a, E> { engine: &'a mut E, rows: RefCell<Vec<Value>>, min: f32 }
impl<E: HudOcrEngine> HudOcrEngine for Traced<'_, E> {
    fn prepare_roi(&self, field: HudField, roi: &RoiFrame, config: HudPreprocessConfig) -> Result<GrayImage, HudReadError> {
        let result = self.engine.prepare_roi(field, roi, config);
        let mut row = json!({"preprocess": config, "text": null, "confidence": null,
            "parsed": null, "reason": "prepared", "error": null});
        match &result {
            Ok(image) => { row["width"] = json!(image.width); row["height"] = json!(image.height); }
            Err(e) => { row["reason"] = json!("preprocess_error"); row["error"] = json!(format!("{e:?}")); }
        }
        self.rows.borrow_mut().push(row);
        result
    }
    fn recognize(&mut self, field: HudField, image: &GrayImage) -> Result<Option<RecognizedText>, String> {
        let result = self.engine.recognize(field, image);
        let mut rows = self.rows.borrow_mut();
        let Some(row) = rows.last_mut() else { return Err("diagnostic trace missing preparation".into()); };
        match &result {
            Err(e) => { row["reason"] = json!("backend_error"); row["error"] = json!(e); }
            Ok(None) => row["reason"] = json!("no_text_or_backend_filter"),
            Ok(Some(r)) => {
                row["text"] = json!(r.text); row["confidence"] = json!(r.confidence.value());
                // Diagnostic parsing has no effect on the value returned to the reader.
                let parsed = parse_candidate(OcrCandidate { field, text:r.text.clone(),
                    confidence:r.confidence, observed_at_ms:0 });
                match parsed {
                    Ok(batch) => {
                        row["parsed"] = match field {
                            HudField::Stage => batch.stage.map(|o|json!(o.value)),
                            HudField::Gold => batch.gold.map(|o|json!(o.value)),
                            HudField::Level => batch.level.map(|o|json!(o.value)),
                            HudField::Xp => batch.xp.map(|o|json!(o.value)),
                            HudField::Hp => batch.hp.map(|o|json!(o.value)),
                        }.unwrap_or(Value::Null);
                        row["reason"] = json!(if r.confidence.value() < self.min { "below_min_confidence" } else { "candidate" });
                    }
                    Err(e) => { row["reason"] = json!("domain_invalid"); row["parse_error"] = json!(format!("{e:?}")); }
                }
            }
        }
        result
    }
}
fn traced<E: HudOcrEngine>(engine: &mut E, layout: &HudLayout, frame: &FrameEnvelope,
    at:u64, expected:&Expected, kind:LabelKind) -> Value {
    let min = layout.regions.iter().find(|r|r.field==expected.field).map(|r|r.policy.min_confidence).unwrap_or(1.0);
    let mut trace = Traced { engine, rows:RefCell::new(Vec::new()), min };
    let mut row = probe::evaluate(&mut trace, layout, frame, at, expected, kind);
    let attempts = trace.rows.into_inner();
    row["ocr_attempts_total"] = json!(attempts.len());
    row["attempt_trace"] = json!(attempts);
    row
}

/// Reuse v3 neutral grayscale preparation, not its level parser/whitelist.
/// Only prepare_roi uses the neutral Level path. Recognition remains Stage/PSM7.
struct StageGray<'a, E>(&'a mut E);
impl<E: HudOcrEngine> HudOcrEngine for StageGray<'_, E> {
    fn prepare_roi(&self, _:HudField, roi:&RoiFrame, config:HudPreprocessConfig) -> Result<GrayImage,HudReadError> {
        self.0.prepare_roi(HudField::Level, roi, config)
    }
    fn recognize(&mut self, _:HudField, image:&GrayImage) -> Result<Option<RecognizedText>,String> {
        let recognized = self.0.recognize(HudField::Stage, image)?;
        Ok(recognized.filter(|r| {
            let text:String=r.text.chars().filter(|c|!c.is_whitespace()).collect();
            text.matches('-').count()==1 && text.split('-').all(|p|!p.is_empty() && p.chars().all(|c|c.is_ascii_digit()))
                && parse_stage(&text).is_ok()
        }))
    }
}

// Stronger than a confidence tie-break: ANY eligible conflicting value abstains.
// Two scales of one ROI must agree; they are not independent temporal evidence.
fn select(candidates:&[Value]) -> Result<(usize,f64), &'static str> {
    let mut distinct=Vec::<Value>::new();
    let mut eligible=Vec::new();
    for (index, c) in candidates.iter().enumerate() {
        let r=&c["record"];
        let attempts=r["attempt_trace"].as_array().ok_or("invalid_trace")?;
        if !r["error"].is_null() || attempts.iter().any(|a|!a["error"].is_null()) { return Err("backend_error"); }
        let valid:Vec<_>=attempts.iter().filter(|a|a["reason"]=="candidate").collect();
        for a in &valid { if !distinct.contains(&a["parsed"]) { distinct.push(a["parsed"].clone()); } }
        if valid.len()>=2 && !r["recognized"].is_null() && valid.iter().all(|a|a["parsed"]==r["recognized"]) {
            let min=valid.iter().filter_map(|a|a["confidence"].as_f64()).fold(1.0, f64::min);
            eligible.push((index,min));
        }
    }
    if distinct.len()>1 { return Err("conflicting_candidates"); }
    eligible.into_iter().next().ok_or("insufficient_scale_agreement")
}

pub fn evaluate<E:HudOcrEngine,F:HudOcrEngine>(engine:&mut E, gray:&mut F, config:&Config,
    layout:&HudLayout, frame:&FrameEnvelope, at:u64, expected:&Expected, kind:LabelKind) -> Value {
    let mut primary=traced(engine,layout,frame,at,expected,kind);
    primary["recovery_applied"]=json!(false);
    // Never use expected.value or correct to decide whether/where to recover.
    if expected.field!=HudField::Stage || primary["status"]!="unknown" || !primary["error"].is_null() { return primary; }
    let Some(region)=layout.regions.iter().find(|r|r.field==HudField::Stage) else { return primary; };
    let mut local=layout.clone();
    let mut candidates=Vec::new();
    let mut adapter=StageGray(gray);
    for c in &config.candidates {
        let r=local.regions.iter_mut().find(|r|r.field==HudField::Stage).unwrap();
        r.rect=c.rect; r.policy=region.policy.clone();
        r.policy.attempts=vec![HudPreprocessConfig {upscale_factor:3,invert:true},HudPreprocessConfig {upscale_factor:4,invert:true}];
        let mut record=traced(&mut adapter,&local,frame,at,expected,kind);
        record["ocr_profile"]=json!("stage_gray_candidates_v4");
        candidates.push(json!({"name":c.name,"record":record}));
    }
    let calls=primary["ocr_attempts_total"].as_u64().unwrap_or(0)+candidates.iter()
        .map(|c|c["record"]["ocr_attempts_total"].as_u64().unwrap_or(0)).sum::<u64>();
    let decision=select(&candidates);
    let mut out=primary.clone();
    let reason=match decision {
        Ok((index,min)) => {
            out=candidates[index]["record"].clone(); out["confidence"]=json!(min);
            out["recovery_applied"]=json!(true); out["selected_candidate"]=candidates[index]["name"].clone();
            "accepted_two_scales"
        }
        Err("backend_error") => { out["status"]=json!("read_error");out["error"]=json!("stage recovery backend/preparation error; inspect recovery_candidates");"backend_error" }
        Err(reason) => reason,
    };
    out["primary_read"]=primary;
    out["ocr_attempts_total"]=json!(calls);
    out["recovery_reason"]=json!(reason);
    out["recovery_candidates"]=json!(candidates);
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use agente_tft_contracts::Confidence;
    use std::collections::VecDeque;
    use crate::media::parse_ppm;
    struct Fake { outputs:VecDeque<Result<Option<RecognizedText>,String>>,calls:usize,prepared:RefCell<Vec<HudField>> }
    impl Fake {
        fn new(values:&[(&str,f32)]) -> Self { Self {outputs:values.iter().map(|(s,c)|Ok(Some(RecognizedText {text:s.to_string(),confidence:Confidence::new(*c).unwrap()}))).collect(),calls:0,prepared:RefCell::new(Vec::new())} }
    }
    impl HudOcrEngine for Fake {
        fn prepare_roi(&self,field:HudField,_:&RoiFrame,_:HudPreprocessConfig)->Result<GrayImage,HudReadError> {
            self.prepared.borrow_mut().push(field); Ok(GrayImage {width:1,height:1,stride_bytes:1,pixels:vec![255]})
        }
        fn recognize(&mut self,_:HudField,_:&GrayImage)->Result<Option<RecognizedText>,String> {self.calls+=1;self.outputs.pop_front().unwrap_or(Ok(None))}
    }
    fn layout()->HudLayout {serde_json::from_value(json!({"schema_version":1,"name":"test","reference_width":100,"reference_height":100,
        "regions":probe::FIELDS.iter().map(|(_,name)|json!({"field":name,"rect":{"x":0,"y":0,"width":0.05,"height":0.05}})).collect::<Vec<_>>()})).unwrap()}
    fn config(l:&HudLayout)->Config {Config::parse(json!({"schema_version":1,"reference_width":100,"reference_height":100,"candidates":[
        {"name":"normal","rect":{"x":0,"y":0,"width":0.05,"height":0.05}},
        {"name":"early","rect":{"x":0.1,"y":0,"width":0.05,"height":0.05}}]}),l).unwrap()}
    fn expected(field:HudField,value:Value)->Expected {Expected {field,name:if field==HudField::Stage {"stage"}else{"gold"},value,confidence:None}}
    fn run(primary:&mut Fake,gray:&mut Fake,e:&Expected)->Value {let l=layout();evaluate(primary,gray,&config(&l),&l,&parse_ppm(b"P6\n1 1\n255\nabc",10).unwrap(),10,e,LabelKind::Prelabels)}
    #[test] fn primary_success_does_not_call_recovery_even_when_label_disagrees() {
        let mut p=Fake::new(&[("2-1",0.9);3]);let mut g=Fake::new(&[]);
        let r=run(&mut p,&mut g,&expected(HudField::Stage,json!("1-1")));
        assert_eq!(r["recognized"],"2-1");assert_eq!(r["correct"],false);assert_eq!(g.calls,0);assert_eq!(p.calls,3);
    }
    #[test] fn numeric_v3_is_never_replaced_and_unknown_trace_is_retained() {
        let mut p=Fake::new(&[("44",0.69);3]);let mut g=Fake::new(&[("44",0.99);4]);
        let r=run(&mut p,&mut g,&expected(HudField::Gold,json!(44)));
        assert!(r["recognized"].is_null());assert_eq!(g.calls,0);assert_eq!(r["attempt_trace"][0]["text"],"44");
        assert_eq!(r["attempt_trace"][0]["reason"],"below_min_confidence");
    }
    #[test] fn two_matching_scales_recover_without_reading_expected_value() {
        for label in ["1-1","9-9"] {let mut p=Fake::new(&[]);let mut g=Fake::new(&[("1-1",0.95),("1-1",0.90)]);
            let r=run(&mut p,&mut g,&expected(HudField::Stage,json!(label)));
            assert_eq!(r["recognized"],"1-1");assert_eq!(r["correct"],label=="1-1");assert_eq!(r["recovery_applied"],true);
            assert_eq!(r["ocr_attempts_total"],7);assert!(g.prepared.borrow().iter().all(|f|*f==HudField::Level));}
    }
    #[test] fn conflicts_across_positions_abstain_even_with_large_confidence_gap() {
        let r=run(&mut Fake::new(&[]),&mut Fake::new(&[("1-1",0.99),("1-1",0.99),("2-1",0.75),("2-1",0.75)]),&expected(HudField::Stage,json!("1-1")));
        assert!(r["recognized"].is_null());assert_eq!(r["recovery_reason"],"conflicting_candidates");
    }
    #[test] fn single_scale_or_missing_hyphen_never_recovers() {
        for values in [vec![("1-1",0.95),("1-1",0.2)],vec![("1 1",0.99);4]] {
            let r=run(&mut Fake::new(&[]),&mut Fake::new(&values),&expected(HudField::Stage,json!("1-1")));
            assert!(r["recognized"].is_null());assert_eq!(r["recovery_reason"],"insufficient_scale_agreement");}
    }
    #[test] fn primary_backend_error_is_not_masked_by_recovery() {
        let mut p=Fake::new(&[]);p.outputs=VecDeque::from(vec![Err("offline".into());3]);let mut g=Fake::new(&[]);
        let r=run(&mut p,&mut g,&expected(HudField::Stage,json!("1-1")));
        assert_eq!(r["status"],"read_error");assert_eq!(g.calls,0);
    }
    #[test] fn recovery_backend_error_remains_operational_error() {
        let mut g=Fake::new(&[]);g.outputs=VecDeque::from(vec![Err("offline".into());4]);
        let r=run(&mut Fake::new(&[]),&mut g,&expected(HudField::Stage,json!("1-1")));
        assert_eq!(r["status"],"read_error");assert!(!r["error"].is_null());
    }
    #[test] fn config_rejects_duplicates_large_regions_and_dimension_mismatch() {
        let l=layout();let c=config(&l);let mut v=c.source.clone();v["reference_width"]=json!(1920);assert!(Config::parse(v,&l).is_err());
        let mut v=c.source.clone();v["candidates"][1]=v["candidates"][0].clone();assert!(Config::parse(v,&l).is_err());
        let mut v=c.source;v["candidates"][0]["rect"]["width"]=json!(0.8);assert!(Config::parse(v,&l).is_err());
    }
    #[test] fn measured_candidates_rasterize_exactly() {
        let l:HudLayout=serde_json::from_str(include_str!("../../../../configs/hud/tft-1920x1080-match001-v3-gray.json")).unwrap();
        let c=Config::parse(serde_json::from_str(include_str!("../../../../configs/hud/tft-1920x1080-match001-v4-stage-recovery.json")).unwrap(),&l).unwrap();
        for (candidate,x) in c.candidates.iter().zip([766,826]) {let p=candidate.rect.to_pixel_rect(1920,1080);assert_eq!((p.x,p.y,p.width,p.height),(x,5,36,25));}
    }
}
