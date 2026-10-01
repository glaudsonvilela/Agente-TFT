"""S3 validates controls without treating appearance as permission or a label."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def number(value: object, low: float, high: float) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def validate_controls(report: dict, profile: dict) -> dict:
    """Recompute aggregates and acceptance from native traces; no expected labels."""
    specs = profile['controls']
    require([s['id'] for s in specs] == ['lock', 'buy_xp', 'refresh'], 'bad control order')
    status_counts = {s['id']: Counter() for s in specs}
    appearances = {s['id']: Counter() for s in specs}
    numeric_counts = Counter()
    calls = 0
    for row in report['records']:
        read, result = row['read'], row['controls']
        require(result['profile'] == profile['id'] and result['timestamp_ms'] == read['timestamp_ms'],
                'control profile/timestamp mismatch')
        require(result.get('error') is None and result.get('temporal_confirmation') is False,
                'control error or unsupported temporal confirmation')
        controls = result['controls']
        require([c['id'] for c in controls] == [s['id'] for s in specs], 'missing/duplicate controls')
        expected_fields = []
        for spec, control in zip(specs, controls):
            require(control['rect'] == spec['rect'] and control.get('action_allowed') is None,
                    'control geometry or authorization mismatch')
            scores = control['scores']
            if read['panel_status'] != 'located':
                require(scores == [], 'hidden panel has visual scores')
                expected_status, state = 'unavailable', None
            else:
                require(len(scores) == len(spec['templates']), 'missing template score')
                states = set()
                for template, score in zip(spec['templates'], scores):
                    sim, mae = score['similarity'], score['rgb_mae']
                    require(score['state'] == template['state'] and number(mae, 0, 255)
                            and (sim is None or number(sim, -1, 1)), 'invalid visual score')
                    eligible = sim is not None and sim >= spec['min_similarity'] and mae <= spec['max_rgb_mae']
                    require(score['eligible'] is eligible, 'false visual eligibility')
                    if eligible:
                        states.add(template['state'])
                expected_status = 'observed' if len(states) == 1 else 'ambiguous' if states else 'unknown'
                state = next(iter(states)) if len(states) == 1 else None
            require(control['status'] == expected_status and control['appearance'] == state,
                    'unsupported control appearance')
            status_counts[spec['id']][expected_status] += 1
            if state is not None:
                appearances[spec['id']][state] += 1
            for rect_key, suffix in [('price_rect', 'price'), ('free_count_rect', 'free_count')]:
                if spec[rect_key] is not None:
                    enabled = expected_status == 'observed' and (suffix == 'price' or state == 'free_refresh_appearance')
                    expected_fields.append((f"{spec['id']}_{suffix}", spec[rect_key], enabled))
        fields = result['numeric_fields']
        require(len(fields) == len(expected_fields), 'missing/extra control numeric field')
        expected_calls = 2 if any(e[2] for e in expected_fields) else 0
        require(type(result['ocr_process_calls']) is int and result['ocr_process_calls'] == expected_calls,
                'unexpected controls OCR budget')
        calls += expected_calls
        for field, (field_id, rect, enabled) in zip(fields, expected_fields):
            require(field['id'] == field_id and field['rect'] == rect, 'numeric field identity mismatch')
            attempts = field['attempts']
            if not enabled:
                require(attempts == [] and field['value'] is None and field['confidence'] is None
                        and field['status'] == 'not_observed', 'unavailable control invented a number')
                continue
            require([a['scale'] for a in attempts] == [3, 4], 'two OCR scales required')
            values = []
            for a in attempts:
                text, conf, reason = a['text'], a['confidence'], a['reason']
                require(conf is None or number(conf, 0, 1), 'invalid OCR confidence')
                if text is None:
                    require(conf is None and reason in ('no_text', 'atlas_assignment_conflict'), 'bad missing attempt')
                    values.append(None)
                    continue
                require(isinstance(text, str), 'OCR text must be string')
                valid = text.isascii() and text.isdigit() and 1 <= len(text) <= 2
                expected = 'invalid_text' if not valid else 'below_min_confidence' if conf is not None and conf < profile['min_text_confidence'] else 'eligible'
                require(conf is not None and reason == expected, 'forged numeric acceptance')
                values.append(text if reason == 'eligible' else None)
            accepted = values[0] is not None and values[0] == values[1]
            if accepted:
                require(type(field['value']) is int and field['value'] == int(values[0])
                        and field['confidence'] == min(a['confidence'] for a in attempts)
                        and field['status'] == 'observed', 'numeric consensus mismatch')
                numeric_counts[field_id] += 1
            else:
                require(field['value'] is None and field['confidence'] is None and field['status'] == 'unknown',
                        'conflicting/uncertain number was accepted')
    return dict(states={k: dict(v) for k, v in status_counts.items()},
                appearances={k: dict(v) for k, v in appearances.items()},
                numeric_readable=dict(numeric_counts), controls_ocr_process_calls=calls,
                action_authorization_provided=False, temporal_confirmation=False,
                closed_lock_reference_available=any(t['state'] == 'locked_appearance' for t in specs[0]['templates']))


def verify_prior(baseline: Path, manifest: Path, root: Path, layout: Path, recovery: Path) -> None:
    from training.shop_recovery_compare import read_run
    from training.shop_replay_observe import prepare, sha
    old, frozen = read_run(baseline)
    require(old['summary']['profile'] == 'shop_text_atlas_v2_local_routing'
            and 'controls_profile' not in old['summary'], 'baseline must be original S2')
    require(frozen == prepare(manifest, root), 'source frames/timestamps differ from S2')
    sources = old['provenance']['input_files_sha256']
    for path in (layout, recovery):
        require(sources.get(str(path.resolve())) == sha(path), 'UI/recovery changed since S2')


def compare_cards(baseline: Path, candidate: Path) -> dict:
    from training.shop_recovery_compare import read_run
    before, frames = read_run(baseline)
    after, other_frames = read_run(candidate)
    require(frames == other_frames, 'different images in S3 comparison')
    require(before['summary']['profile'] == after['summary']['profile'] == 'shop_text_atlas_v2_local_routing',
            'S3 must preserve the S2 card reader')
    require('controls_profile' not in before['summary'] and 'controls_profile' in after['summary'], 'wrong comparison pair')
    for key in ('layout_id', 'locale', 'ocr_language'):
        require(before['summary'][key] == after['summary'][key], 'comparison environment mismatch')
    changes = [dict(timestamp_ms=a['read']['timestamp_ms']) for a, b in zip(before['records'], after['records'])
               if a['read'] != b['read']]
    return dict(frames=len(frames['frames']), card_observations_unchanged=not changes,
                changed_frames=changes, comparison_kind='complete_S2_read_records_excluding_elapsed_time',
                historical_baseline=True, exact_accuracy=None)


def main() -> None:
    from ingestion.knowledge_release import canonical
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    for key in ('manifest', 'image-root', 'layout', 'recovery', 'candidate', 'output'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    try:
        if args.candidate is None:
            require(all(getattr(args, k) is not None for k in ('manifest', 'image_root', 'layout', 'recovery')), 'preflight paths required')
            verify_prior(args.baseline, args.manifest, args.image_root, args.layout, args.recovery)
            print('SHOP3_PREFLIGHT=verified_S2_sources')
        else:
            require(args.output is not None, 'comparison output required')
            result = compare_cards(args.baseline, args.candidate)
            with args.output.open('xb') as file:
                file.write(canonical(result))
            print('SHOP3_REGRESSION=' + json.dumps(result))
            require(result['card_observations_unchanged'], 'card reader changed; preserve evidence for review')
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'SHOP3_ERROR={error}\n')


if __name__ == '__main__':
    main()
