//! E1 resident, offline-only worker. Existing algorithms, raw RGB input, no capture.
//! Paths reuse frozen implementations rather than copy/reimplement their math/OCR.
#![allow(dead_code)]
#[path="../../../rust/apps/hud-replay-probe/src/media.rs"] mod media;
#[path="../../../rust/apps/shop-replay-probe/src/layout.rs"] mod layout;
#[path="../../../rust/apps/shop-replay-probe/src/screen.rs"] mod screen;
#[path="../../../rust/apps/shop-replay-probe/src/recovery.rs"] mod recovery;
#[path="../../../rust/apps/shop-replay-probe/src/controls.rs"] mod controls;
#[path="../../../rust/apps/shop-replay-probe/src/control_text.rs"] mod control_text;
#[path="../../../rust/apps/shop-replay-probe/src/control_numbers.rs"] mod control_numbers;
#[path="../../../rust/apps/board-replay-probe/src/profile.rs"] mod profile;
#[path="../../../rust/apps/board-replay-probe/src/bars.rs"] mod bars;
#[path="../../../rust/apps/board-replay-probe/src/scene.rs"] mod scene;
mod engine;

use std::{io::{self,BufRead,Read,Write},path::{Path,PathBuf},thread,time::Instant};
use agente_tft_capture_core::{FrameEnvelope,PixelFormat,extract_roi};
use agente_tft_hud_runtime::HudLayout;
use agente_tft_ocr_tesseract::{TesseractConfig,TesseractOcr};
use agente_tft_perception_hud::{HudField,read_roi_robust};
use agente_tft_contracts::GameState;
use serde_json::{Value,json};

