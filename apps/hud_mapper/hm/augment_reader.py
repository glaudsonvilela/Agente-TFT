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
CARD_BOXES = ((375, 245, 740, 810), (780, 245, 1145, 810),
              (1190, 245, 1555, 810))


def _fold(value: str) -> str:
    plain = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', ' ', plain.lower()).strip()


def bind_offer(title: str, body: str, entries: list[dict]) -> dict:
    """Preserve duplicate game IDs unless the observed effect separates them."""
    observed = _fold(title)
    if not observed:
        return dict(status='unresolved', candidate_id=None, candidate_ids=[],
                    name_score=0.0)
    names = {}
    for row in entries:
        names.setdefault(_fold(row['name']), []).append(row)
    if observed in names:
        candidates = names[observed]
        name_score = 1.0
    else:
        scored = sorted(((SequenceMatcher(None, observed, name).ratio(), name)
                         for name in names), reverse=True)
        best_score, best_name = scored[0] if scored else (0.0, '')
        runner_score = scored[1][0] if len(scored) > 1 else 0.0
        if (len(observed) < 7 or best_score < .84 or
                best_score - runner_score < .10):
            return dict(status='unresolved', candidate_id=None, candidate_ids=[],
                        name_score=round(best_score, 3),
                        runner_up_score=round(runner_score, 3))
        candidates = names[best_name]
        name_score = best_score
    body_folded = _fold(body)
    ranked = sorted(((SequenceMatcher(None, body_folded,
                      _fold(row['description'])).ratio() if body_folded else 0.0, row)
                     for row in candidates), key=lambda pair: pair[0], reverse=True)
    top_score, best = ranked[0]
    variants_distinct = (len(ranked) < 2 or SequenceMatcher(None,
        _fold(ranked[0][1]['description']),
        _fold(ranked[1][1]['description'])).ratio() < .85)
    unique = len(ranked) == 1 or (body_folded and variants_distinct and
             top_score >= .75 and top_score - ranked[1][0] >= .08)
    result = dict(status='catalog_name_bound' if unique else 'catalog_name_ambiguous_id',
                  candidate_id=best['id'] if unique else None,
                  candidate_ids=[row['id'] for _, row in ranked],
                  candidate_name=best['name'],
                  name_score=round(name_score, 3),
                  description_similarity=round(top_score, 3))
    # A shared effect is useful even when the source game IDs are identical on
    # screen. It is reference text, never observed player choice.
    if unique or len({_fold(row['description']) for _, row in ranked}) == 1:
        result['catalog_description'] = best['description']
    return result


class AugmentReader:
    def __init__(self, configs: str | Path, *, tesseract: str = 'tesseract'):
        path = Path(configs).parent / 'configs/catalog/augments-ddragon-16.20.1-pt_BR.json'
        catalog = json.loads(path.read_text(encoding='utf-8'))
        supplement_path = (Path(configs).parent /
                           'configs/catalog/augments-set18-supplement-18.4b-pt_BR.json')
        supplement = json.loads(supplement_path.read_text(encoding='utf-8'))
        self.entries = [*catalog['entries'], *supplement['entries']]
        if len({row['id'] for row in self.entries}) != len(self.entries):
            raise ValueError('Duplicate augment ID across catalog and supplement')
        self.catalog = {key: catalog[key] for key in
                         ('data_dragon_version', 'locale', 'entry_count', 'source_urls',
                          'scope', 'live_offer_pool_complete', 'hero_augments_included')}
        self.catalog['supplement_entry_count'] = supplement['entry_count']
        self.catalog['lookup_entry_count'] = len(self.entries)
        self.catalog['supplement_source_urls'] = supplement['source_urls']
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
            for slot, (title_box, body_box, card_box) in enumerate(
                    zip(TITLE_BOXES, BODY_BOXES, CARD_BOXES)):
                title = self._ocr(image.crop(title_box), psm=6, upscale=3)
                body = self._ocr(image.crop(body_box), psm=6, upscale=2)
                options.append(dict(slot=slot, observed_title=title or '',
                                    observed_description=body or '',
                                    title_box=list(title_box), body_box=list(body_box),
                                    card_box=list(card_box),
                                    training_label=False,
                                    selection_confirmed=False,
                                    **bind_offer(title or '', body or '', self.entries)))
            self.last_signature = signature
            self.last_options = options
            status = 'visible_read'
        return dict(status=status, selection_visible=True, options=options,
                    selection_confirmed=False, reroll_count=None,
                    frame_id=frame_id, source_ms=source_ms, epoch=epoch,
                    source='same_frame_augment_choice_ocr', catalog=self.catalog,
                    catalog_patch_verified_from_client=False,
                    ground_truth=False)
