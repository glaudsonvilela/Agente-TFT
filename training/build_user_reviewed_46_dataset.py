"""Build an isolated diagnostic classifier set from verified champion crops.

This does not change the canonical training eligibility of the 65-class corpus.
The validation folder mirrors training solely to satisfy the YOLO trainer; only
the separate held-out videos may be used to report generalization.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


HELD_OUT_VIDEOS = {"8W7Wfnf36M8.webm", "-YQHDFlMRRs.webm"}


def build(index_path: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    index = json.loads(index_path.read_text(encoding="utf-8"))
    records = index["records"]
    if index.get("model_predictions_used_as_labels") is not False or len(records) != 106:
        raise ValueError("Expected exactly 106 reviewed, non-prediction crop records")

    by_split: dict[str, list[dict]] = {"train": [], "holdout": []}
    for row in records:
        if row["review_status"] not in {"user_confirmed_candidate", "ui_confirmed_candidate"}:
            raise ValueError(f"Unconfirmed crop {row['review_id']}")
        crop = Path(row["natural_crop"])
        if hashlib.sha256(crop.read_bytes()).hexdigest() != row["natural_crop_sha256"]:
            raise ValueError(f"Changed crop {row['review_id']}")
        split = "holdout" if Path(row["source_video_local"]).name in HELD_OUT_VIDEOS else "train"
        by_split[split].append(row)

    classes = sorted({row["game_id"] for row in records})
    train_classes = {row["game_id"] for row in by_split["train"]}
    if len(classes) != 46 or train_classes != set(classes):
        raise ValueError("Every one of the 46 classes must be represented in training")
    train_videos = {row["source_video_local"] for row in by_split["train"]}
    holdout_videos = {row["source_video_local"] for row in by_split["holdout"]}
    if train_videos & holdout_videos or len(by_split["holdout"]) != 4:
        raise ValueError("Expected four crops from two fully unseen videos")

    for split, rows in by_split.items():
        for row in rows:
            src = Path(row["natural_crop"])
            suffix = src.suffix.lower() or ".png"
            dst = output / ("dataset/train" if split == "train" else "holdout") / row["game_id"] / f"{int(row['review_id']):03d}{suffix}"
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.symlink_to(src)
            if split == "train":
                val = output / "dataset/val" / row["game_id"] / dst.name
                val.parent.mkdir(parents=True, exist_ok=True)
                val.symlink_to(src)

    report = {
        "scope": "experimental_46_class_classifier_only",
        "canonical_65_class_training_eligibility_changed": False,
        "model_predictions_used_as_labels": False,
        "old_tft_weights_used": False,
        "train": len(by_split["train"]),
        "holdout": len(by_split["holdout"]),
        "classes": classes,
        "training_counts": dict(Counter(row["game_id"] for row in by_split["train"])),
        "heldout_videos": sorted(holdout_videos),
        "holdout_review_ids": [row["review_id"] for row in by_split["holdout"]],
        "validation_note": "YOLO val mirrors train; it is not an accuracy estimate. Evaluate only holdout.",
        "source_index": str(index_path),
        "source_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
    }
    (output / "provenance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.index, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
