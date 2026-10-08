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
mod stage;
mod trait_panel;
mod opponent_panel;
mod live_rank;
mod combat_facts;
mod match_memory;
mod match_brain;
mod match_plan;
mod fast_marker_track;

use std::{collections::HashMap,io::{self,BufRead,Read,Write},path::{Path,PathBuf},thread,time::Instant,
          sync::mpsc::{self,TrySendError}};
#[cfg(any(windows,target_os="linux"))] use std::sync::Mutex;
use agente_tft_capture_core::{FrameEnvelope,PixelFormat,PixelRect,extract_roi};
use agente_tft_hud_runtime::HudLayout;
use agente_tft_ocr_tesseract::{TesseractConfig,TesseractOcr};
#[cfg(any(windows,target_os="linux"))] use agente_tft_ocr_tesseract::ResidentTesseractOcr;
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
#[derive(Clone)]
struct ShopNameTrack {
    name:String,key:String,first_ms:u64,last_ms:u64,last_frame_id:u64,
    confirmations:u8,min_score:f32,
}
fn advance_shop_name_track(previous:Option<ShopNameTrack>,name:&str,score:f32,at:u64,frame_id:u64)->ShopNameTrack{
    let key=screen::normalize(name);
    if let Some(mut track)=previous {
        if track.key==key && track.last_frame_id!=frame_id
            && at>=track.last_ms && at-track.last_ms<=3000 {
            track.confirmations=track.confirmations.saturating_add(1);
            track.min_score=track.min_score.min(score);
            track.last_ms=at;
            track.last_frame_id=frame_id;
            return track;
        }
    }
    ShopNameTrack{name:name.into(),key,first_ms:at,last_ms:at,last_frame_id:frame_id,
        confirmations:1,min_score:score}
}
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
fn cadence_json(value:&Value,source_frame_id:u64,source_ms:u64,delivered_frame_id:u64,delivered_ms:u64)->Value{
    let mut out=value.clone();
    if let Some(obj)=out.as_object_mut(){
        obj.insert("cadence_delivery".into(),json!({
            "fresh":false,
            "source_frame_id":source_frame_id,
            "source_ms":source_ms,
            "delivered_frame_id":delivered_frame_id,
            "delivered_source_ms":delivered_ms,
            "age_ms":delivered_ms.saturating_sub(source_ms),
            "policy":"hm4_shop_2s_v1"
        }));
    }
    out
}
#[cfg(any(windows,target_os="linux"))]
struct ResidentHudPool{
    stage:Mutex<ResidentTesseractOcr>,gold:Mutex<ResidentTesseractOcr>,
    level:Mutex<ResidentTesseractOcr>,xp:Mutex<ResidentTesseractOcr>,
}
#[cfg(any(windows,target_os="linux"))]
impl ResidentHudPool{
    fn new(binary:&str)->Result<Self,String>{
        let make=||ResidentTesseractOcr::from_cli_path(binary,"eng").map(|x|x.with_numeric_gray());
        Ok(Self{stage:Mutex::new(make()?),gold:Mutex::new(make()?),
                level:Mutex::new(make()?),xp:Mutex::new(make()?)})
    }
    fn engine(&self,field:HudField)->Result<&Mutex<ResidentTesseractOcr>,String>{
        match field{
            HudField::Stage=>Ok(&self.stage),HudField::Gold=>Ok(&self.gold),
            HudField::Level=>Ok(&self.level),HudField::Xp=>Ok(&self.xp),
            _=>Err("resident numeric HUD pool received unsupported field".into()),
        }
    }
}

