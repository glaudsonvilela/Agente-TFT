"""One reviewable frame observation across fixed board geometry and versioned art."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from training.board_hub_equipped_candidates import run as equipped_run
from training.board_hub_item_candidates import TemplateBank, load_reference, run as inventory_run
from training.board_hub_position_candidates import project


def build_snapshot(image, read: dict, board: dict, position_profile: dict,
                   equipped_profile: dict, inventory_profile: dict, manifest: dict,
                   entries: list[dict], icon_dir: Path, match_scope: str,
                   recording_context: dict | None = None,
                   inventory_templates: tuple[TemplateBank, int] | None = None,
                   equipped_templates: tuple[TemplateBank, int] | None = None,
                   allow_unmatched_arena: bool = False) -> dict:
    if recording_context is not None:
        if (recording_context.get("schema_version") != 1 or
                recording_context.get("set_key") != manifest["set_key"] or
                not recording_context.get("tft_patch")):
            raise ValueError("recording set/patch context does not match visual reference")
    positions = project(read, position_profile, board,
                        allow_unmatched_arena=allow_unmatched_arena)
    inventory = inventory_run(image, inventory_profile, manifest, entries, icon_dir, match_scope,
                              preloaded_templates=inventory_templates)
    equipped = equipped_run(image, read, board, position_profile, equipped_profile,
                            manifest, entries, icon_dir, match_scope,
                            preloaded_templates=equipped_templates,
                            allow_unmatched_arena=allow_unmatched_arena)
    grouped = {}
    for row in positions["candidates"]:
        grouped.setdefault((row["zone"], row["row"], row["cell_or_slot"]), []).append(row["marker_id"])
    board_cells = []
    for row, (left, right, y) in enumerate(board["board_rows"]):
        for col in range(7):
            board_cells.append({"row": row, "col": col,
                                "screen_center": [left + (right - left) * col / 6, y],
                                "marker_candidates": grouped.get(("board", row, col), []),
                                "occupancy": None, "unit_id": None})
    bench_slots = [{"slot": slot, "screen_center": [x, board["bench_y"]],
                    "marker_candidates": grouped.get(("bench", None, slot), []),
                    "occupancy": None, "unit_id": None}
                   for slot, x in enumerate(board["bench_centers"])]
    units = [{"marker_id": row["marker_id"], "position_candidate": row["position_candidate"],
              "equipped_slots": row["slots"], "champion_id": None, "stars": None}
             for row in equipped["markers"]]
    return {"schema_version": 1, "policy": "board_hub_snapshot_v1",
            "timestamp_ms": read["timestamp_ms"], "geometry_profile": board["id"],
            "reference_sha256": manifest["reference_sha256"],
            "data_dragon_version": manifest["version"], "set_key": manifest["set_key"],
            "set_binding": "recording_context_set_match" if recording_context else "unverified_for_recording",
            "tft_patch": recording_context["tft_patch"] if recording_context else None,
            "patch_basis": recording_context.get("version_basis") if recording_context else None,
            "visual_reference_patch_compatibility": "unverified",
            "matching_scope": match_scope,
            "arena_projection_status": read["projection_status"],
            "position_status": positions["status"],
            "board_cells": board_cells, "bench_slots": bench_slots,
            "observed_markers": units, "unassigned_markers": positions["unassigned"],
            "inventory": inventory, "item_catalog_entries": len(entries),
            "matching_item_entries": inventory["matching_entries"],
            "capabilities": {"perspective_known": False, "unit_identity_established": False,
                             "unit_ground_point_established": False,
                             "item_identity_established": False,
                             "independent_accuracy_measured": False,
                             "game_state_updated": False}}


def main() -> None:
    from PIL import Image

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--frame-index", type=int, required=True)
    parser.add_argument("--board-profile", type=Path, required=True)
    parser.add_argument("--position-profile", type=Path, required=True)
    parser.add_argument("--equipped-profile", type=Path, required=True)
    parser.add_argument("--inventory-profile", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--recording-context", type=Path, required=True)
    parser.add_argument("--icon-dir", type=Path, required=True)
    parser.add_argument("--match-scope", choices=("all", "set_path", "set_plus_core"), default="set_plus_core")
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    if not 1 <= args.frame_index <= len(report["records"]):
        parser.error("frame index outside report")
    read = report["records"][args.frame_index - 1]["read"]
    match = re.fullmatch(r"\d{4}_(\d{9})ms\.jpe?g", args.image.name)
    if match is None or int(match[1]) != read["timestamp_ms"]:
        parser.error("image filename timestamp does not match B1 frame")
    board = json.loads(args.board_profile.read_text())
    position = json.loads(args.position_profile.read_text())
    equipped = json.loads(args.equipped_profile.read_text())
    inventory = json.loads(args.inventory_profile.read_text())
    context = json.loads(args.recording_context.read_text())
    manifest, entries = load_reference(args.reference)
    with Image.open(args.image) as image:
        result = build_snapshot(image, read, board, position, equipped, inventory,
                                manifest, entries, args.icon_dir, args.match_scope, context)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
