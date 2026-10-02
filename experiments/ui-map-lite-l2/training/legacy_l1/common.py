"""Small, auditable IO and geometry contracts. No automatic activation."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np

VERSION = 'uimap-lite-l1-v1'
WIDTH, HEIGHT = 320, 192
PANELS = ('bench', 'shop')


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def load(path: Path, limit: int = 32 * 1024**2):
    require(path.is_file() and path.stat().st_size <= limit, 'missing/oversized file: ' + str(path))
    def unique(items):
        obj = {}
        for key, value in items:
            require(key not in obj, 'duplicate JSON key')
            obj[key] = value
        return obj
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def save(path: Path, value) -> None:
    # Every run uses a fresh output directory. Never replace a prior result.
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        f.write('\n')


def contained(root: Path, name: str) -> Path:
    rel = Path(name)
    require(not rel.is_absolute() and '..' not in rel.parts, 'unsafe image path')
    path = (root / rel).resolve(strict=True)
    require(path.is_relative_to(root.resolve()), 'image outside source directory')
    return path


def corners(box: np.ndarray) -> np.ndarray:
    cx, cy, w, h = np.moveaxis(np.asarray(box), -1, 0)
    return np.stack((cx-w/2, cy-h/2, cx+w/2, cy+h/2), axis=-1)


def box_from_rect(rect, size=(1920, 1080)) -> list[float]:
    x, y, w, h = rect
    return [(x+w/2)/size[0], (y+h/2)/size[1], w/size[0], h/size[1]]


def percentile(values, q):
    return float(np.quantile(values, q)) if len(values) else None


def proposals(raw, source_size=(1920, 1080)) -> list[dict]:
    raw = np.asarray(raw, dtype=np.float32)
    require(raw.shape == (2, 5) and np.isfinite(raw).all(), 'invalid network output')
    results = []
    for name, row in zip(PANELS, raw):
        # Logit is not a calibrated probability. Do not train using this gate.
        cx, cy, w, h, logit = [float(x) for x in row]
        l, t, r, b = corners(np.asarray([cx, cy, w, h])).tolist()
        valid = 0 <= l < r <= 1 and 0 <= t < b <= 1 and w >= .08 and h >= .015
        state = 'candidate' if valid and logit >= 2.1972245773362196 else 'unknown'
        results.append(dict(panel=name, state=state,
            box_pixels=[l*source_size[0], t*source_size[1],
                        (r-l)*source_size[0], (b-t)*source_size[1]],
            visibility_logit=logit, score_calibrated=False,
            geometry_valid=valid, map_usable_by_readers=False,
            narrow_ocr_crop_safe=False, occupancy=None, unit_id=None))
    return results
