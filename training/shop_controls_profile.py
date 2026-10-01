"""Versioned UI patches: immutable parent, bounded pixel seeds, unchanged reader.

Only declared numeric rectangles and additional already-known appearances may
change. No OCR result, season roster, confidence threshold or expected number
participates in profile materialization.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def rect(value: object) -> bool:
    return (isinstance(value, dict) and set(value) == {'x', 'y', 'width', 'height'}
            and all(type(n) is int for n in value.values())
            and 0 <= value['x'] < 8192 and 0 <= value['y'] < 8192
            and 1 <= value['width'] <= 256 and 1 <= value['height'] <= 96)


def validate_patch(base: dict, raw: bytes, patch: dict) -> None:
    require(json.loads(raw) == base, 'parent document and pinned bytes differ')
    require(set(patch) == {'schema_version', 'id', 'parent_id', 'parent_git_blob',
                           'rectangles', 'additional_templates'}, 'unsupported UI patch key')
    require(type(patch['schema_version']) is int and patch['schema_version'] == 1,
            'unsupported UI patch schema')
    require(isinstance(patch['id'], str) and 0 < len(patch['id']) <= 100
            and patch['id'].strip() and patch['id'] != base['id'], 'new profile id required')
    require(patch['parent_id'] == base['id'] and patch['parent_git_blob'] == blob_sha(raw),
            'parent controls profile changed')
    specs = {s['id']: s for s in base['controls']}
    require(list(specs) == ['lock', 'buy_xp', 'refresh'], 'unexpected parent control order')
    changes = patch['rectangles']
    seeds = patch['additional_templates']
    require(isinstance(changes, list) and len(changes) <= 6
            and isinstance(seeds, list) and len(seeds) <= 4, 'UI patch budget exceeded')
    seen = set()
    for change in changes:
        require(isinstance(change, dict) and set(change) == {'control', 'field', 'rect'},
                'invalid rectangle operation')
        cid, field = change['control'], change['field']
        require(cid in specs and field in ('price_rect', 'free_count_rect')
                and specs[cid][field] is not None and rect(change['rect']),
                'only existing numeric regions may change')
        require((cid, field) not in seen, 'duplicate rectangle operation')
        seen.add((cid, field))
    seen = set()
    per_control = {cid: len(s['templates']) for cid, s in specs.items()}
    for seed in seeds:
        require(isinstance(seed, dict) and set(seed) == {'control', 'state', 'image', 'sha256'},
                'invalid visual seed; expected numbers are forbidden')
        cid, state, image = seed['control'], seed['state'], seed['image']
        require(cid in specs and state in {t['state'] for t in specs[cid]['templates']},
                'new appearance classes require a separate reviewed change')
        require(isinstance(image, str) and image and not Path(image).is_absolute()
                and '..' not in Path(image).parts, 'unsafe seed path')
        require(isinstance(seed['sha256'], str) and len(seed['sha256']) == 64
                and all(c in '0123456789abcdef' for c in seed['sha256']), 'invalid seed hash')
        require((cid, state, image) not in seen, 'duplicate visual seed')
        seen.add((cid, state, image))
        per_control[cid] += 1
        require(per_control[cid] <= 8, 'too many templates for control')


def decode_signature(path: Path, spec: dict) -> tuple[list[int], str]:
    """Convert to RGB before cropping, matching the native FFmpeg/PPM path.

    Output is bounded to one small raw ROI. Integer center sampling matches
    ControlsReader::sample; no image library or extra recognizer is involved.
    """
    r = spec['rect']
    require(rect(r), 'invalid visual seed ROI')
    gw, gh = spec['grid_width'], spec['grid_height']
    require(type(gw) is int and type(gh) is int and 4 <= gw <= 32 and 4 <= gh <= 32,
            'invalid signature dimensions')
    filt = f"format=rgb24,crop={r['width']}:{r['height']}:{r['x']}:{r['y']}:exact=1"
    cmd = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-i', str(path),
           '-map', '0:v:0', '-frames:v', '1', '-an', '-sn', '-vf', filt,
           '-c:v', 'rawvideo', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1']
    result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True,
                            check=True, timeout=20)
    pixels = result.stdout
    require(len(pixels) == r['width'] * r['height'] * 3, 'truncated/excessive seed raster')
    rgb = []
    for y in range(gh):
        sy = min((2 * y + 1) * r['height'] // (2 * gh), r['height'] - 1)
        for x in range(gw):
            sx = min((2 * x + 1) * r['width'] // (2 * gw), r['width'] - 1)
            at = (sy * r['width'] + sx) * 3
            rgb.extend(pixels[at:at + 3])
    return rgb, hashlib.sha256(pixels).hexdigest()


def materialize(base: dict, raw: bytes, patch: dict, root: Path, manifest: dict,
                decoder=decode_signature) -> tuple[dict, dict]:
    validate_patch(base, raw, patch)
    root = root.resolve(strict=True)
    known = {r['image']: r['sha256'] for r in manifest['frames']}
    out = copy.deepcopy(base)
    out['id'] = patch['id']
    specs = {s['id']: s for s in out['controls']}
    sources = {}
    for change in patch['rectangles']:
        specs[change['control']][change['field']] = copy.deepcopy(change['rect'])
    for seed in patch['additional_templates']:
        require(known.get(seed['image']) == seed['sha256'], 'visual seed not in frozen manifest')
        path = (root / seed['image']).resolve(strict=True)
        require(path.is_relative_to(root) and path.is_file() and path.stat().st_size <= 32 * 1024 * 1024,
                'unsafe/oversized seed file')
        require(hashlib.sha256(path.read_bytes()).hexdigest() == seed['sha256'], 'visual seed changed')
        spec = specs[seed['control']]
        rgb, raster_hash = decoder(path, spec)
        require(len(rgb) == spec['grid_width'] * spec['grid_height'] * 3
                and all(type(n) is int and 0 <= n <= 255 for n in rgb), 'invalid decoded signature')
        require(hashlib.sha256(path.read_bytes()).hexdigest() == seed['sha256'], 'seed changed during decoding')
        sources[str(path)] = seed['sha256']
        spec['templates'].append(dict(state=seed['state'], rgb=rgb, source=dict(
            image=seed['image'], image_sha256=seed['sha256'],
            decoded_roi_sha256=raster_hash, decoder='ffmpeg_rgb24_before_crop',
            role='visual_seed_not_ground_truth')))
    out['profile_patch'] = dict(parent_id=base['id'], parent_git_blob=blob_sha(raw),
                                 policy='bounded_ui_data_patch_v1')
    return out, sources


def compare_observations(before: dict, after: dict) -> dict:
    """Same-frame comparison; no majority vote, correction or probability claim."""
    from collections import Counter
    require(len(before['records']) == len(after['records']), 'different record count')
    for key in ('profile', 'layout_id', 'locale', 'ocr_language'):
        require(before['summary'][key] == after['summary'][key], 'reader/context changed')
    counts = {k: Counter() for k in ('refresh_appearance', 'buy_xp_price', 'refresh_price', 'refresh_free_count')}
    changes, cards, visuals = [], [], []
    for a, b in zip(before['records'], after['records']):
        at = a['read']['timestamp_ms']
        require(at == b['read']['timestamp_ms'], 'timestamps changed')
        if a['read'] != b['read']:
            cards.append(at)
        x, y = a['controls'], b['controls']
        require([c['id'] for c in x['controls']] == [c['id'] for c in y['controls']]
                == ['lock', 'buy_xp', 'refresh'], 'missing/duplicate controls')
        if x['controls'][:2] != y['controls'][:2]:
            visuals.append(at)
        expected_ids = ['buy_xp_price', 'refresh_price', 'refresh_free_count']
        require([n['id'] for n in x['numeric_fields']] == [n['id'] for n in y['numeric_fields']]
                == expected_ids, 'missing/duplicate numbers')
        pairs = [('refresh_appearance', x['controls'][2]['appearance'], y['controls'][2]['appearance'],
                  x['controls'][2], y['controls'][2])]
        pairs.extend((old['id'], old['value'], new['value'], old, new)
                     for old, new in zip(x['numeric_fields'], y['numeric_fields']))
        for key, old, new, old_trace, new_trace in pairs:
            kind = ('neither' if old is None and new is None else 'candidate_only' if old is None
                    else 'baseline_only' if new is None else 'both_equal' if old == new else 'both_disagree')
            counts[key][kind] += 1
            if kind in ('candidate_only', 'baseline_only', 'both_disagree'):
                changes.append(dict(timestamp_ms=at, field=key, comparison=kind,
                                    baseline=old, candidate=new, baseline_trace=old_trace,
                                    candidate_trace=new_trace))
    return dict(frames=len(before['records']), card_observations_unchanged=not cards,
                non_refresh_visuals_unchanged=not visuals, changed_card_frames=cards,
                changed_non_refresh_visual_frames=visuals,
                fields={k: dict(v) for k, v in counts.items()}, cases=changes,
                exact_accuracy=None, profile_promoted=False,
                note='same inputs and executable; UI data changed; exclusive readability is not accuracy')
