"""Train the experimental reserve localizer on reviewed high-resolution tiles."""

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
        raise RuntimeError("CUDA unavailable; reserve training will not fall back to CPU")
    torch.set_num_threads(2)
    YOLO(str(args.weights)).train(
        data=str(args.dataset / "data.yaml"), epochs=50, patience=12,
        imgsz=640, batch=6, workers=0, device=0, amp=False, cache=False,
        project=str(args.runs), name="bench-focus-v1", exist_ok=True,
        seed=29, plots=False, save_period=5,
    )


if __name__ == "__main__":
    main()
