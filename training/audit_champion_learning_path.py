#!/usr/bin/env python3
"""Find recycled champion crops and contradictory labels before another train.

This compares pixels, not model predictions. A low mean absolute pixel error
is evidence of a repeated observation, not proof of a champion's identity.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
NEAR_EXACT_MAE = 5.0


def _images(root: Path, split: str) -> list[tuple[str, np.ndarray]]:
    rows = []
    for path in sorted((root / split).glob("*/*")):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            with Image.open(path) as image:
                rows.append((str(path.relative_to(root)),
                             np.asarray(image.convert("RGB"), dtype=np.uint8)))
    return rows


def _thumb(image: np.ndarray) -> np.ndarray:
    return cv2.resize(image, (16, 18), interpolation=cv2.INTER_AREA).astype(np.int16)


def _mae(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.abs(left.astype(np.int16) - right.astype(np.int16)).mean())


def _same_size_pairs(left: list[tuple[str, np.ndarray]],
                     right: list[tuple[str, np.ndarray]],
                     triangular: bool = False) -> list[dict]:
    thumbs = np.stack([_thumb(image) for _, image in right])
    pairs = []
    for left_index, (left_path, image) in enumerate(left):
        coarse = np.abs(thumbs - _thumb(image)).mean(axis=(1, 2, 3))
        for right_index in np.flatnonzero(coarse < 10):
            if triangular and right_index <= left_index:
                continue
            right_path, other = right[int(right_index)]
            error = _mae(image, other)
            if error < NEAR_EXACT_MAE:
                pairs.append({"left": left_path, "right": right_path,
                              "mae": round(error, 3),
                              "same_label": Path(left_path).parent.name == Path(right_path).parent.name})
    return pairs


def audit(root: Path) -> dict:
    train = _images(root, "train")
    val = _images(root, "val")
    test = _images(root, "test")
    legacy = [(path, image) for path, image in train if image.shape[:2] == (168, 152)]
    extensions = [(path, image) for path, image in train if image.shape[:2] == (144, 128)]
    legacy_centers = [(path, image[12:156, 12:140]) for path, image in legacy]
    center_thumbs = np.stack([_thumb(image) for _, image in legacy_centers])
    extension_matches = []
    for path, image in extensions:
        coarse = np.abs(center_thumbs - _thumb(image)).mean(axis=(1, 2, 3))
        # Shortlist only removes obvious nonmatches; inspect every close center.
        for index in np.flatnonzero(coarse < 10):
            other_path, center = legacy_centers[int(index)]
            error = _mae(image, center)
            if error < NEAR_EXACT_MAE:
                extension_matches.append({"extension": path, "legacy": other_path,
                                          "mae": round(error, 3),
                                          "same_label": Path(path).parent.name == Path(other_path).parent.name})
    legacy_pairs = _same_size_pairs(legacy, legacy, triangular=True)
    held_out = [(path, image) for path, image in val + test
                if image.shape[:2] == (168, 152)]
    train_test_pairs = _same_size_pairs(held_out, legacy)

    parent: dict[str, str] = {}

    def find(path: str) -> str:
        parent.setdefault(path, path)
        if parent[path] != path:
            parent[path] = find(parent[path])
        return parent[path]

    for row in extension_matches:
        parent[find(row["extension"])] = find(row["legacy"])
    for row in legacy_pairs:
        parent[find(row["left"])] = find(row["right"])
    groups: dict[str, list[str]] = defaultdict(list)
    for path, _ in train:
        groups[find(path)].append(path)
    contradictory = [sorted(paths) for paths in groups.values()
                     if len({Path(path).parent.name for path in paths}) > 1]
    per_class = defaultdict(set)
    for path, _ in train:
        per_class[Path(path).parent.name].add(find(path))

    return {
        "schema_version": 1,
        "method": "RGB mean absolute error < 5 after exact center alignment; near-pixel-copy proxy, not semantic identity",
        "counts": {"train": len(train), "val": len(val), "test": len(test),
                   "extension_sized": len(extensions),
                   "extension_copies": len({row["extension"] for row in extension_matches}),
                   "legacy_near_exact_pairs": len(legacy_pairs),
                   "near_exact_train_components": len(groups),
                   "cross_split_near_exact_pairs": len(train_test_pairs)},
        "size_counts_train": {f"{width}x{height}": count for (width, height), count in
                              Counter((image.shape[1], image.shape[0]) for _, image in train).items()},
        "extension_matches": extension_matches,
        "legacy_pairs": legacy_pairs,
        "cross_split_pairs": train_test_pairs,
        "contradictory_components": contradictory,
        "per_class_near_exact_components": {name: len(groups) for name, groups in sorted(per_class.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit(args.corpus)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"counts": report["counts"],
                      "contradictory_components": report["contradictory_components"],
                      "Kha'Zix_effective_crops":
                      report["per_class_near_exact_components"].get("Kha'Zix")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
