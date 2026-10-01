"""S1: paired-scale shop observations with independent UI and seasonal bindings.

Reads local images. No prelabels, latest catalog, inferred season, GameState,
worker queue or active profile mutation. The native process has a finite budget.
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

from ingestion.knowledge_release import load, bind_names, require, canonical


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def prepare(manifest, image_root):
    source,_=load(manifest)
    root=image_root.resolve(strict=True)
    rows=source.get('frames')
    require(isinstance(rows,list) and 1<=len(rows)<=128,'require 1..128 source frames')
    result=[];last=-1;paths=set()
    for row in rows:
        at=row.get('timestamp_ms');image=row.get('image')
        require(type(at) is int and last<at<=86_400_000,'timestamps must be unique and increasing')
        require(isinstance(image,str) and not Path(image).is_absolute() and '..' not in Path(image).parts,'unsafe image path')
        path=(root/image).resolve(strict=True)
        require(path.is_relative_to(root) and path.is_file() and path not in paths,'invalid/duplicate image')
        require(path.stat().st_size<=32*1024*1024,'image byte budget exceeded')
        result.append(dict(timestamp_ms=at,image=image,sha256=sha(path)))
        paths.add(path);last=at
    # Do not copy suggestions, expected values, patch claims or other labels.
    return dict(frames=result,labels_used=False)


def run(args):
    root=args.image_root.resolve(strict=True)
    layout,_=load(args.layout)
    manifest=prepare(args.manifest,root)
    out=args.output.absolute()
    require(not out.exists(),'output exists; no overwrite')
    out.mkdir(parents=True,exist_ok=False)
    sources={str(p.resolve()):sha(p) for p in (args.manifest,args.layout,args.probe)}
    sources.update({str((root/r['image']).resolve()):r['sha256'] for r in manifest['frames']})
    (out/'manifest.json').write_bytes(canonical(manifest))
    # Source paths contain no commands; binary comes from the explicit runner.
    command=[str(args.probe.resolve(strict=True)),str(out/'manifest.json'),str(root),str(args.layout.resolve()),str(out/'native.json')]
    (out/'command.json').write_bytes(canonical(command))
    with (out/'events.jsonl').open('xb') as stdout, (out/'native.stderr').open('xb') as stderr:
        child=subprocess.Popen(command,stdout=stdout,stderr=stderr,start_new_session=True)
        try:
            rc=child.wait(timeout=240)
        except BaseException:
            try: os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            child.wait()
            raise
    require(rc==0, f'native shop probe failed ({rc}); inspect {out}/native.stderr')
    report,_=load(out/'native.json')
    require(report['summary'].get('execution_complete') is True,'incomplete native report')
    records=report['records']
    require(len(records)==len(manifest['frames']),'native frame count mismatch')
    statuses=Counter()
    for frame,row in zip(manifest['frames'],records):
        read=row.get('read',{})
        require(read.get('timestamp_ms')==frame['timestamp_ms'],'native timestamp mismatch')
        require([s['slot'] for s in read.get('slots',[])]==list(range(5)),'missing or duplicated shop slot')
        for slot in read['slots']:
            statuses[slot['status']]+=1
            if slot['status']=='empty_observed':
                require(slot['observed_name'] is None and slot['observed_cost'] is None,'empty slot has content')
    require(dict(statuses)==report['summary']['slot_statuses'],'native summary mismatch')
    require(all(sha(Path(p))==h for p,h in sources.items()),'input changed during shop probe')
    if args.release is not None:
        require(args.context is not None,'release binding requires explicit recording context')
        context,_=load(args.context)
        report=bind_names(report,context,args.release)
    report['provenance']=dict(input_files_sha256=sources,layout_id=layout['id'],
        review_kind='same-recording UI seed diagnostics',catalog_binding_requested=args.release is not None)
    (out/'report.json').write_bytes(canonical(report))
    (out/'COMPLETE.json').write_bytes(canonical(dict(report_sha256=sha(out/'report.json'),manifest_sha256=sha(out/'manifest.json'))))
    for row in records:
        r=row['read']
        print('SHOP1_FRAME='+json.dumps(dict(timestamp_ms=r['timestamp_ms'],panel=r['panel_status'],
            slots=[dict(slot=s['slot'],status=s['status'],name=s['observed_name'],cost=s['observed_cost'],unit_id=s['unit_id']) for s in r['slots']]),ensure_ascii=False))
    print('SHOP1_SUMMARY='+json.dumps(report['summary'],ensure_ascii=False))
    print('SHOP1_REPORT='+str(out/'report.json'))
    return report['summary']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('manifest','image-root','layout','probe','output'):
        p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--release',type=Path)
    p.add_argument('--context',type=Path)
    try: run(p.parse_args())
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired) as e:
        p.exit(2,f'SHOP1_ERROR={e}\n')

if __name__=='__main__': main()
