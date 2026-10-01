"""Run B1 on existing local frames; no labels, game access or OCR."""
from __future__ import annotations
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import signal
import subprocess
from training.board_spatial_evidence import profile_contract, require, validate
from training.board_spatial_viewer import write_viewer


def source_path(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and not Path(relative).is_absolute()
            and '..' not in Path(relative).parts, 'unsafe source image')
    path = (root / relative).resolve(strict=True)
    require(path.is_relative_to(root) and path.is_file()
            and path.suffix.lower() in ('.png', '.jpg', '.jpeg'), 'invalid local image')
    return path


def preflight(args, with_probe=True):
    from ingestion.knowledge_release import load
    from training.shop_replay_observe import prepare, sha, verify_sources
    root = args.image_root.resolve(strict=True)
    p, _ = load(args.profile)
    profile_contract(p)
    board, _ = load(args.board_topology)
    bench, _ = load(args.bench_topology)
    require(board.get('id') == p['board_topology_id'] and board.get('rows_per_side') == 4
            and board.get('columns') == 7 and board.get('set_specific') is False,
            'board topology mismatch')
    require(bench.get('id') == p['bench_topology_id'] and bench.get('slots') == list(range(9))
            and bench.get('set_specific') is False, 'bench topology mismatch')
    manifest = prepare(args.manifest, root)
    sources = {str(path.resolve(strict=True)): sha(path) for path in
               (args.manifest, args.profile, args.board_topology, args.bench_topology)}
    for row in manifest['frames']:
        path = source_path(root, row['image'])
        sources[str(path)] = row['sha256']
    for relative, expected in ((p['reference_image'], p['reference_sha256']),
                               (p['geometry_source']['image'], p['geometry_source']['sha256'])):
        path = source_path(root, relative)
        require(sha(path) == expected, 'reference seed hash mismatch')
        sources[str(path)] = expected
    require(sum(source_path(root, r['image']).stat().st_size for r in manifest['frames']) <= 64*1024*1024,
            'self-contained viewer byte budget exceeded')
    if with_probe:
        binary = args.probe.resolve(strict=True)
        require(binary.is_file(), 'native probe missing')
        sources[str(binary)] = sha(binary)
    verify_sources(sources)
    return p, manifest, sources


def run(args):
    from ingestion.knowledge_release import canonical, load
    from training.shop_replay_observe import sha, verify_sources
    p, manifest, sources = preflight(args)
    out = args.output.absolute()
    require(not out.exists(), 'output exists; no overwrite')
    out.mkdir(parents=True, exist_ok=False)
    (out/'manifest.json').write_bytes(canonical(manifest))
    command = [str(args.probe.resolve()), str(out/'manifest.json'), str(args.image_root.resolve()),
               str(args.profile.resolve()), str(out/'native.json')]
    (out/'command.json').write_bytes(canonical(command))
    with (out/'events.jsonl').open('xb') as log, (out/'native.stderr').open('xb') as err:
        child = subprocess.Popen(command, stdout=log, stderr=err, start_new_session=True)
        try:
            rc = child.wait(timeout=180)
        except BaseException:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            raise
    require(rc == 0, f'native spatial probe failed ({rc}); inspect {out}/native.stderr')
    report, _ = load(out/'native.json')
    validate(report, manifest, p)
    verify_sources(sources)
    write_viewer(out/'viewer.html', p, manifest, report['records'], args.image_root.resolve())
    verify_sources(sources)
    report['provenance'] = dict(input_files_sha256=sources, frozen_manifest_sha256=sha(out/'manifest.json'),
        board_topology=p['board_topology_id'], bench_topology=p['bench_topology_id'],
        geometry_seed=p['geometry_source'], empty_appearance_seed=p['reference_image'],
        seed_frames_may_be_in_evaluation=True, catalog_bound=False,
        raw_image_timestamps='manifest timestamps; source video PTS not checked in sparse JPEGs')
    (out/'report.json').write_bytes(canonical(report))
    (out/'COMPLETE.json').write_bytes(canonical(dict(report_sha256=sha(out/'report.json'),
        manifest_sha256=sha(out/'manifest.json'), viewer_sha256=sha(out/'viewer.html'))))
    for record in report['records']:
        r = record['read']
        print('BOARD1_FRAME=' + json.dumps(dict(timestamp_ms=r['timestamp_ms'], projection=r['projection_status'],
            marker_candidates=len(r['markers']), bench_evidence=dict(Counter(b['evidence'] for b in r['bench'])),
            scan_ms=record['scan_ms']), ensure_ascii=False))
    print('BOARD1_SUMMARY=' + json.dumps(report['summary'], ensure_ascii=False))
    print('BOARD1_REPORT=' + str(out/'report.json'))
    print('BOARD1_VIEWER=' + str(out/'viewer.html'))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('manifest', 'image-root', 'profile', 'board-topology', 'bench-topology', 'probe', 'output'):
        parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--preflight-only', action='store_true')
    args = parser.parse_args()
    try:
        if args.preflight_only:
            preflight(args, with_probe=False)
            print('BOARD1_PREFLIGHT_OK=true')
        else:
            run(args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f'BOARD1_ERROR={exc}\n')


if __name__ == '__main__':
    main()
