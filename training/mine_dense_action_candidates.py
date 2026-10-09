"""Rank adjacent 1080p VOD frames for visual action review.

The scores describe pixel changes, not player actions. Every pair stays in the
queue so a reviewer can find missed actions and inspect false positives.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


REGIONS = {
    "stage": (740, 0, 825, 43),
    "gold": (1004, 873, 1060, 918),
    "xp": (345, 874, 545, 924),
    "shop": (552, 925, 1557, 1080),
    "bench": (335, 665, 1535, 840),
    "board": (575, 230, 1450, 665),
    "items": (0, 250, 105, 835),
    "opponents": (1690, 160, 1920, 815),
}


def read_regions(path: Path) -> dict[str, np.ndarray]:
    with Image.open(path) as image:
        if image.size != (1920, 1080):
            raise ValueError(f"expected native 1920x1080 frame: {path}")
        pixels = np.asarray(image.convert("L"), dtype=np.uint8)
    return {name: pixels[y1:y2, x1:x2] for name, (x1, y1, x2, y2) in REGIONS.items()}


def mean_absolute_change(before: np.ndarray, after: np.ndarray) -> float:
    return float(np.abs(before.astype(np.int16) - after.astype(np.int16)).mean() / 255)


def mine(frames_dir: Path, output: Path) -> list[dict]:
    frames = sorted(frames_dir.glob("frame-*.jpg"))
    if len(frames) < 2:
        raise ValueError("at least two numbered frames are required")
    numbers = [int(path.stem.split("-")[-1]) for path in frames]
    if numbers != list(range(numbers[0], numbers[-1] + 1)):
        raise ValueError("frame sequence has a gap")
    if output.exists():
        raise ValueError("use a new output path")

    rows = []
    previous = read_regions(frames[0])
    for before_path, after_path in zip(frames, frames[1:]):
        current = read_regions(after_path)
        change = {key: round(mean_absolute_change(previous[key], current[key]), 5)
                  for key in REGIONS}
        rows.append({
            "before_frame": before_path.name,
            "after_frame": after_path.name,
            "region_change": change,
            "review_priority": round(change["shop"] + change["gold"] +
                                     0.25 * change["bench"], 5),
            "executed_action_label": None,
            "review_status": "unreviewed_visual_transition",
        })
        previous = current
    for region in REGIONS:
        for rank, row in enumerate(sorted(rows,
                                           key=lambda candidate: candidate["region_change"][region],
                                           reverse=True), 1):
            row.setdefault("review_rank_by_region", {})[region] = rank
    rows.sort(key=lambda row: row["review_priority"], reverse=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows = mine(args.frames_dir, args.output)
    print(f"{len(rows)} transições para revisão; 0 ações rotuladas automaticamente", flush=True)


if __name__ == "__main__":
    main()
