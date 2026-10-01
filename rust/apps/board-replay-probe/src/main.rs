//! Local spatial diagnostics. No OCR, live game access, decisions or mutations.
#[path="../../hud-replay-probe/src/media.rs"]
mod media;
mod profile;
mod bars;
mod scene;
use std::{collections::{BTreeMap,HashSet},env,fs,io::Write,path::{Path,PathBuf},process::ExitCode,time::Instant};
use serde_json::{json,Value};
use profile::Profile;
use scene::SceneReader;

fn load(path:&Path)->Result<Value,String> {
    if fs::metadata(path).map_err(|e|e.to_string())?.len()>16*1024*1024 {return Err("JSON byte budget exceeded".into());}
    serde_json::from_slice(&fs::read(path).map_err(|e|e.to_string())?).map_err(|e|e.to_string())
}
fn plan(value:&Value,root:&Path)->Result<Vec<(u64,PathBuf)>,String> {
    let rows=value["frames"].as_array().ok_or("manifest frames missing")?;
    if rows.is_empty() || rows.len()>128 {return Err("require 1..128 frames".into());}
    let mut last=None;let mut paths=HashSet::new();let mut out=Vec::new();
    for r in rows {
        let at=r["timestamp_ms"].as_u64().ok_or("invalid timestamp")?;
        if at>86_400_000 || last.is_some_and(|t|at<=t) {return Err("unordered/duplicate timestamp".into());}
        let path=media::relative_image_path(root,r["image"].as_str())?;
        if !paths.insert(path.clone()) {return Err("reused frame path".into());}
        out.push((at,path));last=Some(at);
    }
    Ok(out)
}
fn quantile(values:&[f64],q:f64)->f64 {
    let mut v=values.to_vec();v.sort_by(f64::total_cmp);
    let p=(v.len()-1) as f64*q;let lo=p.floor() as usize;let hi=p.ceil() as usize;
    v[lo]+(v[hi]-v[lo])*(p-lo as f64)
}
fn run()->Result<(),String> {
    let a:Vec<_>=env::args().skip(1).collect();
    if a.len()!=4 {return Err("Usage: board-replay-probe <manifest> <image-root> <UI-profile> <NEW-report>".into());}
    let root=PathBuf::from(&a[1]).canonicalize().map_err(|e|e.to_string())?;
    let p:Profile=serde_json::from_value(load(Path::new(&a[2]))?).map_err(|e|e.to_string())?;
    p.validate()?;
    let frames=plan(&load(Path::new(&a[0]))?,&root)?;
    let reference_path=media::relative_image_path(&root,Some(&p.reference_image))?;
    let reference=media::decode(&reference_path,None,0)?;
    let reader=SceneReader::new(p.clone(),&reference)?;
    // Refuse overwrite before scanning any evaluation frame.
    let mut output=fs::OpenOptions::new().write(true).create_new(true).open(&a[3]).map_err(|e|e.to_string())?;
    let mut records=Vec::new();let mut projections=BTreeMap::<String,usize>::new();
    let mut bench_states=BTreeMap::<String,usize>::new();let mut colors=BTreeMap::<String,usize>::new();
    let mut scan_ms=Vec::new();let mut total_ms=Vec::new();
    for (i,(at,path)) in frames.iter().enumerate() {
        eprintln!("BOARD1_READ={}/{} timestamp_ms={at}",i+1,frames.len());
        let started=Instant::now();let frame=media::decode(path,None,*at)?;
        let read_start=Instant::now();let read=reader.read(&frame)?;
        let elapsed=read_start.elapsed().as_secs_f64()*1000.0;
        let total=started.elapsed().as_secs_f64()*1000.0;
        *projections.entry(read.projection_status.clone()).or_default()+=1;
        for b in &read.bench {*bench_states.entry(b.evidence.clone()).or_default()+=1;}
        for m in &read.markers {*colors.entry(m.color.clone()).or_default()+=1;}
        scan_ms.push(elapsed);total_ms.push(total);
        let record=json!({"type":"spatial_frame","read":read,"scan_ms":elapsed,"decode_and_scan_ms":total});
        println!("{record}");records.push(record);
    }
    let summary=json!({"schema_version":1,"policy":"board_bench_spatial_v1","profile":p.id,"frames":frames.len(),
        "projection_statuses":projections,"bench_evidence":bench_states,"marker_colors":colors,
        "scan_ms_p50":quantile(&scan_ms,0.5),"scan_ms_p95":quantile(&scan_ms,0.95),
        "decode_and_scan_ms_p50":quantile(&total_ms,0.5),"decode_and_scan_ms_p95":quantile(&total_ms,0.95),
        "board_cells_per_frame":28,"bench_slots_per_frame":9,"execution_complete":true,"errors":0,
        "ocr_process_calls":0,"labels_used":false,"model_trained":false,"game_state_updated":false,
        "profile_promoted":false,"temporal_confirmation":false,"exact_accuracy":null,
        "unit_identity_established":false,"occupancy_established":false,"ground_assignment_established":false,
        "metric_kind":"spatial_proposals_and_reference_similarity",
        "note":"Projection seeds and empty appearance matches are not independent validation; markers are proposals, not unit count/HP/ownership. No ground anchor inferred from bar/body center."});
    serde_json::to_writer_pretty(&mut output,&json!({"summary":summary,"records":records})).map_err(|e|e.to_string())?;
    output.write_all(b"\n").map_err(|e|e.to_string())?;output.sync_all().map_err(|e|e.to_string())?;
    println!("{summary}");Ok(())
}
fn main()->ExitCode {
    match run() {Ok(())=>ExitCode::SUCCESS,Err(e)=>{eprintln!("BOARD1_ERROR={e}");ExitCode::FAILURE}}
}
#[cfg(test)] mod tests;
