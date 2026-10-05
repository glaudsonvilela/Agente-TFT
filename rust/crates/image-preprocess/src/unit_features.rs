//! Bounded native unit crops, optional foreground hypothesis and feature vectors.
//! A mask is a color/border heuristic, not verified champion segmentation.
//! No seasonal IDs, neural weights, OCR, Python or OpenCV dependency lives here.

use agente_tft_capture_core::{FrameEnvelope, PixelFormat, PixelRect};
use std::collections::VecDeque;

pub const WIDTH: usize = 128;
pub const HEIGHT: usize = 144;
pub const MAX_SIDE: usize = 224;

#[derive(Clone, Debug, PartialEq)]
pub struct UnitCrop {
    pub rgb: Vec<u8>,
}

impl UnitCrop {
    /// Extract and resize exactly the requested ROI, respecting stride/channel order.
    pub fn from_frame(frame: &FrameEnvelope, rect: PixelRect) -> Result<Self, String> {
        frame.validate().map_err(|e| e.to_string())?;
        if rect.width == 0
            || rect.height == 0
            || rect
                .x
                .checked_add(rect.width)
                .filter(|&v| v <= frame.width)
                .is_none()
            || rect
                .y
                .checked_add(rect.height)
                .filter(|&v| v <= frame.height)
                .is_none()
        {
            return Err("unit crop outside frame".into());
        }
        let mut rgb = vec![0; WIDTH * HEIGHT * 3];
        let bpp = frame.pixel_format.bytes_per_pixel();
        let read = |x: usize, y: usize, channel: usize| {
            let channel = if frame.pixel_format == PixelFormat::Bgra8 {
                2 - channel
            } else {
                channel
            };
            frame.pixels[(rect.y as usize + y) * frame.stride_bytes as usize
                + (rect.x as usize + x) * bpp
                + channel]
        };
        for y in 0..HEIGHT {
            for x in 0..WIDTH {
                let sx = ((x as f32 + 0.5) * rect.width as f32 / WIDTH as f32 - 0.5)
                    .clamp(0.0, rect.width as f32 - 1.0);
                let sy = ((y as f32 + 0.5) * rect.height as f32 / HEIGHT as f32 - 0.5)
                    .clamp(0.0, rect.height as f32 - 1.0);
                let (x0, y0) = (sx.floor() as usize, sy.floor() as usize);
                let (x1, y1) = (
                    (x0 + 1).min(rect.width as usize - 1),
                    (y0 + 1).min(rect.height as usize - 1),
                );
                for c in 0..3 {
                    let a = read(x0, y0, c) as f32 * (1.0 - sx.fract())
                        + read(x1, y0, c) as f32 * sx.fract();
                    let b = read(x0, y1, c) as f32 * (1.0 - sx.fract())
                        + read(x1, y1, c) as f32 * sx.fract();
                    rgb[(y * WIDTH + x) * 3 + c] =
                        (a * (1.0 - sy.fract()) + b * sy.fract()).round() as u8;
                }
            }
        }
        Ok(Self { rgb })
    }

    fn validate(&self) -> Result<(), String> {
        if self.rgb.len() != WIDTH * HEIGHT * 3 {
            return Err("unit RGB buffer size".into());
        }
        Ok(())
    }

    pub fn grayscale(&mut self) -> Result<(), String> {
        self.validate()?;
        for p in self.rgb.chunks_exact_mut(3) {
            let gray = ((77 * p[0] as u32 + 150 * p[1] as u32 + 29 * p[2] as u32 + 128) >> 8) as u8;
            p.fill(gray);
        }
        Ok(())
    }

    /// Remove only border-connected colors near the most common border colors.
    /// This is intentionally a separate hypothesis, never a semantic unit assertion.
    pub fn foreground(&mut self) -> Result<MaskSummary, String> {
        let background = self.background_mask()?;
        for (i, bg) in background.iter().enumerate() {
            if *bg {
                self.rgb[i * 3..i * 3 + 3].fill(127);
            }
        }
        Ok(mask_summary(&background))
    }

