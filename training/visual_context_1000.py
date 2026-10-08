"""Build 1,000 visual triplets around an existing expert-moment queue.

The queue's timestamps originally came from speech segments. Selection here
does not use speech content, but is not yet independent video-time sampling.
Frames before/at/after each moment support visual review; no action is labeled.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import time

import numpy as np
from PIL import Image

from training.expert_video_review_frames import digest, frame, parse_source


def spaced(rows: list[dict], count: int) -> list[dict]:
    if count > len(rows):
        raise ValueError("not enough moments for visual sampling")
    rows = sorted(rows, key=lambda row: row["start"])
    return [rows[(index * len(rows) + len(rows) // 2) // count]
            for index in range(count)]


def select(moments: list[dict], total: int) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for row in moments:
        groups.setdefault(row["source_sha256"], []).append(row)
    quotas = {source: total * len(rows) // len(moments)
              for source, rows in groups.items()}
    remaining = total - sum(quotas.values())
    ranked = sorted(groups, key=lambda source: (total * len(groups[source]) % len(moments)), reverse=True)
    for source in ranked[:remaining]:
        quotas[source] += 1
    chosen = [row for source, rows in groups.items() for row in spaced(rows, quotas[source])]
    if len(chosen) != total or len({row["moment"] for row in chosen}) != total:
        raise ValueError("visual selection is not unique")
    return sorted(chosen, key=lambda row: (row["source_sha256"], row["start"]))


def build(moments: Path, center_frames: Path, output: Path,
          sources: dict[str, Path], *, total: int, workers: int,
          scene_probabilities: Path, scene_threshold: float,
          reuse_frames: list[Path] | None = None,
          exclude_sources: set[str] | None = None,
          hud_brightness_max: float | None = None) -> dict:
    if output.exists():
        raise ValueError("use a new output directory")
    if not 1 <= workers <= 8:
        raise ValueError("workers must be 1..8")
    candidates = [json.loads(line) for line in moments.open()]
    probabilities = np.load(scene_probabilities)
    if len(probabilities) != len(candidates) or not 0 < scene_threshold < 1:
        raise ValueError("scene probabilities must match the source queue")
    visible = [row for row, score in zip(candidates, probabilities)
               if float(score) >= scene_threshold
               and row["source_sha256"] not in (exclude_sources or set())]
    scene_candidates = len(visible)
    if hud_brightness_max is not None:
        if not 0 < hud_brightness_max < 1:
            raise ValueError("HUD brightness limit must be between 0 and 1")

        def game_hud_visible(row: dict) -> bool:
            path = center_frames / f"moment-{row['moment']:04d}.jpg"
            with Image.open(path) as image:
                image = image.convert("RGB")
                width, height = image.size
                region = image.crop((int(width * 350 / 960), 0,
                                     int(width * 625 / 960), int(height * 38 / 540)))
                pixels = np.asarray(region, dtype=np.float32) / 255
            return float((pixels.mean(axis=2) > 0.7).mean()) < hud_brightness_max

        visible = [row for row in visible if game_hud_visible(row)]
    rows = select(visible, total)
    print(f"Cenas selecionáveis: {len(visible)}/{scene_candidates} após exame do HUD; "
          f"amostra visual: {len(rows)}", flush=True)
    for source in {row["source_sha256"] for row in rows}:
        video = sources.get(source)
        if video is None or not video.is_file() or digest(video) != source:
            raise ValueError(f"missing or mismatched video: {source[:12]}")
        print(f"Vídeo de alto nível {source[:12]} verificado", flush=True)
    output.mkdir(parents=True)
    started = time.perf_counter()

    def extract(row: dict) -> dict:
        center = (row["start"] + row["end"]) / 2
        center_image = center_frames / f"moment-{row['moment']:04d}.jpg"
        if not center_image.is_file():
            raise FileNotFoundError(center_image)
        images = {"during": str(center_image)}
        for role, second in (("before", max(0.0, center - 5.0)),
                             ("after", center + 5.0)):
            target = output / f"moment-{row['moment']:04d}-{role}.jpg"
            cached = next((directory / target.name for directory in (reuse_frames or [])
                           if (directory / target.name).is_file()), None)
            if cached is not None and cached.is_file():
                os.link(cached, target)
            else:
                frame(sources[row["source_sha256"]], second, target)
            images[role] = str(target)
        return {"moment": row["moment"], "source_sha256": row["source_sha256"],
                "source_seconds": round(center, 2), "images": images,
                "speech_context": row.get("phrase_en", ""),
                "speech_is_action_label": False, "executed_action_label": None,
                "status": "visual_triplet_ready"}

    records = []
    print(f"Extraindo contexto visual de {total} momentos: antes, agora, depois.", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(extract, row): row["moment"] for row in rows}
        for future in as_completed(futures):
            try:
                records.append(future.result())
            except Exception as exc:
                records.append({"moment": futures[future], "status": "extraction_failed",
                                "error": str(exc), "executed_action_label": None})
            if len(records) % 25 == 0 or len(records) == total:
                print(f"CONTEXTO VISUAL {len(records)}/{total} | "
                      f"{(time.perf_counter()-started)/60:.1f} min", flush=True)
    records.sort(key=lambda row: row["moment"])
    with (output / "visual_triplets.jsonl").open("w", encoding="utf-8") as log:
        for row in records:
            log.write(json.dumps(row, ensure_ascii=False) + "\n")
    ready = sum(row["status"] == "visual_triplet_ready" for row in records)
    report = {"selected": total, "triplets_ready": ready, "failures": total-ready,
              "scene_candidates": scene_candidates, "hud_candidates": len(visible),
              "hud_brightness_max": hud_brightness_max,
              "scene_threshold": scene_threshold,
              "scene_gate_limit": "single held-out match; false positives and domain shift possible",
              "sampling": "speech_timestamp_pool_time_spaced_by_source_then_visual_scene_filter_without_speech_content",
              "executed_action_labels": 0, "elapsed_seconds": round(time.perf_counter()-started, 2)}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Concluído: {ready}/{total} sequências visuais", flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--moments", type=Path, required=True)
    parser.add_argument("--center-frames", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--total", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--scene-probabilities", type=Path, required=True)
    parser.add_argument("--scene-threshold", type=float, default=0.99)
    parser.add_argument("--reuse-frames", type=Path, action="append")
    parser.add_argument("--exclude-source", action="append", default=[])
    parser.add_argument("--hud-brightness-max", type=float)
    args = parser.parse_args()
    build(args.moments, args.center_frames, args.output,
          dict(parse_source(value) for value in args.source),
          total=args.total, workers=args.workers,
          scene_probabilities=args.scene_probabilities,
          scene_threshold=args.scene_threshold, reuse_frames=args.reuse_frames,
          exclude_sources=set(args.exclude_source),
          hud_brightness_max=args.hud_brightness_max)


if __name__ == "__main__":
    main()
