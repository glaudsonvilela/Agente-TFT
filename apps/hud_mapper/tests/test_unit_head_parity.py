from __future__ import annotations

import numpy as np

from hm.unit_head import _resize_bilinear_u8


def rust_like_resize_u8(rgb: np.ndarray, out_h: int, out_w: int) -> np.ndarray:
    src = np.asarray(rgb, dtype=np.uint8)
    in_h, in_w, channels = src.shape
    out = np.zeros((out_h, out_w, channels), dtype=np.uint8)
    for y in range(out_h):
        for x in range(out_w):
            sx = ((x + 0.5) * in_w / out_w - 0.5)
            sy = ((y + 0.5) * in_h / out_h - 0.5)
            sx = min(max(sx, 0.0), in_w - 1.0)
            sy = min(max(sy, 0.0), in_h - 1.0)
            x0, y0 = int(np.floor(sx)), int(np.floor(sy))
            x1, y1 = min(x0 + 1, in_w - 1), min(y0 + 1, in_h - 1)
            fx, fy = sx - x0, sy - y0
            for channel in range(channels):
                a = float(src[y0, x0, channel]) * (1.0 - fx) + float(src[y0, x1, channel]) * fx
                b = float(src[y1, x0, channel]) * (1.0 - fx) + float(src[y1, x1, channel]) * fx
                value = a * (1.0 - fy) + b * fy
                out[y, x, channel] = np.uint8(min(255, max(0, int(np.floor(value + 0.5)))))
    return out


def test_vectorized_u8_resize_matches_rust_quantization():
    # Deliberately use alternating values to create many .5/interpolated cases.
    source = np.zeros((5, 7, 3), dtype=np.uint8)
    for y in range(source.shape[0]):
        for x in range(source.shape[1]):
            source[y, x] = [
                (x * 37 + y * 11) % 256,
                (x * 17 + y * 53) % 256,
                (x * 91 + y * 7) % 256,
            ]
    expected = rust_like_resize_u8(source, 11, 13)
    actual = _resize_bilinear_u8(source, 11, 13)
    assert actual.dtype == np.uint8
    assert np.array_equal(actual, expected)
