use std::{env,fs,path::{Path,PathBuf},time::Instant};
use agente_tft_image_preprocess::GrayImage;
use agente_tft_ocr_tesseract::{ResidentTesseractOcr,TesseractConfig,TesseractOcr,TextBlockOcrEngine,TextWord};
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

fn one_block(engine:&mut impl TextBlockOcrEngine,image:&GrayImage)->Result<(Vec<TextWord>,f64),String>{
    let at=Instant::now();let out=engine.recognize_text_block(image)?;Ok((out,at.elapsed().as_secs_f64()*1000.0))
}
fn words_json(words:&[TextWord])->serde_json::Value{
    json!(words.iter().map(|w|json!({"text":w.text,"confidence":w.confidence,
        "x":w.x,"y":w.y,"width":w.width,"height":w.height})).collect::<Vec<_>>())
}
fn text_block_equal(a:&[TextWord],b:&[TextWord])->bool{
    a.len()==b.len() && !a.is_empty() && a.iter().zip(b).all(|(x,y)|
        x.text==y.text && x.x==y.x && x.y==y.y && x.width==y.width && x.height==y.height
        && (x.confidence-y.confidence).abs()<=0.01)
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
    let block_image=read_pgm(&fixtures.join("textblock.pgm")).expect("textblock fixture");
    let mut block_rows=Vec::new();
    let mut block_equal=true;
    for repeat in 0..repeats {
        let (a,cli_ms)=one_block(&mut cli,&block_image).expect("cli text block");
        let (b,resident_ms)=one_block(&mut resident,&block_image).expect("resident text block");
        let a_join=a.iter().map(|w|w.text.as_str()).collect::<Vec<_>>().join(" ");
        let b_join=b.iter().map(|w|w.text.as_str()).collect::<Vec<_>>().join(" ");
        let equal=a_join=="ALPHA 1 BETA 2" && b_join=="ALPHA 1 BETA 2" && text_block_equal(&a,&b);
        block_equal&=equal;
        block_rows.push(json!({"repeat":repeat,"cli_ms":cli_ms,"resident_ms":resident_ms,
            "cli_joined":a_join,"resident_joined":b_join,"cli_words":words_json(&a),
            "resident_words":words_json(&b),"parity":equal}));
    }
    all_equal &= block_equal;

    let expected_shop="ALPHA 1 BETA 2 GAMMA 3 DELTA 4 OMEGA 5";
    let mut shop_atlas=Vec::new();
    let mut shop_all_equal=true;
    for scale in [3u8,4u8] {
        let image=read_pgm(&fixtures.join(format!("shop_atlas_scale{scale}.pgm"))).expect("shop atlas fixture");
        let mut cli_times=Vec::new();let mut resident_times=Vec::new();let mut parity=true;
        let mut samples=Vec::new();
        for repeat in 0..repeats {
            let (a,cli_ms)=one_block(&mut cli,&image).expect("cli shop atlas");
            let (b,resident_ms)=one_block(&mut resident,&image).expect("resident shop atlas");
            let a_join=a.iter().map(|w|w.text.as_str()).collect::<Vec<_>>().join(" ");
            let b_join=b.iter().map(|w|w.text.as_str()).collect::<Vec<_>>().join(" ");
            let equal=a_join==expected_shop && b_join==expected_shop && text_block_equal(&a,&b);
            parity&=equal;cli_times.push(cli_ms);resident_times.push(resident_ms);
            samples.push(json!({"repeat":repeat,"cli_ms":cli_ms,"resident_ms":resident_ms,
                "cli_joined":a_join,"resident_joined":b_join,"parity":equal}));
        }
        cli_times.sort_by(|a,b|a.total_cmp(b));resident_times.sort_by(|a,b|a.total_cmp(b));
        let cli_p50=cli_times[cli_times.len()/2];let resident_p50=resident_times[resident_times.len()/2];
        let performance=resident_p50<cli_p50*0.50;
        shop_all_equal &= parity && performance;
        shop_atlas.push(json!({"scale":scale,"width":image.width,"height":image.height,
            "parity":parity,"performance_gate":performance,"cli_p50_ms":cli_p50,
            "resident_p50_ms":resident_p50,"speedup":cli_p50/resident_p50,"samples":samples}));
    }
    all_equal &= shop_all_equal;
    let report=json!({"schema_version":3,"policy":"hm44_cli_resident_text_parity_v3",
        "production_enabled":false,"fixtures_generated_on_runner":true,"all_equal":all_equal,
        "numeric_all_equal":rows.iter().all(|r|r["parity"]==true),
        "spatial_text_all_equal":block_equal,"shop_atlas_all_equal_and_fast":shop_all_equal,
        "confidence_abs_tolerance":0.01,"rows":rows,"spatial_text_rows":block_rows,
        "shop_atlas_rows":shop_atlas,
        "resident_dll":resident.dll_path(),"resident_tessdata":resident.tessdata_path(),"language":resident.language()});
    fs::write(&output,serde_json::to_vec_pretty(&report).unwrap()).unwrap();
    println!("HM44_OCR_PARITY={}",serde_json::to_string(&report).unwrap());
    assert!(all_equal,"CLI/resident OCR parity gate failed");
}
