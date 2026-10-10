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
USER_LABEL_CORRECTIONS = {
    "train/Kha'Zix/fresh-aou9H4gyQ1g-000594600-0013.jpg": {
        "class": "Azir",
        "sha256": "255d90a52de0dfe424868fa0b18ac1b7c11ffa3c7f0ec350480f4e6d6bd03636",
        "evidence": "user identified the pictured unit as Azir on 2026-10-09",
    },
}


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
            label_status: str = "assistant_visual_review") -> None:
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
        records.append({"path": str(destination.relative_to(stage)), "class": name,
                        "sha256": digest, "origin": origin, "label_status": label_status})

    try:
        for split in ("train", "val", "test"):
            for path in _images(clean / split):
                relative = str(path.relative_to(clean))
                correction = USER_LABEL_CORRECTIONS.get(relative)
                if correction and _digest(path) != correction["sha256"]:
                    raise ValueError(f"Corrected image bytes changed: {path}")
                name = correction["class"] if correction else path.parent.name
                section = "correlated_holdout" if split == "test" and name == "Xayah" \
                    and path.name.startswith("holdout-xayah-") else split
                add(path, section, name,
                    "user_corrected_20261009" if correction else "mixed_clean_20261009",
                    "user_identified_from_crop" if correction else "assistant_visual_review")
        for path in extra:
            add(path, "train", path.parent.name, "extension_reviewed_v2")
        for relative in sorted(CONFLICTS):
            path = original / relative
            add(path, "quarantine", path.parent.name, "identity_conflict",
                "identity_unresolved_not_training_label")
        expected = {"train": 731, "val": 32, "test": 127,
                    "correlated_holdout": 10, "quarantine": 3}
        if dict(counts) != expected:
            raise ValueError(f"Unexpected package counts: {dict(counts)}")
        manifest = {
            "schema_version": 1,
            "purpose": "single canonical TFT champion identity corpus",
            "classes": names,
            "counts": expected,
            "independent_human_ground_truth": False,
            "model_predictions_used_as_labels": False,
            "label_corrections": USER_LABEL_CORRECTIONS,
            "splits": {
                "train": "assistant-reviewed identities from the cleaned mixed set and 47 reviewed extensions; one hash-checked user correction from Kha'Zix to Azir",
                "val": "unchanged legacy validation images",
                "test": "legacy test excluding same-source Xayah images",
                "correlated_holdout": "10 Xayah test images from the same source as 22 training images; never use for independent metrics",
                "quarantine": "three identity conflicts; never use as labels",
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
            "separate evaluation. One Azir image was corrected from a historical "
            "Kha'Zix label by the user; historical candidate weights are invalid "
            "for promotion.\n", encoding="utf-8")
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
