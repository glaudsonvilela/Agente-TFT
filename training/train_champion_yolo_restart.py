#!/usr/bin/env python3
"""Train a fresh experimental TFT champion classifier on audited visual crops."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-weights", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--name", default="champion-audited-restart")
    parser.add_argument("--epochs", type=int, default=60)
    args = parser.parse_args()
    manifest = json.loads((args.dataset / "provenance.json").read_text())
    if manifest["status"] != "experimental_candidate_dataset" or \
            manifest["model_predictions_used_as_labels"] is not False or \
            manifest["counts"]["train"] != 325 or len(manifest["classes"]) != 65:
        raise ValueError("The audited 65-class restart dataset is required")
    if not args.base_weights.is_file():
        raise FileNotFoundError(args.base_weights)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; refusing a silent CPU fallback")
    if (args.runs / args.name).exists():
        raise FileExistsError(args.runs / args.name)
    torch.set_num_threads(2)
    print(f"GPU: {torch.cuda.get_device_name(0)}", flush=True)
    print("Training: 325 reviewed source crops, 65 classes; no model-predicted labels", flush=True)
    print("Result stays experimental until held-out evaluation", flush=True)
    YOLO(str(args.base_weights)).train(
        data=str(args.dataset), epochs=args.epochs, patience=12, imgsz=224,
        batch=16, workers=2, device=0, amp=False, cache=False,
        optimizer="AdamW", lr0=.000145, seed=31, plots=False,
        project=str(args.runs), name=args.name, exist_ok=False,
        save_period=10,
    )


if __name__ == "__main__":
    main()
