"""Experimental video-state forecast, deliberately separate from player policy.

Input frames are sampled from complete 1920x1080 matches. The network sees a
resized frame plus current OCR state and predicts visible stage, gold, and level
30 seconds later. It receives no action, combat, placement, or win labels.
The entire source VOD is held out for evaluation to avoid same-match leakage.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import signal
import time

import numpy as np
from PIL import Image
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset


FIELDS = ("stage", "gold", "level")
SCALES = np.array([70.0, 100.0, 10.0], dtype=np.float32)
DEFAULT_HOLDOUT_VOD = "2894958056"
VALIDATION_MATCH_ID = "setsuko-2894958056-game1"
TEST_MATCH_ID = "setsuko-2894958056-game2"


def stage_number(value: object) -> float | None:
    if not isinstance(value, str) or len(value) != 3 or value[1] != "-":
        return None
    if not value[0].isdigit() or not value[2].isdigit():
        return None
    major, minor = int(value[0]), int(value[2])
    return float((major - 1) * 7 + minor) if 1 <= major <= 9 and 1 <= minor <= 7 else None


def numeric_state(row: dict) -> tuple[np.ndarray, np.ndarray]:
    parsed = row.get("parsed", {})
    values = [stage_number(parsed.get("stage")), parsed.get("gold"), parsed.get("level")]
    valid = np.array([
        value is not None and isinstance(value, (int, float)) and
        ((1 <= value <= 63) if i == 0 else (0 <= value <= 150) if i == 1 else (1 <= value <= 10))
        for i, value in enumerate(values)
    ], dtype=np.float32)
    clean = np.array([float(value) if good else 0.0 for value, good in zip(values, valid)],
                     dtype=np.float32)
    return clean / SCALES, valid


def load_examples(index_path: Path, frames_root: Path, holdout_vod: str) -> tuple[list[dict], list[dict]]:
    index = json.loads(index_path.read_text())
    if index.get("schema_version") != 1 or index.get("interval_seconds") != 15:
        raise ValueError("15-second experimental index required")
    if index.get("native_resolution") != [1920, 1080]:
        raise ValueError("only native 1920x1080 source frames accepted")
    train: list[dict] = []
    holdout: list[dict] = []
    matches = index.get("matches", [])
    if len({m["match_id"] for m in matches}) != len(matches):
        raise ValueError("duplicate match IDs")
    for match in matches:
        rows = match["observations"]
        vod = match["source_vod_id"]
        destination = holdout if vod == holdout_vod else train
        for before, after in zip(rows, rows[2:]):
            if after["frame_number"] != before["frame_number"] + 2:
                continue
            state, state_valid = numeric_state(before)
            target, target_valid = numeric_state(after)
            if not target_valid.any():
                continue
            frame = frames_root / match["match_id"] / before["frame"]
            if not frame.is_file():
                raise FileNotFoundError(frame)
            destination.append({"frame": str(frame), "state": state, "state_valid": state_valid,
                                "target": target, "target_valid": target_valid,
                                "match_id": match["match_id"], "source_vod_id": vod})
    if not train or not holdout:
        raise ValueError("train and held-out VOD examples are both required")
    return train, holdout


class StateDataset(Dataset):
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int):
        row = self.rows[index]
        with Image.open(row["frame"]) as source:
            if source.size != (1920, 1080):
                raise ValueError(f"non-1080p frame: {row['frame']}")
            image = source.convert("RGB").resize((320, 180), Image.Resampling.BILINEAR)
            pixels = np.asarray(image, dtype=np.float32).transpose(2, 0, 1) / 255.0
        state = np.concatenate((row["state"], row["state_valid"]), dtype=np.float32)
        return (torch.from_numpy(pixels), torch.from_numpy(state),
                torch.from_numpy(row["target"]), torch.from_numpy(row["target_valid"]))


class StateNet(nn.Module):
    def __init__(self):
        super().__init__()
        layers = []
        channels = [3, 16, 32, 48, 64]
        for cin, cout in zip(channels, channels[1:]):
            layers.extend((nn.Conv2d(cin, cout, 3, stride=2, padding=1), nn.ReLU()))
        self.image = nn.Sequential(*layers, nn.AdaptiveAvgPool2d((3, 5)), nn.Flatten(),
                                   nn.Linear(64 * 3 * 5, 64), nn.ReLU())
        self.head = nn.Sequential(nn.Linear(70, 64), nn.ReLU(), nn.Linear(64, 3))
        nn.init.zeros_(self.head[-1].weight)
        nn.init.zeros_(self.head[-1].bias)

    def forward(self, image: torch.Tensor, state: torch.Tensor) -> torch.Tensor:
        return state[:, :3] + self.head(torch.cat((self.image(image), state), dim=1))


def masked_loss(prediction: torch.Tensor, target: torch.Tensor,
                valid: torch.Tensor) -> torch.Tensor:
    error = nn.functional.smooth_l1_loss(prediction, target, reduction="none")
    return (error * valid).sum() / valid.sum().clamp_min(1)


@torch.no_grad()
def evaluate(model: StateNet, loader: DataLoader, device: torch.device) -> dict:
    model.eval()
    absolute = np.zeros(3, dtype=np.float64)
    baseline = np.zeros(3, dtype=np.float64)
    counts = np.zeros(3, dtype=np.int64)
    for image, state, target, valid in loader:
        image, state = image.to(device), state.to(device)
        prediction = model(image, state).cpu().numpy()
        target, valid = target.numpy(), valid.numpy()
        current = state.cpu().numpy()
        mask = (valid > 0) & (current[:, 3:] > 0)
        absolute += (np.abs(prediction - target) * mask).sum(axis=0) * SCALES
        baseline += (np.abs(current[:, :3] - target) * mask).sum(axis=0) * SCALES
        counts += mask.sum(axis=0)
    mae = np.divide(absolute, counts, out=np.full(3, np.nan), where=counts > 0)
    base_mae = np.divide(baseline, counts, out=np.full(3, np.nan), where=counts > 0)
    return {field: {"count": int(counts[i]), "model_mae": float(mae[i]),
                    "persistence_mae": float(base_mae[i])}
            for i, field in enumerate(FIELDS)}


def atomic_checkpoint(output: Path, model: StateNet, optimizer: torch.optim.Optimizer,
                      epoch: int, best_score: float, best_metrics: dict,
                      best_model: dict, stale_epochs: int,
                      dataset_sha256: str, started_utc: float) -> None:
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / "experimental-state-checkpoint.pt"
    temporary = output / "experimental-state-checkpoint.pt.tmp"
    torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(),
                "epoch": epoch, "best_score": best_score, "best_metrics": best_metrics,
                "best_model": best_model, "stale_epochs": stale_epochs,
                "python_rng_state": random.getstate(), "numpy_rng_state": np.random.get_state(),
                "torch_rng_state": torch.get_rng_state(),
                "cuda_rng_state": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else None,
                "dataset_sha256": dataset_sha256, "started_utc": started_utc}, temporary)
    os.replace(temporary, artifact)
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    seal = output / "checkpoint.json"
    seal_temp = output / "checkpoint.json.tmp"
    seal_temp.write_text(json.dumps({"path": artifact.name, "sha256": digest}) + "\n")
    os.replace(seal_temp, seal)


def train(index: Path, frames: Path, output: Path, *, holdout_vod: str,
          max_epochs: int, batch_size: int, branches: Path | None = None,
          resume: bool = False) -> dict:
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    random.seed(20261012)
    np.random.seed(20261012)
    torch.manual_seed(20261012)
    source_digest = hashlib.sha256(index.read_bytes()).hexdigest()
    index_facts = json.loads(index.read_text())
    train_rows, holdout_rows = load_examples(index, frames, holdout_vod)
    validation_rows = [row for row in holdout_rows
                       if row["match_id"] == VALIDATION_MATCH_ID]
    test_rows = [row for row in holdout_rows if row["match_id"] == TEST_MATCH_ID]
    if not validation_rows or not test_rows or len(validation_rows) + len(test_rows) != len(holdout_rows):
        raise ValueError("both named held-out matches are required")
    target_counts = {
        name: {field: int(sum(row["target_valid"][i] > 0 for row in rows))
               for i, field in enumerate(FIELDS)}
        for name, rows in (("train", train_rows), ("validation", validation_rows),
                           ("test", test_rows))
    }
    branch_count = 0
    if branches is not None:
        economy = json.loads(branches.read_text())
        if economy.get("full_match_simulator_ready") is not False or economy.get("synthetic_policy_labels_created") != 0:
            raise ValueError("economy scenes must remain outside policy training")
        if any(row.get("observed_branch_matches_video") is not True for row in economy["branches"]):
            raise ValueError("unverified economy scene")
        branch_count = len(economy["branches"])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = StateNet().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001)
    started_utc = time.time()
    first_epoch, best_score, best_metrics = 0, float("inf"), {}
    best_model = copy.deepcopy(model.state_dict())
    patience, stale = 15, 0
    if resume:
        saved = torch.load(output / "experimental-state-checkpoint.pt", map_location="cpu",
                           weights_only=False)
        if saved["dataset_sha256"] != source_digest:
            raise ValueError("dataset changed since checkpoint")
        model.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        first_epoch, best_score = saved["epoch"], saved["best_score"]
        best_metrics = saved["best_metrics"]
        best_model = saved["best_model"]
        stale = saved["stale_epochs"]
        started_utc = saved["started_utc"]
        random.setstate(saved["python_rng_state"])
        np.random.set_state(saved["numpy_rng_state"])
        torch.set_rng_state(saved["torch_rng_state"])
        if device.type == "cuda" and saved["cuda_rng_state"] is not None:
            torch.cuda.set_rng_state_all(saved["cuda_rng_state"])
        torch.save(best_model, output / "experimental-state-best.pt.tmp")
        os.replace(output / "experimental-state-best.pt.tmp",
                   output / "experimental-state-best.pt")
    else:
        atomic_checkpoint(output, model, optimizer, 0, best_score, best_metrics,
                          best_model, stale, source_digest, started_utc)
    train_loader = DataLoader(StateDataset(train_rows), batch_size=batch_size, shuffle=True,
                              num_workers=0)
    val_loader = DataLoader(StateDataset(validation_rows), batch_size=batch_size, shuffle=False,
                            num_workers=0)
    test_loader = DataLoader(StateDataset(test_rows), batch_size=batch_size, shuffle=False,
                             num_workers=0)
    deadline = float(os.environ.get("TFT_DEADLINE_UTC", time.time() + 36000))
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    for epoch in range(first_epoch + 1, max_epochs + 1):
        if stopped or time.time() >= deadline - 20:
            break
        model.train()
        losses = []
        for image, state, target, valid in train_loader:
            if stopped or time.time() >= deadline - 20:
                break
            optimizer.zero_grad(set_to_none=True)
            prediction = model(image.to(device), state.to(device))
            loss = masked_loss(prediction, target.to(device), valid.to(device))
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach().cpu()))
        metrics = evaluate(model, val_loader, device)
        observed = [metrics[k]["model_mae"] / scale for k, scale in
                    zip(FIELDS, SCALES) if metrics[k]["count"] > 0]
        score = float(np.mean(observed)) if observed else float("inf")
        if score + 1e-5 < best_score:
            best_score, best_metrics, stale = score, metrics, 0
            best_model = copy.deepcopy(model.state_dict())
            torch.save(best_model, output / "experimental-state-best.pt.tmp")
            os.replace(output / "experimental-state-best.pt.tmp", output / "experimental-state-best.pt")
        else:
            stale += 1
        atomic_checkpoint(output, model, optimizer, epoch, best_score, best_metrics,
                          best_model, stale, source_digest, started_utc)
        report = {"schema_version": 1, "task": "experimental_30s_visible_state_forecast",
                  "not_player_policy": True, "native_source_resolution": [1920, 1080],
                  "target_patch": index_facts.get("target_patch"),
                  "client_patch_verified": index_facts.get("client_patch_verified", False),
                  "network_input_resolution": [320, 180], "future_horizon_seconds": 30,
                  "held_out_source_vod": holdout_vod, "train_examples": len(train_rows),
                  "validation_match": VALIDATION_MATCH_ID,
                  "test_match": TEST_MATCH_ID,
                  "validation_examples": len(validation_rows),
                  "test_examples": len(test_rows), "epoch": epoch,
                  "weak_ocr_target_counts": target_counts,
                  "training_wall_seconds": round(time.time() - started_utc, 3),
                  "train_loss": float(np.mean(losses)) if losses else None,
                  "current_validation_metrics": metrics,
                  "best_validation_metrics": best_metrics,
                  "best_score": best_score, "simulator_policy_labels": 0,
                  "separate_validated_economy_scenes": branch_count}
        tmp = output / "report.json.tmp"
        tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, output / "report.json")
        print(json.dumps({"epoch": epoch, "train_loss": report["train_loss"],
                          "best_score": best_score, "stale_epochs": stale}), flush=True)
        if stale >= patience or stopped:
            break
    if not stopped:
        model.load_state_dict(best_model)
        report = json.loads((output / "report.json").read_text())
        report["final_test_metrics"] = evaluate(model, test_loader, device)
        report["training_wall_seconds"] = round(time.time() - started_utc, 3)
        temporary = output / "report.json.tmp"
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        os.replace(temporary, output / "report.json")
        (output / "complete.flag").write_text("experimental task completed\n")
    return json.loads((output / "report.json").read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--holdout-vod", default=DEFAULT_HOLDOUT_VOD)
    parser.add_argument("--max-epochs", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--branches", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    print(json.dumps(train(args.index, args.frames, args.output,
                           holdout_vod=args.holdout_vod,
                           max_epochs=args.max_epochs, batch_size=args.batch_size,
                           branches=args.branches,
                           resume=args.resume), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
