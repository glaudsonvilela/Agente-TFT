use std::{env,fs,path::{Path,PathBuf},time::Instant};
use agente_tft_image_preprocess::GrayImage;
use agente_tft_ocr_tesseract::{ResidentTesseractOcr,TesseractConfig,TesseractOcr};
use agente_tft_perception_hud::{HudField,HudOcrEngine,RecognizedText};
use serde_json::json;

fn read_pgm(path:&Path)->Result<GrayImage,String>{
    let data=fs::read(path).map_err(|e|format!("{}: {e}",path.display()))?;
    if !data.starts_with(b"P5\n"){return Err(format!("{}: expected P5 PGM",path.display()))}
    let mut cuts=Vec::new();
    for (i,b) in data.iter().enumerate(){if *b==b'\n'{cuts.push(i);if cuts.len()==3{break}}}
    if cuts.len()!=3{return Err(format!("{}: truncated PGM header",path.display()))}
    let dims=std::str::from_utf8(&data[cuts[0]+1..cuts[1]]).map_err(|e|e.to_string())?;
    let mut it=dims.split_whitespace();
    let width:u32=it.next().ok_or("missing width")?.parse().map_err(|_|"bad width")?;
    let height:u32=it.next().ok_or("missing height")?.parse().map_err(|_|"bad height")?;
    if it.next().is_some(){return Err("extra dimensions".into())}
    if &data[cuts[1]+1..cuts[2]]!=b"255"{return Err("PGM max value must be 255".into())}
    let pixels=data[cuts[2]+1..].to_vec();
    if pixels.len()!=width as usize*height as usize{return Err(format!("{}: pixel length mismatch",path.display()))}
    Ok(GrayImage{width,height,stride_bytes:width,pixels})
}
fn field(name:&str)->Result<HudField,String>{match name{
    "gold"=>Ok(HudField::Gold),"level"=>Ok(HudField::Level),"stage"=>Ok(HudField::Stage),"xp"=>Ok(HudField::Xp),
    _=>Err(format!("unknown field {name}"))
}}
fn one(engine:&mut impl HudOcrEngine,field:HudField,image:&GrayImage)->Result<(Option<RecognizedText>,f64),String>{
    let at=Instant::now();let out=engine.recognize(field,image)?;Ok((out,at.elapsed().as_secs_f64()*1000.0))
}
fn main(){
    let args:Vec<String>=env::args().skip(1).collect();
    if args.len()<2{panic!("usage: <tesseract.exe> <fixture-dir> [--output file] [--repeats N]")}
    let binary=PathBuf::from(&args[0]);let fixtures=PathBuf::from(&args[1]);
    let mut output="hm44-ocr-hub-parity.json".to_string();let mut repeats=3usize;let mut i=2usize;
    while i<args.len(){match args[i].as_str(){
        "--output"=>{i+=1;output=args.get(i).cloned().unwrap_or(output)},
        "--repeats"=>{i+=1;repeats=args.get(i).and_then(|x|x.parse().ok()).unwrap_or(3)},
        _=>{}
    } i+=1;}
    if !(1..=5).contains(&repeats){panic!("repeats must be 1..=5")}
    let mut cli=TesseractOcr::new(TesseractConfig{binary:binary.to_string_lossy().into_owned(),language:"eng".into()}).with_numeric_gray();
    if !cli.available(){panic!("CLI tesseract unavailable")}
    let mut resident=ResidentTesseractOcr::from_cli_path(&binary,"eng").expect("resident init").with_numeric_gray();

    let cases=[("gold","50"),("level","8"),("stage","4-2"),("xp","20/68")];
    let mut rows=Vec::new();let mut all_equal=true;
    for (name,expected) in cases {
        let image=read_pgm(&fixtures.join(format!("{name}.pgm"))).expect("fixture");
        for repeat in 0..repeats {
            let (a,cli_ms)=one(&mut cli,field(name).unwrap(),&image).expect("cli");
            let (b,resident_ms)=one(&mut resident,field(name).unwrap(),&image).expect("resident");
            let a_text=a.as_ref().map(|x|x.text.clone());
            let b_text=b.as_ref().map(|x|x.text.clone());
            let a_conf=a.as_ref().map(|x|x.confidence.value());
            let b_conf=b.as_ref().map(|x|x.confidence.value());
            let conf_delta=match (a_conf,b_conf){(Some(x),Some(y))=>Some((x-y).abs()),(None,None)=>Some(0.0),_=>None};
            let equal=a_text.as_deref()==Some(expected) && b_text.as_deref()==Some(expected)
                && a_text==b_text && conf_delta.is_some_and(|d|d<=0.01);
            all_equal&=equal;
            rows.push(json!({"field":name,"expected":expected,"repeat":repeat,
                "cli_text":a_text,"resident_text":b_text,"cli_confidence":a_conf,"resident_confidence":b_conf,
                "confidence_abs_delta":conf_delta,"cli_ms":cli_ms,"resident_ms":resident_ms,"parity":equal}));
        }
    }
    let report=json!({"schema_version":1,"policy":"hm44_cli_resident_text_parity_v1",
        "production_enabled":false,"fixtures_generated_on_runner":true,"all_equal":all_equal,
        "confidence_abs_tolerance":0.01,"rows":rows,
        "resident_dll":resident.dll_path(),"resident_tessdata":resident.tessdata_path(),"language":resident.language()});
    fs::write(&output,serde_json::to_vec_pretty(&report).unwrap()).unwrap();
    println!("HM44_OCR_PARITY={}",serde_json::to_string(&report).unwrap());
    assert!(all_equal,"CLI/resident OCR parity gate failed");
}
