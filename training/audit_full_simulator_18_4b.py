"""Fail-closed inventory of rules required for TFT Set 18 patch 18.4B simulation.

Catalog text and patch notes are evidence of content, not executable rules.
This audit does not claim completeness: it lists every known unresolved binding and
also blocks on missing full-match validation, including rules absent from catalogs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "configs/strategy/TFTSet18/18.4B"
SIMULATOR = ROOT / "configs/simulation/seasons/TFTSet18/18.4B/manifest.json"
REQUIRED_COMPONENTS = (
    "economy", "shop_odds", "pool_sizes", "combat", "champion_abilities",
    "trait_effects", "item_effects", "augments", "wisps",
    "opponent_observation", "replay_validation", "player_policy_validation",
    "commentary_grounding",
)
PATCH_LINEAGE = ("18.1", "18.2", "18.3", "18.4", "18.4B")
REQUIRED_MATCH_SYSTEMS = (
    "round_calendar", "planning_and_combat_timing", "shop_generation",
    "shared_pool_and_depletion", "economy_interest_streaks", "xp_and_leveling",
    "unit_purchase_sale_merge", "bench_board_item_capacity", "item_recipes_and_effects",
    "trait_activation_and_effects", "champion_abilities_and_targeting",
    "combat_damage_healing_status", "augment_offers_eligibility_and_effects",
    "wisp_offers_eligibility_and_effects", "pve_and_loot",
    "carousel_or_shared_draft", "opponent_pairing_and_ghosts",
    "player_damage_elimination_placement", "scouting_observation_limits",
    "lobby_limited_and_disabled_content", "random_seed_replay",
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(*, patch_dir: Path = PATCH, simulator_manifest: Path = SIMULATOR) -> dict:
    knowledge_path = patch_dir / "knowledge.json"
    manifest_path = patch_dir / "manifest.json"
    readiness_path = patch_dir / "readiness.json"
    knowledge = json.loads(knowledge_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    readiness = json.loads(readiness_path.read_text())
    blockers: list[dict] = []

    def block(kind: str, identity: str, reason: str) -> None:
        blockers.append({"kind": kind, "id": identity, "reason": reason})

    if any(doc.get("patch") != "18.4B" for doc in (knowledge, manifest, readiness)):
        block("patch", "18.4B", "catalog, manifest and readiness must all identify 18.4B")
    if knowledge.get("set_key") != "TFTSet18" or manifest.get("set_key") != "TFTSet18":
        block("set", "TFTSet18", "catalog and manifest must identify TFTSet18")
    if manifest.get("knowledge_sha256") != _digest(knowledge_path):
        block("integrity", "knowledge.json", "catalog digest differs from manifest")
    if tuple(manifest.get("validated_patch_lineage", ())) != PATCH_LINEAGE:
        block("lineage", "18.1→18.4B", "set launch and all intervening patches not reconciled")
    if not simulator_manifest.is_file():
        block("executor", "18.4B", "patch-specific full-match simulator manifest missing")
        validated_systems = {}
    else:
        sim = json.loads(simulator_manifest.read_text())
        validated_systems = sim.get("validated_systems", {})
        if sim.get("patch") != "18.4B" or sim.get("full_match_ready") is not True:
            block("executor", "18.4B", "patch-specific full-match executor unverified")
    for system in REQUIRED_MATCH_SYSTEMS:
        if validated_systems.get(system) is not True:
            block("match_system", system, "no patch-matched end-to-end validation")

    for component in REQUIRED_COMPONENTS:
        if readiness.get("components", {}).get(component) is not True:
            block("readiness", component, "patch-matched validation has not passed")

    economy = knowledge.get("economy", {})
    if economy.get("source_patch") != "18.4B" or economy.get("status") != "verified_for_18.4B":
        block("economy", "economy", "shop, pool and income parameters not verified for 18.4B")
    if knowledge.get("runtime_combat_rules_verified") is not True:
        block("combat", "runtime", "combat rules not verified against patch-matched replay")

    for group in ("champions", "traits", "effects"):
        catalog = knowledge.get(group, {})
        if not catalog:
            block("catalog", group, "catalog missing or empty")
        for identity, entry in sorted(catalog.items()):
            if entry.get("mechanic_status") != "executable_replay_validated_18.4B":
                block(group, identity, "mechanic is not executable and replay validated for 18.4B")
            if group == "champions":
                if entry.get("stats_status") != "verified_for_18.4B":
                    block("champion_stats", identity, "stats not reconciled with official 18.4B changes")
                if "@" in entry.get("ability", {}).get("description", ""):
                    block("ability_text", identity, "ability has unresolved numeric/text placeholders")

    for group in ("official_base_patch_changes", "official_mid_patch_changes"):
        for index, change in enumerate(knowledge.get(group, [])):
            if change.get("binding_status") != "executable_replay_validated_18.4B":
                identity = f"{index:03d}:{change.get('subject', 'unknown')}"
                block(group, identity, "official patch fact not bound to validated executable rule")

    # Even a zero-blocker catalog cannot prove that it enumerates every client
    # mechanic. A full-match replay suite and observed event inventory must pass.
    if readiness.get("components", {}).get("replay_validation") is not True:
        block("completeness", "full_match_replay_suite", "unknown or unlisted mechanics remain possible")

    counts: dict[str, int] = {}
    for item in blockers:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    return {
        "schema_version": 1,
        "set_key": "TFTSet18",
        "patch": "18.4B",
        "status": "ready" if not blockers else "blocked",
        "training_allowed": not blockers,
        "synthetic_rollouts_allowed_for_player_policy": not blockers,
        "catalog_sha256": _digest(knowledge_path),
        "official_patch_notes_url": knowledge.get("source", {}).get("official_patch_notes_url"),
        "known_catalog_entries": {
            group: len(knowledge.get(group, {})) for group in ("champions", "traits", "effects")
        },
        "known_official_patch_changes": {
            group: len(knowledge.get(group, []))
            for group in ("official_base_patch_changes", "official_mid_patch_changes")
        },
        "required_match_systems": list(REQUIRED_MATCH_SYSTEMS),
        "blocker_counts": counts,
        "blockers": blockers,
        "scope_warning": "Patch notes are change logs, not a complete executable game rulebook.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(args.output.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    temp.replace(args.output)
    print(json.dumps({k: report[k] for k in ("status", "training_allowed", "known_catalog_entries", "known_official_patch_changes", "blocker_counts")}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["training_allowed"] else 2)


if __name__ == "__main__":
    main()
