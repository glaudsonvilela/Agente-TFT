"""Map B1 health bar evidence to candidate cells without claiming occupancy."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


def validate(profile: dict, board: dict) -> None:
    if (profile.get("schema_version"), profile.get("id"), profile.get("board_profile_id")) != (
            1, "match001-bar-to-cell-candidates-v1", board.get("id")):
        raise ValueError("bar-to-cell profile mismatch")
    if (profile.get("reference_width"), profile.get("reference_height")) != (
            board.get("reference_width"), board.get("reference_height")):
        raise ValueError("bar-to-cell resolution mismatch")
    bands = profile.get("bands")
    if not isinstance(bands, list) or [(b.get("zone"), b.get("row")) for b in bands] != (
            [("board", row) for row in range(4)] + [("bench", None)]):
        raise ValueError("bar-to-cell bands incomplete")
    prior = -1
    for band in bands:
        low, high = band.get("min_bar_y"), band.get("max_bar_y")
        if (type(low) is not int or type(high) is not int or low <= prior or
                high < low or high >= board["reference_height"]):
            raise ValueError("bar-to-cell bands overlap or escape frame")
        prior = high
    residual = profile.get("max_horizontal_residual_px")
    if type(residual) is not int or not 0 < residual <= 100:
        raise ValueError("invalid horizontal residual")


def project(read: dict, profile: dict, board: dict,
            allow_unmatched_arena: bool = False) -> dict:
    validate(profile, board)
    if read.get("profile") != board["id"]:
        raise ValueError("B1 report profile mismatch")
    matched = read.get("projection_status") == "reference_arena_match"
    if not matched and not (allow_unmatched_arena and read.get("projection_status") == "unresolved"):
        return {"status": "projection_unavailable", "candidates": [], "unassigned": [],
                "occupancy_established": False, "ground_assignment_established": False}
    candidates, unassigned = [], []
    for marker in read["markers"]:
        if marker.get("color") != "green":
            unassigned.append({"marker_id": marker["id"], "reason": "not_green_bar"})
            continue
        rect = marker["rect"]
        center_x, y = rect["x"] + rect["width"] / 2, rect["y"]
        bands = [band for band in profile["bands"] if band["min_bar_y"] <= y <= band["max_bar_y"]]
        if len(bands) != 1:
            unassigned.append({"marker_id": marker["id"], "reason": "outside_bar_bands"})
            continue
        band = bands[0]
        if band["zone"] == "board":
            left, right, _ = board["board_rows"][band["row"]]
            centers = [left + (right - left) * col / 6 for col in range(7)]
        else:
            centers = board["bench_centers"]
        index = min(range(len(centers)), key=lambda col: abs(center_x - centers[col]))
        residual = round(abs(center_x - centers[index]), 3)
        if residual > profile["max_horizontal_residual_px"]:
            unassigned.append({"marker_id": marker["id"], "reason": "horizontal_residual_too_large"})
            continue
        candidates.append({"marker_id": marker["id"], "zone": band["zone"],
                           "row": band["row"], "cell_or_slot": index, "bar_center": [center_x, y],
                           "horizontal_residual_px": residual, "status": "candidate_only",
                           "ground_point": None, "unit_id": None, "occupancy": None})
    counts = Counter((row["zone"], row["row"], row["cell_or_slot"]) for row in candidates)
    for row in candidates:
        if counts[(row["zone"], row["row"], row["cell_or_slot"])] > 1:
            row["status"] = "ambiguous_collision"
    return {"status": "candidate_only" if matched else "bar_geometry_only_unmatched_arena",
            "candidates": candidates, "unassigned": unassigned,
            "occupancy_established": False, "ground_assignment_established": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--board-profile", type=Path, required=True)
    parser.add_argument("--projection-profile", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    board = json.loads(args.board_profile.read_text())
    profile = json.loads(args.projection_profile.read_text())
    records = [{"timestamp_ms": record["read"]["timestamp_ms"],
                "projection": project(record["read"], profile, board)} for record in report["records"]]
    print(json.dumps({"schema_version": 1, "policy": "board_hub_position_candidates_v1",
                      "profile": profile["id"], "records": records,
                      "unit_identity_established": False, "game_state_updated": False},
                     ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
