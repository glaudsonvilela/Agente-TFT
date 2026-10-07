//! Locate the closest frame in a dense review window to audit sparse VOD timestamps.
use image::{imageops::FilterType, RgbImage};
use serde_json::{json, Value};
use std::{fs, path::Path};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn thumbnail(path: &Path) -> Result<RgbImage> {
    let image = image::open(path)?.to_rgb8();
    Ok(image::imageops::resize(
        &image,
        64,
        36,
        FilterType::Triangle,
    ))
}
fn distance(a: &RgbImage, b: &RgbImage) -> u64 {
    a.as_raw()
        .iter()
        .zip(b.as_raw())
        .map(|(x, y)| x.abs_diff(*y) as u64)
        .sum()
}
fn run() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 4 {
        return Err("use TARGET_FRAME DENSE_COLLECTION TOP_N".into());
    }
    let target = thumbnail(Path::new(&args[1]))?;
    let root = Path::new(&args[2]);
    let count: usize = args[3].parse()?;
    if !(1..=50).contains(&count) {
        return Err("top N must be 1..50".into());
    }
    let observations = fs::read_to_string(root.join("observations.jsonl"))?;
    let mut matches = Vec::new();
    for line in observations.lines() {
        let row: Value = serde_json::from_str(line)?;
        let Some(file) = row["review_frame"].as_str() else {
            continue;
        };
        let sample = thumbnail(&root.join(file))?;
        matches.push((
            distance(&target, &sample),
            row["source_seconds_nominal"].as_u64().ok_or("time")?,
        ));
    }
    matches.sort_unstable();
    println!(
        "{}",
        json!({"top_matches":matches.into_iter().take(count).map(|(sad,time)|json!({"source_seconds_nominal":time,"thumbnail_sad":sad})).collect::<Vec<_>>()})
    );
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("FRAME_TIME_AUDIT_ERROR: {error}");
        std::process::exit(1);
    }
}
