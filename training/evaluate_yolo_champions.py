"""Evaluate a YOLO champion classifier on the held-out reviewed crops.

The labels were reviewed by an assistant, so these numbers are development
evidence rather than independent ground truth or live-game accuracy.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re


NAME = re.compile(r"frame-(\d{6})-(marker-\d+)\.jpg$")


def zone_index(annotations: Path) -> dict[tuple[int, str], str]:
    frames = json.loads(annotations.read_text(encoding="utf-8"))["frames"]
    # Crop names use the frame's position in this list, not frame["index"].
    return {
        (index, unit["key"]): unit.get("zone", "unknown")
        for index, frame in enumerate(frames)
        for unit in frame.get("layout", {}).get("units", [])
    }


def evaluate(model_path: Path, data: Path, annotations: Path) -> dict:
    from ultralytics import YOLO

    images = sorted((data / "test").glob("*/*.jpg"))
    if not images:
        raise ValueError("No test crops")
    zones = zone_index(annotations)
    model = YOLO(str(model_path))
    names = model.names
    counts = defaultdict(Counter)
    errors = []
    for start in range(0, len(images), 32):
        batch = images[start:start + 32]
        results = model.predict([str(path) for path in batch], imgsz=224,
                                batch=len(batch), device=0, verbose=False)
        for path, result in zip(batch, results, strict=True):
            true_name = path.parent.name
            match = NAME.fullmatch(path.name)
            zone = zones.get((int(match[1]), match[2]), "unmapped") if match else "unmapped"
            top5 = [names[int(index)] for index in result.probs.top5]
            for key in ("all", zone):
                counts[key]["samples"] += 1
                counts[key]["top1"] += top5[0] == true_name
                counts[key]["top5"] += true_name in top5
            if top5[0] != true_name:
                errors.append({"file": path.name, "zone": zone, "expected": true_name,
                               "predicted": top5[0],
                               "score": round(float(result.probs.top1conf), 4)})
    groups = {name: {**dict(counter),
                     "top1_rate": round(counter["top1"] / counter["samples"], 4),
                     "top5_rate": round(counter["top5"] / counter["samples"], 4)}
              for name, counter in sorted(counts.items())}
    return {"model": str(model_path), "test_set": str(data / "test"),
            "annotation_source": str(annotations),
            "independent_human_ground_truth": False,
            "split_warning": "Development split reviewed by assistant; not independent live accuracy",
            "groups": groups, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.model, args.data, args.annotations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps(report["groups"], ensure_ascii=False))


if __name__ == "__main__":
    main()
