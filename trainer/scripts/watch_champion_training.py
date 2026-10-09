"""Show the actual champion-corpus and training state in an Ubuntu terminal."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def catalog_ids(repository: Path) -> set[str]:
    catalogs = sorted(
        repository.glob("knowledge/riot-ddragon/*/pt_BR/TFTSet18/*/champions.json")
    )
    if not catalogs:
        return set()
    data = read_json(catalogs[-1])
    return {
        row["id"]
        for row in data.get("entries", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }


def verified_poses(path: Path, catalog: set[str], allowed_sources: set[str]) -> tuple[int, dict[str, set[str]]]:
    poses: dict[str, set[str]] = defaultdict(set)
    seen_crops: set[str] = set()
    accepted = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0, poses
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("reviewer_verified") is not True:
            continue
        champion = row.get("champion_id")
        source = row.get("source_id")
        pose = row.get("pose_id")
        crop_digest = row.get("crop_pixel_sha256")
        if (
            not isinstance(champion, str)
            or champion not in catalog
            or not isinstance(source, str)
            or source not in allowed_sources
            or not isinstance(pose, str)
            or not pose
            or not isinstance(crop_digest, str)
            or len(crop_digest) != 64
            or any(c not in "0123456789abcdef" for c in crop_digest)
            or crop_digest in seen_crops
        ):
            continue
        seen_crops.add(crop_digest)
        accepted += 1
        poses[champion].add(pose)
    return accepted, poses


def render(corpus: Path, catalog: set[str]) -> str:
    summary = read_json(corpus / "meta/collection-summary.json")
    training_sources = {
        row["source_id"] for row in summary.get("sources", [])
        if isinstance(row, dict) and row.get("partition") == "train"
        and isinstance(row.get("source_id"), str)
    }
    labels, poses = verified_poses(corpus / "meta/verified-labels.jsonl", catalog, training_sources)
    covered = sum(len(poses.get(champion, set())) >= 10 for champion in catalog)
    target = len(catalog)
    lines = [
        "TFT  •  TREINO VISUAL DE CAMPEÕES",
        datetime.now().strftime("Atualizado: %d/%m/%Y %H:%M:%S"),
        "=" * 62,
        f"Vídeos novos verificados: {summary.get('media_files', 0)}",
        f"Fontes antigas excluídas: {summary.get('excluded_prior_source_ids', 0)}",
        f"Recortes candidatos: {summary.get('crop_proposals_total', 0)}",
        f"Rótulos revisados: {labels}",
        f"Campeões com 10 poses distintas: {covered}/{target}",
        "",
        "COLETA POR FONTE",
    ]
    for source in summary.get("sources", []):
        if not isinstance(source, dict):
            continue
        lines.append(
            f"  {source.get('partition', '?'):<9} "
            f"{source.get('source_id', '?'):<26} "
            f"{source.get('sampled_frames', 0):>4} quadros  "
            f"{source.get('crop_proposals', 0):>5} recortes"
        )
    lines.extend(["", "TREINAMENTO"])
    progress = read_json(corpus / "meta/training-status.json")
    if progress:
        lines.append(f"  Estado: {progress.get('status', 'desconhecido')}")
        for key, title in (("extracted", "Recortes extraídos"), ("total", "Total nesta etapa"), ("epoch", "Época"), ("loss", "Perda"), ("validation_retrieval", "Recuperação visual isolada"), ("validation_cosine", "Similaridade de duas vistas")):
            if key in progress:
                lines.append(f"  {title}: {progress[key]}")
    else:
        lines.append("  Aguardando rótulos verificados; nenhum treino novo iniciado.")
    lines.extend(["", "Últimas mensagens do treino:"])
    try:
        recent = (corpus / "meta/training.log").read_text(encoding="utf-8").splitlines()[-5:]
    except OSError:
        recent = []
    lines.extend(f"  {line}" for line in recent)
    if not recent:
        lines.append("  Nenhuma ainda.")
    lines.extend(["", "Ctrl+C fecha esta visualização."])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval deve ser positivo")
    repository = Path(__file__).resolve().parents[2]
    catalog = catalog_ids(repository)
    if not catalog:
        parser.error("catálogo TFT Set 18 não encontrado")
    try:
        while True:
            if not args.once:
                sys.stdout.write("\033[2J\033[H")
            print(render(args.corpus, catalog), flush=True)
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
