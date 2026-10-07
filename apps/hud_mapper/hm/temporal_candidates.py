"""Bounded cross-frame persistence for visual hypotheses, never identity labels."""
from __future__ import annotations

from collections import Counter, deque


def _position(value):
    if not isinstance(value, dict) or value.get('status') != 'candidate_only':
        return None
    zone, row, slot = (value.get(key) for key in ('zone', 'row', 'cell_or_slot'))
    if zone not in ('board', 'bench') or type(slot) is not int:
        return None
    if zone == 'board' and type(row) is not int:
        return None
    return (zone, row, slot)


class TemporalCandidates:
    """Track only the same visible slot/hex for a few recent HUB observations.

    Support is a count of repeated frames, not a calibrated probability or
    independent validation. A moved unit gets a different track and must build
    evidence again.
    """

    def __init__(self, *, max_age_ms=5000, history=3):
        self.max_age_ms = max_age_ms
        self.history = history
        self.epoch = None
        self.last_ms = None
        self.tracks = {}

    def update(self, snapshot: dict, epoch=None) -> dict:
        now = snapshot.get('timestamp_ms')
        if type(now) is not int:
            self.tracks.clear()
            self.last_ms = None
            return dict(status='no_timestamp', units=[], inventory=[], equipped=[])
        if (self.last_ms is not None and
                (self.epoch != epoch or now <= self.last_ms or now - self.last_ms > self.max_age_ms)):
            self.tracks.clear()
        self.epoch, self.last_ms = epoch, now

        locations = {row['marker_id']: _position(row.get('position_candidate'))
                     for row in snapshot.get('observed_markers', [])}
        current = []
        for row in (snapshot.get('neural_units') or {}).get('records', []):
            position = locations.get(row.get('marker_id'))
            if position:
                current.append(('units', ('unit', position), row.get('candidate_id'),
                                dict(position=list(position), marker_id=row['marker_id'],
                                     current_candidate_name=row.get('candidate_name'))))
        visual = snapshot.get('item_visual_native') or {}
        for row in visual.get('inventory', []):
            if type(row.get('slot')) is int:
                names = (row.get('candidates') or [{}])[0].get('names') or []
                current.append(('inventory', ('inventory', row['slot']), row.get('candidate_id'),
                                dict(slot=row['slot'],
                                     current_candidate_name=names[0] if len(names) == 1 else None)))
        for row in visual.get('equipped', []):
            position = _position(row.get('position_candidate'))
            if position and type(row.get('slot')) is int:
                names = (row.get('candidates') or [{}])[0].get('names') or []
                current.append(('equipped', ('equipped', position, row['slot']),
                                row.get('candidate_id'),
                                dict(position=list(position), slot=row['slot'],
                                     marker_id=row.get('marker_id'),
                                     current_candidate_name=names[0] if len(names) == 1 else None)))

        visible = {key for _, key, _, _ in current}
        for key in list(self.tracks):
            if key not in visible:
                del self.tracks[key]
        result = dict(status='candidate_persistence', units=[], inventory=[], equipped=[],
                      identity_verified=False, score_is_probability=False)
        for group, key, candidate, details in current:
            votes = self.tracks.setdefault(key, deque(maxlen=self.history))
            votes.append(candidate if isinstance(candidate, str) and candidate else None)
            counts = Counter(value for value in votes if value is not None)
            top = counts.most_common(2)
            persistent = (len(votes) >= 2 and bool(top) and candidate == top[0][0]
                          and top[0][1] >= 2
                          and (len(top) == 1 or top[0][1] > top[1][1]))
            result[group].append(dict(**details,
                candidate_id=top[0][0] if persistent else None,
                current_candidate_id=candidate,
                candidate_name=(details.get('current_candidate_name')
                                if persistent and top[0][0] == candidate else None),
                support_frames=top[0][1] if top else 0,
                observed_frames=len(votes),
                status='persistent_candidate' if persistent else 'observing',
                identity_verified=False))
        return result
