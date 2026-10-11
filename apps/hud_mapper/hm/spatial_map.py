"""Stable names for the TFT cells and benches in one observed match.

Coordinates are visual guides from the active arena profile. They never turn
a detected box into a champion identity or a confirmed occupied hex.
"""
from __future__ import annotations


def build_spatial_map(board_cells, bench_slots, opponents, *, source_ms, projection_status,
                      reserve_calibration=None, neural_units=None):
    def visible(point):
        return point if point and 0 <= point[0] < 1920 and 0 <= point[1] < 1080 else None
    own = []
    for cell in board_cells or []:
        row, col = cell.get('row'), cell.get('col')
        if type(row) is not int or type(col) is not int or not (0 <= row < 4 and 0 <= col < 7):
            continue
        own.append(dict(id=f'{chr(65 + row)}{col + 1}', side='own',
                        center=cell.get('screen_center'), occupancy='unknown',
                        champion_id=None, marker_candidates=cell.get('marker_candidates') or []))
    bench = []
    for slot in bench_slots or []:
        index = slot.get('slot')
        if type(index) is not int or not 0 <= index < 9:
            continue
        bench.append(dict(id=f'R{index + 1}', side='own', center=slot.get('screen_center'),
                          occupancy='unknown', champion_id=None,
                          marker_candidates=slot.get('marker_candidates') or []))
    # The opposite half and bench are named now, but their pixel anchors need
    # verified screen framing. Their appearance/skin is not part of geometry.
    enemy = [dict(id=f'{chr(65 + row)}{col + 1}', side='enemy', center=None,
                  occupancy='unknown', champion_id=None)
             for row in range(4) for col in range(7)]
    enemy_bench = [dict(id=f'R{slot + 1}', side='enemy', center=None,
                        occupancy='unknown', champion_id=None)
                   for slot in range(9)]
    geometry_status = (reserve_calibration or {}).get('status')
    calibrated = geometry_status in ('arena_candidate_match', 'standard_screen_geometry')
    enemy_calibrated = calibrated and bool(reserve_calibration.get('enemy_board_visible'))
    if calibrated:
        for rows, centers in ((reserve_calibration['own_rows'], own),):
            for row, (left, right, y) in enumerate(rows):
                for col in range(7):
                    centers[row * 7 + col]['center'] = visible([left + (right-left)*col/6, y])
        for slot, center in enumerate(reserve_calibration['lower']):
            bench[slot]['center'] = visible(center)
    if enemy_calibrated:
        for row, (left, right, y) in enumerate(reserve_calibration['enemy_rows']):
            for col in range(7):
                enemy[row * 7 + col]['center'] = visible([left + (right-left)*col/6, y])
        for slot, center in enumerate(reserve_calibration['upper']):
            enemy_bench[slot]['center'] = visible(center)
        # An upper-bench detection is only a candidate for a numbered slot.
        # Keep identity and occupancy unverified, and never borrow boxes from
        # combat units below the bench to fill an empty position.
        if (neural_units or {}).get('active') is True:
            possible = []
            for index, record in enumerate(neural_units.get('bench_records') or []):
                box = record.get('box') if isinstance(record, dict) else None
                if not (isinstance(box, (list, tuple)) and len(box) == 4 and
                        all(type(value) in (int, float) for value in box)):
                    continue
                middle_x, bottom_y = (box[0] + box[2]) / 2, box[3]
                for slot, address in enumerate(enemy_bench):
                    center = address['center']
                    if center is None:
                        continue
                    dx, dy = abs(middle_x - center[0]), abs(bottom_y - center[1])
                    if dx <= 50 and dy <= 55 and box[1] < center[1]:
                        possible.append((dx + dy, index, slot))
            used_records, used_slots = set(), set()
            for _, index, slot in sorted(possible):
                if index in used_records or slot in used_slots:
                    continue
                record = neural_units['bench_records'][index]
                enemy_bench[slot]['visual_candidate'] = dict(
                    box=record['box'], candidate_id=record.get('candidate_id'),
                    candidate_name=record.get('candidate_name'),
                    confidence_uncalibrated=record.get('confidence_uncalibrated'),
                    status='unverified_detection', identity_verified=False)
                used_records.add(index)
                used_slots.add(slot)
    opponent = (opponents or {}).get('current_opponent')
    # Every visible roster entry has its own independent address space, even
    # before we can tell whose arena or bench is on screen.
    roster_spaces = [dict(owner=row['name'],
                          cells=[f'{chr(65 + r)}{c + 1}' for r in range(4) for c in range(7)],
                          bench=[f'R{i + 1}' for i in range(9)],
                          board_assigned=False, units=[])
                     for row in (opponents or {}).get('players', [])
                     if isinstance(row, dict) and isinstance(row.get('name'), str) and row['name']]
    return dict(schema_version=1, source_ms=source_ms,
                own_owner='self_unverified',
                enemy_owner=opponent if isinstance(opponent, str) and opponent else None,
                enemy_owner_status=(opponents or {}).get('current_opponent_status', 'unresolved'),
                own_geometry_status=('standard_screen_geometry' if geometry_status == 'standard_screen_geometry' else
                                     'arena_candidate' if calibrated else
                                     'reference_candidate' if projection_status == 'reference_arena_match'
                                     else 'unmatched_arena_guide'),
                enemy_geometry_status=('standard_screen_geometry' if geometry_status == 'standard_screen_geometry' else
                                       'arena_candidate') if enemy_calibrated else 'not_visible_or_calibrated',
                enemy_bench_geometry_status=(('standard_screen_geometry' if geometry_status == 'standard_screen_geometry' else
                                              'arena_candidate') if enemy_calibrated else 'not_visible_or_calibrated'),
                own_bench_geometry_status=('standard_screen_geometry' if geometry_status == 'standard_screen_geometry' else
                                            'arena_candidate' if calibrated else
                                            'reference_candidate' if projection_status == 'reference_arena_match'
                                            else 'not_calibrated'),
                reserve_calibration=reserve_calibration,
                own_cells=own, enemy_cells=enemy,
                own_bench=bench, enemy_bench=enemy_bench,
                roster_spaces=roster_spaces,
                occupancy_verified=False, champion_identity_verified=False)