struct Readers{
    hud:HudLayout,ocr:TesseractOcr,shop:layout::ScreenLayout,recovery:recovery::RecoveryProfile,
    stage:stage::Reader,
    controls:controls::ControlsReader,board_profile:profile::Profile,board:Option<scene::SceneReader>,available:bool,
    ocr_backend:&'static str,text_ocr_backend:&'static str,ocr_fallback_error:Option<String>,
    #[cfg(any(windows,target_os="linux"))] resident_hud:Option<ResidentHudPool>,
    #[cfg(any(windows,target_os="linux"))] resident_text:Option<ResidentTesseractOcr>,
    hud_cache:HashMap<HudField,HudCacheEntry>,shop_cache:Option<JsonCacheEntry>,controls_cache:Option<JsonCacheEntry>,
    shop_name_tracks:[Option<ShopNameTrack>;5],
}
impl Readers{
 fn new(root:&Path,tess:String,controls_path:Option<PathBuf>)->Result<Self,String>{
    let hud:HudLayout=load(&root.join("hud/tft-1920x1080-match001-v3-gray.json"))?;hud.validate().map_err(|e|e.to_string())?;
    let stage=stage::Reader::new(load(&root.join("hud/tft-1920x1080-match001-v4-stage-recovery.json"))?)?;
    let shop:layout::ScreenLayout=load(&root.join("ui/match001-desktop-1920x1080-ptbr-v1.json"))?;shop.validate()?;
    let recovery:recovery::RecoveryProfile=load(&root.join("ui/match001-shop-recovery-v2.json"))?;recovery.validate(&shop)?;
    let c=load(&controls_path.unwrap_or_else(||root.join("ui/match001-shop-controls-v1.json")))?;
    let controls=controls::ControlsReader::new(c,&shop,&recovery)?;
    let board_profile:profile::Profile=load(&root.join("ui/match001-board-bench-v1.json"))?;board_profile.validate()?;
    let resident_mode=std::env::var("AGENTE_TFT_RESIDENT_OCR").unwrap_or_else(|_|"0".into());
    let shop_only=std::env::var("AGENTE_TFT_SHOP_ONLY").as_deref()==Ok("1");
    #[cfg(any(windows,target_os="linux"))]
    let make_resident_suite=||->Result<(Option<ResidentHudPool>,ResidentTesseractOcr),String>{
        let hud=if shop_only {None}else{Some(ResidentHudPool::new(&tess)?)};
        let text=ResidentTesseractOcr::from_cli_path(&tess,"eng")?.with_numeric_gray();
        Ok((hud,text))
    };
    #[cfg(any(windows,target_os="linux"))]
    let (resident_hud,resident_text,ocr_fallback_error)=match resident_mode.as_str(){
        ""|"0"=>(None,None,None),
        "1"|"required"=>{
            let (hud,text)=make_resident_suite()?;
            (hud,Some(text),None)
        },
        "auto"=>match make_resident_suite(){
            Ok((hud,text))=>(hud,Some(text),None),
            Err(error)=>(None,None,Some(error)),
        },
        other=>return Err(format!("invalid AGENTE_TFT_RESIDENT_OCR mode: {other}")),
    };
    #[cfg(not(any(windows,target_os="linux")))]
    let (resident_hud_unused,ocr_fallback_error)=match resident_mode.as_str(){
        ""|"0"=>(None::<()>,None),
        other=>return Err(format!("AGENTE_TFT_RESIDENT_OCR={other} is unsupported on this platform")),
    };
    #[cfg(not(any(windows,target_os="linux")))]
    let _=resident_hud_unused;
    #[cfg(any(windows,target_os="linux"))]
    let ocr_backend=if resident_hud.is_some(){"resident_tesseract_c_api_v1"}
        else if ocr_fallback_error.is_some(){"cli_process_fallback_v1"}else{"cli_process_v1"};
    #[cfg(any(windows,target_os="linux"))]
    let text_ocr_backend=if resident_text.is_some(){"resident_tesseract_c_api_text_v1"}
        else if ocr_fallback_error.is_some(){"cli_process_fallback_v1"}else{"cli_process_v1"};
    #[cfg(not(any(windows,target_os="linux")))]
    let ocr_backend="cli_process_v1";
    #[cfg(not(any(windows,target_os="linux")))]
    let text_ocr_backend="cli_process_v1";
    let ocr=TesseractOcr::new(TesseractConfig{binary:tess,language:"eng".into()}).with_numeric_gray();
    // A resident suite can read frames even when the companion CLI cannot start.
    #[cfg(any(windows,target_os="linux"))]
    let available=resident_hud.is_some() || resident_text.is_some() || ocr.available();
    #[cfg(not(any(windows,target_os="linux")))]
    let available=ocr.available();
    let anchors_path=root.join("ui/standard-arena-anchors-v1.json");
    let board=if !shop_only && anchors_path.is_file() {
        let anchors:Value=load(&anchors_path)?;
        if anchors["schema_version"]!=1 || anchors["profile"]!=board_profile.id {
            return Err("packaged arena profile mismatch".into());
        }
        let reference=serde_json::from_value(anchors["arena_reference"].clone()).map_err(|e|e.to_string())?;
        Some(scene::SceneReader::from_anchors(board_profile.clone(),reference)?)
    } else {None};
    Ok(Self{hud,stage,ocr,shop,recovery,controls,board_profile,board,available,ocr_backend,text_ocr_backend,ocr_fallback_error,
        #[cfg(any(windows,target_os="linux"))] resident_hud,
        #[cfg(any(windows,target_os="linux"))] resident_text,
        hud_cache:HashMap::new(),shop_cache:None,controls_cache:None,
        shop_name_tracks:std::array::from_fn(|_|None)})
 }
 fn reconcile_shop_names(&mut self,f:&FrameEnvelope,read:&mut screen::ScreenRead){
    if read.panel_status!="located" {
        self.shop_name_tracks=std::array::from_fn(|_|None);
        return;
    }
    for (index,slot) in read.slots.iter_mut().enumerate(){
        if slot.name_evidence.as_deref()==Some("atlas_strip_conflict") {
            self.shop_name_tracks[index]=None;
            continue;
        }
        let candidate=slot.strip_name_attempt.as_ref().filter(|attempt|attempt.reason=="eligible")
            .and_then(|attempt|attempt.text.as_deref().zip(attempt.confidence));
        let Some((name,score))=candidate else {
            self.shop_name_tracks[index]=None;
            continue;
        };
        if !score.is_finite() || score<0.85 {
            self.shop_name_tracks[index]=None;
            continue;
        }
        let track=advance_shop_name_track(self.shop_name_tracks[index].take(),name,score,
            f.captured_at_ms,f.frame_id);
        if track.confirmations>=2 && track.last_ms-track.first_ms>=250 {
            if slot.observed_name.is_none() {
                slot.observed_name=Some(track.name.clone());
                slot.name_confidence=Some(track.min_score);
                slot.name_evidence=Some("strip_temporal_consensus".into());
                slot.status=if slot.observed_cost.is_some(){"offer_text_readable"}
                    else{"partially_readable"}.into();
            } else if slot.name_confidence.is_some_and(|confidence|confidence<0.90)
                && slot.observed_name.as_ref().is_some_and(|current|
                    screen::normalize(current)==track.key) {
                slot.name_evidence=Some("atlas_strip_temporal_consensus".into());
            }
        }
        self.shop_name_tracks[index]=Some(track);
    }
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
 fn observe_shop_fields(&mut self,f:&FrameEnvelope)->Result<(Value,Value,Vec<Value>),String>{
      let t=Instant::now();
      let mut spans=Vec::new();
      let mut shop:Value;
      let mut controls:Value;
      let mut located=false;
      let started=ms(&t);
      let shop_pixels=self.shop_signature(f)?;
      let shop_hit=self.shop_cache.as_ref().is_some_and(|entry|entry.pixels==shop_pixels);
      if shop_hit {
        let entry=self.shop_cache.as_ref().expect("shop cache checked");
        shop=entry.value.clone();
        located=entry.panel_located==Some(true);
        restamp_json(&mut shop,f.captured_at_ms,entry.source_frame_id,entry.source_ms,f.frame_id);
      } else {
        #[cfg(any(windows,target_os="linux"))]
        let shop_read=if let Some(engine)=self.resident_text.as_mut(){
            screen::perceive_with_name_fallback(f,&self.shop,engine,Some(&self.recovery),true)
        }else{
            screen::perceive_with_name_fallback(f,&self.shop,&mut self.ocr,Some(&self.recovery),true)
        };
        #[cfg(not(any(windows,target_os="linux")))]
        let shop_read=screen::perceive_with_name_fallback(f,&self.shop,&mut self.ocr,Some(&self.recovery),true);
        match shop_read {
         Ok(mut read)=>{
          self.reconcile_shop_names(f,&mut read);
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
            #[cfg(any(windows,target_os="linux"))]
            let result=if let Some(engine)=self.resident_text.as_mut(){
                control_text::read_numbers(f,&self.controls.profile,&mut c,engine)
            }else{
                control_text::read_numbers(f,&self.controls.profile,&mut c,&mut self.ocr)
            };
            #[cfg(not(any(windows,target_os="linux")))]
            let result=control_text::read_numbers(f,&self.controls.profile,&mut c,&mut self.ocr);
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
      for value in [&mut shop,&mut controls] {
          if value.is_object() && value["error"].is_null() {
              value["cadence_delivery"]=json!({"fresh":true,"delivered_frame_id":f.frame_id,
                  "delivered_source_ms":f.captured_at_ms,"age_ms":0,"policy":"current_frame_v1"});
          }
      }
      Ok((shop,controls,spans))
 }
 fn observe_shop_only(&mut self,f:&FrameEnvelope)->Result<Value,String>{
      let t=Instant::now();
      let valid_size=(f.width,f.height)==(self.hud.reference_width,self.hud.reference_height);
      if !valid_size || !self.available {
          return Ok(json!({"id":f.frame_id,"source_ms":f.captured_at_ms,
              "shop":{"panel_status":"unavailable","slots":[]},
              "controls":{"status":"unavailable"},"resolution_compatible":valid_size,
              "ocr_available":self.available,"native_ms":ms(&t)}));
      }
      let (shop,controls,spans)=self.observe_shop_fields(f)?;
      Ok(json!({"id":f.frame_id,"source_ms":f.captured_at_ms,
          "origin":"observed_pixels","shop":shop,"controls":controls,
          "spans":spans,"native_ms":ms(&t),"resolution_compatible":true,
          "ocr_available":self.available}))
 }
 fn observe(&mut self,f:&FrameEnvelope,include_shop:bool)->Result<Value,String>{
    let t=Instant::now();let mut spans=vec![];let mut obs=vec![];let mut state=GameState::empty(f.captured_at_ms);
    state.revision=f.frame_id;let mut attempted=0;
    let mut shop=Value::Null;let mut controls=Value::Null;let mut board=Value::Null;
    let valid_size=(f.width,f.height)==(self.hud.reference_width,self.hud.reference_height);
    if valid_size && self.available {
      let hud_wall_started=ms(&t);
      let mut parallel=Vec::with_capacity(self.hud.regions.len());
      let mut pending=Vec::new();
      let stage_started=ms(&t);
      #[cfg(any(windows,target_os="linux"))]
      let stage=if let Some(pool)=self.resident_hud.as_ref(){
          let mut ocr=pool.stage.lock().map_err(|_|"resident stage OCR mutex poisoned")?;
          self.stage.observe(f,&mut *ocr)?
      }else{self.stage.observe(f,&mut self.ocr)?};
      #[cfg(not(any(windows,target_os="linux")))]
      let stage=self.stage.observe(f,&mut self.ocr)?;
      let stage_duration=ms(&t)-stage_started;
      for (index,region) in self.hud.regions.iter().enumerate() {
        if region.field==HudField::Stage {
            parallel.push((index,region.field,Ok(stage.read.clone()),stage_started,stage_duration,stage.cache_hit,None));
            continue;
        }
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
          #[cfg(any(windows,target_os="linux"))]
          if let Some(pool)=self.resident_hud.as_ref(){
            let engine=pool.engine(field)?;
            handles.push(scope.spawn(move ||->Result<_,String>{
              let started=ms(&t);
              let mut ocr=engine.lock().map_err(|_|"resident OCR mutex poisoned".to_string())?;
              // Frozen v3 policy/thresholds; only backend residency changes under explicit opt-in.
              let result=read_roi_robust(&mut *ocr,field,&roi,&policy);
              let duration=ms(&t)-started;
              Ok((index,field,result,started,duration,roi.pixels))
            }));
            continue;
          }
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
        if field==HudField::Stage {
            row["localization"]=stage.details.clone();
            if let Some(delivery)=stage.details.get("cache_delivery") {row["cache_delivery"]=delivery.clone();}
        }
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
      if !include_shop {
        shop=match self.shop_cache.as_ref() {
          Some(entry)=>{
            let mut value=cadence_json(&entry.value,entry.source_frame_id,entry.source_ms,f.frame_id,f.captured_at_ms);
            if entry.pixels==self.shop_signature(f)? {
                restamp_json(&mut value,f.captured_at_ms,entry.source_frame_id,entry.source_ms,f.frame_id);
                value["cadence_delivery"]["fresh"]=json!(true);
                value["cadence_delivery"]["exact_reader_pixels"]=json!(true);
            }
            value
          },
          None=>json!({"timestamp_ms":f.captured_at_ms,"panel_status":"cadence_deferred_no_prior_observation",
                       "slots":[],"cadence_delivery":{"fresh":false,"policy":"hm4_shop_2s_v1"}}),
        };
        controls=match self.controls_cache.as_ref() {
          Some(entry)=>{
            let mut value=cadence_json(&entry.value,entry.source_frame_id,entry.source_ms,f.frame_id,f.captured_at_ms);
            if entry.pixels==self.controls_signature(f)? {
                restamp_json(&mut value,f.captured_at_ms,entry.source_frame_id,entry.source_ms,f.frame_id);
                value["cadence_delivery"]["fresh"]=json!(true);
                value["cadence_delivery"]["exact_reader_pixels"]=json!(true);
            }
            value
          },
          None=>json!({"timestamp_ms":f.captured_at_ms,"status":"cadence_deferred_no_prior_observation",
                       "cadence_delivery":{"fresh":false,"policy":"hm4_shop_2s_v1"}}),
        };
        spans.push(json!({"stage":"shop_cadence_reuse","start_ms":started,"duration_ms":ms(&t)-started,
                          "shop_executed":false,"policy":"hm4_shop_2s_v1"}));
      } else {
      let (read_shop,read_controls,mut shop_spans)=self.observe_shop_fields(f)?;
      shop=read_shop;
      controls=read_controls;
      spans.append(&mut shop_spans);
      }
    }
    if valid_size && std::env::var("AGENTE_TFT_SKIP_BOARD").as_deref()!=Ok("1") {
      if let Some(reader)=&self.board {let started=ms(&t);
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
      "hud_cache_policy":"exact_roi_rgb_bytes_v1","hud_process_calls_exact":null,
      "shop_requested":include_shop,"resolution_compatible":valid_size,"ocr_available":self.available,
       "numeric_hud_ocr_backend":self.ocr_backend,"spatial_text_ocr_backend":self.text_ocr_backend,
        "numeric_hud_ocr_fallback_error":self.ocr_fallback_error,
      "blockers":["planning_phase_not_observed","unit_identity_not_bound","board_and_hp_unvalidated"],
      "canonical_game_state_updated":false,"temporal_consensus":false,"profile_promoted":false}))
 }
}
fn main(){if let Err(e)=run(){eprintln!("E1_WORKER_ERROR={e}");std::process::exit(2)}}
fn run()->Result<(),String>{
    let args:Vec<_>=std::env::args().skip(1).collect();
    if args.len()<2 || args[0]!="--configs"{return Err("usage: e1-worker --configs <dir> [tesseract] [controls.json]".into())}
    if std::env::var("AGENTE_TFT_MARKERS_ONLY").as_deref()==Ok("1") {
        return markers_only(Path::new(&args[1]));
    }
    if std::env::var("AGENTE_TFT_BOARD_ONLY").as_deref()==Ok("1") {
        return board_only(Path::new(&args[1]),args.get(2).map(String::as_str).unwrap_or("tesseract"));
    }
    if std::env::var("AGENTE_TFT_SHOP_ONLY").as_deref()==Ok("1") {
        return shop_only(Path::new(&args[1]),args.get(2).map(String::as_str).unwrap_or("tesseract"),
            args.get(3).map(PathBuf::from));
    }
    let mut readers=Readers::new(Path::new(&args[1]),args.get(2).cloned().unwrap_or("tesseract".into()),args.get(3).map(PathBuf::from))?;
    let mut input=io::BufReader::new(io::stdin());let mut output=io::BufWriter::new(io::stdout());
    let mut memory=match_memory::from_environment();
    writeln!(output,"{}",json!({"ready":true,"protocol":1,"rank_advice":true,"ack_advice":true,"match_event":true,"match_memory":true,"combat_facts":true,"ocr_available":readers.available,"numeric_hud_ocr_backend":readers.ocr_backend,
        "spatial_text_ocr_backend":readers.text_ocr_backend,"numeric_hud_ocr_fallback_error":readers.ocr_fallback_error,"pid":std::process::id()})).map_err(|e|e.to_string())?;
    output.flush().map_err(|e|e.to_string())?;
    while let Some(h)=header(&mut input)?{
      let id=number(&h,"id")?;
      let out=match h["op"].as_str(){
       Some("frame")=>readers.observe(&frame(&h,&mut input)?,h["include_shop"].as_bool().unwrap_or(true))?,
       Some("fixture")=>engine::fixture(id,number(&h,"source_ms")?,number(&h,"case")? as usize)?,
       Some("rank_advice")=>live_rank::rank(&h,&mut memory)?,
       Some("ack_advice")=>live_rank::acknowledge(&h,&mut memory)?,
       Some("match_event")=>live_rank::observe_event(&h,&mut memory)?,
       Some("combat_facts")=>combat_facts::analyze(&h)?,
       Some("reference")=>{
        let f=frame(&h,&mut input)?;readers.board=Some(scene::SceneReader::new(readers.board_profile.clone(),&f)?);
        json!({"id":id,"reference_ready":true})
       },Some("stop")=>break,_=>return Err("unknown operation".into()),
      };
      writeln!(output,"{out}").map_err(|e|e.to_string())?;output.flush().map_err(|e|e.to_string())?;
    }Ok(())
}

// The shop lane performs only shop and control OCR. HUD, board and strategy
// stay in their own workers so a two-second shop read cannot duplicate them.
fn shop_only(root:&Path,tess:&str,controls_path:Option<PathBuf>)->Result<(),String>{
    let mut readers=Readers::new(root,tess.to_string(),controls_path)?;
    let mut input=io::BufReader::new(io::stdin());
    let mut output=io::BufWriter::new(io::stdout());
    writeln!(output,"{}",json!({"ready":true,"protocol":1,"shop_only":true,
        "ocr_available":readers.available,"pid":std::process::id()}))
        .map_err(|e|e.to_string())?;
    output.flush().map_err(|e|e.to_string())?;
    while let Some(h)=header(&mut input)? {
        if h["op"]=="stop" {break;}
        if h["op"]!="frame" {return Err("unknown shop operation".into());}
        let f=frame(&h,&mut input)?;
        let out=readers.observe_shop_only(&f)?;
        writeln!(output,"{out}").map_err(|e|e.to_string())?;
        output.flush().map_err(|e|e.to_string())?;
    }
    Ok(())
}

// Cheap, OCR-free visual continuity for the diagnostic preview. Color and track
// position are observations, not unit identity or side-of-board evidence.
fn markers_only(root:&Path)->Result<(),String>{
    let profile:profile::Profile=load(&root.join("ui/match001-board-bench-v1.json"))?;
    profile.validate()?;
    let mut tracker=fast_marker_track::FastMarkerTrack::default();
    let mut input=io::BufReader::new(io::stdin());
    let mut output=io::BufWriter::new(io::stdout());
    writeln!(output,"{}",json!({"ready":true,"protocol":1,"fast_marker_tracking":true,
        "ocr_available":false,"pid":std::process::id()})).map_err(|e|e.to_string())?;
    output.flush().map_err(|e|e.to_string())?;
    while let Some(h)=header(&mut input)? {
        let id=number(&h,"id")?;
        if h["op"]=="stop" {break;}
        if h["op"]!="markers" {return Err("unknown marker operation".into());}
        let f=frame(&h,&mut input)?;
        let started=Instant::now();
        let mut markers=bars::detect(&f,profile.scan_rect,&profile.bars)?;
        markers.extend(fast_marker_track::detect_avatar_bars(&f,profile.scan_rect));
        let tracks=tracker.update(&markers,number(&h,"epoch")?,f.captured_at_ms);
        writeln!(output,"{}",json!({"id":id,"source_ms":f.captured_at_ms,
            "origin":"rust_fast_marker_tracker_v1","markers":tracks,"native_ms":ms(&started)}))
            .map_err(|e|e.to_string())?;
        output.flush().map_err(|e|e.to_string())?;
    }
    Ok(())
}

// Independent board worker. Its two small OCR panels run at a bounded cadence;
// a slow shop read in the main worker cannot hold up a fresh board frame.
fn board_only(root:&Path,tess:&str)->Result<(),String>{
    let profile:profile::Profile=load(&root.join("ui/match001-board-bench-v1.json"))?;
    profile.validate()?;
    let anchors:Value=load(&root.join("ui/standard-arena-anchors-v1.json"))?;
    if anchors["schema_version"]!=1 || anchors["profile"]!=profile.id {
        return Err("packaged arena profile mismatch".into());
    }
    let reference=serde_json::from_value(anchors["arena_reference"].clone()).map_err(|e|e.to_string())?;
    let mut reader=scene::SceneReader::from_anchors(profile.clone(),reference)?;
    let (trait_tx,trait_rx)=mpsc::sync_channel::<FrameEnvelope>(1);
    let (trait_result_tx,trait_result_rx)=mpsc::channel::<Value>();
    let trait_tess=tess.to_string();
    let trait_thread=thread::Builder::new().name("trait-panel-ocr".into()).spawn(move ||{
        #[cfg(any(windows,target_os="linux"))]
        let mut resident=ResidentTesseractOcr::from_cli_path(&trait_tess,"eng").ok();
        let mut cli=TesseractOcr::new(TesseractConfig{binary:trait_tess,language:"eng".into()});
        let mut previous:Option<(Vec<u8>,Value)>=None;
        for frame in trait_rx {
            let started=Instant::now();
            let read=match exact_rect_signature(&frame,&[trait_panel::PANEL]) {
                Ok(pixels)=>{
                    let cached=previous.as_ref().and_then(|(old,value)|
                        if old==&pixels {Some(value.clone())}else{None});
                    if let Some(mut value)=cached {
                        value["status"]=json!("exact_pixels_cached");
                        value
                    }else{
                        #[cfg(any(windows,target_os="linux"))]
                        let result=if let Some(engine)=resident.as_mut(){
                            trait_panel::observe(&frame,engine)
                        }else{trait_panel::observe(&frame,&mut cli)};
                        #[cfg(not(any(windows,target_os="linux")))]
                        let result=trait_panel::observe(&frame,&mut cli);
                        let value=result.unwrap_or_else(|error|json!({"status":"read_error","error":error}));
                        previous=Some((pixels,value.clone()));
                        value
                    }
                },Err(error)=>json!({"status":"read_error","error":error})
            };
            let mut read=read;
            read["processing_ms"]=json!(ms(&started));
            if trait_result_tx.send(read).is_err(){break}
        }
    }).map_err(|e|format!("trait OCR thread: {e}"))?;
    let mut latest_traits=json!({"status":"async_pending","words":[]});
    let mut last_trait_submit:Option<u64>=None;
    let (opponent_tx,opponent_rx)=mpsc::sync_channel::<FrameEnvelope>(1);
    let (opponent_result_tx,opponent_result_rx)=mpsc::channel::<Value>();
    let opponent_tess=tess.to_string();
    let opponent_thread=thread::Builder::new().name("opponent-panel-ocr".into()).spawn(move ||{
        #[cfg(any(windows,target_os="linux"))]
        let mut resident=ResidentTesseractOcr::from_cli_path(&opponent_tess,"eng").ok();
        let mut text_cli=TesseractOcr::new(TesseractConfig{binary:opponent_tess.clone(),language:"eng".into()});
        let mut numbers_cli=TesseractOcr::new(TesseractConfig{binary:opponent_tess,language:"eng".into()});
        let mut previous:Option<(Vec<u8>,Value)>=None;
        for frame in opponent_rx {
            let started=Instant::now();
            let pixels=exact_rect_signature(&frame,&[
                opponent_panel::PANEL,opponent_panel::BATTLE_NAME,
                opponent_panel::ENEMY_NAME,opponent_panel::SELF_OVERLAY,
                opponent_panel::HP_PANEL]);
            let read=match pixels {
                Ok(pixels)=>{
                    let cached=previous.as_ref().and_then(|(old,value)|
                        if old==&pixels {Some(value.clone())}else{None});
                    if let Some(mut value)=cached {
                        value["status"]=json!("exact_pixels_cached");
                        value
                    }else{
                        #[cfg(any(windows,target_os="linux"))]
                        let result=if let Some(engine)=resident.as_mut(){
                            opponent_panel::observe(&frame,engine,&mut numbers_cli)
                        }else{opponent_panel::observe(&frame,&mut text_cli,&mut numbers_cli)};
                        #[cfg(not(any(windows,target_os="linux")))]
                        let result=opponent_panel::observe(&frame,&mut text_cli,&mut numbers_cli);
                        let value=result.unwrap_or_else(|error|json!({"status":"read_error","error":error}));
                        previous=Some((pixels,value.clone()));
                        value
                    }
                },Err(error)=>json!({"status":"read_error","error":error})
            };
            let mut read=read;
            read["processing_ms"]=json!(ms(&started));
            if opponent_result_tx.send(read).is_err(){break}
        }
    }).map_err(|e|format!("opponent OCR thread: {e}"))?;
    let mut latest_opponents=json!({"status":"async_pending","words":[],"battle_name_words":[]});
    let mut last_opponent_submit:Option<u64>=None;
    let mut input=io::BufReader::new(io::stdin());let mut output=io::BufWriter::new(io::stdout());
    writeln!(output,"{}",json!({"ready":true,"protocol":1,"board_only":true,"ocr_available":false,
        "pid":std::process::id()})).map_err(|e|e.to_string())?;
    output.flush().map_err(|e|e.to_string())?;
    while let Some(h)=header(&mut input)? {
        let id=number(&h,"id")?;
        if h["op"]=="stop" {break;}
        if h["op"]!="frame" && h["op"]!="reference" {return Err("unknown board-only operation".into());}
        let f=frame(&h,&mut input)?;
        let started=Instant::now();
        let out=if h["op"]=="reference" {
            match scene::SceneReader::new(profile.clone(),&f) {
                Ok(next)=>{reader=next;json!({"id":id,"reference_ready":true})},
                Err(error)=>json!({"id":id,"reference_ready":false,"error":error}),
            }
        } else {
            let board=reader.read(&f)?;
            let active=serde_json::to_value(&board).map_err(|e|e.to_string())?["markers"]
                .as_array().is_some_and(|rows| !rows.is_empty());
            let mut fresh_traits=false;
            while let Ok(result)=trait_result_rx.try_recv(){
                latest_traits=result;
                fresh_traits=true;
            }
            if active && last_trait_submit.map_or(true,|at|
                    f.captured_at_ms<at || f.captured_at_ms.saturating_sub(at)>=1000){
                match trait_tx.try_send(f.clone()){
                    Ok(())=>last_trait_submit=Some(f.captured_at_ms),
                    Err(TrySendError::Full(_))=>{},
                    Err(TrySendError::Disconnected(_))=>return Err("trait OCR thread ended".into()),
                }
            }
            let mut traits=if active {latest_traits.clone()}
                else {json!({"status":"panel_not_visible","words":[]})};
            if active {
                if let Some(at)=traits["source_ms"].as_u64(){
                    let age=f.captured_at_ms.saturating_sub(at);
                    traits["age_ms"]=json!(age);
                    if age>10000 {traits["status"]=json!("async_stale");}
                    else if !fresh_traits && traits["status"]=="raw_ocr" {
                        traits["status"]=json!("cadence_cached");
                    }
                }
            }
            let mut fresh_opponents=false;
            while let Ok(result)=opponent_result_rx.try_recv(){
                latest_opponents=result;
                fresh_opponents=true;
            }
            if last_opponent_submit.map_or(true,|at|
                    f.captured_at_ms<at || f.captured_at_ms.saturating_sub(at)>=5000){
                match opponent_tx.try_send(f.clone()){
                    Ok(())=>last_opponent_submit=Some(f.captured_at_ms),
                    Err(TrySendError::Full(_))=>{},
                    Err(TrySendError::Disconnected(_))=>return Err("opponent OCR thread ended".into()),
                }
            }
            let mut opponents=latest_opponents.clone();
            if let Some(at)=opponents["source_ms"].as_u64(){
                let age=f.captured_at_ms.saturating_sub(at);
                opponents["age_ms"]=json!(age);
                if age>10000 {opponents["status"]=json!("async_stale");}
                else if !fresh_opponents && opponents["status"]=="raw_ocr" {
                    opponents["status"]=json!("cadence_cached");
                }
            }
            json!({"id":id,"source_ms":f.captured_at_ms,"board":board,
                "trait_panel":traits,"opponent_panel":opponents,"native_ms":ms(&started),
                "ocr_process_calls":if active && fresh_traits && traits["status"]=="raw_ocr" {1}else{0},
                "trait_ocr_async":true,"opponent_ocr_async":true})
        };
        writeln!(output,"{out}").map_err(|e|e.to_string())?;output.flush().map_err(|e|e.to_string())?;
    }
    drop(trait_tx);
    let _=trait_thread.join();
    drop(opponent_tx);
    let _=opponent_thread.join();
    Ok(())
}
#[cfg(test)] mod tests{
 use super::*;
 #[test] fn shop_name_track_needs_distinct_ordered_frames_and_resets_on_change(){
   let first=advance_shop_name_track(None,"Alune",0.89,1000,1);
   let same_frame=advance_shop_name_track(Some(first.clone()),"Alune",0.88,1000,1);
   assert_eq!(same_frame.confirmations,1);
   let repeated=advance_shop_name_track(Some(first),"alune",0.88,1500,2);
   assert_eq!(repeated.confirmations,2);
   assert_eq!(repeated.min_score,0.88);
   assert_eq!(repeated.first_ms,1000);
   let changed=advance_shop_name_track(Some(repeated.clone()),"Ashe",0.96,2000,3);
   assert_eq!(changed.confirmations,1);
   let stale=advance_shop_name_track(Some(repeated),"Alune",0.90,5001,4);
   assert_eq!(stale.confirmations,1);
 }
 #[test] fn protocol_rejects_oversize_header(){assert!(header(&mut io::Cursor::new(vec![b'x';65537])).is_err())}
 #[test] fn protocol_eof(){assert!(header(&mut io::Cursor::new(Vec::<u8>::new())).unwrap().is_none())}
 #[test] fn payload_size_not_guessed(){let h=json!({"id":1,"source_ms":0,"width":2,"height":2,"bytes":16});assert!(frame(&h,&mut io::empty()).is_err())}
 #[test] fn payload_timestamp_preserved(){let h=json!({"id":2,"source_ms":1234,"width":1,"height":1,"bytes":3});let f=frame(&h,&mut io::Cursor::new([1,2,3])).unwrap();assert_eq!(f.captured_at_ms,1234);assert_eq!(f.pixels,vec![1,2,3]);}
 #[test] fn cadence_delivery_preserves_original_timestamp(){
   let original=json!({"timestamp_ms":1000,"panel_status":"located"});
   let out=cadence_json(&original,10,1000,11,1750);
   assert_eq!(out["timestamp_ms"],1000);
   assert_eq!(out["cadence_delivery"]["source_frame_id"],10);
   assert_eq!(out["cadence_delivery"]["delivered_frame_id"],11);
   assert_eq!(out["cadence_delivery"]["age_ms"],750);
   assert_eq!(out["cadence_delivery"]["fresh"],false);
 }
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
