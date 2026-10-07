#!/usr/bin/env python3
"""Seed BigBANANA stable generation 1 from the currently shipped runtime model."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from trainer.remote_trainer.champion_registry import ChampionRegistry
from trainer.remote_trainer.schemas import ChampionPublishRequest


def die(message:str)->"NoReturn":
    raise SystemExit(f"SEED_CHAMPION_ERROR: {message}")


def load(path:Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root",type=Path,default=Path("/var/lib/agente-tft-trainer"))
    p.add_argument("--repo",type=Path,default=ROOT)
    p.add_argument("--seed-root",type=Path,default=Path("/opt/agente-tft/runtime-seed"))
    p.add_argument("--learner-root",type=Path,default=Path("/opt/agente-tft/learner"))
    args=p.parse_args()

    registry=ChampionRegistry(args.data_root)
    current=registry.latest("stable")
    if current is not None:
        print(f"SEED_CHAMPION_RESUME=generation:{current.generation}")
        return 0

    l3=args.seed_root/"models/deployment-candidate.json"
    onnx=args.seed_root/"models/candidate-model.onnx"
    if not l3.is_file() or not onnx.is_file():
        die("runtime seed L3 files missing")
    meta=load(l3)
    identity=meta.get("sha256")
    if not isinstance(identity,str) or len(identity)!=64:
        die("seed L3 identity missing")

    version="g000001-bootstrap"
    output=registry.staging/f"{version}.zip"
    publish=registry.staging/f"{version}.publish.json"
    cmd=[
        sys.executable,str(args.repo/"trainer/scripts/build_champion_bundle.py"),
        "--version",version,"--generation","1",
        "--runtime-min-version","0.7.0",
        "--l3-metadata",str(l3),"--l3-onnx",str(onnx),
        "--output",str(output),"--publish-request",str(publish),
        "--channel","stable",
    ]
    item_plan=args.seed_root/"configs/catalog/active-item-neural-v1.json"
    item_dir=args.seed_root/"models/item-icons"
    if item_plan.is_file() and item_dir.is_dir():
        cmd.extend(["--item-plan",str(item_plan),"--item-dir",str(item_dir)])

    unit_head=args.learner_root/"model/dino-head.json"
    unit_encoder=args.learner_root/"encoder/dino.onnx"
    unit_reference=args.learner_root/"reference/reference.json"
    unit_gates=args.learner_root/"model/runtime-gates.json"
    for required in (unit_head,unit_encoder,unit_reference,unit_gates):
        if not required.is_file():
            die(f"initial unit-head artifact missing: {required}")
    reference=load(unit_reference)
    gates=load(unit_gates)
    set_key=reference.get("set_key")
    if (not isinstance(set_key,str) or not set_key
            or gates.get("runtime_gate_eligible") is not True):
        die("initial unit-head reference/gates invalid")
    cmd.extend([
        "--unit-head",str(unit_head),
        "--unit-encoder",str(unit_encoder),
        "--unit-reference",str(unit_reference),
        "--unit-set-key",set_key,
        "--unit-min-probability",str(gates["min_probability"]),
        "--unit-min-margin",str(gates["min_margin"]),
    ])
    subprocess.run(cmd,cwd=args.repo,check=True)

    request=ChampionPublishRequest.model_validate(load(publish))
    request.training_provenance.update({
        "kind":"initial_shipped_runtime_seed",
        "autonomous_training":False,
        "generation_zero_preexisting_runtime":True,
        "initial_unit_head":"optimizer-default-parity",
        "initial_unit_head_runtime_gate":"validation_zero_error_max_coverage_v1",
    })
    manifest=registry.publish(request,int(time.time()*1000))
    print("SEED_CHAMPION_OK=true")
    print(f"GENERATION={manifest.generation}")
    print(f"VERSION={manifest.version}")
    print(f"PACKAGE_SHA256={manifest.package_sha256}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
