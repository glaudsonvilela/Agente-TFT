"""Keep every reviewed visual transition in a complete match action ledger.

Visual changes are discovery candidates, never automatically called actions.
The ledger keeps actions outside the current Rust candidate vocabulary so they
are visible as an integration gap rather than silently removed from training.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ACTION_FAMILIES = {
    "buy_unit": "roster", "sell_unit": "roster", "move_unit": "positioning",
    "bench_unit": "positioning", "field_unit": "positioning",
    "reroll": "economy", "buy_xp": "economy", "lock_shop": "economy",
    "unlock_shop": "economy", "equip_item": "items", "unequip_item": "items",
    "combine_items": "items", "choose_augment": "augment",
    "reroll_augment": "augment", "choose_encounter": "special_choice",
    "choose_carousel": "special_choice", "choose_anvil": "special_choice",
    "scout_opponent": "information", "reposition": "positioning",
    "wait": "inaction",
}

# These are semantic matches, not a claim that the concrete target is bound.
MOTOR2_TYPES = {"buy_xp": "buy_xp", "reroll": "roll"}


def frame_number(filename: str) -> int:
    if not filename.startswith("frame-") or not filename.endswith(".jpg"):
        raise ValueError(f"invalid numbered frame: {filename}")
    return int(filename[6:-4])


def build_ledger(changes: list[dict], review: dict, *, match_id: str,
                 source_sha256: str, sampling_fps: int = 5,
                 sample_start_seconds: float = 0,
                 video_duration_seconds: float | None = None) -> tuple[list[dict], dict]:
    if not changes or sampling_fps < 1 or len(source_sha256) != 64:
        raise ValueError("source video and visual transitions required")
    if sample_start_seconds < 0 or (video_duration_seconds is not None and
                                   video_duration_seconds <= sample_start_seconds):
        raise ValueError("invalid sample time boundaries")
    if review.get("source_clip_sha256") not in (None, source_sha256):
        raise ValueError("review and video identity differ")
    labels = {}
    for row in review.get("actions", []):
        if row.get("type") not in ACTION_FAMILIES:
            raise ValueError(f"unknown reviewed action type: {row.get('type')}")
        key = (row["before"], row["after"])
        if key in labels:
            raise ValueError("duplicate reviewed action")
        labels[key] = ("reviewed_action", row)
    for row in review.get("hard_cases", []):
        key = (row["before"], row["after"])
        if key in labels:
            raise ValueError("conflicting reviewed evidence")
        labels[key] = ("reviewed_non_action", row)
    ordered = sorted(changes, key=lambda row: frame_number(row["before_frame"]))
    ledger = []
    previous = None
    for change in ordered:
        before, after = change["before_frame"], change["after_frame"]
        number = frame_number(before)
        if frame_number(after) != number + 1 or (previous is not None and number != previous + 1):
            raise ValueError("sampled visual sequence has a gap")
        previous = number
        key = (before, after)
        status, review_row = labels.pop(key, ("unreviewed_transition", None))
        action_type = review_row.get("type") if status == "reviewed_action" else None
        ledger.append({
            "match_id": match_id, "source_sha256": source_sha256,
            "before_frame": before, "after_frame": after,
            "sampled_before_ms": round(sample_start_seconds * 1000 +
                                       (number - 1) * 1000 / sampling_fps),
            "sampled_after_ms": round(sample_start_seconds * 1000 +
                                      number * 1000 / sampling_fps),
            "visual_region_change": change["region_change"],
            "evidence_status": status, "action_type": action_type,
            "action_family": ACTION_FAMILIES[action_type] if action_type else None,
            "action_details": ({key: value for key, value in review_row.items()
                                if key not in {"before_sha256", "after_sha256"}}
                               if review_row else None),
            "motor2_equivalent_type": MOTOR2_TYPES.get(action_type),
            "motor2_exact_candidate_bound": False,
            "training_eligible": False,
        })
    if labels:
        raise ValueError(f"reviewed evidence absent from visual sequence: {len(labels)}")
    known = sum(row["evidence_status"] == "reviewed_action" for row in ledger)
    report = {"match_id": match_id, "source_sha256": source_sha256,
              "visual_sampling_fps": sampling_fps,
              "sample_start_seconds": sample_start_seconds,
              "sample_last_seconds": round(sample_start_seconds +
                                           frame_number(ledger[-1]["after_frame"]) /
                                           sampling_fps, 3),
              "source_video_duration_seconds": video_duration_seconds,
              "source_video_decoded_at_native_fps": False,
              "sampled_adjacent_pairs_kept": len(ledger),
              "reviewed_actions": known,
              "reviewed_non_actions": sum(row["evidence_status"] == "reviewed_non_action"
                                          for row in ledger),
              "unreviewed_transitions": sum(row["evidence_status"] == "unreviewed_transition"
                                            for row in ledger),
              "action_types_reviewed": sorted({row["action_type"] for row in ledger
                                               if row["action_type"]}),
              "all_actual_player_actions_identified": False,
              "macro_decisions_validated": False,
              "motor2_exact_candidates_bound": 0}
    return ledger, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changes", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--match-id", required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--sample-start-seconds", type=float, default=0)
    parser.add_argument("--video-duration-seconds", type=float)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("use a new output path")
    changes = [json.loads(line) for line in args.changes.read_text().splitlines()
               if line.strip()]
    review = json.loads(args.review.read_text())
    ledger, report = build_ledger(changes, review, match_id=args.match_id,
                                  source_sha256=args.source_sha256,
                                  sample_start_seconds=args.sample_start_seconds,
                                  video_duration_seconds=args.video_duration_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as stream:
        for row in ledger:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    args.output.with_suffix(".report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
