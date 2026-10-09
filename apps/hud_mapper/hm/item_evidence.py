"""Reconcile patch artwork, Rust descriptors, and inventory neural candidates.

Agreement produces a named observation, never a verified equipment action or
training label. The neural item head does not inspect equipped slots.
"""
from __future__ import annotations


def _template(slot):
    leading = (slot.get('candidates') or [{}])[0]
    options = leading.get('catalog_options') or []
    attributes = {row['attribute_id'] for row in options if row.get('attribute_id')}
    visual = {row['visual_id'] for row in options if row.get('visual_id')}
    names = {row['name'] for row in options if row.get('name')}
    return attributes, visual, names


def _native(row):
    leading = (row.get('candidates') or [{}])[0]
    return set(leading.get('attribute_ids') or []), set(leading.get('visual_ids') or [])


def _neural(row):
    leading = (row.get('candidates') or [{}])[0]
    return set(leading.get('ids') or [])


def _resolve(template, native, neural=None):
    attributes, visual, names = _template(template)
    native_attributes, native_visual = _native(native)
    common = attributes & native_attributes
    binding = 'exact_attribute_id'
    evidence = ['patch_artwork_top', 'rust_descriptor_top']
    if neural is not None:
        evidence.append('neural_inventory_top')
        common &= _neural(neural)
    if not common:
        common = visual & native_visual
        if neural is not None:
            common &= _neural(neural)
        binding = 'visual_id_only'
    if len(common) == 1 and len(names) == 1:
        return dict(status='corroborated_candidate', candidate_id=next(iter(common)),
                    candidate_name=next(iter(names)), evidence=evidence,
                    catalog_binding=binding,
                    identity_verified=False, game_state_write_allowed=False,
                    training_label=False)
    return dict(status='conflicting_or_missing_evidence', candidate_id=None,
                candidate_name=None, evidence=evidence, catalog_binding=None,
                identity_verified=False, game_state_write_allowed=False,
                training_label=False)


def reconcile(snapshot):
    inventory = snapshot['inventory']['candidate_slots']
    native = snapshot['item_visual_native']
    neural = snapshot['neural_items']
    native_inventory = {row['slot']: row for row in native.get('inventory', [])}
    neural_inventory = {row['slot']: row for row in neural.get('records', [])}
    seen = []
    for slot in inventory:
        index = slot['slot']
        if index not in native_inventory:
            continue
        neural_row = neural_inventory.get(index, {}) if neural.get('active') else None
        seen.append(dict(slot=index,
                         **_resolve(slot, native_inventory[index], neural_row)))

    native_equipped = {(row['marker_id'], row['slot']): row
                       for row in native.get('equipped', [])}
    equipped = []
    for marker in snapshot['observed_markers']:
        for slot in marker['equipped_slots']:
            key = (marker['marker_id'], slot['slot'])
            if key not in native_equipped:
                continue
            equipped.append(dict(marker_id=key[0], slot=key[1],
                                 position_candidate=marker.get('position_candidate'),
                                 **_resolve(slot, native_equipped[key])))
    return dict(status='candidate_evidence_only', inventory=seen, equipped=equipped,
                identity_verified=False, game_state_write_allowed=False,
                training_label_allowed=False)
