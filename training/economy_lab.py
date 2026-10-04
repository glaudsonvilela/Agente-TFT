"""Reproduce cross-system economy examples against an explicit content bundle.

These are hypothetical resource snapshots, not annotated games or policy labels.
No missing fight is turned into a claimed win probability or coaching advice.
"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ingestion.knowledge_release import canonical
from trainer.simulation.economy import new_planning_probe
from trainer.simulation.round_economy import project_pvp, validate_rules
from trainer.simulation.shop_probability import next_shop_probability
from trainer.simulation.state import Action, Player, Unit, apply
from training.event_lab import engine_identity


def compare(content, rules, champion):
    validate_rules(rules)
    reports = []
    for name, actions, overrides, contested in [
        ("hold_at_fifty", [], {}, 0),
        ("paid_roll_below_fifty", [Action("reroll")], {}, 0),
        ("level_before_next_shop", [Action("xp")], {}, 0),
        ("same_target_contested", [], {"level": 8, "xp": 0}, 6),
        ("same_level_uncontested", [], {"level": 8, "xp": 0}, 0),
        ("lethal_next_loss", [], {"hp": 8}, 0),
        (
            "round_credit_preserves_interest",
            [Action("reroll")],
            {"round_free_rerolls": 1},
            0,
        ),
    ]:
        p = Player(
            **dict(
                dict(gold=50, level=7, xp=52, hp=20, stage=4, streak=-4), **overrides
            )
        )
        opponent = Player(
            50,
            8,
            0,
            stage=4,
            units=[
                Unit(f"contested-{i}", champion, position=(i,))
                for i in range(contested)
            ],
        )
        world = new_planning_probe([p, opponent], content, seed=0)
        before = deepcopy(world.players[0])
        for action in actions:
            world = apply(world, 0, action, content)
        probability = next_shop_probability(world, 0, champion, content)
        conditional = {}
        for outcome in ("win", "loss"):
            _, receipt = project_pvp(
                world.players[0],
                content,
                rules,
                outcome=outcome,
                surviving_enemy_champions=0 if outcome == "win" else 2,
            )
            conditional[outcome] = receipt
        after = world.players[0]
        reports.append(
            dict(
                name=name,
                actions=[dict(kind=a.kind, args=a.args) for a in actions],
                resources_before={
                    k: getattr(before, k)
                    for k in (
                        "gold",
                        "level",
                        "xp",
                        "hp",
                        "streak",
                        "free_rerolls",
                        "round_free_rerolls",
                    )
                },
                resources_after={
                    k: getattr(after, k)
                    for k in (
                        "gold",
                        "level",
                        "xp",
                        "hp",
                        "streak",
                        "free_rerolls",
                        "round_free_rerolls",
                    )
                },
                contested_copies_assumed=contested,
                next_refresh_probability=probability,
                conditional_income=conditional,
            )
        )
    return dict(
        schema_version=1,
        kind="conditional_economy_examples",
        scenarios=reports,
        rules_scope="ordinary_income_and_shop_only",
        resources_are_hypothetical=True,
        board_strength_evaluated=False,
        full_matches_run=0,
        training_labels_created=0,
        runtime_promoted=False,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--content", type=Path, required=True)
    p.add_argument(
        "--rules",
        type=Path,
        default=Path("configs/simulation/core/standard-economy-v2.json"),
    )
    p.add_argument("--champion", default="DA_Nidalee18_AP")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = compare(
        json.loads(a.content.read_text()), json.loads(a.rules.read_text()), a.champion
    )
    result.update(
        content_sha256=hashlib.sha256(a.content.read_bytes()).hexdigest(),
        rules_sha256=hashlib.sha256(a.rules.read_bytes()).hexdigest(),
        engine=engine_identity(),
    )
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(canonical(result))
    print(
        json.dumps(
            [
                dict(
                    case=r["name"],
                    gold=r["resources_after"]["gold"],
                    level=r["resources_after"]["level"],
                    next_shop_target_probability=r["next_refresh_probability"][
                        "probability"
                    ],
                    next_gold_if_loss=r["conditional_income"]["loss"]["gold_after"],
                    next_hp_if_loss=r["conditional_income"]["loss"]["hp_after"],
                )
                for r in result["scenarios"]
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
