"""One RGB conversion and byte buffer shared by the board observation stages."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreparedFrame:
    rgb: object
    pixels: bytes
    array: object

    @classmethod
    def from_image(cls, image, trusted_rgb_bytes: bytes | None = None):
        import numpy as np

        rgb = image if image.mode == "RGB" else image.convert("RGB")
        if trusted_rgb_bytes is not None:
            if (image.mode != "RGB" or type(trusted_rgb_bytes) is not bytes or
                    len(trusted_rgb_bytes) != rgb.width * rgb.height * 3):
                raise ValueError("Trusted RGB source does not match the image geometry")
            pixels = trusted_rgb_bytes
        else:
            pixels = rgb.tobytes()
        array = np.frombuffer(pixels, dtype=np.uint8).reshape(rgb.height, rgb.width, 3)
        return cls(rgb, pixels, array)
