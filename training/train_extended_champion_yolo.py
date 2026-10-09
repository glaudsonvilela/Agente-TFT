"""Continue YOLO champion classification with verified added source crops."""

import argparse
from pathlib import Path

import torch
from ultralytics import YOLO


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--runs", required=True, type=Path)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; classifier training will not fall back to CPU")
    torch.set_num_threads(2)
    YOLO(str(args.weights)).train(
        data=str(args.dataset), epochs=40, patience=10, imgsz=224,
        batch=32, workers=0, device=0, amp=False, cache=False,
        optimizer="AdamW", lr0=.000145, seed=31, plots=False,
        project=str(args.runs), name="champion-verified-extension-v1", exist_ok=True,
        save_period=5,
    )


if __name__ == "__main__":
    main()
