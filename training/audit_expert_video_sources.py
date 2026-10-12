"""Check candidate VOD provenance before any player-policy episode is built."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


TARGET_PATCH = "18.4B"
SOURCE_KINDS = {"single_match_candidate", "edited_single_match", "multi_match_vod"}
SOURCE_PLATFORMS = {"youtube", "twitch"}
SUPPORTED_HUD_LANGUAGES = {"en_US", "pt_BR"}
REVIEW_FLAGS = (
    "client_patch_verified", "complete_match_boundaries_reviewed",
    "player_pov_verified", "player_rank_at_game_verified",
    "action_sequence_reviewed", "outcome_reviewed",
    "hud_language_verified", "ocr_locale_validated",
)


def audit(document: dict) -> dict:
    if document.get("schema_version") != 1 or document.get("kind") != "expert_video_source_candidates":
        raise ValueError("expert video source manifest schema 1 required")
    if document.get("target_set") != "TFTSet18" or document.get("target_patch") != TARGET_PATCH:
        raise ValueError("target set or patch mismatch")
    videos = document.get("videos")
    if not isinstance(videos, list) or not videos:
        raise ValueError("candidate videos missing")
    seen = set()
    rows = []
    for entry in videos:
        identity = entry.get("id")
        platform = entry.get("platform", "youtube")
        if platform not in SOURCE_PLATFORMS:
            raise ValueError("unsupported video platform")
        if not isinstance(identity, str) or not (
                len(identity) == 11 if platform == "youtube" else
                re.fullmatch(r"[0-9]{8,15}", identity)):
            raise ValueError("invalid video ID")
        source_key = (platform, identity)
        if source_key in seen:
            raise ValueError("duplicate video ID")
        seen.add(source_key)
        if entry.get("source_kind") not in SOURCE_KINDS:
            raise ValueError("unknown video source kind")
        if type(entry.get("duration_seconds")) is not int or entry["duration_seconds"] < 60:
            raise ValueError("invalid video duration")
        if not isinstance(entry.get("patch_evidence"), str) or not entry["patch_evidence"]:
            raise ValueError("patch candidate needs provenance")
        missing = [key for key in REVIEW_FLAGS if entry.get(key) is not True]
        if entry.get("hud_language") not in SUPPORTED_HUD_LANGUAGES:
            missing.append("supported_hud_language")
        if entry["source_kind"] == "multi_match_vod" and not entry.get("reviewed_match_segments"):
            missing.append("reviewed_match_segments")
        if entry["source_kind"] == "edited_single_match" and entry.get("known_limitation"):
            missing.append("unedited_start_and_end")
        if not isinstance(entry.get("local_source_sha256"), str) or len(entry["local_source_sha256"]) != 64:
            missing.append("local_source_sha256")
        rows.append({
            "id": identity,
            "platform": platform,
            "url": ("https://www.youtube.com/watch?v=" if platform == "youtube"
                    else "https://www.twitch.tv/videos/") + identity,
            "channel": entry.get("channel"),
            "region_candidate": entry.get("region_candidate"),
            "source_kind": entry["source_kind"],
            "patch_evidence": entry["patch_evidence"],
            "hud_language": entry.get("hud_language"),
            "training_ready": not missing,
            "missing_review": missing,
        })
    return {
        "schema_version": 1,
        "kind": "expert_video_source_audit",
        "target_patch": TARGET_PATCH,
        "candidate_videos": len(rows),
        "candidate_duration_seconds": sum(entry["duration_seconds"] for entry in videos),
        "twitch_archive_duration_seconds": sum(
            entry["duration_seconds"] for entry in videos
            if entry.get("platform", "youtube") == "twitch"),
        "reviewed_training_sources": sum(row["training_ready"] for row in rows),
        "videos": rows,
        "training_started": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(json.loads(args.manifest.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("candidate_videos", "reviewed_training_sources", "training_started")}))


if __name__ == "__main__":
    main()
