"""Decode YOLO proposals in the TFT Rust vision crate when its library is present."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path


class _Box(ctypes.Structure):
    _fields_ = [("class_id", ctypes.c_uint32), ("anchor", ctypes.c_uint32),
                ("x0", ctypes.c_float), ("y0", ctypes.c_float),
                ("x1", ctypes.c_float), ("y1", ctypes.c_float),
                ("raw_score", ctypes.c_float), ("score", ctypes.c_float)]


def _library_path() -> Path:
    chosen = os.environ.get("TFT_RUST_YOLO_DECODER_LIB")
    if chosen:
        return Path(chosen)
    target = os.environ.get("CARGO_TARGET_DIR")
    if target:
        return Path(target) / "release/libagente_tft_yolo_decoder.so"
    return Path(__file__).resolve().parents[3] / "rust/target/release/libagente_tft_yolo_decoder.so"


class RustYoloDecoder:
    def __init__(self, path: Path | None = None):
        self.path = path or _library_path()
        self.library = ctypes.CDLL(str(self.path))
        self.function = self.library.tft_decode_yolo_head
        self.function.argtypes = [ctypes.POINTER(ctypes.c_float), ctypes.c_size_t,
                                  ctypes.c_size_t, ctypes.c_size_t,
                                  ctypes.c_size_t, ctypes.c_size_t,
                                  ctypes.c_size_t, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_float),
                                  ctypes.POINTER(ctypes.c_uint32),
                                  ctypes.POINTER(_Box), ctypes.c_size_t]
        self.function.restype = ctypes.c_ssize_t

    def decode(self, output, image_size, names, thresholds, limits):
        import numpy as np

        head = np.ascontiguousarray(output, dtype=np.float32)
        if head.ndim != 2 or head.shape[0] != 4 + len(names):
            raise ValueError("Unexpected YOLO head shape")
        score_floor = np.ascontiguousarray(thresholds, dtype=np.float32)
        caps = np.ascontiguousarray(limits, dtype=np.uint32)
        capacity = int(sum(limits))
        boxes = (_Box * capacity)()
        count = self.function(
            head.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), head.size,
            len(names), head.shape[1], 640, 640, image_size[0], image_size[1],
            score_floor.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            caps.ctypes.data_as(ctypes.POINTER(ctypes.c_uint32)),
            boxes, capacity,
        )
        if count < 0:
            raise ValueError("Rust YOLO decoder rejected the tensor")
        return [dict(class_name=names[box.class_id],
                     box=[round(box.x0), round(box.y0), round(box.x1), round(box.y1)],
                     confidence=round(float(box.raw_score), 4))
                for box in boxes[:count]]
