//! Tiny item icon descriptors and gallery ranking. The caller supplies only
//! public screen pixels and versioned icon art; no game process access.
use std::slice;

const GRID: usize = 16;
const CHANNELS: usize = 4;
const FEATURES: usize = GRID * GRID * CHANNELS;

#[no_mangle]
pub extern "C" fn tft_item_feature_len() -> usize {
    FEATURES
}

fn descriptor(
    data: &[u8],
    image_w: usize,
    image_h: usize,
    rect: [usize; 4],
) -> Option<[f32; FEATURES]> {
    let [x, y, w, h] = rect;
    if image_w == 0
        || image_h == 0
        || w < 4
        || h < 4
        || x.checked_add(w)? > image_w
        || y.checked_add(h)? > image_h
        || image_w.checked_mul(image_h)?.checked_mul(3)? != data.len()
    {
        return None;
    }
    let mut samples = [[0.0f32; GRID * GRID]; CHANNELS];
    for gy in 0..GRID {
        for gx in 0..GRID {
            // Exclude the outer border: item frames and selection rings vary.
            let fx = x as f32 + w as f32 * (0.05 + 0.90 * (gx as f32 + 0.5) / GRID as f32);
            let fy = y as f32 + h as f32 * (0.05 + 0.90 * (gy as f32 + 0.5) / GRID as f32);
            let px = (fx.floor() as usize).min(x + w - 1);
            let py = (fy.floor() as usize).min(y + h - 1);
            let offset = (py * image_w + px) * 3;
            let at = gy * GRID + gx;
            for channel in 0..3 {
                samples[channel][at] = data[offset + channel] as f32;
            }
        }
    }
    for gy in 0..GRID {
        for gx in 0..GRID {
            let at = gy * GRID + gx;
            let right = gy * GRID + (gx + 1).min(GRID - 1);
            let down = (gy + 1).min(GRID - 1) * GRID + gx;
            let luminance = |index: usize| {
                0.299 * samples[0][index] + 0.587 * samples[1][index] + 0.114 * samples[2][index]
            };
            samples[3][at] =
                (luminance(right) - luminance(at)).abs() + (luminance(down) - luminance(at)).abs();
        }
    }
    let mut out = [0.0f32; FEATURES];
    for (channel, values) in samples.iter().enumerate() {
        let mean = values.iter().sum::<f32>() / values.len() as f32;
        let norm = values
            .iter()
            .map(|value| (value - mean).powi(2))
            .sum::<f32>()
            .sqrt();
        if norm > 1e-6 {
            for (index, value) in values.iter().enumerate() {
                out[channel * GRID * GRID + index] = 0.5 * (value - mean) / norm;
            }
        }
    }
    if out.iter().all(|value| value.abs() < 1e-7) {
        return None;
    }
    Some(out)
}

/// Returns 0 on success. Caller validates owned buffer lengths before passing
/// pointers. Negative values mean an invalid crop or buffer contract.
#[no_mangle]
pub unsafe extern "C" fn tft_item_descriptor_rgb(
    pixels: *const u8,
    pixel_len: usize,
    image_w: usize,
    image_h: usize,
    x: usize,
    y: usize,
    w: usize,
    h: usize,
    out: *mut f32,
    out_len: usize,
) -> i32 {
    if pixels.is_null()
        || out.is_null()
        || out_len != FEATURES
        || image_w == 0
        || image_h == 0
        || image_w > 8192
        || image_h > 8192
        || image_w.checked_mul(image_h).and_then(|n| n.checked_mul(3)) != Some(pixel_len)
    {
        return -1;
    }
    let input = slice::from_raw_parts(pixels, pixel_len);
    let Some(features) = descriptor(input, image_w, image_h, [x, y, w, h]) else {
        return -2;
    };
    slice::from_raw_parts_mut(out, FEATURES).copy_from_slice(&features);
    0
}

/// Gallery consists of `count` consecutive normalized feature vectors.
/// Output positions are indices into the caller's pinned gallery manifest.
#[no_mangle]
pub unsafe extern "C" fn tft_item_rank(
    query: *const f32,
    gallery: *const f32,
    count: usize,
    indices: *mut usize,
    scores: *mut f32,
    top_n: usize,
) -> i32 {
    if query.is_null()
        || gallery.is_null()
        || indices.is_null()
        || scores.is_null()
        || count == 0
        || count > 8192
        || top_n == 0
        || top_n > 3
        || top_n > count
    {
        return -1;
    }
    let query = slice::from_raw_parts(query, FEATURES);
    let gallery = slice::from_raw_parts(gallery, count * FEATURES);
    if !query.iter().all(|v| v.is_finite()) || !gallery.iter().all(|v| v.is_finite()) {
        return -2;
    }
    let mut best = [(usize::MAX, f32::NEG_INFINITY); 3];
    for (index, candidate) in gallery.chunks_exact(FEATURES).enumerate() {
        let similarity: f32 = query.iter().zip(candidate).map(|(a, b)| a * b).sum();
        for place in 0..top_n {
            if similarity > best[place].1 {
                best.copy_within(place..top_n - 1, place + 1);
                best[place] = (index, similarity);
                break;
            }
        }
    }
    let out_indices = slice::from_raw_parts_mut(indices, top_n);
    let out_scores = slice::from_raw_parts_mut(scores, top_n);
    for place in 0..top_n {
        out_indices[place] = best[place].0;
        out_scores[place] = best[place].1;
    }
    0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn brightness_offset_keeps_structure() {
        let a = [
            0, 20, 40, 10, 30, 50, 20, 40, 60, 30, 50, 70, 40, 60, 80, 50, 70, 90, 60, 80, 100, 70,
            90, 110, 80, 100, 120, 90, 110, 130, 100, 120, 140, 110, 130, 150, 120, 140, 160, 130,
            150, 170, 140, 160, 180, 150, 170, 190,
        ];
        let b: Vec<u8> = a.iter().map(|v| v + 10).collect();
        let first = descriptor(&a, 4, 4, [0, 0, 4, 4]).unwrap();
        let shifted = descriptor(&b, 4, 4, [0, 0, 4, 4]).unwrap();
        assert!(first.iter().zip(shifted).all(|(x, y)| (x - y).abs() < 1e-5));
        assert!(descriptor(&a, 4, 4, [1, 0, 4, 4]).is_none());
    }

    #[test]
    fn ranks_distinct_vectors_without_a_model_head() {
        let mut red = vec![0.0f32; FEATURES];
        red[0] = 1.0;
        let mut green = vec![0.0f32; FEATURES];
        green[1] = 1.0;
        let gallery = [green.clone(), red.clone()].concat();
        let mut indices = [usize::MAX; 2];
        let mut scores = [0.0; 2];
        let code = unsafe {
            tft_item_rank(
                red.as_ptr(),
                gallery.as_ptr(),
                2,
                indices.as_mut_ptr(),
                scores.as_mut_ptr(),
                2,
            )
        };
        assert_eq!(code, 0);
        assert_eq!(indices, [1, 0]);
        assert_eq!(scores, [1.0, 0.0]);
    }

    #[test]
    fn flat_background_is_not_an_item_descriptor() {
        let pixels = [42u8; 8 * 8 * 3];
        assert!(descriptor(&pixels, 8, 8, [0, 0, 8, 8]).is_none());
    }
}