    /// Draw the inner boundary of the foreground hypothesis on the color crop.
    /// This includes erroneous foreground islands; it is not a verified silhouette.
    pub fn outline_overlay(&mut self, mask_background: bool) -> Result<MaskSummary, String> {
        let background = self.background_mask()?;
        let boundary = inner_boundary(&background);
        for i in 0..WIDTH * HEIGHT {
            if mask_background && background[i] {
                self.rgb[i * 3..i * 3 + 3].fill(127);
            } else if boundary[i] {
                self.rgb[i * 3..i * 3 + 3].fill(0);
            }
        }
        Ok(mask_summary(&background))
    }

    /// Binary contour view for a separate shape descriptor; preserve source pixels.
    pub fn contour_view(&self) -> Result<Self, String> {
        let boundary = inner_boundary(&self.background_mask()?);
        let mut rgb = vec![0; WIDTH * HEIGHT * 3];
        for (i, edge) in boundary.iter().enumerate() {
            if *edge {
                rgb[i * 3..i * 3 + 3].fill(255);
            }
        }
        Ok(Self { rgb })
    }

    /// Blur only the estimated background, excluding foreground colors from the
    /// box filter. Fixed radius 5; no blur or contrast changes inside foreground.
    pub fn blur_background(
        &mut self,
        outline: bool,
        grayscale_background: bool,
    ) -> Result<MaskSummary, String> {
        let background = self.background_mask()?;
        let boundary = inner_boundary(&background);
        let stride = WIDTH + 1;
        // Integral RGB sums and sample counts: bounded ~300 KiB temporary storage.
        let mut sums = vec![[0u32; 4]; stride * (HEIGHT + 1)];
        for y in 0..HEIGHT {
            let mut row = [0u32; 4];
            for x in 0..WIDTH {
                let i = y * WIDTH + x;
                if background[i] {
                    for (c, sum) in row.iter_mut().take(3).enumerate() {
                        *sum += self.rgb[i * 3 + c] as u32;
                    }
                    row[3] += 1;
                }
                for c in 0..4 {
                    sums[(y + 1) * stride + x + 1][c] = sums[y * stride + x + 1][c] + row[c];
                }
            }
        }
        for y in 0..HEIGHT {
            for x in 0..WIDTH {
                let i = y * WIDTH + x;
                if background[i] {
                    let (x0, y0) = (x.saturating_sub(5), y.saturating_sub(5));
                    let (x1, y1) = ((x + 6).min(WIDTH), (y + 6).min(HEIGHT));
                    let total = |c| {
                        sums[y1 * stride + x1][c] + sums[y0 * stride + x0][c]
                            - sums[y0 * stride + x1][c]
                            - sums[y1 * stride + x0][c]
                    };
                    let count = total(3);
                    if count > 0 {
                        for c in 0..3 {
                            self.rgb[i * 3 + c] = ((total(c) + count / 2) / count) as u8;
                        }
                        if grayscale_background {
                            let p = &mut self.rgb[i * 3..i * 3 + 3];
                            let luma =
                                ((77 * p[0] as u32 + 150 * p[1] as u32 + 29 * p[2] as u32 + 128)
                                    >> 8) as u8;
                            p.fill(luma);
                        }
                    }
                } else if outline && boundary[i] {
                    self.rgb[i * 3..i * 3 + 3].fill(0);
                }
            }
        }
        Ok(mask_summary(&background))
    }

