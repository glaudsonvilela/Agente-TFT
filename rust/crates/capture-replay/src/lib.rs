use std::{
    io::{self, BufReader, Read},
    path::{Path, PathBuf},
    process::{Child, ChildStdout, Command, Stdio},
};

use agente_tft_capture_core::{
    CaptureCapabilities, CaptureError, CaptureSource, CaptureSourceKind, FrameEnvelope, PixelFormat,
};

#[derive(Debug, Clone, PartialEq)]
pub struct ReplayMetadata {
    pub width: u32,
    pub height: u32,
    pub source_fps: Option<f32>,
}

pub struct ReplayVideoSource {
    source_id: String,
    path: PathBuf,
    target_fps: u16,
    metadata: ReplayMetadata,
    frame_size: usize,
    frame_index: u64,
    child: Child,
    stdout: BufReader<ChildStdout>,
}

impl ReplayVideoSource {
    pub fn open(path: impl AsRef<Path>, target_fps: u16) -> Result<Self, CaptureError> {
        if target_fps == 0 {
            return Err(CaptureError::Backend(
                "replay target_fps must be greater than zero".into(),
            ));
        }

        let path = path.as_ref().to_path_buf();
        if !path.is_file() {
            return Err(CaptureError::Backend(format!(
                "replay file does not exist: {}",
                path.display()
            )));
        }

        let metadata = probe_video(&path)?;
        let frame_size = (metadata.width as usize)
            .checked_mul(metadata.height as usize)
            .and_then(|v| v.checked_mul(4))
            .ok_or_else(|| CaptureError::Backend("replay frame size overflow".into()))?;

        let mut child = Command::new("ffmpeg")
            .arg("-nostdin")
            .arg("-loglevel")
            .arg("error")
            .arg("-i")
            .arg(&path)
            .arg("-an")
            .arg("-sn")
            .arg("-vf")
            .arg(format!("fps={target_fps}"))
            .arg("-f")
            .arg("rawvideo")
            .arg("-pix_fmt")
            .arg("rgba")
            .arg("pipe:1")
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| {
                CaptureError::Backend(format!(
                    "failed to start ffmpeg for replay: {e}"
                ))
            })?;

        let stdout = child.stdout.take().ok_or_else(|| {
            CaptureError::Backend("ffmpeg stdout was not available".into())
        })?;

        let source_id = format!("replay:{}", path.display());

        Ok(Self {
            source_id,
            path,
            target_fps,
            metadata,
            frame_size,
            frame_index: 0,
            child,
            stdout: BufReader::new(stdout),
        })
    }

    pub fn metadata(&self) -> &ReplayMetadata {
        &self.metadata
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    fn next_timestamp_ms(&self) -> u64 {
        self.frame_index.saturating_mul(1000) / self.target_fps as u64
    }
}

impl CaptureSource for ReplayVideoSource {
    fn capabilities(&self) -> CaptureCapabilities {
        CaptureCapabilities {
            source_id: self.source_id.clone(),
            source_kind: CaptureSourceKind::Replay,
            can_seek: false,
            has_real_time_clock: false,
            max_fps_hint: Some(self.target_fps),
        }
    }

    fn next_frame(&mut self) -> Result<FrameEnvelope, CaptureError> {
        let mut pixels = vec![0u8; self.frame_size];

        match read_exact_frame(&mut self.stdout, &mut pixels) {
            Ok(true) => {}
            Ok(false) => return Err(CaptureError::EndOfStream),
            Err(e) => {
                return Err(CaptureError::Backend(format!(
                    "failed reading replay frame: {e}"
                )))
            }
        }

        let frame = FrameEnvelope {
            frame_id: self.frame_index,
            captured_at_ms: self.next_timestamp_ms(),
            width: self.metadata.width,
            height: self.metadata.height,
            stride_bytes: self.metadata.width.saturating_mul(4),
            pixel_format: PixelFormat::Rgba8,
            source_id: self.source_id.clone(),
            pixels,
        };

        self.frame_index = self.frame_index.saturating_add(1);
        frame.validate()?;
        Ok(frame)
    }
}

