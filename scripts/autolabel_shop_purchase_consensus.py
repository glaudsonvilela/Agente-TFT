#!/usr/bin/env python3
"""Create conservative autonomous labels from shop purchase transitions.

A crop is admitted only when independent game-derived signals agree:
1. exact unique catalog ID from shop OCR;
2. high OCR confidence;
3. card portrait physically disappears;
4. exactly one new bench proposal appears;
5. that bench unit persists spatially in later dense frames.

No model prediction is used as a label. Ambiguous cases stay unknown.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any


def die(message: str) -> "NoReturn":
    raise SystemExit(f"AUTOLABEL_SHOP_ERROR: {message}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"cannot read JSON {path}: {exc}")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def box_center(box: Any) -> tuple[float, float] | None:
    if (
        not isinstance(box, list)
        or len(box) != 4
        or any(not isinstance(v, (int, float)) for v in box)
    ):
        return None
    return (
        (float(box[0]) + float(box[2])) / 2.0,
        (float(box[1]) + float(box[3])) / 2.0,
    )


def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def persistence_evidence(
    observations: list[dict[str, Any]],
    after_seconds: int,
    box: Any,
    max_seconds: int,
    max_distance: float,
) -> dict[str, Any]:
    origin = box_center(box)
    if origin is None:
        return {"persistent": False, "reason": "invalid_origin_box"}

    matches = []
    inspected = 0
    for frame in observations:
        t = frame.get("source_seconds_nominal")
        if not isinstance(t, int):
            continue
        if t <= after_seconds:
            continue
        if t > after_seconds + max_seconds:
            break
        inspected += 1
        best = None
        for unit in frame.get("units", []):
            if not isinstance(unit, dict):
                continue
            center = box_center(unit.get("box"))
            if center is None:
                continue
            d = dist(origin, center)
            if best is None or d < best[0]:
                best = (d, unit)
        if best is not None and best[0] <= max_distance:
            matches.append(
                {
                    "source_seconds_nominal": t,
                    "distance_px": best[0],
                    "crop": best[1].get("crop"),
                    "pixel_sha256": best[1].get("pixel_sha256"),
                    "box": best[1].get("box"),
                }
            )

    return {
        "persistent": len(matches) >= 1,
        "frames_inspected": inspected,
        "matches": matches,
        "max_seconds": max_seconds,
        "max_distance_px": max_distance,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transitions", type=Path, required=True)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-ocr-confidence", type=float, default=94.0)
    parser.add_argument("--max-persistence-seconds", type=int, default=6)
    parser.add_argument("--max-persistence-distance-px", type=float, default=70.0)
    args = parser.parse_args()

    transitions_path = args.transitions.expanduser().resolve()
    collection = args.collection.expanduser().resolve()
    output = args.output.expanduser()

    if output.exists():
        die(f"output already exists: {output}")
    if not (0 < args.min_ocr_confidence <= 100):
        die("--min-ocr-confidence must be in (0,100]")
    if args.max_persistence_seconds < 2:
        die("--max-persistence-seconds must be >=2")
    if args.max_persistence_distance_px <= 0:
        die("--max-persistence-distance-px must be positive")

    transitions = load_json(transitions_path)
    if not isinstance(transitions, list):
        die("transition-proposals.json must be a list")
    report = load_json(collection / "report.json")
    partition = report.get("partition") if isinstance(report, dict) else None
    source_id = report.get("source_id") if isinstance(report, dict) else None
    if partition not in {"training_pool_unlabeled", "evaluation_unlabeled"} or not isinstance(source_id, str):
        die("collection partition/source missing or invalid")
    observations = load_jsonl(collection / "observations.jsonl")
    if not observations:
        die("collection observations are empty")
    observations.sort(key=lambda r: int(r.get("source_seconds_nominal", -1)))

    labels: list[dict[str, Any]] = []
    excluded = Counter()

    for row in transitions:
        if not isinstance(row, dict):
            excluded["invalid_transition"] += 1
            continue
        if row.get("source_id") != source_id or row.get("partition") != partition:
            excluded["transition_source_or_partition_mismatch"] += 1
            continue

        ids = row.get("shop_unit_candidates")
        if not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str):
            excluded["shop_identity_not_unique"] += 1
            continue
        unit_id = ids[0]

        conf = row.get("shop_ocr_name_confidence")
        if not isinstance(conf, (int, float)) or not math.isfinite(float(conf)):
            excluded["missing_ocr_confidence"] += 1
            continue
        if float(conf) < args.min_ocr_confidence:
            excluded["ocr_confidence_below_threshold"] += 1
            continue

        before = row.get("portrait_brightness_before")
        after = row.get("portrait_brightness_after")
        if not (
            isinstance(before, (int, float))
            and isinstance(after, (int, float))
            and math.isfinite(float(before))
            and math.isfinite(float(after))
            and float(before) >= 0.10
            and 0.0 <= float(after) <= 0.02
        ):
            excluded["portrait_disappearance_not_strong"] += 1
            continue

        old_t = row.get("before_seconds")
        new_t = row.get("after_seconds")
        if not isinstance(old_t, int) or not isinstance(new_t, int) or not (1 <= new_t - old_t <= 2):
            excluded["transition_gap_not_dense"] += 1
            continue

        bench = row.get("new_bench_proposals")
        if not isinstance(bench, list) or len(bench) != 1 or not isinstance(bench[0], dict):
            excluded["new_bench_unit_not_unique"] += 1
            continue
        unit = bench[0]

        crop = unit.get("crop")
        pixel = unit.get("pixel_sha256")
        box = unit.get("box")
        if not isinstance(crop, str) or not isinstance(pixel, str) or len(pixel) != 64:
            excluded["invalid_bench_crop_binding"] += 1
            continue
        crop_path = (collection / crop).resolve()
        if not crop_path.is_file():
            excluded["bench_crop_missing"] += 1
            continue

        persistence = persistence_evidence(
            observations,
            after_seconds=new_t,
            box=box,
            max_seconds=args.max_persistence_seconds,
            max_distance=args.max_persistence_distance_px,
        )
        if not persistence["persistent"]:
            excluded["bench_unit_not_temporally_persistent"] += 1
            continue

        labels.append(
            {
                "source_id": row.get("source_id"),
                "partition": partition,
                "unit_id": unit_id,
                "source_seconds_nominal": new_t,
                "crop": crop,
                "crop_path": str(crop_path),
                "pixel_sha256": pixel,
                "box": box,
                "label_source": "autonomous_shop_purchase_bench_consensus_v1",
                "evidence": {
                    "unique_shop_catalog_id": True,
                    "shop_ocr_name_confidence": float(conf),
                    "portrait_brightness_before": float(before),
                    "portrait_brightness_after": float(after),
                    "transition_gap_seconds": new_t - old_t,
                    "unique_new_bench_proposal": True,
                    "temporal_persistence": persistence,
                },
                "human_review_required": False,
                "model_prediction_used_as_label": False,
                "training_eligible": partition == "training_pool_unlabeled",
            }
        )

    # Never allow one crop to receive conflicting autonomous identities.
    seen: dict[str, str] = {}
    deduped = []
    for row in labels:
        pixel = row["pixel_sha256"]
        old = seen.get(pixel)
        if old is not None and old != row["unit_id"]:
            die("conflicting autonomous labels for identical crop pixels")
        if old is None:
            seen[pixel] = row["unit_id"]
            deduped.append(row)

    labels = deduped
    counts = Counter(row["unit_id"] for row in labels)

    output.mkdir(parents=True)
    (output / "auto-labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = {
        "schema_version": 1,
        "policy": "autonomous_shop_purchase_bench_consensus_v1",
        "transition_proposals": len(transitions),
        "gold_auto_labels": len(labels),
        "training_eligible_labels": sum(row["training_eligible"] for row in labels),
        "gold_auto_ids": dict(sorted(counts.items())),
        "excluded": dict(sorted(excluded.items())),
        "thresholds": {
            "min_ocr_confidence": args.min_ocr_confidence,
            "max_persistence_seconds": args.max_persistence_seconds,
            "max_persistence_distance_px": args.max_persistence_distance_px,
            "portrait_before_min": 0.10,
            "portrait_after_max": 0.02,
            "transition_gap_seconds_max": 2,
            "new_bench_proposals_required": 1,
        },
        "human_review_required": False,
        "model_prediction_used_as_label": False,
        "training_performed": False,
        "runtime_approved": False,
        "next": (
            "Use gold_auto labels as trusted anchors for temporal/embedding propagation. "
            "All rejected transitions remain unknown."
        ),
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\nAUTONOMOUS_SHOP_LABELS_OK=true")
    print(f"OUTPUT={output}")
    print(f"GOLD_AUTO_LABELS={len(labels)}")
    print("HUMAN_REVIEW_REQUIRED=false")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
