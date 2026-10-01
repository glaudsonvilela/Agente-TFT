from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def load_events(path: Path) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    malformed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(value, dict):
            events.append(value)
        else:
            malformed += 1
    return events, malformed


def summarize(events: list[dict[str, Any]], malformed: int = 0) -> dict[str, Any]:
    roi_counts: Counter[str] = Counter()
    roi_scores: dict[str, list[float]] = defaultdict(list)
    roi_times: dict[str, list[int]] = defaultdict(list)
    cochange_counts: Counter[str] = Counter()

    first_ms: int | None = None
    last_ms: int | None = None
    frames_with_changes = 0
    total_changes = 0

    for event in events:
        timestamp = event.get("timestamp_ms")
        changes = event.get("changes")
        if not isinstance(timestamp, int) or not isinstance(changes, list):
            continue

        first_ms = timestamp if first_ms is None else min(first_ms, timestamp)
        last_ms = timestamp if last_ms is None else max(last_ms, timestamp)

        names: list[str] = []
        valid_change = False
        for change in changes:
            if not isinstance(change, dict):
                continue
            roi = change.get("roi")
            score = change.get("score")
            if not isinstance(roi, str):
                continue
            valid_change = True
            total_changes += 1
            roi_counts[roi] += 1
            roi_times[roi].append(timestamp)
            names.append(roi)
            if isinstance(score, (int, float)) and math.isfinite(float(score)):
                roi_scores[roi].append(float(score))

        if valid_change:
            frames_with_changes += 1

        unique_names = sorted(set(names))
        if len(unique_names) > 1:
            cochange_counts["+".join(unique_names)] += 1

    duration_ms = None
    if first_ms is not None and last_ms is not None:
        duration_ms = max(0, last_ms - first_ms)

    duration_minutes = (
        duration_ms / 60000.0
        if duration_ms is not None and duration_ms > 0
        else None
    )

    per_roi: dict[str, Any] = {}
    for roi in sorted(roi_counts):
        scores = roi_scores.get(roi, [])
        times = sorted(roi_times.get(roi, []))
        gaps = [
            float(b - a)
            for a, b in zip(times, times[1:])
            if b >= a
        ]
        per_roi[roi] = {
            "changes": roi_counts[roi],
            "changes_per_minute": (
                roi_counts[roi] / duration_minutes
                if duration_minutes
                else None
            ),
            "score_p50": median(scores) if scores else None,
            "score_p95": percentile(scores, 0.95),
            "score_max": max(scores) if scores else None,
            "gap_ms_p50": median(gaps) if gaps else None,
            "gap_ms_p95": percentile(gaps, 0.95),
            "first_change_ms": times[0] if times else None,
            "last_change_ms": times[-1] if times else None,
        }

    return {
        "schema_version": 1,
        "event_lines": len(events),
        "malformed_lines": malformed,
        "frames_with_changes": frames_with_changes,
        "total_changes": total_changes,
        "first_change_ms": first_ms,
        "last_change_ms": last_ms,
        "duration_between_changes_ms": duration_ms,
        "per_roi": per_roi,
        "top_cochanges": [
            {"rois": key.split("+"), "count": count}
            for key, count in cochange_counts.most_common(20)
        ],
        "notes": [
            "This report measures ROI change-detector behavior, not perception accuracy.",
            "Very high event rates can indicate a threshold that is too sensitive.",
            "Very low event rates can indicate a threshold that is too strict or an incorrect ROI.",
            "Compare these metrics against replay scenes and ground truth before changing thresholds.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize JSONL output from agente-tft-roi-replay-inspect."
    )
    parser.add_argument("events_jsonl", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    events, malformed = load_events(args.events_jsonl)
    report = summarize(events, malformed)
    encoded = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
