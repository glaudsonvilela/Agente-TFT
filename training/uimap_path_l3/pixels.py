"""A single RGB decode; explicit pixel-edge coordinates and reusable prepared input."""
from dataclasses import dataclass
from pathlib import Path
import time
import numpy as np
from PIL import Image
from . import legacy
from uimap_lite_l2.common import require
from uimap_lite_l2.data import image_input

SOURCE_SIZE = (1920, 1080)

@dataclass(frozen=True)
class PreparedFrame:
    frame_id: int
    rgb: np.ndarray
    tensor: np.ndarray
    decode_resize_ms: float


def prepare_image(image, frame_id=0):
    require(type(frame_id) is int and frame_id >= 0, 'invalid frame id')
    require(image.size == SOURCE_SIZE, 'unregistered input resolution')
    rgb_image = image.convert('RGB')
    rgb = np.asarray(rgb_image).copy()
    tensor = image_input(rgb_image)
    rgb.setflags(write=False)
    tensor.setflags(write=False)
    return PreparedFrame(frame_id, rgb, tensor, 0.)


def decode(path, frame_id):
    start = time.perf_counter_ns()
    with Image.open(Path(path)) as im:
        frame = prepare_image(im, frame_id)
    return PreparedFrame(frame.frame_id, frame.rgb, frame.tensor,
                         (time.perf_counter_ns() - start) / 1e6)


def from_rgb(rgb, frame_id):
    a = np.asarray(rgb)
    require(a.dtype == np.uint8 and a.shape == (1080, 1920, 3), 'RGB contract')
    return prepare_image(Image.fromarray(a), frame_id)


def decode_resize_parity(image):
    """Changing the owner of the decode must not change legacy model pixels."""
    return np.array_equal(prepare_image(image).tensor, image_input(image))
