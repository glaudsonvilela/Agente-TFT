"""Learn temporal context from tactical VOD speech on CPU.

Nearby passages in one VOD are a weak context signal, not a strategy action
label. The model is kept in the review pipeline and never promoted to coach.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import random
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


class ContextEncoder(nn.Module):
    def __init__(self, dimensions: int):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(dimensions, 64), nn.GELU(), nn.Linear(64, dimensions))

    def forward(self, x):
        return F.normalize(x + self.layers(x), dim=-1)


def pair_examples(rows: list[dict], *, positive_gap: int = 90, negative_gap: int = 600):
    by_source = defaultdict(list)
    for i, row in enumerate(rows):
        by_source[row["source_sha256"]].append(i)
    pairs = {}
    for source, indices in by_source.items():
        indices.sort(key=lambda i: rows[i]["start"])
        group = []
        for i, anchor in enumerate(indices):
            later = indices[i + 1 : i + 4]
            positive = next((j for j in later if rows[j]["start"] - rows[anchor]["end"] <= positive_gap), None)
            if positive is None:
                continue
            distant = [j for j in indices if abs(rows[j]["start"] - rows[anchor]["start"]) >= negative_gap]
            if distant:
                group.append((anchor, positive, distant))
        pairs[source] = group
    return pairs


def accuracy(model, x, pairs, seed):
    rng = random.Random(seed)
    if not pairs:
        return None
    with torch.no_grad():
        z = model(x)
        correct = 0
        for anchor, positive, negatives in pairs:
            bad = rng.choice(negatives)
            correct += int(torch.dot(z[anchor], z[positive]) > torch.dot(z[anchor], z[bad]))
    return correct / len(pairs)


def fit(memory: Path, output: Path, *, epochs: int = 200, seed: int = 17):
    if output.exists():
        raise ValueError("use a new output directory")
    rows = [json.loads(line) for line in (memory / "passages.jsonl").open()]
    archive = np.load(memory / "latent_memory.npz")
    x = torch.tensor(archive["embeddings"], dtype=torch.float32)
    groups = pair_examples(rows)
    eligible = sorted((s for s in groups if groups[s]), key=lambda s: -len(groups[s]))
    if len(eligible) < 2:
        raise ValueError("two independently sourced VODs with temporal pairs required")
    validation_source = eligible[-1]
    train = [p for source in eligible if source != validation_source for p in groups[source]]
    validation = groups[validation_source]
    torch.set_num_threads(2)
    torch.manual_seed(seed)
    rng = random.Random(seed)
    model = ContextEncoder(x.shape[1])
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.01)
    baseline = accuracy(model, x, validation, seed)
    output.mkdir(parents=True)
    progress_path = output / "progress.jsonl"
    start = time.perf_counter()
    best_accuracy, best_state, best_epoch = -1.0, None, 0

    def record(**fields):
        event = {"elapsed_seconds": round(time.perf_counter() - start, 2), **fields}
        with progress_path.open("a") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        if event["status"] == "started":
            print("AGENTE TFT · aprendendo contexto de vídeos autorizados", flush=True)
            print(f"Treino: {len(train)} pares de trechos próximos | Validação: {len(validation)} pares de outro VOD", flush=True)
            print(f"Acerto inicial na validação: {baseline:.1%}", flush=True)
            print("Alvo: relacionar explicações próximas na mesma partida; ações ainda exigem revisão visual.", flush=True)
            for row in sorted(rows, key=lambda r: -r["cue_score"])[:3]:
                print(f"  {','.join(row['families'])} · {row['text'][:125]}", flush=True)
        elif event["status"] == "learning":
            print(f"Época {epoch:03d}/{epochs} | erro {event['training_loss']:.4f} | contexto em VOD reservado {valid:.1%} | melhor {best_accuracy:.1%}", flush=True)
        else:
            print(f"Treino concluído | melhor época {best_epoch} | validação {final:.1%} | política de jogadas: ainda sem treino", flush=True)

    record(status="started", train_pairs=len(train), validation_pairs=len(validation),
           train_sources=len(eligible) - 1, validation_source_sha256=validation_source,
           baseline_validation_pair_accuracy=baseline,
           learning_target="nearby_expert_speech_vs_distant_same_vod_speech",
           action_policy_trained=False)
    for epoch in range(1, epochs + 1):
        rng.shuffle(train)
        losses = []
        for offset in range(0, len(train), 128):
            batch = train[offset : offset + 128]
            anchors = torch.tensor([p[0] for p in batch])
            positives = torch.tensor([p[1] for p in batch])
            negatives = torch.tensor([rng.choice(p[2]) for p in batch])
            za, zp, zn = model(x[anchors]), model(x[positives]), model(x[negatives])
            margin = (za * zp).sum(1) - (za * zn).sum(1)
            loss = F.softplus(-8 * margin).mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            losses.append(loss.item())
        if epoch == 1 or epoch % 5 == 0 or epoch == epochs:
            valid = accuracy(model, x, validation, seed)
            if valid > best_accuracy:
                best_accuracy, best_epoch = valid, epoch
                best_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
            record(status="learning", epoch=epoch, epochs=epochs,
                   training_loss=round(sum(losses) / len(losses), 5),
                   validation_pair_accuracy=round(valid, 4),
                   best_validation_pair_accuracy=round(best_accuracy, 4))
            if epoch - best_epoch >= 40:
                break
    model.load_state_dict(best_state)
    final = accuracy(model, x, validation, seed)
    torch.save(model.state_dict(), output / "context_encoder.pt")
    with torch.no_grad():
        np.save(output / "context_vectors.npy", model(x).numpy())
    report = {
        "kind": "authorized_vod_temporal_context_learning",
        "train_pairs": len(train), "validation_pairs": len(validation),
        "validation_source_sha256": validation_source,
        "baseline_validation_pair_accuracy": baseline,
        "best_validation_pair_accuracy": final,
        "best_epoch": best_epoch,
        "learned_scope": "temporal_speech_retrieval_context",
        "expert_action_labels_used": 0,
        "action_policy_trained": False,
        "game_strategy_verified": False,
        "runtime_promoted": False,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    record(status="complete", **report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=200)
    args = parser.parse_args()
    fit(args.memory, args.output, epochs=args.epochs)


if __name__ == "__main__":
    main()