    fn background_mask(&self) -> Result<Vec<bool>, String> {
        self.validate()?;
        let mut counts = [0u32; 512];
        let mut sums = [[0u32; 3]; 512];
        for y in 0..HEIGHT {
            for x in 0..WIDTH {
                if x < 3 || x >= WIDTH - 3 || y < 3 || y >= HEIGHT - 3 {
                    let p = &self.rgb[(y * WIDTH + x) * 3..][..3];
                    let bin =
                        (p[0] as usize / 32) * 64 + (p[1] as usize / 32) * 8 + p[2] as usize / 32;
                    counts[bin] += 1;
                    for c in 0..3 {
                        sums[bin][c] += p[c] as u32;
                    }
                }
            }
        }
        let mut order: Vec<_> = (0..512).filter(|&i| counts[i] > 0).collect();
        order.sort_by_key(|&i| (std::cmp::Reverse(counts[i]), i));
        let palette: Vec<[i32; 3]> = order
            .into_iter()
            .take(8)
            .map(|i| std::array::from_fn(|c| (sums[i][c] / counts[i]) as i32))
            .collect();
        let mut eligible = vec![false; WIDTH * HEIGHT];
        for (i, p) in self.rgb.chunks_exact(3).enumerate() {
            eligible[i] = palette
                .iter()
                .any(|b| (0..3).map(|c| (p[c] as i32 - b[c]).pow(2)).sum::<i32>() <= 3 * 26 * 26);
        }
        let mut background = vec![false; WIDTH * HEIGHT];
        let mut queue = VecDeque::with_capacity(WIDTH * HEIGHT);
        for y in 0..HEIGHT {
            for x in 0..WIDTH {
                let i = y * WIDTH + x;
                if (x == 0 || x == WIDTH - 1 || y == 0 || y == HEIGHT - 1) && eligible[i] {
                    background[i] = true;
                    queue.push_back(i);
                }
            }
        }
        while let Some(i) = queue.pop_front() {
            let (x, y) = (i % WIDTH, i / WIDTH);
            for next in [
                (x > 0).then(|| i - 1),
                (x + 1 < WIDTH).then(|| i + 1),
                (y > 0).then(|| i - WIDTH),
                (y + 1 < HEIGHT).then(|| i + WIDTH),
            ]
            .into_iter()
            .flatten()
            {
                if eligible[next] && !background[next] {
                    background[next] = true;
                    queue.push_back(next);
                }
            }
        }
        Ok(background)
    }

    /// RGB CHW in [0,1]. The exported encoder contains ImageNet normalization.
    pub fn tensor(&self, side: usize) -> Result<Vec<f32>, String> {
        self.validate()?;
        if !(32..=MAX_SIDE).contains(&side) {
            return Err("unit tensor dimension budget".into());
        }
        let mut out = vec![0.0; side * side * 3];
        for y in 0..side {
            for x in 0..side {
                let sx = ((x as f32 + 0.5) * WIDTH as f32 / side as f32 - 0.5)
                    .clamp(0.0, (WIDTH - 1) as f32);
                let sy = ((y as f32 + 0.5) * HEIGHT as f32 / side as f32 - 0.5)
                    .clamp(0.0, (HEIGHT - 1) as f32);
                let (x0, y0) = (sx.floor() as usize, sy.floor() as usize);
                let (x1, y1) = ((x0 + 1).min(WIDTH - 1), (y0 + 1).min(HEIGHT - 1));
                for c in 0..3 {
                    let at = |px, py| self.rgb[(py * WIDTH + px) * 3 + c] as f32;
                    let a = at(x0, y0) * (1.0 - sx.fract()) + at(x1, y0) * sx.fract();
                    let b = at(x0, y1) * (1.0 - sx.fract()) + at(x1, y1) * sx.fract();
                    out[c * side * side + y * side + x] =
                        (a * (1.0 - sy.fract()) + b * sy.fract()) / 255.0;
                }
            }
        }
        Ok(out)
    }

    /// Cell gradient histograms (8x9 cells, 9 unsigned bins), not a neural model.
    pub fn gradient_vector(&self) -> Result<Vec<f32>, String> {
        let mut gray = self.clone();
        gray.grayscale()?;
        let mut v = vec![0.0f32; 8 * 9 * 9];
        for y in 1..HEIGHT - 1 {
            for x in 1..WIDTH - 1 {
                let at = |px, py| gray.rgb[(py * WIDTH + px) * 3] as f32;
                let dx = at(x + 1, y) - at(x - 1, y);
                let dy = at(x, y + 1) - at(x, y - 1);
                let angle = dy.atan2(dx).rem_euclid(std::f32::consts::PI);
                let bin = ((angle / std::f32::consts::PI * 9.0) as usize).min(8);
                v[((y / 16) * 8 + x / 16) * 9 + bin] += dx.hypot(dy);
            }
        }
        for cell in v.chunks_exact_mut(9) {
            normalize(cell);
        }
        normalize(&mut v);
        Ok(v)
    }
}

