"""Build an experimental enemy detector dataset from real combat footage.

Red health bars provide geometric proposals, not reviewed ground truth or
champion identities. Entire source videos stay in one split.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import cv2
import yaml

from training.watch_tft_yolo_replay import enemy_health_bar_candidates


def yolo_box(box, width=1920, height=1080):
    x0, y0, x1, y1 = box
    return f"0 {(x0+x1)/(2*width):.8f} {(y0+y1)/(2*height):.8f} {(x1-x0)/width:.8f} {(y1-y0)/height:.8f}"


def build(sources, output: Path, start: int, stop: int, step: int):
    output.mkdir(parents=True, exist_ok=True)
    audit = []
    counts = {split: Counter() for split in ("train", "val", "test")}
    for source_number, (split, video) in enumerate(sources):
        capture = cv2.VideoCapture(str(video))
        if not capture.isOpened():
            raise RuntimeError(f"Cannot open {video}")
        duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / capture.get(cv2.CAP_PROP_FPS)
        if not 0 < duration < 100000:
            raise ValueError(f"Invalid video duration: {video}")
        times = range(start, min(stop, int(duration) - 3), step)
        for index, second in enumerate(times):
            capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
            ok, frame = capture.read()
            if not ok or frame.shape[:2] != (1080, 1920):
                continue
            proposals = enemy_health_bar_candidates(frame, [])
            if len(proposals) < 2:
                continue
            image_dir = output / "images" / split
            label_dir = output / "labels" / split
            image_dir.mkdir(parents=True, exist_ok=True)
            label_dir.mkdir(parents=True, exist_ok=True)
            stem = f"source{source_number:02d}-{second:05d}"
            cv2.imwrite(str(image_dir / f"{stem}.jpg"), frame,
                        [cv2.IMWRITE_JPEG_QUALITY, 87])
            (label_dir / f"{stem}.txt").write_text("\n".join(
                yolo_box(row["box"]) for row in proposals) + "\n")
            audit.append({"video": str(video), "second": second, "split": split,
                          "image": stem + ".jpg", "proposals": proposals,
                          "label_source": "red_health_bar_geometry_not_human_review"})
            counts[split]["frames"] += 1
            counts[split]["boxes"] += len(proposals)
            if index % 20 == 0:
                print(f"{split} {video.name}: {index+1}/{len(times)}", flush=True)
        capture.release()
    (output / "data.yaml").write_text(yaml.safe_dump({
        "path": str(output), "train": "images/train", "val": "images/val",
        "test": "images/test", "names": {0: "enemy_unit"}}, sort_keys=False))
    (output / "audit.json").write_text(json.dumps({
        "label_kind": "pixel_proposal_not_human_ground_truth",
        "source_video_groups": {split: [str(video) for s, video in sources if s == split]
                                for split in ("train", "val", "test")},
        "counts": {key: dict(value) for key, value in counts.items()},
        "frames": audit,
    }, ensure_ascii=False, indent=2))
    print(json.dumps({key: dict(value) for key, value in counts.items()}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", action="append", required=True,
                        help="train:/video.mp4, val:/video.mp4 or test:/video.mp4")
    parser.add_argument("--start", type=int, default=180)
    parser.add_argument("--stop", type=int, default=1800)
    parser.add_argument("--step", type=int, default=18)
    args = parser.parse_args()
    sources = []
    for source in args.source:
        split, path = source.split(":", 1)
        if split not in ("train", "val", "test"):
            parser.error(f"Invalid split: {split}")
        sources.append((split, Path(path)))
    if {split for split, _ in sources} != {"train", "val", "test"}:
        parser.error("At least one source is required for each split")
    build(sources, args.output, args.start, args.stop, args.step)


if __name__ == "__main__":
    main()
