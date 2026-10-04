"""Probe compiled dependencies without running search, training or full matches.

Diagnostic cores are lower bounds on a composition's requirements. Successful
initialization is not proof of complete items, timing, economy or replay parity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ingestion.knowledge_release import read_release
from ingestion.simulation_bindings import load_bindings
from trainer.simulation.event_combat import Battle
from trainer.simulation.state import Player, Unit, UnsupportedRule
from training.compile_effects import compile_catalog


def audit(memory, probes, content):
    strategies = {row["id"]: row for row in memory["strategies"]}
    if set(probes["cores"]) != set(strategies):
        raise ValueError("Every strategy requires exactly one diagnostic core")
    findings = []
    for key, core in probes["cores"].items():
        if (
            not core
            or len(core) > 7
            or any(c not in content["champions"] for c in core)
        ):
            raise ValueError(f"Invalid diagnostic core: {key}")
        teams = [
            Player(
                0,
                len(core),
                0,
                units=[
                    Unit(f"{team}:{i}", champion, zone="board", position=(0, i))
                    for i, champion in enumerate(core)
                ],
            )
            for team in (0, 1)
        ]
        reason = None
        try:
            Battle(teams, content)
        except UnsupportedRule as error:
            reason = str(error)
        traits = sorted(
            {trait for c in core for trait in content["champions"][c].get("traits", [])}
        )
        findings.append(
            dict(
                strategy_id=key,
                diagnostic_core=core,
                unsupported_units=[
                    c for c in core if content["champions"][c].get("unsupported")
                ],
                missing_required_forms=probes.get("missing_required_forms", {}).get(
                    key, []
                ),
                potentially_required_traits=traits,
                combat_initialization="rejected" if reason else "accepted_unvalidated",
                first_rejection=reason,
                seasonal_dependencies=strategies[key]["mechanic_dependencies"],
                full_strategy_validated=False,
            )
        )
    coverage = content["coverage"]
    return dict(
        schema_version=1,
        kind="compiled_strategy_dependency_audit",
        knowledge_patch=memory["patch"],
        executable_patch=content["patch"],
        exact_patch_match=memory["patch"] == content["patch"],
        release_sha256=content["release_sha256"],
        bindings_sha256=content["bindings_sha256"],
        absent_content_sections=[
            k
            for k in ("economy", "match_rules", "wisps", "persistent_rules")
            if not content.get(k)
        ],
        implemented_augment_count=len(content.get("augments", {})),
        combat_coverage={
            k: coverage[k] for k in ("abilities", "champions", "traits", "items")
        },
        findings=findings,
        accepted_core_initializations=sum(
            r["combat_initialization"] == "accepted_unvalidated" for r in findings
        ),
        full_strategy_validation_passes=0,
        complete_matches_run=0,
        training_run=False,
        runtime_promoted=False,
        limit="Tests core construction only. No traits are stripped, no AD form is replaced with AP, and no omitted items are claimed validated.",
    )


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    memory_path = (
        root / "configs/training/strategy-memory/TFTSet18/18.3B-20260928/memory.json"
    )
    probe_path = root / "docs/evidence/dependencies-20261004/core-probes.json"
    active = json.loads(
        (root / "configs/catalog/active-knowledge-release-v1.json").read_text()
    )
    manifest, catalogs = read_release(root / active["reference"])
    bindings = load_bindings(
        root / "configs/simulation/seasons/TFTSet18/18.3/manifest.json"
    )
    content = compile_catalog(manifest, catalogs, bindings)
    result = audit(
        json.loads(memory_path.read_text()), json.loads(probe_path.read_text()), content
    )
    result["inputs_sha256"] = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (memory_path, probe_path)
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "exact_patch_match",
                    "absent_content_sections",
                    "accepted_core_initializations",
                    "full_strategy_validation_passes",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
