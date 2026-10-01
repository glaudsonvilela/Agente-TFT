"""B1 evidence contracts. Proposals are not identities, occupancy or accuracy."""
from collections import Counter
import math
import struct

BENCH_STATES = {'projection_unavailable', 'ambiguous', 'bar_candidate', 'empty_reference_match', 'unknown'}
NO_EFFECTS = ('labels_used', 'model_trained', 'game_state_updated', 'profile_promoted',
              'temporal_confirmation', 'unit_identity_established', 'occupancy_established',
              'ground_assignment_established')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def rect_ok(r, width, height):
    return (isinstance(r, dict) and set(r) == {'x', 'y', 'width', 'height'}
            and all(type(v) is int for v in r.values()) and r['x'] >= 0 and r['y'] >= 0
            and r['width'] > 0 and r['height'] > 0
            and r['x'] + r['width'] <= width and r['y'] + r['height'] <= height)


def profile_contract(p):
    require(p.get('schema_version') == 1 and p.get('board_topology_id') == 'board-standard-4x7-v1'
            and p.get('bench_topology_id') == 'bench-nine-v1', 'profile identity mismatch')
    require(isinstance(p.get('id'), str) and 0 < len(p['id']) <= 100, 'invalid profile id')
    for key in ('reference_width', 'reference_height'):
        require(type(p.get(key)) is int and 1 <= p[key] <= 8192, 'invalid reference size')
    require(len(p.get('board_rows', [])) == 4 and len(p.get('bench_centers', [])) == 9,
            'invalid projection counts')
    for digest in (p.get('reference_sha256'), p.get('geometry_source', {}).get('sha256')):
        require(isinstance(digest, str) and len(digest) == 64
                and all(c in '0123456789abcdef' for c in digest), 'invalid seed hash')
    require(p.get('geometry_source', {}).get('role') == 'visible_grid_development_seed_not_independent_validation',
            'seed role mismatch')


