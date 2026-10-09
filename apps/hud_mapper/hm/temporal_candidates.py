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
    """Track a visible slot/hex, or a marker when its position is unknown.

    Support is a count of repeated frames, not a calibrated probability or
    independent validation. Marker IDs can be reassigned between frames, so a
    moved or reordered marker must build evidence again.
    """

    def __init__(self, *, max_age_ms=5000, history=3):
        self.max_age_ms = max_age_ms
        self.history = history
        self.epoch = None
        self.last_ms = None
        self.tracks = {}
        self.async_unit_tracks = {}
        self.async_unit_epoch = None
        self.async_unit_last_ms = None

    def ingest_async_units(self, completed: dict, *, epoch, now_ms: int) -> bool:
        """Count each completed source frame once, using its own marker positions."""
        source_ms = completed.get('source_ms')
        frame_id = completed.get('frame_id')
        if (completed.get('epoch') != epoch or type(now_ms) is not int or
                type(source_ms) is not int or type(frame_id) is not int or
                not 0 <= now_ms - source_ms <= min(self.max_age_ms, 3500)):
            return False
        if (self.last_ms is not None and
                (self.epoch != epoch or now_ms <= self.last_ms or
                 now_ms - self.last_ms > self.max_age_ms)):
            self.tracks.clear()
            self.async_unit_tracks.clear()
            self.async_unit_last_ms = None
            self.epoch = epoch
            self.last_ms = None
        if self.async_unit_epoch != epoch:
            self.async_unit_tracks.clear()
            self.async_unit_last_ms = None
            self.async_unit_epoch = epoch
        if self.async_unit_last_ms is not None and source_ms <= self.async_unit_last_ms:
            return False
        self.async_unit_last_ms = source_ms
        positions = {row.get('marker_id'): _position(row.get('position_candidate'))
                     for row in completed.get('positions') or [] if isinstance(row, dict)}
        visible = {position for position in positions.values() if position}
        for key in list(self.async_unit_tracks):
            if key not in visible:
                del self.async_unit_tracks[key]
        records = (completed.get('result') or {}).get('records') or []
        observed = {}
        for row in records:
            if not isinstance(row, dict):
                continue
            marker_id = row.get('marker_id')
            position = positions.get(marker_id)
            if position and position not in observed:
                observed[position] = row
        for position in visible:
            row = observed.get(position) or {}
            candidate = (row.get('candidate_id') if row.get('status') == 'identity_candidate'
                         and row.get('identity_verified') is False else None)
            if not isinstance(candidate, str) or not candidate:
                candidate = None
            track = self.async_unit_tracks.setdefault(position, dict(
                votes=deque(maxlen=self.history)))
            track['votes'].append(candidate)
            track.update(marker_id=row.get('marker_id'), candidate_id=candidate,
                         candidate_name=row.get('candidate_name') if candidate else None,
                         source_frame_id=frame_id, source_ms=source_ms)
        return True

    def update(self, snapshot: dict, epoch=None) -> dict:
        now = snapshot.get('timestamp_ms')
        if type(now) is not int:
            self.tracks.clear()
            self.async_unit_tracks.clear()
            self.async_unit_last_ms = None
            self.last_ms = None
            return dict(status='no_timestamp', units=[], inventory=[], equipped=[])
        if (self.last_ms is not None and
                (self.epoch != epoch or now <= self.last_ms or now - self.last_ms > self.max_age_ms)):
            self.tracks.clear()
            self.async_unit_tracks.clear()
            self.async_unit_last_ms = None
            self.async_unit_epoch = epoch
        self.epoch, self.last_ms = epoch, now

        locations = {row['marker_id']: _position(row.get('position_candidate'))
                     for row in snapshot.get('observed_markers', [])}
        visible_positions = {position for position in locations.values() if position}
        for position in list(self.async_unit_tracks):
            if position not in visible_positions:
                del self.async_unit_tracks[position]
        current = []
        for row in (snapshot.get('neural_units') or {}).get('records', []):
            position = locations.get(row.get('marker_id'))
            if position:
                current.append(('units', ('unit', position), row.get('candidate_id'),
                                dict(position=list(position), marker_id=row['marker_id'],
                                     current_candidate_name=row.get('candidate_name'))))
        visual = snapshot.get('item_evidence') or snapshot.get('item_visual_native') or {}
        for row in visual.get('inventory', []):
            if type(row.get('slot')) is int:
                names = ([row['candidate_name']] if row.get('candidate_name') else
                         (row.get('candidates') or [{}])[0].get('names') or [])
                current.append(('inventory', ('inventory', row['slot']), row.get('candidate_id'),
                                dict(slot=row['slot'],
                                     current_candidate_name=names[0] if len(names) == 1 else None)))
        for row in visual.get('equipped', []):
            position = _position(row.get('position_candidate'))
            marker_id = row.get('marker_id')
            if type(row.get('slot')) is int and (position or type(marker_id) is int):
                names = ([row['candidate_name']] if row.get('candidate_name') else
                         (row.get('candidates') or [{}])[0].get('names') or [])
                key = (('equipped', position, row['slot']) if position else
                       ('equipped_marker', marker_id, row['slot']))
                current.append(('equipped', key,
                                row.get('candidate_id'),
                                dict(position=list(position) if position else None,
                                     slot=row['slot'], marker_id=marker_id,
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
        if (snapshot.get('neural_units') or {}).get('mode') == 'async_diagnostic_candidates':
            for position, track in self.async_unit_tracks.items():
                age_ms = now - track['source_ms']
                if not 0 <= age_ms <= min(self.max_age_ms, 3500):
                    continue
                candidate = track['candidate_id']
                votes = track['votes']
                counts = Counter(value for value in votes if value is not None)
                top = counts.most_common(2)
                persistent = (len(votes) >= 2 and bool(top) and candidate == top[0][0]
                              and top[0][1] >= 2
                              and (len(top) == 1 or top[0][1] > top[1][1]))
                result['units'].append(dict(position=list(position),
                    marker_id=track['marker_id'],
                    candidate_id=candidate if persistent else None,
                    current_candidate_id=candidate,
                    candidate_name=track['candidate_name'] if persistent else None,
                    support_frames=top[0][1] if top else 0,
                    observed_frames=len(votes),
                    source_frame_id=track['source_frame_id'],
                    source_ms=track['source_ms'], age_ms=age_ms,
                    status='persistent_candidate' if persistent else 'observing',
                    identity_verified=False))
        return result
