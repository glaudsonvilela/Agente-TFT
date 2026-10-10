"""Recognize one reviewed 1080p arena before showing its reserve guides."""
from __future__ import annotations

import math


def observe_reserves(image, profile):
    if tuple(image.size) != tuple(profile.get('resolution') or ()):
        return dict(status='wrong_resolution', profile=profile.get('id'), upper=[], lower=[])
    if len(profile.get('lower_reserve') or []) != 9 or len(profile.get('own_board_rows') or []) != 4:
        raise ValueError('Arena profile needs nine lower slots and four visible rows')
    has_opposite_side = bool(profile.get('enemy_board_visible'))
    if has_opposite_side and (len(profile.get('upper_reserve') or []) != 9 or
                              len(profile.get('enemy_board_rows') or []) != 4):
        raise ValueError('Visible opposite side needs nine upper slots and four rows')
    differences = []
    for anchor in profile['anchors']:
        x1, y1, x2, y2 = anchor['rect']
        patch = image.crop((x1, y1, x2, y2))
        from PIL import ImageStat
        mean = ImageStat.Stat(patch).mean[:3]
        differences.append(round(math.dist(mean, anchor['mean_rgb']), 1))
    matched = all(value <= profile['max_rgb_distance'] for value in differences)
    return dict(status='arena_candidate_match' if matched else 'arena_unmatched',
                profile=profile['id'], rgb_distances=differences,
                upper=profile.get('upper_reserve', []) if matched and has_opposite_side else [],
                lower=profile['lower_reserve'] if matched else [],
                enemy_rows=profile.get('enemy_board_rows', []) if matched and has_opposite_side else [],
                own_rows=profile['own_board_rows'] if matched else [],
                enemy_board_visible=has_opposite_side if matched else False,
                owner_verified=False, training_label=False)


def choose_calibration(proposals, registered, active_profile, *, registration_available):
    """Do not let one skin's colors rename a different arena during zoom."""
    previous = next((row for row in proposals if row['profile'] == active_profile), None)
    if previous and previous['status'] == 'arena_candidate_match':
        return previous
    if registered and registered['status'] == 'arena_candidate_match':
        return registered
    # On a runtime without OpenCV, retain the basic reviewed color profiles.
    if not registration_available:
        fallback = next((row for row in proposals if row['status'] == 'arena_candidate_match'), None)
        if fallback:
            return fallback
    return dict(status='arena_unmatched', profile=None, upper=[], lower=[],
                own_rows=[], enemy_rows=[], enemy_board_visible=False,
                rejected_static_profiles=[row['profile'] for row in proposals
                                          if row['status'] == 'arena_candidate_match'],
                owner_verified=False, training_label=False)
