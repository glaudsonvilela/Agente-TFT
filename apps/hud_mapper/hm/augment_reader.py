"""Read the three visible TFT augment offers without choosing one.

The immutable 1080p frame is processed on a separate, latest-only lane. OCR
and catalog binding are observations, never labels for visual training.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
import json
import os
import re
import subprocess
import unicodedata

from PIL import Image


HEADING = (800, 190, 1120, 250)
TITLE_BOXES = ((430, 525, 700, 568), (830, 525, 1090, 568),
               (1230, 525, 1525, 568))
BODY_BOXES = ((420, 570, 695, 690), (830, 570, 1090, 810),
              (1235, 570, 1520, 705))


def _fold(value: str) -> str:
    plain = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', ' ', plain.lower()).strip()


def bind_offer(title: str, body: str, entries: list[dict]) -> dict:
    """Bind only a well separated catalog name; preserve unbound OCR evidence."""
    observed = _fold(title)
    if not observed:
        return dict(status='unresolved', candidate_id=None, name_score=0.0)
    scores = sorted(((SequenceMatcher(None, observed, _fold(row['name'])).ratio(), row)
                     for row in entries), key=lambda pair: pair[0], reverse=True)
    if not scores:
        return dict(status='unresolved', candidate_id=None, name_score=0.0)
    best_score, best = scores[0]
    runner_score = scores[1][0] if len(scores) > 1 else 0.0
    exact = observed == _fold(best['name'])
    # Titles that are too short or close to two catalog entries stay unresolved.
    bound = (len(observed) >= 7 and best_score >= (1.0 if exact else .84)
             and best_score - runner_score >= .10)
    result = dict(status='catalog_name_bound' if bound else 'unresolved',
                  candidate_id=best['id'] if bound else None,
                  candidate_name=best['name'] if bound else None,
                  name_score=round(best_score, 3),
                  runner_up_score=round(runner_score, 3))
    if bound:
        result['catalog_description'] = best['description']
        result['description_similarity'] = round(SequenceMatcher(
            None, _fold(body), _fold(best['description'])).ratio(), 3) if body else 0.0
        result['disabled_in_catalog_revision'] = bool(best['disabled_18_3b'])
    return result


class AugmentReader:
    def __init__(self, configs: str | Path, *, tesseract: str = 'tesseract'):
        path = Path(configs).parent / 'configs/catalog/augments-set18-18.3-pt_BR.json'
        catalog = json.loads(path.read_text(encoding='utf-8'))
        self.entries = catalog['entries']
        self.catalog = {key: catalog[key] for key in
                        ('set_key', 'tft_patch', 'patch_revision', 'locale',
                         'data_dragon_version', 'source_url', 'source_scope')}
        self.tesseract = tesseract
        self.last_visible = False
        self.last_signature: bytes | None = None
        self.last_options: list[dict] | None = None
        self.last_epoch: int | None = None

    def _ocr(self, image: Image.Image, *, psm: int, upscale: int = 1) -> str | None:
        if upscale > 1:
            image = image.resize((image.width * upscale, image.height * upscale),
                                 Image.Resampling.BICUBIC)
        payload = BytesIO()
        image.save(payload, format='PNG', compress_level=1)
        try:
            run = subprocess.run([self.tesseract, 'stdin', 'stdout', '-l', 'eng',
                                  '--psm', str(psm)], input=payload.getvalue(),
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 check=False, timeout=3,
                                 env=dict(os.environ, OMP_THREAD_LIMIT='1'))
        except (OSError, subprocess.TimeoutExpired):
            return None
        return run.stdout.decode('utf-8', 'replace').strip() if run.returncode == 0 else ''

    def observe(self, rgb: bytes, width: int, height: int, *, frame_id: int,
                source_ms: float, epoch: int) -> dict | None:
        if (width, height) != (1920, 1080) or len(rgb) != width * height * 3:
            return None
        if epoch != self.last_epoch:
            self.last_visible = False
            self.last_signature = None
            self.last_options = None
            self.last_epoch = epoch
        image = Image.frombytes('RGB', (width, height), rgb)
        heading = self._ocr(image.crop(HEADING), psm=7)
        if heading is None:
            return None
        visible = SequenceMatcher(None, _fold(heading), 'escolha um').ratio() >= .8
        if not visible:
            was_visible = self.last_visible
            self.last_visible = False
            self.last_signature = None
            self.last_options = None
            return (dict(status='not_visible', selection_visible=False, options=[],
                         frame_id=frame_id, source_ms=source_ms, epoch=epoch)
                    if was_visible else None)
        self.last_visible = True
        signature = b''.join(image.crop(box).convert('L').resize((64, 12)).tobytes()
                             for box in TITLE_BOXES)
        unchanged = (self.last_signature is not None and len(signature) == len(self.last_signature)
                     and sum(abs(a - b) for a, b in zip(signature, self.last_signature))
                     / len(signature) < 3)
        if unchanged and self.last_options is not None:
            options = self.last_options
            status = 'visible_cached'
        else:
            options = []
            for slot, (title_box, body_box) in enumerate(zip(TITLE_BOXES, BODY_BOXES)):
                title = self._ocr(image.crop(title_box), psm=6, upscale=3)
                body = self._ocr(image.crop(body_box), psm=6, upscale=2)
                options.append(dict(slot=slot, observed_title=title or '',
                                    observed_description=body or '',
                                    title_box=list(title_box), body_box=list(body_box),
                                    **bind_offer(title or '', body or '', self.entries)))
            self.last_signature = signature
            self.last_options = options
            status = 'visible_read'
        return dict(status=status, selection_visible=True, options=options,
                    selection_confirmed=False, reroll_count=None,
                    frame_id=frame_id, source_ms=source_ms, epoch=epoch,
                    source='same_frame_augment_choice_ocr', catalog=self.catalog,
                    ground_truth=False)
