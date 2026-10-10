"""Compare a two-stage TFT unit locator with the isolated YOLO experiment.

The reviewed crop split is reused without adding labels. Full-frame results
are reported only for the independently reviewed boxes in unseen videos.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import torch
from torch.utils.data import Dataset
from torchvision.models.detection import (
    FasterRCNN_MobileNet_V3_Large_320_FPN_Weights,
    fasterrcnn_mobilenet_v3_large_320_fpn,
)
from torchvision.models.detection.faster_rcnn import FastRCNNPredictor
from torchvision.ops import nms

from build_reviewed_unit_locator_experiment import TEST_VIDEOS, reviewed_boxes
from evaluate_reviewed_unit_locator_experiment import intersection_over_union, starts


class ReviewedPatches(Dataset):
    def __init__(self, root: Path, split: str):
        self.images = sorted((root / "images" / split).glob("*.jpg"))
        self.labels = root / "labels" / split

    def __len__(self):
        return len(self.images)

    def __getitem__(self, index):
        path = self.images[index]
        bgr = cv2.imread(str(path))
        if bgr is None:
            raise ValueError(path)
        height, width = bgr.shape[:2]
        boxes = []
        categories = []
        for line in (self.labels / f"{path.stem}.txt").read_text().splitlines():
            category, cx, cy, bw, bh = map(float, line.split())
            if not category.is_integer() or category < 0:
                raise ValueError(f"Unexpected class: {category}")
            boxes.append([(cx - bw / 2) * width, (cy - bh / 2) * height,
                          (cx + bw / 2) * width, (cy + bh / 2) * height])
            categories.append(int(category) + 1)  # Background is class zero in Torchvision.
        image = torch.from_numpy(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).copy()).permute(2, 0, 1).float() / 255
        target = {"boxes": torch.tensor(boxes, dtype=torch.float32).reshape(-1, 4),
                  "labels": torch.tensor(categories, dtype=torch.int64)}
        return image, target


def make_model(pretrained: bool, num_classes: int = 2):
    weights = FasterRCNN_MobileNet_V3_Large_320_FPN_Weights.DEFAULT if pretrained else None
    model = fasterrcnn_mobilenet_v3_large_320_fpn(weights=weights,
                                                   weights_backbone=None,
                                                   trainable_backbone_layers=0 if pretrained else None)
    inputs = model.roi_heads.box_predictor.cls_score.in_features
    model.roi_heads.box_predictor = FastRCNNPredictor(inputs, num_classes)
    return model


@torch.inference_mode()
def predict_tiles(model, frame, device):
    tile, stride = 512, 416
    height, width = frame.shape[:2]
    boxes, scores = [], []
    for top in starts(height, tile, stride):
        for left in starts(width, tile, stride):
            bgr = frame[top:top + tile, left:left + tile]
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            image = torch.from_numpy(rgb.copy()).permute(2, 0, 1).float().to(device) / 255
            result = model([image])[0]
            for box, score in zip(result["boxes"], result["scores"]):
                if score < 0.15:
                    break
                x0, y0, x1, y1 = box.cpu().tolist()
                boxes.append((round(x0 + left), round(y0 + top),
                              round(x1 + left), round(y1 + top)))
                scores.append(score.item())
    if not boxes:
        return []
    keep = nms(torch.tensor(boxes, dtype=torch.float32),
               torch.tensor(scores), 0.5).tolist()
    return [{"box": boxes[i], "confidence": round(scores[i], 4)} for i in keep]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--eval-only", action="store_true")
    args = parser.parse_args()
    provenance = json.loads((args.experiment / "provenance.json").read_text())
    if provenance["patches"] != {"train": 135, "val": 10, "test": 4}:
        raise ValueError("Unexpected dataset split")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    torch.manual_seed(59)
    torch.set_num_threads(2)
    device = torch.device("cuda")
    output = args.experiment / "fasterrcnn-mobilenetv3-320"
    output.mkdir(exist_ok=True)
    weights_file = output / "model.pt"
    model = make_model(pretrained=not args.eval_only).to(device)
    if args.eval_only:
        model.load_state_dict(torch.load(weights_file, map_location=device, weights_only=True))
    else:
        train = ReviewedPatches(args.experiment / "dataset", "train")
        optimizer = torch.optim.SGD((p for p in model.parameters() if p.requires_grad),
                                    lr=0.002, momentum=0.9, weight_decay=0.0005)
        for epoch in range(args.epochs):
            model.train()
            total = 0.0
            order = torch.randperm(len(train)).tolist()
            started = time.monotonic()
            for index in order:
                image, target = train[index]
                losses = model([image.to(device)], [{k: v.to(device) for k, v in target.items()}])
                loss = sum(losses.values())
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
                total += loss.item()
            print(f"epoch {epoch + 1}/{args.epochs} loss={total / len(train):.4f} "
                  f"seconds={time.monotonic() - started:.1f} "
                  f"gpu_peak_mb={torch.cuda.max_memory_allocated() / 1048576:.0f}", flush=True)
        torch.save(model.cpu().state_dict(), weights_file)
        model.to(device)
    model.eval()
    by_frame = reviewed_boxes(args.index)
    rows, timings = [], []
    for frame_path, references in sorted(by_frame.items()):
        references = [r for r in references if r["video"] in TEST_VIDEOS]
        if not references:
            continue
        frame = cv2.imread(frame_path)
        if frame is None:
            raise ValueError(frame_path)
        started = time.monotonic()
        detections = predict_tiles(model, frame, device)
        timings.append(time.monotonic() - started)
        preview = cv2.resize(frame, (1280, round(frame.shape[0] * 1280 / frame.shape[1])))
        scale = 1280 / frame.shape[1]
        for detection in detections:
            x0, y0, x1, y1 = [round(v * scale) for v in detection["box"]]
            cv2.rectangle(preview, (x0, y0), (x1, y1), (0, 225, 0), 2)
        for reference in references:
            x0, y0, x1, y1 = [round(v * scale) for v in reference["box"]]
            cv2.rectangle(preview, (x0, y0), (x1, y1), (0, 0, 255), 2)
        cv2.imwrite(str(output / f"unseen-{Path(frame_path).stem}.jpg"), preview)
        for reference in references:
            best = max((intersection_over_union(reference["box"], d["box"])
                        for d in detections), default=0)
            rows.append({"review_id": reference["id"], "video": reference["video"],
                         "best_full_frame_iou": round(best, 4),
                         "detected_boxes_in_frame": len(detections)})
    report = {
        "model": "Faster R-CNN MobileNetV3 320, COCO pretrained, 2 classes",
        "dataset": "same isolated reviewed patches and unseen VODs as YOLO locator",
        "training_epochs": args.epochs,
        "full_frame_reviewed_box_count": len(rows),
        "full_frame_hits_iou_0_5": sum(row["best_full_frame_iou"] >= 0.5 for row in rows),
        "tiled_inference_mean_seconds_per_frame": round(sum(timings) / len(timings), 3),
        "rows": rows,
        "limitations": ["Only four reviewed boxes in unseen VODs; other visible units are not exhaustively annotated.",
                        "This is generic unit localization, not champion naming."],
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
