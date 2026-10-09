"""Build an auditable YOLO HUD experiment from reviewed TFT frames.

Visual anchors add localization labels only. They never supply champion names,
item identities, player names, or numeric values. Source match splits are kept.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import cv2
import yaml


CLASSES = (
    "board_unit",
    "bench_unit",
    "player_entry",
    "player_avatar",
    "stage_display",
    "gold_display",
    "level_display",
    "shop_offer",
)
WIDTH, HEIGHT = 1920, 1080
STAGE = (742, 0, 819, 42)
GOLD = (963, 873, 1101, 922)
LEVEL = (340, 875, 548, 921)
SHOP_X = (553, 754, 955, 1156, 1357)
SHOP_Y = (928, 1079)


def add_box(labels: list[tuple[int, tuple[int, int, int, int]]], name: str, box):
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(WIDTH, x1), min(HEIGHT, y1)
    if not (0 <= x0 < x1 <= WIDTH and 0 <= y0 < y1 <= HEIGHT):
        raise ValueError(f"Invalid {name} box: {box}")
    labels.append((CLASSES.index(name), (x0, y0, x1, y1)))


def players(image):
    """Locate visible circular player badges; require the actual ring pixels."""
    gray = cv2.cvtColor(image[:, 1720:], cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 1.4)
    found = cv2.HoughCircles(
        gray, cv2.HOUGH_GRADIENT, dp=1, minDist=53,
        param1=80, param2=35, minRadius=22, maxRadius=42,
    )
    if found is None:
        return []
    circles = sorted(
        ((int(round(x)) + 1720, int(round(y)), int(round(radius)))
         for x, y, radius in found[0]
         if 1830 <= x + 1720 <= 1905 and 160 <= y <= 815),
        key=lambda item: item[1],
    )
    output = []
    for x, y, radius in circles:
        if any(abs(y - earlier[1]) < 47 for earlier in output):
            continue
        output.append((x, y, radius))
    return output


def structural_labels(image, labels):
    add_box(labels, "stage_display", STAGE)
    add_box(labels, "gold_display", GOLD)
    add_box(labels, "level_display", LEVEL)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    for x in SHOP_X:
        art = gray[940:1020, x + 15:x + 170]
        if art.mean() > 25 and art.std() > 18:
            add_box(labels, "shop_offer", (x, SHOP_Y[0], x + 192, SHOP_Y[1]))
    for x, y, radius in players(image):
        add_box(labels, "player_avatar", (x-radius, y-radius, x+radius, y+radius))
        add_box(labels, "player_entry", (1680, y-radius-5, 1913, y+radius+5))


def yolo_line(class_id, box, width=WIDTH, height=HEIGHT):
    x0, y0, x1, y1 = box
    return f"{class_id} {(x0+x1)/(2*width):.8f} {(y0+y1)/(2*height):.8f} {(x1-x0)/width:.8f} {(y1-y0)/height:.8f}"


def add_panel_sources(output: Path, sources, counts, provenance):
    crop_x, crop_y, crop_width, crop_height = 1600, 130, 320, 720
    for source_id, (split, directory) in enumerate(sources):
        paths = sorted(directory.glob("*.jpg")) + sorted(directory.glob("*.png"))
        if not paths:
            raise ValueError(f"No source frames in {directory}")
        for index, path in enumerate(paths):
            image = cv2.imread(str(path))
            if image is None or image.shape[:2] != (HEIGHT, WIDTH):
                raise ValueError(f"Invalid source frame: {path}")
            circles = players(image)
            if len(circles) < 4:
                continue
            labels = []
            for x, y, radius in circles:
                for name, box in (
                    ("player_avatar", (x-radius, y-radius, x+radius, y+radius)),
                    ("player_entry", (1680, y-radius-5, 1913, y+radius+5)),
                ):
                    x0, y0, x1, y1 = box
                    x0, x1 = max(crop_x, x0), min(crop_x+crop_width, x1)
                    y0, y1 = max(crop_y, y0), min(crop_y+crop_height, y1)
                    if x1 > x0 and y1 > y0:
                        labels.append((CLASSES.index(name),
                                       (x0-crop_x, y0-crop_y, x1-crop_x, y1-crop_y)))
            stem = f"{split}-panel-{source_id:02d}-{index:05d}"
            image_dir = output / "images" / split
            label_dir = output / "labels" / split
            image_dir.mkdir(parents=True, exist_ok=True)
            label_dir.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(image_dir / f"{stem}.jpg"),
                        image[crop_y:crop_y+crop_height, crop_x:crop_x+crop_width],
                        [cv2.IMWRITE_JPEG_QUALITY, 85])
            (label_dir / f"{stem}.txt").write_text("\n".join(
                yolo_line(class_id, box, crop_width, crop_height) for class_id, box in labels) + "\n")
            counts[split].update(CLASSES[class_id] for class_id, _ in labels)
            provenance.append({"image": str(path), "split": split, "source_video_group": str(directory),
                               "boxes": len(labels), "hud_source": "hough_circle_pixel_proposal",
                               "unit_labels": False, "crop": [crop_x, crop_y, crop_width, crop_height]})


def build(annotation_path: Path, output: Path, panel_sources=()):
    source_root = annotation_path.parent / "images"
    records = json.loads(annotation_path.read_text())["frames"]
    counts = {split: Counter() for split in ("train", "val", "test")}
    provenance = []
    for index, record in enumerate(records):
        split = {"validation": "val", "train": "train", "test": "test"}[record["identity_split"]]
        if record["image_size"] != [WIDTH, HEIGHT]:
            raise ValueError(f"Unexpected resolution: {record['image']}")
        path = source_root / record["image"]
        image = cv2.imread(str(path))
        if image is None:
            raise FileNotFoundError(path)
        labels = []
        for unit in record.get("layout", {}).get("units", []):
            if unit["zone"] in ("board", "bench"):
                add_box(labels, f"{unit['zone']}_unit", unit["box"])
        if record["scene"] == "board":
            structural_labels(image, labels)
        stem = f"{split}-{index:04d}"
        image_dir = output / "images" / split
        label_dir = output / "labels" / split
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)
        target = image_dir / f"{stem}{path.suffix.lower()}"
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(path)
        (label_dir / f"{stem}.txt").write_text("\n".join(yolo_line(*value) for value in labels) + "\n")
        counts[split].update(CLASSES[class_id] for class_id, _ in labels)
        provenance.append({"image": record["image"], "split": split, "match_group": record["match_group"],
                           "boxes": len(labels), "board_bench_source": "assistant_visual_review",
                           "hud_source": "layout_projection_and_pixel_heuristic" if record["scene"] == "board" else None})
    add_panel_sources(output, panel_sources, counts, provenance)
    (output / "data.yaml").write_text(yaml.safe_dump({"path": str(output), "train": "images/train",
                                                     "val": "images/val", "test": "images/test",
                                                     "names": dict(enumerate(CLASSES))}, sort_keys=False))
    report = {"classes": CLASSES, "counts": {key: dict(value) for key, value in counts.items()},
              "frames": len(provenance), "reviewed_frames": len(records), "limitations": [
                  "Player circles are pixel proposals, not independently reviewed ground truth.",
                  "Fixed HUD positions apply only to 1920x1080 board frames with this layout.",
                  "YOLO boxes localize UI elements; they do not read values, names or item identities.",
                  "Some reviewed unit frames have incomplete boxes, creating possible false negatives.",
                  "Video panel crops contain only proposed avatar and row boxes; no player names or HP values.",
              ], "provenance": provenance}
    (output / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("annotations", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--panel-source", action="append", default=[],
                        help="Source split and directory: train:/path/to/frames")
    args = parser.parse_args()
    sources = []
    for value in args.panel_source:
        split, directory = value.split(":", 1)
        if split not in ("train", "val", "test"):
            parser.error(f"Invalid split: {split}")
        sources.append((split, Path(directory)))
    result = build(args.annotations, args.output, sources)
    print(json.dumps({"frames": result["frames"], "counts": result["counts"]}, ensure_ascii=False))
