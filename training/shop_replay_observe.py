"""Shop observations with independent UI and seasonal bindings.

Reads local images. No prelabels, latest catalog, inferred season, GameState,
worker queue or active profile mutation. S2 is an explicit recovery-profile opt-in.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess

from ingestion.knowledge_release import bind_names, canonical, load, read_release, require


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify_sources(fingerprints: dict[str, str]) -> None:
    require(all(sha(Path(p)) == h for p, h in fingerprints.items()),
            'input changed during shop probe')


def prepare(manifest: Path, image_root: Path) -> dict:
    source, _ = load(manifest)
    root = image_root.resolve(strict=True)
    rows = source.get('frames')
    require(isinstance(rows, list) and 1 <= len(rows) <= 128, 'require 1..128 source frames')
    result, paths, last = [], set(), -1
    for row in rows:
        at, image = row.get('timestamp_ms'), row.get('image')
        require(type(at) is int and last < at <= 86_400_000,
                'timestamps must be unique and increasing')
        require(isinstance(image, str) and not Path(image).is_absolute()
                and '..' not in Path(image).parts, 'unsafe image path')
        path = (root / image).resolve(strict=True)
        require(path.is_relative_to(root) and path.is_file() and path not in paths,
                'invalid/duplicate image')
        require(path.stat().st_size <= 32 * 1024 * 1024, 'image byte budget exceeded')
        result.append(dict(timestamp_ms=at, image=image, sha256=sha(path)))
        paths.add(path)
        last = at
    return dict(frames=result, labels_used=False)


def freeze_binding(context_path: Path, release_dir: Path, layout: dict) -> tuple[dict, str, dict]:
    """Validate an explicit seasonal binding before any expensive OCR work."""
    folder = release_dir.resolve(strict=True)
    context_path = context_path.resolve(strict=True)
    context, context_hash = load(context_path)
    manifest, _ = read_release(folder)
    release_id = manifest['release_sha256']
    require(context.get('knowledge_release') in (None, release_id),
            'recording release content pin mismatch')
    probe = dict(summary=dict(locale=layout['locale'], layout_id=layout['id'], capabilities={}), records=[])
    checked = bind_names(probe, context, folder)
    require(checked['summary']['knowledge_release'] == release_id,
            'release changed during binding preflight')
    fingerprints = {str(context_path): context_hash}
    for name in ('release.json', 'units.json', 'items.json', 'traits.json'):
        path = folder / name
        require(path.is_file() and not path.is_symlink(), 'unsafe release file')
        fingerprints[str(path)] = sha(path)
    verify_sources(fingerprints)
    return context, release_id, fingerprints


def run(args: argparse.Namespace) -> dict:
    root = args.image_root.resolve(strict=True)
    layout, _ = load(args.layout)
    manifest = prepare(args.manifest, root)
    require((args.release is None) == (args.context is None),
            'release and recording context must be supplied together')
    recovery_path = getattr(args, 'recovery_profile', None)
    prefix = 'SHOP2' if recovery_path is not None else 'SHOP1'
    binding = None
    sources = {str(p.resolve()): sha(p) for p in (args.manifest, args.layout, args.probe)}
    sources.update({str((root / r['image']).resolve()): r['sha256'] for r in manifest['frames']})
    if recovery_path is not None:
        recovery_path = recovery_path.resolve(strict=True)
        recovery, digest = load(recovery_path)
        require(recovery.get('schema_version') == 1 and recovery.get('parent_layout_id') == layout['id'],
                'recovery profile parent UI mismatch')
        sources[str(recovery_path)] = digest
    if args.release is not None:
        context, release_id, fingerprints = freeze_binding(args.context, args.release, layout)
        sources.update(fingerprints)
        binding = (context, release_id)

    out = args.output.absolute()
    require(not out.exists(), 'output exists; no overwrite')
    out.mkdir(parents=True, exist_ok=False)
    (out / 'manifest.json').write_bytes(canonical(manifest))
    command = [str(args.probe.resolve(strict=True)), str(out / 'manifest.json'), str(root),
               str(args.layout.resolve()), str(out / 'native.json')]
    if recovery_path is not None:
        command.append(str(recovery_path))
    (out / 'command.json').write_bytes(canonical(command))
    with (out / 'events.jsonl').open('xb') as stdout, (out / 'native.stderr').open('xb') as stderr:
        child = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            rc = child.wait(timeout=240)
        except BaseException:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            raise
    require(rc == 0, f'native shop probe failed ({rc}); inspect {out}/native.stderr')
    report, _ = load(out / 'native.json')
    require(report['summary'].get('execution_complete') is True, 'incomplete native report')
    expected_profile = 'shop_text_atlas_v2_local_routing' if recovery_path else 'shop_text_atlas_v1'
    require(report['summary'].get('profile') == expected_profile, 'native reader profile mismatch')
    records = report['records']
    require(len(records) == len(manifest['frames']), 'native frame count mismatch')
    statuses = Counter()
    for frame, row in zip(manifest['frames'], records):
        read = row.get('read', {})
        require(read.get('timestamp_ms') == frame['timestamp_ms'], 'native timestamp mismatch')
        require([s['slot'] for s in read.get('slots', [])] == list(range(5)),
                'missing or duplicated shop slot')
        require((read.get('recovery') is not None) == (recovery_path is not None),
                'native recovery trace mismatch')
        for slot in read['slots']:
            statuses[slot['status']] += 1
            if slot['status'] == 'empty_observed':
                require(slot['observed_name'] is None and slot['observed_cost'] is None,
                        'empty slot has content')
    require(dict(statuses) == report['summary']['slot_statuses'], 'native summary mismatch')
    verify_sources(sources)
    if binding is not None:
        context, release_id = binding
        report = bind_names(report, context, args.release)
        require(report['summary']['knowledge_release'] == release_id,
                'release changed before final binding')
    verify_sources(sources)
    report['provenance'] = dict(input_files_sha256=sources, layout_id=layout['id'],
        review_kind='same-recording UI seed diagnostics', catalog_binding_requested=binding is not None,
        recovery_profile=str(recovery_path) if recovery_path else None)
    (out / 'report.json').write_bytes(canonical(report))
    (out / 'COMPLETE.json').write_bytes(canonical(dict(
        report_sha256=sha(out / 'report.json'), manifest_sha256=sha(out / 'manifest.json'))))
    for row in records:
        r = row['read']
        print(prefix + '_FRAME=' + json.dumps(dict(timestamp_ms=r['timestamp_ms'], panel=r['panel_status'],
            slots=[dict(slot=s['slot'], status=s['status'], name=s['observed_name'],
                        cost=s['observed_cost'], unit_id=s['unit_id']) for s in r['slots']]), ensure_ascii=False))
        if r.get('recovery'):
            print(prefix + '_TRACE=' + json.dumps(dict(timestamp_ms=r['timestamp_ms'], **r['recovery']), ensure_ascii=False))
    print(prefix + '_SUMMARY=' + json.dumps(report['summary'], ensure_ascii=False))
    print(prefix + '_REPORT=' + str(out / 'report.json'))
    return report['summary']


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('manifest', 'image-root', 'layout', 'probe', 'output'):
        p.add_argument('--' + key, type=Path, required=True)
    p.add_argument('--release', type=Path)
    p.add_argument('--context', type=Path)
    p.add_argument('--recovery-profile', type=Path)
    try:
        run(p.parse_args())
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as e:
        p.exit(2, f'SHOP_ERROR={e}\n')


if __name__ == '__main__':
    main()
