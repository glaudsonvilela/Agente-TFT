//! Raw scoreboard words and a tentative battle name. The seasonal player
//! roster and combat result are reconciled later across distinct frames.
use agente_tft_capture_core::{FrameEnvelope, PixelRect};
use agente_tft_image_preprocess::{to_luma, upscale_nearest, GrayImage};
use agente_tft_ocr_tesseract::{NumberBlockOcrEngine,TextBlockOcrEngine};
use serde_json::{json, Value};
use crate::layout::crop;

pub const PANEL: PixelRect = PixelRect { x: 1690, y: 170, width: 175, height: 635 };
pub const BATTLE_NAME: PixelRect = PixelRect { x: 1080, y: 125, width: 105, height: 20 };
pub const ENEMY_NAME: PixelRect = PixelRect { x: 1215, y: 77, width: 95, height: 22 };
pub const SELF_OVERLAY: PixelRect = PixelRect { x: 80, y: 9, width: 160, height: 20 };
pub const HP_PANEL: PixelRect = PixelRect { x: 1830, y: 180, width: 26, height: 605 };

fn cubic(distance:f32)->f32 {
    let x=distance.abs();
    if x<1.0 {1.5*x*x*x-2.5*x*x+1.0}
    else if x<2.0 {-0.5*x*x*x+2.5*x*x-4.0*x+2.0}
    else {0.0}
}

// Small 26x515 numeric strip. Smooth scaling preserves the thin scoreboard
// digits that nearest-neighbor scaling confused with border decorations.
fn upscale_bicubic(image:&GrayImage, factor:u32)->Result<GrayImage,String>{
    image.validate().map_err(|e|e.to_string())?;
    let width=image.width.checked_mul(factor).ok_or("numeric upscale width overflow")?;
    let height=image.height.checked_mul(factor).ok_or("numeric upscale height overflow")?;
    if width as u64*height as u64>4_000_000{return Err("numeric atlas budget exceeded".into())}
    let mut pixels=vec![0u8;(width*height) as usize];
    for y in 0..height {
        let sy=(y as f32+0.5)/factor as f32-0.5;
        let y0=sy.floor() as i32;
        for x in 0..width {
            let sx=(x as f32+0.5)/factor as f32-0.5;
            let x0=sx.floor() as i32;
            let mut sum=0.0f32;let mut weight=0.0f32;
            for dy in -1..=2 {
                let yy=(y0+dy).clamp(0,image.height as i32-1) as usize;
                let wy=cubic(sy-(y0+dy) as f32);
                for dx in -1..=2 {
                    let xx=(x0+dx).clamp(0,image.width as i32-1) as usize;
                    let w=wy*cubic(sx-(x0+dx) as f32);
                    sum+=image.pixels[yy*image.stride_bytes as usize+xx] as f32*w;
                    weight+=w;
                }
            }
            pixels[(y*width+x) as usize]=(sum/weight).round().clamp(0.0,255.0) as u8;
        }
    }
    Ok(GrayImage{width,height,stride_bytes:width,pixels})
}

fn words<E: TextBlockOcrEngine>(frame: &FrameEnvelope, rect: PixelRect, scale: u8,
                                engine: &mut E) -> Result<Vec<Value>, String> {
    let roi = crop(frame, rect)?;
    let gray = to_luma(&roi).map_err(|e| e.to_string())?;
    let enlarged = upscale_nearest(&gray, scale).map_err(|e| e.to_string())?;
    Ok(engine.recognize_text_block(&enlarged)?.into_iter()
        .filter(|word| word.confidence >= 0.20)
        .map(|word| json!({"text":word.text,"confidence":word.confidence,
            "box":[rect.x + word.x / scale as u32,
                   rect.y + word.y / scale as u32,
                   rect.x + (word.x + word.width + scale as u32 - 1) / scale as u32,
                   rect.y + (word.y + word.height + scale as u32 - 1) / scale as u32]}))
        .collect())
}

pub fn observe<E: TextBlockOcrEngine,N:NumberBlockOcrEngine>(frame: &FrameEnvelope, engine: &mut E,
                                                              number_engine:&mut N) -> Result<Value, String> {
    let mut scoreboard = words(frame, PANEL, 2, engine)?;
    scoreboard.retain(|word|word["box"][0].as_u64().unwrap_or(0)<1830);
    let roi=crop(frame,HP_PANEL)?;
    let gray=to_luma(&roi).map_err(|e|e.to_string())?;
    let enlarged=upscale_bicubic(&gray,2)?;
    scoreboard.extend(number_engine.recognize_number_block(&enlarged)?.into_iter()
        .filter(|word|word.confidence>=0.20)
        .map(|word|json!({"text":word.text,"confidence":word.confidence,
            "box":[HP_PANEL.x+word.x/2,HP_PANEL.y+word.y/2,
                   HP_PANEL.x+(word.x+word.width+1)/2,
                   HP_PANEL.y+(word.y+word.height+1)/2]})));
    let battle_name = words(frame, BATTLE_NAME, 4, engine)?;
    let enemy_name = words(frame, ENEMY_NAME, 4, engine)?;
    let self_name = words(frame, SELF_OVERLAY, 4, engine)?;
    Ok(json!({"status":"raw_ocr","basis":"fixed_right_scoreboard_and_battle_label_v1",
              "frame_id":frame.frame_id,"source_ms":frame.captured_at_ms,
              "panel":[PANEL.x,PANEL.y,PANEL.width,PANEL.height],
              "words":scoreboard,"battle_name_words":battle_name,
              "enemy_name_words":enemy_name,
              "self_name_words":self_name,
              "player_identity_verified":false,"opponent_board_assigned":false}))
}
