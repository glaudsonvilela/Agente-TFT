"""Run the audited unified HUD localization experiment on CUDA."""

import argparse
from pathlib import Path

import torch
from ultralytics import YOLO


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("weights", type=Path)
    parser.add_argument("runs", type=Path)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA indisponível: o treino não será desviado para CPU")
    torch.set_num_threads(2)
    model = YOLO(str(args.weights))
    model.train(
        data=str(args.dataset / "data.yaml"),
        epochs=60,
        imgsz=640,
        batch=6,
        workers=0,
        device=0,
        project=str(args.runs),
        name="unified-hud-v2",
        exist_ok=True,
        amp=False,
        cache=False,
        plots=False,
        patience=12,
        seed=23,
        save_period=5,
    )


if __name__ == "__main__":
    main()
