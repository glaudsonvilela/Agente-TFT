"""Evaluate learned combat choices on new simulator seeds.

Measures position/equipment alternatives, not economic advice or real TFT skill.
Choices are made before evaluation outcomes. Planning uses separate random seeds.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import time

import numpy as np

from trainer.simulation.combat import simulate
from trainer.simulation.state import UnsupportedRule
from trainer.simulation.value_model import CombatValueModel
from training.event_lab import canonical, engine_identity, scenario
from training.combat_planner import outcome, select


def alternatives(teams, item):
    """Counterfactual board copies; no mouse command, spending or pool mutation."""
    choices = [(dict(type="hold"), teams)]
    player = teams[0]
    for index, unit in enumerate(player.units):
        if unit.zone != "board":
            continue
        for row in range(4):
            for column in range(7):
                position = (row, column)
                if position == unit.position:
                    continue
                pair = deepcopy(teams)
                other = next(
                    (
                        u
                        for u in pair[0].units
                        if u.zone == "board" and u.position == position
                    ),
                    None,
                )
                if other is not None:
                    other.position = unit.position
                pair[0].units[index].position = position
                choices.append(
                    (dict(type="position", unit_id=unit.uid, position=position), pair)
                )
        if len(unit.items) < 3 and item not in unit.items:
            pair = deepcopy(teams)
            pair[0].units[index].items.append(item)
            choices.append(
                (
                    dict(
                        type="equip",
                        unit_id=unit.uid,
                        item_id=item,
                        inventory_assumption="one_available_completed_item",
                    ),
                    pair,
                )
            )
    return choices


def evaluate(
    content_path, model_path, output, cases=50, *, planning=False, seed_offset=0
):
    content_path, model_path, output = map(Path, (content_path, model_path, output))
    content = json.loads(content_path.read_text())
    model = CombatValueModel(
        model_path,
        content_sha256=hashlib.sha256(content_path.read_bytes()).hexdigest(),
        engine_sha256=engine_identity()["sha256"],
    )
    champions, items = model.encoder.champions, model.encoder.items
    rows, rejected = [], []
    started = time.monotonic()
    for attempt in range(cases * 10):
        if len(rows) == cases:
            break
        seed = 2**31 + seed_offset + attempt
        teams = scenario(content, seed, champions, items)
        item = random.Random(seed).choice(items)
        choices = alternatives(teams, item)
        tick = time.perf_counter()
        prediction = model.predict([pair for _, pair in choices])
        utilities = prediction[:, 2] - prediction[:, 0]
        selected = int(np.argmax(utilities))
        if utilities[selected] - utilities[0] < 0.03:
            selected = 0
        model_only_selected = selected
        inference_ms = (time.perf_counter() - tick) * 1000
        plan = None
        if planning:
            try:
                plan = select(
                    choices, model, content, seed=seed ^ (2**50), seconds=0.75
                )
            except UnsupportedRule as exc:
                rejected.append(dict(seed=seed, reason=str(exc)))
                continue
            selected = plan["selected"]
        # These evaluation outcomes never enter either selection path.
        try:
            outcomes = [
                outcome(simulate(pair, content, seed=seed)) for _, pair in choices
            ]
        except UnsupportedRule as exc:
            rejected.append(dict(seed=seed, reason=str(exc)))
            continue
        random_index = random.Random(seed ^ 65535).randrange(len(choices))
        rows.append(
            dict(
                seed=seed,
                alternatives=len(choices),
                action=choices[selected][0],
                neural_utility=float(utilities[selected]),
                neural_outcome=outcomes[selected],
                model_only_outcome=outcomes[model_only_selected],
                hold_outcome=outcomes[0],
                random_outcome=outcomes[random_index],
                oracle_outcome=max(outcomes),
                inference_ms=inference_ms,
                plan=plan,
            )
        )
    if not rows:
        raise ValueError("No supported evaluation scenarios")
    report = dict(
        schema_version=1,
        kind="neural_combat_choice_evaluation",
        scope="supported_simulator_subset",
        independent_seed_domain="2**31 + seed_offset + attempt",
        model_sha256=model.schema["checkpoint_sha256"],
        seed_offset=seed_offset,
        counterfactual_planning=planning,
        selection_method=(
            "neural_shortlist_and_simulation" if planning else "neural_value_only"
        ),
        cases=len(rows),
        requested_cases=cases,
        rejected_scenarios=rejected,
        rows=rows,
        neural_mean_outcome=float(np.mean([r["neural_outcome"] for r in rows])),
        model_only_mean_outcome=float(np.mean([r["model_only_outcome"] for r in rows])),
        hold_mean_outcome=float(np.mean([r["hold_outcome"] for r in rows])),
        random_mean_outcome=float(np.mean([r["random_outcome"] for r in rows])),
        oracle_mean_outcome=float(np.mean([r["oracle_outcome"] for r in rows])),
        inference_ms_p95=float(np.percentile([r["inference_ms"] for r in rows], 95)),
        decision_ms_p95=float(
            np.percentile(
                [
                    r["plan"]["elapsed_ms"] if r["plan"] else r["inference_ms"]
                    for r in rows
                ],
                95,
            )
        ),
        elapsed_seconds=time.monotonic() - started,
        runtime_promoted=False,
        real_tft_improvement_proven=False,
        limitations=[
            "Partial seasonal simulator; coverage rejections retained",
            "One fight, no future economy, opponent scouting or component opportunity cost",
            "Model-estimated outcome is not a calibrated real-match win probability",
        ],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as file:
        file.write(canonical(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", type=int, default=50)
    parser.add_argument("--planning", action="store_true")
    parser.add_argument("--seed-offset", type=int, default=0)
    args = parser.parse_args()
    if not 1 <= args.cases <= 200:
        parser.error("Use 1..200 independent scenarios")
    if not 0 <= args.seed_offset <= 2**30:
        parser.error("Seed offset out of range")
    result = evaluate(
        args.content,
        args.model,
        args.output,
        args.cases,
        planning=args.planning,
        seed_offset=args.seed_offset,
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in ("rows", "rejected_scenarios")
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
