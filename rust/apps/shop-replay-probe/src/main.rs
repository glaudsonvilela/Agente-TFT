//! Local opt-in shop probe. Existing capture decoder and Tesseract only.
#[path = "../../hud-replay-probe/src/media.rs"]
mod media;
mod layout;
mod screen;
mod recovery;
mod controls;
mod control_text;

use std::{collections::{BTreeMap,HashSet},env,fs,io::Write,path::{Path,PathBuf},process::ExitCode,time::Instant};
use agente_tft_ocr_tesseract::{TesseractConfig,TesseractOcr};
use serde_json::{json,Value};
use layout::ScreenLayout;
use recovery::RecoveryProfile;

fn load(path:&Path)->Result<Value,String> {
    if fs::metadata(path).map_err(|e|e.to_string())?.len()>16*1024*1024 {return Err("JSON budget exceeded".into());}
    serde_json::from_str(&fs::read_to_string(path).map_err(|e|e.to_string())?).map_err(|e|e.to_string())
}
fn run()->Result<bool,String> {
    let args:Vec<_>=env::args().skip(1).collect();
    if !(4..=6).contains(&args.len()) {
        return Err("Usage: shop-replay-probe <manifest.json> <image-root> <ui-layout.json> <NEW-report.json> [recovery-profile.json [controls-profile.json]]".into());
    }
    let root=PathBuf::from(&args[1]).canonicalize().map_err(|e|e.to_string())?;
    let manifest=load(Path::new(&args[0]))?;
    let rows=manifest["frames"].as_array().ok_or("manifest frames missing")?;
    if rows.is_empty() || rows.len()>128 {return Err("require 1..128 frames".into());}
    let mut plan=Vec::new();let mut seen=HashSet::new();let mut last=None;
    for r in rows {
        let at=r["timestamp_ms"].as_u64().ok_or("invalid timestamp")?;
        if last.is_some_and(|v|at<=v) || at>86_400_000 {return Err("unordered/invalid timestamp".into());}
        let image=media::relative_image_path(&root,r["image"].as_str())?;
        if !seen.insert(image.clone()) {return Err("duplicate image path".into());}
        last=Some(at);plan.push((at,image));
    }
    let layout:ScreenLayout=serde_json::from_value(load(Path::new(&args[2]))?).map_err(|e|e.to_string())?;
    layout.validate()?;
    let recovery: Option<RecoveryProfile> = args.get(4).map(|path| {
        serde_json::from_value(load(Path::new(path))?).map_err(|e| e.to_string())
    }).transpose()?;
    if let Some(profile) = &recovery { profile.validate(&layout)?; }
    let controls = args.get(5).map(|path| {
        let profile = serde_json::from_value(load(Path::new(path))?).map_err(|e| e.to_string())?;
        controls::ControlsReader::new(profile, &layout, recovery.as_ref().ok_or("controls require recovery profile")?)
    }).transpose()?;
    let mut control_calls = 0u64;
    let language=env::var("TFT_SHOP_OCR_LANGUAGE").unwrap_or_else(|_|"eng".into());
    if language.is_empty() || language.len()>40 || !language.chars().all(|c|c.is_ascii_alphanumeric()||c=='_'||c=='+') {
        return Err("invalid OCR language".into());
    }
    let engine=TesseractOcr::new(TesseractConfig{language:language.clone(),..TesseractConfig::default()}).with_numeric_gray();
    if !engine.available() {return Err("tesseract unavailable".into());}
    let mut file=fs::OpenOptions::new().create_new(true).write(true).open(&args[3]).map_err(|e|e.to_string())?;
    let mut records=Vec::new();let mut errors=0;let mut calls=0u64;let mut panels=BTreeMap::<String,usize>::new();
    let mut statuses=BTreeMap::<String,usize>::new();let mut times=Vec::<f64>::new();
    for (i,(at,path)) in plan.iter().enumerate() {
        eprintln!("SHOP_FRAME={}/{} timestamp_ms={at}",i+1,plan.len());
        let start=Instant::now();
        let result=media::decode(path,None,*at).and_then(|frame| {
            let read = screen::perceive(&frame, &layout, &engine, recovery.as_ref())?;
            let control_read = if let Some(reader) = &controls {
                let mut value = reader.read_visual(&frame, read.panel_status == "located")?;
                control_text::read_numbers(&frame, &reader.profile, &mut value, &engine)?;
                Some(value)
            } else { None };
            Ok((read, control_read))
        });
        match result {
            Ok((read, control_read))=>{
                errors+=usize::from(read.error.is_some());calls+=read.ocr_process_calls as u64;
                *panels.entry(read.panel_status.clone()).or_default()+=1;
                for s in &read.slots {*statuses.entry(s.status.clone()).or_default()+=1;}
                let ms=start.elapsed().as_secs_f64()*1000.0;times.push(ms);
                let mut row=json!({"type":"shop_observation","read":read,"elapsed_ms":ms});
                if let Some(value) = control_read {
                    errors += usize::from(value.error.is_some());
                    control_calls += value.ocr_process_calls as u64;
                    row["controls"] = serde_json::to_value(value).map_err(|e| e.to_string())?;
                }
                println!("{row}");records.push(row);
            }
            Err(e)=>{errors+=1;records.push(json!({"timestamp_ms":at,"error":e}));}
        }
    }
    times.sort_by(f64::total_cmp);
    let p50=times.get(times.len()/2).copied();
    let p95=times.get(times.len().saturating_sub(1)*95/100).copied();
    let profile = if recovery.is_some() { "shop_text_atlas_v2_local_routing" } else { "shop_text_atlas_v1" };
    let mut summary=json!({"schema_version":1,"profile":profile,"frames":plan.len(),
        "slots_per_frame":5,"panel_statuses":panels,"slot_statuses":statuses,"errors":errors,
        "ocr_process_calls":calls,"frame_ms_p50":p50,"frame_ms_p95":p95,"ocr_language":language,
        "layout_id":layout.id,"locale":layout.locale,"set_key":null,"tft_patch":null,
        "catalog_status":"not_bound","exact_accuracy":null,"metric_kind":"operational_shop_observations",
        "labels_used":false,"game_state_updated":false,"profile_promoted":false,"model_trained":false,
        "execution_complete":errors==0,"cost_origin":"pixels; not catalog base cost",
        "capabilities":{"five_slots":true,"empty_marker":true,"offer_text":true,"visible_cost":true,
            "unit_id_binding":false,"lock_state":false,"button_states":false,"purchase_inference":false},
        "note":"UI seeds are not independent evaluation; special offers are not assumed champions; sparse frames do not establish temporal consensus"});
    if let Some(reader) = &controls {
        summary["controls_profile"] = json!(reader.profile.id);
        summary["controls_ocr_process_calls"] = json!(control_calls);
        summary["total_ocr_process_calls"] = json!(calls + control_calls);
        summary["capabilities"]["button_states"] = json!(true);
        summary["capabilities"]["lock_appearance"] = json!(true);
        summary["capabilities"]["button_prices"] = json!(true);
        summary["capabilities"]["free_refresh_counter"] = json!(true);
        summary["controls_note"] = json!("visual appearances only; not click authorization or temporal confirmation; closed-lock template not present in seeded profile");
    }
    serde_json::to_writer_pretty(&mut file,&json!({"summary":summary,"records":records})).map_err(|e|e.to_string())?;
    file.write_all(b"\n").map_err(|e|e.to_string())?;file.sync_all().map_err(|e|e.to_string())?;
    println!("{summary}");Ok(errors==0)
}
fn main()->ExitCode {match run(){Ok(true)=>ExitCode::SUCCESS,Ok(false)=>ExitCode::from(2),Err(e)=>{eprintln!("SHOP_ERROR={e}");ExitCode::FAILURE}}}
