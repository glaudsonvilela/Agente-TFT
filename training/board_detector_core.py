"""B3 comparison of different visual signals; no labels, training or winner selection."""
from collections import Counter
import math

MODEL_ID = 'IDEA-Research/grounding-dino-tiny'
MODEL_REVISION = 'c254d1f282bf348ab7f5a27d5cf90531eeba69be'
WEIGHTS_SHA256 = '1a2412ef99bd74bcd3c2a246fa1e48581f8889a1300c9051974741314fc042f3'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def policy_contract(p):
    keys = {'schema_version', 'id', 'model_id', 'model_revision', 'weights_sha256',
            'prompt', 'box_threshold', 'text_threshold', 'nms_iou', 'max_detections',
            'max_raw_detections', 'shortest_edge', 'longest_edge', 'cpu_threads',
            'device', 'association_note'}
    require(set(p) == keys and type(p['schema_version']) is int and p['schema_version'] == 1,
            'invalid detector policy fields')
    require(p['id'] == 'board-open-vocabulary-v1' and p['device'] == 'cpu', 'policy/device mismatch')
    require((p['model_id'], p['model_revision'], p['weights_sha256']) ==
            (MODEL_ID, MODEL_REVISION, WEIGHTS_SHA256), 'model must be pinned to audited weights')
    require(p['prompt'] == 'a video game character. a creature. a game piece.',
            'this experiment has a frozen prompt, not a prompt search')
    for key, expected in [('box_threshold', .30), ('text_threshold', .25), ('nms_iou', .50)]:
        require(type(p[key]) in (int, float) and math.isfinite(p[key]) and p[key] == expected,
                'changed detector thresholds require another experiment')
    for key, expected in [('max_detections', 128), ('max_raw_detections', 900),
                          ('shortest_edge', 800), ('longest_edge', 1333), ('cpu_threads', 4)]:
        require(type(p[key]) is int and p[key] == expected, 'invalid detector budget')
    return p


def rect_contract(r):
    require(isinstance(r, dict) and set(r) == {'x', 'y', 'width', 'height'}, 'invalid rectangle')
    require(all(type(v) in (int, float) and math.isfinite(v) for v in r.values()), 'nonfinite rectangle')
    require(r['x'] >= 0 and r['y'] >= 0 and r['width'] > 0 and r['height'] > 0, 'invalid rectangle size')


def overlap(a, b):
    return (a['x'] < b['x'] + b['width'] and b['x'] < a['x'] + a['width']
            and a['y'] < b['y'] + b['height'] and b['y'] < a['y'] + a['height'])


def iou(a, b):
    w = max(0, min(a['x']+a['width'], b['x']+b['width']) - max(a['x'], b['x']))
    h = max(0, min(a['y']+a['height'], b['y']+b['height']) - max(a['y'], b['y']))
    intersection = w*h
    return intersection / (a['width']*a['height'] + b['width']*b['height'] - intersection)


def detections(raw, roi, policy):
    """Accept model boxes in crop pixels; deterministic class-agnostic NMS, no fabricated detections."""
    require(len(raw) <= policy['max_raw_detections'], 'raw model output budget exceeded')
    rect_contract(roi)
    candidates = []
    rejected = 0
    for source_index, item in enumerate(raw):
        score, box, label = item['score'], item['box'], item['label']
        require(type(score) in (int, float) and math.isfinite(score) and 0 <= score <= 1, 'bad model score')
        require(isinstance(label, str) and len(label) <= 512, 'bad model phrase')
        require(isinstance(box, list) and len(box) == 4 and all(
            type(v) in (int, float) and math.isfinite(v) for v in box), 'bad model box')
        x0, y0, x1, y1 = box
        require(x1 > x0 and y1 > y0, 'inverted model box')
        if score < policy['box_threshold']:
            rejected += 1
            continue
        # Record clipping explicitly. A clipped box is never a floor/foot anchor.
        clipped = [max(0., x0), max(0., y0), min(float(roi['width']), x1), min(float(roi['height']), y1)]
        a, b, c, d = clipped
        if c <= a or d <= b:
            rejected += 1
            continue
        candidates.append(dict(source_index=source_index, score=score, phrase=label,
            rect=dict(x=a+roi['x'], y=b+roi['y'], width=c-a, height=d-b),
            raw_box=box, clipped=clipped != box, unit_id=None, ground_point=None, board_cell=None))
    candidates.sort(key=lambda x: (-x['score'], x['source_index']))
    kept = []
    suppressed = 0
    for candidate in candidates:
        if any(iou(candidate['rect'], x['rect']) > policy['nms_iou'] for x in kept):
            suppressed += 1
            continue
        require(len(kept) < policy['max_detections'], 'retained model output budget exceeded')
        candidate['id'] = len(kept)
        kept.append(candidate)
    return dict(proposals=kept, raw_count=len(raw), rejected=rejected, nms_suppressed=suppressed)


