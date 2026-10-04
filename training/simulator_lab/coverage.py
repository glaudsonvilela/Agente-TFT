"""Audit seasonal data independently of screen layout and executable game rules."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from ingestion.knowledge_release import read_release
from ingestion.simulation_bindings import load_bindings
from training.compile_effects import compile_catalog

REQUIRED_STATS = (
    "hp",
    "damage",
    "attackSpeed",
    "armor",
    "magicResist",
    "range",
    "mana",
    "initialMana",
    "critChance",
    "critMultiplier",
)


def audit(project: Path) -> dict:
    from .attribute_worklist import variables_audit

    selection = json.loads(
        (project / "configs/catalog/active-knowledge-release-v1.json").read_text()
    )
    manifest, catalogs = read_release(project / selection["reference"])
    rules_path = (
        project
        / "configs/simulation/seasons"
        / selection["set_key"]
        / selection["tft_patch"]
        / "manifest.json"
    )
    bindings = load_bindings(rules_path)
    compiled = compile_catalog(manifest, catalogs, bindings)
    coverage = compiled["coverage"]
    units = []
    for champion in catalogs["units"]["champions"]:
        stats = champion.get("stats") or {}
        missing = [
            key
            for key in REQUIRED_STATS
            if not isinstance(stats.get(key), (float, int))
            or isinstance(stats.get(key), bool)
            or not math.isfinite(stats[key])
        ]
        ability = champion.get("ability") or {}
        units.append(
            dict(
                id=champion["api_name"],
                missing_stats=missing,
                numeric_ability_variables=bool(variables_audit(ability)[0]),
                unresolved_description="@"
                in str(ability.get("desc", ability.get("description", ""))),
                executable_ability=not compiled["champions"][champion["api_name"]].get(
                    "unsupported", False
                ),
            )
        )
    # Coverage means an implemented and tested semantic handler, not merely text/IDs.
    # There is deliberately no user-editable 'ready: true' switch here.
    return dict(
        schema_version=1,
        kind="simulation_coverage",
        set_key=selection["set_key"],
        patch=selection["tft_patch"],
        release_sha256=manifest["release_sha256"],
        units=units,
        champions=len(units),
        champions_with_complete_stats=sum(not u["missing_stats"] for u in units),
        champions_with_numeric_ability_variables=sum(
            u["numeric_ability_variables"] for u in units
        ),
        executable_abilities=sum(u["executable_ability"] for u in units),
        ability_programs=coverage["abilities"]["candidate_programs"],
        role_integration_pending=len(coverage["abilities"]["role_integration_pending"]),
        blocked_abilities=len(coverage["abilities"]["blocked"]),
        candidate_item_effects=coverage["items"]["candidate_effects"],
        candidate_components=sum(
            item.get("combat_handler") == "effects" and item.get("component", False)
            for item in compiled["items"].values()
        ),
        candidate_noncomponent_items=sum(
            item.get("combat_handler") == "effects" and not item.get("component", False)
            for item in compiled["items"].values()
        ),
        compiled_recipes=len(compiled["recipes"]),
        candidate_trait_effects=coverage["traits"]["candidate_effects"],
        replay_validated_abilities=coverage["abilities"]["replay_validated"],
        compiled_content_coverage=coverage,
        seasonal_match_data=dict(
            economy_present=bool(compiled.get("economy")),
            round_schedule_present=bool(compiled.get("match_rules")),
            augment_definitions=len(compiled.get("augments", {})),
            wisp_definitions=len(compiled.get("wisps", {})),
            loot_definitions=len(compiled.get("loot", {})),
            encounter_definitions=len(compiled.get("encounters", {})),
            full_match_ready=coverage["full_match_ready"],
        ),
        calibration=dict(
            configured_mana_roles=sorted(bindings["profile"]["roles"]),
            combat_timing_status=bindings["profile"]["timing_profile"]["status"],
            unresolved=bindings["unresolved"],
            alternate_forms=bindings.get("ability_scope", {}).get(
                "alternate_forms_outside_catalog", []
            ),
            four_star_coverage_complete=bindings.get("ability_scope", {}).get(
                "four_star_coverage_complete", False
            ),
        ),
        current_patch_training_ready=coverage["current_patch_training_ready"],
        runtime_promoted=False,
        blockers=[
            f"{len(coverage['champions']['missing_handlers'])} champions cannot enter full combat",
            f"{len(coverage['traits']['missing_handlers'])} traits have missing effect tiers",
            "Seasonal economy, loot, augments and seasonal mechanic not validated",
            "Owned units, stars, equipped items and hex positions lack replay ground truth",
            "No independent match validation for combat or policy",
        ],
        laboratory=dict(
            adapter="tft_goat_synthetic_tick_v1",
            set_key="synthetic",
            official_rules=False,
            replay_compatible=False,
            explicit_position_actions=False,
            item_choice_actions=False,
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.project)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "units"}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
