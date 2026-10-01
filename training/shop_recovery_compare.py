"""S2: compare sealed S1/S2 observations of the same pixels, never assign truth."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from ingestion.knowledge_release import canonical, load, require
from training.shop_replay_observe import prepare, sha


def read_run(path: Path) -> tuple[dict, dict]:
    """Only read an explicit, complete local report. Checksums are not signatures."""
    report, digest = load(path)
    folder = path.parent
    complete, _ = load(folder / 'COMPLETE.json')
    manifest, manifest_hash = load(folder / 'manifest.json')
    require(complete.get('report_sha256') == digest and complete.get('manifest_sha256') == manifest_hash,
            'report/manifest checksum mismatch')
    summary = report['summary']
    require(summary.get('execution_complete') is True, 'incomplete shop report')
    for key in ('labels_used', 'game_state_updated', 'profile_promoted', 'model_trained'):
        require(summary.get(key) is False, f'unexpected side effect: {key}')
    require(summary.get('catalog_status') == 'not_bound', 'compare raw observations before catalog binding')
    rows = report['records']
    frames = manifest['frames']
    require(isinstance(rows, list) and 1 <= len(rows) <= 128 and len(rows) == len(frames), 'invalid frame count')
    statuses, panels = Counter(), Counter()
    last = -1
    for row, frame in zip(rows, frames):
        value = row['read']
        at = value['timestamp_ms']
        require(type(at) is int and at > last and at == frame['timestamp_ms'], 'timestamp identity mismatch')
        last = at
        require(value.get('error') is None and [s['slot'] for s in value['slots']] == list(range(5)), 'invalid slots')
        statuses.update(s['status'] for s in value['slots'])
        panels[value['panel_status']] += 1
    require(dict(statuses) == summary['slot_statuses'] and dict(panels) == summary['panel_statuses'],
            'aggregate counts do not match records')
    require(summary['frames'] == len(rows), 'summary frames mismatch')
    return report, manifest


def verify_current(baseline: Path, manifest: Path, root: Path, layout: Path) -> None:
    old, frozen = read_run(baseline)
    require(old['summary']['profile'] == 'shop_text_atlas_v1', 'baseline must be S1')
    require(frozen == prepare(manifest, root), 'current source pixels/timestamps differ from S1')
    expected = old['provenance']['input_files_sha256'].get(str(layout.resolve()))
    require(expected == sha(layout), 'base UI profile differs from S1')


def comparison(a, b) -> str:
    if a is None and b is None:
        return 'neither'
    if a is None:
        return 'candidate_only'
    if b is None:
        return 'baseline_only'
    equal = a == b if not isinstance(a, str) else ' '.join(a.lower().split()) == ' '.join(b.lower().split())
    return 'both_equal' if equal else 'both_disagree'


def compare(baseline: Path, candidate: Path) -> dict:
    before, a_frames = read_run(baseline)
    after, b_frames = read_run(candidate)
    require(a_frames == b_frames, 'cannot compare different source pixels/timestamps')
    a, b = before['summary'], after['summary']
    require(a['profile'] == 'shop_text_atlas_v1' and b['profile'] == 'shop_text_atlas_v2_local_routing', 'wrong reader pair')
    for key in ('layout_id', 'locale', 'ocr_language'):
        require(a[key] == b[key], f'comparison context mismatch: {key}')
    metrics = {field: Counter() for field in ('name', 'cost')}
    cases, recovered_panels, routing_fields = [], [], 0
    for first, second in zip(before['records'], after['records']):
        old, new = first['read'], second['read']
        at = old['timestamp_ms']
        trace = new.get('recovery', {})
        if trace.get('panel_source') == 'structural_fallback':
            recovered_panels.append(at)
        routing_fields += sum(len(t['conflicted_fields']) for t in trace.get('routing', []))
        for x, y in zip(old['slots'], new['slots']):
            for field in ('name', 'cost'):
                key = 'observed_' + field
                result = comparison(x[key], y[key])
                metrics[field][result] += 1
                if result in ('both_disagree', 'baseline_only'):
                    cases.append(dict(timestamp_ms=at, slot=x['slot'], field=field, comparison=result,
                                      baseline=x[key], candidate=y[key], candidate_status=y['status']))
    return dict(schema_version=1, frames=a['frames'], slots=a['frames'] * 5,
                baseline_statuses=a['slot_statuses'], candidate_statuses=b['slot_statuses'],
                baseline_panels=a['panel_statuses'], candidate_panels=b['panel_statuses'],
                fields={key: dict(value) for key, value in metrics.items()},
                structural_panel_timestamps=recovered_panels, field_conflicts=routing_fields, cases=cases,
                exact_accuracy=None, labels_used=False, game_state_updated=False, profile_promoted=False,
                metric_kind='same_pixel_historical_baseline_comparison',
                warning='new readability is not accuracy; historical timings are not controlled benchmarks')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--image-root', type=Path)
    parser.add_argument('--layout', type=Path)
    args = parser.parse_args()
    try:
        if args.candidate is None:
            require(all(x is not None for x in (args.manifest, args.image_root, args.layout)), 'preflight needs source paths')
            verify_current(args.baseline, args.manifest, args.image_root, args.layout)
            print('SHOP2_PREFLIGHT=verified_same_sources')
        else:
            require(args.output is not None, 'comparison requires output')
            report = compare(args.baseline, args.candidate)
            with args.output.open('xb') as file:
                file.write(canonical(report))
            for case in report['cases']:
                print('SHOP2_DIFFERENCE=' + json.dumps(case, ensure_ascii=False))
            print('SHOP2_COMPARISON=' + json.dumps({k: v for k, v in report.items() if k != 'cases'}, ensure_ascii=False))
            print('SHOP2_COMPARISON_REPORT=' + str(args.output))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'SHOP2_COMPARE_ERROR={error}\n')


if __name__ == '__main__':
    main()
