"""Build an isolated HUD + reviewed-unit detector dataset.

HUD crops avoid treating incompletely labeled board units as background. Unit
patches come only from the previously reviewed source boxes. Layout anchors
are proposals and the generated preview must be visually audited before use.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import cv2
import yaml

from build_reviewed_unit_locator_experiment import TEST_VIDEOS, VALIDATION_VIDEO, reviewed_boxes
from build_unified_hud_yolo import SHOP_X, players


CLASSES = ("champion_body", "stage_display", "gold_display", "level_display",
           "xp_display", "player_hp_display", "shop_card")
LAYOUT = {"stage_display": (742, 0, 819, 42),
          "gold_display": (963, 873, 1101, 922),
          "level_display": (340, 875, 438, 913),
          "xp_display": (438, 875, 548, 923)}
ROI = {"top": (650, 0, 970, 100),
       "bottom": (300, 850, 1600, 1080),
       "right": (1690, 150, 1920, 850)}
EXCLUDE_BOTTOM = {"sivir-360-full.png", "8W7Wfnf36M8-1590-full.png",
                  "1500-full.png"}


def split_for_video(video: str) -> str:
    return "test" if video in TEST_VIDEOS else "val" if video == VALIDATION_VIDEO else "train"


def yolo_line(name: str, box: tuple[int, int, int, int], roi):
    rx0, ry0, rx1, ry1 = roi
    x0, y0, x1, y1 = box
    if not (rx0 <= x0 < x1 <= rx1 and ry0 <= y0 < y1 <= ry1):
        raise ValueError((name, box, roi))
    width, height = rx1 - rx0, ry1 - ry0
    return (f"{CLASSES.index(name)} {((x0+x1)/2-rx0)/width:.8f} "
            f"{((y0+y1)/2-ry0)/height:.8f} {(x1-x0)/width:.8f} {(y1-y0)/height:.8f}")


def hud_labels(image, region: str):
    labels = []
    if region == "top":
        labels.append(("stage_display", LAYOUT["stage_display"]))
    elif region == "bottom":
        for name in ("gold_display", "level_display", "xp_display"):
            labels.append((name, LAYOUT[name]))
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        for x in SHOP_X:
            art = gray[940:1020, x+15:x+170]
            if art.mean() > 25 and art.std() > 18:
                labels.append(("shop_card", (x, 928, x+192, 1079)))
    elif region == "right":
        circles = players(image)
        if len(circles) < 6:
            return []
        for x, y, _ in circles:
            labels.append(("player_hp_display", (x-63, y-17, x-26, y+16)))
    return labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--unit-dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    counts = {split: Counter() for split in ("train", "val", "test")}
    sources = []
    for split in counts:
        for source in sorted((args.unit_dataset / "images" / split).glob("*.jpg")):
            image_dir = args.output / "images" / split
            label_dir = args.output / "labels" / split
            image_dir.mkdir(parents=True, exist_ok=True)
            label_dir.mkdir(parents=True, exist_ok=True)
            (image_dir / f"unit-{source.name}").symlink_to(source.resolve())
            label = args.unit_dataset / "labels" / split / f"{source.stem}.txt"
            target = label_dir / f"unit-{source.stem}.txt"
            target.write_text(label.read_text())
            counts[split]["champion_body"] += len(label.read_text().splitlines())
    preview_dir = args.output / "previews"
    preview_dir.mkdir(parents=True)
    for frame_path, reviewed in sorted(reviewed_boxes(args.index).items()):
        video = reviewed[0]["video"]
        split = split_for_video(video)
        frame = cv2.imread(frame_path)
        if frame is None:
            raise ValueError(frame_path)
        image = cv2.resize(frame, (1920, 1080), interpolation=cv2.INTER_AREA)
        stem = Path(frame_path).stem
        canvas = image.copy()
        scale_x, scale_y = 1920 / frame.shape[1], 1080 / frame.shape[0]
        for row in reviewed:
            x0, y0, x1, y1 = row["box"]
            cv2.rectangle(canvas, (round(x0 * scale_x), round(y0 * scale_y)),
                          (round(x1 * scale_x), round(y1 * scale_y)), (60, 230, 60), 2)
        frame_record = {"source_frame": frame_path, "source_video": video,
                        "split": split, "region_labels": {}}
        for region, roi in ROI.items():
            if region == "bottom" and Path(frame_path).name in EXCLUDE_BOTTOM:
                continue
            labels = hud_labels(image, region)
            if not labels:
                continue
            rx0, ry0, rx1, ry1 = roi
            image_dir = args.output / "images" / split
            label_dir = args.output / "labels" / split
            image_dir.mkdir(parents=True, exist_ok=True)
            label_dir.mkdir(parents=True, exist_ok=True)
            target_stem = f"hud-{stem}-{region}"
            cv2.imwrite(str(image_dir / f"{target_stem}.jpg"), image[ry0:ry1, rx0:rx1],
                        [cv2.IMWRITE_JPEG_QUALITY, 94])
            (label_dir / f"{target_stem}.txt").write_text(
                "\n".join(yolo_line(name, box, roi) for name, box in labels) + "\n")
            frame_record["region_labels"][region] = [{"class": name, "box_1920": box}
                                                     for name, box in labels]
            for name, box in labels:
                counts[split][name] += 1
                x0, y0, x1, y1 = box
                cv2.rectangle(canvas, (x0, y0), (x1, y1), (0, 230, 255), 2)
        if frame_record["region_labels"]:
            cv2.imwrite(str(preview_dir / f"{stem}.jpg"),
                        cv2.resize(canvas, (1280, 720)), [cv2.IMWRITE_JPEG_QUALITY, 90])
        sources.append(frame_record)
    (args.output / "data.yaml").write_text(yaml.safe_dump({
        "path": str(args.output.resolve()), "train": "images/train",
        "val": "images/val", "test": "images/test",
        "names": dict(enumerate(CLASSES))}, sort_keys=False))
    report = {"scope": "isolated_joint_hud_unit_experiment",
              "classes": CLASSES, "counts": {k: dict(v) for k, v in counts.items()},
              "model_predictions_used_as_labels": False,
              "hud_labels": "layout_and_pixel_proposals_pending_visual_audit",
              "champion_labels": "previously_reviewed_source_boxes_in_crops",
              "limitations": ["HUD positions assume normalized 1920x1080 game layout.",
                              "Special overlays and hidden shop cards are excluded by frame.",
                              "Player HP is a localized number area, not a read HP value.",
                              "Champion bodies are generic localization boxes, not identity classes."],
              "sources": sources}
    (args.output / "provenance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "sources"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
