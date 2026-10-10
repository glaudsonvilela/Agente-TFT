"""Train an isolated 46-class diagnostic model with generic ImageNet weights."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--initial-weights", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch", type=int, default=8)
    args = parser.parse_args()
    provenance = json.loads((args.experiment / "provenance.json").read_text())
    if (provenance["scope"] != "experimental_46_class_classifier_only"
            or provenance["model_predictions_used_as_labels"] is not False
            or provenance["old_tft_weights_used"] is not False
            or provenance["train"] != 102 or provenance["holdout"] != 4
            or len(provenance["classes"]) != 46):
        raise ValueError("Unexpected diagnostic dataset")
    if not torch.cuda.is_available():
        raise RuntimeError("GTX/CUDA unavailable; CPU fallback would hide the speed result")
    if not args.initial_weights.is_file():
        raise FileNotFoundError(args.initial_weights)
    run_dir = args.experiment / "runs" / "reviewed-46-v1"
    if run_dir.exists():
        raise FileExistsError(run_dir)
    torch.set_num_threads(2)
    print(f"GPU: {torch.cuda.get_device_name(0)}", flush=True)
    print("Diagnostic: 46 classes, 102 train crops, 4 clips from unseen videos", flush=True)
    print("YOLO's validation is a training-set mirror; only the four held-out crops measure generalization", flush=True)
    YOLO(str(args.initial_weights)).train(
        data=str(args.experiment / "dataset"),
        epochs=args.epochs,
        patience=args.epochs,
        imgsz=224,
        batch=args.batch,
        workers=0,
        device=0,
        amp=False,
        cache=False,
        optimizer="AdamW",
        lr0=0.0002,
        seed=46,
        plots=False,
        project=str(args.experiment / "runs"),
        name="reviewed-46-v1",
        exist_ok=False,
        save_period=10,
    )


if __name__ == "__main__":
    main()
