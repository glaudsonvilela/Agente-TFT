//! Observations only. Empty, unknown and an unresolved seasonal offer are distinct.
use agente_tft_capture_core::{FrameEnvelope, PixelRect};
use agente_tft_image_preprocess::GrayImage;
use agente_tft_ocr_tesseract::{TesseractOcr, TextWord};
use agente_tft_perception_hud::{HudField, HudOcrEngine, HudPreprocessConfig};
use serde::Serialize;
use crate::layout::{contains,crop,score,ScreenLayout};

#[derive(Debug, Clone, Serialize)]
pub struct Attempt {
    pub scale:u8,
    pub text:Option<String>,
    pub confidence:Option<f32>,
    pub reason:String,
}
#[derive(Debug, Clone, Serialize)]
pub struct SlotRead {
    pub slot:u8,
    pub status:String,
    pub observed_name:Option<String>,
    pub observed_cost:Option<u16>,
    pub name_confidence:Option<f32>,
    pub cost_confidence:Option<f32>,
    pub unit_id:Option<String>,
    pub catalog_status:String,
    pub catalog_base_cost:Option<u8>,
    pub empty_similarity:Option<f32>,
    pub name_attempts:Vec<Attempt>,
    pub cost_attempts:Vec<Attempt>,
}
#[derive(Debug, Clone, Serialize)]
pub struct ScreenRead {
    pub timestamp_ms:u64,
    pub layout_id:String,
    pub panel_status:String,
    pub panel_anchor_similarities:Vec<Option<f32>>,
    pub slots:Vec<SlotRead>,
    pub ocr_process_calls:u8,
    pub error:Option<String>,
}
#[derive(Debug, Clone, Copy)]
struct Tile { slot:usize, field:usize, rect:PixelRect }

fn base_slot(slot:u8,status:&str,similarity:Option<f32>)->SlotRead {
    SlotRead {slot,status:status.into(),observed_name:None,observed_cost:None,
        name_confidence:None,cost_confidence:None,unit_id:None,catalog_status:"not_bound".into(),
        catalog_base_cost:None,empty_similarity:similarity,name_attempts:vec![],cost_attempts:vec![]}
}

pub fn normalize(text:&str)->String { text.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase() }

fn attempt(words:&[TextWord],tile:Tile,scale:u8,threshold:f32,ambiguous:bool)->Attempt {
    if ambiguous { return Attempt {scale,text:None,confidence:None,reason:"atlas_assignment_conflict".into()}; }
    let mut selected:Vec<_>=words.iter().filter(|w| contains(tile.rect,
        PixelRect{x:w.x,y:w.y,width:w.width,height:w.height})).collect();
    selected.sort_by_key(|w|w.x);
    if selected.is_empty() { return Attempt{scale,text:None,confidence:None,reason:"no_text".into()}; }
    let text=selected.iter().map(|w|w.text.as_str()).collect::<Vec<_>>().join(" ");
    // Minimum WORD score, not average confidence hiding an uncertain token.
    let confidence=selected.iter().map(|w|w.confidence).fold(1.0,f32::min);
    let valid=if tile.field==0 {
        text.chars().count()<=80 && text.chars().filter(|c|c.is_alphabetic()).count()>=2
            && text.chars().all(|c|c.is_alphabetic() || c.is_whitespace() || "'-.’".contains(c))
    } else { !text.is_empty() && text.len()<=2 && text.bytes().all(|b|b.is_ascii_digit()) };
    Attempt {scale,text:Some(text),confidence:Some(confidence),
        reason:if !valid {"invalid_text"} else if confidence<threshold {"below_min_confidence"} else {"eligible"}.into()}
}

fn agree(a:&[Attempt])->(Option<String>,Option<f32>) {
    if a.len()!=2 || a.iter().any(|v|v.reason!="eligible") { return (None,None); }
    let (Some(x),Some(y))=(&a[0].text,&a[1].text) else { return (None,None); };
    if normalize(x)!=normalize(y) { return (None,None); }
    (Some(x.clone()),Some(a[0].confidence.unwrap().min(a[1].confidence.unwrap())))
}

fn atlas(frame:&FrameEnvelope,layout:&ScreenLayout,engine:&TesseractOcr,skip:&[bool],scale:u8)
    ->Result<(GrayImage,Vec<Tile>),String> {
    let mut pieces=Vec::new();
    let (mut name_w,mut cost_w,mut row_h)=(0u32,0u32,0u32);
    for (i,s) in layout.slots.iter().enumerate() {
        if skip[i] { continue; }
        for (field,rect) in [(0,s.name),(1,s.cost)] {
            let roi=crop(frame,rect)?;
            // Level selects the existing gray text path; numeric parsing is NOT invoked.
            let img=engine.prepare_roi(HudField::Level,&roi,HudPreprocessConfig{upscale_factor:scale,invert:true})
                .map_err(|e|format!("text preparation: {e:?}"))?;
            if field==0 {name_w=name_w.max(img.width);} else {cost_w=cost_w.max(img.width);}
            row_h=row_h.max(img.height); pieces.push((i,field,img));
        }
    }
    let width=name_w+cost_w+60;
    let height=(row_h+20)*5+20;
    if width as u64*height as u64>4_000_000 {return Err("shop atlas too large".into());}
    let mut image=GrayImage {width,height,stride_bytes:width,pixels:vec![255;(width*height) as usize]};
    let mut tiles=Vec::new();
    for (slot,field,img) in pieces {
        let x=if field==0 {10} else {name_w+40};
        let y=10+slot as u32*(row_h+20);
        for row in 0..img.height as usize {
            let dest=(y as usize+row)*width as usize+x as usize;
            let src=row*img.stride_bytes as usize;
            image.pixels[dest..dest+img.width as usize].copy_from_slice(&img.pixels[src..src+img.width as usize]);
        }
        tiles.push(Tile{slot,field,rect:PixelRect{x,y,width:img.width,height:img.height}});
    }
    Ok((image,tiles))
}