fn load<T:serde::de::DeserializeOwned>(path:&Path)->Result<T,String>{
    let m=std::fs::metadata(path).map_err(|e|format!("{}: {e}",path.display()))?;
    if !m.is_file() || m.len()>2*1024*1024{return Err("configuration size/type".into())}
    serde_json::from_slice(&std::fs::read(path).map_err(|e|e.to_string())?).map_err(|e|e.to_string())
}
fn header(r:&mut impl BufRead)->Result<Option<Value>,String>{
    let mut b=Vec::new();let n=r.take(65537).read_until(b'\n',&mut b).map_err(|e|e.to_string())?;
    if n==0{return Ok(None)}
    if n>65536 || b.last()!=Some(&b'\n'){return Err("invalid/oversized protocol header".into())}
    serde_json::from_slice(&b).map(Some).map_err(|e|e.to_string())
}
fn number(v:&Value,k:&str)->Result<u64,String>{v[k].as_u64().ok_or_else(||format!("missing integer {k}"))}
fn frame(h:&Value,r:&mut impl Read)->Result<FrameEnvelope,String>{
    let (w,hh)=(number(h,"width")?,number(h,"height")?);
    if w==0 || hh==0 || w>3840 || hh>2160{return Err("image dimensions outside budget".into())}
    let count=w.checked_mul(hh).and_then(|x|x.checked_mul(3)).ok_or("image overflow")?;
    if number(h,"bytes")?!=count{return Err("RGB payload size mismatch".into())}
    let mut pixels=vec![0;count as usize];r.read_exact(&mut pixels).map_err(|e|e.to_string())?;
    let f=FrameEnvelope{frame_id:number(h,"id")?,captured_at_ms:number(h,"source_ms")?,width:w as u32,height:hh as u32,
      stride_bytes:(w*3) as u32,pixel_format:PixelFormat::Rgb8,source_id:"e1_closed_file_replay".into(),pixels};
    f.validate().map_err(|e|e.to_string())?;Ok(f)
}
fn span(t:&Instant,name:&str,start:f64)->Value{json!({"stage":name,"start_ms":start,"duration_ms":t.elapsed().as_secs_f64()*1000.-start})}
fn ms(t:&Instant)->f64{t.elapsed().as_secs_f64()*1000.}
struct Readers{
    hud:HudLayout,ocr:TesseractOcr,shop:layout::ScreenLayout,recovery:recovery::RecoveryProfile,
    controls:controls::ControlsReader,board_profile:profile::Profile,board:Option<scene::SceneReader>,available:bool,
}
impl Readers{
 fn new(root:&Path,tess:String,controls_path:Option<PathBuf>)->Result<Self,String>{
    let hud:HudLayout=load(&root.join("hud/tft-1920x1080-match001-v3-gray.json"))?;hud.validate().map_err(|e|e.to_string())?;
    let shop:layout::ScreenLayout=load(&root.join("ui/match001-desktop-1920x1080-ptbr-v1.json"))?;shop.validate()?;
    let recovery:recovery::RecoveryProfile=load(&root.join("ui/match001-shop-recovery-v2.json"))?;recovery.validate(&shop)?;
    let c=load(&controls_path.unwrap_or_else(||root.join("ui/match001-shop-controls-v1.json")))?;
    let controls=controls::ControlsReader::new(c,&shop,&recovery)?;
    let board_profile:profile::Profile=load(&root.join("ui/match001-board-bench-v1.json"))?;board_profile.validate()?;
    let ocr=TesseractOcr::new(TesseractConfig{binary:tess,language:"eng".into()}).with_numeric_gray();
    let available=ocr.available();
    Ok(Self{hud,ocr,shop,recovery,controls,board_profile,board:None,available})
 }
 fn observe(&mut self,f:&FrameEnvelope)->Result<Value,String>{
    let t=Instant::now();let mut spans=vec![];let mut obs=vec![];let mut state=GameState::empty(f.captured_at_ms);
    state.revision=f.frame_id;let mut attempted=0;
    let mut shop=Value::Null;let mut controls=Value::Null;let mut board=Value::Null;
    let valid_size=(f.width,f.height)==(self.hud.reference_width,self.hud.reference_height);
    if valid_size && self.available {
      let hud_wall_started=ms(&t);
      let mut parallel=thread::scope(|scope|->Result<Vec<_>,String>{
        let mut handles=Vec::with_capacity(self.hud.regions.len());
        for (index,region) in self.hud.regions.iter().enumerate() {
          let mut ocr=self.ocr.clone();
          handles.push(scope.spawn(move ||->Result<_,String>{
            let started=ms(&t);
            let roi=extract_roi(f,region.rect).map_err(|e|e.to_string())?;
            // Same frozen v3 robust policy/thresholds; only scheduling is parallel.
            let result=read_roi_robust(&mut ocr,region.field,&roi,&region.policy);
            let duration=ms(&t)-started;
            Ok((index,region.field,result,started,duration))
          }));
        }
        let mut out=Vec::with_capacity(handles.len());
        for handle in handles {
          out.push(handle.join().map_err(|_|"parallel HUD worker panicked".to_string())??);
        }
        Ok(out)
      })?;
      parallel.sort_by_key(|x|x.0);
      for (_,field,result,started,duration) in parallel {
        let mut row=json!({"field":field,"value":null,"source_ms":f.captured_at_ms,"status":"unknown"});
        match result {
          Ok(Some(read))=>{
            attempted+=read.attempts_made;
            row["text"]=json!(read.recognized_text);row["confidence"]=json!(read.confidence.value());
            row["status"]=json!("single_frame_observation");
            match field {
             HudField::Gold=>{row["value"]=json!(read.batch.gold.as_ref().map(|x|x.value));state.player.gold=read.batch.gold;}
             HudField::Level=>{row["value"]=json!(read.batch.level.as_ref().map(|x|x.value));state.player.level=read.batch.level;}
             HudField::Xp=>{row["value"]=json!(read.batch.xp.as_ref().map(|x|x.value));state.player.xp=read.batch.xp;}
             HudField::Stage=>{row["value"]=json!(read.batch.stage.as_ref().map(|x|x.value.clone()));state.player.stage=read.batch.stage;}
             _=>{}
            }
          },Ok(None)=>{},Err(e)=>{row["status"]=json!("failed");row["error"]=json!(format!("{e:?}"));}
        }
        obs.push(row);
        spans.push(json!({"stage":format!("hud_{field:?}").to_lowercase(),"start_ms":started,
                         "duration_ms":duration,"parallel_group":"hud_numeric_v1"}));
      }
      spans.push(json!({"stage":"hud_parallel_wall","start_ms":hud_wall_started,
                        "duration_ms":ms(&t)-hud_wall_started,"parallel_fields":self.hud.regions.len()}));
      let started=ms(&t);
      match screen::perceive(f,&self.shop,&self.ocr,Some(&self.recovery)) {
       Ok(read)=>{
        let located=read.panel_status=="located";shop=serde_json::to_value(read).map_err(|e|e.to_string())?;
        spans.push(span(&t,"shop_cards",started));let started=ms(&t);
        match self.controls.read_visual(f,located){
          Ok(mut c)=>{
            match control_text::read_numbers(f,&self.controls.profile,&mut c,&self.ocr){
             Ok(())=>controls=serde_json::to_value(c).map_err(|e|e.to_string())?,
             Err(e)=>controls=json!({"error":e,"status":"failed"}),
            }
          },Err(e)=>controls=json!({"error":e,"status":"failed"}),
        }
        spans.push(span(&t,"shop_controls",started));
       },Err(e)=>{shop=json!({"error":e,"status":"failed"});spans.push(span(&t,"shop_cards",started));}
      }
    }
    if valid_size {if let Some(reader)=&self.board {let started=ms(&t);
      board=match reader.read(f){Ok(b)=>serde_json::to_value(b).map_err(|e|e.to_string())?,Err(e)=>json!({"error":e})};
      spans.push(span(&t,"board_b1",started));
    }}
    let started=ms(&t);
    // No inferred planning phase, identities, HP or fixture facts injected into visual input.
    let (report,decision)=engine::evaluate(&state,Default::default())?;
    spans.push(span(&t,"opportunity_and_decision",started));
    Ok(json!({"id":f.frame_id,"source_ms":f.captured_at_ms,"origin":"observed_pixels",
      "hud":obs,"shop":shop,"controls":controls,"board":board,"state":state,"report":report,"decision":decision,
      "spans":spans,"native_ms":ms(&t),"hud_accepted_attempts_lower_bound":attempted,
      "hud_process_calls_exact":null,"resolution_compatible":valid_size,"ocr_available":self.available,
      "blockers":["planning_phase_not_observed","unit_identity_not_bound","board_and_hp_unvalidated"],
      "canonical_game_state_updated":false,"temporal_consensus":false,"profile_promoted":false}))
 }
}
fn main(){if let Err(e)=run(){eprintln!("E1_WORKER_ERROR={e}");std::process::exit(2)}}
fn run()->Result<(),String>{
    let args:Vec<_>=std::env::args().skip(1).collect();
    if args.len()<2 || args[0]!="--configs"{return Err("usage: e1-worker --configs <dir> [tesseract] [controls.json]".into())}
    let mut readers=Readers::new(Path::new(&args[1]),args.get(2).cloned().unwrap_or("tesseract".into()),args.get(3).map(PathBuf::from))?;
    let mut input=io::BufReader::new(io::stdin());let mut output=io::BufWriter::new(io::stdout());
    writeln!(output,"{}",json!({"ready":true,"protocol":1,"ocr_available":readers.available,"pid":std::process::id()})).map_err(|e|e.to_string())?;
    output.flush().map_err(|e|e.to_string())?;
    while let Some(h)=header(&mut input)?{
      let id=number(&h,"id")?;
      let out=match h["op"].as_str(){
       Some("frame")=>readers.observe(&frame(&h,&mut input)?)?,
       Some("fixture")=>engine::fixture(id,number(&h,"source_ms")?,number(&h,"case")? as usize)?,
       Some("reference")=>{
        let f=frame(&h,&mut input)?;readers.board=Some(scene::SceneReader::new(readers.board_profile.clone(),&f)?);
        json!({"id":id,"reference_ready":true})
       },Some("stop")=>break,_=>return Err("unknown operation".into()),
      };
      writeln!(output,"{out}").map_err(|e|e.to_string())?;output.flush().map_err(|e|e.to_string())?;
    }Ok(())
}
#[cfg(test)] mod tests{
 use super::*;
 #[test] fn protocol_rejects_oversize_header(){assert!(header(&mut io::Cursor::new(vec![b'x';65537])).is_err())}
 #[test] fn protocol_eof(){assert!(header(&mut io::Cursor::new(Vec::<u8>::new())).unwrap().is_none())}
 #[test] fn payload_size_not_guessed(){let h=json!({"id":1,"source_ms":0,"width":2,"height":2,"bytes":16});assert!(frame(&h,&mut io::empty()).is_err())}
 #[test] fn payload_timestamp_preserved(){let h=json!({"id":2,"source_ms":1234,"width":1,"height":1,"bytes":3});let f=frame(&h,&mut io::Cursor::new([1,2,3])).unwrap();assert_eq!(f.captured_at_ms,1234);assert_eq!(f.pixels,vec![1,2,3]);}
}
