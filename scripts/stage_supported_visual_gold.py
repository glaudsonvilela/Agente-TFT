#!/usr/bin/env python3
"""Make a compact, checksum-verified package of existing direct gold anchors.

This copies only already adjudicated crops. It never creates or changes labels.
The package can be imported into the server corpus without transferring VODs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from PIL import Image


ALLOWED_LABEL_SOURCES = {
    "autonomous_shop_purchase_bench_consensus_v1",
    "autonomous_tooltip_temporal_consensus_v1",
}


def stage(supported: Path, search_root: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("output already exists")
    rows = json.loads(supported.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("supported anchor list is empty")
    eligible = []
    for row in rows:
        if row.get("decision") not in {"supported", "bootstrap_supported"}:
            continue
        if (row.get("label_source") not in ALLOWED_LABEL_SOURCES
                or row.get("training_eligible") is not True
                or row.get("human_review_required") is not False
                or row.get("model_prediction_used_as_label") is not False
                or row.get("partition") not in (None, "training_pool_unlabeled")):
            raise ValueError("gold provenance contract failed")
        eligible.append(row)
    if not eligible:
        raise ValueError("no strictly supported anchors")
    sources = {row.get("source_id") for row in eligible}
    if len(sources) != 1 or not isinstance(next(iter(sources)), str):
        raise ValueError("package must contain one source")
    source_id = next(iter(sources))
    search_root = search_root.resolve()
    by_name = {}
    for path in search_root.rglob("*.png"):
        if path.name not in by_name:
            by_name[path.name] = path

    prepared = []
    seen_pixels = set()
    for row in eligible:
        pixel = row.get("pixel_sha256")
        relative = row.get("crop")
        if (not isinstance(pixel, str) or len(pixel) != 64
                or not isinstance(relative, str) or Path(relative).name != f"{pixel}.png"):
            raise ValueError("crop identity is invalid")
        if pixel in seen_pixels:
            continue
        crop = by_name.get(f"{pixel}.png")
        if crop is None or not crop.resolve().is_relative_to(search_root):
            raise ValueError(f"verified crop missing: {pixel}")
        with Image.open(crop) as image:
            actual = hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()
        if actual != pixel:
            raise ValueError(f"crop pixel checksum mismatch: {pixel}")
        prepared.append((row, crop))
        seen_pixels.add(pixel)

    crops = output / "collection" / "crops"
    crops.mkdir(parents=True)
    for row, crop in prepared:
        shutil.copy2(crop, crops / f"{row['pixel_sha256']}.png")
    gold = [row for row, _ in prepared]
    (output / "gold.json").write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n")
    (output / "silver.json").write_text("[]\n")
    report = {"schema_version": 1, "source_id": source_id,
              "partition": "training_pool_unlabeled",
              "collection_mode": "compacted_adjudicated_gold_only",
              "unit_crops": len(gold), "labels_created": 0,
              "model_prediction_used_as_label": False}
    (output / "collection" / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    package = {"schema_version": 1, "source_id": source_id, "gold": len(gold),
               "silver": 0, "source_supported_sha256": hashlib.sha256(supported.read_bytes()).hexdigest(),
               "labels_created": 0, "model_prediction_used_as_label": False}
    (output / "package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n")
    return package


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--supported", type=Path, required=True)
    parser.add_argument("--search-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args.supported, args.search_root, args.output), ensure_ascii=False))


if __name__ == "__main__":
    main()
