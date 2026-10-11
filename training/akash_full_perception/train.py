#!/usr/bin/env python3
"""Reset-only DINOv2 + ConvNeXt champion identity experiment for Akash.

This does not fabricate HUD labels. The other perception components are bundled
for the subsequent integrated replay test and are reported separately.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps
import torch
from torch import nn
from torchvision import transforms
from torchvision.models import convnext_tiny, ConvNeXt_Tiny_Weights


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(root: Path) -> tuple[list[dict], dict]:
    manifest = json.loads((root / "bundle-manifest.json").read_text())
    if manifest["old_tft_weights_included"] or manifest["model_predictions_used_as_labels"]:
        raise ValueError("Reset policy failed")
    for entry in manifest["inventory"]:
        file = root / entry["path"]
        if not file.is_file() or sha(file) != entry["sha256"]:
            raise ValueError(f"Bundle hash mismatch: {entry['path']}")
    rows = json.loads((root / "champions.json").read_text())
    if len(rows) != manifest["champion_crops"] or not all(
        row["review_status"] == "user_confirmed_candidate" and sha(root / row["image"]) == row["sha256"]
        for row in rows
    ):
        raise ValueError("Champion review gate failed")
    return rows, manifest


def tensor(image: Image.Image, size: int, normalize: bool) -> np.ndarray:
    array = np.asarray(ImageOps.pad(image.convert("RGB"), (size, size),
                                   method=Image.Resampling.BICUBIC, color=(0, 0, 0)), dtype=np.float32)
    array = array.transpose(2, 0, 1) / 255.0
    if normalize:
        array = (array - np.array([0.485, 0.456, 0.406], np.float32)[:, None, None]) / np.array(
            [0.229, 0.224, 0.225], np.float32)[:, None, None]
    return array


def features(root: Path, rows: list[dict], output: Path) -> tuple[np.ndarray, np.ndarray]:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the Akash GPU experiment")
    print(json.dumps({"event": "gpu", "name": torch.cuda.get_device_name(0)}), flush=True)
    torch.set_num_threads(4)
    pretrained = convnext_tiny(weights=ConvNeXt_Tiny_Weights.IMAGENET1K_V1)
    pretrained.classifier = torch.nn.Sequential(pretrained.classifier[0], pretrained.classifier[1])
    cnn = pretrained.eval().cuda()
    # The reset corpus never supplies network weights. Both feature extractors
    # begin from generic visual pretraining.
    dino = ort.InferenceSession(str(root / "models/dino.onnx"), providers=["CPUExecutionProvider"])
    dino_input = dino.get_inputs()[0]
    dino_size = int(dino_input.shape[-1]) if isinstance(dino_input.shape[-1], int) else 140
    cnn_parts, dino_parts = [], []
    with torch.inference_mode():
        for offset in range(0, len(rows), 4):
            images = [Image.open(root / row["image"]) for row in rows[offset:offset + 4]]
            cnn_input = torch.from_numpy(np.stack([tensor(im, 224, True) for im in images])).cuda()
            cnn_part = cnn(cnn_input).float().cpu().numpy()
            dino_input_array = np.stack([tensor(im, dino_size, False) for im in images])
            dino_part = dino.run(None, {dino_input.name: dino_input_array})[0]
            cnn_parts.append(cnn_part.reshape(len(images), -1))
            dino_parts.append(dino_part.reshape(len(images), -1))
            print(json.dumps({"event": "features", "done": min(offset + 4, len(rows)), "total": len(rows)}), flush=True)
    a, b = np.concatenate(cnn_parts), np.concatenate(dino_parts)
    temporary = output / "features.npz.tmp"
    with temporary.open("wb") as stream:
        np.savez_compressed(stream, convnext=a, dino=b)
    os.replace(temporary, output / "features.npz")
    return a, b


def norm(values: np.ndarray) -> np.ndarray:
    return values / np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-8)


def ridge(train: np.ndarray, targets: np.ndarray, classes: int, alpha: float) -> np.ndarray:
    onehot = np.eye(classes, dtype=np.float64)[targets]
    x = np.concatenate([train.astype(np.float64), np.ones((len(train), 1))], axis=1)
    # Dual solve is stable for this small reviewed corpus and keeps the original
    # feature dimensions intact.
    gram = x @ x.T + alpha * np.eye(len(x))
    return x.T @ np.linalg.solve(gram, onehot)


def scores(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    x = np.concatenate([values.astype(np.float64), np.ones((len(values), 1))], axis=1)
    return x @ weights


def source_holdout(rows: list[dict]) -> tuple[str, list[int], list[int], list[str]]:
    sources = defaultdict(set)
    for row in rows:
        sources[row["champion"]].add(row["source_video"])
    candidates = Counter(row["source_video"] for row in rows if len(sources[row["champion"]]) > 1)
    if not candidates:
        raise ValueError("No cross-video champion class available for evaluation")
    held = sorted(candidates, key=lambda key: (-candidates[key], key))[0]
    train = [index for index, row in enumerate(rows) if row["source_video"] != held]
    represented = {rows[index]["champion"] for index in train}
    test = [index for index, row in enumerate(rows) if row["source_video"] == held and row["champion"] in represented]
    return held, train, test, sorted(represented)


def evaluate(rows: list[dict], cnn: np.ndarray, dino: np.ndarray, output: Path) -> dict:
    held, train, test, represented = source_holdout(rows)
    labels = sorted({row["champion"] for row in rows})
    index = {name: pos for pos, name in enumerate(labels)}
    truth = np.array([index[row["champion"]] for row in rows])
    vectors = {"convnext": norm(cnn), "dino": norm(dino),
               "fusion": np.concatenate([norm(cnn), norm(dino)], axis=1) / np.sqrt(2)}
    trials = []
    for model_name, vector in vectors.items():
        for alpha in (0.01, 0.1, 1.0):
            weights = ridge(vector[train], truth[train], len(labels), alpha)
            predicted = scores(vector[test], weights).argmax(axis=1)
            correct = int((predicted == truth[test]).sum())
            trials.append({"model": model_name, "alpha": alpha, "correct": correct,
                           "total": len(test), "accuracy": round(correct / len(test), 4) if test else None})
    # Report all settings; a winning setting selected on this small holdout is
    # exploratory, not a final independent test score.
    selected = max(trials, key=lambda row: (row["correct"], -row["alpha"], row["model"]))
    vector = vectors[selected["model"]]
    full_weights = ridge(vector, truth, len(labels), selected["alpha"])
    np.savez_compressed(output / "champion-fusion-head.npz", weights=full_weights,
                        labels=np.array(labels), encoder=np.array(selected["model"]),
                        alpha=np.array(selected["alpha"]))
    result = {
        "status": "experimental_not_promoted", "reviewed_crops": len(rows),
        "trained_classes": len(labels), "roster_classes": 65,
        "holdout_video": held, "holdout_named_samples": len(test),
        "holdout_classes": len({rows[i]["champion"] for i in test}),
        "unseen_roster_classes": 65 - len(labels),
        "trials": trials, "selected_for_full_fit": selected,
        "accuracy_note": "Source-disjoint exploratory holdout; no untouched final test, no HUD accuracy claim.",
        "hud_training_status": "not_trained_no_confirmed_full_frame_labels",
    }
    (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def extended_training(root: Path, rows: list[dict], output: Path, minutes: float) -> dict:
    """Spend the requested GPU time on augmented ConvNeXt fine-tuning.

    A source-disjoint diagnostic phase runs first. Its score stops being valid
    once the held-out video is admitted to the final full-corpus phase.
    """
    labels = sorted({row["champion"] for row in rows})
    corpus_hash = hashlib.sha256(json.dumps(
        [(row["champion"], row["sha256"]) for row in rows], sort_keys=True
    ).encode()).hexdigest()
    label_index = {name: i for i, name in enumerate(labels)}
    held, train_ids, test_ids, _ = source_holdout(rows)
    train_aug = transforms.Compose([
        transforms.RandomResizedCrop(224, scale=(0.75, 1.0), ratio=(0.9, 1.1)),
        transforms.RandomHorizontalFlip(),
        transforms.ColorJitter(brightness=0.12, contrast=0.12, saturation=0.12),
        transforms.ToTensor(),
        transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
    ])
    eval_aug = transforms.Compose([
        transforms.Resize((224, 224)), transforms.ToTensor(),
        transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
    ])
    model = convnext_tiny(weights=ConvNeXt_Tiny_Weights.IMAGENET1K_V1)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(labels))
    for param in model.features.parameters():
        param.requires_grad_(False)
    for param in model.features[-1].parameters():
        param.requires_grad_(True)
    model.cuda()
    optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=5e-5, weight_decay=0.02)
    checkpoint = output / "training-checkpoint.pt"
    elapsed_before = 0.0
    epoch = 0
    phase = "source_disjoint_diagnostic"
    phase_scores = []
    best = -1
    if checkpoint.is_file():
        saved = torch.load(checkpoint, map_location="cpu", weights_only=False)
        if (saved["labels"] != labels or saved["holdout_video"] != held
                or saved["corpus_hash"] != corpus_hash):
            raise ValueError("Checkpoint does not match the reviewed corpus")
        model.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        # Checkpoints are written after each evaluation and at most five
        # minutes apart. Downtime is not counted as GPU training time.
        elapsed_before = float(saved["elapsed_s"])
        epoch = int(saved["epoch"])
        phase = saved["phase"]
        phase_scores = list(saved["phase_scores"])
        best = int(saved["best"])
        print(json.dumps({"event": "resume", "elapsed_s": elapsed_before,
                          "epoch": epoch, "phase": phase}), flush=True)
    start = time.monotonic() - elapsed_before
    deadline = start + minutes * 60
    phase_end = start + minutes * 60 * 0.375
    next_log = time.monotonic() + 60
    next_eval = start + (phase_scores[-1]["elapsed_s"] + 300 if phase_scores else 300)
    next_checkpoint = time.monotonic() + 300

    def save_checkpoint(now: float) -> None:
        temporary = checkpoint.with_suffix(".pt.tmp")
        torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                    "labels": labels, "holdout_video": held, "corpus_hash": corpus_hash,
                    "elapsed_s": round(now - start, 1),
                    "epoch": epoch, "phase": phase, "phase_scores": phase_scores, "best": best},
                   temporary)
        os.replace(temporary, checkpoint)
    if not checkpoint.is_file():
        save_checkpoint(time.monotonic())
    while time.monotonic() < deadline:
        now = time.monotonic()
        if phase == "source_disjoint_diagnostic" and now >= phase_end:
            torch.save({"weights": model.state_dict(), "labels": labels, "holdout_video": held},
                       output / "diagnostic-source-disjoint.pt")
            phase = "all_confirmed_crops"
            print(json.dumps({"event": "phase_change", "phase": phase, "elapsed_s": round(now - start, 1)}), flush=True)
            save_checkpoint(now)
        examples = train_ids if phase == "source_disjoint_diagnostic" else list(range(len(rows)))
        order = np.random.default_rng(epoch + 20261010).permutation(examples)
        running_loss = 0.0
        batches = 0
        model.train()
        for offset in range(0, len(order), 8):
            if time.monotonic() >= deadline:
                break
            ids = order[offset:offset + 8]
            inputs = torch.stack([train_aug(Image.open(root / rows[i]["image"]).convert("RGB")) for i in ids]).cuda()
            targets = torch.tensor([label_index[rows[i]["champion"]] for i in ids], device="cuda")
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type="cuda", dtype=torch.float16):
                logits = model(inputs)
                loss = nn.functional.cross_entropy(logits.float(), targets)
            loss.backward()
            optimizer.step()
            running_loss += float(loss.detach())
            batches += 1
        epoch += 1
        now = time.monotonic()
        if now >= next_eval and phase == "source_disjoint_diagnostic":
            model.eval()
            correct = 0
            with torch.inference_mode():
                for offset in range(0, len(test_ids), 8):
                    ids = test_ids[offset:offset + 8]
                    inputs = torch.stack([eval_aug(Image.open(root / rows[i]["image"]).convert("RGB")) for i in ids]).cuda()
                    predictions = model(inputs).argmax(dim=1).cpu().tolist()
                    correct += sum(pred == label_index[rows[i]["champion"]] for pred, i in zip(predictions, ids))
            observation = {"elapsed_s": round(now - start, 1), "correct": correct, "total": len(test_ids)}
            phase_scores.append(observation)
            if correct > best:
                best = correct
                torch.save({"weights": model.state_dict(), "labels": labels, "holdout_video": held},
                           output / "diagnostic-best.pt")
            print(json.dumps({"event": "diagnostic", **observation}), flush=True)
            next_eval = now + 300
            save_checkpoint(now)
            next_checkpoint = now + 300
        elif now >= next_checkpoint:
            save_checkpoint(now)
            next_checkpoint = now + 300
        if now >= next_log:
            print(json.dumps({"event": "training", "phase": phase, "epoch": epoch,
                              "elapsed_s": round(now - start, 1), "remaining_s": round(max(0, deadline - now), 1),
                              "mean_loss": round(running_loss / max(1, batches), 4),
                              "gpu_peak_mib": round(torch.cuda.max_memory_allocated() / 1048576)}), flush=True)
            next_log = now + 60
    save_checkpoint(time.monotonic())
    torch.save({"weights": model.state_dict(), "labels": labels, "all_reviewed_crops": len(rows)},
               output / "convnext-finetuned-experimental.pt")
    return {"duration_seconds": round(time.monotonic() - start, 1), "epochs": epoch,
            "diagnostic_video": held, "diagnostic_scores": phase_scores,
            "final_phase": phase, "status": "experimental_not_promoted"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path, default=Path("/workspace/results"))
    parser.add_argument("--extended-minutes", type=float, default=120)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "complete.flag").exists():
        print(json.dumps({"event": "already_complete"}), flush=True)
        return
    start = time.monotonic()
    rows, manifest = load(args.root)
    print(json.dumps({"event": "preflight", "crops": len(rows), "classes": manifest["champion_classes_in_crops"],
                      "component_states": manifest["component_states"]}, ensure_ascii=False), flush=True)
    cached_features = args.output / "features.npz"
    if cached_features.exists():
        with np.load(cached_features) as cache:
            cnn, dino = cache["convnext"], cache["dino"]
        if len(cnn) != len(rows) or len(dino) != len(rows):
            raise ValueError("Cached features do not match the reviewed corpus")
        print(json.dumps({"event": "features_resumed", "total": len(rows)}), flush=True)
    else:
        cnn, dino = features(args.root, rows, args.output)
    result = evaluate(rows, cnn, dino, args.output)
    if args.extended_minutes > 0:
        result["extended_training"] = extended_training(args.root, rows, args.output, args.extended_minutes)
    result["elapsed_seconds"] = round(time.monotonic() - start, 2)
    (args.output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (args.output / "complete.flag").write_text("complete\n")
    print(json.dumps({"event": "complete", "result": result}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
