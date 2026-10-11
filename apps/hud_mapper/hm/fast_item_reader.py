"""Low-latency inventory candidates, independent of the full board scan."""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from training.board_hub_inventory import observe
from training.board_hub_item_candidates import load_reference, select_entries
from .item_visual_native import ItemVisualNative


class FastItemReader:
    def __init__(self, configs: str):
        root = Path(configs).absolute().parent
        catalog = json.loads((root / 'configs/catalog/active-visual-reference-v1.json').read_text())
        manifest, entries = load_reference(root / catalog['reference'])
        selected = select_entries(entries, manifest['set_key'], catalog['match_scope'])
        icons = root / catalog['icon_dir']
        if not icons.is_dir():
            icons = root / 'build/hm4-live-assets' / catalog['icon_dir']
        if not icons.is_dir() or any(not (icons / row['icon']).is_file() for row in selected):
            raise FileNotFoundError('Item artwork catalog incomplete')
        self.profile = json.loads((root / 'configs/ui/match001-inventory-v1.json').read_text())
        self.matcher = ItemVisualNative(root, selected, icons, {row['id'] for row in selected})

    def _enemy_equipped(self, frame, pixels, markers: list[dict]) -> list[dict]:
        """Read icon tiles below red health strips; retain bar linkage as a candidate."""
        found = []
        for marker in markers:
            if marker.get('color') != 'red':
                continue
            box = marker.get('box') or []
            if len(box) != 4 or box[2] - box[0] < 50:
                continue
            for slot in range(3):
                best = None
                for offset in (-8, 3):
                    x, y = round(box[0]) + offset + slot * 26, round(box[3]) + 9
                    if x < 0 or y < 0 or x + 23 > frame.width or y + 23 > frame.height:
                        continue
                    tile = pixels[y:y + 23, x:x + 23]
                    # Item tiles have a dark frame. Reject bare arena and effects before
                    # querying the gallery, which otherwise always returns a name.
                    dark_left = float(np.mean(np.max(tile[:, 0], axis=1) < 70))
                    dark_bottom = float(np.mean(np.max(tile[-1], axis=1) < 70))
                    if dark_left < .25 or dark_bottom < .65 or float(tile.std()) < 45:
                        continue
                    match = self.matcher.rank(frame, dict(x=x, y=y, width=23, height=23))
                    top = (match.get('candidates') or [None])[0]
                    if not top or top['similarity'] < .29:
                        continue
                    if best is None or top['similarity'] > best[0]['similarity']:
                        best = (top, x, y, match['similarity_margin'])
                if best is None:
                    continue
                top, x, y, margin = best
                named = margin >= .04 and len(top['names']) == 1
                found.append(dict(track_id=marker.get('track_id'), marker_box=box,
                                  scan_zone=marker.get('scan_zone'), slot=slot,
                                  rect=[x, y, x + 23, y + 23],
                                  name=top['names'][0] if named else None,
                                  candidate_ids=top['attribute_ids'] if named else [],
                                  similarity=top['similarity'], similarity_margin=margin,
                                  status='visual_candidate' if named else 'icon_observed_name_ambiguous',
                                  identity_verified=False))
        return found

    def observe(self, frame, markers: list[dict] | None = None) -> dict:
        started = time.perf_counter_ns()
        if (frame.width, frame.height) != (1920, 1080):
            return dict(status='unsupported_resolution', source_ms=frame.pts_ms,
                        frame_id=frame.id, slots=[])
        pixels = np.frombuffer(frame.rgb, dtype=np.uint8).reshape(1080, 1920, 3)
        inventory = observe(frame.rgb, frame.width, frame.height, self.profile,
                            frame_array=pixels)
        slots = []
        for slot in inventory['slots']:
            if slot['status'] != 'icon_candidate':
                continue
            rect = slot['rect']
            votes = []
            for dx in (6, 8, 10):
                sample = dict(x=rect['x'] + dx, y=rect['y'] + 9,
                              width=28, height=28)
                rank = self.matcher.rank(frame, sample)
                top = (rank.get('candidates') or [None])[0]
                if top:
                    votes.append((top, rank.get('similarity_margin')))
            if not votes:
                continue
            counts = {}
            for top, _ in votes:
                key = top['art_sha256']
                counts[key] = counts.get(key, 0) + 1
            winner = max(counts, key=counts.get)
            matching = [(top, margin) for top, margin in votes
                        if top['art_sha256'] == winner]
            top = max(matching, key=lambda pair: pair[0]['similarity'])[0]
            slots.append(dict(slot=slot['slot'], rect=rect,
                              name=top['names'][0] if len(top['names']) == 1 else None,
                              candidate_ids=top['attribute_ids'],
                              votes=len(matching), total_votes=len(votes),
                              similarity=top['similarity'],
                              status='visual_candidate' if len(matching) >= 2 else 'ambiguous',
                              identity_verified=False))
        equipped = self._enemy_equipped(frame, pixels, markers or [])
        equipped_tracks = sorted({row['track_id'] for row in equipped
                                  if row['track_id'] is not None})
        return dict(status='observed', frame_id=frame.id, source_ms=frame.pts_ms,
                    epoch=getattr(frame, 'epoch', None),
                    panel_status=inventory['panel_status'], slots=slots,
                    enemy_equipped=equipped,
                    enemy_equipment_macro=dict(visible_item_icons=len(equipped),
                        equipped_unit_tracks=len(equipped_tracks), track_ids=equipped_tracks,
                        sampled_red_bars=sum(row.get('color') == 'red' for row in markers or []),
                        status='observed_minimum', opponent_identity_verified=False),
                    reference_artworks=self.matcher.reference_artworks,
                    processing_ms=round((time.perf_counter_ns() - started) / 1e6, 3))
