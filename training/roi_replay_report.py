from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any

CANONICAL_ROI_NAMES = {
    "levelxp": "level_xp",
    "playerlist": "player_list",
}


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


def canonical_roi(value: str) -> str:
    normalized = value.strip().lower()
    return CANONICAL_ROI_NAMES.get(normalized, normalized)


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


def _episodes(times: list[int], scores: list[float], gap_ms: int) -> list[dict[str, Any]]:
    if not times:
        return []

    pairs = sorted(zip(times, scores, strict=False), key=lambda pair: pair[0])
    groups: list[list[tuple[int, float]]] = [[pairs[0]]]

    for pair in pairs[1:]:
        if pair[0] - groups[-1][-1][0] <= gap_ms:
            groups[-1].append(pair)
        else:
            groups.append([pair])

    episodes = []
    for group in groups:
        start = group[0][0]
        end = group[-1][0]
        episodes.append(
            {
                "start_ms": start,
                "end_ms": end,
                "duration_ms": end - start,
                "raw_changes": len(group),
                "peak_score": max(score for _, score in group),
            }
        )
    return episodes


def _per_roi_metrics(
    counts: Counter[str],
    scores: dict[str, list[float]],
    times: dict[str, list[int]],
    duration_minutes: float | None,
    episode_gap_ms: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for roi in sorted(counts):
        roi_scores = scores.get(roi, [])
        roi_times = sorted(times.get(roi, []))
        gaps = [
            float(b - a)
            for a, b in zip(roi_times, roi_times[1:])
            if b >= a
        ]
        episode_rows = _episodes(
            roi_times,
            roi_scores if len(roi_scores) == len(roi_times) else [0.0] * len(roi_times),
            episode_gap_ms,
        )
        episode_durations = [float(row["duration_ms"]) for row in episode_rows]
        result[roi] = {
            "changes": counts[roi],
            "changes_per_minute": (
                counts[roi] / duration_minutes if duration_minutes else None
            ),
            "episodes": len(episode_rows),
            "episodes_per_minute": (
                len(episode_rows) / duration_minutes if duration_minutes else None
            ),
            "raw_changes_per_episode_p50": (
                median([float(row["raw_changes"]) for row in episode_rows])
                if episode_rows
                else None
            ),
            "episode_duration_ms_p50": (
                median(episode_durations) if episode_durations else None
            ),
            "score_p50": median(roi_scores) if roi_scores else None,
            "score_p95": percentile(roi_scores, 0.95),
            "score_max": max(roi_scores) if roi_scores else None,
            "gap_ms_p50": median(gaps) if gaps else None,
            "gap_ms_p95": percentile(gaps, 0.95),
            "first_change_ms": roi_times[0] if roi_times else None,
            "last_change_ms": roi_times[-1] if roi_times else None,
        }
    return result


def summarize(
    events: list[dict[str, Any]],
    malformed: int = 0,
    *,
    global_cut_min_rois: int = 6,
    episode_gap_ms: int = 1500,
) -> dict[str, Any]:
    raw_counts: Counter[str] = Counter()
    raw_scores: dict[str, list[float]] = defaultdict(list)
    raw_times: dict[str, list[int]] = defaultdict(list)

    filtered_counts: Counter[str] = Counter()
    filtered_scores: dict[str, list[float]] = defaultdict(list)
    filtered_times: dict[str, list[int]] = defaultdict(list)

    cochange_counts: Counter[str] = Counter()
    global_cut_timestamps: list[int] = []

    first_ms: int | None = None
    last_ms: int | None = None
    raw_frames_with_changes = 0
    filtered_frames_with_changes = 0
    raw_total_changes = 0
    filtered_total_changes = 0

    for event in events:
        timestamp = event.get("timestamp_ms")
        changes = event.get("changes")
        if not isinstance(timestamp, int) or not isinstance(changes, list):
            continue

        first_ms = timestamp if first_ms is None else min(first_ms, timestamp)
        last_ms = timestamp if last_ms is None else max(last_ms, timestamp)

        parsed: list[tuple[str, float]] = []
        for change in changes:
            if not isinstance(change, dict):
                continue
            roi = change.get("roi")
            score = change.get("score")
            if not isinstance(roi, str):
                continue
            numeric_score = (
                float(score)
                if isinstance(score, (int, float)) and math.isfinite(float(score))
                else 0.0
            )
            parsed.append((canonical_roi(roi), numeric_score))

        if not parsed:
            continue

        raw_frames_with_changes += 1
        unique_names = sorted({roi for roi, _ in parsed})

        for roi, score in parsed:
            raw_total_changes += 1
            raw_counts[roi] += 1
            raw_scores[roi].append(score)
            raw_times[roi].append(timestamp)

        if len(unique_names) > 1:
            cochange_counts["+".join(unique_names)] += 1

        is_global_cut = len(unique_names) >= global_cut_min_rois
        if is_global_cut:
            global_cut_timestamps.append(timestamp)
            continue

        filtered_frames_with_changes += 1
        for roi, score in parsed:
            filtered_total_changes += 1
            filtered_counts[roi] += 1
            filtered_scores[roi].append(score)
            filtered_times[roi].append(timestamp)

    duration_ms = None
    if first_ms is not None and last_ms is not None:
        duration_ms = max(0, last_ms - first_ms)
    duration_minutes = (
        duration_ms / 60000.0
        if duration_ms is not None and duration_ms > 0
        else None
    )

    return {
        "schema_version": 2,
        "event_lines": len(events),
        "malformed_lines": malformed,
        "first_change_ms": first_ms,
        "last_change_ms": last_ms,
        "duration_between_changes_ms": duration_ms,
        "filters": {
            "global_cut_min_rois": global_cut_min_rois,
            "episode_gap_ms": episode_gap_ms,
        },
        "global_cuts": {
            "frames": len(global_cut_timestamps),
            "per_minute": (
                len(global_cut_timestamps) / duration_minutes
                if duration_minutes
                else None
            ),
            "first_ms": global_cut_timestamps[0] if global_cut_timestamps else None,
            "last_ms": global_cut_timestamps[-1] if global_cut_timestamps else None,
        },
        "raw": {
            "frames_with_changes": raw_frames_with_changes,
            "total_changes": raw_total_changes,
            "per_roi": _per_roi_metrics(
                raw_counts,
                raw_scores,
                raw_times,
                duration_minutes,
                episode_gap_ms,
            ),
        },
        "semantic": {
            "frames_with_changes": filtered_frames_with_changes,
            "total_changes": filtered_total_changes,
            "per_roi": _per_roi_metrics(
                filtered_counts,
                filtered_scores,
                filtered_times,
                duration_minutes,
                episode_gap_ms,
            ),
        },
        "top_cochanges": [
            {"rois": key.split("+"), "count": count}
            for key, count in cochange_counts.most_common(20)
        ],
        "notes": [
            "raw contains every ROI change emitted by the detector.",
            "semantic excludes frames where at least global_cut_min_rois changed together.",
            "episodes collapse repeated changes separated by <= episode_gap_ms into one episode.",
            "Global-cut filtering and episode clustering reduce animation/transition noise; they do not prove perception accuracy.",
            "Only change ROI coordinates or thresholds after comparing semantic episodes with replay ground truth.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize JSONL output from agente-tft-roi-replay-inspect."
    )
    parser.add_argument("events_jsonl", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--global-cut-min-rois", type=int, default=6)
    parser.add_argument("--episode-gap-ms", type=int, default=1500)
    args = parser.parse_args()

    if args.global_cut_min_rois < 2:
        raise SystemExit("--global-cut-min-rois must be >= 2")
    if args.episode_gap_ms < 0:
        raise SystemExit("--episode-gap-ms must be >= 0")

    events, malformed = load_events(args.events_jsonl)
    report = summarize(
        events,
        malformed,
        global_cut_min_rois=args.global_cut_min_rois,
        episode_gap_ms=args.episode_gap_ms,
    )
    encoded = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
