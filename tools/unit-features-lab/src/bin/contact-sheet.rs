//! Dataset inspection only; image transformations remain native Rust.
use std::{fs, path::PathBuf};
fn run() -> Result<(), Box<dyn std::error::Error>> {
    let a: Vec<_> = std::env::args().collect();
    if a.len() != 3 {
        return Err("use MANIFEST_JSON NEW_OUTPUT_DIRECTORY".into());
    }
    let rows: Vec<serde_json::Value> = serde_json::from_slice(&fs::read(&a[1])?)?;
    let out = PathBuf::from(&a[2]);
    if out.exists() {
        return Err("new output required".into());
    }
    fs::create_dir_all(&out)?;
    for (page, chunk) in rows.chunks(24).enumerate() {
        let mut sheet = image::RgbImage::new(128 * 6, 144 * 4);
        for (i, row) in chunk.iter().enumerate() {
            let mut rgb = image::open(row["path"].as_str().ok_or("path")?)?.to_rgb8();
            // Reference renders can declare a display-only region. This never
            // changes the training crop contract or writes model inputs.
            if let Some(b) = row["source_box"].as_array() {
                let b: Vec<u32> = b
                    .iter()
                    .map(|v| {
                        v.as_u64()
                            .and_then(|v| u32::try_from(v).ok())
                            .ok_or("source_box coordinate")
                    })
                    .collect::<Result<_, _>>()?;
                if b.len() != 4
                    || b[0] >= b[2]
                    || b[1] >= b[3]
                    || b[2] > rgb.width()
                    || b[3] > rgb.height()
                {
                    return Err("source_box outside image".into());
                }
                rgb = image::imageops::resize(
                    &image::imageops::crop_imm(&rgb, b[0], b[1], b[2] - b[0], b[3] - b[1])
                        .to_image(),
                    128,
                    144,
                    image::imageops::FilterType::Triangle,
                );
            }
            if rgb.width() != 128 || rgb.height() != 144 {
                return Err("expected native unit crop".into());
            }
            image::imageops::replace(&mut sheet, &rgb, (i % 6 * 128) as i64, (i / 6 * 144) as i64);
        }
        sheet.save(out.join(format!("page-{page}.png")))?;
        fs::write(
            out.join(format!("page-{page}.json")),
            serde_json::to_vec_pretty(chunk)?,
        )?;
    }
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("CONTACT_SHEET_ERROR: {e}");
        std::process::exit(1);
    }
}
