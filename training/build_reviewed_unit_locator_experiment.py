"""Build a one-class YOLO locator from reviewed TFT body boxes.

This is an isolated localization experiment. Only human or in-game confirmed
boxes are labels. Cropping around a reviewed unit reduces, but cannot eliminate,
the incomplete-label problem in crowded source frames.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

import cv2


VALIDATION_VIDEO = "QUiyk-mfoBs.webm"
TEST_VIDEOS = {"8W7Wfnf36M8.webm", "-YQHDFlMRRs.webm"}


def reviewed_boxes(index_path: Path) -> dict[str, list[dict]]:
    index = json.loads(index_path.read_text())
    if index.get("model_predictions_used_as_labels") is not False:
        raise ValueError("Source index has no reviewed-label guarantee")
    by_frame: dict[str, list[dict]] = defaultdict(list)
    manifests = {}
    for row in index["records"]:
        if row["review_status"] not in {"user_confirmed_candidate", "ui_confirmed_candidate"}:
            continue
        path = row["manifest"]
        if path not in manifests:
            manifests[path] = json.loads(Path(path).read_text())
        for candidate in manifests[path].get("records", manifests[path].get("crops", [])):
            if str(candidate.get("id")) != str(row["review_id"]):
                continue
            box = candidate.get("source_pixel_box", candidate.get("box_source_3840"))
            frame = candidate.get("source_frame")
            if box and frame and Path(frame).is_file():
                by_frame[frame].append({"id": row["review_id"],
                                        "box": tuple(box),
                                        "video": Path(row["source_video_local"]).name})
            break
    return by_frame


def crop_rectangle(box: tuple[int, ...], shape: tuple[int, ...],
                   factor: float) -> tuple[int, int, int, int]:
    height, width = shape[:2]
    x0, y0, x1, y1 = box
    crop_w = min(width, max(128, round((x1 - x0) * factor)))
    crop_h = min(height, max(128, round((y1 - y0) * factor)))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left = max(0, min(width - crop_w, round(cx - crop_w / 2)))
    top = max(0, min(height - crop_h, round(cy - crop_h / 2)))
    return left, top, left + crop_w, top + crop_h


def normalized_label(box: tuple[int, ...], crop: tuple[int, ...]) -> str | None:
    x0, y0, x1, y1 = box
    left, top, right, bottom = crop
    ax0, ay0 = max(x0, left), max(y0, top)
    ax1, ay1 = min(x1, right), min(y1, bottom)
    overlap = max(0, ax1 - ax0) * max(0, ay1 - ay0)
    if overlap < (x1 - x0) * (y1 - y0) * 0.5:
        return None
    crop_w, crop_h = right - left, bottom - top
    cx = ((ax0 + ax1) / 2 - left) / crop_w
    cy = ((ay0 + ay1) / 2 - top) / crop_h
    w, h = (ax1 - ax0) / crop_w, (ay1 - ay0) / crop_h
    return f"0 {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    by_frame = reviewed_boxes(args.index)
    counts = Counter()
    examples = []
    for frame_path, records in sorted(by_frame.items()):
        image = cv2.imread(frame_path)
        if image is None:
            raise RuntimeError(f"Cannot read reviewed source frame: {frame_path}")
        videos = {row["video"] for row in records}
        if len(videos) != 1:
            raise ValueError(f"Mixed videos for source frame: {frame_path}")
        video = videos.pop()
        split = ("test" if video in TEST_VIDEOS else
                 "val" if video == VALIDATION_VIDEO else "train")
        # Keep patches close to their reviewed single-body crop. Wide patches
        # introduce other unreviewed units as accidental background labels.
        factors = (1.25, 1.5, 1.75) if split == "train" else (1.5,)
        for row in records:
            for variation, factor in enumerate(factors):
                region = crop_rectangle(row["box"], image.shape, factor)
                left, top, right, bottom = region
                labels = [label for candidate in records
                          if (label := normalized_label(candidate["box"], region))]
                if not labels:
                    raise ValueError(f"No label for reviewed unit {row['id']}")
                stem = f"{int(row['id']):03d}-{variation}"
                image_path = args.output / "dataset/images" / split / f"{stem}.jpg"
                label_path = args.output / "dataset/labels" / split / f"{stem}.txt"
                image_path.parent.mkdir(parents=True, exist_ok=True)
                label_path.parent.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(str(image_path), image[top:bottom, left:right],
                                   [cv2.IMWRITE_JPEG_QUALITY, 94]):
                    raise RuntimeError(f"Cannot write {image_path}")
                label_path.write_text("\n".join(labels) + "\n")
                counts[split] += 1
                examples.append({"review_id": row["id"], "video": video,
                                 "split": split, "factor": factor,
                                 "source_box": row["box"], "source_crop": region,
                                 "labels_in_patch": len(labels)})
    if counts != {"train": 135, "val": 10, "test": 4}:
        raise ValueError(f"Unexpected split counts: {counts}")
    dataset = (args.output / "dataset").resolve()
    (dataset / "data.yaml").write_text(
        f"path: {dataset}\ntrain: images/train\nval: images/val\ntest: images/test\n"
        "names:\n  0: unit\n")
    provenance = {"scope": "experimental_one_class_unit_locator",
                  "model_predictions_used_as_labels": False,
                  "old_tft_weights_used": False,
                  "independent_reviewed_source_boxes": 59,
                  "patches": dict(counts),
                  "validation_video": VALIDATION_VIDEO,
                  "test_videos": sorted(TEST_VIDEOS),
                  "limitation": "Other unreviewed units may appear inside a cropped patch.",
                  "examples": examples}
    (args.output / "provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in provenance.items()
                      if key != "examples"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
