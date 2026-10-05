"""Additional held-out audit with full candidate sets and both seed parities.

The original modulo-10 split gives the test fold mostly non-forced pairs.
This disjoint audit exercises rolling more often without changing any weights.
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics

from hm.strategic_coach import StrategicCoach, alternatives
from training.strategy_ranker_lab import scenario


def audit(root, states=500, seed_start=2026100420000):
    coach = StrategicCoach(root)
    if coach.model is None:
        raise ValueError("evaluated checkpoint required")
    groups = defaultdict(list)
    alternatives_count = 0
    for seed in range(seed_start, seed_start + states):
        choices = alternatives(scenario(coach.catalog, seed), coach.catalog)
        alternatives_count += len(choices)
        scores = coach.model.predict([c["features"] for c in choices])
        for family in ("roll", "composition", "position", "equip"):
            ids = [i for i, c in enumerate(choices) if c["family"] in ("hold", family)]
            if len(ids) < 2:
                continue
            selected = max(ids, key=lambda i: scores[i])
            groups[family].append(
                max(choices[i]["teacher_utility"] for i in ids)
                - choices[selected]["teacher_utility"]
            )
    metrics = {
        k: dict(states=len(v), mean_regret=statistics.mean(v), max_regret=max(v))
        for k, v in groups.items()
    }
    return dict(
        scope="synthetic_attribute_objective_full_candidates",
        states=states,
        seed_start=seed_start,
        seed_end=seed_start + states - 1,
        candidates=alternatives_count,
        per_family=metrics,
        new_optimizer_steps=0,
        human_demonstrations=0,
        real_tft_improvement_proven=False,
        passed=len(metrics) == 4
        and all(
            v["states"] >= 100 and v["mean_regret"] < 0.025 for v in metrics.values()
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(Path(__file__).resolve().parents[1])
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
