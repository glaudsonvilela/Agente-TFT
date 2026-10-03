"""Run B4 against a captured frame in diagnostic mode, independently of the neural map."""
from __future__ import annotations

import json
from pathlib import Path
from PIL import Image

from training.board_hub_item_candidates import load_reference, select_entries
from training.board_hub_snapshot import build_snapshot
from .core import region, xyxy


class BoardHubLive:
    def __init__(self, configs: str):
        root = Path(configs).absolute().parent
        profile = json.loads((root / 'configs/ui/board-hub-live-v1.json').read_text(encoding='utf-8'))
        if (profile.get('schema_version'), profile.get('id'), profile.get('semantic_mode'),
                profile.get('game_state_write_allowed')) != (1, 'board-hub-live-v1', 'candidate_only', False):
            raise ValueError('Invalid live board hub policy')
        reference = root / profile['reference']
        self.manifest, self.entries = load_reference(reference)
        if self.manifest['set_key'] != profile['set_key']:
            raise ValueError('Live set and reference mismatch')
        self.icons = root / profile['icon_dir']
        selected = select_entries(self.entries, self.manifest['set_key'], profile['match_scope'])
        missing = [entry['icon'] for entry in selected if not (self.icons / entry['icon']).is_file()]
        if missing:
            raise ValueError(f'Live icon bank incomplete: {len(missing)} assets missing')
        self.interval_ms = profile['sample_interval_ms']
        if type(self.interval_ms) is not int or not 1000 <= self.interval_ms <= 30000:
            raise ValueError('Invalid live board hub interval')
        self.scope = profile['match_scope']
        def config(name):
            return json.loads((root / 'configs/ui' / name).read_text(encoding='utf-8'))
        self.board = config('match001-board-bench-v1.json')
        self.position = config('match001-bar-to-cell-candidates-v1.json')
        self.equipped = config('match001-equipped-icons-v1.json')
        self.inventory = config('match001-inventory-v1.json')

    def observe(self, canonical_frame, board_read: dict | None) -> dict:
        if (canonical_frame.width, canonical_frame.height) != (1920, 1080):
            raise ValueError('Live B4 requires canonical 1920x1080 reader input')
        read = board_read if isinstance(board_read, dict) and board_read.get('profile') == self.board['id'] else {
            'timestamp_ms': round(canonical_frame.pts_ms), 'profile': self.board['id'],
            'projection_status': 'unresolved', 'markers': []}
        with Image.frombytes('RGB', (canonical_frame.width, canonical_frame.height), canonical_frame.rgb) as image:
            snapshot = build_snapshot(image, read, self.board, self.position, self.equipped,
                                      self.inventory, self.manifest, self.entries, self.icons,
                                      self.scope)
        # A live recording has no verified patch binding or semantic labels.
        snapshot['live_diagnostic_only'] = True
        snapshot['board_reference_status'] = 'manual_reference_active' if board_read else 'not_calibrated'
        regions = [region('hub.board.cells', None, snapshot['position_status'],
                          basis='fixed_grid_and_B1_bar_candidates',
                          guide_points=[{'screen': cell['screen_center']} for cell in snapshot['board_cells']],
                          game_state_write_allowed=False)]
        for slot in snapshot['inventory']['inventory']['slots']:
            item = next((row for row in snapshot['inventory']['candidate_slots']
                         if row['slot'] == slot['slot']), None)
            candidates = (item or {}).get('candidates') or []
            regions.append(region(f"hub.inventory.{slot['slot']}", xyxy(slot['rect']), slot['status'],
                                  value=candidates[0]['ids_with_same_template'][0] if candidates else None,
                                  value_is_unverified_candidate=bool(candidates), item_id=None,
                                  game_state_write_allowed=False))
        positions = {m['marker_id']: m['position_candidate'] for m in snapshot['observed_markers']}
        for marker in read['markers']:
            location = positions.get(marker['id'])
            regions.append(region(f"hub.marker.{marker['id']}", xyxy(marker['rect']),
                                  'position_candidate' if location else 'unassigned_bar',
                                  value=location, champion_id=None, game_state_write_allowed=False))
        return {'snapshot': snapshot, 'regions': regions}
