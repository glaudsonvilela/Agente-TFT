"""Reframe user-reviewed champion crops to the recognizer's 1080p pixel scale.

This changes image scale only. It creates no new identities or independent
poses; held-out source videos remain completely outside training.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

import cv2


HELD_OUT = {'8W7Wfnf36M8.webm', '-YQHDFlMRRs.webm'}


def source_height(row, cache):
    resolution = row.get('source_resolution')
    if isinstance(resolution, list) and len(resolution) == 2:
        return int(resolution[1])
    video = row['source_video_local']
    if video not in cache:
        answer = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=height', '-of', 'csv=p=0', video],
            check=True, capture_output=True, text=True, timeout=20)
        cache[video] = int(answer.stdout.strip())
    return cache[video]


def build(index_path: Path, output: Path):
    if output.exists():
        raise FileExistsError(output)
    index = json.loads(index_path.read_text(encoding='utf-8'))
    if index.get('model_predictions_used_as_labels') is not False:
        raise ValueError('The source contains prediction labels')
    records = index['records']
    classes = {row['game_id'] for row in records}
    if len(classes) != 46:
        raise ValueError('Expected the isolated 46-class reviewed source')
    dimensions, seen, counts = {}, set(), Counter()
    rows = []
    for row in records:
        if row.get('review_status') not in ('user_confirmed_candidate',
                                             'ui_confirmed_candidate'):
            raise ValueError(f"Identity was not reviewed: {row['review_id']}")
        path = Path(row['natural_crop'])
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row['natural_crop_sha256'] or digest in seen:
            raise ValueError(f"Changed or duplicate image: {row['review_id']}")
        seen.add(digest)
        split = ('holdout' if Path(row['source_video_local']).name in HELD_OUT
                 else 'train')
        height = source_height(row, dimensions)
        if not 720 <= height <= 4320:
            raise ValueError(f"Unexpected source size: {row['review_id']}")
        crop = cv2.imread(str(path))
        if crop is None:
            raise ValueError(f"Cannot open crop: {path}")
        scale = min(1.0, 1080 / height)
        resized = cv2.resize(crop, (max(16, round(crop.shape[1] * scale)),
                                     max(16, round(crop.shape[0] * scale))),
                             interpolation=cv2.INTER_AREA)
        folder = output / ('dataset/train' if split == 'train' else 'holdout') / row['game_id']
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / f"{int(row['review_id']):03d}-1080.png"
        if not cv2.imwrite(str(destination), resized):
            raise OSError(destination)
        if split == 'train':
            (folder / f"{int(row['review_id']):03d}-native{path.suffix}").symlink_to(path)
            validation = output / 'dataset/val' / row['game_id']
            validation.mkdir(parents=True, exist_ok=True)
            (validation / destination.name).symlink_to(destination)
            (validation / f"{int(row['review_id']):03d}-native{path.suffix}").symlink_to(path)
        counts[split] += 1
        rows.append(dict(review_id=row['review_id'], game_id=row['game_id'],
                         source_video=Path(row['source_video_local']).name,
                         split=split, source_height=height, image_scale=scale,
                         original_sha256=digest,
                         normalized_sha256=hashlib.sha256(destination.read_bytes()).hexdigest()))
    if counts != {'train': 102, 'holdout': 4}:
        raise ValueError(f'Unexpected split: {counts}')
    report = dict(scope='telemetry_scale_1080_probe',
                  model_predictions_used_as_labels=False,
                  source_index=str(index_path), train_original=102,
                  train_scaled=102, heldout_scaled=4,
                  independent_new_poses=0,
                  validation_note='Validation mirrors training; use only held-out videos',
                  rows=rows)
    (output / 'provenance.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    summary = build(args.index, args.output)
    print(json.dumps({key: value for key, value in summary.items() if key != 'rows'},
                     ensure_ascii=False))
