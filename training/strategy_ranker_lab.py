"""Reproducible synthetic distillation, explicitly NOT human SFT or self-play.

The target is the observable attribute/economy objective in strategic_coach.
Episode seeds are split before candidate creation. Held-out evaluation measures
agreement/regret against that objective, not improvement in real TFT matches.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import random
import resource
import time

import numpy as np
import torch

from hm.strategic_coach import (
    FEATURES,
    SCOPE,
    StrategicCoach,
    alternatives,
    state_error,
)
from hm.strategy_ranker import StrategyRanker
from training.decision_objectives import ActionPolicy


def scenario(catalog, seed):
    rng = random.Random(seed)
    champions = [
        k for k, v in catalog["champions"].items() if not v.get("purchase_blocker")
    ]
    level = rng.randint(4, 9)
    size = rng.randint(max(2, level - 2), level)
    positions = rng.sample([(r, c) for r in range(4) for c in range(7)], size)
    complete = [k for k, v in catalog["items"].items() if not v["component"]]
    units = []
    for i in range(size + rng.randint(1, 4)):
        units.append(
            dict(
                uid=f"u{i}",
                unit_id=rng.choice(champions),
                stars=rng.choice([1, 1, 2, 3]),
                items=rng.sample(complete, rng.randint(0, 2)),
                identity_verified=True,
                zone="board" if i < size else "bench",
                position=list(positions[i]) if i < size else i - size,
            )
        )
    if seed % 2 == 0:
        units[-1].update(unit_id=units[0]["unit_id"], stars=1)
        units[0]["stars"] = 1
    # Respect actual own-copy limits before constructing synthetic observations.
    counts = Counter()
    for unit in units:
        identity = catalog["champions"][unit["unit_id"]]["pool_identity"]
        cost = catalog["champions"][unit["unit_id"]]["cost"]
        pool = catalog["economy"]["pool_by_cost"].get(str(cost), 30)
        while unit["stars"] > 1 and counts[identity] + 3 ** (unit["stars"] - 1) > pool:
            unit["stars"] -= 1
        if counts[identity] >= pool:
            unit["unit_id"] = next(
                k
                for k in champions
                if counts[catalog["champions"][k]["pool_identity"]] == 0
            )
            identity = catalog["champions"][unit["unit_id"]]["pool_identity"]
            unit["stars"] = 1
        counts[identity] += 3 ** (unit["stars"] - 1)
    result = dict(
        verified=True,
        complete=True,
        perspective="self",
        phase="planning",
        evidence_id=f"synthetic:{seed}",
        patch=catalog["patch"],
        set_key=catalog["set_key"],
        age_ms=0,
        gold=rng.randint(8, 90),
        hp=rng.randint(10, 100),
        level=level,
        units=units,
        inventory=rng.choices(list(catalog["items"]), k=rng.randint(0, 5)),
    )
    assert state_error(result, catalog) is None
    return result


def compact_candidates(choices, seed):
    rng = random.Random(seed)
    selected = [choices[0]]
    for family in ("roll", "composition", "position", "equip"):
        group = [c for c in choices if c["family"] == family]
        if len(group) > 12:
            best = max(group, key=lambda c: c["teacher_utility"])
            group = [best] + rng.sample([c for c in group if c is not best], 11)
        selected += group
    return selected


def evaluate(model, episodes):
    regrets, agreements, gains, random_gains = [], [], [], []
    families = Counter()
    family_regrets = {k: [] for k in ("roll", "composition", "position", "equip")}
    with torch.no_grad():
        for episode in episodes:
            candidates = episode["candidates"]
            x = torch.tensor([[c["features"] for c in candidates]], dtype=torch.float32)
            scores = model(x)[0].numpy()
            target = np.asarray([c["teacher_utility"] for c in candidates])
            selected = int(np.argmax(scores))
            regrets.append(float(target.max() - target[selected]))
            agreements.append(float(target.max() - target[selected]) < 0.01)
            gains.append(float(target[selected]))
            random_gains.append(float(target.mean()))
            families[candidates[selected]["family"]] += 1
            for family, values in family_regrets.items():
                ids = [
                    i
                    for i, c in enumerate(candidates)
                    if c["family"] in ("hold", family)
                ]
                if len(ids) > 1:
                    best = max(ids, key=lambda i: scores[i])
                    values.append(float(max(target[i] for i in ids) - target[best]))
    return dict(
        states=len(episodes),
        mean_regret=float(np.mean(regrets)),
        p95_regret=float(np.percentile(regrets, 95)),
        agreement_within_001=float(np.mean(agreements)),
        mean_objective=float(np.mean(gains)),
        hold_baseline=0,
        uniform_random_mean_objective=float(np.mean(random_gains)),
        selected_families=dict(families),
        per_family={
            k: dict(states=len(v), mean_regret=float(np.mean(v)) if v else None)
            for k, v in family_regrets.items()
        },
    )


def run(root, output, states=10000, epochs=40, seed=20261004, dataset=None):
    if not 100 <= states <= 20000 or not 1 <= epochs <= 200:
        raise ValueError("bounded lab accepts 100..20000 states and 1..200 epochs")
    start = time.perf_counter()
    torch.set_num_threads(2)
    torch.manual_seed(seed)
    np.random.seed(seed)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    coach = StrategicCoach(root)
    engine_files = [
        "apps/hud_mapper/hm/strategic_coach.py",
        "training/strategy_ranker_lab.py",
    ]
    engine = {
        f: hashlib.sha256((Path(root) / f).read_bytes()).hexdigest()
        for f in engine_files
    }

    def progress(**fields):
        (output / "progress.json").write_text(
            json.dumps(
                dict(
                    kind="strategy_distillation",
                    scope=SCOPE,
                    elapsed_seconds=time.perf_counter() - start,
                    runtime_promoted=False,
                    **fields,
                ),
                indent=2,
            )
        )

    episodes = []
    if dataset:
        with gzip.open(dataset, "rt") as f:
            episodes = [json.loads(line) for line in f]
        if len(episodes) != states or any(
            e["catalog_sha256"] != coach.catalog_sha256 or e.get("engine") != engine
            for e in episodes
        ):
            raise ValueError("dataset identity mismatch")
    else:
        for i in range(states):
            sample_seed = seed * 100000 + i
            state = scenario(coach.catalog, sample_seed)
            candidates = compact_candidates(
                alternatives(state, coach.catalog), sample_seed
            )
            split = "train" if i % 10 < 8 else "validation" if i % 10 == 8 else "test"
            episodes.append(
                dict(
                    seed=sample_seed,
                    split=split,
                    catalog_sha256=coach.catalog_sha256,
                    engine=engine,
                    provenance="synthetic_attribute_teacher",
                    state=state,
                    candidates=candidates,
                )
            )
            if (i + 1) % 100 == 0:
                progress(
                    status="generating", completed_states=i + 1, requested_states=states
                )
    with gzip.open(output / "dataset.jsonl.gz", "wt", encoding="utf8") as f:
        for e in episodes:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    train = [e for e in episodes if e["split"] == "train"]
    validation = [e for e in episodes if e["split"] == "validation"]
    test = [e for e in episodes if e["split"] == "test"]
    x = torch.tensor(
        [c["features"] for e in train for c in e["candidates"]], dtype=torch.float32
    )
    y = torch.tensor(
        [c["teacher_utility"] for e in train for c in e["candidates"]],
        dtype=torch.float32,
    )
    model = ActionPolicy(len(FEATURES), hidden=32)
    initial = {k: v.clone() for k, v in model.state_dict().items()}
    initial_metrics = evaluate(model, validation)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.003)
    best, best_loss, steps = None, float("inf"), 0
    for epoch in range(epochs):
        order = torch.randperm(len(x))
        for indices in order.split(512):
            prediction = model(x[indices].unsqueeze(1)).squeeze(1)
            loss = torch.nn.functional.mse_loss(prediction, y[indices])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            steps += 1
        metrics = evaluate(model, validation)
        if metrics["mean_regret"] < best_loss:
            best_loss = metrics["mean_regret"]
            best = {k: v.clone() for k, v in model.state_dict().items()}
        progress(
            status="training",
            completed_states=states,
            epoch=epoch + 1,
            epochs=epochs,
            optimizer_steps=steps,
            validation=metrics,
        )
    model.load_state_dict(best)
    final_validation, final_test = evaluate(model, validation), evaluate(model, test)
    passed = (
        final_validation["mean_regret"] < 0.025
        and final_test["mean_regret"] < 0.025
        and final_test["mean_objective"] > final_test["uniform_random_mean_objective"]
    )
    run_id = output.name
    artifact = dict(
        schema_version=1,
        scope=SCOPE,
        features=list(FEATURES),
        catalog_sha256=coach.catalog_sha256,
        objective="synthetic_attribute_teacher_distillation",
        objective_version=2,
        training_run_id=run_id,
        evaluation_passed=passed,
        w1=model.layers[0].weight.detach().tolist(),
        b1=model.layers[0].bias.detach().tolist(),
        w2=model.layers[2].weight.detach()[0].tolist(),
        b2=float(model.layers[2].bias.detach()[0]),
    )
    (output / "weights.json").write_text(json.dumps(artifact, separators=(",", ":")))
    parity = None
    if passed:
        portable = StrategyRanker(artifact, coach.catalog_sha256)
        probe = [c["features"] for e in test[:10] for c in e["candidates"]]
        with torch.no_grad():
            reference = model(torch.tensor([probe], dtype=torch.float32))[0].numpy()
        parity = float(np.max(np.abs(reference - np.asarray(portable.predict(probe)))))
        if parity > 1e-5:
            raise ValueError("portable model diverges from training runtime")
    report = dict(
        schema_version=1,
        scope=SCOPE,
        status="completed",
        objective=artifact["objective"],
        requested_states=states,
        engine=engine,
        train_states=len(train),
        validation_states=len(validation),
        test_states=len(test),
        training_candidates=len(x),
        optimizer_steps=steps,
        epochs=epochs,
        changed_parameter_tensors=sum(
            not torch.equal(v, initial[k]) for k, v in model.state_dict().items()
        ),
        parameters=sum(p.numel() for p in model.parameters()),
        seed=seed,
        initial_validation=initial_metrics,
        final_validation=final_validation,
        test=final_test,
        evaluation_passed=passed,
        portable_max_absolute_error=parity,
        catalog_sha256=coach.catalog_sha256,
        weights_sha256=hashlib.sha256(
            (output / "weights.json").read_bytes()
        ).hexdigest(),
        dataset_sha256=hashlib.sha256(
            (output / "dataset.jsonl.gz").read_bytes()
        ).hexdigest(),
        elapsed_seconds=time.perf_counter() - start,
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        real_tft_improvement_proven=False,
        complete_matches=0,
        human_demonstrations=0,
        runtime_promoted=False,
        abilities_used=False,
    )
    (output / "report.json").write_text(json.dumps(report, indent=2))
    progress(status="completed", completed_states=states, evaluation_passed=passed)
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--states", type=int, default=10000)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--dataset", type=Path)
    args = parser.parse_args()
    run(args.root, args.output, args.states, args.epochs, dataset=args.dataset)
