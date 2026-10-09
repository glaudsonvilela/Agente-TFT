"""Measure reserve localization separately for allied and opponent tiles."""

import argparse
from collections import Counter
import json
from pathlib import Path

from ultralytics import YOLO


def _iou(a, b):
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    area = max(0, x1 - x0) * max(0, y1 - y0)
    return area / max(1, (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - area)


def evaluate(model_path: Path, dataset: Path, split: str, confidence: float):
    audit = json.loads((dataset / "audit.json").read_text())
    model = YOLO(str(model_path))
    counts = {side: Counter() for side in ("ally", "opponent")}
    for tile in audit["tiles"]:
        if tile["split"] != split:
            continue
        image = dataset / "images" / split / tile["image"]
        label = dataset / "labels" / split / (image.stem + ".txt")
        width = tile["tile"][2] - tile["tile"][0]
        height = tile["tile"][3] - tile["tile"][1]
        truth = []
        for line in label.read_text().splitlines():
            _, cx, cy, bw, bh = map(float, line.split())
            truth.append(((cx-bw/2)*width, (cy-bh/2)*height,
                          (cx+bw/2)*width, (cy+bh/2)*height))
        result = model.predict(str(image), imgsz=640, conf=confidence, iou=.5,
                               device=0, verbose=False)[0]
        predicted = result.boxes.xyxy.cpu().numpy().tolist()
        used = set()
        matched = 0
        for box in truth:
            candidates = [(index, _iou(box, found)) for index, found in enumerate(predicted)
                          if index not in used]
            index, overlap = max(candidates, key=lambda pair: pair[1], default=(-1, 0))
            if overlap >= .5:
                matched += 1
                used.add(index)
        row = counts[tile["side"]]
        row["tiles"] += 1
        row["truth"] += len(truth)
        row["matched"] += matched
        row["missed"] += len(truth) - matched
        row["false_positive"] += len(predicted) - matched
    return {side: dict(value) for side, value in counts.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--split", choices=("val", "test"), default="test")
    parser.add_argument("--confidence", type=float, default=.10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 0 < args.confidence < 1:
        parser.error("--confidence must be between 0 and 1")
    report = {"model": str(args.model), "dataset": str(args.dataset),
              "split": args.split, "confidence_threshold": args.confidence,
              "iou_match_threshold": .5,
              "independent_human_ground_truth": False,
              "metrics": evaluate(args.model, args.dataset, args.split,
                                  args.confidence)}
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload)
    print(payload)


if __name__ == "__main__":
    main()
