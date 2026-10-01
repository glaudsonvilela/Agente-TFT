//! Sparse offline decoding only. Never connects to the running game.
use std::{fs, path::{Component, Path, PathBuf}, process::{Command, Stdio}};
use agente_tft_capture_core::{FrameEnvelope, PixelFormat};

pub fn relative_image_path(root: &Path, image: Option<&str>) -> Result<PathBuf, String> {
    let relative = Path::new(image.ok_or("--image-root requires image in every selected frame")?);
    if relative.as_os_str().is_empty() || relative.components().any(|c| !matches!(c, Component::Normal(_))) {
        return Err("image must be a nonempty relative path without traversal".into());
    }
    let joined = root.join(relative);
    // Also reject existing symlinks to files outside the supplied root.
    if joined.exists() {
        let resolved = joined.canonicalize().map_err(|e| e.to_string())?;
        let canonical_root = root.canonicalize().map_err(|e| e.to_string())?;
        if !resolved.starts_with(canonical_root) { return Err("image escapes image root".into()); }
        return Ok(resolved);
    }
    Ok(joined)
}

pub fn decode(path: &Path, seek_ms: Option<u64>, timestamp_ms: u64) -> Result<FrameEnvelope, String> {
    if !path.is_file() { return Err(format!("media file not found: {}", path.display())); }
    let path = fs::canonicalize(path).map_err(|e| e.to_string())?;
    let mut command = Command::new("ffmpeg");
    command.args(["-nostdin", "-hide_banner", "-loglevel", "error"]);
    // Same input-seek convention as training.prepare_replay_annotations.
    // FFmpeg decodes from its seek point to the requested time, not from t=0.
    if let Some(ms) = seek_ms { command.args(["-ss", &format!("{}.{:03}", ms/1000, ms%1000)]); }
    let result = command.arg("-i").arg(&path)
        .args(["-map", "0:v:0", "-frames:v", "1", "-an", "-sn", "-c:v", "ppm", "-f", "image2pipe", "pipe:1"])
        .stdin(Stdio::null()).output().map_err(|e| format!("cannot start ffmpeg: {e}"))?;
    if !result.status.success() {
        return Err(format!("ffmpeg {}: {}", result.status, String::from_utf8_lossy(&result.stderr)));
    }
    let mut frame = parse_ppm(&result.stdout, timestamp_ms)?;
    frame.source_id = format!("offline-probe:{}", path.display());
    Ok(frame)
}

fn header_token<'a>(bytes: &'a [u8], pos: &mut usize) -> Result<&'a [u8], String> {
    loop {
        while bytes.get(*pos).is_some_and(|b| b.is_ascii_whitespace()) { *pos += 1; }
        if bytes.get(*pos) == Some(&b'#') {
            while bytes.get(*pos).is_some_and(|b| *b != b'\n') { *pos += 1; }
        } else { break; }
    }
    let start = *pos;
    while bytes.get(*pos).is_some_and(|b| !b.is_ascii_whitespace()) { *pos += 1; }
    if *pos == start { return Err("empty/truncated PPM header or seek beyond EOF".into()); }
    Ok(&bytes[start..*pos])
}

