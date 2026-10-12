"""Validate user-selected expert matches before any Akash strategy training.

One match identity is one split unit. Videos alone are not action labels: each
training candidate needs separately reviewed actions and outcomes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from knowledge.strategy_knowledge import StrategyKnowledge


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _https(value):
    try:
        parsed = urlsplit(value)
    except (TypeError, ValueError):
        return False
    return parsed.scheme == "https" and bool(parsed.netloc)


def audit(selection, root):
    if (selection.get("schema_version"), selection.get("set_key"),
            selection.get("patch")) != (1, "TFTSet18", "18.4B"):
        raise ValueError("selection has wrong set, patch or schema")
    book = StrategyKnowledge.for_patch(root, set_key="TFTSet18", patch="18.4B")
    if book is None:
        raise ValueError("missing 18.4B strategy knowledge")
    readiness_path = (Path(root) / "configs" / "strategy" / "TFTSet18" /
                      "18.4B" / "readiness.json")
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    required = {"economy", "shop_odds", "pool_sizes", "combat",
                "champion_abilities", "trait_effects", "item_effects",
                "augments", "wisps", "opponent_observation",
                "replay_validation", "player_policy_validation",
                "commentary_grounding"}
    components = readiness.get("components")
    if (readiness.get("patch") != "18.4B" or not isinstance(components, dict)
            or set(components) != required or
            any(type(value) is not bool for value in components.values())):
        raise ValueError("invalid 18.4B rule readiness manifest")
    unverified = sorted(name for name, verified in components.items() if not verified)
    patch_manifest = json.loads((readiness_path.parent / "manifest.json")
                                .read_text(encoding="utf-8"))
    unresolved = patch_manifest.get("coverage", {}).get(
        "unresolved_ability_placeholders", 0)
    rule_coverage_ready = not unverified and unresolved == 0
    games = selection.get("games")
    if not isinstance(games, list):
        raise ValueError("games must be a list")
    seen = set()
    video_hashes = set()
    checked = []
    for game in games:
        match_id = game.get("match_id")
        if not isinstance(match_id, str) or not match_id or match_id in seen:
            raise ValueError("missing or duplicate match identity")
        seen.add(match_id)
        if game.get("patch") != "18.4B" or game.get("set_key") != "TFTSet18":
            raise ValueError(f"patch mismatch: {match_id}")
        if game.get("rank") != "challenger" or not _https(game.get("rank_evidence_url")):
            raise ValueError(f"challenger rank evidence required: {match_id}")
        if not _https(game.get("source_url")) or not _https(game.get("patch_evidence_url")):
            raise ValueError(f"source and patch evidence required: {match_id}")
        if game.get("usage_permission") is not True:
            raise ValueError(f"usage permission not documented: {match_id}")
        video = Path(game.get("video_path") or "")
        if not video.is_file() or _sha256(video) != game.get("video_sha256"):
            raise ValueError(f"video missing or hash mismatch: {match_id}")
        if game["video_sha256"] in video_hashes:
            raise ValueError(f"same video selected under multiple match IDs: {match_id}")
        video_hashes.add(game["video_sha256"])
        review = Path(game.get("reviewed_actions_path") or "")
        if not review.is_file() or _sha256(review) != game.get("reviewed_actions_sha256"):
            raise ValueError(f"reviewed actions missing or hash mismatch: {match_id}")
        reviewed = json.loads(review.read_text(encoding="utf-8"))
        if (reviewed.get("match_id") != match_id or
                not isinstance(reviewed.get("actions"), list) or
                not reviewed["actions"] or
                not all(row.get("before_ms") is not None and
                        row.get("action") is not None and
                        row.get("after_ms") is not None
                        for row in reviewed["actions"])):
            raise ValueError(f"action review incomplete: {match_id}")
        checked.append(dict(match_id=match_id, video_sha256=game["video_sha256"],
                            reviewed_actions_sha256=game["reviewed_actions_sha256"],
                            reviewed_actions=len(reviewed["actions"])))
    ordered = sorted(checked, key=lambda row: hashlib.sha256(
        row["match_id"].encode()).hexdigest())
    if len(ordered) >= 3:
        ordered[-2]["split"] = "validation"
        ordered[-1]["split"] = "test"
        for row in ordered[:-2]:
            row["split"] = "train"
    return dict(schema_version=1, set_key="TFTSet18", patch="18.4B",
                knowledge_sha256=book.digest, selected_matches=len(checked),
                games=ordered, data_split_ready=len(ordered) >= 3,
                rule_coverage_ready=rule_coverage_ready,
                unverified_rules=unverified,
                unresolved_ability_placeholders=unresolved,
                training_ready=len(ordered) >= 3 and rule_coverage_ready,
                split_unit="whole_match_id",
                runtime_promoted=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(json.loads(args.selection.read_text(encoding="utf-8")), args.root)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True,
                                          indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
