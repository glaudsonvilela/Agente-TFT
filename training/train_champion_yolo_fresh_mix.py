#!/usr/bin/env python3
"""Train the 65-class YOLO crop classifier with reviewed new video crops.

The dataset is prepared separately on SSD. It combines the existing train
split with manually reviewed new crops while keeping legacy val/test fixed.
"""

from __future__ import annotations

import argparse
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
    if not (args.dataset / "mix-provenance.json").is_file():
        raise ValueError("Expected an audited mixed dataset")
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = True
    YOLO(str(args.weights)).train(
        data=str(args.dataset), epochs=args.epochs, patience=12,
        imgsz=224, batch=args.batch, workers=4, device=0,
        amp=False, cache="ram", optimizer="AdamW", lr0=0.00012,
        seed=31, plots=False, project=str(args.runs), name=args.name,
        exist_ok=False, save_period=5,
    )


if __name__ == "__main__":
    main()
