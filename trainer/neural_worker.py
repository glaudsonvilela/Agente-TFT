#!/usr/bin/env python3
"""Durable filesystem neural worker for BigBANANA."""
from __future__ import annotations
import argparse,os,subprocess,sys,time
from pathlib import Path

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--data-root",type=Path,default=Path("/var/lib/agente-tft-trainer"))
    p.add_argument("--poll-seconds",type=float,default=2.0)
    args=p.parse_args()
    root=args.data_root/"neural-jobs"; inbox=root/"inbox"; working=root/"working"; outbox=root/"outbox"; failed=root/"failed"
    for d in (inbox,working,outbox,failed):d.mkdir(parents=True,exist_ok=True)
    runner=Path("/workspace/trainer/scripts/process_neural_job.py")
    while True:
        jobs=sorted(inbox.glob("*.json"),key=lambda x:x.stat().st_mtime)
        if not jobs:
            time.sleep(args.poll_seconds);continue
        source=jobs[0]; target=working/source.name
        try: os.replace(source,target)
        except FileNotFoundError: continue
        sid=target.stem
        proc=subprocess.run([
            sys.executable,str(runner),"--job",str(target),"--data-root",str(args.data_root),
            "--outbox",str(outbox),"--failed",str(failed)
        ],cwd="/workspace",env=os.environ.copy())
        target.unlink(missing_ok=True)
        if proc.returncode!=0:
            time.sleep(1)

if __name__=="__main__":main()