impl Drop for ReplayVideoSource {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn read_exact_frame(reader: &mut impl Read, buffer: &mut [u8]) -> io::Result<bool> {
    let mut filled = 0usize;

    while filled < buffer.len() {
        match reader.read(&mut buffer[filled..]) {
            Ok(0) if filled == 0 => return Ok(false),
            Ok(0) => {
                return Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "truncated raw replay frame",
                ))
            }
            Ok(n) => filled += n,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }

    Ok(true)
}

fn probe_video(path: &Path) -> Result<ReplayMetadata, CaptureError> {
    let output = Command::new("ffprobe")
        .arg("-v")
        .arg("error")
        .arg("-select_streams")
        .arg("v:0")
        .arg("-show_entries")
        .arg("stream=width,height,avg_frame_rate")
        .arg("-of")
        .arg("json")
        .arg(path)
        .output()
        .map_err(|e| CaptureError::Backend(format!("failed to start ffprobe: {e}")))?;

    if !output.status.success() {
        return Err(CaptureError::Backend(format!(
            "ffprobe failed for {}",
            path.display()
        )));
    }

    parse_probe_json(&output.stdout)
}

fn parse_probe_json(bytes: &[u8]) -> Result<ReplayMetadata, CaptureError> {
    let value: serde_json::Value = serde_json::from_slice(bytes)
        .map_err(|e| CaptureError::Backend(format!("invalid ffprobe JSON: {e}")))?;

    let stream = value
        .get("streams")
        .and_then(|v| v.as_array())
        .and_then(|v| v.first())
        .ok_or_else(|| CaptureError::Backend("ffprobe returned no video stream".into()))?;

    let width = stream
        .get("width")
        .and_then(|v| v.as_u64())
        .and_then(|v| u32::try_from(v).ok())
        .filter(|v| *v > 0)
        .ok_or_else(|| CaptureError::Backend("invalid replay width".into()))?;

    let height = stream
        .get("height")
        .and_then(|v| v.as_u64())
        .and_then(|v| u32::try_from(v).ok())
        .filter(|v| *v > 0)
        .ok_or_else(|| CaptureError::Backend("invalid replay height".into()))?;

    let source_fps = stream
        .get("avg_frame_rate")
        .and_then(|v| v.as_str())
        .and_then(parse_fraction)
        .filter(|v| v.is_finite() && *v > 0.0);

    Ok(ReplayMetadata {
        width,
        height,
        source_fps,
    })
}

fn parse_fraction(value: &str) -> Option<f32> {
    let (num, den) = value.split_once('/')?;
    let num: f32 = num.parse().ok()?;
    let den: f32 = den.parse().ok()?;
    if den == 0.0 {
        return None;
    }
    Some(num / den)
}

#[cfg(test)]
mod tests {
    use std::fs;

    use super::*;

    #[test]
    fn parses_ffprobe_metadata() {
        let json = br#"{
          "streams": [{
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "60000/1001"
          }]
        }"#;

        let metadata = parse_probe_json(json).unwrap();
        assert_eq!(metadata.width, 1920);
        assert_eq!(metadata.height, 1080);
        assert!(metadata.source_fps.unwrap() > 59.9);
    }

    #[test]
    fn exact_frame_reader_distinguishes_eof_and_truncation() {
        let mut empty = io::Cursor::new(Vec::<u8>::new());
        let mut buffer = vec![0; 4];
        assert!(!read_exact_frame(&mut empty, &mut buffer).unwrap());

        let mut truncated = io::Cursor::new(vec![1, 2]);
        assert_eq!(
            read_exact_frame(&mut truncated, &mut buffer)
                .unwrap_err()
                .kind(),
            io::ErrorKind::UnexpectedEof
        );
    }

    #[test]
    fn zero_denominator_fraction_is_rejected() {
        assert_eq!(parse_fraction("60/0"), None);
    }

    #[test]
    fn open_rejects_missing_file_before_starting_ffmpeg() {
        let missing = std::env::temp_dir().join("agente-tft-missing-replay.mp4");
        let _ = fs::remove_file(&missing);
        assert!(ReplayVideoSource::open(missing, 10).is_err());
    }
}
