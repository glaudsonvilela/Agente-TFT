"""Native full-frame resize for the diagnostic panel model."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

import numpy as np


class NativeMapResize:
    def __init__(self):
        name = ('agente_tft_hm_item_native.dll' if os.name == 'nt'
                else 'libagente_tft_hm_item_native.so')
        root = Path(__file__).resolve().parents[3]
        paths = [root / 'bin' / name,
                 root / 'tools/hm-item-native/target/release' / name]
        if os.environ.get('CARGO_TARGET_DIR'):
            paths.insert(0, Path(os.environ['CARGO_TARGET_DIR']) / 'release' / name)
        library = next((path for path in paths if path.is_file()), None)
        if library is None:
            raise OSError('Native visual resize is not installed')
        self.lib = ctypes.CDLL(str(library))
        self.lib.tft_map_rgb_to_chw_f32.argtypes = [
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
            ctypes.c_size_t, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_float), ctypes.c_size_t]
        self.lib.tft_map_rgb_to_chw_f32.restype = ctypes.c_int

    def resize(self, frame):
        output = np.empty((1, 3, 192, 320), dtype=np.float32)
        source = ctypes.cast(ctypes.c_char_p(frame.rgb), ctypes.POINTER(ctypes.c_uint8))
        result = self.lib.tft_map_rgb_to_chw_f32(
            source, len(frame.rgb), frame.width, frame.height,
            output.ctypes.data_as(ctypes.POINTER(ctypes.c_float)), output.size)
        if result:
            raise ValueError(f'Native visual resize rejected the frame: {result}')
        return output
