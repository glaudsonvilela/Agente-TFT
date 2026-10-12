"""Run the scoped 10-hour experiment on a mounted Akash persistent volume.

This entry point intentionally does not call the full-match player-policy
preflight: the experimental task predicts only future visible HUD readings.
The strict strategic-policy gate remains unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from training.akash_policy_supervisor import ensure_persistent, run
from training.experimental_video_state import (TEST_MATCH_ID,
                                               VALIDATION_MATCH_ID, load_examples)


def preflight(index: Path, frames: Path, holdout_vod: str,
              branches: Path | None = None) -> dict:
    training, heldout = load_examples(index, frames, holdout_vod)
    index_digest = hashlib.sha256(index.read_bytes()).hexdigest()
    source_ids = {row["source_vod_id"] for row in training}
    holdout_ids = {row["source_vod_id"] for row in heldout}
    if source_ids & holdout_ids:
        raise ValueError("source VOD leakage between train and validation")
    if holdout_ids != {holdout_vod}:
        raise ValueError("requested holdout VOD missing")
    heldout_matches = {row["match_id"] for row in heldout}
    if heldout_matches != {VALIDATION_MATCH_ID, TEST_MATCH_ID}:
        raise ValueError("validation and untouched test matches are both required")
    coverage = {}
    for name, mid in (("validation", VALIDATION_MATCH_ID), ("test", TEST_MATCH_ID)):
        rows = [row for row in heldout if row["match_id"] == mid]
        coverage[name] = {field: int(sum(row["state_valid"][i] > 0 and
                                         row["target_valid"][i] > 0 for row in rows))
                          for i, field in enumerate(("stage", "gold", "level"))}
        if any(value < 1 for value in coverage[name].values()):
            raise ValueError(f"no comparable held-out {name} readings for every field")
    branch_count = 0
    if branches is not None:
        economy = json.loads(branches.read_text())
        if economy.get("full_match_simulator_ready") is not False or economy.get("synthetic_policy_labels_created") != 0:
            raise ValueError("economy branch dataset is unsafe for policy labels")
        branch_count = economy["simulated_decisions"]
        if branch_count != len(economy["branches"]) or branch_count < 1:
            raise ValueError("invalid economy branch count")
    return {"kind": "experimental_visible_state_forecast",
            "not_player_policy": True, "input_sha256": index_digest,
            "training_pairs": len(training),
            "validation_pairs": sum(row["match_id"] == VALIDATION_MATCH_ID for row in heldout),
            "test_pairs": sum(row["match_id"] == TEST_MATCH_ID for row in heldout),
            "comparable_heldout_readings": coverage,
            "train_vods": sorted(source_ids), "heldout_vods": sorted(holdout_ids),
            "simulator_policy_labels": 0,
            "separate_validated_economy_scenes": branch_count}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--branches", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--persistent-root", type=Path, default=Path("/workspace"))
    parser.add_argument("--holdout-vod", default="2894958056")
    parser.add_argument("--seconds", type=int, default=36000)
    args = parser.parse_args()
    ensure_persistent(args.workdir, args.persistent_root)
    gate = preflight(args.index, args.frames, args.holdout_vod, args.branches)
    print(json.dumps(gate, ensure_ascii=False), flush=True)
    command = [sys.executable, "-m", "training.experimental_video_state",
               "--index", str(args.index), "--frames", str(args.frames),
               "--output", str(args.workdir), "--holdout-vod", args.holdout_vod,
               "--branches", str(args.branches)]
    result = run(args.workdir, command, seconds=args.seconds,
                 input_identity=gate["input_sha256"])
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
