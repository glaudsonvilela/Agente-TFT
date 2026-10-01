use std::{collections::HashSet, path::Path};
use agente_tft_capture_core::{extract_roi, FrameEnvelope};
use agente_tft_hud_runtime::HudLayout;
use agente_tft_perception_hud::{parse_stage, read_roi_robust, HudField, HudOcrEngine};
use serde_json::{json, Value};

pub const FIELDS: [(HudField, &str); 4] = [(HudField::Stage,"stage"),(HudField::Gold,"gold"),(HudField::Level,"level"),(HudField::Xp,"xp")];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LabelKind { Annotations, Prelabels }
impl LabelKind {
    pub fn name(self) -> &'static str { match self { Self::Annotations=>"annotations", Self::Prelabels=>"prelabels" } }
    pub fn metric_name(self) -> &'static str { match self { Self::Annotations=>"annotation_exact_accuracy", Self::Prelabels=>"prelabel_agreement" } }
}
#[derive(Clone, Debug)]
pub struct Expected { pub field: HudField, pub name: &'static str, pub value: Value, pub confidence: Option<f64> }
#[derive(Debug)]
pub struct Sample { pub timestamp_ms: u64, pub image: Option<String>, pub expected: Vec<Expected> }
#[derive(Debug)]
pub struct Plan { pub source_video: String, pub frames_in_labels: usize, pub samples: Vec<Sample> }

impl Plan {
    pub fn parse(root: &Value, kind: LabelKind, video: &Path) -> Result<Self, String> {
        if root["schema_version"].as_u64() != Some(1) { return Err("labels schema_version must be 1".into()); }
        let source_video=root["source_video"].as_str().filter(|s| !s.trim().is_empty()).ok_or("labels require source_video")?;
        if Path::new(source_video).file_name() != video.file_name() { return Err("source_video mismatch".into()); }
        let frames=root["frames"].as_array().ok_or("labels.frames must be an array")?;
        if frames.is_empty() || frames.len()>1000 { return Err("probe requires 1..1000 label frames".into()); }
        let mut seen=HashSet::new();
        let mut samples=Vec::new();
        for frame in frames {
            let at=frame["timestamp_ms"].as_u64().ok_or("timestamp_ms must be a nonnegative integer")?;
            if !seen.insert(at) { return Err(format!("duplicate timestamp_ms {at}")); }
            let labels=match kind {
                LabelKind::Annotations => {
                    if frame.get("suggestions").is_some() { return Err("AI suggestions require explicit --prelabels; they are not ground truth".into()); }
                    frame.as_object().ok_or("frame must be an object")?
                }
                LabelKind::Prelabels => frame["suggestions"].as_object().ok_or("--prelabels requires suggestions in each frame")?,
            };
            let mut expected=Vec::new();
            for (field,name) in FIELDS {
                let Some(item)=labels.get(name).filter(|v| !v.is_null()) else { continue; };
                let (value,confidence)=match kind {
                    LabelKind::Annotations => (item,None),
                    LabelKind::Prelabels => {
                        let c=item["confidence"].as_f64().filter(|c| c.is_finite() && (0.0..=1.0).contains(c)).ok_or("invalid prelabel confidence")?;
                        let value=item.get("value").ok_or("prelabel requires value")?;
                        (value,Some(c))
                    }
                };
                if value.is_null() { continue; }
                let normalized=match field {
                    HudField::Stage => {
                        let raw=value.as_str().ok_or("expected stage must be a string")?;
                        let canonical=parse_stage(raw).map_err(|e| format!("invalid expected stage: {e:?}"))?;
                        if raw!=canonical { return Err("expected stage must be canonical, e.g. 2-1".into()); }
                        json!(canonical)
                    }
                    _ => {
                        let number=value.as_u64().ok_or("expected numeric HUD value must be an unsigned integer, not a string or bool")?;
                        let (min,max)=if field==HudField::Level { (1,12) } else { (0,999) };
                        if number<min || number>max { return Err(format!("out-of-range expected {name}")); }
                        json!(number)
                    }
                };
                expected.push(Expected { field,name,value:normalized,confidence });
            }
            if !expected.is_empty() {
                let image=match frame.get("image") {
                    Some(v) if !v.is_null() => Some(v.as_str().ok_or("image must be a string")?.to_string()),
                    _ => None,
                };
                samples.push(Sample { timestamp_ms:at, image, expected });
            }
        }
        if samples.is_empty() { return Err("no labeled stage/gold/level/xp fields; review annotations or pass --prelabels explicitly".into()); }
        samples.sort_by_key(|s|s.timestamp_ms);
        Ok(Self { source_video:source_video.into(),frames_in_labels:frames.len(),samples })
    }
}

pub fn validate_layout(layout: &HudLayout) -> Result<(), String> {
    layout.validate().map_err(|e| e.to_string())?;
    if layout.regions.len()!=4 || FIELDS.iter().any(|(field,_)| !layout.regions.iter().any(|r| r.field==*field)) {
        return Err("this probe requires exactly stage/gold/level/xp; static HP is not allowed".into());
    }
    for r in &layout.regions {
        if !r.policy.ambiguity_margin.is_finite() || !(0.0..=1.0).contains(&r.policy.ambiguity_margin)
            || r.policy.attempts.len()>8 || r.policy.attempts.iter().any(|p| !(1..=8).contains(&p.upscale_factor)) {
            return Err("invalid/unbounded OCR policy".into());
        }
    }
    Ok(())
}

fn row(at:u64, expected:&Expected, kind:LabelKind) -> Value {
    json!({"type":"hud_probe", "field":expected.name, "timestamp_ms":at,
        "expected":expected.value, "expected_confidence":expected.confidence,
        "label_kind":kind.name(), "recognized":null, "recognized_text":null,
        "confidence":null, "correct":false, "status":"unknown", "error":null})
}
pub fn failure(at:u64, expected:&Expected, kind:LabelKind, status:&str, error:&str) -> Value {
    let mut value=row(at,expected,kind); value["status"]=json!(status); value["error"]=json!(error); value
}

pub fn evaluate(engine:&mut impl HudOcrEngine, layout:&HudLayout, frame:&FrameEnvelope, at:u64, expected:&Expected, kind:LabelKind) -> Value {
    let Some(region)=layout.regions.iter().find(|r| r.field==expected.field) else {
        return failure(at,expected,kind,"layout_error","missing field in layout");
    };
    let roi=match extract_roi(frame,region.rect) { Ok(roi)=>roi, Err(e)=>return failure(at,expected,kind,"read_error",&e.to_string()) };
    let mut out=row(at,expected,kind);
    out["roi_pixels"]=json!(roi.rect);
    match read_roi_robust(engine,expected.field,&roi,&region.policy) {
        Err(e)=> { out["status"]=json!("read_error"); out["error"]=json!(format!("{e:?}")); }
        Ok(None)=> {}
        Ok(Some(read))=> {
            // Compare the domain-parsed value, not raw OCR text (XP may be 30/56).
            let recognized=match expected.field {
                HudField::Stage=>read.batch.stage.map(|o|json!(o.value)),
                HudField::Gold=>read.batch.gold.map(|o|json!(o.value)),
                HudField::Level=>read.batch.level.map(|o|json!(o.value)),
                HudField::Xp=>read.batch.xp.map(|o|json!(o.value)),
                HudField::Hp=>None,
            }.unwrap_or(Value::Null);
            out["correct"]=json!(recognized==expected.value);
            out["recognized"]=recognized;
            out["recognized_text"]=json!(read.recognized_text);
            out["confidence"]=json!(read.confidence.value());
            out["preprocess"]=json!(read.preprocess);
            out["attempts_made"]=json!(read.attempts_made);
            out["status"]=json!("read");
        }
    }
    out
}

fn fraction(n:usize,d:usize) -> Value { if d==0 { Value::Null } else { json!(n as f64/d as f64) } }
fn percentile(sorted:&[f64],q:f64) -> Value {
    if sorted.is_empty() { return Value::Null; }
    let p=(sorted.len()-1) as f64*q;
    let lo=p.floor() as usize; let hi=p.ceil() as usize;
    json!(sorted[lo]+(sorted[hi]-sorted[lo])*(p-lo as f64))
}
pub fn summarize(records:&[Value],kind:LabelKind) -> Value {
    let mut fields=serde_json::Map::new();
    for (_,name) in FIELDS {
        let rows:Vec<_>=records.iter().filter(|r| r["field"].as_str()==Some(name)).collect();
        let n=rows.len();
        let correct=rows.iter().filter(|r|r["correct"]==true).count();
        let no_read=rows.iter().filter(|r|r["recognized"].is_null()).count();
        let errors=rows.iter().filter(|r|!r["error"].is_null()).count();
        let mut confidence:Vec<f64>=rows.iter().filter_map(|r|r["confidence"].as_f64()).collect();
        confidence.sort_by(f64::total_cmp);
        fields.insert(name.into(),json!({"annotated":n,"correct":correct,"recognized":n-no_read,
            "unknown":no_read,"errors":errors,
            "exact_accuracy":if kind==LabelKind::Annotations { fraction(correct,n) } else { Value::Null },
            "prelabel_agreement":if kind==LabelKind::Prelabels { fraction(correct,n) } else { Value::Null },
            "unknown_rate":fraction(no_read,n),"confidence_count":confidence.len(),
            "confidence_p50":percentile(&confidence,0.50),"confidence_p95":percentile(&confidence,0.95)}));
    }
    Value::Object(fields)
}

#[cfg(test)]
mod tests {
    use super::*;
    use agente_tft_contracts::Confidence;
    use agente_tft_image_preprocess::GrayImage;
    use agente_tft_perception_hud::RecognizedText;
    use crate::media::parse_ppm;
    fn root(frames:Value)->Value { json!({"schema_version":1,"source_video":"match.mp4","frames":frames}) }
    fn plan(v:&Value,kind:LabelKind)->Result<Plan,String> { Plan::parse(v,kind,Path::new("/local/match.mp4")) }
    fn layout()->HudLayout {
        serde_json::from_value(json!({"schema_version":1,"name":"test","reference_width":1,"reference_height":1,
            "regions":FIELDS.iter().map(|(_,n)|json!({"field":n,"rect":{"x":0,"y":0,"width":1,"height":1}})).collect::<Vec<_>>()})).unwrap()
    }
    fn frame()->FrameEnvelope { parse_ppm(b"P6\n1 1\n255\nabc",10).unwrap() }
    struct Fake { result:Result<Option<RecognizedText>,String>, calls:usize }
    impl HudOcrEngine for Fake {
        fn recognize(&mut self,_:HudField,_:&GrayImage)->Result<Option<RecognizedText>,String> { self.calls+=1;self.result.clone() }
    }
    fn fake(text:&str,confidence:f32)->Fake { Fake { result:Ok(Some(RecognizedText { text:text.into(),confidence:Confidence::new(confidence).unwrap() })),calls:0 } }
    fn gold()->Expected { Expected { field:HudField::Gold,name:"gold",value:json!(31),confidence:None } }
    #[test] fn annotations_skip_unlabeled_and_sort_without_losing_zero() {
        let p=plan(&root(json!([{"timestamp_ms":20,"gold":0},{"timestamp_ms":0},{"timestamp_ms":10,"xp":0,"level":2}])),LabelKind::Annotations).unwrap();
        assert_eq!(p.frames_in_labels,3);assert_eq!(p.samples.len(),2);assert_eq!(p.samples[0].timestamp_ms,10);assert_eq!(p.samples[1].expected[0].value,0);
    }
    #[test] fn prelabels_are_never_silently_ground_truth() {
        let v=root(json!([{"timestamp_ms":10,"suggestions":{"gold":{"value":31,"confidence":0.99}}}]));
        assert!(plan(&v,LabelKind::Annotations).is_err());
        let p=plan(&v,LabelKind::Prelabels).unwrap(); assert_eq!(p.samples[0].expected[0].confidence,Some(0.99));
    }
    #[test] fn schema_source_duplicates_and_bad_timestamps_rejected() {
        let mut v=root(json!([{"timestamp_ms":10,"gold":1}]));
        v["schema_version"]=json!(2);assert!(plan(&v,LabelKind::Annotations).is_err());
        v["schema_version"]=json!(1);v["source_video"]=json!("wrong.mp4");assert!(plan(&v,LabelKind::Annotations).is_err());
        for frames in [json!([{"timestamp_ms":-1,"gold":1}]),json!([{"timestamp_ms":true,"gold":1}]),json!([{"timestamp_ms":1,"gold":1},{"timestamp_ms":1,"gold":2}])] {
            assert!(plan(&root(frames),LabelKind::Annotations).is_err());
        }
    }
    #[test] fn expected_values_are_typed_and_validated() {
        for (key,value) in [("gold",json!(true)),("gold",json!("31")),("gold",json!(1000)),("level",json!(0)),("level",json!(13)),("xp",json!("0/10")),("stage",json!("2--1")),("stage",json!("0-1"))] {
            let mut f=json!({"timestamp_ms":10});f[key]=value;
            assert!(plan(&root(json!([f])),LabelKind::Annotations).is_err(),"{key}");
        }
    }
    #[test] fn empty_labels_do_not_report_perfect_accuracy() {
        for frames in [json!([]),json!([{"timestamp_ms":0}]),json!([{"timestamp_ms":0,"gold":null}])] {
            assert!(plan(&root(frames),LabelKind::Annotations).is_err());
        }
        assert!(summarize(&[],LabelKind::Annotations)["gold"]["exact_accuracy"].is_null());
    }
    #[test] fn prelabel_confidence_is_validated_not_used_to_filter_failures() {
        let v=root(json!([{"timestamp_ms":0,"suggestions":{"gold":{"value":1,"confidence":0.01}}}]));
        assert_eq!(plan(&v,LabelKind::Prelabels).unwrap().samples.len(),1);
        let mut invalid=v;invalid["frames"][0]["suggestions"]["gold"]["confidence"]=json!(2);
        assert!(plan(&invalid,LabelKind::Prelabels).is_err());
    }
    #[test] fn no_hp_and_no_unsafe_policies() {
        let mut l=layout();assert!(validate_layout(&l).is_ok());
        l.regions[0].field=HudField::Hp;assert!(validate_layout(&l).is_err());
        l=layout();l.regions[0].policy.ambiguity_margin=f32::NAN;assert!(validate_layout(&l).is_err());
        l=layout();l.regions[0].policy.attempts[0].upscale_factor=0;assert!(validate_layout(&l).is_err());
    }
    #[test] fn uses_existing_robust_reader_and_compares_semantics() {
        let mut engine=fake("031",0.94);
        let r=evaluate(&mut engine,&layout(),&frame(),10,&gold(),LabelKind::Annotations);
        assert_eq!(r["recognized"],31);assert_eq!(r["correct"],true);assert_eq!(engine.calls,3);
        let expected=Expected { field:HudField::Xp,name:"xp",value:json!(30),confidence:None };
        assert_eq!(evaluate(&mut fake("30/56",0.94),&layout(),&frame(),10,&expected,LabelKind::Annotations)["correct"],true);
    }
    #[test] fn expected_label_does_not_select_or_correct_ocr() {
        let r=evaluate(&mut fake("32",0.95),&layout(),&frame(),10,&gold(),LabelKind::Annotations);
        assert_eq!(r["recognized"],32);assert_eq!(r["correct"],false);
    }
    #[test] fn low_confidence_remains_unknown_and_counted_as_failure() {
        let r=evaluate(&mut fake("31",0.20),&layout(),&frame(),10,&gold(),LabelKind::Annotations);
        assert!(r["recognized"].is_null());assert_eq!(r["correct"],false);
        let s=summarize(&[r],LabelKind::Annotations);
        assert_eq!(s["gold"]["unknown_rate"],1.0);assert_eq!(s["gold"]["exact_accuracy"],0.0);
    }
    #[test] fn backend_errors_are_retained_not_omitted() {
        let mut engine=Fake { result:Err("backend failed".into()),calls:0 };
        let r=evaluate(&mut engine,&layout(),&frame(),10,&gold(),LabelKind::Annotations);
        assert_eq!(r["status"],"read_error");
        let s=summarize(&[r,failure(20,&gold(),LabelKind::Annotations,"decode_error","missing frame")],LabelKind::Annotations);
        assert_eq!(s["gold"]["annotated"],2);assert_eq!(s["gold"]["errors"],2);assert_eq!(s["gold"]["exact_accuracy"],0.0);
    }
    #[test] fn prelabel_summary_never_claims_accuracy() {
        let r=evaluate(&mut fake("31",0.94),&layout(),&frame(),10,&gold(),LabelKind::Prelabels);
        let s=summarize(&[r],LabelKind::Prelabels);
        assert!(s["gold"]["exact_accuracy"].is_null());assert_eq!(s["gold"]["prelabel_agreement"],1.0);
    }
    #[test] fn percentile_has_explicit_empty_and_linear_cases() {
        assert!(percentile(&[],0.5).is_null());assert_eq!(percentile(&[0.7,0.9],0.5),0.8);
        assert_eq!(percentile(&[0.9],0.95),0.9);
    }
    #[test] fn measured_v2_maps_to_documented_pixel_boxes() {
        let l:HudLayout=serde_json::from_str(include_str!("../../../../configs/hud/tft-1920x1080-match001-v2.json")).unwrap();
        validate_layout(&l).unwrap();
        for (region,(x,y,w,h)) in l.regions.iter().zip([(766,5,36,25),(1020,885,33,25),(390,883,22,24),(466,884,49,20)]) {
            let r=region.rect.to_pixel_rect(1920,1080);assert_eq!((r.x,r.y,r.width,r.height),(x,y,w,h));
        }
    }
}
