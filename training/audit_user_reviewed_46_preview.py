"""Audit whether replay proposals cover independently reviewed unit boxes.

This measures localization only. It does not treat model predictions as labels
or claim that an overlapping box has the correct champion identity.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics

import cv2

from preview_user_reviewed_46_replay import locate_health_bars


def intersection_over_union(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    overlap = max(0, x1 - x0) * max(0, y1 - y0)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return overlap / (area_a + area_b - overlap)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    args = parser.parse_args()
    provenance = json.loads((args.experiment / "provenance.json").read_text())
    index = json.loads(Path(provenance["source_index"]).read_text())
    reviewed = [row for row in index["records"]
                if row["review_status"] in
                {"user_confirmed_candidate", "ui_confirmed_candidate"}]
    counts = Counter(row["game_id"] for row in reviewed
                     if row["review_id"] not in provenance["holdout_review_ids"])
    manifest_cache = {}
    by_frame = defaultdict(list)
    for row in reviewed:
        manifest_path = row["manifest"]
        if manifest_path not in manifest_cache:
            manifest_cache[manifest_path] = json.loads(Path(manifest_path).read_text())
        manifest = manifest_cache[manifest_path]
        for candidate in manifest.get("records", manifest.get("crops", [])):
            if str(candidate.get("id")) != str(row["review_id"]):
                continue
            box = candidate.get("source_pixel_box", candidate.get("box_source_3840"))
            frame = candidate.get("source_frame")
            if box and frame and Path(frame).is_file():
                by_frame[frame].append((row, tuple(box)))
            break

    rows = []
    for frame_path, references in by_frame.items():
        frame = cv2.imread(frame_path)
        if frame is None:
            raise RuntimeError(f"Could not read reviewed source frame: {frame_path}")
        proposals = locate_health_bars(frame)
        for row, box in references:
            best = max((intersection_over_union(box, proposed)
                        for proposed in proposals), default=0.0)
            rows.append({"review_id": row["review_id"],
                         "champion": row["champion"], "zone": row["zone"],
                         "best_proposal_iou": round(best, 4)})

    values = [row["best_proposal_iou"] for row in rows]
    report = {
        "scope": "experimental_46_class_preview_audit",
        "status": "rejected_for_live_champion_identification",
        "model_predictions_used_as_labels": False,
        "reviewed_training_crops": sum(counts.values()),
        "classes": len(counts),
        "classes_with_one_training_crop": sum(n == 1 for n in counts.values()),
        "classes_with_fewer_than_five_training_crops": sum(n < 5 for n in counts.values()),
        "reviewed_boxes_with_source_frame": len(rows),
        "source_frames": len(by_frame),
        "median_best_iou": round(statistics.median(values), 4),
        "best_iou_at_least_0_5": sum(value >= 0.5 for value in values),
        "best_iou_at_least_0_7": sum(value >= 0.7 for value in values),
        "heldout_classification": json.loads(
            (args.experiment / "heldout-report.json").read_text()),
        "rows": rows,
        "limitations": [
            "The localization boxes are reviewed 4K crops, not dense frame annotations.",
            "The holdout has only four reviewed identities from two unseen videos.",
            "IoU measures crop alignment, not champion recognition accuracy.",
        ],
    }
    output = args.experiment / "preview-audit.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {"rows", "heldout_classification"}},
                     ensure_ascii=False, indent=2))
    print(f"Report: {output}")


if __name__ == "__main__":
    main()