pub fn parse_ppm(bytes: &[u8], timestamp_ms: u64) -> Result<FrameEnvelope, String> {
    let mut pos = 0;
    if header_token(bytes, &mut pos)? != b"P6" { return Err("expected binary RGB PPM".into()); }
    fn number(bytes: &[u8]) -> Result<u32, String> {
        std::str::from_utf8(bytes).map_err(|e| e.to_string())?.parse().map_err(|e| format!("invalid PPM number: {e}"))
    }
    let width = number(header_token(bytes, &mut pos)?)?;
    let height = number(header_token(bytes, &mut pos)?)?;
    if number(header_token(bytes, &mut pos)?)? != 255 { return Err("PPM must be 8-bit".into()); }
    let size = (width as usize).checked_mul(height as usize).and_then(|v| v.checked_mul(3))
        .filter(|n| *n > 0 && *n <= 64*1024*1024).ok_or("invalid/oversized PPM dimensions")?;
    // Consume exactly the header separator. Pixel data may begin with whitespace or '#'.
    match bytes.get(pos) {
        Some(b'\r') if bytes.get(pos+1) == Some(&b'\n') => pos += 2,
        Some(b) if b.is_ascii_whitespace() => pos += 1,
        _ => return Err("missing PPM raster separator".into()),
    }
    if bytes.len().saturating_sub(pos) != size { return Err("truncated or multiple PPM frames".into()); }
    let frame = FrameEnvelope { frame_id: timestamp_ms, captured_at_ms: timestamp_ms, width, height,
        stride_bytes: width.checked_mul(3).ok_or("PPM stride overflow")?, pixel_format: PixelFormat::Rgb8,
        source_id: "offline-probe".into(), pixels: bytes[pos..].to_vec() };
    frame.validate().map_err(|e| e.to_string())?;
    Ok(frame)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn binary_whitespace_and_hash_are_pixels() {
        let mut data = b"P6\n1 1\n255\n".to_vec(); data.extend([10,32,35]);
        assert_eq!(parse_ppm(&data,42).unwrap().pixels, vec![10,32,35]);
    }
    #[test] fn header_comments_and_crlf() {
        let mut data = b"P6\n# fixture\n1 1\n255\r\n".to_vec(); data.extend([1,2,3]);
        let f=parse_ppm(&data,123).unwrap(); assert_eq!((f.width,f.height,f.captured_at_ms),(1,1,123));
    }
    #[test] fn invalid_rasters_are_errors() {
        for data in [&b""[..], &b"P6\n1 1\n255\nxx"[..], &b"P6\n0 1\n255\n"[..], &b"P6\n1 1\n65535\nabc"[..], &b"P6\n1 1\n255\nabcd"[..]] {
            assert!(parse_ppm(data,0).is_err());
        }
    }
    #[test] fn paths_reject_escape_and_missing_name() {
        for name in [None,Some(""),Some("../secret"),Some("/etc/passwd"),Some("frames/../secret")] {
            assert!(relative_image_path(Path::new("."),name).is_err());
        }
    }
    #[test] fn missing_media_fails_before_decoder() {
        assert!(decode(Path::new("/nonexistent-agente-tft-fixture.ppm"),None,0).is_err());
    }
    #[test] fn ffmpeg_sparse_seek_smoke_when_available() {
        if Command::new("ffmpeg").arg("-version").stdout(Stdio::null()).stderr(Stdio::null()).status().map(|s| !s.success()).unwrap_or(true) {
            eprintln!("SKIP: ffmpeg unavailable"); return;
        }
        let dir=std::env::temp_dir().join(format!("hud-probe-smoke-{}",std::process::id()));
        fs::create_dir(&dir).unwrap();
        let video=dir.join("fixture.mkv");
        let result=Command::new("ffmpeg").args(["-nostdin","-loglevel","error","-f","lavfi","-i","color=c=red:s=16x16:r=2:d=1","-f","lavfi","-i","color=c=blue:s=16x16:r=2:d=1","-filter_complex","[0:v][1:v]concat=n=2:v=1:a=0[v]","-map","[v]","-c:v","ffv1"]).arg(&video).output().unwrap();
        assert!(result.status.success(),"{}",String::from_utf8_lossy(&result.stderr));
        let first=decode(&video,Some(0),0).unwrap();
        let late=decode(&video,Some(1500),1500).unwrap();
        assert_eq!((first.width,late.height),(16,16));
        assert!(first.pixels[0]>200 && first.pixels[2]<50);
        assert!(late.pixels[2]>200 && late.pixels[0]<50);
        assert!(decode(&video,Some(30000),30000).is_err());
        fs::remove_dir_all(dir).unwrap();
    }
}
