"""Export reviewed TFT scene frames for YOLO image classification."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def build(manifest: Path, video_root: Path, output: Path) -> dict:
    document = json.loads(manifest.read_text(encoding="utf-8"))
    if document.get("review_method") != "assistant_visual_review":
        raise ValueError("Expected reviewed frames")
    classes = set(document["classes"])
    counts = {split: {name: 0 for name in classes} for split in ("train", "val", "test")}
    sources = {split: set() for split in counts}
    frames = []
    for scene in document["scenes"]:
        split, category, source = scene["split"], scene["class"], scene["source"]
        if split not in counts or category not in classes or scene.get("reviewed") is not True:
            raise ValueError(f"Invalid scene: {scene}")
        if source.startswith("/") or ".." in Path(source).parts:
            raise ValueError(f"Source path escapes video root: {source}")
        video = video_root / source
        if not video.is_file():
            raise FileNotFoundError(video)
        sources[split].add(source)
        for second in scene["seconds"]:
            if float(second) < 0:
                raise ValueError("Negative timestamp")
            name = f"{Path(source).stem}-{int(float(second) * 1000):08d}.jpg"
            image = output / split / category / name
            image.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-v", "error", "-ss", str(second), "-i",
                            str(video), "-frames:v", "1", "-y", str(image)],
                           check=True, timeout=30)
            if not image.is_file() or not image.stat().st_size:
                raise ValueError(f"Frame extraction failed: {source} {second}")
            counts[split][category] += 1
            frames.append({"source": source, "second": second, "split": split,
                           "class": category, "sha256": hashlib.sha256(image.read_bytes()).hexdigest()})
    for left in counts:
        for right in counts:
            if left != right and sources[left] & sources[right]:
                raise ValueError(f"Source overlap: {left} and {right}")
    report = {"classes": sorted(classes), "counts": counts,
              "independent_human_ground_truth": False,
              "model_predictions_used_as_labels": False,
              "source_group_split": {k: sorted(v) for k, v in sources.items()},
              "frames": frames}
    (output / "provenance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                             encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.manifest, args.video_root, args.output)["counts"]))


if __name__ == "__main__":
    main()
