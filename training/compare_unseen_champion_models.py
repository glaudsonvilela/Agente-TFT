#!/usr/bin/env python3
"""Compare two champion classifiers on the exact same unseen video boxes.

Predictions are diagnostic outputs, never labels. Verified identity probes come
only from the separate raw-video review file.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

from training.evaluate_unseen_replays import _frame, _stability
from hm.yolo_hud import _session, _tensor


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(frame: dict) -> list[tuple[str, dict]]:
    # The runtime includes reserve units in both records and bench_records.
    return ([('board', row) for row in frame['records']
             if row.get('zone') != 'bench_unit'] +
            [('bench', row) for row in frame['bench_records']] +
            [('enemy', row) for row in frame['enemy_records']])


def compare(config: dict, observations: list[dict], review: dict,
            active_path: Path, candidate_path: Path) -> dict:
    if review.get('model_predictions_used_as_labels') is not False:
        raise ValueError('Predictions cannot be used as review labels')
    sessions = {}
    for key, path in [('active', active_path), ('candidate', candidate_path)]:
        sessions[key] = _session(path, 224, 65)
    if sessions['active'][1] != sessions['candidate'][1]:
        raise ValueError('Model class names/order differ')
    videos = {row['source_id']: Path(row['video']) for row in config['sources']}
    by_key = {(row['source_id'], row['second']): row for row in observations}
    if len(by_key) != len(observations):
        raise ValueError('Duplicate observation key')
    paired = []
    spatial_rows = {'active': [], 'candidate': []}
    counts = defaultdict(Counter)
    runtime_active_disagreement = 0
    for observation in observations:
        image = _frame(videos[observation['source_id']], observation['second'])
        new_rows = {model: dict(source_id=observation['source_id'],
                                second=observation['second'], records=[],
                                bench_records=[], enemy_records=[])
                    for model in sessions}
        for zone, row in _rows(observation):
            crop = image.crop(tuple(int(value) for value in row['box'])).convert('RGB')
            if min(crop.size) < 8:
                continue
            tensor = _tensor(crop, 224)
            names = {}
            for model, (session, labels) in sessions.items():
                scores = session.run(None, {'images': tensor})[0][0]
                index = int(np.argmax(scores))
                names[model] = {'name': labels[index],
                                'score_uncalibrated': round(float(scores[index]), 4)}
                new_row = {'box': row['box'], 'candidate_name': labels[index],
                           'zone': 'board_unit' if zone == 'board' else zone}
                destination = {'board': 'records', 'bench': 'bench_records',
                               'enemy': 'enemy_records'}[zone]
                new_rows[model][destination].append(new_row)
            counts[zone]['boxes'] += 1
            counts[zone]['name_disagreements'] += (names['active']['name'] !=
                                                   names['candidate']['name'])
            if names['active']['name'] != row['candidate_name']:
                runtime_active_disagreement += 1
            paired.append({'source_id': observation['source_id'],
                           'second': observation['second'], 'zone': zone,
                           'box': row['box'], 'runtime_active_name': row['candidate_name'],
                           **names})
        for model in sessions:
            spatial_rows[model].append(new_rows[model])
    probes = []
    for frame in review['frames']:
        key = frame['source_id'], frame['second']
        if key not in by_key:
            raise ValueError(f'Unknown reviewed frame: {key}')
        for unit in frame.get('identity_only_units', []):
            if (unit.get('identity_status') != 'visually_verified' or
                    not unit.get('evidence') or not unit.get('name')):
                raise ValueError(f'Identity probe lacks visual evidence: {key}')
            point = unit['point']
            choices = [row for row in paired if
                       (row['source_id'], row['second'], row['zone']) ==
                       (key[0], key[1], unit['zone']) and
                       row['box'][0] <= point[0] <= row['box'][2] and
                       row['box'][1] <= point[1] <= row['box'][3]]
            choices.sort(key=lambda row: ((point[0] - (row['box'][0] + row['box'][2])/2)**2 +
                                          (point[1] - (row['box'][1] + row['box'][3])/2)**2))
            matched = choices[0] if choices else None
            probes.append({'source_id': key[0], 'second': key[1],
                           'zone': unit['zone'], 'verified_name': unit['name'],
                           'evidence': unit['evidence'],
                           'box': matched['box'] if matched else None,
                           'active': matched['active'] if matched else None,
                           'candidate': matched['candidate'] if matched else None})
    return {'schema_version': 1, 'scope': 'same-box paired model comparison',
            'predictions_used_as_labels': False,
            'active_sha256': _sha256(active_path),
            'candidate_sha256': _sha256(candidate_path),
            'source_frames': len(observations), 'paired_boxes': len(paired),
            'by_zone': {zone: dict(counts[zone]) for zone in ('board', 'bench', 'enemy')},
            'runtime_active_disagreement': runtime_active_disagreement,
            'spatial_consistency': {model: _stability(rows)
                                    for model, rows in spatial_rows.items()},
            'visually_verified_probes': probes,
            'pairs': paired,
            'limitations': [
                'Only visually verified probes can measure identity accuracy.',
                'Same detector boxes isolate the classifier; this does not compare detectors.',
                'Spatial pairing is approximate and movement can appear as name flicker.',
                'Classifier scores are uncalibrated.']}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--observations', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--active', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare(json.loads(args.config.read_text()),
                     [json.loads(line) for line in args.observations.read_text().splitlines()],
                     json.loads(args.review.read_text()), args.active, args.candidate)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in
                      ('source_frames', 'paired_boxes', 'by_zone',
                       'spatial_consistency', 'visually_verified_probes')},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
