"""Reproducible resource walkthrough with declared outcomes, not full matches."""

import argparse
import hashlib
import json
from pathlib import Path
from dataclasses import asdict

from trainer.simulation.economy import new_planning_probe
from trainer.simulation.state import Player
from trainer.simulation.seasonal_events import (
    begin_observed_round,
    observe_offer,
    buy_wisp,
    end_planning,
    settle_observed_pvp,
    settle_observed_non_pvp,
)


def walkthrough(content, events, calendar, economy):
    world = new_planning_probe([Player(50, 7, 0, hp=30, stage=2)], content, seed=42)
    log = []
    # Empty boards and declared results intentionally prevent this resource
    # exercise from being mistaken for a battle-strength estimate.
    for key, outcome in [
        ("2-2", "win"),
        ("2-3", "loss"),
        ("2-4", None),
        ("2-5", "win"),
    ]:
        world = begin_observed_round(world, 0, key, content, events, calendar)
        if key == "2-2":
            world = observe_offer(world, 0, "golden_road", content, events)
            world, receipt = buy_wisp(world, 0, content, events)
            log.append(receipt)
        world = end_planning(world, 0, content, events)
        if outcome is None:
            p = world.players[0]
            totals = {
                k: getattr(p, k)
                for k in (
                    "gold",
                    "level",
                    "xp",
                    "hp",
                    "streak",
                    "free_rerolls",
                    "round_free_rerolls",
                )
            }
            world, receipt = settle_observed_non_pvp(
                world, 0, content, events, calendar, resources=totals
            )
        else:
            world, receipt = settle_observed_pvp(
                world,
                0,
                content,
                events,
                calendar,
                economy,
                outcome=outcome,
                enemy_champion_kills=0,
                surviving_enemy_champions=0 if outcome == "win" else 1,
                allied_survivors=0,
            )
        log.append(receipt)
    return dict(
        kind="declared_outcome_resource_walkthrough",
        receipts=log,
        final_player=asdict(world.players[0]),
        assumed_outcomes=True,
        carousel_resources_held_constant_for_example=True,
        combats_simulated=0,
        complete_matches=0,
        training_labels=0,
        runtime_promoted=False,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--content", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    paths = {
        "content": a.content,
        "events": Path("configs/simulation/seasons/TFTSet18/events/18.3B-economy.json"),
        "calendar": Path("configs/simulation/core/standard-calendar-v1.json"),
        "economy": Path("configs/simulation/core/standard-economy-v2.json"),
    }
    report = walkthrough(**{k: json.loads(v.read_text()) for k, v in paths.items()})
    report["data_sha256"] = {
        k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in paths.items()
    }
    report["code_sha256"] = {
        str(v): hashlib.sha256(v.read_bytes()).hexdigest()
        for v in sorted(Path("trainer/simulation").glob("*.py"))
    }
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "kind",
                    "combats_simulated",
                    "complete_matches",
                    "training_labels",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
