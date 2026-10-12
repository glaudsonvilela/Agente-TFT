"""Replay exact local economy branches from reviewed 1080p decisions.

This is a scoped transition simulator. It does not simulate a match, infer a
shop roll, award a placement, or create preference/reward labels for policy
training. The observed branch must agree with the next reviewed video frame.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.validate_dense_action_review import validate


def buy_xp_branches(row: dict) -> dict:
    if row.get("type") != "buy_xp":
        raise ValueError("only reviewed buy_xp decisions are supported")
    gold = row["gold_before"]
    level = row["level_before"]
    xp = row["xp_before"]
    threshold = row["xp_to_next_before"]
    cost = row["xp_cost"]
    gained = row["xp_gained"]
    if any(type(v) is not int for v in (gold, level, xp, threshold, cost, gained)):
        raise ValueError("economy state must use exact integer observations")
    if not (gold >= cost > 0 and level > 0 and 0 <= xp < threshold and gained > 0):
        raise ValueError("invalid or unaffordable buy_xp state")
    # One purchase can cross at most one known level threshold. Beyond that,
    # the next threshold would also have to be observed before branching.
    if xp + gained >= 2 * threshold:
        raise ValueError("next level threshold is not observed")
    leveled = xp + gained >= threshold
    purchase = {
        "gold": gold - cost,
        "level": level + int(leveled),
        "xp": xp + gained - (threshold if leveled else 0),
    }
    observed = {"gold": row["gold_after"], "level": row["level_after"],
                "xp": row["xp_after"]}
    if purchase != observed:
        raise ValueError("simulated purchase disagrees with reviewed video")
    return {
        "stage": row["stage"],
        "before_frame": row["before"],
        "after_frame": row["after"],
        "observed_action": "buy_xp",
        "branches": {
            "hold": {"gold": gold, "level": level, "xp": xp},
            "buy_xp": purchase,
        },
        "observed_branch_matches_video": True,
        "scope": "immediate_gold_level_xp_only",
        "unknown_outcomes": ["future_shop", "combat", "placement", "future_opponent_actions"],
        "policy_preference_label": None,
    }


def simulate(manifest_path: Path, frames_dir: Path) -> dict:
    summary = validate(manifest_path, frames_dir)
    manifest = json.loads(manifest_path.read_text())
    branches = [buy_xp_branches(row) for row in manifest["actions"]
                if row["type"] == "buy_xp"]
    return {
        "schema_version": 1,
        "kind": "reviewed_local_economy_branches",
        "source_clip": manifest.get("source_clip"),
        "source_clip_sha256": manifest.get("source_clip_sha256"),
        "source_resolution": manifest["source_resolution"],
        "reviewed_actions": summary["reviewed_actions"],
        "simulated_decisions": len(branches),
        "branches": branches,
        "full_match_simulator_ready": False,
        "synthetic_policy_labels_created": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--frames-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = simulate(args.manifest, args.frames_dir)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"simulated_decisions": result["simulated_decisions"],
                      "synthetic_policy_labels_created": 0}))


if __name__ == "__main__":
    main()