def compare_frame(b1, model):
    """A bar and a body box are NOT the same object type. Only overlap is measured."""
    links = []
    for bar in b1['markers']:
        for d in model['proposals']:
            if overlap(bar['rect'], d['rect']):
                links.append(dict(marker_id=bar['id'], proposal_id=d['id']))
    bench = []
    for slot in b1['bench']:
        ids = [d['id'] for d in model['proposals'] if overlap(slot['rect'], d['rect'])]
        has_bar = bool(slot['marker_candidates'])
        state = ('both_signals' if has_bar and ids else 'b1_bar_only' if has_bar else
                 'neural_box_only' if ids else 'neither_signal')
        bench.append(dict(slot=slot['slot'], b1_evidence=slot['evidence'],
            neural_overlap_ids=ids, comparison=state, occupancy=None, unit_id=None,
            reference_empty_with_neural_overlap=slot['evidence']=='empty_reference_match' and bool(ids)))
    return dict(bench=bench, bar_box_overlaps=links,
        unmatched_b1_markers=[b['id'] for b in b1['markers'] if not any(x['marker_id']==b['id'] for x in links)],
        unmatched_neural_boxes=[d['id'] for d in model['proposals'] if not any(x['proposal_id']==d['id'] for x in links)],
        warning='Spatial co-occurrence only. Neither signal is a label, unit count, identity, ownership or ground cell.')


def percentile(values, q):
    if not values:
        return None
    v = sorted(values)
    x = (len(v)-1)*q
    a, b = int(x), min(int(x)+1, len(v)-1)
    return v[a]+(v[b]-v[a])*(x-a)


def summarize(records, historical):
    require(bool(records), 'no frames processed')
    crosses, b1_evidence = Counter(), Counter()
    for r in records:
        crosses.update(x['comparison'] for x in r['comparison']['bench'])
        b1_evidence.update(x['b1_evidence'] for x in r['comparison']['bench'])
    result = dict(schema_version=1, policy='b3_b1_vs_open_vocabulary_v1', frames=len(records),
        b1_historical=historical, b1_observations_unchanged=True,
        b1_markers=sum(len(r['b1']['markers']) for r in records),
        neural_proposals=sum(len(r['neural']['proposals']) for r in records),
        frames_with_neural_proposals=sum(bool(r['neural']['proposals']) for r in records),
        bench_comparison=dict(crosses), b1_bench_evidence=dict(b1_evidence),
        b1_empty_reference_with_neural_overlap=sum(x['reference_empty_with_neural_overlap']
            for r in records for x in r['comparison']['bench']),
        projections_unresolved_with_neural_proposals=sum(r['b1']['projection_status']=='unresolved'
            and bool(r['neural']['proposals']) for r in records),
        model_forward_passes=len(records), model_trained=False, pretrained_weights_loaded=True,
        exact_accuracy=None, labels_used=False, human_labels_required=False,
        ocr_process_calls=0, text_readers_modified=False, profile_promoted=False,
        game_state_updated=False, ground_assignment_established=False, occupancy_validated=False,
        false_positive_rate=None, false_negative_rate=None, temporal_confirmation=False,
        execution_complete=True, errors=0, metric_kind='different_visual_signals_same_source_images',
        recommendation='keep_shadow_no_automatic_winner',
        note='More boxes do not prove improvement. No absence-to-empty inference; same-match development test; not a trained TFT detector.')
    for name in ['model_ms', 'decode_ms', 'candidate_total_ms']:
        result[name+'_p50'] = percentile([r[name] for r in records], .50)
        result[name+'_p95'] = percentile([r[name] for r in records], .95)
    return result
