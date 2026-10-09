"""Build a labeled item-art experiment from the pinned Riot icon catalog.

Synthetic variants in train and validation share the same original icon, so
validation here measures fit to artwork only, never in-game recognition.
"""

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def variant(image, generator):
    pixels = cv2.resize(image, (96, 96), interpolation=cv2.INTER_CUBIC)
    angle = generator.uniform(-8, 8)
    scale = generator.uniform(0.88, 1.06)
    center = (47.5, 47.5)
    matrix = cv2.getRotationMatrix2D(center, angle, scale)
    matrix[:, 2] += generator.uniform(-4, 4, size=2)
    pixels = cv2.warpAffine(pixels, matrix, (96, 96), flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_REPLICATE)
    pixels = pixels.astype(np.float32) * generator.uniform(0.78, 1.15)
    pixels += generator.normal(0, 2.5, size=pixels.shape)
    return np.clip(pixels, 0, 255).astype(np.uint8)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("metadata", type=Path)
    parser.add_argument("icon_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    classes = json.loads(args.metadata.read_text())["classes"]
    icons = {hashlib.sha256(path.read_bytes()).hexdigest(): path
             for path in args.icon_dir.glob("*.png")}
    mapping = []
    generator = np.random.default_rng(20261009)
    for index, row in enumerate(classes):
        source = next((icons[digest] for digest in row["source_sha256"] if digest in icons), None)
        if source is None:
            raise FileNotFoundError(f"No pinned artwork for item class {index}")
        image = cv2.imread(str(source))
        if image is None:
            raise ValueError(f"Invalid artwork: {source}")
        name = f"{index:03d}"
        mapping.append({"class": name, "ids": row["ids"], "names": row["names"],
                        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
        for split, count in (("train", 20), ("val", 4)):
            folder = args.output / split / name
            folder.mkdir(parents=True, exist_ok=True)
            for sample in range(count):
                cv2.imwrite(str(folder / f"{sample:02d}.png"), variant(image, generator))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "audit.json").write_text(json.dumps({
        "classes": mapping, "source": "official_item_artwork",
        "validation_independent": False,
        "warning": "All variants of a class share one original icon; no in-game item accuracy can be inferred.",
    }, ensure_ascii=False, indent=2))
    print(json.dumps({"classes": len(mapping), "train": 20*len(mapping),
                      "val": 4*len(mapping), "validation_independent": False}))


if __name__ == "__main__":
    main()
