"""Learn visual continuity from expert VOD triplets, independent of subtitles.

The frozen DINO ONNX encoder observes board, shop, and opponent regions. A
small projection head learns which before/after views belong to the same
moment. This is visual representation learning, not an action or reward model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image


REGIONS = {
    "board": (0.10, 0.03, 0.86, 0.82),
    "shop": (0.16, 0.79, 0.84, 1.00),
    "opponents": (0.85, 0.06, 1.00, 0.85),
}
ROLES = ("before", "during", "after")


def crops(path: str, size: int = 140) -> np.ndarray:
    with Image.open(path) as image:
        image = image.convert("RGB")
        width, height = image.size
        result = []
        for bounds in REGIONS.values():
            box = (int(bounds[0] * width), int(bounds[1] * height),
                   int(bounds[2] * width), int(bounds[3] * height))
            region = image.crop(box).resize((size, size), Image.Resampling.BICUBIC)
            result.append(np.asarray(region, dtype=np.float32).transpose(2, 0, 1) / 255.0)
        return np.stack(result)


def normalize(array: np.ndarray) -> np.ndarray:
    return array / np.maximum(np.linalg.norm(array, axis=-1, keepdims=True), 1e-9)


def extract(rows: list[dict], encoder: Path, output: Path,
            reuse_run: Path | None = None,
            reuse_triplets: Path | None = None) -> tuple[np.ndarray, int]:
    import onnxruntime as ort

    if len(rows) != 1000 or any(row["status"] != "visual_triplet_ready" for row in rows):
        raise ValueError("exactly 1000 complete visual triplets are required")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(encoder), sess_options=options,
                                   providers=["CPUExecutionProvider"])
    if session.get_inputs()[0].shape[-2:] != [140, 140]:
        raise ValueError("unexpected DINO input resolution")
    path = output / "visual_features.npy"
    features = np.lib.format.open_memmap(path, mode="w+", dtype=np.float32,
                                         shape=(len(rows), len(ROLES), len(REGIONS), 384))
    old_features = None
    old_rows = {}
    if reuse_run is not None and reuse_triplets is not None:
        if (reuse_run / "encoder.sha256").read_text().strip() != (output / "encoder.sha256").read_text().strip():
            raise ValueError("cached features used a different visual encoder")
        old_features = np.load(reuse_run / "visual_features.npy", mmap_mode="r")
        old_rows = {row["moment"]: (index, row) for index, row in enumerate(
            json.loads(line) for line in reuse_triplets.open())}
    reused = 0
    started = time.perf_counter()
    for index, row in enumerate(rows):
        old = old_rows.get(row["moment"])
        matching = (old is not None and
                    old[1]["source_sha256"] == row["source_sha256"] and
                    old[1]["source_seconds"] == row["source_seconds"] and
                    all(Path(row["images"][role]).samefile(old[1]["images"][role])
                        for role in ROLES))
        if matching:
            features[index] = old_features[old[0]]
            reused += 1
        else:
            pixels = np.concatenate([crops(row["images"][role]) for role in ROLES])
            embeddings = session.run(None, {session.get_inputs()[0].name: pixels})[0]
            if embeddings.shape != (len(ROLES) * len(REGIONS), 384):
                raise ValueError(f"unexpected encoder output {embeddings.shape}")
            features[index] = normalize(embeddings.reshape(len(ROLES), len(REGIONS), 384))
        if (index + 1) % 25 == 0 or index == 0:
            features.flush()
            print(f"VISÃO {index+1}/1000 | tabuleiro, loja, adversários | "
                  f"{reused} quadros reaproveitados | {(time.perf_counter()-started)/60:.1f} min", flush=True)
    return np.asarray(features), reused


def pair_accuracy(features: np.ndarray, rows: list[dict], indices: list[int],
                  weight: np.ndarray | None = None) -> tuple[int, int]:
    if not indices:
        raise ValueError("empty visual validation split")
    before = features[indices, 0].reshape(len(indices), -1)
    after = features[indices, 2].reshape(len(indices), -1)
    if weight is not None:
        before, after = before @ weight, after @ weight
    before, after = normalize(before), normalize(after)
    similarities = before @ after.T
    # Distractors must come from the same video and be at least one minute away.
    valid = np.zeros_like(similarities, dtype=bool)
    for i, a in enumerate(indices):
        for j, b in enumerate(indices):
            valid[i, j] = (a == b or
                           (rows[a]["source_sha256"] == rows[b]["source_sha256"] and
                            abs(rows[a]["source_seconds"] - rows[b]["source_seconds"]) >= 60))
    similarities[~valid] = -2
    return int(np.sum(np.argmax(similarities, axis=1) == np.arange(len(indices)))), len(indices)


def train(features: np.ndarray, rows: list[dict], output: Path,
          epochs: int = 20, reused_features: int = 0) -> dict:
    import torch

    torch.set_num_threads(4)
    sources = sorted({row["source_sha256"] for row in rows})
    if len(sources) < 2:
        raise ValueError("need two source videos for source holdout")
    holdout = sources[0]
    train_indices = {source: [i for i, row in enumerate(rows)
                              if row["source_sha256"] == source]
                     for source in sources if source != holdout}
    test_indices = [i for i, row in enumerate(rows) if row["source_sha256"] == holdout]
    baseline_correct, test_count = pair_accuracy(features, rows, test_indices)
    x = torch.from_numpy(features.reshape(len(rows), 3, -1).copy())
    torch.manual_seed(20261008)
    head = torch.nn.Linear(x.shape[-1], 128, bias=False)
    optimizer = torch.optim.AdamW(head.parameters(), lr=0.0005, weight_decay=0.01)
    final_correct = baseline_correct
    rng = np.random.default_rng(20261008)
    print(f"Base visual no vídeo separado: {baseline_correct}/{test_count} pares reconhecidos", flush=True)
    for epoch in range(1, epochs + 1):
        losses = []
        for indices in train_indices.values():
            order = np.asarray(indices)
            rng.shuffle(order)
            for chunk in np.array_split(order, max(1, len(order) // 32)):
                if len(chunk) < 2:
                    continue
                views = [torch.nn.functional.normalize(head(x[chunk, role]), dim=1)
                         for role in range(3)]
                seconds = torch.tensor([rows[int(i)]["source_seconds"] for i in chunk])
                near = (seconds[:, None] - seconds[None, :]).abs() < 60
                near.fill_diagonal_(False)
                labels = torch.arange(len(chunk))
                pair_losses = []
                for left, right in ((0, 1), (1, 2), (0, 2)):
                    logits = (views[left] @ views[right].T / 0.08).masked_fill(near, -1e4)
                    pair_losses.append((torch.nn.functional.cross_entropy(logits, labels) +
                                        torch.nn.functional.cross_entropy(logits.T, labels)) / 2)
                loss = torch.stack(pair_losses).mean()
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                losses.append(float(loss.detach()))
        weight = head.weight.detach().numpy().T.copy()
        correct, _ = pair_accuracy(features, rows, test_indices, weight)
        print(f"ÉPOCA {epoch:02d}/{epochs} | perda {np.mean(losses):.3f} | "
              f"vídeo separado {correct}/{test_count}", flush=True)
        final_correct = correct
    # Fixed final checkpoint: the held-out video never selects model weights.
    np.save(output / "visual_head.npy", weight)
    # Region deltas are candidates for review, not semantic action labels.
    changes = []
    for i, row in enumerate(rows):
        distances = 1 - np.sum(features[i, 0] * features[i, 2], axis=1)
        changes.append({"moment": row["moment"], "source_sha256": row["source_sha256"],
                        "source_seconds": row["source_seconds"],
                        "region_change": {key: round(float(value), 4)
                                          for key, value in zip(REGIONS, distances)},
                        "executed_action_label": None})
    changes.sort(key=lambda row: max(row["region_change"].values()), reverse=True)
    with (output / "visual_change_candidates.jsonl").open("w") as log:
        for row in changes:
            log.write(json.dumps(row) + "\n")
    report = {"moments": len(rows), "encoder": "frozen_dino_int8",
              "reused_features": reused_features,
              "encoder_sha256": (output / "encoder.sha256").read_text().strip(),
              "training": "visual_before_after_contrastive_head",
              "speech_used_for_training": False, "held_out_source": holdout,
              "baseline_correct": baseline_correct, "final_correct": final_correct,
              "held_out_pairs": test_count, "checkpoint_epoch": epochs,
              "executed_action_labels": 0, "strategy_policy_trained": False}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"FINAL | visual {baseline_correct}/{test_count} → {final_correct}/{test_count} "
          f"no vídeo separado | ações identificadas: 0", flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--triplets", type=Path, required=True)
    parser.add_argument("--encoder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-run", type=Path)
    parser.add_argument("--reuse-triplets", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("use a new output directory")
    if (args.reuse_run is None) != (args.reuse_triplets is None):
        raise ValueError("provide both cached run and its triplet index")
    rows = [json.loads(line) for line in args.triplets.open()]
    args.output.mkdir(parents=True)
    (args.output / "encoder.sha256").write_text(hashlib.sha256(args.encoder.read_bytes()).hexdigest())
    print("Treino visual: imagens antes/durante/depois; transcrições fora do modelo.", flush=True)
    features, reused = extract(rows, args.encoder, args.output,
                               args.reuse_run, args.reuse_triplets)
    train(features, rows, args.output, reused_features=reused)


if __name__ == "__main__":
    main()
