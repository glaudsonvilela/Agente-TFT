"""Validate manually reviewed VOD transitions against their source frames."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


GOLD_FIELDS = {"reroll": ("reroll_cost", -1),
               "buy_unit": ("unit_cost", -1),
               "sell_unit": ("sale_gold", 1),
               "buy_xp": ("xp_cost", -1)}


def validate(manifest_path: Path, frames_dir: Path) -> dict[str, int]:
    manifest = json.loads(manifest_path.read_text())
    if manifest["source_resolution"] != [1920, 1080] or manifest["sampling_fps"] != 5:
        raise ValueError("unexpected extraction profile")
    actions = manifest["actions"]
    hard_cases = manifest["hard_cases"]
    if not actions or not hard_cases:
        raise ValueError("review requires positive actions and hard cases")
    seen = set()
    for row in actions + hard_cases:
        before_number = int(row["before"].removeprefix("frame-").removesuffix(".jpg"))
        after_number = int(row["after"].removeprefix("frame-").removesuffix(".jpg"))
        if after_number != before_number + 1 or (before_number, after_number) in seen:
            raise ValueError("reviewed frames must be unique adjacent pairs")
        seen.add((before_number, after_number))
        for side in ("before", "after"):
            frame = frames_dir / row[side]
            if frame.parent != frames_dir or not frame.is_file():
                raise ValueError(f"missing frame: {frame}")
            actual = hashlib.sha256(frame.read_bytes()).hexdigest()
            if actual != row[f"{side}_sha256"]:
                raise ValueError(f"frame hash mismatch: {frame}")
        if not row.get("visual_evidence"):
            raise ValueError("missing independent visual rationale")
    for row in actions:
        cost_field, direction = GOLD_FIELDS.get(row["type"], (None, None))
        if cost_field is None or cost_field not in row or row[cost_field] < 0 or (
                row[cost_field] == 0 and row["type"] != "reroll") or (
                row["gold_after"] - row["gold_before"] != direction * row[cost_field]):
            raise ValueError(f"gold delta does not support label: {row['before']}")
        if not row.get("stage") or "-" not in row["stage"]:
            raise ValueError("action needs a stable reviewed round")
        if row["type"] in {"reroll", "buy_unit"}:
            if len(row["shop_before"]) != 5 or len(row["shop_after"]) != 5:
                raise ValueError("shop snapshot must have five slots")
        if row["type"] == "reroll" and row["shop_before"] == row["shop_after"]:
            raise ValueError("reroll without a shop change")
        if row["type"] == "buy_unit":
            disappeared = [a for a, b in zip(row["shop_before"], row["shop_after"])
                           if a is not None and b is None]
            if disappeared != [row["unit"]]:
                raise ValueError("bought unit did not disappear from exactly one shop slot")
        if row["type"] == "buy_xp":
            if row["level_after"] not in (row["level_before"], row["level_before"] + 1):
                raise ValueError("invalid level transition")
            expected_xp = row["xp_before"] + row["xp_gained"]
            if row["level_after"] > row["level_before"]:
                expected_xp -= row["xp_to_next_before"]
            if row["xp_after"] != expected_xp:
                raise ValueError("XP bar does not support buy_xp")
    for row in hard_cases:
        if row["review_status"] == "not_a_reroll":
            valid = row["gold_before"] == row["gold_after"]
        elif row["review_status"] == "natural_round_transition":
            valid = row["stage_before"] != row["stage_after"]
        else:
            valid = False
        if not valid:
            raise ValueError("invalid hard-case review")
    return {"reviewed_actions": len(actions), "hard_cases": len(hard_cases),
            "reviewed_frame_pairs": len(seen)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--frames-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.manifest, args.frames_dir)))


if __name__ == "__main__":
    main()
