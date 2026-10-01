"""S5: compare isolated numeric fields against a complete S4 observation run."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import subprocess

from ingestion.knowledge_release import canonical, load, require
from training.shop_controls_evidence import validate_controls
from training.shop_numbers_policy import validate_policy
from training.shop_recovery_compare import comparison, read_run
from training.shop_replay_observe import prepare, run as observe, sha, verify_sources


def preflight(args: argparse.Namespace) -> tuple[dict, dict, Path, dict]:
    outer, digest = load(args.baseline)
    complete, _ = load(args.baseline.parent / 'COMPLETE.json')
    require(complete.get('report_sha256') == digest and complete.get('execution_complete') is True,
            'S4 result checksum or completion mismatch')
    summary = outer['summary']
    require(summary.get('policy') == 'same_binary_controls_data_patch_v1'
            and summary.get('execution_complete') is True, 'complete S4 baseline required')
    for key in ('labels_used', 'profile_promoted', 'model_trained', 'game_state_updated'):
        require(summary.get(key) is False, 'S4 baseline has unexpected side effects')
    native = args.baseline.parent / 'run/report.json'
    require(Path(outer['native_report']).resolve() == native.resolve(), 'S4 native report must be local to its run')
    before, frozen = read_run(native)
    controls_path = args.baseline.parent / 'controls-effective.json'
    controls, controls_hash = load(controls_path)
    metrics = validate_controls(before, controls)
    require(before['summary'].get('controls_metrics') == summary.get('candidate_controls') == metrics,
            'S4 metric identity mismatch')
    require(before['summary'].get('controls_profile') == controls['id'], 'S4 effective profile mismatch')
    require(before['summary'].get('ocr_language') == os.environ.get('TFT_SHOP_OCR_LANGUAGE', 'eng'),
            'OCR language changed since S4')
    require(frozen == prepare(args.manifest, args.image_root), 'images/timestamps changed since S4')
    sources = dict(outer['frozen_input_files_sha256'])
    prior = before['provenance']['input_files_sha256']
    require(sources.get(str(controls_path.resolve())) == controls_hash
            and prior.get(str(controls_path.resolve())) == controls_hash, 'effective controls not pinned')
    for path in (args.layout, args.recovery_profile):
        require(prior.get(str(path.resolve())) == sha(path) == sources.get(str(path.resolve())),
                'UI/recovery changed since S4')
    policy, _ = load(args.numbers_profile)
    layout, _ = load(args.layout)
    validate_policy(policy, controls, layout)
    for path in (args.baseline, args.baseline.parent/'COMPLETE.json', native,
                 native.parent/'COMPLETE.json', native.parent/'manifest.json', args.numbers_profile, args.manifest):
        sources[str(path.resolve())] = sha(path)
    verify_sources(sources)
    return before, frozen, controls_path, sources


def compare_reports(before: dict, after: dict) -> dict:
    require(len(before['records']) == len(after['records']), 'S5 frame count mismatch')
    metrics = {key: Counter() for key in ('buy_xp_price', 'refresh_price', 'refresh_free_count')}
    cards, visuals, cases = [], [], []
    for a, b in zip(before['records'], after['records']):
        at = a['read']['timestamp_ms']
        require(at == b['read']['timestamp_ms'], 'S5 timestamp mismatch')
        if a['read'] != b['read']:
            cards.append(at)
        if a['controls']['controls'] != b['controls']['controls']:
            visuals.append(at)
        old, new = a['controls']['numeric_fields'], b['controls']['numeric_fields']
        require([v['id'] for v in old] == [v['id'] for v in new] == list(metrics), 'S5 numeric identities mismatch')
        for x, y in zip(old, new):
            result = comparison(x['value'], y['value'])
            metrics[x['id']][result] += 1
            if result in ('candidate_only', 'baseline_only', 'both_disagree'):
                cases.append(dict(timestamp_ms=at, field=x['id'], comparison=result,
                                  baseline=x['value'], candidate=y['value'], baseline_trace=x, candidate_trace=y))
    return dict(frames=len(before['records']), card_observations_unchanged=not cards,
                visual_observations_unchanged=not visuals, changed_card_frames=cards,
                changed_visual_frames=visuals, fields={k:dict(v) for k,v in metrics.items()}, cases=cases)


def execute(args: argparse.Namespace) -> dict:
    before, frozen, controls_path, sources = preflight(args)
    sources[str(args.probe.resolve(strict=True))] = sha(args.probe)
    out = args.output.absolute()
    require(not out.exists(), 'S5 output exists; no overwrite')
    out.mkdir(parents=True, exist_ok=False)
    (out/'plan.json').write_bytes(canonical(dict(policy='isolated_control_numbers_v1',
        baseline=str(args.baseline.resolve()), controls_profile=str(controls_path.resolve()),
        numbers_profile=str(args.numbers_profile.resolve()), frozen_input_files_sha256=sources,
        labels_used=False, profile_promoted=False)))
    print('SHOP5_PHASE=read_isolated_fields')
    with (out/'reader.stdout').open('x',encoding='utf-8') as log, redirect_stdout(log):
        observe(argparse.Namespace(manifest=args.manifest, image_root=args.image_root,
            layout=args.layout, recovery_profile=args.recovery_profile, controls_profile=controls_path,
            numbers_profile=args.numbers_profile, probe=args.probe, output=out/'run', context=None, release=None))
    after, new_frozen = read_run(out/'run/report.json')
    require(frozen == new_frozen, 'S5 manifest mismatch')
    for key in ('profile', 'layout_id', 'locale', 'ocr_language', 'controls_profile'):
        require(before['summary'][key] == after['summary'][key], 'S5 comparison context mismatch')
    policy, _ = load(args.numbers_profile)
    controls, _ = load(controls_path)
    require(after['summary']['controls_metrics'] == validate_controls(after, controls, policy),
            'S5 recomputed numeric metrics mismatch')
    verify_sources(sources)
    result = compare_reports(before, after)
    (out/'comparison.json').write_bytes(canonical(result))
    summary = dict(schema_version=1, policy='isolated_control_numbers_v1', frames=result['frames'],
        baseline_controls=before['summary']['controls_metrics'], candidate_controls=after['summary']['controls_metrics'],
        fields=result['fields'], card_observations_unchanged=result['card_observations_unchanged'],
        visual_observations_unchanged=result['visual_observations_unchanged'],
        candidate_controls_ocr_process_calls=after['summary']['controls_ocr_process_calls'],
        baseline_controls_ocr_process_calls=before['summary']['controls_ocr_process_calls'],
        candidate_frame_ms_p50=after['summary']['frame_ms_p50'], candidate_frame_ms_p95=after['summary']['frame_ms_p95'],
        numbers_profile=policy['id'], native_binary_unchanged=False, backend_versions_frozen=False,
        exact_accuracy=None, labels_used=False, model_trained=False, profile_promoted=False,
        game_state_updated=False, human_labels_required=False, video_decoded=False,
        execution_complete=result['card_observations_unchanged'] and result['visual_observations_unchanged'],
        note='one field per OCR call, two scales; higher process budget measured; no assumed numbers or promotion')
    report = dict(summary=summary, comparison=result, native_report=str(out/'run/report.json'),
                  frozen_input_files_sha256=sources)
    (out/'report.json').write_bytes(canonical(report))
    (out/'COMPLETE.json').write_bytes(canonical(dict(report_sha256=sha(out/'report.json'),
        execution_complete=summary['execution_complete'])))
    for case in result['cases']:
        print('SHOP5_DIFFERENCE=' + json.dumps(case,ensure_ascii=False))
    print('SHOP5_REGRESSION=' + json.dumps({k:result[k] for k in ('frames','card_observations_unchanged',
        'visual_observations_unchanged','changed_card_frames','changed_visual_frames')}))
    print('SHOP5_SUMMARY=' + json.dumps(summary,ensure_ascii=False))
    print('SHOP5_REPORT=' + str(out/'report.json'))
    require(summary['execution_complete'], 'preserved observations changed; evidence retained')
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('baseline','manifest','image-root','layout','recovery-profile','numbers-profile','probe','output'):
        parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    try:
        if args.preflight_only:
            preflight(args)
            print('SHOP5_PREFLIGHT=verified_S4_sources')
        else:
            execute(args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(2, f'SHOP5_ERROR={error}\n')


if __name__ == '__main__':
    main()
