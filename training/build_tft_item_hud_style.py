"""Simulate source-resolution TFT item chips from pinned official artwork.

This tests domain adaptation to small, compressed HUD icons. Because every
class still comes from one artwork file, synthetic validation is not gameplay
accuracy. Real crops must be independently labeled before such a claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def sample(image, rng):
    side = int(rng.integers(21, 30))
    art = cv2.resize(image, (side, side), interpolation=cv2.INTER_AREA)
    art = art.astype(np.float32) * rng.uniform(0.64, 1.16)
    art += rng.normal(0, 3.5, art.shape)
    art = np.clip(art, 0, 255).astype(np.uint8)
    if rng.random() < 0.65:
        quality = int(rng.integers(55, 96))
        _, encoded = cv2.imencode(".jpg", art, [cv2.IMWRITE_JPEG_QUALITY, quality])
        art = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if rng.random() < 0.35:
        art = cv2.GaussianBlur(art, (3, 3), float(rng.uniform(0.2, 0.8)))
    canvas = np.full((36, 36, 3), rng.integers(4, 26, size=3), dtype=np.uint8)
    x = (36-side)//2 + int(rng.integers(-2, 3))
    y = (36-side)//2 + int(rng.integers(-2, 3))
    canvas[y:y+side, x:x+side] = art
    border = tuple(int(v) for v in rng.integers(28, 94, size=3))
    cv2.rectangle(canvas, (x-1, y-1), (x+side, y+side), border, 1)
    if rng.random() < 0.2:
        # An on-board effect may hide a narrow part of the icon.
        px = int(rng.integers(x, x+side))
        cv2.line(canvas, (px, y), (px, y+side-1), (85, 110, 135), 1)
    return canvas


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", type=Path)
    parser.add_argument("icon_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    classes = json.loads(args.metadata.read_text())["classes"]
    icons = {hashlib.sha256(path.read_bytes()).hexdigest(): path
             for path in args.icon_dir.glob("*.png")}
    rng = np.random.default_rng(20261009)
    mapping = []
    for index, row in enumerate(classes):
        source = next((icons[digest] for digest in row["source_sha256"] if digest in icons), None)
        if source is None:
            raise FileNotFoundError(f"No pinned artwork for class {index}")
        art = cv2.imread(str(source))
        if art is None:
            raise ValueError(f"Invalid icon: {source}")
        label = f"{index:03d}"
        for split, count in (("train", 36), ("val", 6)):
            destination = args.output / split / label
            destination.mkdir(parents=True, exist_ok=True)
            for number in range(count):
                cv2.imwrite(str(destination / f"{number:02d}.png"), sample(art, rng))
        mapping.append({"label": label, "ids": row["ids"], "names": row["names"],
                        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
    (args.output / "audit.json").write_text(json.dumps({
        "classes": mapping, "source": "official_artwork_small_HUD_style_simulation",
        "independent_gameplay_validation": False,
        "train_samples": 36*len(mapping), "val_samples": 6*len(mapping),
    }, ensure_ascii=False, indent=2))
    print(json.dumps({"classes": len(mapping), "train": 36*len(mapping),
                      "val": 6*len(mapping), "gameplay_validation": False}))


if __name__ == "__main__":
    main()
