"""Keep Motor 2 observations in whole-match order for sequential learning.

This does not infer actions or assign per-frame rewards from final placement.
Completion, patch and outcome must be independently reviewed in metadata.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

SUPPORTED_HUD_LANGUAGES = {"en_US", "pt_BR"}


def _player_frame(row):
    if row.get("kind") == "motor2_player_observation":
        return row
    return (row.get("answer") or {}).get("player_policy_frame")


def build_episodes(rows, manifest, *, max_gap_ms=10_000):
    if manifest.get("schema_version") != 1 or manifest.get("kind") != "reviewed_full_matches":
        raise ValueError("reviewed_full_matches schema 1 required")
    groups = defaultdict(list)
    for row in rows:
        frame = _player_frame(row)
        if frame is None:
            continue
        if frame.get("kind") != "motor2_player_observation" or \
                not isinstance(frame.get("match_id"), str) or not frame["match_id"]:
            raise ValueError("unbound player frame")
        groups[frame["match_id"]].append(frame)
    episodes = []
    matches = manifest.get("matches")
    if not isinstance(matches, list) or not matches:
        raise ValueError("full-match metadata missing")
    for meta in matches:
        match_id = meta.get("match_id")
        frames = sorted(groups.pop(match_id, []), key=lambda row: row["source_ms"])
        if len(frames) < 2 or meta.get("full_video_reviewed") is not True or \
                meta.get("patch_reviewed") is not True or \
                meta.get("outcome_reviewed") is not True:
            raise ValueError(f"incomplete episode review: {match_id}")
        if meta.get("hud_language") not in SUPPORTED_HUD_LANGUAGES or \
                meta.get("ocr_locale_validated") is not True:
            raise ValueError(f"unsupported or unvalidated HUD language: {match_id}")
        if meta.get("player_pov_verified") is not True or \
                meta.get("player_rank_at_game_verified") is not True:
            raise ValueError(f"player POV or Challenger rank unverified: {match_id}")
        if not isinstance(meta.get("source_sha256"), str) or \
                len(meta["source_sha256"]) != 64:
            raise ValueError(f"source identity missing: {match_id}")
        start, end, placement = (meta.get(key) for key in
                                 ("start_ms", "end_ms", "placement"))
        if any(type(value) is not int for value in (start, end, placement)) or \
                not 0 <= start < end or not 1 <= placement <= 8:
            raise ValueError(f"invalid match boundary/outcome: {match_id}")
        if frames[0]["source_ms"] - start > max_gap_ms or \
                end - frames[-1]["source_ms"] > max_gap_ms:
            raise ValueError(f"beginning or end not captured: {match_id}")
        frame_ids, frame_hashes = set(), set()
        previous_ms = None
        patch = meta.get("patch")
        names = frames[0].get("feature_names")
        for frame in frames:
            at = frame.get("source_ms")
            if frame.get("patch") != patch or frame.get("set_key") != meta.get("set_key") or \
                    frame.get("feature_names") != names or frame.get("epoch") != 0:
                raise ValueError(f"episode patch/schema/epoch changed: {match_id}")
            if type(at) is not int or not start <= at <= end or \
                    (previous_ms is not None and (at <= previous_ms or at - previous_ms > max_gap_ms)):
                raise ValueError(f"episode has missing or reordered time: {match_id}")
            if frame.get("frame_id") in frame_ids or \
                    frame.get("observation_sha256") in frame_hashes:
                raise ValueError(f"duplicate episode frame: {match_id}")
            frame_ids.add(frame["frame_id"])
            frame_hashes.add(frame["observation_sha256"])
            previous_ms = at
        episodes.append(dict(schema_version=1, kind="motor2_player_episode",
            match_id=match_id, source_sha256=meta["source_sha256"],
            patch=patch, set_key=meta["set_key"],
            hud_language=meta["hud_language"],
            start_ms=start, end_ms=end, placement=placement,
            outcome_evidence_id=meta.get("outcome_evidence_id"),
            frames=frames, split_unit="whole_match_id",
            action_labels_reviewed=False,
            terminal_reward_only=True, runtime_promoted=False))
    if groups:
        raise ValueError("frames from matches absent in metadata")
    return episodes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.frames.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    episodes = build_episodes(rows, manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for episode in episodes:
            handle.write(json.dumps(episode, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(json.dumps(dict(episodes=len(episodes), frames=sum(len(row["frames"])
                    for row in episodes)), ensure_ascii=False))


if __name__ == "__main__":
    main()
