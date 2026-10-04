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

fn preview_size(width: usize, height: usize, max_width: usize, max_height: usize) -> (usize, usize) {
    if width <= max_width && height <= max_height { return (width, height); }
    if width * max_height > height * max_width {
        (max_width, (height * max_width / width).max(1))
    } else {
        ((width * max_height / height).max(1), max_height)
    }
}

fn preview_rgb_from_bgra(data: &[u8], width: usize, height: usize, pitch: usize,
                         max_width: usize, max_height: usize) -> Result<(usize, usize, Vec<u8>)> {
    if width == 0 || height == 0 || width > 8192 || height > 8192
        || pitch < width * 4 || pitch.checked_mul(height).is_none_or(|size| data.len() < size) {
        return Err(bad("invalid preview source geometry"));
    }
    let (out_w, out_h) = preview_size(width, height, max_width, max_height);
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

// Preserve the native channel order for the Windows DIB preview. Analysis stays RGB.
fn preview_bgra(data: &[u8], width: usize, height: usize, pitch: usize,
                max_width: usize, max_height: usize) -> Result<(usize, usize, Vec<u8>)> {
    if width == 0 || height == 0 || width > 8192 || height > 8192
        || pitch < width * 4 || pitch.checked_mul(height).is_none_or(|n| data.len() < n) {
        return Err(bad("invalid preview geometry"));
    }
    let (w,h) = preview_size(width,height,max_width,max_height);
    let mut pixels=vec![0;w*h*4];
    let offsets:Vec<usize>=(0..w).map(|x| x*width/w*4).collect();
    for y in 0..h {
        let row=y*height/h*pitch;
        for (x,offset) in offsets.iter().enumerate() {
            let target=(y*w+x)*4;
            pixels[target..target+4].copy_from_slice(&data[row+offset..row+offset+4]);
        }
    }
    Ok((w,h,pixels))
}

struct Cadence { period: f64, next: f64 }
impl Cadence {
    fn new(hz:f64)->Self {Self {period:1.0/hz,next:0.0}}
    fn take(&mut self, now:f64)->bool {
        if now+0.001 < self.next {return false;}
        self.next += self.period;
        if self.next <= now {self.next=now+self.period;}
        true
    }
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
struct Args { kind: String, id: String, seconds: f64, hz: f64, preview_hz: Option<f64>,
              preview_width: usize, preview_height: usize }
fn parse(args: &[String]) -> Result<Args> {
    if !args.iter().any(|s| s == "--consent") { return Err(bad("explicit --consent required")); }
    let field = |key: &str| -> Result<&str> {
        let i = args.iter().position(|s| s == key).ok_or_else(|| bad("missing capture argument"))?;
        args.get(i+1).map(String::as_str).ok_or_else(|| bad("missing argument value"))
    };
    let preview_hz = args.iter().position(|s| s == "--preview-hz")
        .map(|_| field("--preview-hz").and_then(|value| value.parse::<f64>().map_err(Into::into)))
        .transpose()?;
    let optional_size = |key: &str, default: usize| -> Result<usize> {
        if args.iter().any(|s| s == key) { Ok(field(key)?.parse()?) } else { Ok(default) }
    };
    let a = Args { kind: field("--kind")?.into(), id: field("--id")?.into(),
        seconds: field("--seconds")?.parse()?, hz: field("--hz")?.parse()?, preview_hz,
        preview_width: optional_size("--preview-width", 1280)?,
        preview_height: optional_size("--preview-height", 720)? };
    if !["monitor", "window"].contains(&a.kind.as_str()) || a.id.is_empty() || a.id.len()>32
        || !a.id.chars().all(|c| c.is_ascii_hexdigit()) || usize::from_str_radix(&a.id,16)? == 0
        || !a.seconds.is_finite() || !(1.0..=7200.0).contains(&a.seconds)
        || !a.hz.is_finite() || !(0.2..=30.0).contains(&a.hz)
        || a.preview_hz.is_some_and(|hz| !hz.is_finite() || !(5.0..=30.0).contains(&hz))
        || !(160..=1280).contains(&a.preview_width) || !(90..=720).contains(&a.preview_height)
        || (a.preview_hz.is_none() && (a.preview_width != 1280 || a.preview_height != 720)) {
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
    #[test] fn preview_cadence_tolerates_sixty_hz_jitter() {
        let mut cadence=Cadence::new(30.0);
        let count=(0..600).filter(|i| {
            cadence.take(*i as f64/60.0 + if i%2==0 {0.0002} else {-0.0002})
        }).count();
        assert_eq!(count,300);
        assert!(cadence.take(20.0));
        assert!(!cadence.take(20.001));
    }
    #[test] fn native_preview_preserves_bgra_and_ignores_stride_padding() {
        let input=[3,2,1,255,99,99,99,99,6,5,4,255,88,88,88,88];
        assert_eq!(preview_bgra(&input,1,2,8,1280,720).unwrap(),(1,2,vec![3,2,1,255,6,5,4,255]));
        assert!(preview_bgra(&input[..10],1,2,8,1280,720).is_err());
    }
    #[test] fn bgr_rows_ignore_padding() {
        assert_eq!(rgb_from_bgra(&[3,2,1,255,99,99,99,99,6,5,4,0,88,88,88,88],1,2,8).unwrap(),[1,2,3,4,5,6]);
    }
    #[test] fn invalid_stride_refused() { assert!(rgb_from_bgra(&[0;16],2,2,4).is_err()); }
    #[test] fn truncated_data_refused() { assert!(rgb_from_bgra(&[0;15],2,2,8).is_err()); }
    #[test] fn zero_size_refused() { assert!(rgb_from_bgra(&[],0,1,0).is_err()); }
    #[test] fn huge_size_refused() { assert!(rgb_from_bgra(&[],usize::MAX,2,4).is_err()); }
    #[test] fn preview_downscale_preserves_rgb_and_bounds() {
        let bgra = [3, 2, 1, 255, 6, 5, 4, 255, 9, 8, 7, 255, 12, 11, 10, 255];
        assert_eq!(preview_rgb_from_bgra(&bgra, 2, 2, 8, 1280, 720).unwrap(), (2, 2, vec![1,2,3,4,5,6,7,8,9,10,11,12]));
        assert_eq!(preview_size(3840, 2160, 1280, 720), (1280, 720));
        assert_eq!(preview_size(1600, 1200, 1280, 720), (960, 720));
        assert_eq!(preview_size(1920, 1080, 846, 476), (846, 475));
    }
    fn args() -> Vec<String> { "--kind monitor --id 123 --seconds 2 --hz 4 --consent".split_whitespace().map(str::to_string).collect() }
    #[test] fn consent_required() { let mut a=args();a.pop();assert!(parse(&a).is_err()); }
    #[test] fn finite_budget_required() { let mut a=args();a[5]="NaN".into();assert!(parse(&a).is_err()); }
    #[test] fn valid_selection() { assert_eq!(parse(&args()).unwrap().kind,"monitor"); }
    #[test] fn invalid_target_refused() { let mut a=args();a[3]="0".into();assert!(parse(&a).is_err()); }
}
