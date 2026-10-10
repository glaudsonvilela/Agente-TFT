"""Compare original and 1080p-aligned classifiers on unseen source videos."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


def evaluate(index_path, probe, baseline_weights, trial_weights):
    index = json.loads(index_path.read_text(encoding='utf-8'))
    report = json.loads((probe / 'provenance.json').read_text(encoding='utf-8'))
    if (index.get('model_predictions_used_as_labels') is not False or
            report.get('model_predictions_used_as_labels') is not False or
            report.get('heldout_scaled') != 4):
        raise ValueError('Invalid independent holdout contract')
    by_id = {row['review_id']: row for row in index['records']}
    cases = [row for row in report['rows'] if row['split'] == 'holdout']
    results = {}
    for name, weights in (('previous', baseline_weights), ('scale_1080', trial_weights)):
        model = YOLO(str(weights))
        rows = []
        for case in cases:
            source = by_id[case['review_id']]
            for variant, path in (
                    ('natural', Path(source['natural_crop'])),
                    ('1080', probe / 'holdout' / case['game_id'] /
                     f"{int(case['review_id']):03d}-1080.png")):
                prediction = model.predict(str(path), device=0, imgsz=224,
                                           verbose=False)[0]
                top5 = [model.names[int(i)] for i in prediction.probs.top5]
                rows.append(dict(review_id=case['review_id'],
                                 source_video=case['source_video'],
                                 variant=variant, truth=case['game_id'],
                                 top1=top5[0], top1_correct=top5[0] == case['game_id'],
                                 top5_correct=case['game_id'] in top5,
                                 top5=top5))
        results[name] = dict(weights=str(weights), rows=rows,
                             natural_top1=sum(x['top1_correct'] for x in rows if x['variant'] == 'natural'),
                             scaled_top1=sum(x['top1_correct'] for x in rows if x['variant'] == '1080'),
                             scaled_top5=sum(x['top5_correct'] for x in rows if x['variant'] == '1080'))
    return dict(scope='four_user_reviewed_crops_from_two_unseen_videos',
                model_predictions_used_as_labels=False,
                sample_count=4, models=results,
                limitation='Four crops cannot establish 46-class generalization')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.index, args.probe, args.baseline, args.trial)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8')
    print(json.dumps({name: {key: value for key, value in model.items() if key != 'rows'}
                      for name, model in result['models'].items()}, ensure_ascii=False))
