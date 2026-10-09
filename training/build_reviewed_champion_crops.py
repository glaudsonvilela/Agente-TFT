#!/usr/bin/env python3
"""Export visually verified board and bench crops for YOLO classification."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from pathlib import Path

from PIL import Image


def build(manifest: Path, video_root: Path, output: Path) -> dict:
    document = json.loads(manifest.read_text(encoding="utf-8"))
    if document.get("review_method") != "assistant_visual_review":
        raise ValueError("Labels must be visually reviewed")
    classes = document["classes"]
    if len(classes) != len(set(classes)):
        raise ValueError("Duplicate class name")
    counts: dict[str, Counter[str]] = {split: Counter() for split in ("train", "val", "test")}
    sources: dict[str, set[str]] = {split: set() for split in counts}
    for index, row in enumerate(document["crops"]):
        split, name, source = row["split"], row["class"], row["source"]
        if split not in counts or name not in classes or row.get("reviewed") is not True:
            raise ValueError(f"Invalid or unreviewed crop at index {index}")
        if source.startswith("/") or ".." in Path(source).parts:
            raise ValueError(f"Source escapes video root: {source}")
        if not (video_root / source).is_file():
            raise FileNotFoundError(video_root / source)
        if float(row["second"]) < 0:
            raise ValueError(f"Negative timestamp at index {index}")
        sources[split].add(source)
    for left in sources:
        for right in sources:
            if left != right and sources[left] & sources[right]:
                raise ValueError(f"Source overlap between {left} and {right}")
    output.mkdir(parents=True, exist_ok=True)
    exported = []
    for index, row in enumerate(document["crops"]):
        split, name, source = row["split"], row["class"], row["source"]
        video = video_root / source
        second = float(row["second"])
        frame = output / f".frame-{index:06d}.png"
        try:
            subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-ss", f"{second:.3f}",
                 "-i", str(video), "-frames:v", "1", "-y", str(frame)],
                check=True,
                timeout=45,
            )
            with Image.open(frame) as image:
                width, height = image.size
                x1, y1, x2, y2 = map(int, row["box"])
                if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                    raise ValueError(f"Invalid crop box at index {index}: {row['box']}")
                crop = image.crop((x1, y1, x2, y2)).convert("RGB")
                destination = output / split / name / (
                    f"{Path(source).stem}-{int(second * 1000):09d}-{index:04d}.jpg"
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                crop.save(destination, quality=95)
        finally:
            frame.unlink(missing_ok=True)
        counts[split][name] += 1
        exported.append(
            {"class": name, "source": source, "second": second, "box": row["box"],
             "split": split, "image": str(destination.relative_to(output)),
             "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
        )
    report = {
        "classes": classes,
        "counts": {split: dict(count) for split, count in counts.items()},
        "sources": {split: sorted(group) for split, group in sources.items()},
        "independent_human_ground_truth": False,
        "model_predictions_used_as_labels": False,
        "crops": exported,
    }
    (output / "provenance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.manifest, args.video_root, args.output)
    print(json.dumps(report["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
