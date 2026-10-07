"""Conservative inventory-to-unit transitions from consecutive screen frames."""
from __future__ import annotations

from collections import Counter


def _position(row):
    point = row.get('position_candidate') or {}
    if point.get('status') != 'candidate_only':
        return None
    return (point.get('zone'), point.get('row'), point.get('cell_or_slot'))


class ItemMovementTracker:
    def __init__(self, recipes: dict[str, tuple[str, str]] | None = None):
        self.previous = None
        self.recipes = recipes or {}

    def update(self, snapshot: dict, visual: dict, epoch: int | None = None) -> dict:
        now = snapshot.get('timestamp_ms')
        ready = (visual.get('active') and snapshot['inventory']['inventory']['panel_status'] == 'located'
                 and snapshot.get('position_status') != 'projection_unavailable'
                 and bool(snapshot.get('observed_markers')))
        if not ready or type(now) is not int:
            self.previous = None
            return dict(status='insufficient_frame_evidence', events=[])
        inventory = Counter(row['candidates'][0]['art_sha256'] for row in visual['inventory']
                            if row.get('candidates') and row['status'] == 'candidate_only')
        inventory_ids = Counter(row['candidate_id'] for row in visual['inventory']
                                if row.get('candidate_id') and row['status'] == 'candidate_only')
        equipped = {}
        for row in visual['equipped']:
            position = _position(row)
            if position and row.get('candidates') and row['status'] == 'candidate_only':
                equipped[(position, row['slot'])] = row
        positions = {_position(row) for row in snapshot['observed_markers']}
        positions.discard(None)
        current = dict(epoch=epoch, timestamp_ms=now, inventory=inventory,
                       inventory_ids=inventory_ids,
                       equipped=equipped, positions=positions)
        before = self.previous
        self.previous = current
        if (before is None or before['epoch'] != epoch or not 0 < now - before['timestamp_ms'] <= 5000
                or not before['positions'] or before['positions'] != positions):
            return dict(status='observing', events=[])
        removed = before['inventory'] - inventory
        removed_ids = before['inventory_ids'] - inventory_ids
        added = [(key, row) for key, row in equipped.items()
                 if key not in before['equipped'] or
                 before['equipped'][key]['candidates'][0]['art_sha256'] != row['candidates'][0]['art_sha256']]
        events = []
        for art, count in removed.items():
            matches = [row for _, row in added if row['candidates'][0]['art_sha256'] == art]
            if count == 1 and len(matches) == 1:
                row = matches[0]
                events.append(dict(kind='equip_hypothesis', art_sha256=art,
                    item_candidate_id=row['candidate_id'], position_candidate=row['position_candidate'],
                    equipped_slot=row['slot'], source_interval_ms=now - before['timestamp_ms'],
                    identity_verified=False, unit_verified=False, training_label=False))
        for key, row in added:
            composition = self.recipes.get(row.get('candidate_id'))
            if not composition:
                continue
            needed = Counter(composition)
            prior = before['equipped'].get(key)
            if prior and prior.get('candidate_id') in needed:
                needed.subtract([prior['candidate_id']])
            if all(removed_ids[item_id] >= count for item_id, count in needed.items() if count > 0):
                events.append(dict(kind='combine_hypothesis',
                    item_candidate_id=row['candidate_id'], components=list(composition),
                    position_candidate=row['position_candidate'], equipped_slot=row['slot'],
                    source_interval_ms=now - before['timestamp_ms'],
                    identity_verified=False, unit_verified=False, training_label=False))
        return dict(status='candidate_events' if events else 'observing', events=events)
