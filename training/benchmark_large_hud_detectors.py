"""Compare isolated large detectors on the same unseen TFT source frames.

Only previously reviewed boxes count as references. Other visible units are
not completely annotated, so this script cannot estimate body precision.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import torch
from torchvision.ops import nms
import yaml

from build_joint_hud_unit_experiment import ROI
from build_reviewed_unit_locator_experiment import reviewed_boxes
from evaluate_reviewed_unit_locator_experiment import intersection_over_union, starts


def load_model(kind: str, weights: Path):
    if kind == "yolo26x":
        from ultralytics import YOLO

        return YOLO(str(weights))
    from rfdetr import RFDETRLarge

    return RFDETRLarge(pretrain_weights=str(weights.resolve()), device="cuda")


def predict(kind: str, model, bgr):
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    if kind == "yolo26x":
        result = model.predict(bgr, device=0, imgsz=640, conf=0.15,
                               iou=0.5, max_det=100, verbose=False)[0]
        return [(int(row.cls.item()), tuple(row.xyxy[0].cpu().tolist()),
                 float(row.conf.item())) for row in result.boxes]
    result = model.predict(rgb, threshold=0.15)
    return [(int(category), tuple(map(float, box)), float(score))
            for box, category, score in zip(result.xyxy, result.class_id,
                                             result.confidence)]


def body_tiles(kind: str, model, frame):
    height, width = frame.shape[:2]
    x0, y0, x1, y1 = (round(v) for v in
                      (width * 170 / 1920, height * 120 / 1080,
                       width * 1700 / 1920, height * 860 / 1080))
    board = frame[y0:y1, x0:x1]
    boxes, scores = [], []
    for top in starts(board.shape[0], 512, 416):
        for left in starts(board.shape[1], 512, 416):
            tile = board[top:top + 512, left:left + 512]
            for category, box, score in predict(kind, model, tile):
                if category != 0:
                    continue
                bx0, by0, bx1, by1 = box
                boxes.append((bx0 + left + x0, by0 + top + y0,
                              bx1 + left + x0, by1 + top + y0))
                scores.append(score)
    if not boxes:
        return []
    keep = nms(torch.tensor(boxes, dtype=torch.float32),
               torch.tensor(scores), 0.5).tolist()
    return [{"box": boxes[i], "confidence": round(scores[i], 4)} for i in keep]


def run(dataset: Path, index: Path, kind: str, weights: Path, output: Path):
    if output.exists():
        raise FileExistsError(output)
    manifest = json.loads((dataset / "provenance.json").read_text())
    if manifest["model_predictions_used_as_labels"] is not False:
        raise ValueError("Unreviewed labels are not valid ground truth")
    names = yaml.safe_load((dataset / "data.yaml").read_text())["names"]
    if list(names.values()) != list(manifest["classes"]):
        raise ValueError("Class map mismatch")
    references_by_frame = reviewed_boxes(index)
    model = load_model(kind, weights)
    output.mkdir(parents=True)
    rows = []
    for source in manifest["sources"]:
        if source["split"] != "test":
            continue
        frame_path = source["source_frame"]
        frame = cv2.imread(frame_path)
        if frame is None:
            raise FileNotFoundError(frame_path)
        native = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_AREA)
        canvas = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
        started = time.monotonic()
        hud_rows = []
        hud_prediction_count = 0
        for region, references in source["region_labels"].items():
            rx0, ry0, rx1, ry1 = ROI[region]
            detections = predict(kind, model, native[ry0:ry1, rx0:rx1])
            hud_prediction_count += sum(category != 0 for category, _, _ in detections)
            for category, box, _ in detections:
                if category == 0:
                    continue
                bx0, by0, bx1, by1 = box
                shifted = (bx0 + rx0, by0 + ry0, bx1 + rx0, by1 + ry0)
                a, b, c, d = (round(v * 2 / 3) for v in shifted)
                cv2.rectangle(canvas, (a, b), (c, d), (0, 220, 255), 2)
            for reference in references:
                category = next(i for i, name in names.items()
                                if name == reference["class"])
                box = reference["box_1920"]
                best = max((intersection_over_union(
                    box, (candidate[0] + rx0, candidate[1] + ry0,
                          candidate[2] + rx0, candidate[3] + ry0))
                    for found, candidate, _ in detections if found == category),
                    default=0.0)
                hud_rows.append({"class": reference["class"],
                                 "best_iou": round(best, 4)})
        bodies = body_tiles(kind, model, frame)
        sx, sy = 1280 / frame.shape[1], 720 / frame.shape[0]
        for row in bodies:
            a, b, c, d = row["box"]
            cv2.rectangle(canvas, (round(a * sx), round(b * sy)),
                          (round(c * sx), round(d * sy)), (0, 220, 0), 2)
        body_rows = []
        for reference in references_by_frame[frame_path]:
            box = reference["box"]
            best = max((intersection_over_union(box, row["box"])
                        for row in bodies), default=0.0)
            body_rows.append({"review_id": reference["id"],
                              "best_iou": round(best, 4)})
            a, b, c, d = box
            cv2.rectangle(canvas, (round(a * sx), round(b * sy)),
                          (round(c * sx), round(d * sy)), (0, 0, 255), 2)
        torch.cuda.synchronize()
        target = output / f"{Path(frame_path).stem}.jpg"
        cv2.imwrite(str(target), canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])
        rows.append({"frame": Path(frame_path).name,
                     "seconds": round(time.monotonic() - started, 3),
                     "body_box_count": len(bodies),
                     "hud_box_count": hud_prediction_count,
                     "reviewed_body_hits_iou_0_5": sum(
                         row["best_iou"] >= 0.5 for row in body_rows),
                     "reviewed_body_count": len(body_rows),
                     "hud_hits_iou_0_5": sum(
                         row["best_iou"] >= 0.5 for row in hud_rows),
                     "hud_label_count": len(hud_rows),
                     "body_rows": body_rows, "hud_rows": hud_rows,
                     "preview": str(target)})
    report = {"model": kind, "weights": str(weights),
              "confidence_threshold": 0.15, "iou_threshold": 0.5,
              "frames": rows,
              "total_reviewed_body_hits": sum(
                  row["reviewed_body_hits_iou_0_5"] for row in rows),
              "total_reviewed_body_count": sum(
                  row["reviewed_body_count"] for row in rows),
              "total_hud_hits": sum(row["hud_hits_iou_0_5"] for row in rows),
              "total_hud_label_count": sum(row["hud_label_count"] for row in rows),
              "limitations": [
                  "Visible unreviewed bodies make body precision unmeasurable.",
                  "HUD boxes are layout/pixel proposals, not read values.",
                  "Only four reviewed body boxes in held-out videos.",
                  "This experiment does not identify champion names."],
              }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items()
                      if key != "frames"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--model", required=True, choices=("yolo26x", "rfdetr-large"))
    parser.add_argument("--weights", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.dataset, args.index, args.model, args.weights, args.output)