fn inner_boundary(background: &[bool]) -> Vec<bool> {
    let mut edge = vec![false; WIDTH * HEIGHT];
    // Frame edges do not assert a character boundary: that silhouette is truncated.
    for y in 1..HEIGHT - 1 {
        for x in 1..WIDTH - 1 {
            let i = y * WIDTH + x;
            edge[i] = !background[i]
                && [i - 1, i + 1, i - WIDTH, i + WIDTH]
                    .iter()
                    .any(|&j| background[j]);
        }
    }
    edge
}

fn mask_summary(background: &[bool]) -> MaskSummary {
    let kept = background.iter().filter(|&&v| !v).count();
    MaskSummary {
        foreground_fraction: kept as f32 / (WIDTH * HEIGHT) as f32,
        empty: kept < WIDTH * HEIGHT / 100,
    }
}

#[derive(Clone, Copy, Debug)]
pub struct MaskSummary {
    pub foreground_fraction: f32,
    pub empty: bool,
}

pub fn normalize(v: &mut [f32]) -> bool {
    let norm = v.iter().map(|x| x * x).sum::<f32>().sqrt();
    if !norm.is_finite() || norm <= 1e-8 {
        return false;
    }
    for x in v {
        *x /= norm;
    }
    true
}

/// Cosine similarity only; callers must normalize features and apply class gates.
pub fn cosine(a: &[f32], b: &[f32]) -> Result<f32, String> {
    if a.is_empty() || a.len() != b.len() || a.iter().chain(b).any(|x| !x.is_finite()) {
        return Err("invalid feature vectors".into());
    }
    let (mut aa, mut bb, mut ab) = (0.0, 0.0, 0.0);
    for (&x, &y) in a.iter().zip(b) {
        aa += x * x;
        bb += y * y;
        ab += x * y;
    }
    if aa <= 1e-16 || bb <= 1e-16 {
        return Err("empty feature vector".into());
    }
    Ok((ab / (aa * bb).sqrt()).clamp(-1.0, 1.0))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn frame() -> FrameEnvelope {
        FrameEnvelope {
            frame_id: 1,
            captured_at_ms: 0,
            width: 2,
            height: 1,
            stride_bytes: 12,
            pixel_format: PixelFormat::Bgra8,
            source_id: "test".into(),
            pixels: vec![0, 0, 255, 255, 255, 0, 0, 255, 9, 9, 9, 9],
        }
    }
    #[test]
    fn respects_stride_bgra_and_crop() {
        let crop = UnitCrop::from_frame(
            &frame(),
            PixelRect {
                x: 1,
                y: 0,
                width: 1,
                height: 1,
            },
        )
        .unwrap();
        assert!(crop.rgb.chunks_exact(3).all(|p| p == [0, 0, 255]));
    }
    #[test]
    fn refuses_overflow_and_out_of_frame() {
        for x in [2, u32::MAX] {
            assert!(UnitCrop::from_frame(
                &frame(),
                PixelRect {
                    x,
                    y: 0,
                    width: 1,
                    height: 1
                }
            )
            .is_err());
        }
    }
    #[test]
    fn mask_preserves_distinct_center_and_rejects_blank() {
        let mut c = UnitCrop {
            rgb: vec![40; WIDTH * HEIGHT * 3],
        };
        for y in 40..100 {
            for x in 40..90 {
                c.rgb[(y * WIDTH + x) * 3..(y * WIDTH + x) * 3 + 3].copy_from_slice(&[220, 10, 10]);
            }
        }
        let m = c.foreground().unwrap();
        assert!(!m.empty);
        assert_eq!(&c.rgb[(60 * WIDTH + 60) * 3..][..3], &[220, 10, 10]);
        assert_eq!(&c.rgb[..3], &[127; 3]);
        assert!(
            UnitCrop {
                rgb: vec![40; WIDTH * HEIGHT * 3]
            }
            .foreground()
            .unwrap()
            .empty
        );
    }
    #[test]
    fn vectors_reject_blank_nonfinite_and_bad_shapes() {
        let crop = UnitCrop {
            rgb: vec![100; WIDTH * HEIGHT * 3],
        };
        assert!(cosine(
            &crop.gradient_vector().unwrap(),
            &crop.gradient_vector().unwrap()
        )
        .is_err());
        assert!(cosine(&[f32::NAN], &[1.0]).is_err());
        assert!(cosine(&[1.0], &[1.0, 2.0]).is_err());
        assert!((cosine(&[2.0, 0.0], &[10.0, 0.0]).unwrap() - 1.0).abs() < 1e-6);
        assert!(crop.tensor(4096).is_err());
        assert!(UnitCrop { rgb: vec![0] }.tensor(140).is_err());
    }

    #[test]
    fn contour_combination_preserves_color_inside_and_has_no_frame_rectangle() {
        let mut c = UnitCrop {
            rgb: vec![40; WIDTH * HEIGHT * 3],
        };
        for y in 40..100 {
            for x in 40..90 {
                c.rgb[(y * WIDTH + x) * 3..][..3].copy_from_slice(&[220, 10, 10]);
            }
        }
        let original = c.clone();
        let contour = c.contour_view().unwrap();
        assert_eq!(c, original);
        assert_eq!(&contour.rgb[(40 * WIDTH + 60) * 3..][..3], &[255; 3]);
        assert_eq!(&contour.rgb[(60 * WIDTH + 60) * 3..][..3], &[0; 3]);
        c.outline_overlay(false).unwrap();
        assert_eq!(&c.rgb[..3], &[40; 3]);
        assert_eq!(&c.rgb[(40 * WIDTH + 60) * 3..][..3], &[0; 3]);
        assert_eq!(&c.rgb[(60 * WIDTH + 60) * 3..][..3], &[220, 10, 10]);
        let blank = UnitCrop {
            rgb: vec![40; WIDTH * HEIGHT * 3],
        };
        assert!(blank.contour_view().unwrap().rgb.iter().all(|&v| v == 0));
    }

    #[test]
    fn background_blur_preserves_foreground_and_excludes_its_colors() {
        let mut c = UnitCrop {
            rgb: vec![0; WIDTH * HEIGHT * 3],
        };
        for y in 0..HEIGHT {
            for x in 0..WIDTH {
                let color = if (40..90).contains(&x) && (40..100).contains(&y) {
                    [220, 10, 10]
                } else {
                    [if (x + y) % 2 == 0 { 40 } else { 70 }; 3]
                };
                c.rgb[(y * WIDTH + x) * 3..][..3].copy_from_slice(&color);
            }
        }
        let mut outlined = c.clone();
        c.blur_background(false, false).unwrap();
        let at = |c: &UnitCrop, x, y| c.rgb[(y * WIDTH + x) * 3..][..3].to_vec();
        assert_eq!(at(&c, 40, 40), [220, 10, 10]);
        assert_eq!(at(&c, 60, 60), [220, 10, 10]);
        let bg = at(&c, 39, 40);
        assert!((50..=60).contains(&bg[0]));
        assert_eq!(bg[0], bg[1]); // No red foreground bleed into background.
        outlined.blur_background(true, false).unwrap();
        assert_eq!(at(&outlined, 40, 40), [0; 3]);
        assert_eq!(at(&outlined, 60, 60), [220, 10, 10]);
    }

    #[test]
    fn blurred_grayscale_background_keeps_foreground_color_and_original_mask() {
        let mut c = UnitCrop {
            rgb: [20, 100, 40].repeat(WIDTH * HEIGHT),
        };
        for y in 40..100 {
            for x in 40..90 {
                c.rgb[(y * WIDTH + x) * 3..][..3].copy_from_slice(&[220, 10, 10]);
            }
        }
        let original = c.clone();
        let m = c.blur_background(false, true).unwrap();
        assert!(!m.empty);
        assert_eq!(&c.rgb[..3], &[69; 3]);
        for y in 40..100 {
            for x in 40..90 {
                assert_eq!(&c.rgb[(y * WIDTH + x) * 3..][..3], &[220, 10, 10]);
            }
        }
        let mut colored = original;
        let color_mask = colored.blur_background(false, false).unwrap();
        assert_eq!(m.foreground_fraction, color_mask.foreground_fraction);
    }
}
