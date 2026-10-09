"""Inspect three artwork slots below a B1 green bar, linked only by marker ID."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from training.board_hub_item_candidates import (TemplateBank, load_reference,
                                                load_templates, rank_patches,
                                                rank_patch_groups, select_entries)
from training.board_hub_frame import PreparedFrame
from training.board_hub_position_candidates import project


def validate(profile: dict, board: dict) -> None:
    if (profile.get("schema_version"), profile.get("id"), profile.get("board_profile_id")) != (
            1, "match001-equipped-icons-v1", board.get("id")):
        raise ValueError("equipped icon profile mismatch")
    if (profile.get("reference_width"), profile.get("reference_height")) != (
            board.get("reference_width"), board.get("reference_height")):
        raise ValueError("equipped icon resolution mismatch")
    for key, expected in (("slots_per_bar", 3), ("icon_size", 23), ("slot_step_x", 26)):
        if profile.get(key) != expected:
            raise ValueError(f"invalid equipped {key}")
    for axis in ("x", "y"):
        low, high = profile.get("min_offset_" + axis), profile.get("max_offset_" + axis)
        if type(low) is not int or type(high) is not int or low > high or high - low > 10:
            raise ValueError("invalid icon search offsets")
    candidate, empty = profile.get("icon_candidate_max_rms"), profile.get("empty_appearance_min_rms")
    if (type(candidate) not in (int, float) or type(empty) not in (int, float)
            or not 0 <= candidate < empty <= 255):
        raise ValueError("equipped appearance thresholds overlap")


def rank_equipped(frame, marker: dict, slot: int, templates: TemplateBank, profile: dict) -> list[dict]:
    if not templates:
        return []
    patches, rects = equipped_patches(frame, marker, slot, profile)
    ranked = rank_patches(patches, templates)
    for row in ranked:
        row["sample_rect"] = rects[row.pop("sample_index")]
    return ranked


def equipped_patches(frame, marker: dict, slot: int, profile: dict):
    patches = []
    rects = []
    rect = marker["rect"]
    size = profile["icon_size"]
    for dx in range(profile["min_offset_x"], profile["max_offset_x"] + 1):
        for dy in range(profile["min_offset_y"], profile["max_offset_y"] + 1):
            x = rect["x"] + dx + slot * profile["slot_step_x"]
            y = rect["y"] + dy
            patch = frame[y:y + size, x:x + size]
            if patch.shape != (size, size, 3):
                continue
            patches.append(patch)
            rects.append({"x": x, "y": y, "width": size, "height": size})
    return patches, rects


def run(image, read: dict, board: dict, position_profile: dict, equipped_profile: dict,
        manifest: dict, entries: list[dict], icon_dir: Path, match_scope: str = "all",
        preloaded_templates: tuple[TemplateBank, int] | None = None,
        allow_unmatched_arena: bool = False, prepared_frame: PreparedFrame | None = None,
        selected_entries: list[dict] | None = None) -> dict:

    validate(equipped_profile, board)
    prepared = prepared_frame or PreparedFrame.from_image(image)
    rgb = prepared.rgb
    if (rgb.width, rgb.height) != (board["reference_width"], board["reference_height"]):
        raise ValueError("equipped frame resolution mismatch")
    positions = project(read, position_profile, board,
                        allow_unmatched_arena=allow_unmatched_arena)
    if positions["status"] == "projection_unavailable":
        return {"status": "projection_unavailable", "markers": [], "item_identity_established": False,
                "unit_identity_established": False, "game_state_updated": False}
    locations = {row["marker_id"]: row for row in positions["candidates"]}
    selected = selected_entries if selected_entries is not None else select_entries(
        entries, manifest.get("set_key", ""), match_scope)
    templates, available = (preloaded_templates if preloaded_templates is not None else
                            load_templates(selected, icon_dir, size=equipped_profile["icon_size"]))
    frame = prepared.array
    rows = []
    searches = []
    for marker in read["markers"]:
        if marker["color"] != "green":
            continue
        slots = []
        for slot in range(equipped_profile["slots_per_bar"]):
            patches, rects = equipped_patches(frame, marker, slot, equipped_profile)
            searches.append((patches, rects))
        rows.append({"marker_id": marker["id"], "position_candidate": locations.get(marker["id"]),
                     "slots": slots, "unit_id": None})
    rankings = rank_patch_groups([patches for patches, _ in searches], templates)
    search_index = 0
    for row in rows:
        slots = row["slots"]
        for slot in range(equipped_profile["slots_per_bar"]):
            candidates = rankings[search_index]
            rects = searches[search_index][1]
            search_index += 1
            for candidate in candidates:
                candidate["sample_rect"] = rects[candidate.pop("sample_index")]
            best = candidates[0]["rms"] if candidates else None
            if best is None:
                status = "unknown"
            elif best <= equipped_profile["icon_candidate_max_rms"]:
                status = "icon_candidate"
            elif best >= equipped_profile["empty_appearance_min_rms"]:
                status = "empty_appearance"
            else:
                status = "unknown"
            slots.append({"slot": slot, "status": status, "candidates": candidates,
                          "item_id": None})
    return {"schema_version": 1, "policy": "board_hub_equipped_candidates_v1",
            "status": "candidate_only", "reference_sha256": manifest["reference_sha256"],
            "data_dragon_version": manifest["version"], "tft_patch": None,
            "icon_assets_available": available, "catalog_entries": len(entries),
            "matching_entries": len(selected), "matching_scope": match_scope,
            "markers": rows, "item_identity_established": False,
            "unit_identity_established": False, "game_state_updated": False}


def main() -> None:
    from PIL import Image

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--icon-dir", type=Path, required=True)
    parser.add_argument("--match-scope", choices=("all", "set_path", "set_plus_core"), default="all")
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--frame-index", type=int, required=True, help="one-based index in B1 report")
    parser.add_argument("--board-profile", type=Path, required=True)
    parser.add_argument("--position-profile", type=Path, required=True)
    parser.add_argument("--equipped-profile", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    if not 1 <= args.frame_index <= len(report["records"]):
        parser.error("frame index outside report")
    read = report["records"][args.frame_index - 1]["read"]
    board = json.loads(args.board_profile.read_text())
    position = json.loads(args.position_profile.read_text())
    equipped = json.loads(args.equipped_profile.read_text())
    manifest, entries = load_reference(args.reference)
    with Image.open(args.image) as image:
        result = run(image, read, board, position, equipped, manifest, entries, args.icon_dir,
                     args.match_scope)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
