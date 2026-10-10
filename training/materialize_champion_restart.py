#!/usr/bin/env python3
"""Materialize an audited champion review queue for candidate classification training."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil


def _copy_verified(source: Path, expected_sha256: str, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"Changed source crop: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def materialize(corpus: Path, review: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"Use a new output directory: {output}")
    source_manifest = json.loads((corpus / "manifest.json").read_text())
    queue = json.loads(review.read_text())
    classes = source_manifest["classes"]
    if queue.get("status") != "review_queue_not_training_data" or \
            queue.get("model_predictions_used_as_labels") is not False:
        raise ValueError("The source must be a reviewed queue without predicted labels")
    selected = queue["selected"]
    counts = Counter(row["class"] for row in selected)
    if set(counts) != set(classes) or any(counts[name] != 5 for name in classes):
        raise ValueError("Expected exactly five audited crops for each of 65 classes")
    if len({row["sha256"] for row in selected}) != len(selected):
        raise ValueError("Exact duplicate in the selected training crops")
    holdout = [row for row in source_manifest["records"]
               if row["path"].startswith(("val/", "test/"))]
    holdout_shas = {row["sha256"] for row in holdout}
    if any(row["sha256"] in holdout_shas for row in selected):
        raise ValueError("An image selected for training occurs in the holdout")

    output.mkdir(parents=True)
    records = []
    for index, row in enumerate(selected):
        path = Path(row["path"])
        source = path if path.is_absolute() else corpus / path
        destination = output / "train" / row["class"] / f"{index:03d}-{row['sha256'][:12]}{path.suffix.lower()}"
        _copy_verified(source, row["sha256"], destination)
        records.append({"split": "train", "class": row["class"],
                        "path": str(destination.relative_to(output)),
                        "sha256": row["sha256"], "source": row["source"],
                        "label_status": row["label_status"]})
    for row in holdout:
        destination = output / row["path"]
        _copy_verified(corpus / row["path"], row["sha256"], destination)
        records.append({"split": Path(row["path"]).parts[0],
                        "class": row["class"],
                        "path": str(destination.relative_to(output)),
                        "sha256": row["sha256"],
                        "label_status": row["label_status"]})
    report = {
        "schema_version": 1,
        "status": "experimental_candidate_dataset",
        "classes": classes,
        "counts": dict(Counter(row["split"] for row in records)),
        "five_distinct_sources_classes": queue["classes_with_five_sources"],
        "independent_human_ground_truth": source_manifest["independent_human_ground_truth"],
        "model_predictions_used_as_labels": False,
        "review_manifest": str(review),
        "records": records,
    }
    (output / "provenance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = materialize(args.corpus, args.review, args.output)
    print(json.dumps({"counts": report["counts"],
                      "five_distinct_sources_classes": report["five_distinct_sources_classes"]},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
