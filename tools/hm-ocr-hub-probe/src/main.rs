use std::{env, ffi::{CStr,CString,c_char,c_int,c_void}, fs, path::{Path,PathBuf}, time::Instant};
use agente_tft_image_preprocess::GrayImage;
use agente_tft_ocr_tesseract::{TesseractConfig,TesseractOcr};
use agente_tft_perception_hud::{HudField,HudOcrEngine};
use libloading::{Library,Symbol};
use serde_json::json;

type ApiCreate=unsafe extern "C" fn()->*mut c_void;
type ApiDelete=unsafe extern "C" fn(*mut c_void);
type ApiEnd=unsafe extern "C" fn(*mut c_void);
type ApiInit3=unsafe extern "C" fn(*mut c_void,*const c_char,*const c_char)->c_int;
type ApiSetVariable=unsafe extern "C" fn(*mut c_void,*const c_char,*const c_char)->c_int;
type ApiSetPsm=unsafe extern "C" fn(*mut c_void,c_int);
type ApiSetImage=unsafe extern "C" fn(*mut c_void,*const u8,c_int,c_int,c_int,c_int);
type ApiRecognize=unsafe extern "C" fn(*mut c_void,*mut c_void)->c_int;
type ApiGetTsv=unsafe extern "C" fn(*mut c_void,c_int)->*mut c_char;
type DeleteText=unsafe extern "C" fn(*const c_char);

