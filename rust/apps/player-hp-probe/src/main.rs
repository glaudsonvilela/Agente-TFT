//! Offline HP1 probe. Shares the existing sparse media decoder, never the game process.
#[path = "../../hud-replay-probe/src/media.rs"]
mod media;
use std::{collections::{BTreeMap,HashSet},env,fs,io::Write,path::{Path,PathBuf},process::ExitCode};
use agente_tft_contracts::Confidence;
use agente_tft_ocr_tesseract::TesseractOcr;
use agente_tft_perception_health::{PerceptionHealthMonitor,PerceptionHealthPolicy,PerceptionOutcome,PerceptionSample,PerceptionStreamId};
use agente_tft_perception_player_list::{BadgeProfile,HpRead,HpStatus,HpTracker,read_player_hp};
use serde_json::{Value,json};
const USAGE:&str="Usage: agente-tft-player-hp-probe <manifest-or-prelabels.json> <image-root> <badge-profile.json> <NEW-report.json>";
fn load(p:&Path)->Result<Value,String>{
    let meta=fs::metadata(p).map_err(|e|format!("{}: {e}",p.display()))?;
    if meta.len()>8*1024*1024{return Err("input JSON exceeds 8 MiB".into());}
    serde_json::from_str(&fs::read_to_string(p).map_err(|e|e.to_string())?).map_err(|e|e.to_string())
}
// Only timestamp/image identity is read. Labels/suggestions are deliberately ignored.
fn plan(manifest:&Value,root:&Path)->Result<Vec<(u64,PathBuf)>,String>{
    let frames=manifest["frames"].as_array().ok_or("manifest requires frames")?;
    if frames.is_empty() || frames.len()>1000{return Err("require 1..1000 frames".into());}
    let mut out=Vec::new();let mut images=HashSet::new();let mut last=None;
    for row in frames{
        let at=row["timestamp_ms"].as_u64().ok_or("invalid timestamp_ms")?;
        if last.is_some_and(|prev|at<=prev){return Err("timestamps must be strictly increasing and unique".into());}
        let path=media::relative_image_path(root,row["image"].as_str())?;
        if !images.insert(path.clone()){return Err("reused image path must not count as new evidence".into());}
        out.push((at,path));last=Some(at);
    }
    Ok(out)
}
fn run()->Result<bool,String>{
    let args:Vec<_>=env::args().skip(1).collect();
    if args==["--help"] {println!("{USAGE}");return Ok(true);}
    if args.len()!=4{return Err(USAGE.into());}
    let manifest=PathBuf::from(&args[0]);let root=PathBuf::from(&args[1]).canonicalize().map_err(|e|e.to_string())?;
    if !root.is_dir(){return Err("image-root must be a directory".into());}
    let profile_path=PathBuf::from(&args[2]);
    let profile:BadgeProfile=serde_json::from_value(load(&profile_path)?).map_err(|e|e.to_string())?;profile.validate()?;
    let frames=plan(&load(&manifest)?,&root)?;
    let mut engine=TesseractOcr::default().with_numeric_gray();
    if !engine.available(){return Err("tesseract unavailable".into());}
    let output=PathBuf::from(&args[3]);
    let mut file=fs::OpenOptions::new().write(true).create_new(true).open(&output).map_err(|e|format!("NEW report: {e}"))?;
    let mut tracker=HpTracker::new(750,1500)?;
    let mut health=PerceptionHealthMonitor::new(PerceptionHealthPolicy::default()).map_err(|e|e.to_string())?;
    let stream=PerceptionStreamId::new("player_list","hp",&profile.name).map_err(|e|e.to_string())?;
    let mut records=Vec::new();let mut statuses=BTreeMap::<String,usize>::new();
    let mut errors=0;let mut located=0;let mut accepted=0;let mut negative=0;
    for (index,(at,path)) in frames.iter().enumerate(){
        eprintln!("HP_PROBE {}/{} timestamp_ms={at}",index+1,frames.len());
        let read=match media::decode(path,None,*at){
            Ok(frame)=>read_player_hp(&mut engine,&frame,&profile),
            Err(e)=>HpRead::failure(*at,*at,e),
        };
        let freshness=tracker.observe(&read)?;
        let outcome=match read.status{
            HpStatus::Accepted|HpStatus::NegativeDisplay=>PerceptionOutcome::Accepted{confidence:Confidence::new(read.confidence.unwrap()).map_err(|e|e.to_string())?},
            HpStatus::OcrConflict|HpStatus::BadgeAmbiguous=>PerceptionOutcome::Conflict,
            HpStatus::ReadError=>PerceptionOutcome::Error,
            _=>PerceptionOutcome::Unknown,
        };
        let snapshot=health.observe(PerceptionSample{stream:stream.clone(),observed_at_ms:*at,outcome}).map_err(|e|e.to_string())?;
        let status=serde_json::to_value(read.status).map_err(|e|e.to_string())?.as_str().unwrap().to_string();
        *statuses.entry(status).or_default()+=1;
        errors+=usize::from(read.error.is_some());located+=usize::from(read.location.candidates.len()==1);
        accepted+=usize::from(read.status==HpStatus::Accepted);negative+=usize::from(read.status==HpStatus::NegativeDisplay);
        let record=json!({"type":"player_hp_probe","read":read,"freshness":freshness,"health":snapshot});
        println!("{record}");records.push(record);
    }
    let summary=json!({"type":"summary","schema_version":1,"profile":profile.name,"frames":frames.len(),
        "localized_unique":located,"hp_accepted":accepted,"negative_display":negative,"errors":errors,"statuses":statuses,
        "execution_complete":errors==0,"metric_kind":"operational_read_coverage","exact_accuracy":null,
        "labels_used":false,"game_state_updated":false,"profile_promoted":false,"manifest":manifest,"image_root":root,"profile_path":profile_path,
        "time_basis":"manifest_timestamp; decoded PTS not independently verified",
        "identity_basis":"unique enlarged badge; recording-specific visual hypothesis, not account identity",
        "temporal_note":"two OCR scales are one frame; sparse JPEGs do not provide 750ms temporal confirmation",
        "health_note":"all supplied frames counted, including hidden/pre-HUD frames; health does not trigger adaptation"});
    serde_json::to_writer_pretty(&mut file,&json!({"summary":summary,"records":records})).map_err(|e|e.to_string())?;
    file.write_all(b"\n").map_err(|e|e.to_string())?;file.sync_all().map_err(|e|e.to_string())?;
    println!("{summary}");eprintln!("HP_PROBE_REPORT={}",output.display());Ok(errors==0)
}
fn main()->ExitCode{match run(){Ok(true)=>ExitCode::SUCCESS,Ok(false)=>ExitCode::from(2),Err(e)=>{eprintln!("HP_PROBE_ERROR={e}");ExitCode::FAILURE}}}
#[cfg(test)] mod tests{
    use super::*;
    #[test]fn labels_cannot_affect_plan(){let root=Path::new(".");let a=json!({"frames":[{"timestamp_ms":1,"image":"frames/a.jpg","hp":100}]});
        let b=json!({"frames":[{"timestamp_ms":1,"image":"frames/a.jpg","hp":1,"suggestions":{"hp":{"value":1}}}]});assert_eq!(plan(&a,root).unwrap(),plan(&b,root).unwrap());}
    #[test]fn duplicate_frames_are_rejected(){let m=json!({"frames":[{"timestamp_ms":1,"image":"a.jpg"},{"timestamp_ms":2,"image":"a.jpg"}]});assert!(plan(&m,Path::new(".")).is_err());}
    #[test]fn out_of_order_is_not_silently_sorted(){let m=json!({"frames":[{"timestamp_ms":2,"image":"a.jpg"},{"timestamp_ms":1,"image":"b.jpg"}]});assert!(plan(&m,Path::new(".")).is_err());}
}
