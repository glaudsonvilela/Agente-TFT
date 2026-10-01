//! Paired offline comparison on identical decoded frames, not active fusion.
#[path = "../../hud-replay-probe/src/media.rs"]
mod media;
use std::{collections::{BTreeMap,HashSet},env,fs,io::Write,path::{Path,PathBuf},process::ExitCode,time::Instant};
use agente_tft_ocr_tesseract::TesseractOcr;
use agente_tft_perception_player_list::{BadgeProfile,HpRead,HpStatus,HpTracker,read_player_hp};
mod text_fit;
use text_fit::{HpTextFitOcr,HP_TEXT_FIT_PROFILE};
use serde_json::{Value,json};
const USAGE:&str="Usage: agente-tft-player-hp-fit-probe <manifest.json> <image-root> <badge-profile.json> <NEW-report.json>";
fn load(p:&Path)->Result<Value,String> {
    if fs::metadata(p).map_err(|e|e.to_string())?.len()>8*1024*1024 {return Err("JSON exceeds 8 MiB".into());}
    serde_json::from_str(&fs::read_to_string(p).map_err(|e|e.to_string())?).map_err(|e|e.to_string())
}
fn plan(manifest:&Value,root:&Path)->Result<Vec<(u64,PathBuf)>,String> {
    let frames=manifest["frames"].as_array().ok_or("missing frames array")?;
    if frames.is_empty() || frames.len()>128 {return Err("require 1..128 frames per batch".into());}
    let mut result=Vec::new();let mut paths=HashSet::new();let mut last=None;
    for f in frames {
        let at=f["timestamp_ms"].as_u64().ok_or("invalid timestamp")?;
        if last.is_some_and(|prev|at<=prev) {return Err("duplicate/out-of-order timestamp".into());}
        let path=media::relative_image_path(root,f["image"].as_str())?;
        if !paths.insert(path.clone()) {return Err("reused source image path".into());}
        result.push((at,path));last=Some(at);
    }
    Ok(result)
}
fn comparison(b:&HpRead,c:&HpRead)->&'static str {
    fn readable(r:&HpRead)->bool {
        matches!(r.status,HpStatus::Accepted|HpStatus::NegativeDisplay) && r.signed_hp.is_some()
    }
    match (readable(b),readable(c)) {
        (true,true) if b.signed_hp==c.signed_hp => "both_readable_equal",
        (true,true) => "both_readable_disagree",
        (true,false) => "baseline_only_readable",
        (false,true) => "candidate_only_readable",
        (false,false) => "neither_readable",
    }
}
fn count(map:&mut BTreeMap<String,usize>,key:impl Into<String>) {*map.entry(key.into()).or_default()+=1;}
fn status(r:&HpRead)->String {serde_json::to_value(r.status).unwrap().as_str().unwrap().into()}
fn percentile(v:&[f64],q:f64)->Option<f64> {
    if v.is_empty() {return None;}let mut a=v.to_vec();a.sort_by(f64::total_cmp);
    let x=(a.len()-1) as f64*q;let lo=x.floor() as usize;let hi=x.ceil() as usize;
    Some(a[lo]+(a[hi]-a[lo])*(x-lo as f64))
}
fn run()->Result<bool,String> {
    let args:Vec<_>=env::args().skip(1).collect();
    if args==["--help"] {println!("{USAGE}");return Ok(true);}
    if args.len()!=4 {return Err(USAGE.into());}
    let root=Path::new(&args[1]).canonicalize().map_err(|e|e.to_string())?;
    if !root.is_dir() {return Err("image-root must be a directory".into());}
    let frames=plan(&load(Path::new(&args[0]))?,&root)?;
    let p:BadgeProfile=serde_json::from_value(load(Path::new(&args[2]))?).map_err(|e|e.to_string())?;p.validate()?;
    let mut baseline=TesseractOcr::default().with_numeric_gray();
    if !baseline.available() {return Err("Tesseract unavailable".into());}
    let mut candidate=HpTextFitOcr::new(TesseractOcr::default().with_numeric_gray());
    let mut output=fs::OpenOptions::new().create_new(true).write(true).open(&args[3]).map_err(|e|format!("NEW report: {e}"))?;
    let mut bt=HpTracker::new(750,1500)?;let mut ct=HpTracker::new(750,1500)?;
    let (mut bs,mut cs,mut comparisons)=(BTreeMap::new(),BTreeMap::new(),BTreeMap::new());
    let (mut bc,mut cc,mut fits,mut errors)=(0usize,0usize,0usize,0usize);
    let (mut btimes,mut ctimes)=(Vec::new(),Vec::new());let mut records=Vec::new();
    for (i,(at,path)) in frames.iter().enumerate() {
        eprintln!("HP3_PROBE={}/{} timestamp_ms={at}",i+1,frames.len());
        let decode_start=Instant::now();let frame=media::decode(path,None,*at);let decode_ms=decode_start.elapsed().as_secs_f64()*1000.0;
        let (b,c,bms,cms)=match frame {
            Err(e)=>(HpRead::failure(*at,*at,e.clone()),HpRead::failure(*at,*at,e),0.0,0.0),
            Ok(f)=>{
                let now=Instant::now();let b=read_player_hp(&mut baseline,&f,&p);let bms=now.elapsed().as_secs_f64()*1000.0;
                let now=Instant::now();let c=read_player_hp(&mut candidate,&f,&p);let cms=now.elapsed().as_secs_f64()*1000.0;
                (b,c,bms,cms)
            }
        };
        let trace=candidate.take_traces();let fitted=trace.iter().any(|t|t.applied);
        let bf=bt.observe(&b)?;let cf=ct.observe(&c)?;let class=comparison(&b,&c);
        count(&mut bs,status(&b));count(&mut cs,status(&c));count(&mut comparisons,class);
        bc+=usize::from(bf.current.is_some());cc+=usize::from(cf.current.is_some());fits+=usize::from(fitted);
        errors+=usize::from(b.status==HpStatus::ReadError || c.status==HpStatus::ReadError);
        btimes.push(bms);ctimes.push(cms);
        let record=json!({"timestamp_ms":at,"baseline":b,"candidate":c,"comparison":class,
            "baseline_freshness":bf,"candidate_freshness":cf,"text_fit":trace,
            "decode_ms":decode_ms,"baseline_ms":bms,"candidate_ms":cms});
        println!("{record}");records.push(record);
    }
    let summary=json!({"schema_version":1,"frames":frames.len(),"errors":errors,"execution_complete":errors==0,
        "baseline_profile":p.name,"candidate_profile":HP_TEXT_FIT_PROFILE,
        "baseline_statuses":bs,"candidate_statuses":cs,"comparison":comparisons,
        "baseline_confirmed_frames":bc,"candidate_confirmed_frames":cc,"text_fitted_frames":fits,
        "baseline_read_ms_p50":percentile(&btimes,0.5),"baseline_read_ms_p95":percentile(&btimes,0.95),
        "candidate_read_ms_p50":percentile(&ctimes,0.5),"candidate_read_ms_p95":percentile(&ctimes,0.95),
        "metric_kind":"paired_operational_diagnostics","exact_accuracy":null,"labels_used":false,
        "game_state_updated":false,"profile_promoted":false,"model_trained":false,
        "note":"same decoded pixels; candidate-only reads are not proven recoveries; disagreements are not auto-resolved"});
    serde_json::to_writer_pretty(&mut output,&json!({"summary":summary,"records":records})).map_err(|e|e.to_string())?;
    output.write_all(b"\n").map_err(|e|e.to_string())?;output.sync_all().map_err(|e|e.to_string())?;
    eprintln!("HP3_PROBE_REPORT={}",args[3]);Ok(errors==0)
}
fn main()->ExitCode {match run(){Ok(true)=>ExitCode::SUCCESS,Ok(false)=>ExitCode::from(2),Err(e)=>{eprintln!("HP3_PROBE_ERROR={e}");ExitCode::FAILURE}}}
#[cfg(test)] mod tests {
    use super::*;
    fn r(v:Option<i16>)->HpRead {
        let mut r=HpRead::failure(1,1,"fixture".into());r.error=None;r.status=HpStatus::OcrUncertain;
        if let Some(n)=v {r.status=if n<0 {HpStatus::NegativeDisplay} else {HpStatus::Accepted};r.signed_hp=Some(n);r.hp=(n>=0).then_some(n as u16);r.confidence=Some(0.9);}
        r
    }
    #[test] fn all_comparison_outcomes_are_explicit() {
        assert_eq!(comparison(&r(Some(36)),&r(Some(56))),"both_readable_disagree");
        assert_eq!(comparison(&r(Some(-7)),&r(Some(7))),"both_readable_disagree");
        assert_eq!(comparison(&r(Some(36)),&r(Some(36))),"both_readable_equal");
        assert_eq!(comparison(&r(None),&r(Some(36))),"candidate_only_readable");
        assert_eq!(comparison(&r(Some(36)),&r(None)),"baseline_only_readable");
        assert_eq!(comparison(&r(None),&r(None)),"neither_readable");
    }
    #[test] fn expected_values_never_enter_plan() {
        let a=json!({"frames":[{"timestamp_ms":1,"image":"hp3-absent-a.png","expected":36}]});
        let b=json!({"frames":[{"timestamp_ms":1,"image":"hp3-absent-a.png","expected":56}]});
        assert_eq!(plan(&a,Path::new(".")).unwrap(),plan(&b,Path::new(".")).unwrap());
    }
    #[test] fn duplicate_and_unordered_inputs_fail() {
        let a=json!({"frames":[{"timestamp_ms":2,"image":"a.png"},{"timestamp_ms":1,"image":"b.png"}]});
        assert!(plan(&a,Path::new(".")).is_err());
        let a=json!({"frames":[{"timestamp_ms":1,"image":"a.png"},{"timestamp_ms":2,"image":"a.png"}]});
        assert!(plan(&a,Path::new(".")).is_err());
    }
}
