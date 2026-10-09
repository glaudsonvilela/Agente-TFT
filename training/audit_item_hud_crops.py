"""Compare real TFT item crops with model predictions and pinned artwork.

The generated sheet is for human review. Predictions are never saved as labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO


def rect(value: str) -> tuple[int, int, int, int]:
    try:
        parts = tuple(int(part) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected x,y,width,height") from exc
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        raise argparse.ArgumentTypeError("Expected x,y,width,height with positive size")
    return parts


def run(image: Path, model_path: Path, metadata: Path, icon_dir: Path,
        rectangles: list[tuple[int, int, int, int]], output: Path, device: str) -> None:
    frame = cv2.imread(str(image))
    if frame is None:
        raise ValueError(f"Cannot read image: {image}")
    classes = {row["label"]: row for row in json.loads(metadata.read_text())["classes"]}
    artwork = {hashlib.sha256(path.read_bytes()).hexdigest(): path
               for path in icon_dir.glob("*.png")}
    crops = []
    for x, y, width, height in rectangles:
        if x < 0 or y < 0 or x + width > frame.shape[1] or y + height > frame.shape[0]:
            raise ValueError(f"Crop outside image: {x},{y},{width},{height}")
        crops.append(frame[y:y+height, x:x+width].copy())
    model = YOLO(str(model_path))
    results = model.predict(source=crops, imgsz=96, device=device,
                            batch=min(32, len(crops)), verbose=False)
    output.mkdir(parents=True, exist_ok=True)
    sheet = np.full((len(crops)*110, 620, 3), 20, dtype=np.uint8)
    rows = []
    for index, (crop, result) in enumerate(zip(crops, results)):
        label = model.names[int(result.probs.top1)]
        item = classes[label]
        source = artwork.get(item["source_sha256"])
        if source is None:
            raise FileNotFoundError(f"Pinned artwork missing for {label}")
        art = cv2.imread(str(source))
        if art is None:
            raise ValueError(f"Invalid artwork: {source}")
        y = index*110
        sheet[y:y+84, 0:84] = cv2.resize(crop, (84, 84), interpolation=cv2.INTER_NEAREST)
        sheet[y:y+84, 104:188] = cv2.resize(art, (84, 84), interpolation=cv2.INTER_NEAREST)
        name = item["names"][0]
        confidence = float(result.probs.top1conf)
        cv2.putText(sheet, f"{name[:32]}  {confidence:.2f}", (205, y+43),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.43, (230, 230, 230), 1, cv2.LINE_AA)
        rows.append({"rect": rectangles[index], "predicted_label": label,
                     "predicted_names": sorted(set(item["names"])),
                     "confidence": round(confidence, 4), "human_verified": False})
    cv2.imwrite(str(output / "review.png"), sheet)
    (output / "predictions.json").write_text(json.dumps({
        "image": str(image), "model": str(model_path), "prediction_is_ground_truth": False,
        "rows": rows}, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"crops": len(rows), "review": str(output / "review.png")},
                     ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--icon-dir", type=Path, required=True)
    parser.add_argument("--rect", type=rect, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    run(args.image, args.model, args.metadata, args.icon_dir,
        args.rect, args.output, args.device)


if __name__ == "__main__":
    main()
