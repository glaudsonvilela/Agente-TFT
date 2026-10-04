"""Offline SFT → DPO experiment on independently reviewed decision rows.

This consumes explicit candidate-action features, not raw videos. Verification
checks the declared provenance and referenced evidence bytes; it does not turn
metadata into proof that an annotation or a simulator is faithful to TFT.
"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from ingestion.knowledge_release import canonical
from training.decision_objectives import (
    ActionPolicy,
    frozen_reference,
    masked_log_probabilities,
    preference_loss,
    supervised_action_loss,
    validate_partition,
)
from training.event_lab import engine_identity


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(document, *, patch, content_sha256, engine_sha256, evidence_root):
    if (
        document.get("schema_version") != 1
        or document.get("kind") != "reviewed_action_features"
    ):
        raise ValueError("expected reviewed_action_features schema 1")
    names = document.get("feature_names")
    if (
        not isinstance(names, list)
        or not 1 <= len(names) <= 4096
        or any(not isinstance(v, str) or not v for v in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError("explicit unique observable feature names required")
    records = document.get("records", [])
    audit = validate_partition(
        records, patch=patch, content_sha256=content_sha256, engine_sha256=engine_sha256
    )
    registry = document.get("evidence_registry", {})
    checked = {}
    for row in records:
        evidence_id = row["label_provenance"]["evidence_id"]
        if evidence_id in checked:
            continue
        entry = registry.get(evidence_id)
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ValueError("review evidence missing from registry")
        path = Path(evidence_root) / entry["path"]
        if not path.is_file() or sha(path) != entry["sha256"]:
            raise ValueError("review evidence missing or checksum changed")
        checked[evidence_id] = entry["sha256"]
    # Each phase has its own independent validation examples.
    groups = {}
    for split in ("train", "validation", "test"):
        for mode in ("sft", "dpo"):
            selected = [
                r for r in records if r["split"] == split and r.get("mode") == mode
            ]
            if split != "test" and not selected:
                raise ValueError(
                    "SFT and DPO each require train and validation examples"
                )
            groups[split, mode] = selected
    if sum(len(rows) for rows in groups.values()) != len(records):
        raise ValueError("unknown training objective")
    tensors = {}
    for key, rows in groups.items():
        if not rows:
            continue
        counts = [len(r.get("candidates", [])) for r in rows]
        if min(counts) < 2 or max(counts) > 512:
            raise ValueError("expected 2..512 distinct candidate actions per state")
        x = torch.zeros((len(rows), max(counts), len(names)), dtype=torch.float32)
        legal = torch.zeros((len(rows), max(counts)), dtype=torch.bool)
        chosen, rejected = [], []
        for index, row in enumerate(rows):
            actions = row["candidates"]
            if len({a["id"] for a in actions}) != len(actions):
                raise ValueError("candidate action IDs must be unique")
            for slot, action in enumerate(actions):
                values = action.get("features")
                if (
                    not isinstance(values, list)
                    or len(values) != len(names)
                    or any(
                        type(v) not in (int, float) or not np.isfinite(v)
                        for v in values
                    )
                    or type(action.get("legal")) is not bool
                ):
                    raise ValueError(
                        "finite observable features and explicit legality required"
                    )
                x[index, slot] = torch.tensor(values)
                legal[index, slot] = action["legal"]
            target = row.get("chosen")
            if (
                type(target) is not int
                or not 0 <= target < len(actions)
                or not legal[index, target]
            ):
                raise ValueError("chosen action must be legal")
            chosen.append(target)
            kind = row["label_provenance"]["kind"]
            if key[1] == "sft":
                if kind != "reviewed_demonstration":
                    raise ValueError("SFT requires a reviewed demonstration")
            else:
                alternative = row.get("rejected")
                if (
                    kind == "reviewed_demonstration"
                    or type(alternative) is not int
                    or not 0 <= alternative < len(actions)
                    or alternative == target
                    or not legal[index, alternative]
                ):
                    raise ValueError(
                        "DPO requires two different legal actions and a preference review"
                    )
                rejected.append(alternative)
        tensors[key] = (
            x,
            legal,
            torch.tensor(chosen),
            torch.tensor(rejected, dtype=torch.long),
        )
    audit.update(
        evidence_sha256=checked,
        feature_names=names,
        feature_schema_sha256=hashlib.sha256(canonical(names)).hexdigest(),
        evidence_semantics_independently_verified=False,
    )
    return tensors, audit


@torch.no_grad()
def evaluate(policy, tensors):
    result = {}
    for (split, mode), (x, legal, chosen, rejected) in tensors.items():
        if split == "train":
            continue
        scores = policy(x)
        logp = masked_log_probabilities(scores, legal)
        rows = torch.arange(len(chosen))
        values = dict(
            rows=len(chosen),
            chosen_nll=float(-logp[rows, chosen].mean()),
            top1_accuracy=float((logp.argmax(1) == chosen).float().mean()),
        )
        if mode == "dpo":
            margin = scores[rows, chosen] - scores[rows, rejected]
            values.update(
                preference_accuracy=float((margin > 0).float().mean()),
                mean_preference_margin=float(margin.mean()),
            )
        result[split + "/" + mode] = values
    return result


def fit(
    tensors,
    features,
    *,
    seed=0,
    sft_epochs=30,
    dpo_epochs=30,
    beta=0.1,
    learning_rate=0.001
):
    if any(type(v) is not int or not 1 <= v <= 1000 for v in (sft_epochs, dpo_epochs)):
        raise ValueError("each phase requires 1..1000 epochs")
    if not np.isfinite(learning_rate) or not 0 < learning_rate <= 0.1:
        raise ValueError("invalid learning rate")
    if type(beta) not in (int, float) or not np.isfinite(beta) or beta <= 0:
        raise ValueError("invalid DPO beta")
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        policy = ActionPolicy(features)
        history = dict(initial=evaluate(policy, tensors), objectives={})
        reference = None
        for mode, epochs in (("sft", sft_epochs), ("dpo", dpo_epochs)):
            optimizer = torch.optim.AdamW(policy.parameters(), lr=learning_rate)
            if mode == "dpo":
                reference = frozen_reference(policy)
                reference_parameters = deepcopy(reference.state_dict())
            x, legal, chosen, rejected = tensors["train", mode]
            total_steps = 0
            losses = []
            for _ in range(epochs):
                for indices in torch.randperm(len(x)).split(64):
                    optimizer.zero_grad()
                    logits = policy(x[indices])
                    if mode == "sft":
                        loss = supervised_action_loss(
                            logits, chosen[indices], legal[indices]
                        )
                    else:
                        loss, _ = preference_loss(
                            logits,
                            reference(x[indices]),
                            chosen[indices],
                            rejected[indices],
                            legal[indices],
                            beta=beta,
                        )
                    if not torch.isfinite(loss):
                        raise ValueError("nonfinite training objective")
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(
                        policy.parameters(), 1.0, error_if_nonfinite=True
                    )
                    optimizer.step()
                    losses.append(float(loss.detach()))
                    total_steps += 1
            history["objectives"][mode] = dict(
                epochs=epochs,
                optimizer_steps=total_steps,
                first_batch_loss=losses[0],
                last_batch_loss=losses[-1],
            )
            history["after_" + mode] = evaluate(policy, tensors)
        history["reference_unchanged"] = all(
            torch.equal(reference_parameters[k], v)
            for k, v in reference.state_dict().items()
        )
    return policy, history


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--content", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sft-epochs", type=int, default=30)
    parser.add_argument("--dpo-epochs", type=int, default=30)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    content = json.loads(args.content.read_text())
    engine = engine_identity()
    document = json.loads(args.dataset.read_text())
    tensors, audit = prepare(
        document,
        patch=content["patch"],
        content_sha256=sha(args.content),
        engine_sha256=engine["sha256"],
        evidence_root=args.dataset.parent,
    )
    torch.set_num_threads(1)
    model, metrics = fit(
        tensors,
        len(audit["feature_names"]),
        seed=args.seed,
        sft_epochs=args.sft_epochs,
        dpo_epochs=args.dpo_epochs,
    )
    # Every run is an explicit new candidate; never overwrite a previous model.
    args.output.mkdir(parents=True, exist_ok=False)
    checkpoint = args.output / "candidate-action-policy.npz"
    np.savez_compressed(
        checkpoint,
        **{k: v.detach().cpu().numpy() for k, v in model.state_dict().items()}
    )
    report = dict(
        schema_version=1,
        kind="offline_sft_dpo_candidate",
        audit=audit,
        metrics=metrics,
        checkpoint_sha256=sha(checkpoint),
        dataset_sha256=sha(args.dataset),
        content_sha256=sha(args.content),
        engine=engine,
        trainer_sha256={
            name: sha(Path(__file__).with_name(name))
            for name in ("decision_lab.py", "decision_objectives.py")
        },
        seed=args.seed,
        runtime_promoted=False,
        real_tft_improvement_proven=False,
        limitation="Metrics compare declared labels. No replay parity or ranked improvement is established.",
    )
    (args.output / "training-report.json").write_bytes(canonical(report))
    print(
        json.dumps(
            dict(
                output=str(args.output.resolve()),
                metrics=metrics,
                runtime_promoted=False,
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
