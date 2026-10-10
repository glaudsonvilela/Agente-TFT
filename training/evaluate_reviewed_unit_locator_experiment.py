"""Measure one-class unit localization on source videos excluded from training."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import torch
from torchvision.ops import nms
from ultralytics import YOLO

from build_reviewed_unit_locator_experiment import TEST_VIDEOS, reviewed_boxes


def intersection_over_union(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, x1 - x0) * max(0, y1 - y0)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return intersection / max(1, area_a + area_b - intersection)


def starts(length: int, tile: int, stride: int) -> list[int]:
    if length <= tile:
        return [0]
    values = list(range(0, length - tile + 1, stride))
    if values[-1] != length - tile:
        values.append(length - tile)
    return values


def infer_tiled(model: YOLO, frame: cv2.typing.MatLike) -> list[dict]:
    # Keep unit size similar to the reviewed close crops used for training.
    # Speed is secondary in this proof-of-concept evaluation.
    tile, stride = 512, 416
    boxes, scores = [], []
    height, width = frame.shape[:2]
    for top in starts(height, tile, stride):
        for left in starts(width, tile, stride):
            view = frame[top:top+tile, left:left+tile]
            result = model.predict(view, device=0, imgsz=384, conf=0.15,
                                   iou=0.5, max_det=50, verbose=False)[0]
            for detection in result.boxes:
                x0, y0, x1, y1 = detection.xyxy[0].tolist()
                boxes.append((round(x0 + left), round(y0 + top),
                              round(x1 + left), round(y1 + top)))
                scores.append(float(detection.conf))
    if not boxes:
        return []
    keep = nms(torch.tensor(boxes, dtype=torch.float32),
               torch.tensor(scores), 0.5).tolist()
    return [{"box": boxes[index], "confidence": round(scores[index], 4)}
            for index in keep]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    model = YOLO(str(args.weights))
    metrics = model.val(data=str(args.experiment / "dataset/data.yaml"),
                        split="test", imgsz=384, batch=4, device=0,
                        plots=False, verbose=False)
    by_frame = reviewed_boxes(args.index)
    results = []
    for frame_path, references in sorted(by_frame.items()):
        references = [row for row in references if row["video"] in TEST_VIDEOS]
        if not references:
            continue
        frame = cv2.imread(frame_path)
        if frame is None:
            raise RuntimeError(f"Cannot read test frame: {frame_path}")
        detections = infer_tiled(model, frame)
        preview = cv2.resize(frame, (1280, round(frame.shape[0] * 1280 / frame.shape[1])),
                             interpolation=cv2.INTER_AREA)
        scale = 1280 / frame.shape[1]
        for detection in detections:
            x0, y0, x1, y1 = [round(value * scale) for value in detection["box"]]
            cv2.rectangle(preview, (x0, y0), (x1, y1), (0, 225, 0), 2)
        for reference in references:
            x0, y0, x1, y1 = [round(value * scale) for value in reference["box"]]
            cv2.rectangle(preview, (x0, y0), (x1, y1), (0, 0, 255), 2)
        image_path = args.experiment / f"unseen-{Path(frame_path).stem}.jpg"
        cv2.imwrite(str(image_path), preview, [cv2.IMWRITE_JPEG_QUALITY, 92])
        for reference in references:
            best = max((intersection_over_union(reference["box"], row["box"])
                        for row in detections), default=0.0)
            results.append({"review_id": reference["id"],
                            "video": reference["video"],
                            "best_full_frame_iou": round(best, 4),
                            "detected_boxes_in_frame": len(detections)})
    report = {
        "scope": "unseen_videos_only",
        "weights": str(args.weights),
        "model_predictions_used_as_labels": False,
        "patch_test_map50": round(float(metrics.box.map50), 4),
        "patch_test_map50_95": round(float(metrics.box.map), 4),
        "full_frame_reviewed_box_count": len(results),
        "full_frame_hits_iou_0_3": sum(r["best_full_frame_iou"] >= 0.3 for r in results),
        "full_frame_hits_iou_0_5": sum(r["best_full_frame_iou"] >= 0.5 for r in results),
        "rows": results,
        "limitations": [
            "Only four independently reviewed source boxes in two unseen videos.",
            "Unreviewed units in those frames prevent a precision estimate.",
            "This detector localizes generic units; it does not name champions.",
        ],
    }
    output = args.experiment / "unseen-locator-report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
