"""S4: materialize a reviewed UI data patch and reuse the frozen S3 executable."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import subprocess

from ingestion.knowledge_release import canonical, load, require
from training.shop_controls_profile import materialize, validate_patch, compare_observations
from training.shop_controls_evidence import validate_controls
from training.shop_recovery_compare import read_run
from training.shop_replay_observe import prepare, run as observe, sha, verify_sources


def preflight(args: argparse.Namespace) -> tuple[dict, dict, dict, bytes, dict, dict]:
    before, frozen = read_run(args.baseline)
    base, _ = load(args.base_controls)
    raw = args.base_controls.read_bytes()
    require(json.loads(raw) == base, 'parent changed while loading')
    patch, _ = load(args.patch)
    validate_patch(base, raw, patch)
    require(before['summary'].get('controls_profile') == base['id'], 'baseline controls mismatch')
    require(before['summary'].get('ocr_language') == os.environ.get('TFT_SHOP_OCR_LANGUAGE', 'eng'),
            'OCR language differs from frozen S3')
    metrics = validate_controls(before, base)
    require(before['summary'].get('controls_metrics') == metrics, 'baseline controls aggregate mismatch')
    require(frozen == prepare(args.manifest, args.image_root), 'source frames changed since S3')
    prior = before['provenance']['input_files_sha256']
    for path in (args.layout, args.recovery_profile, args.base_controls, args.probe):
        require(prior.get(str(path.resolve())) == sha(path), f'frozen input changed: {path}')
    sources = {str(path.resolve()): sha(path) for path in (
        args.baseline, args.baseline.parent / 'COMPLETE.json', args.baseline.parent / 'manifest.json',
        args.base_controls, args.patch, args.layout, args.recovery_profile, args.probe, args.manifest)}
    sources.update({str((args.image_root / r['image']).resolve()): r['sha256'] for r in frozen['frames']})
    verify_sources(sources)
    return before, frozen, base, raw, patch, sources


def execute(args: argparse.Namespace) -> dict:
    before, frozen, base, raw, patch, sources = preflight(args)
    out = args.output.absolute()
    require(not out.exists(), 'S4 output exists; no overwrite')
    out.mkdir(parents=True, exist_ok=False)
    (out / 'plan.json').write_bytes(canonical(dict(policy='shop_controls_ui_patch_v1',
        baseline=str(args.baseline.resolve()), patch=patch, frozen_input_files_sha256=sources,
        labels_used=False, profile_promoted=False)))
    print('SHOP4_PHASE=materialize_UI_data')
    effective, seed_sources = materialize(base, raw, patch, args.image_root, frozen)
    sources.update(seed_sources)
    effective_path = out / 'controls-effective.json'
    effective_path.write_bytes(canonical(effective))
    sources[str(effective_path.resolve())] = sha(effective_path)
    verify_sources(sources)
    print('SHOP4_PHASE=read_with_frozen_S3_binary')
    native = argparse.Namespace(manifest=args.manifest, image_root=args.image_root, layout=args.layout,
        recovery_profile=args.recovery_profile, controls_profile=effective_path, probe=args.probe,
        output=out / 'run', context=None, release=None)
    with (out / 'reader.stdout').open('x', encoding='utf-8') as log, redirect_stdout(log):
        observe(native)
    after, new_frozen = read_run(out / 'run' / 'report.json')
    require(frozen == new_frozen, 'candidate manifest differs from frozen baseline')
    require(after['summary'].get('controls_profile') == effective['id'], 'candidate profile mismatch')
    require(after['summary'].get('controls_metrics') == validate_controls(after, effective),
            'candidate controls aggregate mismatch')
    verify_sources(sources)
    comparison = compare_observations(before, after)
    (out / 'comparison.json').write_bytes(canonical(comparison))
    summary = dict(schema_version=1, policy='same_binary_controls_data_patch_v1',
        frames=comparison['frames'], baseline_controls=before['summary']['controls_metrics'],
        candidate_controls=after['summary']['controls_metrics'], fields=comparison['fields'],
        card_observations_unchanged=comparison['card_observations_unchanged'],
        non_refresh_visuals_unchanged=comparison['non_refresh_visuals_unchanged'],
        native_binary_unchanged=True, backend_versions_frozen=False, compiled=False, rust_changed=False,
        seed_images_decoded=len(patch['additional_templates']), video_decoded=False,
        exact_accuracy=None, labels_used=False, profile_promoted=False, model_trained=False,
        game_state_updated=False, human_labels_required=False,
        execution_complete=comparison['card_observations_unchanged'] and comparison['non_refresh_visuals_unchanged'],
        note='diagnostic UI patch; same recording; appearance is not click permission; no statistical independence claim')
    result = dict(summary=summary, comparison=comparison,
                  native_report=str(out / 'run' / 'report.json'),
                  frozen_input_files_sha256=sources)
    (out / 'report.json').write_bytes(canonical(result))
    (out / 'COMPLETE.json').write_bytes(canonical(dict(report_sha256=sha(out / 'report.json'),
                                                      execution_complete=summary['execution_complete'])))
    for case in comparison['cases']:
        print('SHOP4_DIFFERENCE=' + json.dumps(case, ensure_ascii=False))
    print('SHOP4_REGRESSION=' + json.dumps({k: comparison[k] for k in (
        'frames', 'card_observations_unchanged', 'non_refresh_visuals_unchanged',
        'changed_card_frames', 'changed_non_refresh_visual_frames')}))
    print('SHOP4_SUMMARY=' + json.dumps(summary, ensure_ascii=False))
    print('SHOP4_REPORT=' + str(out / 'report.json'))
    require(summary['execution_complete'], 'preserved reader changed; evidence retained, not accepted')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('baseline', 'manifest', 'image-root', 'layout', 'recovery-profile',
                'base-controls', 'patch', 'probe', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    try:
        execute(parser.parse_args())
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(2, f'SHOP4_ERROR={error}\n')


if __name__ == '__main__':
    main()
