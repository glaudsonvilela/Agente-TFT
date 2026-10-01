"""B3 one-command experiment: frozen native B1 regression and a separate pretrained detector."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time
from training.board_detector_core import require, policy_contract, compare_frame, summarize


def preflight(args):
    from ingestion.knowledge_release import load
    from training.board_spatial_run import preflight as b1_preflight
    from training.board_spatial_evidence import validate
    from training.shop_replay_observe import sha, verify_sources
    p, manifest, sources = b1_preflight(args)
    baseline = args.baseline.resolve(strict=True)
    if baseline.is_dir():
        baseline = baseline/'run/report.json'
    old, old_hash = load(baseline)
    old_manifest, manifest_hash = load(baseline.parent/'manifest.json')
    seal, seal_hash = load(baseline.parent/'COMPLETE.json')
    require(old_hash == seal['report_sha256'] and manifest_hash == seal['manifest_sha256'], 'B1 seal mismatch')
    require(old_manifest == manifest, 'B3 must compare all the same B1 image identities and timestamps')
    validate(old, manifest, p)
    require(all('bench_presence' not in r for r in old['records']), 'historical baseline must be B1')
    original_sources = old.get('provenance', {}).get('input_files_sha256', {})
    for path in [args.profile, args.probe]:
        path = path.resolve(strict=True)
        require(original_sources.get(str(path)) == sha(path), 'original B1 profile/binary is not preserved: '+str(path))
    policy, policy_hash = load(args.detector_policy)
    policy_contract(policy)
    sources.update({str(baseline): old_hash, str(baseline.parent/'manifest.json'): manifest_hash,
                    str(baseline.parent/'COMPLETE.json'): seal_hash,
                    str(args.detector_policy.resolve()): policy_hash})
    for code in Path(__file__).parent.glob('board_detector*.py'):
        sources[str(code.resolve())] = sha(code)
    verify_sources(sources)
    return p, manifest, sources, old, policy


def run_native(command, out):
    with (out/'b1.stdout.jsonl').open('xb') as log, (out/'b1.stderr').open('xb') as err:
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=err, start_new_session=True)
        try:
            rc = proc.wait(timeout=180)
            require(rc == 0, 'frozen B1 execution failed; inspect b1.stderr')
        except BaseException:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            raise


def regression(old, new):
    require(len(old['records']) == len(new['records']), 'B1 frame count changed')
    changed = [a['read']['timestamp_ms'] for a, b in zip(old['records'], new['records']) if a['read'] != b['read']]
    return dict(frames=len(old['records']), b1_observations_unchanged=not changed, changed_frames=changed)


def run(args):
    from ingestion.knowledge_release import canonical, load
    from training.shop_replay_observe import sha, verify_sources
    from training.board_spatial_evidence import validate
    from training.board_spatial_run import source_path
    from training.board_detector_backend import GroundedPresence, decode
    from training.board_detector_viewer import write_viewer
    p, manifest, sources, old, policy = preflight(args)
    out = args.output.absolute()
    require(not out.exists(), 'B3 output exists; no overwrite')
    out.mkdir(parents=True, exist_ok=False)
    (out/'manifest.json').write_bytes(canonical(manifest))
    (out/'detector-policy.json').write_bytes(canonical(policy))
    try:
        print('BOARD3_PHASE=verify_frozen_B1', flush=True)
        command = [str(args.probe.resolve()), str(out/'manifest.json'), str(args.image_root.resolve()),
                   str(args.profile.resolve()), str(out/'b1-native.json')]
        (out/'b1-command.json').write_bytes(canonical(command))
        run_native(command, out)
        native, _ = load(out/'b1-native.json')
        validate(native, manifest, p)
        reg = regression(old, native)
        (out/'regression.json').write_bytes(canonical(reg))
        print('BOARD3_REGRESSION='+json.dumps(reg), flush=True)
        require(reg['b1_observations_unchanged'], 'complete B1 read records changed; experiment stopped')
        verify_sources(sources)
        print('BOARD3_PHASE=load_pretrained_detector_cpu', flush=True)
        detector = GroundedPresence(args.model_cache, policy)
        (out/'model.json').write_bytes(canonical(detector.provenance))
        records = []
        with (out/'events.jsonl').open('xb') as events:
            for entry, old_record in zip(manifest['frames'], native['records']):
                started = time.perf_counter()
                image, decoded_hash = decode(source_path(args.image_root.resolve(), entry['image']),
                                             p['reference_width'], p['reference_height'])
                decoded = (time.perf_counter()-started)*1000
                model = detector.infer(image, p['scan_rect'])
                b1 = old_record['read']
                compared = compare_frame(b1, model)
                r = dict(timestamp_ms=entry['timestamp_ms'], image=entry['image'],
                    image_sha256=entry['sha256'], decoded_rgb_sha256=decoded_hash,
                    b1=b1, neural=model, comparison=compared, decode_ms=decoded,
                    model_ms=model['model_ms'], candidate_total_ms=(time.perf_counter()-started)*1000)
                events.write(canonical(r)+b'\n'); events.flush()
                records.append(r)
                print('BOARD3_FRAME='+json.dumps(dict(timestamp_ms=r['timestamp_ms'],
                    b1_markers=len(b1['markers']), neural_proposals=len(model['proposals']),
                    b1_projection=b1['projection_status'], model_ms=r['model_ms'])), flush=True)
        verify_sources(sources)
        detector.verify()
        summary = summarize(records, old['summary'])
        summary['b1_rerun_timing'] = {k: v for k, v in native['summary'].items() if '_ms_p' in k}
        summary['model_load_ms'] = detector.load_ms
        summary['process_max_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        summary['model_revision'] = policy['model_revision']
        summary['weights_sha256'] = policy['weights_sha256']
        summary['timing_note'] = 'B1 and detector run sequentially with separately decoded images; cold/warm conditions differ; not a controlled speed contest.'
        report = dict(summary=summary, regression=reg, records=records, model=detector.provenance,
            provenance=dict(input_files_sha256=sources, source_images_unchanged=True,
                manifest_sha256=sha(out/'manifest.json'), detector_policy_sha256=sha(out/'detector-policy.json'),
                pretrained_model_not_tft_finetuned=True, server_used=False,
                timestamps='inherited sparse manifest, no source-video PTS verification'))
        write_viewer(out/'viewer.html', records, args.image_root.resolve())
        verify_sources(sources)
        (out/'report.json').write_bytes(canonical(report))
        (out/'comparison.txt').write_text('BOARD3_REGRESSION='+json.dumps(reg)+'\nBOARD3_SUMMARY='+json.dumps(summary, ensure_ascii=False)+'\n', encoding='utf-8')
        (out/'COMPLETE.json').write_bytes(canonical({name: sha(out/name) for name in
            ['report.json', 'events.jsonl', 'manifest.json', 'detector-policy.json', 'model.json',
             'regression.json', 'viewer.html', 'comparison.txt']}))
        print('BOARD3_SUMMARY='+json.dumps(summary, ensure_ascii=False), flush=True)
        print('BOARD3_REPORT='+str(out/'report.json'), flush=True)
        print('BOARD3_VIEWER='+str(out/'viewer.html'), flush=True)
        return report
    except BaseException as exc:
        if not (out/'COMPLETE.json').exists():
            (out/'FAILED.json').write_bytes(canonical(dict(execution_complete=False, error=str(exc),
                exception=type(exc).__name__, game_state_updated=False, profile_promoted=False)))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for k in ('baseline', 'manifest', 'image-root', 'profile', 'board-topology', 'bench-topology',
              'probe', 'detector-policy', 'model-cache', 'output'):
        parser.add_argument('--'+k, type=Path, required=True)
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    def interrupted(_signum, _frame):
        raise InterruptedError('diagnostic interrupted; incomplete result retained')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        if args.preflight_only:
            preflight(args); print('BOARD3_PREFLIGHT_OK=true')
        else:
            run(args)
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as e:
        parser.exit(2, f'BOARD3_ERROR={e}\n')


if __name__ == '__main__':
    main()
