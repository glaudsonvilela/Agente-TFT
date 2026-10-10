"""Draw both detector outputs on unseen TFT frames using the same region protocol."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import torch
import yaml
from torchvision.ops import nms
from ultralytics import YOLO

from build_joint_hud_unit_experiment import ROI
from compare_torchvision_unit_detector import make_model
from evaluate_joint_hud_unit_experiment import predict
from evaluate_reviewed_unit_locator_experiment import intersection_over_union, starts
from build_reviewed_unit_locator_experiment import reviewed_boxes


@torch.inference_mode()
def body_tiles(architecture, model, frame):
    # Restrict the generic body proposal pass to the game board/bench geometry.
    # HUD passes run separately at the native 1920x1080 layout scale.
    height, width = frame.shape[:2]
    x0, y0, x1, y1 = (round(v) for v in
                      (width*170/1920, height*120/1080,
                       width*1700/1920, height*860/1080))
    board = frame[y0:y1, x0:x1]
    boxes, scores = [], []
    tile, stride = 512, 416
    for top in starts(board.shape[0], tile, stride):
        for left in starts(board.shape[1], tile, stride):
            bgr = board[top:top+tile, left:left+tile]
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            image = torch.from_numpy(rgb.copy()).permute(2, 0, 1).float() / 255
            for category, box, score in predict(architecture, model, image):
                if category != 0:
                    continue
                bx0, by0, bx1, by1 = box
                boxes.append((bx0+left+x0, by0+top+y0,
                              bx1+left+x0, by1+top+y0))
                scores.append(score)
    if not boxes:
        return []
    keep = nms(torch.tensor(boxes, dtype=torch.float32),
               torch.tensor(scores), 0.5).tolist()
    return [{"box": boxes[i], "confidence": round(scores[i], 4)} for i in keep]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--model", choices=("yolo", "faster"), required=True)
    args = parser.parse_args()
    classes = yaml.safe_load((args.dataset / "data.yaml").read_text())["names"]
    if args.model == "yolo":
        model = YOLO(str(args.dataset / "runs/joint-yolo11n/weights/best.pt"))
    else:
        model = make_model(pretrained=False, num_classes=len(classes)+1).cuda()
        state = torch.load(args.dataset / "runs/joint-fasterrcnn-mobilenetv3/model.pt",
                           map_location="cuda", weights_only=True)
        model.load_state_dict(state)
        model.eval()
    reviewed = reviewed_boxes(args.index)
    manifest = json.loads((args.dataset / "provenance.json").read_text())
    output = args.dataset / "previews" / f"predictions-{args.model}"
    output.mkdir(parents=True, exist_ok=True)
    report = []
    for source in manifest["sources"]:
        if source["split"] != "test":
            continue
        frame_path = source["source_frame"]
        frame = cv2.imread(frame_path)
        native = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_AREA)
        canvas = cv2.resize(frame, (1280, 720), interpolation=cv2.INTER_AREA)
        started = time.monotonic()
        hud_rows = []
        for region, references in source["region_labels"].items():
            rx0, ry0, rx1, ry1 = ROI[region]
            crop = native[ry0:ry1, rx0:rx1]
            rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            image = torch.from_numpy(rgb.copy()).permute(2, 0, 1).float() / 255
            detected = predict(args.model, model, image)
            expected_classes = {classes.index(r["class"]) if isinstance(classes, list)
                                else next(i for i, name in classes.items() if name == r["class"])
                                for r in references}
            detected = [(category, (box[0]+rx0, box[1]+ry0, box[2]+rx0, box[3]+ry0), score)
                        for category, box, score in detected if category in expected_classes]
            for category, box, score in detected:
                x0, y0, x1, y1 = [round(v*2/3) for v in box]
                cv2.rectangle(canvas, (x0, y0), (x1, y1), (0, 220, 255), 2)
            for reference in references:
                box = reference["box_1920"]
                category = next(i for i, name in classes.items() if name == reference["class"])
                best = max((intersection_over_union(tuple(box), pred)
                            for found_class, pred, _ in detected if found_class == category), default=0)
                hud_rows.append({"class": reference["class"], "best_iou": round(best, 4)})
        bodies = body_tiles(args.model, model, frame)
        sx, sy = 1280 / frame.shape[1], 720 / frame.shape[0]
        for row in bodies:
            x0, y0, x1, y1 = row["box"]
            cv2.rectangle(canvas, (round(x0*sx), round(y0*sy)),
                          (round(x1*sx), round(y1*sy)), (0, 220, 0), 2)
        references = reviewed[frame_path]
        body_rows = []
        for reference in references:
            box = reference["box"]
            x0, y0, x1, y1 = box
            cv2.rectangle(canvas, (round(x0*sx), round(y0*sy)),
                          (round(x1*sx), round(y1*sy)), (0, 0, 255), 2)
            best = max((intersection_over_union(box, row["box"]) for row in bodies), default=0)
            body_rows.append({"review_id": reference["id"], "best_iou": round(best, 4)})
        image_path = output / f"{Path(frame_path).stem}.jpg"
        cv2.imwrite(str(image_path), canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])
        report.append({"frame": Path(frame_path).name,
                       "seconds": round(time.monotonic()-started, 3),
                       "body_box_count": len(bodies),
                       "reviewed_body_hits_iou_0_5": sum(r["best_iou"] >= 0.5 for r in body_rows),
                       "reviewed_body_count": len(body_rows),
                       "hud_hits_iou_0_5": sum(r["best_iou"] >= 0.5 for r in hud_rows),
                       "hud_label_count": len(hud_rows),
                       "body_rows": body_rows,
                       "hud_rows": hud_rows,
                       "preview": str(image_path)})
    summary = {"model": args.model, "frames": report,
               "total_reviewed_body_hits": sum(r["reviewed_body_hits_iou_0_5"] for r in report),
               "total_reviewed_body_count": sum(r["reviewed_body_count"] for r in report),
               "total_hud_hits": sum(r["hud_hits_iou_0_5"] for r in report),
               "total_hud_label_count": sum(r["hud_label_count"] for r in report),
               "limitations": ["Non-reviewed visible units prevent a precision estimate.",
                               "HUD positions are layout/pixel proposals, not independently read values.",
                               "Only four reviewed body boxes in unseen source videos."]}
    (output / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "frames"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
