"""One RGB conversion and byte buffer shared by the board observation stages."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreparedFrame:
    rgb: object
    pixels: bytes
    array: object

    @classmethod
    def from_image(cls, image):
        import numpy as np

        rgb = image if image.mode == "RGB" else image.convert("RGB")
        pixels = rgb.tobytes()
        array = np.frombuffer(pixels, dtype=np.uint8).reshape(rgb.height, rgb.width, 3)
        return cls(rgb, pixels, array)
