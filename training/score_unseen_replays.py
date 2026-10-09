#!/usr/bin/env python3
"""Score manually reviewed replay points without promoting predictions to labels.

Each reviewed frame explicitly lists which zones were inspected. A point is a
unit's visible body centre, not a box inferred from the detector. Unreviewed
frames and zones never enter denominators.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path

ZONES = ("board", "bench", "enemy")
DETECTOR_CLASSES = {"board": "board_unit", "bench": "bench_unit",
                    "enemy": "enemy_unit"}


def _point_in(box: list, point: list) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


def _center_distance(box: list, point: list) -> float:
    return ((point[0] - (box[0] + box[2]) / 2) ** 2 +
            (point[1] - (box[1] + box[3]) / 2) ** 2) ** .5


def _predictions(frame: dict, zone: str, layer: str) -> list[dict]:
    if layer == "detector":
        return [row for row in frame["detections"]
                if row["class_name"] == DETECTOR_CLASSES[zone]]
    if zone == "board":
        return [row for row in frame["records"] if row.get("zone") != "bench_unit"]
    return frame["bench_records" if zone == "bench" else "enemy_records"]


def score(observations: list[dict], review: dict) -> dict:
    if (review.get("schema_version") != 1 or
            review.get("review_method") != "assistant_visual_review_from_raw_video" or
            review.get("model_predictions_used_as_labels") is not False):
        raise ValueError("Review provenance or schema invalid")
    by_key = {(r["source_id"], r["second"]): r for r in observations}
    if len(by_key) != len(observations):
        raise ValueError("Duplicate observation key")
    totals = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    identity = defaultdict(int)
    details = []
    seen = set()
    for sample in review["frames"]:
        key = sample["source_id"], sample["second"]
        if key in seen or key not in by_key:
            raise ValueError(f"Unknown or duplicate reviewed frame: {key}")
        seen.add(key)
        frame = by_key[key]
        reviewed = sample["reviewed_zones"]
        identity_only = sample.get("identity_only_units", [])
        if (not reviewed and not identity_only or
                len(set(reviewed)) != len(reviewed) or set(reviewed) - set(ZONES)):
            raise ValueError(f"Invalid reviewed zones: {key}")
        points = sample.get("units", [])
        if any("candidate_name" in unit or "prediction" in unit or
               unit.get("zone") not in reviewed or
               len(unit.get("point", [])) != 2 or
               unit.get("name") and unit.get("identity_status") != "visually_verified"
               for unit in points):
            raise ValueError(f"Unreviewed or prediction-derived label: {key}")
        if any("candidate_name" in unit or "prediction" in unit or
               unit.get("zone") not in ZONES or
               len(unit.get("point", [])) != 2 or
               not unit.get("name") or
               unit.get("identity_status") != "visually_verified" or
               not unit.get("evidence")
               for unit in identity_only):
            raise ValueError(f"Identity probe lacks visual evidence: {key}")
        for zone in reviewed:
            truth = [unit for unit in points if unit["zone"] == zone]
            for layer in ("detector", "full_reader"):
                candidates = _predictions(frame, zone, layer)
                # One-to-one nearest spatial matching avoids counting several
                # overlapping predictions as correct for one visible unit.
                choices = sorted((_center_distance(pred["box"], unit["point"]), pi, ti)
                                 for pi, pred in enumerate(candidates)
                                 for ti, unit in enumerate(truth)
                                 if _point_in(pred["box"], unit["point"]))
                used_predictions, used_truth = set(), set()
                matches = []
                for _, pi, ti in choices:
                    if pi not in used_predictions and ti not in used_truth:
                        used_predictions.add(pi)
                        used_truth.add(ti)
                        matches.append((pi, ti))
                counts = totals[layer][zone]
                counts["true_positive"] += len(matches)
                counts["false_positive"] += len(candidates) - len(matches)
                counts["false_negative"] += len(truth) - len(matches)
                for pi, ti in matches:
                    unit = truth[ti]
                    if layer != "full_reader" or not unit.get("name"):
                        continue
                    identity["reviewed_matches"] += 1
                    identity["correct"] += candidates[pi]["candidate_name"] == unit["name"]
                details.append({"source_id": key[0], "second": key[1],
                                "zone": zone, "layer": layer,
                                "truth": len(truth), "predictions": len(candidates),
                                "matched": len(matches),
                                "unmatched_prediction_boxes":
                                    [candidates[i]["box"] for i in range(len(candidates))
                                     if i not in used_predictions]})
        for unit in identity_only:
            candidates = _predictions(frame, unit["zone"], "full_reader")
            matches = [(_center_distance(candidate["box"], unit["point"]), candidate)
                       for candidate in candidates
                       if _point_in(candidate["box"], unit["point"])]
            identity["reviewed_probes"] += 1
            if matches:
                _, matched = min(matches, key=lambda row: row[0])
                identity["reviewed_matches"] += 1
                identity["correct"] += matched["candidate_name"] == unit["name"]
                details.append({"source_id": key[0], "second": key[1],
                                "zone": unit["zone"], "layer": "identity_probe",
                                "point": unit["point"], "verified_name": unit["name"],
                                "predicted_name": matched["candidate_name"],
                                "box": matched["box"], "evidence": unit["evidence"]})
            else:
                details.append({"source_id": key[0], "second": key[1],
                                "zone": unit["zone"], "layer": "identity_probe",
                                "point": unit["point"], "verified_name": unit["name"],
                                "predicted_name": None, "evidence": unit["evidence"]})
    return {"schema_version": 1, "review_method": review["review_method"],
            "independent_human_ground_truth": False,
            "reviewed_frames": len(seen),
            "coverage": {layer: {zone: dict(totals[layer][zone]) for zone in ZONES}
                         for layer in ("detector", "full_reader")},
            "identity_on_visually_verified_matches": dict(identity),
            "details": details,
            "limitations": ["Small assistant-reviewed subset; not match-level accuracy.",
                            "Point matching measures body-centre coverage, not IoU.",
                            "Only listed zones/frames were reviewed."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    observations = [json.loads(line) for line in args.observations.read_text().splitlines()]
    review = json.loads(args.review.read_text())
    result = score(observations, review)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("reviewed_frames", "coverage",
                                                  "identity_on_visually_verified_matches")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
