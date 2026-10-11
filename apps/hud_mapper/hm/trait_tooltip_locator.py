"""Locate an open Set 18 trait tooltip in an uncut 1920x1080 game frame.

This is deliberately conservative: a panel is returned only when its dark
interior has the expected full 1080p geometry and every champion slot fits.
It does not infer champion identities from a partial or clipped screenshot.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import os
import re
import subprocess
import unicodedata

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class TraitTooltip:
    bounds: tuple[int, int, int, int]
    title: str
    boxes: tuple[tuple[int, int, int, int], ...]


class TooltipTitleCache:
    """Reuse OCR only while the same title pixels stay on screen."""

    def __init__(self) -> None:
        self._geometry: tuple[int, int, int] | None = None
        self._pixels: np.ndarray | None = None
        self._title: str | None = None

    def read(self, frame: Image.Image, left: int, top: int, right: int,
             known_traits: list[str]) -> str | None:
        title_region = frame.crop((left + 40, top + 8, right - 10, top + 82))
        pixels = np.asarray(title_region.convert("L").resize((64, 20)), dtype=np.int16)
        geometry = (left, top, right)
        if (self._geometry == geometry and self._pixels is not None and
                np.abs(pixels - self._pixels).mean() < 2.0):
            return self._title
        title = _read_title(frame, left, top, right, known_traits)
        self._geometry, self._pixels, self._title = geometry, pixels, title
        return title


def _segments(mask: np.ndarray, bridge: int = 0) -> list[tuple[int, int]]:
    indexes = np.flatnonzero(mask)
    if not len(indexes):
        return []
    out = []
    start = previous = int(indexes[0])
    for index in indexes[1:]:
        index = int(index)
        if index - previous > bridge + 1:
            out.append((start, previous))
            start = index
        previous = index
    out.append((start, previous))
    return out


def _fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _read_title(frame: Image.Image, left: int, top: int, right: int,
                known_traits: list[str]) -> str | None:
    # The icon is left of the title.  Crop only the text line, never the
    # portraits or the whole tooltip.  OCR is run after the fast geometry gate.
    title = frame.crop((left + 40, top + 8, right - 10, top + 82))
    title = title.resize((title.width * 3, title.height * 3), Image.Resampling.BICUBIC)
    payload = BytesIO()
    title.save(payload, format="PNG")
    run = subprocess.run(["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "6"],
                         input=payload.getvalue(), stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, check=False, timeout=3,
                         env=dict(os.environ, OMP_THREAD_LIMIT='1'))
    if run.returncode:
        return None
    observed = _fold(run.stdout.decode("utf-8", "replace"))
    for trait in known_traits:
        if _fold(trait) in observed:
            return trait
    return None


def locate_trait_tooltip(frame: Image.Image, trait_members: dict[str, list[str]],
                         allow_alignment: bool = False,
                         title_cache: TooltipTitleCache | None = None) -> TraitTooltip | None:
    if frame.size != (1920, 1080):
        return None
    # Trait tooltips in this UI are fixed-width panels immediately to the
    # right of the left HUD.  Scan only that strip, independent of arena skin.
    strip = np.asarray(frame.crop((200, 180, 610, 1078)).convert("RGB"), dtype=np.uint8)
    dark = strip.max(axis=2) < 55
    row_dark = dark[:, 70:340].mean(axis=1)
    smooth = np.convolve(row_dark, np.ones(15) / 15, mode="same")
    panels = [segment for segment in _segments(smooth > .65, bridge=120)
              if segment[1] - segment[0] >= 170]
    if not panels:
        return None
    for first, last in sorted(panels, key=lambda segment: segment[1] - segment[0], reverse=True):
        # A dark arena can blend into the panel above its top edge.  The first
        # fully dark five-row run is the actual interior start, even there.
        solid = np.convolve((row_dark > .95).astype(np.float32), np.ones(5), mode="same")
        solid_rows = np.flatnonzero((solid >= 5) & (np.arange(len(solid)) >= first - 10))
        if not len(solid_rows):
            continue
        top = 180 + int(solid_rows[0]) - 4
        bottom = 180 + last + 6
        if not 200 <= top < bottom <= 1078 or bottom - top < 220:
            continue
        # The rightmost continuous dark column gives the interior's right
        # edge.  It is stable on both bright and dark arenas in reviewed frames.
        sample_top = max(0, first + 65)
        sample_bottom = min(dark.shape[0], first + 245, last - 105)
        if sample_bottom - sample_top < 80:
            continue
        col_dark = dark[sample_top:sample_bottom, 200:400].mean(axis=0)
        right_candidates = np.flatnonzero(col_dark > .75)
        if not len(right_candidates):
            continue
        last_dark_x = 200 + int(right_candidates[-1]) + 200
        left = last_dark_x - 325
        right = left + 329
        if not 205 <= left <= 270 or right > 610:
            continue
        trait = (title_cache.read(frame, left, top, right, list(trait_members))
                 if title_cache is not None else _read_title(frame, left, top, right, list(trait_members)))
        if trait is None:
            continue
        member_count = len(trait_members[trait])
        if not 1 <= member_count <= 10:
            continue
        # On some dark arenas the floor blends into the tooltip below its
        # border, making the row mask overestimate its height.  A contrast
        # drop immediately outside the right border supplies a second bottom
        # candidate, accepted only after every portrait frame is verified.
        inside = strip[:, right - 35 - 200:right - 15 - 200].mean(axis=(1, 2))
        outside = strip[:, right + 5 - 200:right + 25 - 200].mean(axis=(1, 2))
        contrast = np.convolve(outside - inside, np.ones(7) / 7, mode="same")
        fallback = None
        for y in range(top + 220, 1070):
            if np.all(contrast[y-180:y-180+8] < 18):
                fallback = y
                break
        bottom_options = (bottom, fallback) if fallback is None or abs(bottom - fallback) <= 5 else (fallback, bottom)
        tentative = None
        for candidate_bottom in dict.fromkeys(bottom_options):
            if candidate_bottom is None or not top + 220 <= candidate_bottom <= 1078:
                continue
            boxes = []
            # At 1080p each portrait has a 49x50 frame, five per row and
            # 58px pitch.  One-row traits sit 68px above the panel bottom;
            # two-row traits start 127px above it.  A trailing emblem is
            # excluded by the trait roster.
            textures_valid = True
            for i in range(member_count):
                col, row = i % 5, i // 5
                x = left + 18 + 58 * col
                y = candidate_bottom - (68 if member_count <= 5 else 127) + 58 * row
                box = (x, y, x + 49, y + 50)
                if x < left or y < top or box[2] > right or box[3] > candidate_bottom:
                    boxes = []
                    break
                observed = strip[y-180:y-180+50, x-200:x-200+49]
                if observed.shape != (50, 49, 3):
                    boxes = []
                    break
                if observed.mean() < 25 or observed.std() < 18:
                    textures_valid = False
                boxes.append(box)
            if len(boxes) == member_count and textures_valid:
                return TraitTooltip((left, top, right, candidate_bottom), trait, tuple(boxes))
            if allow_alignment and candidate_bottom == bottom and len(boxes) == member_count:
                tentative = TraitTooltip((left, top, right, candidate_bottom), trait, tuple(boxes))
        if tentative is not None:
            return tentative
    return None
