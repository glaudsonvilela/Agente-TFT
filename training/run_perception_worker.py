"""Explicit one-shot A1.6 queue pump. Empty queue means zero native executions."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sqlite3
from training.perception_work_source import publish
from training.perception_worker import Worker


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('registry','coordinator','evidence-root','probe','profile','output'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    try:
        root=a.evidence_root.resolve(strict=True);out=a.output.absolute()
        if not out.parent.resolve(strict=True).is_relative_to(root) or out.exists() or out.is_symlink():
            raise ValueError('output must be new and inside the evidence root')
        with Worker(a.registry,a.coordinator,root,a.probe,a.profile) as worker:
            summary=worker.drain()
        publish(out,dict(summary=summary))
        for item in summary['results']:
            print('A16_JOB='+json.dumps(item),flush=True)
        print('A16_SUMMARY='+json.dumps(summary),flush=True)
        print('A16_REPORT='+str(out),flush=True)
    except (ValueError,OSError,KeyError,TypeError,RuntimeError,sqlite3.Error) as exc:
        p.exit(2,f'A16_ERROR={exc}\n')


if __name__=='__main__': main()
