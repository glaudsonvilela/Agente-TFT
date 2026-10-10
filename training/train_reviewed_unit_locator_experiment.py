"""Train one-class TFT unit localization separately from champion naming."""

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
    args = parser.parse_args()
    provenance = json.loads((args.experiment / "provenance.json").read_text())
    if (provenance["scope"] != "experimental_one_class_unit_locator"
            or provenance["model_predictions_used_as_labels"] is not False
            or provenance["old_tft_weights_used"] is not False
            or provenance["independent_reviewed_source_boxes"] != 59
            or provenance["patches"] != {"train": 135, "val": 10, "test": 4}):
        raise ValueError("Unexpected reviewed locator dataset")
    if not args.initial_weights.is_file():
        raise FileNotFoundError(args.initial_weights)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this requested GPU experiment")
    run_dir = args.experiment / "runs" / "unit-locator-v1"
    if run_dir.exists():
        raise FileExistsError(run_dir)
    torch.set_num_threads(2)
    print(f"GPU: {torch.cuda.get_device_name(0)}", flush=True)
    print("Training one class (unit) from 45 reviewed source boxes.", flush=True)
    print("Validation: 10 boxes from a different VOD; final test: 4 boxes from two more VODs.", flush=True)
    print("Caution: not all units in source frames have human boxes; this is an isolated experiment.", flush=True)
    YOLO(str(args.initial_weights)).train(
        data=str(args.experiment / "dataset/data.yaml"),
        epochs=args.epochs,
        patience=args.epochs,
        imgsz=384,
        batch=8,
        workers=0,
        device=0,
        amp=False,
        cache=False,
        mosaic=0,
        mixup=0,
        optimizer="AdamW",
        lr0=0.0002,
        seed=59,
        plots=False,
        project=str(args.experiment / "runs"),
        name="unit-locator-v1",
        exist_ok=False,
        save_period=10,
    )


if __name__ == "__main__":
    main()
