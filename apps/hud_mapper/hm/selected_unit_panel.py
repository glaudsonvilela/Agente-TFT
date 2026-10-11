"""Read the game's selected-unit card without inventing a board or bench slot.

The fixed 1080p panel supplies a name and an image.  Neither alone proves
where the unit was clicked; callers must keep slot assignment separate.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import unicodedata

import numpy as np
from PIL import Image, ImageEnhance, ImageOps


PANEL_BOX = (1670, 194, 1920, 903)
PORTRAIT_BOX = (1679, 203, 1915, 350)
NAME_BOX = (1685, 349, 1908, 378)
HEALTH_BOX = (1680, 381, 1907, 399)


def _fold(value: str) -> str:
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()


def _catalog_names(configs: str | Path) -> list[str]:
    root = Path(configs).parent
    path = root / 'configs/simulation/seasons/TFTSet18/18.3/champions.json'
    rows = json.loads(path.read_text(encoding='utf-8'))
    return sorted({row['name'] for row in rows.values() if isinstance(row.get('name'), str)})


def _green_bar(pixels: np.ndarray) -> bool:
    left, top, right, bottom = HEALTH_BOX
    bar = pixels[top:bottom, left:right, :].astype(np.int16, copy=False)
    green = (bar[:, :, 1] > 78) & (bar[:, :, 1] > bar[:, :, 0] * 1.35) & (bar[:, :, 1] > bar[:, :, 2] * 1.14)
    return bool(green.mean() > .19 and np.count_nonzero(green.mean(axis=0) > .35) >= 75)


def _name_match(observed: str, names: list[str]) -> tuple[str | None, float]:
    folded = _fold(observed)
    if not folded:
        return None, 0.0
    exact = [name for name in names if _fold(name) == folded or folded.startswith(_fold(name) + ' ')]
    if len(exact) == 1:
        return exact[0], 1.0
    # OCR can lose a single accent/character. Accept a correction only when
    # the catalog winner is clearly separated from every other champion.
    words = folded.split()
    prefixes = [" ".join(words[:length]) for length in range(1, min(3, len(words)) + 1)
                if len(" ".join(words[:length])) >= 4]
    scored = sorted(((max(SequenceMatcher(None, prefix, _fold(name)).ratio()
                          for prefix in prefixes), name)
                     for name in names), reverse=True) if prefixes else []
    if len(scored) > 1 and scored[0][0] >= .8 and scored[0][0] - scored[1][0] >= .15:
        return scored[0][1], round(scored[0][0], 3)
    return None, round(scored[0][0], 3) if scored else 0.0


class SelectedUnitPanelReader:
    def __init__(self, configs: str | Path, output: str | Path, *, tesseract: str = 'tesseract'):
        self.names = _catalog_names(configs)
        self.output = Path(output) / 'selected-unit-panels'
        self.tesseract = tesseract
        self.last_signature: bytes | None = None
        self.last_result: dict | None = None
        self.last_present = False

    def observe(self, rgb: bytes, width: int, height: int, *, frame_id: int,
                source_ms: float, epoch: int) -> dict | None:
        if (width, height) != (1920, 1080) or len(rgb) != width * height * 3:
            return None
        pixels = np.frombuffer(rgb, dtype=np.uint8).reshape(height, width, 3)
        if not _green_bar(pixels):
            was_present = self.last_present
            self.last_present = False
            self.last_signature = None
            self.last_result = None
            return (dict(status='panel_not_visible', frame_id=frame_id,
                         source_ms=source_ms, epoch=epoch)
                    if was_present else None)
        x0, y0, x1, y1 = NAME_BOX
        name_pixels = pixels[y0:y1, x0:x1]
        signature = Image.fromarray(name_pixels).convert('L').resize((56, 8)).tobytes()
        if (self.last_present and self.last_signature is not None and
                np.abs(np.frombuffer(signature, dtype=np.uint8).astype(np.int16) -
                       np.frombuffer(self.last_signature, dtype=np.uint8)).mean() < 3):
            if self.last_result is not None:
                return dict(self.last_result, frame_id=frame_id, source_ms=source_ms,
                            epoch=epoch, source='same_visible_panel_cached_name')
            return None
        self.last_present = True
        self.last_signature = signature
        name_image = Image.fromarray(name_pixels).resize(((x1-x0)*3, (y1-y0)*3), Image.Resampling.BICUBIC)
        name_image = ImageEnhance.Contrast(ImageOps.grayscale(name_image)).enhance(1.5)
        payload = BytesIO()
        name_image.save(payload, format='PNG')
        environment = dict(os.environ, OMP_THREAD_LIMIT='1')
        try:
            run = subprocess.run([self.tesseract, 'stdin', 'stdout', '-l', 'eng', '--psm', '7'],
                                 input=payload.getvalue(), stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, check=False, timeout=2,
                                 env=environment)
        except (OSError, subprocess.TimeoutExpired):
            return None
        observed = run.stdout.decode('utf-8', 'replace').strip() if run.returncode == 0 else ''
        name, score = _name_match(observed, self.names)
        if name is None:
            return dict(status='panel_name_unresolved', frame_id=frame_id,
                        source_ms=source_ms, epoch=epoch, observed_text=observed,
                        catalog_score=score, source='same_frame_selected_unit_panel',
                        slot_assignment='unresolved')
        x0, y0, x1, y1 = PORTRAIT_BOX
        portrait = Image.fromarray(pixels[y0:y1, x0:x1].copy())
        portrait_bytes = BytesIO()
        portrait.save(portrait_bytes, format='PNG', compress_level=1)
        encoded = portrait_bytes.getvalue()
        digest = hashlib.sha256(encoded).hexdigest()
        self.output.mkdir(parents=True, exist_ok=True)
        filename = f'{frame_id:09d}-{digest[:12]}.png'
        target = self.output / filename
        if not target.exists():
            target.write_bytes(encoded)
        result = dict(status='selected_unit_named', frame_id=frame_id,
                      source_ms=source_ms, epoch=epoch, champion_name=name,
                      observed_text=observed, catalog_score=score,
                      portrait=str(target.relative_to(self.output.parent)),
                      portrait_sha256=digest, portrait_box=list(PORTRAIT_BOX),
                      panel_box=list(PANEL_BOX),
                      source='same_frame_selected_unit_panel',
                      slot_assignment='unresolved', owner='unresolved',
                      confirmed_champion_name=True,
                      confirmed_reserve_ownership=False)
        self.last_result = result
        return result
