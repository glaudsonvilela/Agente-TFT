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

use std::{collections::HashMap,io::{self,BufRead,Read,Write},path::{Path,PathBuf},thread,time::Instant};
use agente_tft_capture_core::{FrameEnvelope,PixelFormat,PixelRect,extract_roi};
use agente_tft_hud_runtime::HudLayout;
use agente_tft_ocr_tesseract::{TesseractConfig,TesseractOcr};
use agente_tft_perception_hud::{HudField,RobustHudRead,read_roi_robust};
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
#[derive(Clone)]
struct HudCacheEntry{pixels:Vec<u8>,read:Option<RobustHudRead>,source_frame_id:u64,source_ms:u64}
#[derive(Clone)]
struct JsonCacheEntry{pixels:Vec<u8>,value:Value,source_frame_id:u64,source_ms:u64,panel_located:Option<bool>}
fn restamp(read:&mut RobustHudRead,at:u64){
    read.batch.observed_at_ms=at;
    if let Some(v)=read.batch.gold.as_mut(){v.observed_at_ms=at;}
    if let Some(v)=read.batch.level.as_mut(){v.observed_at_ms=at;}
    if let Some(v)=read.batch.xp.as_mut(){v.observed_at_ms=at;}
    if let Some(v)=read.batch.stage.as_mut(){v.observed_at_ms=at;}
    if let Some(v)=read.batch.hp.as_mut(){v.observed_at_ms=at;}
}

