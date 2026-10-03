//! HM2: explicit-target, resident Rust screen acquisition. No game access or hidden capture.
use serde_json::Value;
use std::io::{self, Write};

#[cfg(windows)]
mod platform;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn bad(message: &str) -> Box<dyn std::error::Error> {
    io::Error::new(io::ErrorKind::InvalidInput, message).into()
}

fn rgb_from_bgra(data: &[u8], width: usize, height: usize, pitch: usize) -> Result<Vec<u8>> {
    if width == 0 || height == 0 || width > 8192 || height > 8192 {
        return Err(bad("invalid physical capture dimensions"));
    }
    let packed = width.checked_mul(4).ok_or_else(|| bad("width overflow"))?;
    let total = pitch.checked_mul(height).ok_or_else(|| bad("stride overflow"))?;
    let size = width.checked_mul(height).and_then(|v| v.checked_mul(3)).ok_or_else(|| bad("payload overflow"))?;
    if pitch < packed || data.len() < total || size > 128 * 1024 * 1024 {
        return Err(bad("invalid capture stride/buffer/budget"));
    }
    let mut rgb = vec![0; size];
    for y in 0..height {
        for (src, dst) in data[y*pitch..y*pitch+packed].chunks_exact(4)
            .zip(rgb[y*width*3..(y+1)*width*3].chunks_exact_mut(3)) {
            dst.copy_from_slice(&[src[2], src[1], src[0]]);
        }
    }
    Ok(rgb)
}

fn preview_size(width: usize, height: usize) -> (usize, usize) {
    if width <= 1280 && height <= 720 { return (width, height); }
    if width * 720 > height * 1280 {
        (1280, (height * 1280 / width).max(1))
    } else {
        ((width * 720 / height).max(1), 720)
    }
}

fn preview_rgb_from_bgra(data: &[u8], width: usize, height: usize, pitch: usize) -> Result<(usize, usize, Vec<u8>)> {
    if width == 0 || height == 0 || width > 8192 || height > 8192
        || pitch < width * 4 || pitch.checked_mul(height).is_none_or(|size| data.len() < size) {
        return Err(bad("invalid preview source geometry"));
    }
    let (out_w, out_h) = preview_size(width, height);
    let mut rgb = vec![0; out_w * out_h * 3];
    for y in 0..out_h {
        let row = y * height / out_h * pitch;
        for x in 0..out_w {
            let source = row + (x * width / out_w) * 4;
            let target = (y * out_w + x) * 3;
            rgb[target..target + 3].copy_from_slice(&[data[source + 2], data[source + 1], data[source]]);
        }
    }
    Ok((out_w, out_h, rgb))
}

fn packet(header: &Value, pixels: &[u8]) -> Result<()> {
    let bytes = serde_json::to_vec(header)?;
    if bytes.len() > 65536 || pixels.len() > 128 * 1024 * 1024 {
        return Err(bad("IPC packet budget"));
    }
    let out = io::stdout();
    let mut out = out.lock();
    out.write_all(&(bytes.len() as u32).to_le_bytes())?;
    out.write_all(&bytes)?;
    out.write_all(pixels)?;
    out.flush()?;
    Ok(())
}

#[derive(Debug)]
struct Args { kind: String, id: String, seconds: f64, hz: f64, preview_hz: Option<f64> }
fn parse(args: &[String]) -> Result<Args> {
    if !args.iter().any(|s| s == "--consent") { return Err(bad("explicit --consent required")); }
    let field = |key: &str| -> Result<&str> {
        let i = args.iter().position(|s| s == key).ok_or_else(|| bad("missing capture argument"))?;
        args.get(i+1).map(String::as_str).ok_or_else(|| bad("missing argument value"))
    };
    let preview_hz = args.iter().position(|s| s == "--preview-hz")
        .map(|_| field("--preview-hz").and_then(|value| value.parse::<f64>().map_err(Into::into)))
        .transpose()?;
    let a = Args { kind: field("--kind")?.into(), id: field("--id")?.into(),
        seconds: field("--seconds")?.parse()?, hz: field("--hz")?.parse()?, preview_hz };
    if !["monitor", "window"].contains(&a.kind.as_str()) || a.id.is_empty() || a.id.len()>32
        || !a.id.chars().all(|c| c.is_ascii_hexdigit()) || usize::from_str_radix(&a.id,16)? == 0
        || !a.seconds.is_finite() || !(1.0..=7200.0).contains(&a.seconds)
        || !a.hz.is_finite() || !(0.2..=30.0).contains(&a.hz)
        || a.preview_hz.is_some_and(|hz| !hz.is_finite() || !(5.0..=30.0).contains(&hz)) {
        return Err(bad("invalid target/time/rate"));
    }
    Ok(a)
}

fn run() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    #[cfg(windows)] {
        if args.first().map(String::as_str)==Some("list") {
            println!("{}", serde_json::to_string(&platform::list()?)?); return Ok(());
        }
        let a = parse(&args)?;
        platform::stream(&a)
    }
    #[cfg(not(windows))] {
        let _ = args;
        Err(bad("native capture requires Windows; no fallback backend"))
    }
}
fn main() {
    if let Err(e) = run() {
        eprintln!("HM_CAPTURE_ERROR={e}");
        let _ = packet(&serde_json::json!({"type":"error", "error":e.to_string(), "bytes":0}), &[]);
        std::process::exit(2);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn bgr_rows_ignore_padding() {
        assert_eq!(rgb_from_bgra(&[3,2,1,255,99,99,99,99,6,5,4,0,88,88,88,88],1,2,8).unwrap(),[1,2,3,4,5,6]);
    }
    #[test] fn invalid_stride_refused() { assert!(rgb_from_bgra(&[0;16],2,2,4).is_err()); }
    #[test] fn truncated_data_refused() { assert!(rgb_from_bgra(&[0;15],2,2,8).is_err()); }
    #[test] fn zero_size_refused() { assert!(rgb_from_bgra(&[],0,1,0).is_err()); }
    #[test] fn huge_size_refused() { assert!(rgb_from_bgra(&[],usize::MAX,2,4).is_err()); }
    #[test] fn preview_downscale_preserves_rgb_and_bounds() {
        let bgra = [3, 2, 1, 255, 6, 5, 4, 255, 9, 8, 7, 255, 12, 11, 10, 255];
        assert_eq!(preview_rgb_from_bgra(&bgra, 2, 2, 8).unwrap(), (2, 2, vec![1,2,3,4,5,6,7,8,9,10,11,12]));
        assert_eq!(preview_size(3840, 2160), (1280, 720));
        assert_eq!(preview_size(1600, 1200), (960, 720));
    }
    fn args() -> Vec<String> { "--kind monitor --id 123 --seconds 2 --hz 4 --consent".split_whitespace().map(str::to_string).collect() }
    #[test] fn consent_required() { let mut a=args();a.pop();assert!(parse(&a).is_err()); }
    #[test] fn finite_budget_required() { let mut a=args();a[5]="NaN".into();assert!(parse(&a).is_err()); }
    #[test] fn valid_selection() { assert_eq!(parse(&args()).unwrap().kind,"monitor"); }
    #[test] fn invalid_target_refused() { let mut a=args();a[3]="0".into();assert!(parse(&a).is_err()); }
}
