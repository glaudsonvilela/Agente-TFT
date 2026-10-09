"""Local YOLO HUD reader. Every label is tentative visual evidence."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import time

from PIL import Image

from .unit_identity import unit_box


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _session(path: Path, size: int, channels: int, classes: int | None = None):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.add_session_config_entry('session.intra_op.allow_spinning', '0')
    session = ort.InferenceSession(str(path), options, providers=['CPUExecutionProvider'])
    inputs, outputs = session.get_inputs(), session.get_outputs()
    if (len(inputs) != 1 or inputs[0].shape != [1, 3, size, size] or
            len(outputs) != 1 or outputs[0].shape[0:2] != [1, channels]):
        raise ValueError(f'YOLO tensor contract mismatch: {path.name}')
    names = ast.literal_eval(session.get_modelmeta().custom_metadata_map['names'])
    count = classes if classes is not None else channels
    if len(names) != count or set(names) != set(range(count)):
        raise ValueError(f'YOLO class metadata mismatch: {path.name}')
    return session, [names[index] for index in range(count)]


def _tensor(image: Image.Image, size: int):
    import numpy as np

    # Ultralytics classification inference: shortest edge resize, center crop,
    # RGB ToTensor. Ultralytics uses mean=0 and std=1 for these models.
    width, height = image.size
    # torchvision Resize(int) truncates the longer edge. Rounding here moves
    # pixels by one column/row for many 128x144 unit crops and changes the
    # classifier's logits relative to its training transform.
    shorter, longer = min(width, height), max(width, height)
    target_longer = int(size * longer / shorter)
    target = ((size, target_longer) if width <= height else
              (target_longer, size))
    resized = image.resize(target, Image.Resampling.BILINEAR)
    left = int(round((resized.width - size) / 2))
    top = int(round((resized.height - size) / 2))
    crop = resized.crop((left, top, left + size, top + size))
    array = np.asarray(crop, dtype=np.float32).transpose(2, 0, 1) / 255.0
    return array[None]


def _enemy_health_bars_visible(image: Image.Image) -> bool:
    """Skip the second detector on quiet home boards with no red combat bars."""
    import numpy as np

    pixels = np.asarray(image)[90:680:3, 350:1550]
    red, green, blue = (pixels[:, :, channel] for channel in range(3))
    mask = (red > 80) & (red > green * 1.55) & (red > blue * 1.35) & (green < 115)
    sums = np.cumsum(mask, axis=1, dtype=np.int16)
    return bool(np.any(sums[:, 24:] - sums[:, :-24] == 24))


class YoloHudObserver:
    def __init__(self, runtime_root: Path, bundle_root: Path):
        self.root = Path(runtime_root)
        self.bundle = Path(bundle_root)
        plan = json.loads((self.bundle / 'configs/catalog/active-yolo-hud-v1.json').read_text())
        if plan.get('schema_version') != 1 or plan.get('mode') != 'diagnostic_candidates':
            raise ValueError('Invalid YOLO HUD plan')
        catalog = json.loads((self.root / 'configs/catalog/active-knowledge-release-v1.json').read_text())
        if plan['set_key'] != catalog['set_key'] or plan['tft_patch'] != catalog['tft_patch']:
            raise ValueError('YOLO bundle belongs to another TFT patch')
        folder = self.bundle / 'models/yolo-hud'
        expected = {'detector.onnx', 'enemy_detector.onnx', 'champions.onnx',
                    'items.onnx', 'items.json'}
        if set(plan['files']) != expected:
            raise ValueError('Incomplete YOLO HUD bundle')
        for name, digest in plan['files'].items():
            path = folder / name
            if not path.is_file() or path.stat().st_size > 32 * 1024**2 or _sha256(path) != digest:
                raise ValueError(f'YOLO HUD artifact mismatch: {name}')
        self.detector, detector_names = _session(folder / 'detector.onnx', 640, 12, 8)
        self.enemy_detector, enemy_names = _session(folder / 'enemy_detector.onnx', 640, 5, 1)
        self.champions, champion_names = _session(folder / 'champions.onnx', 224, 65)
        self.items, item_names = _session(folder / 'items.onnx', 96, 193)
        if detector_names != ['board_unit', 'bench_unit', 'player_entry', 'player_avatar',
                              'stage_display', 'gold_display', 'level_display', 'shop_offer']:
            raise ValueError('Unexpected YOLO detector classes')
        if enemy_names != ['enemy_unit']:
            raise ValueError('Unexpected YOLO enemy detector classes')
        self.detector_names = detector_names
        self.champion_names = champion_names
        self.item_classes = json.loads((folder / 'items.json').read_text())['classes']
        if [row['label'] for row in self.item_classes] != item_names:
            raise ValueError('YOLO item class ordering mismatch')
        units = json.loads((self.root / catalog['reference'] / 'units.json').read_text())['champions']
        by_name = {}
        for unit in units:
            by_name.setdefault(unit['name'].casefold(), []).append(unit['api_name'])
        self.champion_ids = {name: (by_name[name.casefold()][0]
                                    if len(by_name.get(name.casefold(), [])) == 1 else None)
                             for name in champion_names}
        self.sha = plan['files']['detector.onnx']
        # A local Rust build activates the TFT-specific decoder. Packaged
        # releases can set TFT_RUST_YOLO_DECODER_LIB to the bundled library.
        from .rust_yolo_decoder import RustYoloDecoder, _library_path
        decoder_path = _library_path()
        self.rust_decoder = RustYoloDecoder(decoder_path) if decoder_path.is_file() else None

    def _classify(self, session, image, box, size):
        import numpy as np

        crop = image.crop(tuple(int(v) for v in box)).convert('RGB')
        if min(crop.size) < 8:
            return None
        scores = session.run(None, {'images': _tensor(crop, size)})[0][0]
        if not np.isfinite(scores).all() or abs(float(scores.sum()) - 1.0) > .01:
            raise ValueError('Invalid YOLO classification output')
        order = np.argsort(-scores, kind='stable')[:3]
        return [(int(index), float(scores[index])) for index in order]

    def _detect(self, image, session=None, names=None, threshold=.20):
        import numpy as np

        primary = session is None
        scale = min(640 / image.width, 640 / image.height)
        width, height = round(image.width * scale), round(image.height * scale)
        pad_x, pad_y = (640 - width) // 2, (640 - height) // 2
        canvas = Image.new('RGB', (640, 640), (114, 114, 114))
        canvas.paste(image.resize((width, height), Image.Resampling.BILINEAR), (pad_x, pad_y))
        data = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
        session = session or self.detector
        names = names or self.detector_names
        output = session.run(None, {'images': data})[0][0]
        scores = output[4:]
        # Select anchors per class. A global top-k was saturated by shop and
        # player HUD anchors and silently discarded every low-score bench box.
        class_thresholds = ([.12, .10, .20, .20, .20, .20, .20, .20]
                            if primary else [threshold] * len(names))
        limits = ([16, 12, 8, 8, 1, 1, 1, 5] if primary else [16])
        if self.rust_decoder is not None:
            return self.rust_decoder.decode(output, image.size, names,
                                            class_thresholds, limits)
        detections = []
        for category, name in enumerate(names):
            class_scores = scores[category]
            candidates = np.flatnonzero(class_scores >= class_thresholds[category])
            candidates = sorted(candidates, key=lambda index: -class_scores[index])[:32]
            accepted = 0
            for index in candidates:
                x, y, width, height = map(float, output[:4, index])
                box = [round(max(0, (x - width / 2 - pad_x) / scale)),
                       round(max(0, (y - height / 2 - pad_y) / scale)),
                       round(min(image.width, (x + width / 2 - pad_x) / scale)),
                       round(min(image.height, (y + height / 2 - pad_y) / scale))]
                if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                    continue
                if any(row['class_name'] == name and _iou(box, row['box']) > .45
                       for row in detections):
                    continue
                detections.append(dict(class_name=name, box=box,
                                       confidence=round(float(class_scores[index]), 4)))
                accepted += 1
                if accepted >= limits[category]:
                    break
        return detections

    def observe(self, image, read: dict, inventory: dict, profile: dict):
        started = time.perf_counter()
        detections = self._detect(image)
        primary_end = time.perf_counter()
        enemy_detections = (self._detect(image, self.enemy_detector, ['enemy_unit'], .35)
                            if _enemy_health_bars_visible(image) else [])
        enemy_end = time.perf_counter()
        detections.extend(enemy_detections)
        from .mascot_bars import observe as observe_mascot_bars
        mascot_candidates = observe_mascot_bars(image)
        records = []
        for marker in read.get('markers', [])[:37]:
            if marker.get('color') != 'green' or type(marker.get('id')) is not int:
                continue
            box = unit_box(marker.get('rect'), image.size)
            if box is None:
                continue
            nearby = [row for row in detections if row['class_name'] in ('board_unit', 'bench_unit')]
            detected = max(nearby, key=lambda row: _iou(box, row['box']), default=None)
            if detected is not None and _iou(box, detected['box']) <= .2:
                detected = None
            crop_box = detected['box'] if detected else box
            # A green bar over the lower reserve is useful even when the
            # full-frame detector misses its much smaller unit body.
            lower_reserve = (box[1] >= image.height * .63 and
                             box[3] <= image.height * .84 and
                             box[0] >= image.width * .13 and
                             box[2] <= image.width * .85)
            zone = (detected['class_name'] if detected else
                    'bench_unit' if lower_reserve else 'unlocalized')
            predictions = self._classify(self.champions, image, crop_box, 224)
            if not predictions:
                continue
            top, score = predictions[0]
            name = self.champion_names[top]
            candidate_id = self.champion_ids[name] if score >= .55 else None
            records.append(dict(marker_id=marker['id'], box=crop_box,
                                zone=zone,
                                candidate_id=candidate_id, candidate_name=name,
                                status='identity_candidate' if candidate_id else 'unknown',
                                confidence_uncalibrated=score, identity_verified=False,
                                candidates=[dict(name=self.champion_names[index],
                                                 unit_id=self.champion_ids[self.champion_names[index]],
                                                 score_uncalibrated=value)
                                            for index, value in predictions]))
        bench_records = []
        for detected in detections:
            if detected['class_name'] != 'bench_unit':
                continue
            matched = max((row for row in records if row['zone'] == 'bench_unit'),
                          key=lambda row: _iou(row['box'], detected['box']), default=None)
            if matched is not None and _iou(matched['box'], detected['box']) <= .5:
                matched = None
            if matched:
                bench_records.append(dict(box=detected['box'], zone='bench',
                    candidate_id=matched['candidate_id'],
                    candidate_name=matched['candidate_name'],
                    confidence_uncalibrated=matched['confidence_uncalibrated'],
                    identity_verified=False, side='visible_board_unverified'))
                continue
            predictions = self._classify(self.champions, image, detected['box'], 224)
            if not predictions:
                continue
            top, score = predictions[0]
            name = self.champion_names[top]
            bench_records.append(dict(box=detected['box'], zone='bench',
                candidate_id=self.champion_ids[name] if score >= .55 else None,
                candidate_name=name, confidence_uncalibrated=score,
                identity_verified=False, side='visible_board_unverified'))
        for record in records:
            if record['zone'] != 'bench_unit':
                continue
            if any(_iou(record['box'], row['box']) > .5 for row in bench_records):
                continue
            bench_records.append(dict(box=record['box'], zone='bench',
                candidate_id=record['candidate_id'],
                candidate_name=record['candidate_name'],
                confidence_uncalibrated=record['confidence_uncalibrated'],
                identity_verified=False, side='visible_board_unverified',
                localization_source='lower_reserve_health_bar'))
        enemy_records = []
        for detected in enemy_detections:
            predictions = self._classify(self.champions, image, detected['box'], 224)
            if not predictions:
                continue
            top, score = predictions[0]
            enemy_records.append(dict(box=detected['box'], side='enemy',
                candidate_id=self.champion_ids[self.champion_names[top]] if score >= .55 else None,
                candidate_name=self.champion_names[top],
                confidence_uncalibrated=score, identity_verified=False))
        units_end = time.perf_counter()
        item_records = []
        offset, extent = profile['icon_inner_offset'], profile['icon_inner_size']
        for slot in inventory.get('slots', []):
            if slot.get('status') != 'icon_candidate':
                continue
            rect = slot['rect']
            x, y = rect['x'] + offset['x'], rect['y'] + offset['y']
            box = [x, y, x + extent['width'], y + extent['height']]
            predictions = self._classify(self.items, image, box, 96)
            if predictions:
                item_records.append(dict(slot=slot['slot'], box=box,
                    candidates=[dict(ids=self.item_classes[index]['ids'],
                                     names=sorted(set(self.item_classes[index]['names'])),
                                     score=value) for index, value in predictions]))
        elapsed = (time.perf_counter() - started) * 1000
        timing = dict(primary_detector_ms=(primary_end - started) * 1000,
                      enemy_detector_ms=(enemy_end - primary_end) * 1000,
                      units_and_mascots_ms=(units_end - enemy_end) * 1000,
                      items_ms=(time.perf_counter() - units_end) * 1000)
        return (dict(active=True, recognizer='yolo_onnx', records=records,
                     bench_records=bench_records,
                     enemy_records=enemy_records, detections=detections,
                     mascot_candidates=mascot_candidates,
                     trained_champions=len(self.champion_names),
                     model_sha256=self.sha, processing_ms=elapsed, timing_ms=timing,
                     mode='diagnostic_candidates', identity_verified=False),
                dict(active=True, recognizer='yolo_onnx', records=item_records,
                     model_sha256=self.sha, processing_ms=elapsed,
                     mode='diagnostic_candidates'))


def _iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    overlap = max(0, x1 - x0) * max(0, y1 - y0)
    return overlap / max(1, (a[2] - a[0]) * (a[3] - a[1]) +
                         (b[2] - b[0]) * (b[3] - b[1]) - overlap)
