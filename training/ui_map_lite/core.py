"""Small, versioned inference contract. This module never imports a training framework."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

WIDTH, HEIGHT = 320, 192
PANELS = ('bench', 'shop')
# in, out, kernel, stride, groups. Parameter/shape contract shared with ONNX export.
LAYERS = ((3, 12, 3, 2, 1), (12, 12, 3, 2, 12), (12, 24, 1, 1, 1),
          (24, 24, 3, 2, 24), (24, 32, 1, 1, 1), (32, 32, 3, 2, 32),
          (32, 48, 1, 1, 1), (48, 48, 3, 1, 48), (48, 64, 1, 1, 1))
ARCHITECTURE = 'uimap_lite_u1_rect_visibility'


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def load_json(path: Path) -> dict:
    require(path.is_file() and path.stat().st_size < 32 * 1024**2, 'missing/excessive JSON: '+str(path))
    def unique(pairs):
        out = {}
        for k, v in pairs:
            require(k not in out, 'duplicate JSON key: '+k)
            out[k] = v
        return out
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def write_json(path: Path, value: object) -> None:
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, sort_keys=True, ensure_ascii=False, allow_nan=False)
        f.write('\n')


def inside(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute()
            and '..' not in Path(relative).parts, 'unsafe relative path')
    p = root / relative
    require(p.resolve(strict=True).is_relative_to(root.resolve(strict=True)), 'path escapes root')
    require(p.is_file() and p.stat().st_size <= 32 * 1024**2, 'missing/excessive source')
    return p


def rect_ok(box) -> bool:
    return (len(box) == 4 and all(type(x) in (int, float) and math.isfinite(x) for x in box)
            and 0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1)


def decoded(output, width: int = 1920, height: int = 1080) -> list[dict]:
    require(len(output) == 10, 'wrong network output length')
    require(all(math.isfinite(float(x)) and 0 <= float(x) <= 1 for x in output), 'invalid network output')
    observations = []
    for i, panel in enumerate(PANELS):
        row = [float(v) for v in output[i*5:i*5+5]]
        box, score = row[:4], row[4]
        geometry = rect_ok(box)
        # A region proposal is not a calibrated semantic presence probability.
        proposed = geometry and score >= .80
        observations.append(dict(panel=panel, status='proposal' if proposed else 'unresolved',
            visibility_score=score, geometry_valid=geometry,
            normalized_box=box if geometry else None,
            corners_px=[[box[0]*width, box[1]*height], [box[2]*width, box[1]*height],
                        [box[2]*width, box[3]*height], [box[0]*width, box[3]*height]] if proposed else None,
            active=False, occupancy=None, unit_id=None))
    return observations


def percentile(values, q):
    if not values:
        return None
    v = sorted(float(x) for x in values)
    pos = (len(v)-1)*q
    a, b = int(pos), min(int(pos)+1, len(v)-1)
    return v[a]+(v[b]-v[a])*(pos-a)


def statistics(predictions, targets, fixed_boxes) -> dict:
    """Generated geometry only. Abstentions are counted, never omitted from the report."""
    require(len(predictions)==len(targets)>0,'missing/unpaired generated examples')
    require(len(fixed_boxes)==2 and all(rect_ok(b) for b in fixed_boxes),'invalid fixed geometry')
    per_panel = {}
    for i, name in enumerate(PANELS):
        errors, baseline, accepted_errors = [], [], []
        pos = neg = accepted_pos = accepted_neg = invalid = 0
        for prediction, target in zip(predictions, targets):
            p = [float(x) for x in prediction[i*5:i*5+5]]
            t = [float(x) for x in target[i*5:i*5+5]]
            good = rect_ok(p[:4])
            accept = good and p[4] >= .80
            invalid += not good
            if t[4] == 1:
                pos += 1
                # Euclidean corner errors scaled back to original image pixels.
                err = (math.hypot((p[0]-t[0])*1920, (p[1]-t[1])*1080)
                       + math.hypot((p[2]-t[2])*1920, (p[3]-t[3])*1080))/2
                errors.append(err)
                f = fixed_boxes[i]
                baseline.append((math.hypot((f[0]-t[0])*1920, (f[1]-t[1])*1080)
                                 + math.hypot((f[2]-t[2])*1920, (f[3]-t[3])*1080))/2)
                accepted_pos += accept
                if accept:
                    accepted_errors.append(err)
            else:
                neg += 1
                accepted_neg += accept
        per_panel[name] = dict(visible_examples=pos, nonvisible_examples=neg,
            accepted_visible=accepted_pos, accepted_nonvisible=accepted_neg, invalid_boxes=invalid,
            corner_error_px_p50=percentile(errors,.5), corner_error_px_p95=percentile(errors,.95),
            accepted_corner_error_px_p95=percentile(accepted_errors,.95),
            fixed_map_corner_error_px_p50=percentile(baseline,.5),
            fixed_map_corner_error_px_p95=percentile(baseline,.95),
            fixed_map_nonvisible_proposals=neg,
            fixed_baseline='coordinates only; not the B1/S4 visual gates')
    return dict(kind='generated_composites_relative_to_development_crop_seeds',
                examples=len(targets), per_panel=per_panel, semantic_tft_accuracy=None,
                independent_match_validation=False)
