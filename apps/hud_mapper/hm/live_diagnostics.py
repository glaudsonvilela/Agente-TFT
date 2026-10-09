"""Small, factual snapshot for the local live inspection view.

This is display data, never a training label or an input to a decision.
"""
from __future__ import annotations

import math

from .core import valid_box


HUD_FIELDS = frozenset(('stage', 'gold', 'level', 'xp'))


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _board_position(value):
    if (not isinstance(value, dict) or value.get('status') != 'candidate_only'
            or value.get('zone') != 'board'):
        return None
    row, cell = value.get('row'), value.get('cell_or_slot')
    return ('board', row, cell) if type(row) is int and type(cell) is int else None


def build_live_diagnostic(answer, regions, *, frame_id, source_ms, epoch,
                          width, height, reader_ms, source_to_reader_ms):
    """Keep observations, unverified candidates, and Rust scores separate."""
    boxes = []
    for region in regions:
        name = str(region.get('id') or '')
        if not (name.startswith('hud.') or name.startswith('shop.') or name == 'player.hp'):
            continue
        box = region.get('box')
        if not isinstance(box, list) or not valid_box(box, width, height):
            continue
        status = region.get('status') or 'unknown'
        value = region.get('value')
        if name.startswith('shop.') and not name.endswith(('.name', '.cost')):
            continue
        boxes.append(dict(id=name, box=[round(x, 2) for x in box],
                          status=status, value=value if type(value) in (str, int, float) else None,
                          confidence=_number(region.get('confidence'))))
    hud = [{key: row.get(key) for key in ('field', 'value', 'status', 'confidence')}
           for row in answer.get('hud') or [] if row.get('field') in HUD_FIELDS]
    shop_read = answer.get('shop') or {}
    shop = [{key: slot.get(key) for key in ('slot', 'status', 'observed_name', 'observed_cost',
             'name_confidence', 'cost_confidence', 'catalog_status', 'unit_id')}
            for slot in shop_read.get('slots') or []][:5]
    rank = answer.get('decision_rank') or {}
    options = answer.get('decision_candidates') or []
    ranked = []
    for row in (rank.get('ranked') or [])[:8]:
        index = row.get('index')
        option = options[index] if type(index) is int and 0 <= index < len(options) else {}
        ranked.append(dict(index=index, action=row.get('action_type'),
                           target=(option.get('action') or {}).get('target'),
                           utility=_number(row.get('utility')),
                           base_utility=_number(row.get('base_utility')),
                           novelty_penalty=_number(row.get('novelty_penalty')),
                           persistence_bonus=_number(row.get('persistence_bonus')),
                           plan_alignment_bonus=_number(row.get('plan_alignment_bonus')),
                           recent_repeats=row.get('recent_repeats'),
                           selected=index == rank.get('selected_index')))
    decision = answer.get('decision') or {}
    action = decision.get('action') or {}
    return dict(frame_id=frame_id, source_ms=source_ms, epoch=epoch,
                image_size=[width, height], origin=answer.get('origin'),
                reader_ms=round(reader_ms, 1),
                source_to_reader_ms=round(source_to_reader_ms, 1),
                hud=hud, shop=shop,
                shop_panel_status=shop_read.get('panel_status'),
                shop_read_fresh=(shop_read.get('cadence_delivery') or {}).get('fresh') is True,
                shop_read_age_ms=_number((shop_read.get('cadence_delivery') or {}).get('age_ms')),
                boxes=boxes,
                rust=dict(status=rank.get('status'), reason=rank.get('reason'),
                          native_ms=_number(rank.get('native_ms')),
                          selected_index=rank.get('selected_index'),
                          action=action.get('type'), ranked=ranked,
                          memory_error=rank.get('memory_error')))


