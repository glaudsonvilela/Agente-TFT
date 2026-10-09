#!/usr/bin/env python3
"""Run a bounded GPU training candidate for the TFT visual recognizer.

The existing YOLO26n visual weights provide the trainable feature extractor.
The project's Rust crate decodes its raw detection head during observation.
This run never installs its candidate automatically or treats predictions as labels.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--name", default="tft-rust-decoder-champions-one-hour")
    args = parser.parse_args()

    import torch
    from ultralytics import YOLO

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required; refusing silent CPU training")
    provenance = json.loads((args.dataset / "mix-provenance.json").read_text())
    correction = json.loads((args.dataset / "correction-manifest.json").read_text())
    if provenance.get("fresh_labels_from_model_predictions") is not False:
        raise ValueError("Training data must exclude model predictions as labels")
    if provenance.get("class_count") != 65 or not correction:
        raise ValueError("Unexpected TFT champion dataset")
    if not args.weights.is_file():
        raise FileNotFoundError(args.weights)
    expected = {folder.name for folder in (args.dataset / "train").iterdir() if folder.is_dir()}
    model = YOLO(str(args.weights))
    if set(model.names.values()) != expected:
        raise ValueError("The incumbent model and reviewed dataset have different classes")
    args.runs.mkdir(parents=True, exist_ok=True)
    if (args.runs / args.name).exists():
        raise FileExistsError(args.runs / args.name)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = True
    print(f"GPU: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"Dados revisados: {args.dataset}", flush=True)
    print("Duração: 1 hora; pesos atuais preservados; candidato separado.", flush=True)
    model.train(
        data=str(args.dataset), epochs=10000, time=1.0, patience=1000,
        imgsz=224, batch=32, workers=2, device=0,
        amp=False, cache="ram", optimizer="AdamW", lr0=0.00008,
        seed=41, plots=False, project=str(args.runs), name=args.name,
        exist_ok=False, save_period=10,
    )
    print("Treino de uma hora concluído. O modelo continua candidato até validação.", flush=True)


if __name__ == "__main__":
    main()
