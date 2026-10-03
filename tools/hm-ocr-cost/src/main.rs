use std::{env, fs, time::Instant};
use agente_tft_capture_core::{PixelFormat, PixelRect, RoiFrame};
use agente_tft_ocr_tesseract::{TesseractConfig, TesseractOcr};
use agente_tft_perception_hud::{HudField, HudOcrEngine, HudPreprocessConfig};
use serde_json::json;

fn pct(values:&[f64], q:f64)->Option<f64>{
    if values.is_empty(){return None}
    let mut a=values.to_vec();a.sort_by(|x,y|x.total_cmp(y));
    let at=(a.len()-1) as f64*q;let lo=at.floor() as usize;let hi=(lo+1).min(a.len()-1);let f=at-lo as f64;
    Some(a[lo]*(1.0-f)+a[hi]*f)
}
fn stats(v:&[f64])->serde_json::Value{
    json!({"n":v.len(),"p50_ms":pct(v,0.5),"p95_ms":pct(v,0.95),"max_ms":v.iter().copied().fold(0.0,f64::max)})
}
fn roi()->RoiFrame{
    let w=44u32;let h=25u32;
    let mut pixels=vec![18u8;(w*h*3) as usize];
    // Deterministic synthetic strokes: enough contrast to exercise preprocessing/OCR,
    // never used as accuracy evidence or a TFT label.
    for y in 4..21 {
        for x in [8u32,9,20,21,32,33] {
            let i=((y*w+x)*3) as usize;
            pixels[i..i+3].copy_from_slice(&[235,235,235]);
        }
    }
    RoiFrame{source_frame_id:1,captured_at_ms:1,rect:PixelRect{x:0,y:0,width:w,height:h},
             stride_bytes:w*3,pixel_format:PixelFormat::Rgb8,bytes_per_pixel:3,pixels}
}
fn main(){
    let args:Vec<String>=env::args().skip(1).collect();
    let binary=args.first().cloned().unwrap_or_else(||"tesseract".into());
    let mut iterations=8usize;let mut output="hm4-ocr-cost.json".to_string();
    let mut i=1usize;
    while i<args.len(){
        match args[i].as_str(){
            "--iterations"=>{i+=1;iterations=args.get(i).and_then(|x|x.parse().ok()).unwrap_or(8)},
            "--output"=>{i+=1;output=args.get(i).cloned().unwrap_or(output)},
            _=>{}
        } i+=1;
    }
    if !(3..=32).contains(&iterations){panic!("iterations must be in 3..=32")}
    let mut engine=TesseractOcr::new(TesseractConfig{binary:binary.clone(),language:"eng".into()}).with_numeric_gray();
    if !engine.available(){panic!("tesseract unavailable: {binary}")}
    let source=roi();let cfg=HudPreprocessConfig{upscale_factor:3,invert:true};
    let mut prep=Vec::new();let mut recognize=Vec::new();let mut total=Vec::new();
    let mut outputs=Vec::new();
    for _ in 0..iterations {
        let all=Instant::now();
        let p=Instant::now();
        let image=engine.prepare_roi(HudField::Gold,&source,cfg).expect("preprocess");
        prep.push(p.elapsed().as_secs_f64()*1000.0);
        let r=Instant::now();
        let observed=engine.recognize(HudField::Gold,&image).expect("recognize");
        recognize.push(r.elapsed().as_secs_f64()*1000.0);
        total.push(all.elapsed().as_secs_f64()*1000.0);
        outputs.push(observed.map(|x|x.text));
    }
    let recognize_sum: f64=recognize.iter().sum();
    let total_sum: f64=total.iter().sum();
    let report=json!({
        "schema_version":1,
        "policy":"hm44_ocr_cost_probe_v1",
        "purpose":"isolate_preprocess_from_tesseract_process_adapter_cost",
        "synthetic_input":true,
        "accuracy_claim":false,
        "field":"gold",
        "iterations":iterations,
        "binary":binary,
        "preprocess":stats(&prep),
        "recognize_process_adapter":stats(&recognize),
        "total":stats(&total),
        "recognize_fraction_of_total": if total_sum>0.0 {recognize_sum/total_sum} else {0.0},
        "outputs":outputs
    });
    fs::write(&output,serde_json::to_vec_pretty(&report).unwrap()).unwrap();
    println!("HM44_OCR_COST={}",serde_json::to_string(&report).unwrap());
}
