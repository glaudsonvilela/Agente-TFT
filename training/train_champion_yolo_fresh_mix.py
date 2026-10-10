#!/usr/bin/env python3
"""Train the 65-class YOLO crop classifier from an audited SSD corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch
from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path)
    parser.add_argument("--name", default="champion-fresh-mix-20261009")
    parser.add_argument("--batch", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=50)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; training must not silently use CPU")
    manifest_path = args.dataset / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Expected a canonical corpus manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    review_path = Path(__file__).with_name("champion_label_corrections_20261009.json")
    review_sha256 = hashlib.sha256(review_path.read_bytes()).hexdigest()
    if manifest.get("model_predictions_used_as_labels") is not False or \
            len(manifest.get("classes", [])) != 65 or \
            manifest.get("counts") != {"train": 734, "val": 32, "test": 127,
                                       "correlated_holdout": 10, "quarantine": 0} or \
            manifest.get("user_review_sha256") != review_sha256:
        raise ValueError("Corpus labels or class coverage differ from audit")
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = True
    YOLO(str(args.weights)).train(
        data=str(args.dataset), epochs=args.epochs, patience=12,
        imgsz=224, batch=args.batch, workers=2, device=0,
        amp=False, cache="ram", optimizer="AdamW", lr0=0.00012,
        seed=31, plots=False, project=str(args.runs), name=args.name,
        exist_ok=False, save_period=5,
    )


if __name__ == "__main__":
    main()
