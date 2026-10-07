#!/usr/bin/env python3
"""Turn strict tooltip OCR evidence into autonomous training anchors.

No human review is required. The script accepts only exact, unique catalog IDs
with strong OCR, strong selected-unit association, and temporal repetition.
Everything else remains unknown and is excluded from training.

Input: proposals.json produced by mine-tooltip-labels.
Output: auto-labels.json + report.json.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


def die(message: str) -> "NoReturn":
    raise SystemExit(f"AUTOLABEL_TOOLTIP_ERROR: {message}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"cannot read JSON {path}: {exc}")


def center(box: list[Any]) -> tuple[float, float]:
    if (
        not isinstance(box, list)
        or len(box) != 4
        or any(not isinstance(v, (int, float)) for v in box)
    ):
        die("invalid association box")
    return ((float(box[0]) + float(box[2])) / 2, (float(box[1]) + float(box[3])) / 2)


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def strong_association(row: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    units = row.get("association_candidates")
    if not isinstance(units, list) or not units:
        return None, {"reason": "no_association_candidates"}
    marker_id = row.get("selected_ring_marker_candidate")
    status = row.get("selection_ring_status")
    if status not in {"unique_shape_candidate", "dominant_shape_candidate"}:
        return None, {"reason": "no_unique_selected_ring"}
    selected = [u for u in units if u.get("marker_id") == marker_id]
    if len(selected) != 1:
        return None, {"reason": "ring_marker_not_unique"}
    ring = selected[0].get("selection_ring")
    if not isinstance(ring, dict) or ring.get("shape_pass") is not True:
        return None, {"reason": "ring_shape_unverified"}
    count = ring.get("cyan_pixels")
    if not isinstance(count, int) or count < 250:
        return None, {"reason": "ring_coverage_insufficient"}
    competitors = [
        (u.get("selection_ring") or {}).get("cyan_pixels", 0)
        for u in units if u is not selected[0]
        and (u.get("selection_ring") or {}).get("shape_pass") is True
    ]
    second = max(competitors, default=0)
    if status == "dominant_shape_candidate" and not (count >= 500 and count * 2 >= second * 5):
        return None, {"reason": "ring_dominance_unverified"}
    return selected[0], {"selected_ring": ring, "second_ring_pixels": second, "association_pass": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-ocr-confidence", type=float, default=94.0)
    parser.add_argument("--max-track-gap-seconds", type=float, default=2.0)
    parser.add_argument("--max-track-distance-px", type=float, default=40.0)
    parser.add_argument("--min-temporal-confirmations", type=int, default=2)
    args = parser.parse_args()

    proposals_path = args.proposals.expanduser().resolve()
    output = args.output.expanduser()
    if output.exists():
        die(f"output already exists: {output}")
    if not (0 < args.min_ocr_confidence <= 100):
        die("--min-ocr-confidence must be in (0,100]")
    if args.min_temporal_confirmations < 2:
        die("--min-temporal-confirmations must be >=2")
    if not (0 < args.max_track_gap_seconds <= 2 and 0 < args.max_track_distance_px <= 40):
        die("temporal tracking limits must remain within two seconds and 40 pixels")

    proposals = load_json(proposals_path)
    if not isinstance(proposals, list):
        die("proposals must be a list")

    prelim: list[dict[str, Any]] = []
    excluded = defaultdict(int)

    for row in proposals:
        if not isinstance(row, dict):
            excluded["invalid_row"] += 1
            continue
        unit_id = row.get("tooltip_unit_id")
        candidates = row.get("tooltip_unit_candidates")
        conf = row.get("ocr_name_confidence")
        if not isinstance(unit_id, str) or not unit_id:
            excluded["nonunique_or_generic_tooltip"] += 1
            continue
        if not isinstance(candidates, list) or candidates != [unit_id]:
            excluded["candidate_identity_not_unique"] += 1
            continue
        if row.get("identity_requires_variant_review") is not False:
            excluded["variant_not_exact"] += 1
            continue
        if not isinstance(conf, (int, float)) or not math.isfinite(conf):
            excluded["invalid_ocr_confidence"] += 1
            continue
        if float(conf) < args.min_ocr_confidence:
            excluded["ocr_confidence_below_threshold"] += 1
            continue

        top, assoc = strong_association(row)
        if top is None:
            excluded["weak_selected_unit_association"] += 1
            continue

        box = top.get("box")
        try:
            xy = center(box)
        except SystemExit:
            excluded["invalid_association_box"] += 1
            continue
        t = row.get("source_seconds_nominal")
        if not isinstance(t, (int, float)) or not math.isfinite(float(t)):
            excluded["invalid_timestamp"] += 1
            continue
        pixel = top.get("pixel_sha256")
        crop = top.get("crop")
        if not isinstance(pixel, str) or len(pixel) != 64 or not isinstance(crop, str):
            excluded["invalid_crop_binding"] += 1
            continue
        source_id = row.get("source_id")
        frame_pixel = row.get("frame_pixel_sha256")
        if not isinstance(source_id, str) or not source_id or not isinstance(frame_pixel, str) or len(frame_pixel) != 64:
            excluded["invalid_frame_provenance"] += 1
            continue

        prelim.append(
            {
                "source_id": source_id,
                "source_seconds_nominal": int(round(float(t))),
                "unit_id": unit_id,
                "ocr_name_confidence": float(conf),
                "crop": crop,
                "pixel_sha256": pixel,
                "box": box,
                "center": xy,
                "frame": row.get("frame"),
                "frame_pixel_sha256": row.get("frame_pixel_sha256"),
                "association": assoc,
                "tooltip_text": row.get("tooltip_text"),
            }
        )

    # Greedy track clustering by exact unit ID, nearby time and nearby screen position.
    clusters: list[list[dict[str, Any]]] = []
    for item in sorted(prelim, key=lambda x: (x["unit_id"], x["source_seconds_nominal"])):
        placed = False
        for cluster in reversed(clusters):
            last = cluster[-1]
            if last["unit_id"] != item["unit_id"] or last["source_id"] != item["source_id"]:
                continue
            dt = item["source_seconds_nominal"] - last["source_seconds_nominal"]
            if dt <= 0 or dt > args.max_track_gap_seconds:
                continue
            if distance(last["center"], item["center"]) > args.max_track_distance_px:
                continue
            cluster.append(item)
            placed = True
            break
        if not placed:
            clusters.append([item])

    labels = []
    rejected_singletons = 0
    for track_id, cluster in enumerate(clusters, 1):
        unique_pixels = {x["pixel_sha256"] for x in cluster}
        unique_frames = {x["frame_pixel_sha256"] for x in cluster}
        if len(unique_pixels) < args.min_temporal_confirmations or len(unique_frames) < args.min_temporal_confirmations:
            rejected_singletons += 1
            continue

        for item in cluster:
            labels.append(
                {
                    "source_id": item["source_id"],
                    "source_seconds_nominal": item["source_seconds_nominal"],
                    "unit_id": item["unit_id"],
                    "crop": item["crop"],
                    "pixel_sha256": item["pixel_sha256"],
                    "box": item["box"],
                    "frame": item["frame"],
                    "frame_pixel_sha256": item["frame_pixel_sha256"],
                    "label_source": "autonomous_tooltip_temporal_consensus_v1",
                    "evidence": {
                        "exact_catalog_name_ocr": True,
                        "ocr_name_confidence": item["ocr_name_confidence"],
                        "selected_unit_association": item["association"],
                        "temporal_track_id": track_id,
                        "temporal_confirmations": len(unique_pixels),
                    },
                    "human_review_required": False,
                    "model_prediction_used_as_label": False,
                    "training_eligible": True,
                }
            )

    # Fail closed on duplicate pixels receiving different IDs.
    seen: dict[str, str] = {}
    for row in labels:
        pixel = row["pixel_sha256"]
        old = seen.setdefault(pixel, row["unit_id"])
        if old != row["unit_id"]:
            die("same crop pixels received conflicting autonomous IDs")

    output.mkdir(parents=True)
    (output / "auto-labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report = {
        "schema_version": 1,
        "policy": "autonomous_tooltip_temporal_consensus_v1",
        "proposals": len(proposals),
        "strong_exact_associations": len(prelim),
        "clusters": len(clusters),
        "auto_labels": len(labels),
        "auto_labeled_ids": dict(
            sorted(
                {
                    ident: sum(row["unit_id"] == ident for row in labels)
                    for ident in {row["unit_id"] for row in labels}
                }.items()
            )
        ),
        "rejected_singleton_clusters": rejected_singletons,
        "excluded": dict(sorted(excluded.items())),
        "thresholds": {
            "min_ocr_confidence": args.min_ocr_confidence,
            "max_track_gap_seconds": args.max_track_gap_seconds,
            "max_track_distance_px": args.max_track_distance_px,
            "min_temporal_confirmations": args.min_temporal_confirmations,
            "selected_ring_shape_required": True,
            "singleton_fallback_allowed": False,
        },
        "human_review_required": False,
        "model_prediction_used_as_label": False,
        "training_performed": False,
        "runtime_approved": False,
        "next": (
            "Use accepted autonomous anchors for temporal propagation and weighted "
            "semi-supervised training. All rejected/ambiguous evidence remains unknown."
        ),
    }
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("\nAUTONOMOUS_TOOLTIP_LABELS_OK=true")
    print(f"OUTPUT={output}")
    print(f"AUTO_LABELS={len(labels)}")
    print("HUMAN_REVIEW_REQUIRED=false")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
