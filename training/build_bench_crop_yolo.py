"""Export reviewed reserve-unit boxes as high-resolution YOLO tiles.

Names are deliberately excluded: this dataset only teaches localization.  No
model prediction is used as a label.  Entire match/video groups stay in one
split; media and exported tiles must remain outside the repository.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import tempfile

import cv2
import yaml


TILES = {
    "ally": [(280, 650, 980, 890), (920, 650, 1620, 890)],
    "opponent": [(400, 20, 1100, 220), (900, 20, 1600, 220)],
}


def _reviewed_bar_matches(image, tile, boxes):
    """Conservatively reject ally tiles with missing unit-body annotations.

    A bar is a pixel check, never a generated label. Some bars can be missed by
    this check, so the resulting set is only a safer subset, not full truth.
    """
    x0, y0, x1, y1 = tile
    hsv = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (30, 90, 65), (95, 255, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1)))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    bars = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if 58 <= width <= 72 and 3 <= height <= 8 and y < 125:
            bars.append((x + x0, y + y0, width))
    if len(bars) != len(boxes):
        return False
    for bx0, by0, bx1, _ in boxes:
        cx = (bx0 + bx1) / 2
        if not any(abs(cx - (x + width / 2)) <= 14 and
                   abs(by0 - (y + 8)) <= 14 for x, y, width in bars):
            return False
    return True


def _frame(video: Path, second: float, output: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(second), "-i", str(video),
         "-frames:v", "1", "-y", str(output)], check=True, timeout=30,
    )


def _write_tiles(image, boxes, side, split, stem, output, counts, audit):
    for tile_index, (x0, y0, x1, y1) in enumerate(TILES[side]):
        crop = image[y0:y1, x0:x1]
        if crop.size == 0:
            raise ValueError("Invalid tile")
        width, height = x1 - x0, y1 - y0
        lines = []
        included = []
        for bx0, by0, bx1, by1 in boxes:
            # A clipped unit can look like a different object.  Include only
            # boxes whose full body is inside the tile.
            if not (x0 <= bx0 < bx1 <= x1 and y0 <= by0 < by1 <= y1):
                continue
            included.append((bx0, by0, bx1, by1))
            lines.append(f"0 {((bx0+bx1)/2-x0)/width:.8f} "
                         f"{((by0+by1)/2-y0)/height:.8f} "
                         f"{(bx1-bx0)/width:.8f} {(by1-by0)/height:.8f}")
        # A zero-box ally tile is not safe negative evidence: some source
        # annotations omit visible units, and bars can be obscured by effects.
        if side == "ally" and (not included or not _reviewed_bar_matches(
                image, (x0, y0, x1, y1), included)):
            counts[split]["ally_tiles_rejected_incomplete_or_uncertain"] += 1
            continue
        name = f"{stem}-{side}-{tile_index}"
        image_dir = output / "images" / split
        label_dir = output / "labels" / split
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(image_dir / f"{name}.jpg"), crop,
                           [cv2.IMWRITE_JPEG_QUALITY, 92]):
            raise RuntimeError("Tile write failed")
        (label_dir / f"{name}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
        counts[split]["tiles"] += 1
        counts[split][side + "_boxes"] += len(lines)
        audit.append({"image": name + ".jpg", "split": split, "side": side,
                      "tile": [x0, y0, x1, y1], "boxes": len(lines)})


def build(annotations: Path, opponent_manifest: Path, video_root: Path, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    reviewed = json.loads(annotations.read_text())
    opponents = json.loads(opponent_manifest.read_text())
    if opponents.get("review_method") != "assistant_visual_review":
        raise ValueError("Opponent labels lack visual review")
    counts = {split: Counter() for split in ("train", "val", "test")}
    audit = []
    for index, row in enumerate(reviewed["frames"]):
        boxes = [unit["box"] for unit in row.get("layout", {}).get("units", [])
                 if unit.get("zone") == "bench"]
        if not boxes:
            continue
        split = {"validation": "val", "train": "train", "test": "test"}[row["identity_split"]]
        image_path = annotations.parent / "images" / row["image"]
        image = cv2.imread(str(image_path))
        if image is None or image.shape[:2] != (1080, 1920):
            raise ValueError(f"Invalid reviewed image: {image_path}")
        _write_tiles(image, boxes, "ally", split, f"review-{index:04d}", output, counts, audit)
    sources = {split: set() for split in counts}
    with tempfile.TemporaryDirectory(dir=output) as temp:
        for scene_index, scene in enumerate(opponents["scenes"]):
            split, source = scene["split"], scene["source"]
            if split not in counts or Path(source).is_absolute() or ".." in Path(source).parts:
                raise ValueError("Invalid opponent source or split")
            video = video_root / source
            sources[split].add(source)
            boxes = [box[1:] for box in scene["boxes"]]
            for second in scene["seconds"]:
                frame_path = Path(temp) / "frame.jpg"
                _frame(video, second, frame_path)
                image = cv2.imread(str(frame_path))
                if image is None or image.shape[:2] != (1080, 1920):
                    raise ValueError(f"Invalid opponent frame: {source} {second}")
                _write_tiles(image, boxes, "opponent", split,
                             f"opponent-{scene_index:03d}-{int(second*1000):08d}",
                             output, counts, audit)
    for left in sources:
        for right in sources:
            if left != right and sources[left] & sources[right]:
                raise ValueError("Video leaked across splits")
    (output / "data.yaml").write_text(yaml.safe_dump({
        "path": str(output), "train": "images/train", "val": "images/val",
        "test": "images/test", "names": {0: "bench_unit"}}, sort_keys=False))
    result = {"counts": {split: dict(counts[split]) for split in counts},
              "identity_labels": False, "model_predictions_used_as_labels": False,
              "independent_human_ground_truth": False,
              "opponent_video_groups": {k: sorted(v) for k, v in sources.items()},
              "limitations": ["Reviewed boxes may omit visible units.",
                              "Nearby seconds from a single video are correlated.",
                              "Reserve geometry assumes 1920x1080 replay frames."],
              "tiles": audit}
    (output / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--opponent-manifest", type=Path, required=True)
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.annotations, args.opponent_manifest,
                           args.video_root, args.output)["counts"]))


if __name__ == "__main__":
    main()
