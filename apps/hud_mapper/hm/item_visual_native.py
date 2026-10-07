"""Patch-gallery item candidates from source-resolution screen crops in Rust."""
from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path
import time

from PIL import Image


class ItemVisualNative:
    def __init__(self, root: Path, entries: list[dict], icon_dir: Path,
                 active_ids: set[str], library_path: Path | None = None):
        name = ('agente_tft_hm_item_native.dll' if os.name == 'nt'
                else 'libagente_tft_hm_item_native.so')
        paths = ([library_path] if library_path else []) + [
            root / 'bin' / name,
            root / 'tools/hm-item-native/target/release' / name,
            root / 'tools/hm-item-native/target/debug' / name,
        ]
        path = next((p for p in paths if p and p.is_file()), None)
        if path is None:
            raise OSError('Native item matcher is not installed')
        self.lib = ctypes.CDLL(str(path))
        byte_ptr = ctypes.POINTER(ctypes.c_uint8)
        float_ptr = ctypes.POINTER(ctypes.c_float)
        size_ptr = ctypes.POINTER(ctypes.c_size_t)
        self.lib.tft_item_feature_len.argtypes = []
        self.lib.tft_item_feature_len.restype = ctypes.c_size_t
        self.lib.tft_item_descriptor_rgb.argtypes = [byte_ptr] + [ctypes.c_size_t] * 7 + [float_ptr, ctypes.c_size_t]
        self.lib.tft_item_descriptor_rgb.restype = ctypes.c_int
        self.lib.tft_item_rank.argtypes = [float_ptr, float_ptr, ctypes.c_size_t,
                                            size_ptr, float_ptr, ctypes.c_size_t]
        self.lib.tft_item_rank.restype = ctypes.c_int
        self.size = self.lib.tft_item_feature_len()
        if self.size != 1024:
            raise ValueError('Native item feature contract changed')
        self.groups = []
        vectors = []
        by_art = {}
        for entry in entries:
            with Image.open(icon_dir / entry['icon']) as opened:
                image = opened.convert('RGB')
            raw = image.tobytes()
            digest = hashlib.sha256(raw).hexdigest()
            if digest in by_art:
                group = self.groups[by_art[digest]]
                group['ids'].add(entry['id'])
                group['names'].add(entry.get('name') or entry['id'])
                continue
            vector = self._descriptor(raw, image.width, image.height,
                                      (0, 0, image.width, image.height))
            if vector is None:
                continue
            by_art[digest] = len(self.groups)
            self.groups.append(dict(art_sha256=digest, ids={entry['id']},
                                    names={entry.get('name') or entry['id']}))
            vectors.extend(vector)
        if len(self.groups) < 2:
            raise ValueError('Item visual gallery incomplete')
        self.matrix = (ctypes.c_float * len(vectors))(*vectors)
        self.active_ids = active_ids
        self.reference_artworks = len(self.groups)

    def _descriptor(self, pixels: bytes, width: int, height: int, rect: tuple[int, int, int, int]):
        if len(pixels) != width * height * 3:
            return None
        out = (ctypes.c_float * self.size)()
        source = ctypes.cast(ctypes.c_char_p(pixels), ctypes.POINTER(ctypes.c_uint8))
        code = self.lib.tft_item_descriptor_rgb(source, len(pixels), width, height,
            *rect, out, self.size)
        return out if code == 0 else None

    @staticmethod
    def _source_rect(rect: dict, width: int, height: int):
        sx, sy = width / 1920, height / 1080
        x = max(0, round(rect['x'] * sx))
        y = max(0, round(rect['y'] * sy))
        right = min(width, round((rect['x'] + rect['width']) * sx))
        bottom = min(height, round((rect['y'] + rect['height']) * sy))
        return x, y, right - x, bottom - y

    def rank(self, frame, rect: dict) -> dict:
        crop = self._source_rect(rect, frame.width, frame.height)
        query = self._descriptor(frame.rgb, frame.width, frame.height, crop)
        if query is None:
            return dict(status='invalid_crop', candidates=[])
        amount = min(3, len(self.groups))
        indices = (ctypes.c_size_t * amount)()
        scores = (ctypes.c_float * amount)()
        code = self.lib.tft_item_rank(query, self.matrix, len(self.groups),
                                      indices, scores, amount)
        if code:
            return dict(status='native_match_error', candidates=[])
        ranked = []
        for place in range(amount):
            group = self.groups[indices[place]]
            ranked.append(dict(visual_ids=sorted(group['ids']),
                               names=sorted(group['names']),
                               attribute_ids=sorted(group['ids'] & self.active_ids),
                               similarity=round(float(scores[place]), 6),
                               art_sha256=group['art_sha256']))
        ids = ranked[0]['attribute_ids']
        return dict(status='candidate_only', candidates=ranked,
                    candidate_id=ids[0] if len(ids) == 1 else None,
                    similarity_margin=round(ranked[0]['similarity'] - ranked[1]['similarity'], 6),
                    identity_verified=False, source_rect=list(crop),
                    score_is_probability=False)

    def observe(self, frame, snapshot: dict) -> dict:
        started = time.perf_counter()
        inventory = []
        for slot in snapshot['inventory']['candidate_slots']:
            leading = (slot.get('candidates') or [{}])[0]
            if leading.get('sample_rect'):
                result = self.rank(frame, leading['sample_rect'])
                result['rms_top_artwork_agrees'] = bool(result.get('candidates') and
                    set(result['candidates'][0]['visual_ids']) &
                    set(leading.get('ids_with_same_template', [])))
                inventory.append(dict(slot=slot['slot'], **result))
        equipped = []
        for marker in snapshot['observed_markers']:
            for slot in marker['equipped_slots']:
                if slot['status'] != 'icon_candidate':
                    continue
                leading = (slot.get('candidates') or [{}])[0]
                if leading.get('sample_rect'):
                    result = self.rank(frame, leading['sample_rect'])
                    result['rms_top_artwork_agrees'] = bool(result.get('candidates') and
                        set(result['candidates'][0]['visual_ids']) &
                        set(leading.get('ids_with_same_template', [])))
                    equipped.append(dict(marker_id=marker['marker_id'], slot=slot['slot'],
                                         position_candidate=marker['position_candidate'],
                                         **result))
        return dict(active=True, mode='source_resolution_rust_gallery_candidates',
                    reference_artworks=self.reference_artworks,
                    inventory=inventory, equipped=equipped,
                    matching_ms=round((time.perf_counter() - started) * 1000, 3),
                    game_state_write_allowed=False)
