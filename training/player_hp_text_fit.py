"""HP3: paired baseline/candidate on existing HP2 PNGs and original JPEGs."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
from typing import Any

COMPARISONS = {'both_readable_equal','both_readable_disagree','baseline_only_readable',
               'candidate_only_readable','neither_readable'}
STATUSES = {'accepted','negative_display','badge_not_found','badge_ambiguous',
            'ocr_uncertain','ocr_conflict','search_budget_exceeded','read_error'}
MAX_BATCHES = 11
MAX_FRAMES = 160


def load(path: Path) -> dict:
    if path.stat().st_size > 16*1024*1024:
        raise ValueError('JSON exceeds 16 MiB')
    value = json.loads(path.read_text(encoding='utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
    if not isinstance(value, dict):
        raise ValueError('expected JSON object')
    return value


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def write(path: Path, value: Any) -> None:
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write('\n')


def contained(root: Path, name: str) -> Path:
    rel = Path(name)
    if not name or rel.is_absolute() or any(p in ('.','..') for p in rel.parts):
        raise ValueError('source path must be relative without traversal')
    result = (root/rel).resolve(strict=True)
    if not result.is_relative_to(root.resolve(strict=True)) or not result.is_file():
        raise ValueError('source file escaped its image root')
    return result


def validate_manifest(manifest: dict, root: Path, require_hash: bool) -> list[dict]:
    rows = manifest.get('frames')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 128:
        raise ValueError('expected 1..128 frames')
    out, seen, last = [], set(), -1
    for row in rows:
        at, image = row.get('timestamp_ms'), row.get('image')
        if type(at) is not int or not last < at <= 86_400_000 or not isinstance(image, str):
            raise ValueError('invalid/duplicate/out-of-order frame identity')
        path = contained(root, image)
        if path in seen:
            raise ValueError('reused image path')
        if path.stat().st_size > 32*1024*1024:
            raise ValueError('image exceeds 32 MiB')
        checksum = sha256(path)
        if require_hash and checksum != row.get('sha256'):
            raise ValueError('HP2 source image hash changed or missing')
        # Never copy labels, expectations or suggested HP into the input contract.
        out.append({'timestamp_ms': at, 'image': image, 'sha256': checksum})
        last = at
        seen.add(path)
    return out


def batches(source: Path, sparse_manifest: Path | None, sparse_root: Path | None) -> list[dict]:
    source = source.resolve(strict=True)
    if not source.is_dir():
        raise ValueError('HP2 evidence must be a directory')
    if load(source/'prepared.json').get('complete') is not True:
        raise ValueError('HP2 extraction is incomplete')
    windows = load(source/'plan.json').get('windows')
    if not isinstance(windows, list) or not 1 <= len(windows) <= 10:
        raise ValueError('require 1..10 HP2 windows')
    result, ids = [], set()
    for w in windows:
        key = w.get('id')
        if not isinstance(key,str) or not re.fullmatch(r'window-\d{2}',key) or key in ids:
            raise ValueError('invalid/duplicate window id')
        ids.add(key)
        manifest_path = contained(source, key+'/manifest.json')
        root = manifest_path.parent
        manifest = load(manifest_path)
        rows = validate_manifest(manifest,root,True)
        result.append(dict(id=key,kind='targeted_dense',root=str(root),frames=rows,
                           source_manifest=str(manifest_path),source_manifest_sha256=sha256(manifest_path)))
    if (sparse_manifest is None) != (sparse_root is None):
        raise ValueError('both sparse arguments are required together')
    if sparse_manifest is not None:
        manifest_path=sparse_manifest.resolve(strict=True)
        root=sparse_root.resolve(strict=True)
        rows=validate_manifest(load(manifest_path),root,False)
        result.append(dict(id='sparse-regression',kind='sparse_regression',root=str(root),frames=rows,
                           source_manifest=str(manifest_path),source_manifest_sha256=sha256(manifest_path)))
    if len(result)>MAX_BATCHES or sum(len(b['frames']) for b in result)>MAX_FRAMES:
        raise ValueError('HP3 batch/frame budget exceeded')
    return result


def run_child(command: list[str], events: Path, log: Path, timeout: int=120) -> None:
    # Kill the entire process group on timeout, including FFmpeg/Tesseract children.
    with events.open('xb') as stdout, log.open('xb') as stderr:
        proc=subprocess.Popen(command,stdout=stdout,stderr=stderr,start_new_session=True)
        try:
            code=proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid,signal.SIGKILL)
            proc.wait()
            raise RuntimeError('HP3 native probe timeout; process group killed') from None
        if code:
            raise RuntimeError(f'HP3 probe exited {code}; see {log}')


def verify_report(report: dict, batch: dict) -> dict:
    s, records=report.get('summary',{}),report.get('records',[])
    if s.get('execution_complete') is not True or s.get('errors') != 0:
        raise ValueError('native comparison incomplete')
    for name in ('labels_used','game_state_updated','profile_promoted','model_trained'):
        if s.get(name) is not False:
            raise ValueError('native comparison is not diagnostic-only')
    expected=[r['timestamp_ms'] for r in batch['frames']]
    if [r.get('timestamp_ms') for r in records] != expected or s.get('frames') != len(expected):
        raise ValueError('native comparison does not match source timestamps/count')
    comparisons, bs, cs = Counter(), Counter(), Counter()
    for r in records:
        b,c=r['baseline'],r['candidate']
        if any(x.get('timestamp_ms')!=r['timestamp_ms'] for x in (b,c)):
            raise ValueError('paired reader timestamp mismatch')
        if b.get('location')!=c.get('location'):
            raise ValueError('text fitting changed badge localization')
        if b.get('status') not in STATUSES or c.get('status') not in STATUSES:
            raise ValueError('unknown native status')
        def readable(x):
            return x['status'] in ('accepted','negative_display') and type(x.get('signed_hp')) is int
        rb,rc=readable(b),readable(c)
        cls=('both_readable_equal' if b['signed_hp']==c['signed_hp'] else 'both_readable_disagree') if rb and rc else (
            'baseline_only_readable' if rb else 'candidate_only_readable' if rc else 'neither_readable')
        if r.get('comparison')!=cls:
            raise ValueError('invalid paired classification')
        comparisons[cls]+=1;bs[b['status']]+=1;cs[c['status']]+=1
    if (dict(comparisons)!=s.get('comparison') or dict(bs)!=s.get('baseline_statuses')
            or dict(cs)!=s.get('candidate_statuses')):
        raise ValueError('native summary differs from records')
    return s


def run(args: argparse.Namespace) -> None:
    source=args.source.resolve(strict=True)
    out=args.output.resolve(strict=True)
    if not out.is_dir() or out==source or out.is_relative_to(source):
        raise ValueError('output must be a new directory outside the HP2 evidence')
    plan=batches(source,args.sparse_manifest,args.sparse_root)
    binary=args.probe.resolve(strict=True);profile=args.profile.resolve(strict=True)
    profile_hash=sha256(profile)
    write(out/'plan.json',dict(batches=plan,source=str(source),profile=str(profile),
        profile_sha256=profile_hash,probe_sha256=sha256(binary),labels_used=False))
    results=[]
    for b in plan:
        folder=out/b['id'];folder.mkdir()
        # Manifest contains only file identity and time. Native plan never reads labels.
        write(folder/'manifest.json',{'frames':b['frames']})
        command=[str(binary),str(folder/'manifest.json'),b['root'],str(profile),str(folder/'report.json')]
        write(folder/'command.json',command)
        print(f"HP3_RUN={b['id']} frames={len(b['frames'])}",flush=True)
        run_child(command,folder/'events.jsonl',folder/'probe.stderr')
        validate_manifest({'frames':b['frames']},Path(b['root']),True)
        if sha256(profile)!=profile_hash or sha256(Path(b['source_manifest']))!=b['source_manifest_sha256']:
            raise ValueError('source manifest/profile changed during comparison')
        report=load(folder/'report.json');s=verify_report(report,b)
        item={'id':b['id'],'kind':b['kind'],**s}
        results.append(item)
        print('HP3_BATCH='+json.dumps(item),flush=True)
        for r in report['records']:
            if r['comparison']=='both_readable_disagree':
                print('HP3_DISAGREEMENT='+json.dumps({'batch':b['id'],'timestamp_ms':r['timestamp_ms'],
                    'baseline':r['baseline']['signed_hp'],'candidate':r['candidate']['signed_hp'],
                    'text_fit':r['text_fit']}),flush=True)
    groups={}
    for kind in ('targeted_dense','sparse_regression'):
        selected=[r for r in results if r['kind']==kind]
        if not selected:continue
        bsum,csum,comp=Counter(),Counter(),Counter()
        for r in selected:
            bsum.update(r['baseline_statuses']);csum.update(r['candidate_statuses']);comp.update(r['comparison'])
        groups[kind]={'frames':sum(r['frames'] for r in selected),'baseline_statuses':dict(bsum),
            'candidate_statuses':dict(csum),'comparison':dict(comp),
            'baseline_confirmed_frames':sum(r['baseline_confirmed_frames'] for r in selected),
            'candidate_confirmed_frames':sum(r['candidate_confirmed_frames'] for r in selected)}
    summary={'schema_version':1,'batches':len(results),'groups':groups,'execution_complete':True,
        'labels_used':False,'exact_accuracy':None,'game_state_updated':False,'profile_promoted':False,'model_trained':False,
        'metric_kind':'paired_text_fit_diagnostics','warning':'candidate-only is not correctness; dense and sparse groups remain separate'}
    write(out/'report.json',{'summary':summary,'batches':results})
    print('HP3_SUMMARY='+json.dumps(summary),flush=True)
    print('HP3_REPORT='+str(out/'report.json'),flush=True)


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','probe','profile'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--sparse-manifest',type=Path)
    p.add_argument('--sparse-root',type=Path)
    run(p.parse_args())

if __name__=='__main__':
    main()
