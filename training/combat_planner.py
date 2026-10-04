"""Neural proposal ranking followed by bounded counterfactual combat search.

Candidate fights are explicit inputs; this does not infer hidden opponents or
turn a fight evaluator into an economic policy. All completed rounds compare
the same random seeds for each alternative and for holding the current board.
"""

from __future__ import annotations

import time

import numpy as np

from trainer.simulation.combat import simulate


def outcome(result):
    return 0.0 if result["winner"] is None else 1.0 if result["winner"] == 0 else -1.0


def select(choices, model, content, *, seed, max_candidates=16, rounds=4, seconds=0.75):
    if not choices or choices[0][0]["type"] != "hold":
        raise ValueError("The first candidate must preserve the observed board")
    if not 2 <= max_candidates <= 64 or not 1 <= rounds <= 16 or not 0 < seconds <= 10:
        raise ValueError("Invalid combat planning budget")
    started = time.perf_counter()
    predictions = model.predict([pair for _, pair in choices])
    utility = predictions[:, 2] - predictions[:, 0]
    ranked = list(np.argsort(-utility, kind="stable"))
    # Keep hold and equipment choices in the comparison even when a value
    # model ranks many nearly equivalent positions above all of them.
    shortlist = [0]
    for index in [
        i for i, (action, _) in enumerate(choices) if action["type"] == "equip"
    ] + ranked:
        if index not in shortlist:
            shortlist.append(int(index))
        if len(shortlist) >= max_candidates:
            break
    totals = np.zeros(len(shortlist), dtype=np.float64)
    completed_rounds = calls = 0
    rng = np.random.default_rng(seed)
    for _ in range(rounds):
        if time.perf_counter() - started >= seconds:
            break
        combat_seed = int(rng.integers(0, 2**63))
        values = []
        for index in shortlist:
            if time.perf_counter() - started >= seconds:
                break
            values.append(
                outcome(simulate(choices[index][1], content, seed=combat_seed))
            )
            calls += 1
        if len(values) != len(shortlist):
            break  # Never compare alternatives given different seed counts.
        totals += values
        completed_rounds += 1
    selected = 0
    if completed_rounds:
        means = totals / completed_rounds
        best = max(
            range(len(shortlist)),
            key=lambda i: (means[i], float(utility[shortlist[i]])),
        )
        if means[best] > means[0]:
            selected = shortlist[best]
    return dict(
        selected=selected,
        action=choices[selected][0],
        completed_rounds=completed_rounds,
        simulated_combats=calls,
        shortlist=shortlist,
        elapsed_ms=(time.perf_counter() - started) * 1000,
        reason=(
            "counterfactual_improvement"
            if selected
            else (
                "no_completed_comparison"
                if not completed_rounds
                else "no_counterfactual_gain"
            )
        ),
        scope="supported_combat_only",
        runtime_promoted=False,
    )
