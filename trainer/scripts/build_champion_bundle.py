#!/usr/bin/env python3
"""Build one sealed runtime champion bundle for BigBANANA publication.

A stable bundle is full enough for the installed runtime to activate atomically:
L3 is always present; item/unit neural components are optional overlays.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile


def die(message: str) -> "NoReturn":
    raise SystemExit(f"CHAMPION_BUNDLE_ERROR: {message}")


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def copy_file(src: Path,dst: Path):
    if not src.is_file():die(f"missing file: {src}")
    dst.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(src,dst)


def add(rows:list[dict],root:Path,path:str,role:str):
    p=root/path
    if not p.is_file():die(f"bundle file missing: {path}")
    rows.append({"path":path,"sha256":sha256(p),"bytes":p.stat().st_size,"role":role})


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--version",required=True)
    p.add_argument("--generation",type=int,required=True)
    p.add_argument("--runtime-min-version",default="0.7.0")
    p.add_argument("--l3-metadata",type=Path,required=True)
    p.add_argument("--l3-onnx",type=Path,required=True)
    p.add_argument("--unit-head",type=Path)
    p.add_argument("--unit-encoder",type=Path)
    p.add_argument("--unit-reference",type=Path)
    p.add_argument("--unit-set-key")
    p.add_argument("--unit-min-probability",type=float)
    p.add_argument("--unit-min-margin",type=float)
    p.add_argument("--item-plan",type=Path)
    p.add_argument("--item-dir",type=Path)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--publish-request",type=Path)
    p.add_argument("--channel",choices=("stable","shadow"),default="stable")
    args=p.parse_args()

    if args.generation<1:die("generation must be positive")
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for ch in args.version):
        die("unsafe version")
    if args.output.exists():die("new output path required")
    unit_values=(args.unit_head,args.unit_encoder,args.unit_reference,args.unit_set_key,
                 args.unit_min_probability,args.unit_min_margin)
    if any(v is not None for v in unit_values) and not all(v is not None for v in unit_values):
        die("unit-head publication requires head, encoder, reference, set-key and both gates")
    if args.unit_min_probability is not None and not 0<=args.unit_min_probability<=1:die("unit probability gate")
    if args.unit_min_margin is not None and not 0<=args.unit_min_margin<=1:die("unit margin gate")
    if (args.item_plan is None)!=(args.item_dir is None):die("item overlay requires plan and directory")

    with tempfile.TemporaryDirectory(prefix="tft-champion-") as td:
        root=Path(td)
        copy_file(args.l3_metadata,root/"models/deployment-candidate.json")
        copy_file(args.l3_onnx,root/"models/candidate-model.onnx")
        l3_meta=json.loads((root/"models/deployment-candidate.json").read_text(encoding="utf-8"))
        l3_sha=sha256(root/"models/candidate-model.onnx")
        if (l3_meta.get("schema_version")!=2 or l3_meta.get("sha256")!=l3_sha
                or l3_meta.get("activation_allowed") is not False or not l3_meta.get("validated")):
            die("L3 model is not a sealed validated runtime candidate")

        rows=[]
        add(rows,root,"models/deployment-candidate.json","l3_metadata")
        add(rows,root,"models/candidate-model.onnx","l3_onnx")

        if args.unit_head:
            reference=json.loads(args.unit_reference.read_text(encoding="utf-8"))
            reference_sha=reference.get("reference_sha256")
            if not isinstance(reference_sha,str) or len(reference_sha)!=64:die("unit reference sha")
            copy_file(args.unit_head,root/"models/unit-head/dino-head.json")
            copy_file(args.unit_encoder,root/"models/unit-head/encoder.onnx")
            head=json.loads((root/"models/unit-head/dino-head.json").read_text(encoding="utf-8"))
            encoder_sha=sha256(root/"models/unit-head/encoder.onnx")
            if (head.get("schema_version")!=1 or head.get("feature_mode")!="dino"
                    or head.get("crop_transform")!="upper_88x80_v1"
                    or head.get("encoder_sha256")!=encoder_sha):
                die("unit head/encoder contract mismatch")
            plan={
                "schema_version":1,"kind":"dino_softmax_unit_classifier",
                "set_key":args.unit_set_key,"reference_sha256":reference_sha,
                "mode":"diagnostic_candidates",
                "min_probability":args.unit_min_probability,
                "min_margin":args.unit_min_margin,
                "files":{
                    "encoder.onnx":encoder_sha,
                    "dino-head.json":sha256(root/"models/unit-head/dino-head.json"),
                },
            }
            plan_path=root/"configs/catalog/active-unit-head-v1.json"
            plan_path.parent.mkdir(parents=True,exist_ok=True)
            plan_path.write_text(json.dumps(plan,indent=2,sort_keys=True)+"\n",encoding="utf-8")
            add(rows,root,"models/unit-head/dino-head.json","unit_head_json")
            add(rows,root,"models/unit-head/encoder.onnx","unit_encoder_onnx")
            add(rows,root,"configs/catalog/active-unit-head-v1.json","unit_head_plan")

        if args.item_plan:
            plan=json.loads(args.item_plan.read_text(encoding="utf-8"))
            files=plan.get("files")
            if not isinstance(files,dict) or set(files)!={"item-icons.onnx","metadata.json"}:
                die("item plan contract")
            copy_file(args.item_plan,root/"configs/catalog/active-item-neural-v1.json")
            for name in files:
                copy_file(args.item_dir/name,root/"models/item-icons"/name)
                if sha256(root/"models/item-icons"/name)!=files[name]:die("item checksum mismatch")
            add(rows,root,"configs/catalog/active-item-neural-v1.json","item_plan")
            add(rows,root,"models/item-icons/item-icons.onnx","item_onnx")
            add(rows,root,"models/item-icons/metadata.json","item_metadata")

        manifest={
            "schema_version":1,
            "package_type":"agente_tft_neural_runtime_bundle",
            "version":args.version,
            "generation":args.generation,
            "runtime_min_version":args.runtime_min_version,
            "model_identity_sha256":l3_sha,
            "files":rows,
        }
        (root/"model-package.json").write_text(
            json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8")

        args.output.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(args.output,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            for file in sorted(root.rglob("*")):
                if file.is_file():z.write(file,file.relative_to(root).as_posix())

    request={
        "channel":args.channel,"version":args.version,"generation":args.generation,
        "staged_filename":args.output.name,
        "runtime_min_version":args.runtime_min_version,
        "model_identity_sha256":l3_sha,
        "training_provenance":{"builder":"build_champion_bundle_v1"},
    }
    request_path=args.publish_request or args.output.with_suffix(".publish.json")
    request_path.write_text(json.dumps(request,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("CHAMPION_BUNDLE_OK=true")
    print(f"OUTPUT={args.output}")
    print(f"PACKAGE_SHA256={sha256(args.output)}")
    print(f"MODEL_IDENTITY_SHA256={l3_sha}")
    print(f"PUBLISH_REQUEST={request_path}")

if __name__=="__main__":main()