def validate(report, manifest, p):
    """Recompute aggregates and reject invented semantic outputs before sealing."""
    s = report['summary']
    require(s.get('schema_version') == 1 and s.get('policy') == 'board_bench_spatial_v1'
            and s.get('profile') == p['id'], 'native identity mismatch')
    require(s.get('execution_complete') is True and s.get('errors') == 0
            and s.get('ocr_process_calls') == 0 and s.get('exact_accuracy') is None,
            'incomplete result or unsupported OCR/accuracy claim')
    require(all(s.get(k) is False for k in NO_EFFECTS), 'semantic or mutation claim not supported by B1')
    rows = report['records']
    require(len(rows) == len(manifest['frames']) == s['frames'], 'frame count mismatch')
    require(s.get('board_cells_per_frame') == 28 and s.get('bench_slots_per_frame') == 9, 'topology count mismatch')
    projections, bench, colors = Counter(), Counter(), Counter()
    f32 = lambda x: struct.unpack('!f', struct.pack('!f', x))[0]
    sig = p['signature']

    def score_ok(a):
        return (isinstance(a, dict) and set(a) == {'rgb_mae', 'changed_fraction'}
                and all(type(v) in (int, float) and math.isfinite(v) for v in a.values())
                and 0 <= a['rgb_mae'] <= 255 and 0 <= a['changed_fraction'] <= 1)

    def overlaps(a, b):
        return (a['x'] < b['x']+b['width'] and b['x'] < a['x']+a['width']
                and a['y'] < b['y']+b['height'] and b['y'] < a['y']+a['height'])

    w, h = p['reference_width'], p['reference_height']
    for f, record in zip(manifest['frames'], rows):
        r = record['read']
        require(r.get('timestamp_ms') == f['timestamp_ms'] and r.get('profile') == p['id'], 'frame/profile mismatch')
        require(r.get('phase') is None and r.get('perspective') is None and r.get('error') is None,
                'B1 does not infer phase, ownership or hide errors')
        require(r['projection_status'] in ('reference_arena_match', 'unresolved'), 'unknown projection status')
        require(len(r['arena_scores']) == 2 and all(score_ok(a) for a in r['arena_scores']), 'invalid arena scores')
        matched = all(a['rgb_mae'] <= f32(sig['arena_max_mae'])
                      and a['changed_fraction'] <= f32(sig['arena_max_changed_fraction']) for a in r['arena_scores'])
        require((r['projection_status'] == 'reference_arena_match') == matched, 'arena decision disagrees with scores')
        for key in ('scan_ms', 'decode_and_scan_ms'):
            require(type(record[key]) in (int, float) and math.isfinite(record[key]) and record[key] >= 0, 'invalid duration')
        markers = r['markers']
        require(len(markers) <= p['bars']['max_candidates'] and [m['id'] for m in markers] == list(range(len(markers))),
                'invalid marker count/identity')
        for m in markers:
            require(rect_ok(m['rect'], w, h) and m['color'] in ('green', 'red'), 'invalid marker rectangle/color')
            require(all(m.get(k) is None for k in ('unit_id', 'ground_point', 'board_cell')), 'bar center cannot become ground/unit')
            require(type(m['border_fraction']) in (int, float) and math.isfinite(m['border_fraction'])
                    and 0.75 <= m['border_fraction'] <= 1, 'invalid raw marker score')
            colors[m['color']] += 1
        require([b['slot'] for b in r['bench']] == list(range(9)), 'missing/duplicate bench slot')
        for i, b in enumerate(r['bench']):
            expected = dict(x=p['bench_centers'][i] - p['bench_crop_width']//2, y=p['bench_crop_y'],
                            width=p['bench_crop_width'], height=p['bench_crop_height'])
            require(b['rect'] == expected and b['ground_pixel'] == [p['bench_centers'][i], p['bench_y']], 'bench geometry mismatch')
            require(b.get('unit_id') is None and b.get('occupancy') is None, 'unsupported bench occupancy/identity claim')
            require(b['evidence'] in BENCH_STATES and len(set(b['marker_candidates'])) == len(b['marker_candidates'])
                    and all(type(i) is int and 0 <= i < len(markers) for i in b['marker_candidates']), 'invalid bench evidence')
            if r['projection_status'] == 'unresolved':
                require(b['evidence'] == 'projection_unavailable' and b['empty_signature'] is None
                        and not b['marker_candidates'], 'unresolved arena reuses bench evidence')
            else:
                score = b['empty_signature']
                require(score_ok(score), 'invalid appearance score')
                hints = [m['id'] for m in markers if overlaps(m['rect'], expected)]
                require(b['marker_candidates'] == hints, 'marker hints do not match geometry')
                empty = score['rgb_mae'] <= f32(sig['empty_max_mae']) and score['changed_fraction'] <= f32(sig['empty_max_changed_fraction'])
                expected_kind = ('ambiguous' if len(hints) > 1 or (empty and hints) else
                                 'bar_candidate' if hints else 'empty_reference_match' if empty else 'unknown')
                require(b['evidence'] == expected_kind, 'bench evidence differs from scores/markers')
            bench[b['evidence']] += 1
        require([(c['row'], c['col']) for c in r['board']] == [(i, j) for i in range(4) for j in range(7)],
                'missing/duplicate board cell')
        for c in r['board']:
            left, right, y = p['board_rows'][c['row']]
            expected = (left + (right-left)*c['col']/6, y)
            require(c.get('occupancy') is None and len(c['screen']) == 2
                    and all(type(v) in (int, float) and math.isfinite(v) and abs(v-e) <= 0.002
                            for v, e in zip(c['screen'], expected)), 'unverified board occupancy or changed projection')
        projections[r['projection_status']] += 1
    require(dict(projections) == s['projection_statuses'] and dict(bench) == s['bench_evidence']
            and dict(colors) == s['marker_colors'], 'aggregates do not match records')
    return s
