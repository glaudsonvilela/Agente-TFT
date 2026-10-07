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
    # A container/process may die after inbox -> working. Recover those jobs
    # before polling new work. Finished/failed jobs are not requeued.
    for stale in sorted(working.glob("*.json")):
        sid=stale.stem
        if (outbox/f"{sid}.json").exists() or (failed/f"{sid}.json").exists():
            stale.unlink(missing_ok=True)
            continue
        target=inbox/stale.name
        if not target.exists():
            os.replace(stale,target)
        else:
            stale.unlink(missing_ok=True)
    runner=Path("/workspace/trainer/scripts/process_neural_job.py")
    pruner=Path("/workspace/trainer/scripts/prune_neural_storage.py")
    raw_days=float(os.environ.get("NEURAL_RAW_RETENTION_DAYS","7"))
    work_days=float(os.environ.get("NEURAL_WORK_RETENTION_DAYS","3"))
    last_prune=0.0
    while True:
        now=time.time()
        if now-last_prune>=3600:
            subprocess.run([
                sys.executable,str(pruner),
                "--data-root",str(args.data_root),
                "--raw-days",str(raw_days),
                "--work-days",str(work_days),
                "--apply",
            ],cwd="/workspace",env=os.environ.copy(),check=False)
            last_prune=now
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
