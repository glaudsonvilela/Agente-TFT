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
            let rgb = image::open(row["path"].as_str().ok_or("path")?)?.to_rgb8();
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
