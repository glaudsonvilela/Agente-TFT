"""Partial replay annotations, independent of patch data and model predictions.

Missing means unreviewed, never an empty slot. Assistant visual review can feed
laboratory training; it is explicitly not independent human ground truth.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

SCENES = {'desktop', 'lobby', 'loading', 'board', 'shared_draft', 'augment', 'other'}
STATES = {'known', 'unknown', 'empty', 'occluded'}
REVIEWS = {'assistant_visual_review', 'human_visual_review'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def sha(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def identity(value, bound):
    require(isinstance(value, dict), 'identity must be an object')
    require(value.get('state') in STATES, 'identity state missing')
    if value['state'] == 'known':
        require(any(isinstance(value.get(k), str) and value[k].strip()
                    for k in ('id', 'visible_name')), 'known identity needs ID or visible name')
    else:
        require(not value.get('id') and not value.get('visible_name'), 'unknown/empty cannot assert identity')
    if value.get('id'):
        require(bound, 'catalog IDs require an explicit patch binding')


def validate(document, root: Path | None = None):
    """Raise on inconsistent annotations, changed images or unsupported certainty."""
    require(isinstance(document, dict) and document.get('schema_version') == 2
            and document.get('kind') == 'board_review', 'unsupported review document')
    frames = document.get('frames')
    require(isinstance(frames, list) and bool(frames), 'frames required')
    seen, pixels, counts = set(), set(), Counter()
    for f in frames:
        require(isinstance(f, dict), 'frame must be an object')
        require(sha(f.get('sha256')) and sha(f.get('pixel_sha256')), 'source hashes required')
        require(f['sha256'] not in seen and f['pixel_sha256'] not in pixels, 'duplicate frame/pixels')
        seen.add(f['sha256']); pixels.add(f['pixel_sha256'])
        require(isinstance(f.get('session_id'), str) and bool(f['session_id']), 'session required')
        require(isinstance(f.get('source_ms'), (int, float)) and not isinstance(f['source_ms'], bool)
                and math.isfinite(f['source_ms']) and f['source_ms'] >= 0, 'invalid source time')
        require(f.get('review', {}).get('method') in REVIEWS, 'explicit visual review required')
        require(f['review'].get('model_predictions_used_as_labels') is False, 'predictions are not labels')
        require(f.get('scene') in SCENES, 'invalid scene')
        counts[f['scene']] += 1
        size = f.get('image_size')
        require(isinstance(size, list) and len(size) == 2
                and all(integer(x) and x > 0 for x in size), 'invalid image dimensions')
        image = f.get('image')
        require(isinstance(image, str) and bool(image) and not Path(image).is_absolute()
                and '..' not in Path(image).parts, 'unsafe image path')
        if root is not None:
            path = (root / image).resolve(strict=True)
            require(path.is_relative_to(root.resolve()), 'image outside dataset')
            require(hashlib.sha256(path.read_bytes()).hexdigest() == f['sha256'], 'image hash mismatch')
            from PIL import Image
            with Image.open(path) as im:
                rgb = im.convert('RGB')
                require(list(rgb.size) == size, 'image dimensions changed')
                require(hashlib.sha256(rgb.tobytes()).hexdigest() == f['pixel_sha256'], 'pixel hash mismatch')
        binding = f.get('patch_binding')
        if binding is not None:
            require(isinstance(binding, dict) and sha(binding.get('release_sha256'))
                    and all(isinstance(binding.get(k), str) and binding[k]
                            for k in ('set_key', 'patch', 'evidence')), 'invalid patch binding')
        hud = f.get('hud', {})
        require(isinstance(hud, dict), 'HUD must be an object')
        require(set(hud) <= {'hp', 'gold', 'level', 'xp', 'xp_cap', 'stage'}, 'unknown HUD field')
        for k, v in hud.items():
            if k == 'stage':
                require(isinstance(v, str) and re.fullmatch(r'\d+-\d+', v), 'invalid stage')
            else:
                require(integer(v) and v >= 0, 'invalid HUD value')
        if 'level' in hud:
            require(1 <= hud['level'] <= 20, 'invalid level')
        if 'xp' in hud and 'xp_cap' in hud:
            require(hud['xp'] <= hud['xp_cap'], 'XP exceeds cap')
        layout = f.get('layout', {})
        require(isinstance(layout, dict), 'layout must be an object')
        locations, hexes, benches = {}, set(), set()
        for u in layout.get('units', []):
            require(isinstance(u, dict) and isinstance(u.get('key'), str) and u['key'], 'unit key missing')
            require(u['key'] not in locations, 'duplicate unit key')
            locations[u['key']] = u
            require(u.get('zone') in {'board', 'bench'}, 'invalid unit zone')
            require(u.get('owner') in {'self', 'opponent', 'unknown'}, 'invalid owner')
            box = u.get('box')
            require(isinstance(box, list) and len(box) == 4 and all(integer(x) for x in box)
                    and 0 <= box[0] < box[2] <= size[0]
                    and 0 <= box[1] < box[3] <= size[1], 'invalid unit box')
            if u.get('hex') is not None:
                h = u['hex']
                require(u['zone'] == 'board' and isinstance(h, list) and len(h) == 2
                        and all(integer(x) for x in h) and 0 <= h[0] < 4 and 0 <= h[1] < 7,
                        'hex must use own-side row 0..3, column 0..6')
                require(f.get('phase') == 'planning' and u['owner'] == 'self', 'hex requires own planning board')
                require(tuple(h) not in hexes, 'duplicate occupied hex')
                hexes.add(tuple(h))
            if u.get('bench_slot') is not None:
                slot = u['bench_slot']
                require(u['zone'] == 'bench' and integer(slot) and 0 <= slot < 9, 'invalid bench slot')
                require((u['owner'], slot) not in benches, 'duplicate bench slot')
                benches.add((u['owner'], slot))
        entities = f.get('entities', [])
        require(isinstance(entities, list), 'entities must be a list')
        entity_keys = set()
        for u in entities:
            require(isinstance(u, dict) and u.get('key') in locations and u['key'] not in entity_keys,
                    'entity missing unique spatial anchor')
            entity_keys.add(u['key'])
            identity(u.get('identity'), bool(binding))
            require(u['identity']['state'] != 'empty', 'spatial unit cannot be empty')
            if u.get('stars') is not None:
                require(integer(u['stars']) and 1 <= u['stars'] <= 4, 'invalid star count')
            if 'equipped' in u:
                check_slots(u['equipped'], 3, bool(binding))
        if 'inventory' in f:
            check_slots(f['inventory'], None, bool(binding))
        if 'shop' in f:
            require(isinstance(f['shop'], list), 'shop must be a list')
            used = set()
            for offer in f['shop']:
                require(isinstance(offer, dict) and integer(offer.get('slot'))
                        and 0 <= offer['slot'] < 5 and offer['slot'] not in used, 'invalid shop slot')
                used.add(offer['slot'])
                require(offer.get('kind') in {'champion', 'consumable', 'empty', 'unknown'}, 'invalid offer kind')
                identity(offer.get('identity'), bool(binding))
                require((offer['kind'] == 'empty') == (offer['identity']['state'] == 'empty'), 'shop emptiness mismatch')
                if 'cost' in offer:
                    require(integer(offer['cost']) and offer['cost'] >= 0, 'invalid offer cost')
    return dict(frames=len(frames), scenes=dict(sorted(counts.items())),
                frames_with_hud=sum(bool(f.get('hud')) for f in frames),
                frames_with_units=sum(bool(f.get('layout', {}).get('units')) for f in frames),
                independent_human_validation=all(f['review']['method'] == 'human_visual_review' for f in frames),
                current_patch_training_ready=False)


def check_slots(value, limit, bound):
    require(isinstance(value, dict) and value.get('coverage') in {'partial', 'complete', 'unknown'}, 'invalid item coverage')
    require(isinstance(value.get('slots'), list), 'item slots required')
    seen = set()
    for item in value['slots']:
        require(isinstance(item, dict) and integer(item.get('slot')) and item['slot'] >= 0
                and (limit is None or item['slot'] < limit) and item['slot'] not in seen, 'invalid item slot')
        seen.add(item['slot'])
        identity(item.get('identity'), bound)
    if value['coverage'] == 'complete':
        require(limit is not None and seen == set(range(limit)), 'complete coverage requires all bounded slots')
    if value['coverage'] == 'unknown':
        require(not seen, 'unknown coverage cannot contain reviewed slots')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('annotations', type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(json.loads(args.annotations.read_text()), args.annotations.parent), indent=2))
