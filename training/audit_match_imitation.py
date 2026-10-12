"""Audit whether a complete replay can actually train the player policy.

This reads recorded Motor 1 -> Motor 2 frames and independently reviewed
video actions. It never converts an unreviewed image change into a label.
"""

from __future__ import annotations

import argparse
import bisect
import json
from collections import Counter
from pathlib import Path


def read_frames(path: Path) -> list[dict]:
    frames = []
    for line in path.open(encoding="utf-8"):
        try:
            frame = json.loads(line).get("answer", {}).get("player_policy_frame")
        except json.JSONDecodeError:
            continue  # A live recorder may have an unfinished final line.
        if isinstance(frame, dict):
            frames.append(frame)
    return sorted(frames, key=lambda frame: frame["source_ms"])


def audit(frames: list[dict], ledger: Path) -> dict:
    times = [frame["source_ms"] for frame in frames]
    totals = Counter()
    actions = []
    for line in ledger.open(encoding="utf-8"):
        row = json.loads(line)
        totals[row.get("evidence_status", "missing_status")] += 1
        if not row.get("action_type") or not str(row.get("evidence_status", "")).startswith("reviewed"):
            continue
        before = row["sampled_before_ms"]
        index = bisect.bisect_left(times, before) - 1
        frame = frames[index] if index >= 0 else None
        gap = before - frame["source_ms"] if frame else None
        candidates = (frame or {}).get("candidates") or []
        types = sorted({candidate.get("action", {}).get("type") for candidate in candidates
                        if isinstance(candidate, dict) and isinstance(candidate.get("action"), dict)})
        receipt = (frame or {}).get("motor1_ingest") or {}
        target = row.get("motor2_equivalent_type")
        causal_frame = frame is not None and gap is not None and 0 < gap <= 2000
        full_receipt = (receipt.get("reader_received") is True
                        and receipt.get("hub_received") is True)
        action_available = target in types
        label_linkable = (causal_frame and full_receipt and action_available
                          and frame.get("source_video_sha256") == row.get("source_sha256")
                          and frame.get("match_id") == row.get("match_id")
                          and frame.get("scene_status") == "stable_planning"
                          and frame.get("full_motor1_interpreted_by_policy") is True)
        blockers = []
        if not causal_frame:
            blockers.append("no_pre_action_state_within_2s")
        if not full_receipt:
            blockers.append("motor1_reader_or_hub_missing")
        if not action_available:
            blockers.append("observed_action_absent_from_motor2_candidates")
        if not frame or frame.get("source_video_sha256") != row.get("source_sha256") \
                or frame.get("match_id") != row.get("match_id"):
            blockers.append("video_identity_not_bound_to_motor2_frame")
        if not frame or frame.get("scene_status") != "stable_planning":
            blockers.append("planning_scene_not_verified")
        if not frame or frame.get("full_motor1_interpreted_by_policy") is not True:
            blockers.append("policy_does_not_interpret_complete_motor1_packet")
        actions.append({
            "before_ms": before, "action": row["action_type"],
            "motor2_type": target, "nearest_motor2_ms": frame["source_ms"] if frame else None,
            "gap_ms": gap, "causal_frame_within_2s": causal_frame,
            "reader_and_hub_received": full_receipt, "candidate_types": types,
            "observed_action_is_candidate": action_available,
            "source_identity_attached": bool(frame and frame.get("source_video_sha256") == row.get("source_sha256")
                                             and frame.get("match_id") == row.get("match_id")),
            "scene_verified": bool(frame and frame.get("scene_status") == "stable_planning"),
            "all_motor1_interpreted_by_policy": bool(frame and frame.get("full_motor1_interpreted_by_policy") is True),
            "training_eligible": label_linkable,
            "blockers": blockers,
        })
    complete_action_inventory = totals["unreviewed_transition"] == 0
    coverage = {
        "reader_and_hub_received": sum(
            (frame.get("motor1_ingest") or {}).get("reader_received") is True
            and (frame.get("motor1_ingest") or {}).get("hub_received") is True
            for frame in frames),
        "shop_offers_present": sum((frame.get("whole_state") or {}).get("fresh_shop_offers", 0) > 0
                                   for frame in frames),
        "board_champion_identity_verified": sum(
            (frame.get("whole_state") or {}).get("board_identity_verified") is True
            for frame in frames),
        "item_candidates_present": sum((frame.get("whole_state") or {}).get("item_candidates", 0) > 0
                                       for frame in frames),
        "opponent_linked": sum((frame.get("whole_state") or {}).get("opponent_linked") is True
                               for frame in frames),
    }
    return {
        "schema": "match_imitation_readiness_v1",
        "motor2_frames": len(frames),
        "frame_coverage": coverage,
        "last_motor2_ms": times[-1] if times else None,
        "ledger_status_counts": dict(totals),
        "full_match_action_inventory_complete": complete_action_inventory,
        "reviewed_actions": len(actions),
        "causally_aligned_within_2s": sum(x["causal_frame_within_2s"] for x in actions),
        "action_available_in_motor2": sum(x["observed_action_is_candidate"] for x in actions),
        "training_eligible_actions": sum(x["training_eligible"] for x in actions),
        "optimizer_allowed": (complete_action_inventory and bool(actions)
                              and all(x["training_eligible"] for x in actions)),
        "actions": actions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(read_frames(args.observations), args.ledger)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "actions"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