fn pct(values:&[f64],q:f64)->Option<f64>{
    if values.is_empty(){return None}
    let mut a=values.to_vec();a.sort_by(|x,y|x.total_cmp(y));
    let at=(a.len()-1) as f64*q;let lo=at.floor() as usize;let hi=(lo+1).min(a.len()-1);let f=at-lo as f64;
    Some(a[lo]*(1.0-f)+a[hi]*f)
}
fn stats(v:&[f64])->serde_json::Value{
    json!({"n":v.len(),"p50_ms":pct(v,0.5),"p95_ms":pct(v,0.95),"max_ms":v.iter().copied().fold(0.0,f64::max)})
}
fn image()->GrayImage{
    let w=132u32;let h=75u32;let mut pixels=vec![0u8;(w*h) as usize];
    for y in 12..63 {
        for x in [24u32,25,60,61,96,97] {
            pixels[(y*w+x) as usize]=255;
        }
    }
    GrayImage{width:w,height:h,stride_bytes:w,pixels}
}
fn find_dll(binary:&Path)->PathBuf{
    let root=binary.parent().unwrap_or(Path::new("."));
    for name in ["libtesseract-5.dll","libtesseract.dll"] {
        let p=root.join(name);if p.is_file(){return p}
    }
    panic!("libtesseract DLL not found beside {}",binary.display())
}
fn main(){
    let args:Vec<String>=env::args().skip(1).collect();
    let binary=PathBuf::from(args.first().cloned().unwrap_or_else(||"C:\\Program Files\\Tesseract-OCR\\tesseract.exe".into()));
    let mut iterations=10usize;let mut output="hm44-ocr-hub-probe.json".to_string();
    let mut i=1usize;while i<args.len(){match args[i].as_str(){
        "--iterations"=>{i+=1;iterations=args.get(i).and_then(|x|x.parse().ok()).unwrap_or(10)},
        "--output"=>{i+=1;output=args.get(i).cloned().unwrap_or(output)},_=>{} } i+=1;}
    if !(4..=32).contains(&iterations){panic!("iterations must be in 4..=32")}
    if !binary.is_file(){panic!("tesseract binary missing: {}",binary.display())}
    let dll=find_dll(&binary);let tessdata=binary.parent().unwrap().join("tessdata");
    if !tessdata.join("eng.traineddata").is_file(){panic!("eng.traineddata missing")}
    let gray=image();

    let mut cli=TesseractOcr::new(TesseractConfig{binary:binary.to_string_lossy().into_owned(),language:"eng".into()}).with_numeric_gray();
    if !cli.available(){panic!("CLI tesseract unavailable")}
    let _=cli.recognize(HudField::Gold,&gray).expect("CLI warmup");

    let lib=unsafe{Library::new(&dll)}.unwrap_or_else(|e|panic!("load {}: {e}",dll.display()));
    unsafe {
        let create:Symbol<ApiCreate>=lib.get(b"TessBaseAPICreate\0").unwrap();
        let delete:Symbol<ApiDelete>=lib.get(b"TessBaseAPIDelete\0").unwrap();
        let end:Symbol<ApiEnd>=lib.get(b"TessBaseAPIEnd\0").unwrap();
        let init3:Symbol<ApiInit3>=lib.get(b"TessBaseAPIInit3\0").unwrap();
        let set_var:Symbol<ApiSetVariable>=lib.get(b"TessBaseAPISetVariable\0").unwrap();
        let set_psm:Symbol<ApiSetPsm>=lib.get(b"TessBaseAPISetPageSegMode\0").unwrap();
        let set_image:Symbol<ApiSetImage>=lib.get(b"TessBaseAPISetImage\0").unwrap();
        let recognize:Symbol<ApiRecognize>=lib.get(b"TessBaseAPIRecognize\0").unwrap();
        let get_tsv:Symbol<ApiGetTsv>=lib.get(b"TessBaseAPIGetTsvText\0").unwrap();
        let delete_text:Symbol<DeleteText>=lib.get(b"TessDeleteText\0").unwrap();

        let init_started=Instant::now();let api=create();if api.is_null(){panic!("TessBaseAPICreate returned null")}
        let data=CString::new(tessdata.to_string_lossy().as_bytes()).unwrap();let lang=CString::new("eng").unwrap();
        if init3(api,data.as_ptr(),lang.as_ptr())!=0{delete(api);panic!("TessBaseAPIInit3 failed")}
        let key=CString::new("tessedit_char_whitelist").unwrap();let value=CString::new("0123456789").unwrap();
        if set_var(api,key.as_ptr(),value.as_ptr())==0{end(api);delete(api);panic!("TessBaseAPISetVariable failed")}
        set_psm(api,7);let init_ms=init_started.elapsed().as_secs_f64()*1000.0;

        let mut hub_once=||->String{
            set_image(api,gray.pixels.as_ptr(),gray.width as c_int,gray.height as c_int,1,gray.stride_bytes as c_int);
            if recognize(api,std::ptr::null_mut())!=0{panic!("TessBaseAPIRecognize failed")}
            let ptr=get_tsv(api,0);if ptr.is_null(){panic!("TessBaseAPIGetTsvText returned null")}
            let out=CStr::from_ptr(ptr).to_string_lossy().into_owned();delete_text(ptr);out
        };
        let _=hub_once(); // warm caches; initialization remains reported separately.

        let mut cli_ms=Vec::new();let mut hub_ms=Vec::new();let mut cli_nonempty=0usize;let mut hub_nonempty=0usize;
        for _ in 0..iterations {
            let a=Instant::now();let c=cli.recognize(HudField::Gold,&gray).expect("CLI recognize");
            cli_ms.push(a.elapsed().as_secs_f64()*1000.0);cli_nonempty+=usize::from(c.is_some());

            let b=Instant::now();let tsv=hub_once();
            hub_ms.push(b.elapsed().as_secs_f64()*1000.0);
            hub_nonempty+=usize::from(tsv.lines().skip(1).any(|line|line.split('\t').nth(11).is_some_and(|x|!x.trim().is_empty())));
        }
        end(api);delete(api);
        let cli_p50=pct(&cli_ms,0.5).unwrap();let hub_p50=pct(&hub_ms,0.5).unwrap();
        let report=json!({
            "schema_version":1,"policy":"hm44_resident_tesseract_c_api_probe_v1",
            "synthetic_input":true,"accuracy_claim":false,
            "binary":binary,"dll":dll,"tessdata":tessdata,"iterations":iterations,
            "resident_init_ms":init_ms,
            "cli_process_adapter":stats(&cli_ms),
            "resident_c_api":stats(&hub_ms),
            "p50_speedup_cli_over_resident":if hub_p50>0.0{cli_p50/hub_p50}else{0.0},
            "cli_nonempty":cli_nonempty,"resident_nonempty":hub_nonempty,
            "production_enabled":false
        });
        fs::write(&output,serde_json::to_vec_pretty(&report).unwrap()).unwrap();
        println!("HM44_OCR_HUB_PROBE={}",serde_json::to_string(&report).unwrap());
    }
}
