"""Run B4 against a captured frame in diagnostic mode, independently of the neural map."""
from __future__ import annotations

import json
import hashlib
import time
from pathlib import Path
from PIL import Image

from training.board_hub_item_candidates import load_reference, load_templates, select_entries
from training.board_hub_snapshot import build_snapshot
from .core import region, xyxy
from .trait_constraints import TraitCountConsensus


class BoardHubLive:
    def __init__(self, configs: str, neural_root: str | Path | None = None,
                 async_unit_recognition: bool = False):
        self.trait_count_consensus = TraitCountConsensus()
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
        item_attributes = json.loads(items_bytes)['items']
        self.item_attribute_ids = {item['api_name'] for item in item_attributes}
        trait_rows = json.loads(traits_bytes)['traits']
        self.trait_names = {trait['name']: trait['name'] for trait in trait_rows}
        trait_ids = {trait['api_name']: trait['name'] for trait in trait_rows}
        aliases_path = root / 'configs/catalog/trait-aliases-set18-en-us-16.20.json'
        if aliases_path.is_file():
            aliases = json.loads(aliases_path.read_text(encoding='utf-8'))
            if (aliases.get('schema_version') != 1 or aliases.get('set_key') != knowledge['set_key'] or
                    aliases.get('target_release_sha256') != release_manifest['release_sha256'] or
                    {row['api_name'] for row in aliases.get('traits', [])} != set(trait_ids)):
                raise ValueError('Trait translation does not match seasonal catalog')
            for row in aliases['traits']:
                alias, name = row['name'], trait_ids[row['api_name']]
                if alias in self.trait_names and self.trait_names[alias] != name:
                    raise ValueError('Ambiguous trait translation')
                self.trait_names[alias] = name
        self.champion_traits = {unit['api_name']: set(unit['traits'])
                                for unit in json.loads(units_bytes)['champions']}
        self.knowledge_release = release_manifest['release_sha256']
        self.knowledge_patch = knowledge['tft_patch']
        selected = select_entries(self.entries, self.manifest['set_key'], catalog['match_scope'])
        self.selected_item_entries = selected
        missing = [entry['icon'] for entry in selected if not (self.icons / entry['icon']).is_file()]
        available_selected = [entry for entry in selected if (self.icons / entry['icon']).is_file()]
        self.missing_item_icons = len(missing)
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
        self.inventory_templates = load_templates(available_selected, self.icons)
        self.equipped_templates = load_templates(available_selected, self.icons,
                                                 size=self.equipped['icon_size'])
        from .item_movement import ItemMovementTracker
        visible_ids = {entry['id'] for entry in selected}
        recipes = {item['api_name']: tuple(item['composition']) for item in item_attributes
                   if item['api_name'] in visible_ids and len(item['composition']) == 2
                   and set(item['composition']) <= visible_ids}
        self.item_movement = ItemMovementTracker(recipes)
        from .temporal_candidates import TemporalCandidates
        self.temporal_candidates = TemporalCandidates()
        self.item_visual = None
        self.item_visual_error = None
        try:
            from .item_visual_native import ItemVisualNative
            self.item_visual = ItemVisualNative(root, available_selected, self.icons,
                                                self.item_attribute_ids)
        except (OSError, ValueError, ImportError, RuntimeError, AttributeError) as exc:
            self.item_visual_error = str(exc)
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
        self.async_unit = None
        if async_unit_recognition and self.unit_neural is not None:
            from .async_unit_observer import AsyncUnitObserver
            self.async_unit = AsyncUnitObserver(self.unit_neural)

    def observe(self, canonical_frame, board_read: dict | None, source_frame=None) -> dict:
        if (canonical_frame.width, canonical_frame.height) != (1920, 1080):
            raise ValueError('Live B4 requires canonical 1920x1080 reader input')
        read = board_read if isinstance(board_read, dict) and board_read.get('profile') == self.board['id'] else {
            'timestamp_ms': round(canonical_frame.pts_ms), 'profile': self.board['id'],
            'projection_status': 'unresolved', 'markers': []}
        timings = {}
        started = time.perf_counter_ns()
        with Image.frombytes('RGB', (canonical_frame.width, canonical_frame.height), canonical_frame.rgb) as image:
            snapshot = build_snapshot(image, read, self.board, self.position, self.equipped,
                                      self.inventory, self.manifest, self.entries, self.icons,
                                      self.scope, inventory_templates=self.inventory_templates,
                                      equipped_templates=self.equipped_templates,
                                      allow_unmatched_arena=True,
                                      selected_entries=self.selected_item_entries)
            timings['snapshot_ms'] = (time.perf_counter_ns()-started)/1e6
            stage_started = time.perf_counter_ns()
            try:
                snapshot['neural_items'] = (self.item_neural.observe(
                    image, snapshot['inventory']['inventory'], self.inventory)
                    if self.item_neural else dict(active=False, error=self.item_neural_error))
            except Exception as exc:
                self.item_neural_error = f'{type(exc).__name__}: {exc}'
                self.item_neural = None
                snapshot['neural_items'] = dict(active=False, error=self.item_neural_error)
            timings['item_neural_ms'] = (time.perf_counter_ns()-stage_started)/1e6
            stage_started = time.perf_counter_ns()
            try:
                if self.async_unit is not None:
                    completed = self.async_unit.update(image, read,
                        frame_id=canonical_frame.id,
                        source_ms=round(canonical_frame.pts_ms),
                        epoch=getattr(source_frame or canonical_frame, 'epoch', None),
                        positions=[dict(marker_id=row['marker_id'],
                                        position_candidate=(row.get('position_candidate') or {}).copy())
                                   for row in snapshot['observed_markers']])
                    snapshot['neural_units'] = dict(active=self.async_unit.last_error is None, records=[],
                        mode='async_diagnostic_candidates', model_sha256=self.unit_neural.sha
                        if hasattr(self.unit_neural, 'sha') else None,
                        pending=self.async_unit.pending is not None,
                        submitted=self.async_unit.submitted,
                        completed=self.async_unit.completed,
                        skipped_busy=self.async_unit.dropped,
                        error=self.async_unit.last_error)
                    snapshot['unit_async_result'] = completed
                else:
                    snapshot['neural_units'] = (self.unit_neural.observe(image, read) if self.unit_neural
                                                else dict(active=False, error=self.unit_neural_error, records=[]))
            except Exception as exc:
                # Quarantine this optional model for the rest of the session.
                # A damaged model must not close screen capture or reuse IDs.
                self.unit_neural_error = f'{type(exc).__name__}: {exc}'
                self.unit_neural = None
                snapshot['neural_units'] = dict(active=False, error=self.unit_neural_error, records=[])
            timings['unit_neural_ms'] = (time.perf_counter_ns()-stage_started)/1e6
        source = source_frame if source_frame is not None else canonical_frame
        stage_started = time.perf_counter_ns()
        try:
            snapshot['item_visual_native'] = (self.item_visual.observe(source, snapshot)
                if self.item_visual else dict(active=False, error=self.item_visual_error,
                                              inventory=[], equipped=[]))
        except Exception as exc:
            # Optional item matching must never terminate the capture/preview.
            self.item_visual_error = f'{type(exc).__name__}: {exc}'
            self.item_visual = None
            snapshot['item_visual_native'] = dict(active=False, error=self.item_visual_error,
                                                   inventory=[], equipped=[])
        timings['item_visual_native_ms'] = (time.perf_counter_ns()-stage_started)/1e6
        snapshot['diagnostic_timings_ms'] = {key:round(value,1) for key,value in timings.items()}
        for row in snapshot['inventory']['candidate_slots']:
            for candidate in row['candidates']:
                self._bind_exact_attribute_ids(candidate)
        for marker in snapshot['observed_markers']:
            for slot in marker['equipped_slots']:
                for candidate in slot['candidates']:
                    self._bind_exact_attribute_ids(candidate)
        snapshot['item_movement'] = self.item_movement.update(
            snapshot, snapshot['item_visual_native'], getattr(source, 'epoch', None))
        from .item_evidence import reconcile
        snapshot['item_evidence'] = reconcile(snapshot)
        completed_unit = snapshot.get('unit_async_result')
        if completed_unit:
            snapshot['unit_async_applied'] = self.temporal_candidates.ingest_async_units(
                completed_unit, epoch=getattr(source, 'epoch', None),
                now_ms=snapshot['timestamp_ms'])
        unit_records = {row['marker_id']: row for row in snapshot['neural_units']['records']}
        for item in snapshot['item_visual_native'].get('equipped', []):
            unit = unit_records.get(item['marker_id']) or {}
            item['candidate_champion_id'] = unit.get('candidate_id')
            item['unit_identity_verified'] = False
        snapshot['temporal_candidates'] = self.temporal_candidates.update(
            snapshot, getattr(source, 'epoch', None))
        snapshot['trait_panel_observation'] = read.get('trait_panel')
        snapshot['opponent_panel_observation'] = read.get('opponent_panel')
        from .trait_constraints import bind_observed_traits, roster_hypotheses
        snapshot['trait_binding'] = bind_observed_traits(read.get('trait_panel'), self.trait_names)
        snapshot['confirmed_trait_counts'] = self.trait_count_consensus.update(
            read.get('trait_panel'), snapshot['trait_binding'],
            epoch=getattr(source, 'epoch', None), source_ms=getattr(source, 'pts_ms', None))
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
        from .equipment_identity import associate_equipment, item_candidate
        snapshot['unit_equipment_candidates'] = associate_equipment(
            snapshot['observed_markers'], unit_records)
        snapshot['inventory_identity_candidates'] = [
            item_candidate(row) for row in snapshot['inventory']['candidate_slots']]
        snapshot['visual_readiness']['candidate_items'] = sum(
            row.get('candidate_id') is not None
            for row in snapshot['item_evidence']['inventory'] +
                       snapshot['item_evidence']['equipped'])
        snapshot['visual_readiness']['persistent_unit_candidates'] = sum(
            row['candidate_id'] is not None for row in snapshot['temporal_candidates']['units'])
        snapshot['visual_readiness']['persistent_item_candidates'] = sum(
            row['candidate_id'] is not None for row in snapshot['temporal_candidates']['inventory'] +
            snapshot['temporal_candidates']['equipped'])
        snapshot['knowledge_release'] = self.knowledge_release
        snapshot['item_attributes_patch'] = self.knowledge_patch
        snapshot['item_art_missing'] = self.missing_item_icons
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
            native = next((row for row in snapshot['item_visual_native'].get('inventory', [])
                           if row['slot'] == slot['slot']), {})
            reconciled = next((row for row in snapshot['item_evidence']['inventory']
                               if row['slot'] == slot['slot']), {})
            regions.append(region(f"hub.inventory.{slot['slot']}", xyxy(slot['rect']), slot['status'],
                                  value=reconciled.get('candidate_name'),
                                  value_is_unverified_candidate=bool(candidates), item_id=None,
                                  candidate_item_id=reconciled.get('candidate_id'),
                                  item_evidence_status=reconciled.get('status'),
                                  item_evidence=reconciled.get('evidence', []),
                                  candidate_items=options,
                                  native_candidate_item_id=native.get('candidate_id'),
                                  native_item_candidates=native.get('candidates', []),
                                  game_state_write_allowed=False))
        positions = {m['marker_id']: m['position_candidate'] for m in snapshot['observed_markers']}
        for marker in read['markers']:
            location = positions.get(marker['id'])
            identity = unit_records.get(marker['id'], {})
            regions.append(region(f"hub.marker.{marker['id']}", xyxy(marker['rect']),
                                  'position_candidate' if location else 'unassigned_bar',
                                  value=location, marker_id=marker['id'], champion_id=None,
                                  candidate_champion_id=identity.get('candidate_id'),
                                  candidate_champion_name=identity.get('candidate_name'),
                                  identity_status=identity.get('status', 'unavailable'),
                                  game_state_write_allowed=False))
        for item in snapshot['item_visual_native'].get('equipped', []):
            reconciled = next((row for row in snapshot['item_evidence']['equipped']
                               if row['marker_id'] == item['marker_id'] and row['slot'] == item['slot']), {})
            regions.append(region(f"hub.equipped.{item['marker_id']}.{item['slot']}",
                                  xyxy(item['canonical_rect']), item['status'],
                                  item_id=None, candidate_item_id=reconciled.get('candidate_id'),
                                  candidate_item_name=reconciled.get('candidate_name'),
                                  item_evidence_status=reconciled.get('status'),
                                  item_evidence=reconciled.get('evidence', []),
                                  candidate_items=item.get('candidates', []),
                                  marker_id=item['marker_id'],
                                  candidate_champion_id=item.get('candidate_champion_id'),
                                  position_candidate=item.get('position_candidate'),
                                  game_state_write_allowed=False))
        return {'snapshot': snapshot, 'regions': regions}

    def _bind_exact_attribute_ids(self, candidate: dict) -> None:
        for option in candidate['catalog_options']:
            item_id = option['visual_id']
            option['attribute_id'] = item_id if item_id in self.item_attribute_ids else None
            option['attribute_binding'] = 'exact_api_name' if option['attribute_id'] else 'visual_name_only'
