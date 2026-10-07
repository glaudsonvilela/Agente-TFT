#!/usr/bin/env python3
"""Calibrate fail-closed runtime acceptance gates from frozen validation output.

Rule is predeclared and deterministic:
1. consider every observed top-score and margin as candidate thresholds plus 0;
2. reject any threshold pair that accepts a wrong named prediction or accepts
   a named prediction on __unknown__;
3. maximize correctly accepted named validation examples;
4. ties choose the lower probability threshold, then lower margin;
5. zero accepted correct examples => not runtime eligible.

No test/holdout source is used.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def die(message: str) -> "NoReturn":
    raise SystemExit(f"UNIT_HEAD_GATE_CALIBRATION_ERROR: {message}")


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"cannot read {path}: {exc}")


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--report",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():die("new output path required")

    report=load(args.report)
    try:
        validation=report["variants"]["dino"]["evaluation"]["validation"]
        rows=validation["predictions"]
    except (KeyError,TypeError):
        die("training report lacks dino validation predictions")
    if not isinstance(rows,list) or not rows:die("empty validation predictions")

    normalized=[]
    for i,row in enumerate(rows):
        if not isinstance(row,dict):die(f"invalid validation row {i}")
        label=row.get("label");pred=row.get("predicted")
        score=row.get("softmax_score_uncalibrated")
        margin=row.get("softmax_margin_uncalibrated")
        if (not isinstance(label,str) or not isinstance(pred,str)
                or type(score) not in (int,float) or type(margin) not in (int,float)
                or not math.isfinite(float(score)) or not math.isfinite(float(margin))
                or not 0<=float(score)<=1 or not 0<=float(margin)<=1):
            die(f"validation row {i} lacks calibrated-gate inputs")
        normalized.append((label,pred,float(score),float(margin)))

    probs=sorted({0.0,*[x[2] for x in normalized]})
    margins=sorted({0.0,*[x[3] for x in normalized]})
    best=None
    explored=0
    feasible=0
    for prob in probs:
        for margin in margins:
            explored+=1
            accepted=[
                row for row in normalized
                if row[1]!="__unknown__" and row[2]>=prob and row[3]>=margin
            ]
            wrong=sum(1 for label,pred,_,_ in accepted if label!=pred)
            correct=sum(1 for label,pred,_,_ in accepted if label!="__unknown__" and label==pred)
            accepted_unknown=sum(1 for label,_,_,_ in accepted if label=="__unknown__")
            if wrong or accepted_unknown:
                continue
            feasible+=1
            key=(correct,-prob,-margin)
            if best is None or key>best[0]:
                best=(key,prob,margin,correct,len(accepted))

    if best is None:
        die("no zero-error threshold pair exists")
    _,prob,margin,correct,accepted=best
    named=sum(1 for label,_,_,_ in normalized if label!="__unknown__")
    result={
        "schema_version":1,
        "policy":"validation_zero_error_max_coverage_v1",
        "source":"training_report.dino.validation.predictions",
        "min_probability":prob,
        "min_margin":margin,
        "validation_rows":len(normalized),
        "validation_named":named,
        "accepted_total":accepted,
        "accepted_named_correct":correct,
        "wrong_accepted":0,
        "accepted_unknown":0,
        "named_coverage":correct/named if named else 0.0,
        "threshold_pairs_explored":explored,
        "feasible_zero_error_pairs":feasible,
        "runtime_gate_eligible":correct>0,
        "test_used":False,
        "holdout_used":False,
        "human_review_required":False,
    }
    if correct<=0:
        result["reason"]="zero_correct_accepts_under_zero_error_constraint"
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("UNIT_HEAD_GATE_CALIBRATION_OK=true")
    print(f"MIN_PROBABILITY={prob:.12f}")
    print(f"MIN_MARGIN={margin:.12f}")
    print(f"ACCEPTED_CORRECT={correct}")
    print("WRONG_ACCEPTED=0")
    print(f"RUNTIME_GATE_ELIGIBLE={str(correct>0).lower()}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
