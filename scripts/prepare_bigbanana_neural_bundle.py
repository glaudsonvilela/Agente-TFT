#!/usr/bin/env python3
"""Prepare the persistent neural bundle mounted by BigBANANA worker.

Copies:
- portable frozen learning baseline;
- currently shipped L3 runtime seed;
- optional currently shipped item-neural overlay.
No client secrets are included.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys


ROOT=Path(__file__).resolve().parents[1]


def die(message:str)->"NoReturn":
    raise SystemExit(f"BIGBANANA_NEURAL_BUNDLE_ERROR: {message}")


def copy(src:Path,dst:Path):
    if not src.exists():die(f"missing source: {src}")
    dst.parent.mkdir(parents=True,exist_ok=True)
    if src.is_dir():shutil.copytree(src,dst)
    else:shutil.copy2(src,dst)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--selection",type=Path,required=True)
    p.add_argument("--l3-assets",type=Path,default=ROOT/"build/hm4-live-assets/models")
    p.add_argument("--output",type=Path,default=ROOT/"trainer/neural-bundle")
    args=p.parse_args()

    out=args.output.expanduser()
    if out.exists():die("new output directory required")
    out.mkdir(parents=True)

    learner=out/"learner"
    subprocess.run([
        sys.executable,str(ROOT/"scripts/prepare_hm45_learning_bundle.py"),
        "--selection",str(args.selection),"--output",str(learner),
    ],cwd=ROOT,check=True)
    gates=learner/"model/runtime-gates.json"
    subprocess.run([
        sys.executable,
        str(ROOT/"trainer/scripts/calibrate_unit_head_runtime_gates.py"),
        "--report",str(learner/"model/report.json"),
        "--output",str(gates),
    ],cwd=ROOT,check=True)
    gate_doc=json.loads(gates.read_text(encoding="utf-8"))
    if gate_doc.get("runtime_gate_eligible") is not True:
        die("frozen baseline has no zero-error runtime gate")

    seed=out/"runtime-seed"
    copy(args.l3_assets/"deployment-candidate.json",seed/"models/deployment-candidate.json")
    copy(args.l3_assets/"candidate-model.onnx",seed/"models/candidate-model.onnx")

    item_plan=ROOT/"configs/catalog/active-item-neural-v1.json"
    item_dir=args.l3_assets/"item-icons"
    if item_plan.is_file() and item_dir.is_dir():
        plan=json.loads(item_plan.read_text(encoding="utf-8"))
        files=plan.get("files")
        if isinstance(files,dict) and set(files)=={"item-icons.onnx","metadata.json"}:
            copy(item_plan,seed/"configs/catalog/active-item-neural-v1.json")
            for name in files:copy(item_dir/name,seed/"models/item-icons"/name)

    manifest={
        "schema_version":1,
        "kind":"bigbanana_neural_bundle_v1",
        "contains_client_secret":False,
        "learner":"learner",
        "runtime_seed":"runtime-seed",
        "initial_unit_head_gates":{
            "min_probability":gate_doc["min_probability"],
            "min_margin":gate_doc["min_margin"],
            "legacy_probability_only":gate_doc.get("legacy_probability_only",False),
        },
        "initial_champion_generation":1,
        "initial_unit_head":"optimizer-default-parity",
        "initial_unit_head_in_stable_g1":True,
        "training_location":"BigBANANA",
    }
    (out/"bundle.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("BIGBANANA_NEURAL_BUNDLE_OK=true")
    print(f"OUTPUT={out}")
    print("INITIAL_CHAMPION_GENERATION=1")

if __name__=="__main__":
    main()
