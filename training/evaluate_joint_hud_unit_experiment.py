"""Compare YOLO and Faster R-CNN on identical reserved TFT HUD/unit crops."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import cv2
import torch
import yaml
from ultralytics import YOLO

from compare_torchvision_unit_detector import ReviewedPatches, make_model
from evaluate_reviewed_unit_locator_experiment import intersection_over_union


@torch.inference_mode()
def predict(architecture, model, image):
    if architecture == "yolo":
        rgb = image.permute(1, 2, 0).mul(255).byte().cpu().numpy()
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        result = model.predict(bgr, device=0, imgsz=640, conf=0.15,
                               iou=0.5, max_det=100, verbose=False)[0]
        return [(int(box.cls.item()), tuple(box.xyxy[0].cpu().tolist()),
                 float(box.conf.item())) for box in result.boxes]
    result = model([image.cuda()])[0]
    return [(int(category.item())-1, tuple(box.cpu().tolist()), float(score.item()))
            for box, category, score in zip(result["boxes"], result["labels"], result["scores"])
            if score.item() >= 0.15]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--model", choices=("yolo", "faster"), required=True)
    args = parser.parse_args()
    names = yaml.safe_load((args.dataset / "data.yaml").read_text())["names"]
    if args.model == "yolo":
        model = YOLO(str(args.dataset / "runs/joint-yolo11n/weights/best.pt"))
    else:
        model = make_model(pretrained=False, num_classes=len(names)+1).cuda()
        state = torch.load(args.dataset / "runs/joint-fasterrcnn-mobilenetv3/model.pt",
                           map_location="cuda", weights_only=True)
        model.load_state_dict(state)
        model.eval()
    test = ReviewedPatches(args.dataset, "test")
    counts = defaultdict(lambda: {"reference": 0, "matched": 0, "predictions": 0})
    examples = []
    for index in range(len(test)):
        image, target = test[index]
        detections = predict(args.model, model, image)
        for category, _, _ in detections:
            counts[names[category]]["predictions"] += 1
        references = [(label - 1, tuple(box)) for box, label in
                      zip(target["boxes"].tolist(), target["labels"].tolist())]
        unmatched = set(range(len(references)))
        matched = set()
        for category, box, score in sorted(detections, key=lambda row: -row[2]):
            candidates = [(intersection_over_union(box, references[i][1]), i)
                          for i in unmatched if references[i][0] == category]
            if candidates:
                best_iou, best_index = max(candidates)
                if best_iou >= 0.5:
                    unmatched.remove(best_index)
                    matched.add(best_index)
        for ref_index, (category, box) in enumerate(references):
            row = counts[names[category]]
            row["reference"] += 1
            best = max((intersection_over_union(tuple(box), predicted)
                        for kind, predicted, _ in detections if kind == category), default=0)
            if ref_index in matched:
                row["matched"] += 1
            examples.append({"image": test.images[index].name,
                             "class": names[category], "best_iou": round(best, 4)})
    report = {"model": args.model, "confidence_threshold": 0.15,
              "reviewed_test_crops": len(test), "iou_threshold": 0.5,
              "by_class": dict(counts), "examples": examples,
              "limitations": ["Only a small held-out set, split by video.",
                              "HUD labels are audited layout/pixel proposals, not read values.",
                              "Some unit crops can contain other unreviewed units."]}
    out = args.dataset / "runs" / f"joint-{args.model}-patch-report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "examples"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
