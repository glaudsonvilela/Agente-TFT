"""Train both YOLO and Faster R-CNN on the same isolated TFT HUD/unit split."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import torch
import yaml
from ultralytics import YOLO

from compare_torchvision_unit_detector import ReviewedPatches, make_model


def load_dataset(root: Path):
    provenance = json.loads((root / "provenance.json").read_text())
    if (provenance["scope"] != "isolated_joint_hud_unit_experiment"
            or provenance["model_predictions_used_as_labels"] is not False
            or len(provenance["classes"]) != 7):
        raise ValueError("Unexpected joint dataset")
    names = yaml.safe_load((root / "data.yaml").read_text())["names"]
    if list(names.values()) != list(provenance["classes"]):
        raise ValueError("Class map mismatch")
    return provenance


def train_yolo(root: Path, initial_weights: Path, epochs: int):
    if not initial_weights.is_file():
        raise FileNotFoundError(initial_weights)
    run = root / "runs" / "joint-yolo11n"
    if run.exists():
        raise FileExistsError(run)
    YOLO(str(initial_weights)).train(
        data=str(root / "data.yaml"), epochs=epochs, patience=epochs,
        imgsz=640, batch=4, workers=0, device=0, amp=False, cache=False,
        mosaic=0, mixup=0, plots=False, optimizer="AdamW", lr0=0.0002,
        seed=59, project=str(root / "runs"), name="joint-yolo11n",
        exist_ok=False)
    model = YOLO(str(run / "weights" / "best.pt"))
    metrics = model.val(data=str(root / "data.yaml"), split="test",
                        imgsz=640, batch=4, device=0, plots=False, verbose=False)
    report = {"model": "YOLO11n", "epochs": epochs,
              "test_patch_map50": round(float(metrics.box.map50), 4),
              "test_patch_map50_95": round(float(metrics.box.map), 4),
              "class_map50": {model.names[i]: round(float(value), 4)
                              for i, value in enumerate(metrics.box.maps)}}
    (run / "test-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False), flush=True)


def train_faster(root: Path, epochs: int, classes: int):
    run = root / "runs" / "joint-fasterrcnn-mobilenetv3"
    if run.exists():
        raise FileExistsError(run)
    run.mkdir(parents=True)
    model = make_model(pretrained=True, num_classes=classes + 1).cuda()
    train = ReviewedPatches(root, "train")
    optimizer = torch.optim.SGD((p for p in model.parameters() if p.requires_grad),
                                lr=0.002, momentum=0.9, weight_decay=0.0005)
    for epoch in range(epochs):
        model.train()
        order = torch.randperm(len(train)).tolist()
        loss_total = 0.0
        started = time.monotonic()
        for index in order:
            image, target = train[index]
            losses = model([image.cuda()], [{k: v.cuda() for k, v in target.items()}])
            loss = sum(losses.values())
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            loss_total += loss.item()
        print(f"Faster epoch {epoch+1}/{epochs} loss={loss_total/len(train):.4f} "
              f"seconds={time.monotonic()-started:.1f}", flush=True)
    torch.save(model.cpu().state_dict(), run / "model.pt")
    print(f"Faster weights: {run / 'model.pt'}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--initial-yolo", type=Path)
    parser.add_argument("--model", choices=("yolo", "faster"), required=True)
    parser.add_argument("--epochs", type=int, default=20)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    torch.set_num_threads(2)
    torch.manual_seed(59)
    provenance = load_dataset(args.dataset)
    if args.model == "yolo":
        if args.initial_yolo is None:
            parser.error("--initial-yolo is required for YOLO")
        train_yolo(args.dataset, args.initial_yolo, args.epochs)
    else:
        train_faster(args.dataset, args.epochs, len(provenance["classes"]))


if __name__ == "__main__":
    main()
