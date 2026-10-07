#!/usr/bin/env python3
"""Compare one shadow candidate with the frozen champion on direct gold anchors.

The evaluation session must be different from the candidate training session.
Only supported direct game-derived gold is accepted as truth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
import onnxruntime as ort

from apps.hud_mapper.hm.unit_head import _resize_bilinear


def die(message: str) -> "NoReturn":
    raise SystemExit(f"SHADOW_CANDIDATE_EVALUATION_ERROR: {message}")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()


def head_parts(path: Path):
    doc=load(path)
    head=doc.get("head")
    if (doc.get("schema_version")!=1 or doc.get("feature_mode")!="dino"
            or doc.get("crop_transform")!="upper_88x80_v1"
            or not isinstance(head,dict)):
        die(f"incompatible head: {path}")
    labels=head.get("labels");dims=head.get("dimensions")
    weights=head.get("weights");biases=head.get("biases")
    if (not isinstance(labels,list) or not isinstance(dims,int)
            or not isinstance(weights,list) or len(weights)!=len(labels)*dims
            or not isinstance(biases,list) or len(biases)!=len(labels)):
        die("invalid head dimensions")
    w=np.asarray(weights,dtype=np.float32).reshape(len(labels),dims)
    b=np.asarray(biases,dtype=np.float32)
    return doc,labels,w,b


def vector_tensor(image: Image.Image, side: int):
    raw=np.asarray(image.convert("RGB"),dtype=np.float32)
    if raw.shape!=(144,128,3):
        die(f"gold crop must be 128x144, got {raw.shape}")
    upper=raw[24:104,20:108]
    transformed=_resize_bilinear(upper,144,128)
    tensor=_resize_bilinear(transformed,side,side)/255.0
    return tensor.transpose(2,0,1).astype(np.float32)


def probabilities(vectors,weights,biases):
    logits=vectors@weights.T+biases
    logits-=logits.max(axis=1,keepdims=True)
    p=np.exp(logits);p/=p.sum(axis=1,keepdims=True)
    return p


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidate",type=Path,required=True)
    p.add_argument("--champion",type=Path,required=True)
    p.add_argument("--encoder",type=Path,required=True)
    p.add_argument("--gates",type=Path,required=True)
    p.add_argument("--collection",type=Path,required=True)
    p.add_argument("--gold",type=Path,required=True)
    p.add_argument("--candidate-training-session",required=True)
    p.add_argument("--evaluation-session",required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():die("new output required")
    if args.candidate_training_session==args.evaluation_session:
        die("candidate cannot be evaluated on its training session")

    cand_doc,cand_labels,cw,cb=head_parts(args.candidate)
    champ_doc,champ_labels,bw,bb=head_parts(args.champion)
    if cand_doc.get("encoder_sha256")!=champ_doc.get("encoder_sha256"):
        die("candidate/champion encoder mismatch")
    if sha256(args.encoder)!=cand_doc.get("encoder_sha256"):
        die("encoder checksum mismatch")
    if cand_doc.get("input_size")!=champ_doc.get("input_size"):
        die("candidate/champion input size mismatch")
    if cand_labels!=champ_labels:
        # A candidate may add a new label; comparing top1 fairly still requires
        # the champion label set to be a subset, but metrics are computed by ID.
        if not set(champ_labels)<=set(cand_labels):
            die("champion labels not subset of candidate labels")

    gates=load(args.gates)
    if gates.get("policy")!="validation_zero_error_max_coverage_v1" or gates.get("runtime_gate_eligible") is not True:
        die("candidate gates are not eligible")
    min_prob=float(gates["min_probability"]);min_margin=float(gates["min_margin"])

    rows=load(args.gold)
    if not isinstance(rows,list) or not rows:die("empty direct gold")
    inputs=[];truths=[]
    seen=set()
    for row in rows:
        if (not isinstance(row,dict)
                or row.get("decision") not in {"supported","bootstrap_supported"}
                or row.get("training_eligible") is not True
                or row.get("human_review_required") is not False
                or row.get("model_prediction_used_as_label") is not False):
            die("gold provenance contract failed")
        pixel=row.get("pixel_sha256");label=row.get("unit_id")
        if not isinstance(pixel,str) or pixel in seen or not isinstance(label,str):die("duplicate/invalid gold")
        seen.add(pixel)
        path=(args.collection/str(row.get("crop"))).resolve()
        if not path.is_file() or not path.is_relative_to(args.collection.resolve()):die("gold crop path invalid")
        with Image.open(path) as im:
            rgb=im.convert("RGB")
            if hashlib.sha256(rgb.tobytes()).hexdigest()!=pixel:die("gold pixel hash mismatch")
            inputs.append(vector_tensor(rgb,int(cand_doc["input_size"])))
        truths.append(label)

    opts=ort.SessionOptions();opts.intra_op_num_threads=opts.inter_op_num_threads=1
    opts.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
    opts.add_session_config_entry("session.intra_op.allow_spinning","0")
    session=ort.InferenceSession(str(args.encoder),opts,providers=["CPUExecutionProvider"])
    input_name=session.get_inputs()[0].name
    vectors=session.run(["embeddings"],{input_name:np.stack(inputs)})[0]
    norms=np.linalg.norm(vectors,axis=1,keepdims=True)
    if np.any(norms<=1e-8):die("empty embedding")
    vectors=vectors/norms

    cp=probabilities(vectors,cw,cb);bp=probabilities(vectors,bw,bb)
    candidate_correct=champion_correct=accepted_correct=wrong_accepted=0
    details=[]
    for truth,ca,ba in zip(truths,cp,bp):
        co=np.argsort(-ca,kind="stable");bo=np.argsort(-ba,kind="stable")
        c1,c2=int(co[0]),int(co[1]);b1=int(bo[0])
        cp1=float(ca[c1]);margin=float(ca[c1]-ca[c2])
        cpred=cand_labels[c1];bpred=champ_labels[b1]
        candidate_correct+=int(cpred==truth)
        champion_correct+=int(bpred==truth)
        accepted=cpred!="__unknown__" and cp1>=min_prob and margin>=min_margin
        accepted_correct+=int(accepted and cpred==truth)
        wrong_accepted+=int(accepted and cpred!=truth)
        details.append({"truth":truth,"candidate":cpred,"champion":bpred,
                        "candidate_score":cp1,"candidate_margin":margin,"accepted":accepted})

    result={
        "schema_version":1,"policy":"independent_direct_gold_shadow_eval_v1",
        "candidate_training_session":args.candidate_training_session,
        "evaluation_session":args.evaluation_session,
        "gold_anchors":len(truths),
        "candidate_correct":candidate_correct,
        "champion_correct":champion_correct,
        "candidate_delta":candidate_correct-champion_correct,
        "candidate_wrong_accepted":wrong_accepted,
        "candidate_accepted_correct":accepted_correct,
        "candidate_not_worse":candidate_correct>=champion_correct,
        "candidate_strictly_better":candidate_correct>champion_correct,
        "runtime_gates":{"min_probability":min_prob,"min_margin":min_margin},
        "details":details,
        "training_performed":False,"human_review_required":False,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("SHADOW_CANDIDATE_EVALUATION_OK=true")
    print(f"GOLD_ANCHORS={len(truths)}")
    print(f"CANDIDATE_CORRECT={candidate_correct}")
    print(f"CHAMPION_CORRECT={champion_correct}")
    print(f"WRONG_ACCEPTED={wrong_accepted}")

if __name__=="__main__":main()