pub fn perceive(frame:&FrameEnvelope,layout:&ScreenLayout,engine:&TesseractOcr)->Result<ScreenRead,String> {
    frame.validate().map_err(|e|e.to_string())?;
    if (frame.width,frame.height)!=(layout.reference_width,layout.reference_height) {
        return Err("UI profile resolution mismatch; no silent resize".into());
    }
    let panel_scores=layout.panel_anchors.iter().map(|a|score(frame,a.rect,&a.index()? ).map(|x|x.0))
        .collect::<Result<Vec<_>,_>>()?;
    let visible=layout.panel_anchors.iter().zip(&panel_scores)
        .all(|(a,s)|s.is_some_and(|v|v>=a.min_similarity));
    let mut out=ScreenRead {timestamp_ms:frame.captured_at_ms,layout_id:layout.id.clone(),
        panel_status:if visible {"located"} else {"unresolved"}.into(),
        panel_anchor_similarities:panel_scores,slots:vec![],ocr_process_calls:0,error:None};
    if !visible {
        out.slots=(0..5).map(|i|base_slot(i,"unavailable",None)).collect();
        return Ok(out);
    }
    let index=layout.empty_template.index()?;
    let mut empty=Vec::new();
    for s in &layout.slots {
        let (similarity,mean)=score(frame,s.empty_region,&index)?;
        let is_empty=similarity.is_some_and(|v|v>=layout.empty_template.min_similarity)
            && mean<=layout.empty_max_mean;
        empty.push(is_empty);
        out.slots.push(base_slot(s.slot,if is_empty {"empty_observed"} else {"unknown"},similarity));
    }
    if empty.iter().all(|v|*v) {return Ok(out);}
    for scale in [3,4] {
        let (image,tiles)=atlas(frame,layout,engine,&empty,scale)?;
        out.ocr_process_calls+=1;
        let words=match engine.recognize_text_block(&image) {
            Ok(w)=>w,
            Err(e)=>{out.error=Some(e);break;}
        };
        let ambiguous=words.iter().any(|w|tiles.iter().filter(|t|contains(t.rect,
            PixelRect{x:w.x,y:w.y,width:w.width,height:w.height})).count()!=1);
        for tile in tiles {
            let a=attempt(&words,tile,scale,layout.min_text_confidence,ambiguous);
            if tile.field==0 {out.slots[tile.slot].name_attempts.push(a);}
            else {out.slots[tile.slot].cost_attempts.push(a);}
        }
    }
    for s in &mut out.slots {
        if s.status=="empty_observed" {continue;}
        if out.error.is_some() {s.status="read_error".into();continue;}
        (s.observed_name,s.name_confidence)=agree(&s.name_attempts);
        let (cost,conf)=agree(&s.cost_attempts);
        s.observed_cost=cost.and_then(|v|v.parse::<u16>().ok());s.cost_confidence=conf;
        s.status=match (s.observed_name.is_some(),s.observed_cost.is_some()) {
            (true,true)=>"offer_text_readable",(true,false)|(false,true)=>"partially_readable",_=>"unknown",
        }.into();
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn a(scale:u8,text:&str,conf:f32)->Attempt {
        Attempt {scale,text:Some(text.into()),confidence:Some(conf),
            reason:if conf>=0.7 {"eligible"}else{"below_min_confidence"}.into()}
    }
    #[test] fn scale_conflict_or_low_confidence_never_chooses_a_value() {
        assert!(agree(&[a(3,"Alpha",0.95),a(4,"Beta",0.99)]).0.is_none());
        assert!(agree(&[a(3,"Alpha",0.69),a(4,"Alpha",0.99)]).0.is_none());
    }
    #[test] fn names_preserve_apostrophes_and_spaces() {
        assert_eq!(agree(&[a(3,"Rek'Sai",0.95),a(4,"rek'sai",0.91)]).0.as_deref(),Some("Rek'Sai"));
        assert_eq!(normalize("  Lobo   Trovogurai "),"lobo trovogurai");
    }
    #[test] fn missing_text_is_not_empty_slot() {
        assert_eq!(base_slot(0,"unknown",None).status,"unknown");
        assert!(base_slot(0,"empty_observed",Some(0.99)).unit_id.is_none());
    }
    #[test] fn atlas_words_cannot_cross_field_boundary() {
        let tile=Tile{slot:0,field:0,rect:PixelRect{x:0,y:0,width:50,height:30}};
        let word=TextWord{text:"Alpha".into(),confidence:0.99,x:45,y:5,width:20,height:10};
        assert_eq!(attempt(&[word],tile,3,0.7,true).reason,"atlas_assignment_conflict");
    }
}
