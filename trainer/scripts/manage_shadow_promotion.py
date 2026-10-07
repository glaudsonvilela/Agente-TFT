#!/usr/bin/env python3
"""Autonomous shadow-candidate registry and stable-promotion gate.

Promotion policy v1:
- candidate must have won frozen validation before registration;
- runtime acceptance gates must be calibration-eligible with zero validation
  wrong accepts;
- evaluation uses only later independent sessions with supported direct gold;
- at least 3 independent evaluation sessions and 6 direct-gold anchors;
- candidate may not be worse than its champion on any evaluation session;
- cumulative candidate top1 must be strictly better than champion;
- runtime-gated candidate may have zero wrong accepts;
- the candidate baseline SHA must still equal the current central champion SHA.

No human approval is used.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from trainer.remote_trainer.champion_registry import ChampionRegistry


def die(message: str) -> "NoReturn":
    raise SystemExit(f"SHADOW_PROMOTION_ERROR: {message}")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def atomic(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    os.replace(tmp,path)


def run(command:list[str],cwd:Path):
    subprocess.run(command,cwd=cwd,check=True)


def register_candidate(
    *,
    data_root:Path,
    repo:Path,
    central_selection:Path,
    challenger_selection:Path,
    training_session:str,
) -> Path|None:
    selection=load(challenger_selection)
    if selection.get("selected_arm")!="weighted-autonomous":
        return None
    challenger=selection.get("challenger") or {}
    model=Path(str(challenger.get("model",""))).resolve()
    report=Path(str(challenger.get("report",""))).resolve()
    if not model.is_file() or not report.is_file():die("selected challenger artifacts missing")
    candidate_sha=str(challenger.get("model_sha256") or "")
    if len(candidate_sha)!=64:die("selected challenger sha missing")
    current=load(central_selection)
    baseline=selection.get("baseline") or {}
    if baseline.get("model_sha256")!=current.get("selected_model_sha256"):
        die("challenger baseline is not current central champion")

    root=data_root/"neural-candidates"/candidate_sha
    meta_path=root/"candidate.json"
    if meta_path.is_file():
        return root
    root.mkdir(parents=True)
    shutil.copy2(model,root/"dino-head.json")
    shutil.copy2(report,root/"training-report.json")

    gates=root/"runtime-gates.json"
    run([
        sys.executable,str(repo/"trainer/scripts/calibrate_unit_head_runtime_gates.py"),
        "--report",str(root/"training-report.json"),"--output",str(gates),
    ],repo)
    calibration=load(gates)
    eligible=calibration.get("runtime_gate_eligible") is True
    metadata={
        "schema_version":1,
        "policy":"central_shadow_promotion_v1",
        "status":"shadow" if eligible else "rejected_runtime_gate",
        "candidate_sha256":candidate_sha,
        "training_session":training_session,
        "baseline_model_sha256":baseline.get("model_sha256"),
        "baseline_arm":baseline.get("arm"),
        "validation":challenger.get("validation"),
        "runtime_gates":calibration,
        "evaluations":[],
        "promotion_policy":{
            "min_independent_sessions":3,
            "min_direct_gold_anchors":6,
            "per_session_not_worse":True,
            "cumulative_strictly_better":True,
            "wrong_accepted_max":0,
        },
        "human_review_required":False,
    }
    atomic(meta_path,metadata)
    return root


def evaluate_candidates(
    *,
    data_root:Path,
    repo:Path,
    central_selection:Path,
    evaluation_session:str,
    collection:Path|None,
    gold:Path|None,
):
    if collection is None or gold is None or not collection.is_dir() or not gold.is_file():
        return
    gold_rows=load(gold)
    if not isinstance(gold_rows,list) or not gold_rows:
        return

    current=load(central_selection)
    champion_model=Path(str(current.get("selected_model_path",""))).resolve()
    champion_sha=current.get("selected_model_sha256")
    run_meta=load(central_selection.parent/"run-metadata.json")
    encoder=Path(str(run_meta.get("encoder",""))).resolve()
    if not champion_model.is_file() or not encoder.is_file():die("central champion/encoder missing")

    candidates=data_root/"neural-candidates"
    if not candidates.is_dir():return
    for root in sorted(candidates.iterdir()):
        meta_path=root/"candidate.json"
        if not meta_path.is_file():continue
        meta=load(meta_path)
        if meta.get("status")!="shadow":continue
        if meta.get("training_session")==evaluation_session:continue
        if meta.get("baseline_model_sha256")!=champion_sha:
            meta["status"]="superseded_by_new_champion"
            atomic(meta_path,meta);continue
        if any(e.get("evaluation_session")==evaluation_session for e in meta.get("evaluations",[])):
            continue
        out=root/"evaluations"/f"{evaluation_session}.json"
        out.parent.mkdir(parents=True,exist_ok=True)
        run([
            sys.executable,str(repo/"trainer/scripts/evaluate_shadow_candidate_gold.py"),
            "--candidate",str(root/"dino-head.json"),
            "--champion",str(champion_model),
            "--encoder",str(encoder),
            "--gates",str(root/"runtime-gates.json"),
            "--collection",str(collection),"--gold",str(gold),
            "--candidate-training-session",str(meta["training_session"]),
            "--evaluation-session",evaluation_session,
            "--output",str(out),
        ],repo)
        result=load(out)
        meta.setdefault("evaluations",[]).append(result)
        atomic(meta_path,meta)


def gate(meta:dict)->bool:
    rows=meta.get("evaluations") or []
    sessions={r.get("evaluation_session") for r in rows if isinstance(r,dict)}
    total=sum(int(r.get("gold_anchors",0)) for r in rows)
    candidate=sum(int(r.get("candidate_correct",0)) for r in rows)
    champion=sum(int(r.get("champion_correct",0)) for r in rows)
    wrong=sum(int(r.get("candidate_wrong_accepted",0)) for r in rows)
    return (
        len(sessions)>=3 and total>=6 and wrong==0
        and all(r.get("candidate_not_worse") is True for r in rows)
        and candidate>champion
    )


def promote_one(*,data_root:Path,repo:Path,central_selection:Path)->dict|None:
    current=load(central_selection)
    current_sha=current.get("selected_model_sha256")
    candidates_root=data_root/"neural-candidates"
    if not candidates_root.is_dir():return None
    eligible=[]
    for root in candidates_root.iterdir():
        meta_path=root/"candidate.json"
        if not meta_path.is_file():continue
        meta=load(meta_path)
        if (meta.get("status")=="shadow"
                and meta.get("baseline_model_sha256")==current_sha
                and gate(meta)):
            rows=meta["evaluations"]
            delta=sum(r["candidate_correct"]-r["champion_correct"] for r in rows)
            anchors=sum(r["gold_anchors"] for r in rows)
            eligible.append((delta,anchors,meta.get("candidate_sha256",""),root,meta))
    if not eligible:return None
    eligible.sort(key=lambda x:(-x[0],-x[1],x[2]))
    _,_,candidate_sha,candidate_root,meta=eligible[0]

    registry=ChampionRegistry(data_root)
    stable=registry.latest("stable")
    if stable is None:
        meta["promotion_blocked"]="initial_stable_champion_not_seeded"
        atomic(candidate_root/"candidate.json",meta)
        return None
    _,stable_zip=registry.package_for("stable",stable.generation)
    next_generation=stable.generation+1
    version=f"g{next_generation:06d}-unit-{candidate_sha[:12]}"

    run_meta=load(central_selection.parent/"run-metadata.json")
    encoder=Path(str(run_meta.get("encoder",""))).resolve()
    if not encoder.is_file():die("central encoder missing")
    visual=load(repo/"configs/catalog/active-visual-reference-v1.json")
    reference=repo/visual["reference"]/"reference.json"
    gates=load(candidate_root/"runtime-gates.json")

    with tempfile.TemporaryDirectory(prefix="tft-promote-") as td:
        extracted=Path(td)/"stable"
        extracted.mkdir()
        with zipfile.ZipFile(stable_zip) as archive:
            archive.extractall(extracted)
        l3_meta=extracted/"models/deployment-candidate.json"
        l3_onnx=extracted/"models/candidate-model.onnx"
        if not l3_meta.is_file() or not l3_onnx.is_file():die("stable L3 bundle incomplete")

        output=registry.staging/f"{version}.zip"
        publish=registry.staging/f"{version}.publish.json"
        command=[
            sys.executable,str(repo/"trainer/scripts/build_champion_bundle.py"),
            "--version",version,"--generation",str(next_generation),
            "--runtime-min-version","0.7.0",
            "--l3-metadata",str(l3_meta),"--l3-onnx",str(l3_onnx),
            "--unit-head",str(candidate_root/"dino-head.json"),
            "--unit-encoder",str(encoder),
            "--unit-reference",str(reference),
            "--unit-set-key",str(visual["set_key"]),
            "--unit-min-probability",str(gates["min_probability"]),
            "--unit-min-margin",str(gates["min_margin"]),
            "--output",str(output),"--publish-request",str(publish),
            "--channel","stable",
        ]
        item_plan=extracted/"configs/catalog/active-item-neural-v1.json"
        item_dir=extracted/"models/item-icons"
        if item_plan.is_file() and item_dir.is_dir():
            command.extend(["--item-plan",str(item_plan),"--item-dir",str(item_dir)])
        run(command,repo)
        from trainer.remote_trainer.schemas import ChampionPublishRequest
        request=ChampionPublishRequest.model_validate(load(publish))
        published=registry.publish(request,int(__import__("time").time()*1000))

    # The promoted head becomes the baseline for the next autonomous challenger.
    new_selection={
        **current,
        "status":"central_stable_champion",
        "selected_arm":f"central-stable-g{published.generation}",
        "selected_model_path":str((candidate_root/"dino-head.json").resolve()),
        "selected_model_sha256":candidate_sha,
        "selected_metrics":meta.get("validation") or {},
        "central_stable_generation":published.generation,
        "runtime_bundle_generation":published.generation,
        "promotion_policy":"central_shadow_promotion_v1",
    }
    atomic(central_selection,new_selection)
    meta["status"]="promoted_stable"
    meta["stable_generation"]=published.generation
    meta["stable_version"]=published.version
    atomic(candidate_root/"candidate.json",meta)

    for root in candidates_root.iterdir():
        other=root/"candidate.json"
        if not other.is_file() or root==candidate_root:continue
        value=load(other)
        if value.get("status")=="shadow" and value.get("baseline_model_sha256")==current_sha:
            value["status"]="superseded_by_new_champion"
            atomic(other,value)

    return {"generation":published.generation,"version":published.version,
            "candidate_sha256":candidate_sha}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root",type=Path,required=True)
    p.add_argument("--repo",type=Path,default=ROOT)
    p.add_argument("--central-selection",type=Path,required=True)
    p.add_argument("--evaluation-session",required=True)
    p.add_argument("--collection",type=Path)
    p.add_argument("--gold",type=Path)
    p.add_argument("--new-challenger-selection",type=Path)
    p.add_argument("--new-candidate-training-session")
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()

    registered=None
    if args.new_challenger_selection and args.new_challenger_selection.is_file():
        registered=register_candidate(
            data_root=args.data_root,repo=args.repo,
            central_selection=args.central_selection,
            challenger_selection=args.new_challenger_selection,
            training_session=args.new_candidate_training_session or args.evaluation_session,
        )
    evaluate_candidates(
        data_root=args.data_root,repo=args.repo,central_selection=args.central_selection,
        evaluation_session=args.evaluation_session,collection=args.collection,gold=args.gold,
    )
    promoted=promote_one(
        data_root=args.data_root,repo=args.repo,central_selection=args.central_selection,
    )
    result={
        "schema_version":1,"policy":"central_shadow_promotion_v1",
        "evaluation_session":args.evaluation_session,
        "registered_candidate":str(registered) if registered else None,
        "promoted":promoted,
        "human_review_required":False,
    }
    atomic(args.output,result)
    print("SHADOW_PROMOTION_MANAGER_OK=true")
    print("PROMOTED="+("true" if promoted else "false"))

if __name__=="__main__":main()
