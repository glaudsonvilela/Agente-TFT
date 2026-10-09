"""Train an unlabeled visual projector from newly collected TFT unit crops.

This does not create champion identity labels or promote a model into the HUD.
The held-out source is never used for fitting or model selection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
from PIL import Image, ImageEnhance, ImageFilter
from torch import nn
from torch.nn import functional as F


def write_status(meta: Path, **fields: object) -> None:
    path = meta / "training-status.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(fields, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def log(meta: Path, message: str) -> None:
    line = time.strftime("%H:%M:%S") + "  " + message
    with (meta / "training.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(line, flush=True)


def load_crops(corpus: Path) -> tuple[list[Path], list[Path]]:
    train: dict[str, Path] = {}
    test: dict[str, Path] = {}
    for file in sorted(corpus.glob("collection-*/observations.jsonl")):
        for line in file.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            source_id = row.get("source_id")
            partition = row.get("partition")
            if source_id not in {"youtube:-Xt_mZgsfp4", "twitch:2893526719", "youtube:xl99CWEZG_w"}:
                raise ValueError(f"unexpected source: {source_id}")
            target = test if partition == "evaluation_unlabeled" else train
            if partition not in {"training_pool_unlabeled", "evaluation_unlabeled"}:
                raise ValueError(f"unexpected partition: {partition}")
            for unit in row.get("units", []):
                digest = unit["pixel_sha256"]
                crop = (file.parent / unit["crop"]).resolve()
                if not crop.is_relative_to(file.parent.resolve()) or not crop.is_file():
                    raise ValueError(f"missing or escaping crop: {crop}")
                target.setdefault(digest, crop)
    if train.keys() & test.keys():
        raise ValueError("pixel-identical crops cross training/evaluation sources")
    if not train or not test:
        raise ValueError("training and evaluation crops are required")
    return list(train.values()), list(test.values())


def model_session(path: Path) -> tuple[ort.InferenceSession, int]:
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
    side = session.get_inputs()[0].shape[-1]
    return session, side


def image_tensor(image: Image.Image, side: int) -> np.ndarray:
    # Like the Rust runtime, encoders receive RGB CHW in [0, 1].
    return np.asarray(image.resize((side, side), Image.Resampling.BILINEAR), dtype=np.float32).transpose(2, 0, 1) / 255.0


def augmentation(image: Image.Image, seed: int) -> Image.Image:
    rng = random.Random(seed)
    image = ImageEnhance.Brightness(image).enhance(rng.uniform(0.82, 1.18))
    image = ImageEnhance.Contrast(image).enhance(rng.uniform(0.85, 1.15))
    if rng.random() < 0.35:
        image = image.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.2, 0.8)))
    return image


def feature_cache(corpus: Path, files: list[Path], name: str, sessions: list[tuple[ort.InferenceSession, int]], meta: Path) -> np.ndarray:
    cache = corpus / "features" / f"{name}-dino-mobile-two-views.npz"
    cache.parent.mkdir(exist_ok=True)
    manifest_hash = hashlib.sha256()
    for file in files:
        manifest_hash.update(str(file).encode())
        manifest_hash.update(hashlib.sha256(file.read_bytes()).digest())
    manifest = manifest_hash.hexdigest()
    if cache.is_file():
        with np.load(cache) as data:
            if str(data["manifest"]) == manifest:
                result = data["features"].copy()
                log(meta, f"Vetores {name} recuperados do cache: {len(result)} recortes")
                return result
    results: list[np.ndarray] = []
    batch_size = 16
    for start in range(0, len(files), batch_size):
        group = files[start : start + batch_size]
        images = []
        for path in group:
            with Image.open(path) as opened:
                image = opened.convert("RGB")
                if image.size != (128, 144):
                    raise ValueError(f"unexpected crop dimensions: {path}: {image.size}")
                if hashlib.sha256(image.tobytes()).hexdigest() != path.stem:
                    raise ValueError(f"crop pixels do not match recorded digest: {path}")
                images.append(image)
        views = [images, [augmentation(image, int(hashlib.sha256(str(path).encode()).hexdigest()[:12], 16)) for image, path in zip(images, group)]]
        per_view: list[np.ndarray] = []
        for view in views:
            vectors = []
            for session, side in sessions:
                batch = np.stack([image_tensor(image, side) for image in view])
                output = session.run(["embeddings"], {session.get_inputs()[0].name: batch})[0]
                output = output.astype(np.float32)
                output /= np.maximum(np.linalg.norm(output, axis=1, keepdims=True), 1e-8)
                vectors.append(output)
            per_view.append(np.concatenate(vectors, axis=1))
        results.append(np.stack(per_view, axis=1))
        done = min(start + len(group), len(files))
        if done == len(files) or done % 160 == 0:
            log(meta, f"Extração {name}: {done}/{len(files)} recortes | DINO + MobileNet")
            write_status(meta, status=f"Extraindo vetores visuais ({name})", phase="feature_extraction", extracted=done, total=len(files))
    result = np.concatenate(results, axis=0)
    np.savez_compressed(cache, features=result, manifest=manifest)
    return result


class Projector(nn.Module):
    def __init__(self, dimension: int) -> None:
        super().__init__()
        self.net = nn.Sequential(nn.Linear(dimension, 512), nn.ReLU(), nn.Linear(512, 256))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.normalize(self.net(x), dim=-1)


def contrastive_loss(model: Projector, x: torch.Tensor, temperature: float = 0.2) -> torch.Tensor:
    batch = x.shape[0]
    z = model(x.reshape(batch * 2, -1))
    logits = z @ z.T / temperature
    logits.fill_diagonal_(-1e4)
    # Positive index for each interleaved view.
    target = torch.arange(batch * 2) ^ 1
    return F.cross_entropy(logits, target)


@torch.no_grad()
def paired_retrieval(model: Projector, data: torch.Tensor) -> tuple[float, float]:
    model.eval()
    z = model(data.reshape(-1, data.shape[-1])).reshape(data.shape[0], 2, -1)
    similarities = z[:, 0] @ z[:, 1].T
    hits = (similarities.argmax(dim=1) == torch.arange(len(data))).float().mean().item()
    cosine = similarities.diag().mean().item()
    return hits, cosine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--dino", type=Path, required=True)
    parser.add_argument("--mobile", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=20)
    args = parser.parse_args()
    if args.epochs < 1:
        parser.error("epochs must be positive")
    torch.set_num_threads(2)
    np.random.seed(17)
    torch.manual_seed(17)
    corpus = args.corpus.resolve()
    meta = corpus / "meta"
    train_files, eval_files = load_crops(corpus)
    log(meta, f"Treino visual novo: {len(train_files)} recortes de treino; {len(eval_files)} de avaliação isolada")
    log(meta, "Objetivo: aproximar duas vistas do mesmo recorte; não há rótulos de identidade")
    write_status(meta, status="Iniciando extração visual", phase="feature_extraction", train_crops=len(train_files), evaluation_crops=len(eval_files))
    sessions = [model_session(args.dino), model_session(args.mobile)]
    train = feature_cache(corpus, train_files, "training", sessions, meta)
    evaluation = feature_cache(corpus, eval_files, "evaluation", sessions, meta)
    # Frozen generic encoders; only the new projector is optimized.
    train_tensor = torch.from_numpy(train)
    eval_tensor = torch.from_numpy(evaluation)
    model = Projector(train.shape[-1])
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.0004, weight_decay=0.0001)
    baseline_hits, baseline_cosine = paired_retrieval(model, eval_tensor)
    log(meta, f"Antes do treino | recuperação da mesma imagem: {baseline_hits:.3f}; cosseno: {baseline_cosine:.3f}")
    best_loss = float("inf")
    for epoch in range(1, args.epochs + 1):
        model.train()
        generator = torch.Generator().manual_seed(17 + epoch)
        permutation = torch.randperm(len(train_tensor), generator=generator)
        losses = []
        for indices in permutation.split(64):
            if len(indices) < 2:
                continue
            optimizer.zero_grad(set_to_none=True)
            loss = contrastive_loss(model, train_tensor[indices])
            loss.backward()
            optimizer.step()
            losses.append(loss.item())
        mean_loss = float(np.mean(losses))
        hits, cosine = paired_retrieval(model, eval_tensor)
        log(meta, f"ÉPOCA {epoch:02d}/{args.epochs} | perda {mean_loss:.4f} | recuperação isolada {hits:.3f} | cosseno {cosine:.3f}")
        write_status(meta, status="Treinando representação visual sem nomes", phase="training", epoch=f"{epoch}/{args.epochs}", loss=round(mean_loss, 4), validation_retrieval=round(hits, 4), validation_cosine=round(cosine, 4), train_crops=len(train_files), evaluation_crops=len(eval_files))
        if mean_loss < best_loss:
            best_loss = mean_loss
            torch.save({"state_dict": model.state_dict(), "input_dimension": train.shape[-1], "output_dimension": 256, "training_source": "fresh_champion_corpus_20261008", "objective": "unlabeled_two_view_contrastive"}, corpus / "features" / "unlabeled-projector.pt")
    report = {"objective": "unlabeled_two_view_contrastive", "evaluation_pair_type": "same_crop_photometric_augment", "verified_cross_pose_pairs": 0, "champion_identity_labels": 0, "champion_accuracy": None, "identity_conclusion": "inconclusive", "train_crops": len(train_files), "evaluation_crops": len(eval_files), "epochs": args.epochs, "baseline_retrieval": baseline_hits, "final_retrieval": hits, "baseline_cosine": baseline_cosine, "final_cosine": cosine, "final_loss": mean_loss, "model_promoted_to_hud": False}
    (meta / "training-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_status(meta, status="Experimento concluído; identidade inconclusiva", phase="complete", epoch=f"{args.epochs}/{args.epochs}", loss=round(mean_loss, 4), validation_retrieval=round(hits, 4), validation_cosine=round(cosine, 4), train_crops=len(train_files), evaluation_crops=len(eval_files))
    if hits <= baseline_hits + 0.01:
        write_status(meta, status="Experimento inconclusivo para reconhecer campeões", phase="complete", epoch=f"{args.epochs}/{args.epochs}", loss=round(mean_loss, 4), validation_retrieval=round(hits, 4), baseline_retrieval=round(baseline_hits, 4), train_crops=len(train_files), evaluation_crops=len(eval_files))
        log(meta, "Recuperação de duas versões da mesma imagem sem ganho. Identidade de campeões não foi avaliada.")
    else:
        log(meta, "Treino concluído. Modelo sem rótulos salvo no SSD; não promovido ao HUD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
