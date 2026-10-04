//! Resident HP1 baseline adapter. Own stdin RGB, no capture/process inspection.
use std::{io::{self,BufRead,Read,Write},path::Path,time::Instant};
use agente_tft_capture_core::{FrameEnvelope,PixelFormat};
#[cfg(not(target_os="linux"))]
use agente_tft_ocr_tesseract::{TesseractConfig,TesseractOcr};
#[cfg(target_os="linux")]
use agente_tft_ocr_tesseract::ResidentTesseractOcr;
use agente_tft_perception_player_list::{BadgeProfile,read_player_hp};
use serde_json::{Value,json};
fn header(r:&mut impl BufRead)->Result<Option<Value>,String>{
 let mut b=Vec::new();let n=r.take(65537).read_until(b'\n',&mut b).map_err(|e|e.to_string())?;
 if n==0{return Ok(None)}
 if n>65536 || b.last()!=Some(&b'\n'){return Err("invalid header budget".into())}
 serde_json::from_slice(&b).map(Some).map_err(|e|e.to_string())
}
fn number(v:&Value,k:&str)->Result<u64,String>{v[k].as_u64().ok_or_else(||format!("missing {k}"))}
fn frame(v:&Value,r:&mut impl Read)->Result<FrameEnvelope,String>{
 let (w,h)=(number(v,"width")?,number(v,"height")?);
 if w==0 || h==0 || w>3840 || h>2160{return Err("frame budget".into())}
 let count=w*h*3;if number(v,"bytes")?!=count{return Err("RGB length mismatch".into())}
 let mut pixels=vec![0;count as usize];r.read_exact(&mut pixels).map_err(|e|e.to_string())?;
 let f=FrameEnvelope{frame_id:number(v,"id")?,captured_at_ms:number(v,"source_ms")?,width:w as u32,height:h as u32,
   stride_bytes:(w*3)as u32,pixel_format:PixelFormat::Rgb8,source_id:"hm1_closed_file".into(),pixels};
 f.validate().map_err(|e|e.to_string())?;Ok(f)
}
fn run()->Result<(),String>{
 let args:Vec<_>=std::env::args().skip(1).collect();
 if args.len()<2 || args[0]!="--configs"{return Err("--configs <root> [tesseract]".into())}
 let p=Path::new(&args[1]).join("player-list/match001-self-badge-v1.json");
 let bytes=std::fs::read(&p).map_err(|e|e.to_string())?;
 if bytes.len()>2*1024*1024{return Err("profile byte budget".into())}
 let profile:BadgeProfile=serde_json::from_slice(&bytes).map_err(|e|e.to_string())?;profile.validate()?;
 #[cfg(target_os="linux")]
 let mut ocr=ResidentTesseractOcr::from_cli_path(args.get(2).cloned().unwrap_or("tesseract".into()),"eng")?.with_numeric_gray();
 #[cfg(not(target_os="linux"))]
 let mut ocr=TesseractOcr::new(TesseractConfig{binary:args.get(2).cloned().unwrap_or("tesseract".into()),language:"eng".into()}).with_numeric_gray();
 #[cfg(target_os="linux")]
 let available=true;
 #[cfg(not(target_os="linux"))]
 let available=ocr.available();
 let mut input=io::BufReader::new(io::stdin());let mut output=io::BufWriter::new(io::stdout());
 writeln!(output,"{}",json!({"ready":true,"protocol":1,"ocr_available":available,"pid":std::process::id(),"profile":"HP1_baseline"})).map_err(|e|e.to_string())?;
 output.flush().map_err(|e|e.to_string())?;
 while let Some(h)=header(&mut input)?{
  if h["op"]=="stop"{break}
  if h["op"]!="frame"{return Err("unknown operation".into())}
  let f=frame(&h,&mut input)?;let start=Instant::now();
  let hp=if (f.width,f.height)==(1920,1080){serde_json::to_value(read_player_hp(&mut ocr,&f,&profile)).map_err(|e|e.to_string())?}
   else{json!({"status":"resolution_incompatible","signed_hp":null})};
  let ms=start.elapsed().as_secs_f64()*1000.;
  writeln!(output,"{}",json!({"id":f.frame_id,"source_ms":f.captured_at_ms,"hp":hp,"native_ms":ms,
    "profile_promoted":false,"game_state_updated":false,"identity_verified":false})).map_err(|e|e.to_string())?;
  output.flush().map_err(|e|e.to_string())?;
 }Ok(())
}
fn main(){if let Err(e)=run(){eprintln!("HM_HP_ERROR={e}");std::process::exit(2)}}
#[cfg(test)]mod tests{
 use super::*;
 #[test]fn wrong_payload_rejected(){let h=json!({"width":1,"height":1,"bytes":4,"id":2,"source_ms":0});assert!(frame(&h,&mut io::empty()).is_err());}
 #[test]fn oversized_header_rejected(){assert!(header(&mut io::Cursor::new(vec![b'x';65537])).is_err());}
 #[test]fn original_pixels_preserved(){let h=json!({"width":1,"height":1,"bytes":3,"id":2,"source_ms":123});let f=frame(&h,&mut io::Cursor::new([9,8,7])).unwrap();assert_eq!(f.pixels,[9,8,7]);assert_eq!(f.captured_at_ms,123);}
}