fn exact_rect_signature(frame:&FrameEnvelope,rects:&[PixelRect])->Result<Vec<u8>,String>{
    let mut out=Vec::new();
    for rect in rects {
        let roi=layout::crop(frame,*rect)?;
        out.extend_from_slice(&roi.pixels);
    }
    Ok(out)
}
fn restamp_json(value:&mut Value,at:u64,source_frame_id:u64,source_ms:u64,delivered_frame_id:u64){
    if let Some(obj)=value.as_object_mut(){
        if obj.contains_key("timestamp_ms"){obj.insert("timestamp_ms".into(),json!(at));}
        obj.insert("cache_delivery".into(),json!({"exact_reader_pixels":true,
            "source_frame_id":source_frame_id,"source_ms":source_ms,
            "delivered_frame_id":delivered_frame_id}));
    }
}
struct Readers{
    hud:HudLayout,ocr:TesseractOcr,shop:layout::ScreenLayout,recovery:recovery::RecoveryProfile,
    controls:controls::ControlsReader,board_profile:profile::Profile,board:Option<scene::SceneReader>,available:bool,
    hud_cache:HashMap<HudField,HudCacheEntry>,shop_cache:Option<JsonCacheEntry>,controls_cache:Option<JsonCacheEntry>,
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
    Ok(Self{hud,ocr,shop,recovery,controls,board_profile,board:None,available,
        hud_cache:HashMap::new(),shop_cache:None,controls_cache:None})
 }
 fn shop_signature(&self,f:&FrameEnvelope)->Result<Vec<u8>,String>{
    let mut rects=Vec::new();
    rects.extend(self.shop.panel_anchors.iter().map(|a|a.rect));
    rects.extend(self.recovery.anchors.iter().map(|a|a.rect));
    rects.extend(self.shop.slots.iter().map(|slot|slot.card));
    exact_rect_signature(f,&rects)
 }
 fn controls_signature(&self,f:&FrameEnvelope)->Result<Vec<u8>,String>{
    let mut rects=Vec::new();
    for spec in &self.controls.profile.controls {
        rects.push(spec.rect);
        if let Some(rect)=spec.price_rect{rects.push(rect);}
        if let Some(rect)=spec.free_count_rect{rects.push(rect);}
    }
    exact_rect_signature(f,&rects)
 }
 fn observe(&mut self,f:&FrameEnvelope)->Result<Value,String>{
    let t=Instant::now();let mut spans=vec![];let mut obs=vec![];let mut state=GameState::empty(f.captured_at_ms);
    state.revision=f.frame_id;let mut attempted=0;
    let mut shop=Value::Null;let mut controls=Value::Null;let mut board=Value::Null;
    let valid_size=(f.width,f.height)==(self.hud.reference_width,self.hud.reference_height);
    if valid_size && self.available {
      let hud_wall_started=ms(&t);
      let mut parallel=Vec::with_capacity(self.hud.regions.len());
      let mut pending=Vec::new();
      for (index,region) in self.hud.regions.iter().enumerate() {
        let roi=extract_roi(f,region.rect).map_err(|e|e.to_string())?;
        if let Some(entry)=self.hud_cache.get(&region.field) {
          if entry.pixels==roi.pixels {
            let mut read=entry.read.clone();
            if let Some(value)=read.as_mut(){restamp(value,f.captured_at_ms);}
            parallel.push((index,region.field,Ok(read),ms(&t),0.0,true,
                           Some((entry.source_frame_id,entry.source_ms))));
            continue;
          }
        }
        pending.push((index,region.field,region.policy.clone(),roi));
      }
      let fresh=thread::scope(|scope|->Result<Vec<_>,String>{
        let mut handles=Vec::with_capacity(pending.len());
        for (index,field,policy,roi) in pending {
          let mut ocr=self.ocr.clone();
          handles.push(scope.spawn(move ||->Result<_,String>{
            let started=ms(&t);
            // Same frozen v3 robust policy/thresholds; only scheduling/cache are different.
            let result=read_roi_robust(&mut ocr,field,&roi,&policy);
            let duration=ms(&t)-started;
            Ok((index,field,result,started,duration,roi.pixels))
          }));
        }
        let mut out=Vec::with_capacity(handles.len());
        for handle in handles {
          out.push(handle.join().map_err(|_|"parallel HUD worker panicked".to_string())??);
        }
        Ok(out)
      })?;
      for (index,field,result,started,duration,pixels) in fresh {
        if let Ok(read)=&result {
          self.hud_cache.insert(field,HudCacheEntry{pixels,read:read.clone(),
              source_frame_id:f.frame_id,source_ms:f.captured_at_ms});
        }
        parallel.push((index,field,result,started,duration,false,None));
      }
      parallel.sort_by_key(|x|x.0);
      let mut hud_cache_hits=0usize;
      for (_,field,result,started,duration,cache_hit,cached_from) in parallel {
        let mut row=json!({"field":field,"value":null,"source_ms":f.captured_at_ms,"status":"unknown"});
        if cache_hit {
          hud_cache_hits+=1;
          if let Some((frame_id,source_ms))=cached_from {
            row["cache_delivery"]=json!({"exact_roi_rgb":true,"source_frame_id":frame_id,
                                          "source_ms":source_ms,"delivered_frame_id":f.frame_id});
          }
        }
        match result {
          Ok(Some(read))=>{
            if !cache_hit { attempted+=read.attempts_made; }
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
                         "duration_ms":duration,"parallel_group":"hud_numeric_v1",
                         "cache_exact_hit":cache_hit,"cache_basis":"exact_roi_rgb_bytes_v1"}));
      }
      spans.push(json!({"stage":"hud_parallel_wall","start_ms":hud_wall_started,
                        "duration_ms":ms(&t)-hud_wall_started,"parallel_fields":self.hud.regions.len(),
                        "exact_roi_cache_hits":hud_cache_hits}));
      let started=ms(&t);
      let shop_pixels=self.shop_signature(f)?;
      let mut located=false;
      let shop_hit=self.shop_cache.as_ref().is_some_and(|entry|entry.pixels==shop_pixels);
      if shop_hit {
        let entry=self.shop_cache.as_ref().expect("shop cache checked");
        shop=entry.value.clone();
        located=entry.panel_located==Some(true);
        restamp_json(&mut shop,f.captured_at_ms,entry.source_frame_id,entry.source_ms,f.frame_id);
      } else {
        match screen::perceive(f,&self.shop,&self.ocr,Some(&self.recovery)) {
         Ok(read)=>{
          located=read.panel_status=="located";
          let cacheable=read.error.is_none();
          shop=serde_json::to_value(read).map_err(|e|e.to_string())?;
          if cacheable {
            self.shop_cache=Some(JsonCacheEntry{pixels:shop_pixels,value:shop.clone(),
                source_frame_id:f.frame_id,source_ms:f.captured_at_ms,panel_located:Some(located)});
          }
         },Err(e)=>{shop=json!({"error":e,"status":"failed"});self.shop_cache=None;}
        }
      }
      spans.push(json!({"stage":"shop_cards","start_ms":started,"duration_ms":ms(&t)-started,
                        "cache_exact_hit":shop_hit,"cache_basis":"all_shop_reader_pixels_v1"}));

      let started=ms(&t);
      let control_pixels=self.controls_signature(f)?;
      let controls_hit=self.controls_cache.as_ref().is_some_and(|entry|
          entry.pixels==control_pixels && entry.panel_located==Some(located));
      if controls_hit {
        let entry=self.controls_cache.as_ref().expect("controls cache checked");
        controls=entry.value.clone();
        restamp_json(&mut controls,f.captured_at_ms,entry.source_frame_id,entry.source_ms,f.frame_id);
      } else {
        match self.controls.read_visual(f,located){
          Ok(mut c)=>{
            let result=control_text::read_numbers(f,&self.controls.profile,&mut c,&self.ocr);
            let cacheable=result.is_ok() && c.error.is_none();
            match result {
             Ok(())=>{
              controls=serde_json::to_value(c).map_err(|e|e.to_string())?;
              if cacheable {
                self.controls_cache=Some(JsonCacheEntry{pixels:control_pixels,value:controls.clone(),
                    source_frame_id:f.frame_id,source_ms:f.captured_at_ms,panel_located:Some(located)});
              }
             },
             Err(e)=>{controls=json!({"error":e,"status":"failed"});self.controls_cache=None;},
            }
          },Err(e)=>{controls=json!({"error":e,"status":"failed"});self.controls_cache=None;},
        }
      }
      spans.push(json!({"stage":"shop_controls","start_ms":started,"duration_ms":ms(&t)-started,
                        "cache_exact_hit":controls_hit,"cache_basis":"all_controls_reader_pixels_v1"}));
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
      "hud_cache_policy":"exact_roi_rgb_bytes_v1","hud_process_calls_exact":null,"resolution_compatible":valid_size,"ocr_available":self.available,
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
 #[test] fn exact_signature_ignores_pixels_outside_registered_rects(){
   let make=|pixels:Vec<u8>|FrameEnvelope{frame_id:1,captured_at_ms:1,width:3,height:2,stride_bytes:9,
      pixel_format:PixelFormat::Rgb8,source_id:"test".into(),pixels};
   let rect=PixelRect{x:1,y:0,width:1,height:1};
   let a=make(vec![1,1,1, 10,11,12, 2,2,2, 3,3,3, 4,4,4, 5,5,5]);
   let outside=make(vec![9,9,9, 10,11,12, 8,8,8, 7,7,7, 6,6,6, 5,5,5]);
   let inside=make(vec![1,1,1, 10,99,12, 2,2,2, 3,3,3, 4,4,4, 5,5,5]);
   assert_eq!(exact_rect_signature(&a,&[rect]).unwrap(),exact_rect_signature(&outside,&[rect]).unwrap());
   assert_ne!(exact_rect_signature(&a,&[rect]).unwrap(),exact_rect_signature(&inside,&[rect]).unwrap());
 }
}
