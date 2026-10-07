"""Run B4 against a captured frame in diagnostic mode, independently of the neural map."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from PIL import Image

from training.board_hub_item_candidates import load_reference, load_templates, select_entries
from training.board_hub_snapshot import build_snapshot
from .core import region, xyxy


class BoardHubLive:
    def __init__(self, configs: str, neural_root: str | Path | None = None):
        root = Path(configs).absolute().parent
        neural_root = Path(neural_root).absolute() if neural_root else root
        profile = json.loads((root / 'configs/ui/board-hub-live-v1.json').read_text(encoding='utf-8'))
        catalog = json.loads((root / 'configs/catalog/active-visual-reference-v1.json').read_text(encoding='utf-8'))
        if (profile.get('schema_version'), profile.get('id'), profile.get('semantic_mode'),
                profile.get('game_state_write_allowed')) != (1, 'board-hub-live-v1', 'candidate_only', False):
            raise ValueError('Invalid live board hub policy')
        reference = root / catalog['reference']
        self.manifest, self.entries = load_reference(reference)
        if self.manifest['set_key'] != catalog['set_key']:
            raise ValueError('Live set and reference mismatch')
        self.icons = root / catalog['icon_dir']
        knowledge = json.loads((root / 'configs/catalog/active-knowledge-release-v1.json').read_text(encoding='utf-8'))
        release = root / knowledge['reference']
        release_manifest = json.loads((release / 'release.json').read_text(encoding='utf-8'))
        items_bytes = (release / 'items.json').read_bytes()
        units_bytes = (release / 'units.json').read_bytes()
        traits_bytes = (release / 'traits.json').read_bytes()
        if (knowledge['set_key'] != self.manifest['set_key'] or
                release_manifest['set']['key'] != knowledge['set_key'] or
                release_manifest['tft_patch'] != knowledge['tft_patch'] or
                hashlib.sha256(items_bytes).hexdigest() != release_manifest['components']['items']['sha256'] or
                hashlib.sha256(units_bytes).hexdigest() != release_manifest['components']['units']['sha256'] or
                hashlib.sha256(traits_bytes).hexdigest() != release_manifest['components']['traits']['sha256']):
            raise ValueError('Visual items and structured release differ')
        self.item_attribute_ids = {item['api_name'] for item in json.loads(items_bytes)['items']}
        self.trait_names = {trait['name'] for trait in json.loads(traits_bytes)['traits']}
        self.champion_traits = {unit['api_name']: set(unit['traits'])
                                for unit in json.loads(units_bytes)['champions']}
        self.knowledge_release = release_manifest['release_sha256']
        self.knowledge_patch = knowledge['tft_patch']
        selected = select_entries(self.entries, self.manifest['set_key'], catalog['match_scope'])
        missing = [entry['icon'] for entry in selected if not (self.icons / entry['icon']).is_file()]
        if missing:
            raise ValueError(f'Live icon bank incomplete: {len(missing)} assets missing')
        self.interval_ms = profile['sample_interval_ms']
        if type(self.interval_ms) is not int or not 1000 <= self.interval_ms <= 30000:
            raise ValueError('Invalid live board hub interval')
        self.scope = catalog['match_scope']
        def config(name):
            return json.loads((root / 'configs/ui' / name).read_text(encoding='utf-8'))
        self.board = config('match001-board-bench-v1.json')
        self.position = config('match001-bar-to-cell-candidates-v1.json')
        self.equipped = config('match001-equipped-icons-v1.json')
        self.inventory = config('match001-inventory-v1.json')
        # Pinned icon art is immutable during a session. Decode it once, not on
        # every B4 frame; a new catalog/session builds a new cache.
        self.inventory_templates = load_templates(selected, self.icons)
        self.equipped_templates = load_templates(selected, self.icons,
                                                 size=self.equipped['icon_size'])
        self.item_neural=None
        self.item_neural_error=None
        if ((neural_root/'configs/catalog/active-item-neural-v1.json').is_file() or
                (root/'configs/catalog/active-item-neural-v1.json').is_file()):
            try:
                from .item_neural import ItemIconObserver
                self.item_neural=ItemIconObserver(root, neural_root)
            except (OSError,ValueError,ImportError,RuntimeError) as exc:
                self.item_neural_error=str(exc)
        self.unit_neural = None
        self.unit_neural_error = 'unit_model_not_installed'
        if (neural_root / 'configs/catalog/active-unit-head-v1.json').is_file():
            try:
                from .unit_head import UnitHeadObserver
                self.unit_neural = UnitHeadObserver(root, neural_root)
                self.unit_neural_error = None
            except (OSError, ValueError, ImportError, RuntimeError) as exc:
                self.unit_neural_error = str(exc)
        if self.unit_neural is None and (root / 'configs/catalog/active-unit-gallery-v1.json').is_file():
            try:
                from .unit_gallery import UnitGalleryObserver
                self.unit_neural = UnitGalleryObserver(root, neural_root)
                self.unit_neural_error = None
            except (OSError, ValueError, ImportError, RuntimeError) as exc:
                self.unit_neural_error = str(exc)
        elif self.unit_neural is None and (root / 'configs/catalog/active-unit-identity-v1.json').is_file():
            try:
                from .unit_identity import UnitIdentityObserver
                self.unit_neural = UnitIdentityObserver(root)
                self.unit_neural_error = None
            except (OSError, ValueError, ImportError, RuntimeError) as exc:
                self.unit_neural_error = str(exc)

    def observe(self, canonical_frame, board_read: dict | None) -> dict:
        if (canonical_frame.width, canonical_frame.height) != (1920, 1080):
            raise ValueError('Live B4 requires canonical 1920x1080 reader input')
        read = board_read if isinstance(board_read, dict) and board_read.get('profile') == self.board['id'] else {
            'timestamp_ms': round(canonical_frame.pts_ms), 'profile': self.board['id'],
            'projection_status': 'unresolved', 'markers': []}
        with Image.frombytes('RGB', (canonical_frame.width, canonical_frame.height), canonical_frame.rgb) as image:
            snapshot = build_snapshot(image, read, self.board, self.position, self.equipped,
                                      self.inventory, self.manifest, self.entries, self.icons,
                                      self.scope, inventory_templates=self.inventory_templates,
                                      equipped_templates=self.equipped_templates,
                                      allow_unmatched_arena=True)
            snapshot['neural_items']=(self.item_neural.observe(image,snapshot['inventory']['inventory'],self.inventory)
                if self.item_neural else dict(active=False,error=self.item_neural_error))
            try:
                snapshot['neural_units'] = (self.unit_neural.observe(image, read) if self.unit_neural
                                            else dict(active=False, error=self.unit_neural_error, records=[]))
            except Exception as exc:
                # Quarantine this optional model for the rest of the session.
                # A damaged model must not close screen capture or reuse IDs.
                self.unit_neural_error = f'{type(exc).__name__}: {exc}'
                self.unit_neural = None
                snapshot['neural_units'] = dict(active=False, error=self.unit_neural_error, records=[])
        unit_records = {row['marker_id']: row for row in snapshot['neural_units']['records']}
        snapshot['trait_panel_observation'] = read.get('trait_panel')
        from .trait_constraints import bind_observed_traits, roster_hypotheses
        snapshot['trait_binding'] = bind_observed_traits(read.get('trait_panel'), self.trait_names)
        snapshot['trait_roster_hypotheses'] = roster_hypotheses(
            snapshot['trait_binding'], read.get('markers') or [], self.champion_traits)
        for marker in snapshot['observed_markers']:
            marker['identity_observation'] = unit_records.get(marker['marker_id'])
        snapshot['visual_readiness'] = dict(
            complete=False, verified_units=0,
            candidate_units=sum(row.get('candidate_id') is not None for row in unit_records.values()),
            observed_unit_regions=len(unit_records),
            trained_champions=snapshot['neural_units'].get('trained_champions', 0),
            blockers=['UNIT_IDENTITY_VALIDATION_PENDING', 'STARS_UNVERIFIED',
                      'GROUND_POSITIONS_UNVERIFIED', 'ITEMS_UNVERIFIED',
                      'PERSPECTIVE_AND_PHASE_UNVERIFIED'])
        for row in snapshot['inventory']['candidate_slots']:
            for candidate in row['candidates']:
                self._bind_exact_attribute_ids(candidate)
        for marker in snapshot['observed_markers']:
            for slot in marker['equipped_slots']:
                for candidate in slot['candidates']:
                    self._bind_exact_attribute_ids(candidate)
        from .equipment_identity import associate_equipment, item_candidate
        snapshot['unit_equipment_candidates'] = associate_equipment(
            snapshot['observed_markers'], unit_records)
        snapshot['inventory_identity_candidates'] = [
            item_candidate(row) for row in snapshot['inventory']['candidate_slots']]
        snapshot['knowledge_release'] = self.knowledge_release
        snapshot['item_attributes_patch'] = self.knowledge_patch
        # A live recording has no verified patch binding or semantic labels.
        snapshot['live_diagnostic_only'] = True
        snapshot['board_reference_status'] = (read.get('reference_basis', 'reference_unspecified')
                                               if board_read else 'not_calibrated')
        regions = [region('hub.board.cells', None, snapshot['position_status'],
                          basis='fixed_grid_and_B1_bar_candidates',
                          guide_points=[{'screen': cell['screen_center']} for cell in snapshot['board_cells']],
                          game_state_write_allowed=False)]
        for slot in snapshot['inventory']['inventory']['slots']:
            item = next((row for row in snapshot['inventory']['candidate_slots']
                         if row['slot'] == slot['slot']), None)
            candidates = (item or {}).get('candidates') or []
            leading = candidates[0] if candidates else None
            options = leading['catalog_options'] if leading else []
            names={option['name'] for option in options}
            regions.append(region(f"hub.inventory.{slot['slot']}", xyxy(slot['rect']), slot['status'],
                                  value=next(iter(names)) if len(names)==1 else None,
                                  value_is_unverified_candidate=bool(candidates), item_id=None,
                                  candidate_items=options,
                                  game_state_write_allowed=False))
        positions = {m['marker_id']: m['position_candidate'] for m in snapshot['observed_markers']}
        for marker in read['markers']:
            location = positions.get(marker['id'])
            identity = unit_records.get(marker['id'], {})
            regions.append(region(f"hub.marker.{marker['id']}", xyxy(marker['rect']),
                                  'position_candidate' if location else 'unassigned_bar',
                                  value=location, champion_id=None,
                                  candidate_champion_id=identity.get('candidate_id'),
                                  candidate_champion_name=identity.get('candidate_name'),
                                  identity_status=identity.get('status', 'unavailable'),
                                  game_state_write_allowed=False))
        return {'snapshot': snapshot, 'regions': regions}

    def _bind_exact_attribute_ids(self, candidate: dict) -> None:
        for option in candidate['catalog_options']:
            item_id = option['visual_id']
            option['attribute_id'] = item_id if item_id in self.item_attribute_ids else None
            option['attribute_binding'] = 'exact_api_name' if option['attribute_id'] else 'visual_name_only'
