#!/usr/bin/env python3
"""Process one sealed neural-learning job entirely on BigBANANA."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def die(message: str) -> "NoReturn":
    raise SystemExit(f"SERVER_NEURAL_JOB_ERROR: {message}")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    os.replace(tmp,path)


def build_session(job: dict, data_root: Path, workspace: Path) -> Path:
    session_id=job["neural_session_id"]
    evidence=Path(job["evidence_root"]).resolve()
    allowed=(data_root/"neural-evidence").resolve()
    if not evidence.is_relative_to(allowed) or evidence.name!=session_id:
        die("evidence path outside neural-evidence root")
    seal=evidence/"seal.json"
    frames_dir=evidence/"frames"
    if not seal.is_file() or not frames_dir.is_dir():
        die("sealed evidence incomplete")

    meta_files=sorted(frames_dir.glob("*.json"))
    if len(meta_files)<2 or len(meta_files)>10000:
        die("evidence frame count outside bounds")
    rows=[]
    for meta_path in meta_files:
        meta=load_json(meta_path)
        if meta.get("neural_session_id")!=session_id:
            die("frame metadata session mismatch")
        frame_id=meta.get("frame_id");source_ms=meta.get("source_ms")
        if not isinstance(frame_id,int) or not isinstance(source_ms,int):
            die("invalid frame metadata")
        stem=meta_path.stem
        image=next((frames_dir/(stem+ext) for ext in (".jpg",".png") if (frames_dir/(stem+ext)).is_file()),None)
        if image is None or sha256(image)!=meta.get("image_sha256"):
            die("evidence frame checksum mismatch")
        rows.append((source_ms,frame_id,image,meta))
    rows.sort(key=lambda x:(x[0],x[1]))
    if any(rows[i][0]>=rows[i+1][0] for i in range(len(rows)-1)):
        die("source timestamps must be strictly increasing")

    session=workspace/"session"
    target_frames=session/"shadow-learning"/"frames"
    target_frames.mkdir(parents=True,exist_ok=False)
    manifest_rows=[]
    from PIL import Image
    for index,(source_ms,frame_id,image,meta) in enumerate(rows):
        target=target_frames/f"{index:06d}.jpg"
        with Image.open(image) as im:
            rgb=im.convert("RGB")
            if rgb.size!=(1920,1080):
                die("server evidence must be canonical 1920x1080")
            rgb.save(target,format="JPEG",quality=95,subsampling=0,optimize=False)
        manifest_rows.append({
            "index":index,"frame_id":frame_id,"source_ms":source_ms,
            "width":1920,"height":1080,"image":f"frames/{index:06d}.jpg",
            "image_sha256":sha256(target),"capture_role":"post_session_learning_evidence",
            "ground_truth":False,"training_label":None,"model_prediction_used_as_label":False,
        })

    manifest={
        "schema_version":1,
        "policy":"server_reconstructed_shadow_learning_capture_v1",
        "session_id":session_id,
        "source":{"source_kind":"remote_sealed_match"},
        "runtime_model_sha256":None,
        "interval_ms":None,
        "frames":manifest_rows,
        "counts":{"saved":len(manifest_rows)},
        "encoded_bytes":sum((target_frames/f"{i:06d}.jpg").stat().st_size for i in range(len(manifest_rows))),
        "learning_geometry":"canonical_1920x1080_rgb_jpeg_v1",
        "active_model_changed_during_session":False,
        "training_performed_during_session":False,
        "human_review_required":False,
        "runtime_approved":False,
    }
    manifest_path=session/"shadow-learning"/"capture-manifest.json"
    atomic_json(manifest_path,manifest)
    manifest_sha=sha256(manifest_path)
    atomic_json(session/"shadow-learning"/"SEALED.json",{
        "schema_version":1,"manifest_sha256":manifest_sha,
        "frames":len(manifest_rows),"encoded_bytes":manifest["encoded_bytes"],
        "ready_for_post_session_learning":True,"training_performed":False,
        "active_model_changed_during_session":False,
    })
    seal_doc=load_json(seal)
    atomic_json(session/"summary.json",{
        "execution_complete":True,"session_id":session_id,
        "active_model_changed_during_session":False,
        "stopped_by_match_end":True,
        "match_end_reason":seal_doc.get("match_end_reason","remote_seal"),
        "source":{"source_kind":"remote_sealed_match"},
    })
    atomic_json(session/"COMPLETE.json",{"server_reconstructed":True})
    return session


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--job",type=Path,required=True)
    p.add_argument("--data-root",type=Path,default=Path("/var/lib/agente-tft-trainer"))
    p.add_argument("--repo",type=Path,default=Path("/workspace"))
    p.add_argument("--selection",type=Path,default=Path("/opt/agente-tft/learner/selection.json"))
    p.add_argument("--outbox",type=Path,required=True)
    p.add_argument("--failed",type=Path,required=True)
    args=p.parse_args()

    job=load_json(args.job)
    if job.get("schema_version")!=1 or not isinstance(job.get("neural_session_id"),str):
        die("invalid job")
    sid=job["neural_session_id"]
    work=args.data_root/"neural-work"/sid
    if work.exists(): shutil.rmtree(work)
    work.mkdir(parents=True)
    try:
        session=build_session(job,args.data_root,work)
        env=os.environ.copy()
        env.setdefault("AGENTE_TFT_UNIT_LAB_BIN_DIR","/opt/agente-bin")
        env.setdefault("OMP_THREAD_LIMIT","1")
        env.setdefault("OPENBLAS_NUM_THREADS","1")
        log=work/"pipeline.log"
        with log.open("w",encoding="utf-8") as handle:
            proc=subprocess.run([
                sys.executable,str(args.repo/"scripts/run_post_session_shadow_learning.py"),
                "--repo",str(args.repo),"--selection",str(args.selection),
                "--session",str(session),
            ],cwd=args.repo,env=env,stdout=handle,stderr=subprocess.STDOUT,text=True)
        if proc.returncode!=0:
            die(f"post-session pipeline failed:{proc.returncode}")

        state=load_json(session/"shadow-learning"/"post-session-v1"/"state.json")
        selection=load_json(args.selection)
        result={
            "schema_version":1,"neural_session_id":sid,
            "outcome":state.get("outcome"),
            "champion_model_sha256":selection.get("selected_model_sha256"),
            "shadow_candidate_sha256":None,
            "challenger_selected":False,
            "training_location":"BigBANANA",
            "client_compute_required":False,
        }
        candidate=session/"shadow-learning"/"post-session-v1"/"shadow-candidate.json"
        if candidate.is_file():
            doc=load_json(candidate)
            result["shadow_candidate_sha256"]=doc.get("model_sha256")
            result["challenger_selected"]=True
            result["shadow_candidate_path"]=doc.get("model_path")
        atomic_json(args.outbox/f"{sid}.json",result)
        print("SERVER_NEURAL_JOB_OK=true")
    except Exception as exc:
        atomic_json(args.failed/f"{sid}.json",{
            "schema_version":1,"neural_session_id":sid,
            "error":f"{type(exc).__name__}:{str(exc)[:500]}",
        })
        raise


if __name__=="__main__":
    main()
