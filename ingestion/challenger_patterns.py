"""Aggregate observed final boards from Riot TFT matches of named high-rank players.

The caller supplies the Challenger PUUID list and match-v1 responses. A public
leaderboard can help discover players, but it is not match telemetry. No round
history, positioning, shop decisions or simulated outcomes are inferred here.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from ingestion.knowledge_release import read_release


def analyze(matches: list[dict], champions: dict[str, dict],
            challenger_puuids: set[str], client_version_prefix: str) -> dict:
    if not challenger_puuids or not client_version_prefix:
        raise ValueError("explicit player cohort and client version required")
    seen = set()
    total = winner_count = 0
    appearances = Counter()
    wins = Counter()
    pair_appearances = Counter()
    pair_wins = Counter()
    skipped = Counter()
    for match in matches:
        metadata, info = match.get("metadata") or {}, match.get("info") or {}
        match_id = metadata.get("match_id")
        if not isinstance(match_id, str) or match_id in seen:
            skipped["missing_or_duplicate_match_id"] += 1
            continue
        seen.add(match_id)
        if not str(info.get("game_version") or "").startswith(client_version_prefix):
            skipped["different_client_version"] += 1
            continue
        for player in info.get("participants") or []:
            if player.get("puuid") not in challenger_puuids:
                continue
            placement = player.get("placement")
            if type(placement) is not int or not 1 <= placement <= 8:
                skipped["invalid_placement"] += 1
                continue
            ids = sorted({unit.get("character_id") for unit in player.get("units") or []
                          if isinstance(unit, dict) and unit.get("character_id") in champions})
            if not ids:
                skipped["no_catalog_units"] += 1
                continue
            total += 1
            won = placement == 1
            winner_count += won
            appearances.update(ids)
            if won:
                wins.update(ids)
            pairs = [(ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))]
            pair_appearances.update(pairs)
            if won:
                pair_wins.update(pairs)
    def rows(counts: Counter, victories: Counter, min_samples: int) -> list[dict]:
        result = []
        for key, count in counts.items():
            if count < min_samples:
                continue
            result.append({"champions": list(key) if isinstance(key, tuple) else [key],
                           "appearances": count, "wins": victories[key],
                           "observed_win_rate": round(victories[key] / count, 4)})
        return sorted(result, key=lambda row: (-row["appearances"], row["champions"]))
    return {"schema_version": 1, "source": "riot_tft_match_v1_observed_final_board",
            "client_version_prefix": client_version_prefix, "cohort_size": len(challenger_puuids),
            "participant_matches": total, "winner_matches": winner_count,
            "champions": rows(appearances, wins, 1),
            "pairs": rows(pair_appearances, pair_wins, 2),
            "skipped": dict(skipped), "round_decisions_available": False,
            "board_positions_available": False, "simulated_games": 0}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--matches", type=Path, required=True, help="Directory of Riot match-v1 JSON files")
    p.add_argument("--challenger-puuids", type=Path, required=True, help="Local JSON list, never published")
    p.add_argument("--release", type=Path, required=True)
    p.add_argument("--client-version-prefix", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    manifest, catalogs = read_release(args.release)
    ids = {unit["api_name"]: unit for unit in catalogs["units"]["champions"]}
    players = set(json.loads(args.challenger_puuids.read_text(encoding="utf-8")))
    matches = [json.loads(path.read_text(encoding="utf-8"))
               for path in sorted(args.matches.glob("*.json"))]
    result = analyze(matches, ids, players, args.client_version_prefix)
    result["knowledge_release"] = manifest["release_sha256"]
    result["tft_patch"] = manifest["tft_patch"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"participant_matches": result["participant_matches"],
                      "winner_matches": result["winner_matches"],
                      "simulated_games": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
