"""Build a YOLO detection set from manually reviewed video frames and boxes.

The manifest is the sole source of labels. This exporter never imports model
predictions as training truth. Keep source videos and extracted frames on SSD.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def build(manifest: Path, video_root: Path, output: Path) -> dict:
    document = json.loads(manifest.read_text(encoding="utf-8"))
    if document.get("review_method") != "assistant_visual_review":
        raise ValueError("Every label must be visually reviewed")
    classes = document["classes"]
    if len(classes) != len(set(classes)):
        raise ValueError("Duplicate classes")
    counts = {split: {"frames": 0, "boxes": 0} for split in ("train", "val", "test")}
    sources_by_split = {split: set() for split in counts}
    rows = []
    frames = list(document.get("frames", []))
    for scene in document.get("scenes", []):
        for second in scene["seconds"]:
            frames.append({**{key: value for key, value in scene.items() if key != "seconds"},
                           "second": second})
    for row in frames:
        split = row["split"]
        if split not in counts:
            raise ValueError(f"Unknown split: {split}")
        source = row["source"]
        if source.startswith("/") or ".." in Path(source).parts:
            raise ValueError(f"Source path escapes video root: {source}")
        source_path = video_root / source
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        if row.get("reviewed") is not True:
            raise ValueError(f"Unreviewed frame: {source} at {row['second']}")
        second = float(row["second"])
        if second < 0:
            raise ValueError("Negative timestamp")
        name = f"{Path(source).stem}-{int(second * 1000):08d}"
        image = output / "images" / split / f"{name}.jpg"
        label = output / "labels" / split / f"{name}.txt"
        image.parent.mkdir(parents=True, exist_ok=True)
        label.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(second), "-i", str(source_path),
             "-frames:v", "1", "-y", str(image)],
            check=True, timeout=30,
        )
        if not image.is_file() or image.stat().st_size == 0:
            raise ValueError(f"Frame extraction failed: {source} at {second}")
        from PIL import Image

        with Image.open(image) as im:
            width, height = im.size
        lines = []
        for box in row["boxes"]:
            label_name, x1, y1, x2, y2 = box
            if label_name not in classes or not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise ValueError(f"Invalid box in {source} at {second}: {box}")
            cx, cy = (x1 + x2) / (2 * width), (y1 + y2) / (2 * height)
            bw, bh = (x2 - x1) / width, (y2 - y1) / height
            lines.append(f"{classes.index(label_name)} {cx:.8f} {cy:.8f} {bw:.8f} {bh:.8f}")
        label.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        counts[split]["frames"] += 1
        counts[split]["boxes"] += len(lines)
        sources_by_split[split].add(source)
        rows.append({"source": source, "second": second, "split": split,
                     "image": str(image), "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                     "boxes": row["boxes"]})
    for left in counts:
        for right in counts:
            if left != right and sources_by_split[left] & sources_by_split[right]:
                raise ValueError(f"Video appears in both {left} and {right}")
    yaml = "path: " + str(output.resolve()) + "\n"
    yaml += "train: images/train\nval: images/val\ntest: images/test\n"
    yaml += "names:\n" + "".join(f"  {i}: {name}\n" for i, name in enumerate(classes))
    (output / "data.yaml").write_text(yaml, encoding="utf-8")
    report = {"classes": classes, "counts": counts,
              "independent_human_ground_truth": False,
              "model_predictions_used_as_labels": False,
              "source_group_split": {k: sorted(v) for k, v in sources_by_split.items()},
              "frames": rows}
    (output / "provenance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--video-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.manifest, args.video_root, args.output)["counts"]))


if __name__ == "__main__":
    main()