def build_hub_diagnostic(snapshot, regions, *, frame_id, source_ms, epoch,
                         width, height, processing_ms, worker_ms=None, observer_ms=None):
    """Expose tracked board candidates without calling them verified units."""
    temporal = snapshot.get('temporal_candidates') or {}
    observed = {row.get('marker_id'): _board_position(row.get('position_candidate'))
                for row in snapshot.get('observed_markers') or [] if isinstance(row, dict)}
    position_counts = {}
    for position in observed.values():
        if position:
            position_counts[position] = position_counts.get(position, 0) + 1
    by_position = {}
    candidate_counts = {}
    for row in temporal.get('units') or []:
        if not isinstance(row, dict) or not isinstance(row.get('position'), list):
            continue
        position = tuple(row['position'])
        candidate_counts[position] = candidate_counts.get(position, 0) + 1
        if row.get('status') == 'persistent_candidate':
            by_position[position] = row
    boxes = []
    for region in regions:
        rid = str(region.get('id') or '')
        box = region.get('box')
        if not isinstance(box, list) or not valid_box(box, width, height):
            continue
        if rid.startswith('hub.marker.'):
            marker_id = region.get('marker_id')
            if type(marker_id) is not int and isinstance(region.get('value'), dict):
                marker_id = region['value'].get('marker_id')
            position = observed.get(marker_id)
            candidate = (by_position.get(position) or {}) if (
                position_counts.get(position) == 1 and candidate_counts.get(position) == 1
            ) else {}
            name = candidate.get('candidate_name') if (candidate.get('support_frames') or 0) >= 2 else None
            x1, y1, x2, y2 = box
            # Only the health bar is observed. This larger rectangle is a
            # visual guide around it, not a detector's silhouette box.
            guide = [max(0, x1-12), max(0, y1-20), min(width, x2+12), min(height, y2+84)]
            boxes.append(dict(id=rid, box=[round(v, 2) for v in guide],
                              observed_box=[round(v, 2) for v in box],
                              label=name if isinstance(name, str) and name else 'unidade não identificada',
                              status=candidate.get('status') or region.get('status'),
                              geometry='bar_anchored_approximation',
                              identity_verified=candidate.get('identity_verified') is True,
                              support_frames=candidate.get('support_frames')))
        elif rid.startswith(('hub.inventory.', 'hub.equipped.')):
            value = region.get('value')
            boxes.append(dict(id=rid, box=[round(v, 2) for v in box],
                              label=value if isinstance(value, str) and value else 'item não identificado',
                              status=region.get('status') or 'unknown',
                              geometry='observed_icon_region', identity_verified=False))
    item_candidates = []
    native_items = snapshot.get('item_visual_native') or {}
    for zone in ('inventory', 'equipped'):
        for row in (native_items.get(zone) or [])[:12]:
            top = (row.get('candidates') or [{}])[0]
            item_candidates.append(dict(zone=zone, marker_id=row.get('marker_id'),
                slot=row.get('slot'), names=top.get('names') or [],
                similarity=_number(top.get('similarity')),
                status=row.get('status') or 'unknown', identity_verified=False))
    async_units = snapshot.get('unit_async_result') or {}
    source_bound = (async_units.get('epoch') == epoch and
                    type(async_units.get('source_ms')) is int and
                    0 <= source_ms - async_units['source_ms'] <= 5000)
    result = async_units.get('result') or {} if source_bound else {}
    unit_candidates = [{key: row.get(key) for key in
                        ('marker_id', 'box', 'candidate_name', 'top_hypothesis_name', 'status',
                         'softmax_score_uncalibrated', 'softmax_margin_uncalibrated',
                         'candidates', 'identity_verified')}
                       for row in (result.get('records') or [])[:16]]
    return dict(frame_id=frame_id, source_ms=source_ms, epoch=epoch,
                image_size=[width, height], processing_ms=round(processing_ms, 1),
                worker_ms=round(worker_ms, 1) if worker_ms is not None else None,
                observer_ms=round(observer_ms, 1) if observer_ms is not None else None,
                diagnostic_timings_ms=snapshot.get('diagnostic_timings_ms') or {},
                unit_inference=dict(pending=(snapshot.get('neural_units') or {}).get('pending'),
                    completed=(snapshot.get('neural_units') or {}).get('completed'),
                    skipped_busy=(snapshot.get('neural_units') or {}).get('skipped_busy'),
                    source_ms=async_units.get('source_ms') if source_bound else None,
                    processing_ms=_number(result.get('processing_ms')),
                    candidates=unit_candidates,
                    identity_verified=False),
                item_candidates=item_candidates[:16],
                boxes=boxes[:50],
                candidate_units=sum(1 for row in boxes if row['id'].startswith('hub.marker.')),
                verified_units=sum(1 for row in boxes if row['id'].startswith('hub.marker.')
                                   and row['identity_verified']))
