#!/usr/bin/env python3
"""Materialize one auditable TFT champion classification corpus on the SSD.

Only assistant-reviewed identities enter train/val/test. Model predictions and
unreviewed video frames are catalogued as sources, never copied as labels.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
CONFLICTS = {
    "train/Nidalee/frame-000144-rare-8.jpg",
    "train/Warwick/frame-000136-rare-2.jpg",
    "train/Azir/frame-000050-marker-2.jpg",
}
USER_REVIEW = Path(__file__).with_name("champion_label_corrections_20261009.json")


def _images(folder: Path):
    return sorted(path for path in folder.rglob("*")
                  if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(clean: Path, extension: Path, original: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"Corpus already exists: {output}")
    correction = json.loads((clean / "correction-manifest.json").read_text())
    mix = json.loads((clean / "mix-provenance.json").read_text())
    extension_audit = json.loads((extension / "extension-audit.json").read_text())
    if set(correction["removed"]) != CONFLICTS:
        raise ValueError("Identity quarantine changed; inspect it before assembly")
    if extension_audit.get("model_predictions_used_as_labels") is not False:
        raise ValueError("Extension has model predictions as labels")
    if mix.get("fresh_labels_from_model_predictions") is not False:
        raise ValueError("Clean mix has model predictions as labels")
    if extension_audit.get("review_method") != "assistant_visual_review":
        raise ValueError("Extension is not visually reviewed")

    review = json.loads(USER_REVIEW.read_text())
    if review.get("schema_version") != 1 or len(review.get("items", [])) != 26:
        raise ValueError("Unexpected user identity review")
    corrections = {}
    for item in review["items"]:
        key = (item["source"], item["source_path"])
        if key in corrections or item["source"] not in {"clean", "extension", "original"}:
            raise ValueError(f"Invalid or duplicate correction: {key}")
        if item["destination_split"] not in {"train", "val", "test", "quarantine"}:
            raise ValueError(f"Invalid review destination: {key}")
        if item["identified_label"] is None and item["destination_split"] != "quarantine":
            raise ValueError(f"Unresolved image would become a label: {key}")
        corrections[key] = item
    pending = set(corrections)

    names = sorted(path.name for path in (clean / "train").iterdir() if path.is_dir())
    if len(names) != 65:
        raise ValueError(f"Expected 65 identity classes; found {len(names)}")
    extra = _images(extension / "train")
    extra = [path for path in extra if path.name.startswith("third-reviewed-")]
    if len(extra) != extension_audit["total_added"]:
        raise ValueError("Extension count differs from reviewed audit")
    if dict(Counter(path.parent.name for path in extra)) != extension_audit["added"]:
        raise ValueError("Extension class counts differ from reviewed audit")

    stage = output.with_name(output.name + ".assembling")
    if stage.exists():
        raise FileExistsError(f"Incomplete previous staging directory: {stage}")
    stage.mkdir(parents=True)
    records = []
    hashes = {}
    counts = Counter()

    def add(path: Path, section: str, name: str, origin: str,
            label_status: str = "assistant_visual_review",
            historical_label: str | None = None) -> None:
        if name not in names:
            raise ValueError(f"Unexpected identity: {name}")
        digest = _digest(path)
        if digest in hashes:
            raise ValueError(f"Duplicate bytes: {path} and {hashes[digest]}")
        hashes[digest] = str(path)
        destination = stage / section / name / path.name
        if destination.exists():
            raise ValueError(f"Filename collision: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        if _digest(destination) != digest:
            raise ValueError(f"Copy changed bytes: {destination}")
        counts[section] += 1
        record = {"path": str(destination.relative_to(stage)),
                  "class": None if section == "quarantine" else name,
                  "sha256": digest, "origin": origin, "label_status": label_status}
        if section == "quarantine":
            record["historical_label"] = historical_label or name
        records.append(record)

    def reviewed(path: Path, source: str, root: Path):
        key = (source, str(path.relative_to(root)))
        item = corrections.get(key)
        if item is None:
            return None
        if _digest(path) != item["sha256"] or path.parent.name != item["previous_label"]:
            raise ValueError(f"Reviewed crop changed since user inspection: {path}")
        pending.remove(key)
        return item

    try:
        for split in ("train", "val", "test"):
            for path in _images(clean / split):
                item = reviewed(path, "clean", clean)
                name = (item["identified_label"] or path.parent.name) if item else path.parent.name
                section = (item["destination_split"] if item else
                           "correlated_holdout" if split == "test" and name == "Xayah"
                           and path.name.startswith("holdout-xayah-") else split)
                add(path, section, name,
                    "user_review_20261009" if item else "mixed_clean_20261009",
                    ("identity_unresolved_not_training_label" if item and name != item["identified_label"]
                     else "user_identified_from_crop" if item else "assistant_visual_review"),
                    path.parent.name)
        for path in extra:
            item = reviewed(path, "extension", extension)
            add(path, item["destination_split"] if item else "train",
                item["identified_label"] if item else path.parent.name,
                "user_review_20261009" if item else "extension_reviewed_v2",
                "user_identified_from_crop" if item else "assistant_visual_review")
        for relative in sorted(CONFLICTS):
            path = original / relative
            item = reviewed(path, "original", original)
            add(path, item["destination_split"] if item else "quarantine",
                item["identified_label"] if item else path.parent.name,
                "user_review_20261009" if item else "identity_conflict",
                "user_identified_from_crop" if item else "identity_unresolved_not_training_label",
                path.parent.name)
        if pending:
            raise ValueError(f"User review not applied to source images: {sorted(pending)}")
        expected = {"train": 734, "val": 32, "test": 127,
                    "correlated_holdout": 10, "quarantine": 0}
        if {section: counts.get(section, 0) for section in expected} != expected:
            raise ValueError(f"Unexpected package counts: {dict(counts)}")
        (stage / "quarantine").mkdir(exist_ok=True)
        manifest = {
            "schema_version": 1,
            "purpose": "single canonical TFT champion identity corpus",
            "classes": names,
            "counts": expected,
            "independent_human_ground_truth": False,
            "model_predictions_used_as_labels": False,
            "user_review_sha256": _digest(USER_REVIEW),
            "splits": {
                "train": "assistant-reviewed sources with 2026-10-09 user-confirmed identity corrections",
                "val": "legacy validation images with user-confirmed Vi correction",
                "test": "legacy test excluding same-source Xayah; user-confirmed Sivir identity restored",
                "correlated_holdout": "10 Xayah test images from the same source as 22 training images; never use for independent metrics",
                "quarantine": "no remaining unresolved identities in this reviewed batch",
            },
            "sources": {
                "clean": str(clean), "extension": str(extension), "original": str(original),
            },
            "records": records,
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (stage / "README.md").write_text(
            "# TFT champion corpus\n\n"
            "Use `train/`, `val/`, and `test/` for identity classification. "
            "`correlated_holdout/` and `quarantine/` are excluded from training "
            "and independent evaluation. Source videos and automatically predicted "
            "labels are not part of this corpus. Historical datasets remain read-only "
            "provenance. The installed model is unchanged until a candidate passes "
            "separate evaluation. User identity corrections are hash-checked "
            "against the numbered review; all 25 numbered images were identified. "
            "Historical weights remain unchanged.\n", encoding="utf-8")
        stage.rename(output)
        return manifest
    except Exception:
        shutil.rmtree(stage)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", required=True, type=Path)
    parser.add_argument("--extension", required=True, type=Path)
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build(args.clean, args.extension, args.original, args.output)
    print(json.dumps({"output": str(args.output), "counts": result["counts"],
                      "classes": len(result["classes"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
