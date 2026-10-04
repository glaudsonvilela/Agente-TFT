"""Bounded CPU combat/value-network experiment; never a full-match claim.

Only the compiled candidate subset is sampled. Separate scenario seeds are
reserved before training; no transcript is converted into an outcome label.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import resource
import time

import numpy as np
from trainer.simulation.combat import simulate
from trainer.simulation.state import Player, Unit, UnsupportedRule
from trainer.simulation.value_model import BoardEncoder, ENCODER, probabilities


def canonical(value):
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def write(path, value):
    staging = path.with_suffix(".tmp")
    staging.write_bytes(canonical(value))
    staging.replace(path)


def engine_identity():
    root = Path(__file__).resolve().parents[1]
    paths = sorted((root / "trainer/simulation").glob("*.py")) + [
        Path(__file__).resolve()
    ]
    files = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
    }
    return dict(files=files, sha256=hashlib.sha256(canonical(files)).hexdigest())


def scenario(content, seed, champions, items):
    rng = random.Random(seed)
    teams = []
    sampling = content["lab_sampling"]
    stage = rng.choice(sampling["stages"]) if sampling.get("stages") else None
    for team in range(2):
        selected = rng.choices(
            champions,
            k=rng.randint(sampling["team_size_min"], sampling["team_size_max"]),
        )
        cells = rng.sample([(r, c) for r in range(4) for c in range(7)], len(selected))
        units = [
            Unit(
                f"{team}:{i}",
                champion,
                stars=rng.choice(sampling["stars"]),
                zone="board",
                position=cells[i],
                items=rng.sample(items, rng.randrange(4)),
            )
            for i, champion in enumerate(selected)
        ]
        teams.append(Player(0, 4, 0, units=units, stage=stage))
    return teams


def encode(teams, champions, items):
    return BoardEncoder(champions, items).encode(teams)


def metrics(x, y, model):
    _, p = probabilities(x, model)
    return dict(
        cross_entropy=float(-np.log(np.clip(p[np.arange(len(y)), y], 1e-9, 1)).mean()),
        accuracy=float((p.argmax(axis=1) == y).mean()),
        samples=len(y),
    )


def train(x, y, train_ids, validation_ids, epochs=60, seed=0, deadline=float("inf")):
    rng = np.random.default_rng(seed)
    model = dict(
        w1=rng.normal(0, 0.1, (x.shape[1], 32)).astype("float32"),
        b1=np.zeros(32, dtype="float32"),
        w2=rng.normal(0, 0.1, (32, 3)).astype("float32"),
        b2=np.zeros(3, dtype="float32"),
    )
    initial = metrics(x[validation_ids], y[validation_ids], model)
    steps = 0
    # Mirroring is training-only. Both orientations of a board stay in one split.
    tx = x[train_ids]
    ty = y[train_ids]
    half = tx.shape[1] // 2
    tx = np.concatenate((tx, np.concatenate((tx[:, half:], tx[:, :half]), axis=1)))
    ty = np.concatenate((ty, 2 - ty))
    completed = 0
    for epoch in range(epochs):
        if time.monotonic() >= deadline:
            break
        for indices in np.array_split(
            rng.permutation(len(ty)), max(1, (len(ty) + 63) // 64)
        ):
            xb = tx[indices]
            labels = ty[indices]
            h, p = probabilities(xb, model)
            dz = p
            dz[np.arange(len(labels)), labels] -= 1
            dz /= len(labels)
            dh = (dz @ model["w2"].T) * (1 - h * h)
            gradients = dict(
                w2=h.T @ dz, b2=dz.sum(axis=0), w1=xb.T @ dh, b1=dh.sum(axis=0)
            )
            for key in model:
                model[key] -= 0.04 * np.clip(gradients[key], -2, 2)
            steps += 1
        completed = epoch + 1
    majority = int(np.bincount(y[train_ids], minlength=3).argmax())
    return model, dict(
        optimizer_steps=steps,
        epochs_completed=completed,
        epochs_requested=epochs,
        parameters=sum(v.size for v in model.values()),
        training_scenarios=len(train_ids),
        validation_scenarios=len(validation_ids),
        initial_validation=initial,
        final_validation=metrics(x[validation_ids], y[validation_ids], model),
        majority_baseline_accuracy=float((y[validation_ids] == majority).mean()),
        split="scenario_seed_before_mirroring",
        objective="predict_candidate_combat_outcome",
        real_tft_improvement_proven=False,
        runtime_promoted=False,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--content", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--combats", type=int, default=500)
    p.add_argument("--seconds", type=int, default=180)
    p.add_argument("--epochs", type=int, default=60)
    a = p.parse_args()
    if (
        not 50 <= a.combats <= 5000
        or not 10 <= a.seconds <= 3600
        or not 1 <= a.epochs <= 200
    ):
        p.error("invalid laboratory budget")
    content = json.loads(a.content.read_text())
    if (
        content.get("schema_version") != 3
        or content.get("combat_version") != 2
        or content.get("scope") != "experimental_hex_lab"
    ):
        p.error(
            "version 3 seasonal bundle required; recompile with training.compile_effects"
        )
    champions = sorted(
        k for k, v in content["champions"].items() if not v.get("unsupported")
    )
    items = content["lab_sampling"]["items"]
    if (
        len(items) < 3
        or len(set(items)) != len(items)
        or any(
            content["items"].get(i, {}).get("combat_handler") != "effects"
            for i in items
        )
    ):
        p.error("invalid or unsupported laboratory item pool")
    identity = {
        k: content[k]
        for k in ("patch", "release_sha256", "bindings_sha256", "data_components")
    }
    identity["content_sha256"] = hashlib.sha256(a.content.read_bytes()).hexdigest()
    started = time.monotonic()
    cpu_started = time.process_time()
    a.output.mkdir(parents=True, exist_ok=True)
    features = []
    labels = []
    durations = []
    events = 0
    seeds = []
    rejections = {}
    report = dict(
        schema_version=1,
        scope="experimental_event_lab",
        status="simulating",
        combats_requested=a.combats,
        combat_calls=0,
        complete_matches=0,
        processed_events=0,
        elapsed_seconds=0,
        coverage=content["coverage"],
        engine=engine_identity(),
        data_identity=identity,
        runtime_promoted=False,
    )
    dataset_path = a.output / "scenarios.jsonl"
    if dataset_path.exists():
        p.error("use a new output directory; existing samples are immutable")
    with dataset_path.open("x") as dataset, (
        a.output / "rejected-scenarios.jsonl"
    ).open("x") as rejected:
        for seed in range(a.combats * 5):
            if len(labels) >= a.combats:
                break
            if time.monotonic() - started >= a.seconds or (a.output / "STOP").exists():
                break
            teams = scenario(content, seed, champions, items)
            tick = time.monotonic()
            try:
                result = simulate(teams, content, seed=seed)
            except UnsupportedRule as exc:
                reason = str(exc)
                rejections[reason] = rejections.get(reason, 0) + 1
                rejected.write(canonical(dict(seed=seed, reason=reason)).decode())
                continue
            durations.append(time.monotonic() - tick)
            events += result["processed_events"]
            label = 1 if result["winner"] is None else 2 if result["winner"] == 0 else 0
            features.append(encode(teams, champions, items))
            labels.append(label)
            seeds.append(seed)
            dataset.write(
                canonical(
                    dict(
                        seed=seed,
                        teams=[asdict(t) for t in teams],
                        result=result,
                        label=label,
                    )
                ).decode()
            )
            if seed % 10 == 0 or seed + 1 == a.combats:
                dataset.flush()
                report.update(
                    combat_calls=len(labels),
                    processed_events=events,
                    elapsed_seconds=time.monotonic() - started,
                    rejected_scenarios=sum(rejections.values()),
                    rejection_reasons=rejections,
                )
                write(a.output / "report.json", report)
    report.update(
        combat_calls=len(labels),
        status="training",
        complete_matches=0,
        rejected_scenarios=sum(rejections.values()),
        rejection_reasons=rejections,
    )
    write(a.output / "report.json", report)
    if len(labels) >= 50 and not (a.output / "STOP").exists():
        x = np.asarray(features, dtype="float32")
        y = np.asarray(labels, dtype="int64")
        validation_ids = np.flatnonzero(np.asarray(seeds) % 5 == 0)
        train_ids = np.flatnonzero(np.asarray(seeds) % 5 != 0)
        if not len(validation_ids) or not len(train_ids):
            raise ValueError("No independent scenario split after coverage filtering")
        model, training = train(
            x, y, train_ids, validation_ids, a.epochs, deadline=started + a.seconds
        )
        checkpoint = a.output / "candidate.npz"
        np.savez_compressed(checkpoint, **model)
        training["checkpoint_sha256"] = hashlib.sha256(
            checkpoint.read_bytes()
        ).hexdigest()
        training["checkpoint_bytes"] = checkpoint.stat().st_size
        report["neural"] = training
        write(
            a.output / "model-schema.json",
            dict(
                data_identity=identity,
                engine_sha256=report["engine"]["sha256"],
                checkpoint_sha256=training["checkpoint_sha256"],
                champions=champions,
                items=items,
                encoder_id=ENCODER,
                features_per_hex=champions + ["stars/3"] + items,
                supported_stars=sorted(set(content["lab_sampling"]["stars"])),
                labels=["team_1_wins", "tie_or_timeout", "team_0_wins"],
                validation_seeds=[seeds[i] for i in validation_ids],
                runtime_promoted=False,
            ),
        )
    report.update(
        status=(
            "completed"
            if len(labels) == a.combats
            and report.get("neural", {}).get("epochs_completed") == a.epochs
            else "stopped_or_budget_limited"
        ),
        content_sha256=hashlib.sha256(a.content.read_bytes()).hexdigest(),
        dataset_sha256=hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        processed_events=events,
        elapsed_seconds=time.monotonic() - started,
        process_cpu_seconds=time.process_time() - cpu_started,
        mean_combat_ms=float(np.mean(durations) * 1000) if durations else None,
        p95_combat_ms=float(np.percentile(durations, 95) * 1000) if durations else None,
        peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        current_patch_training_ready=False,
        runtime_promoted=False,
    )
    write(a.output / "report.json", report)
    print(json.dumps({k: v for k, v in report.items() if k != "coverage"}, indent=2))


if __name__ == "__main__":
    main()
