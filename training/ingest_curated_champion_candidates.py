#!/usr/bin/env python3
"""Register reviewed gameplay crops without admitting them to model training."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--shop", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
    if decisions["training_eligibility"] is not False:
        raise ValueError("This review batch must remain outside training")
    manifest_path = Path(decisions["source_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_records = {row["id"]: row for row in manifest["records"]}
    shop = json.loads(args.shop.read_text(encoding="utf-8"))
    names = {row["name_pt_br"]: row["game_id"] for row in shop["rows"]}
    roster = json.loads(args.roster.read_text(encoding="utf-8"))
    existing = {row["review_id"] for row in roster["records"]}
    decisions_by_id = {}
    for status in ("user_confirmed", "panel_confirmed", "panel_tracked", "assistant_visual_match"):
        for ident, name in decisions.get(status, {}).items():
            if ident in decisions_by_id or ident in decisions.get("confirmed_non_champion", []):
                raise ValueError(f"Conflicting decision: {ident}")
            if name not in names or ident not in source_records:
                raise ValueError(f"Unknown champion or crop: {ident} {name}")
            decisions_by_id[ident] = (status, name)
    added = 0
    for ident, (status, name) in decisions_by_id.items():
        review_id = f"{decisions['id_prefix']}-{ident}"
        if review_id in existing:
            continue
        source = source_records[ident]
        if status == "panel_confirmed" and source.get("box_source") != "same_frame_selected_unit_panel":
            raise ValueError(f"Missing same-frame panel evidence: {ident}")
        if status == "panel_tracked" and (
            source.get("box_source") != "selected_panel_same_video_item_tracking"
            or not Path(source.get("proof_frame", "")).is_file()
        ):
            raise ValueError(f"Missing selected-panel tracking evidence: {ident}")
        crop = manifest_path.parent / source["crop"]
        digest = sha256(crop.read_bytes()).hexdigest()
        if digest != source["crop_sha256"] or source["identity"] is not None or source["may_train"]:
            raise ValueError(f"Source crop changed or was previously labeled: {ident}")
        roster["records"].append({
            "review_id": review_id,
            "champion": name,
            "game_id": names[name],
            "zone": "unverified_board_or_bench",
            "natural_crop": str(crop),
            "natural_crop_sha256": digest,
            "source_video_local": source["source_video"],
            "source_second": source["second"],
            "source_resolution": source["source_resolution"],
            "review_status": f"{status}_candidate",
            "identity_confirmed_by": {
                "user_confirmed": "user_review_20261010",
                "panel_confirmed": "same_frame_selected_unit_panel",
                "panel_tracked": "selected_unit_panel_and_same_unit_item_tracking",
                "assistant_visual_match": "visual_match_to_user_confirmed_20261010",
            }[status],
            "training_eligible": False,
            "eligibility_reason": "box_quality_and_distinct_pose_review_pending",
            "manifest": str(manifest_path),
            "review_preview_crop": str(crop),
            "box_source": source["box_source"],
            "crop_quality_review_pending": True,
        })
        added += 1
    roster["reviewed_candidate_count"] = len(roster["records"])
    roster["reviewed_champion_count"] = len({row["game_id"] for row in roster["records"]})
    roster["training_eligible_count"] = sum(row["training_eligible"] for row in roster["records"])
    if not args.dry_run:
        write_json(args.roster, roster)
    print(json.dumps({"added": added, "total": len(roster["records"]),
                      "classes": roster["reviewed_champion_count"],
                      "training_eligible": roster["training_eligible_count"],
                      "dry_run": args.dry_run}, ensure_ascii=False))


if __name__ == "__main__":
    main()
