"""Rank expert VOD windows where a game decision may be visible.

This is a review queue, not an action detector. A stable stage HUD and a
visible shop on both sides reduce camera cuts; visual deltas remain unlabeled.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image


def roi(path: str, box: tuple[int, int, int, int]) -> np.ndarray:
    with Image.open(path) as image:
        image = image.convert("L").resize((960, 540), Image.Resampling.BILINEAR)
        return np.asarray(image.crop(box), dtype=np.float32) / 255.0


def edge_strength(pixels: np.ndarray) -> float:
    return float((np.abs(np.diff(pixels, axis=0)).mean() +
                  np.abs(np.diff(pixels, axis=1)).mean()) / 2)


def mine(triplets: Path, changes: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("use a new output directory")
    rows = [json.loads(line) for line in triplets.open()]
    deltas = {row["moment"]: row for row in (json.loads(line) for line in changes.open())}
    if len(rows) != 1000 or len(deltas) != len(rows):
        raise ValueError("expected 1000 visual triplets and change records")
    candidates = []
    for row in rows:
        images = row["images"]
        stage_before = roi(images["before"], (380, 0, 430, 28))
        stage_after = roi(images["after"], (380, 0, 430, 28))
        stage_difference = float(np.abs(stage_before - stage_after).mean())
        shop_before = edge_strength(roi(images["before"], (285, 465, 775, 537)))
        shop_after = edge_strength(roi(images["after"], (285, 465, 775, 537)))
        change = deltas[row["moment"]]["region_change"]
        if (stage_difference >= 0.04 or min(shop_before, shop_after) <= 0.025 or
                change["shop"] <= 0.08):
            continue
        candidates.append({
            "moment": row["moment"], "source_sha256": row["source_sha256"],
            "source_seconds": row["source_seconds"], "images": images,
            "stage_difference": round(stage_difference, 4),
            "shop_edges_before_after": [round(shop_before, 4), round(shop_after, 4)],
            "region_change": change, "executed_action_label": None,
            "review_status": "visual_change_needs_manual_action_review",
        })
    candidates.sort(key=lambda row: row["region_change"]["shop"], reverse=True)
    output.mkdir(parents=True)
    with (output / "action_review_queue.jsonl").open("w") as log:
        for row in candidates:
            log.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {
        "input_triplets": len(rows), "review_candidates": len(candidates),
        "executed_action_labels": 0,
        "heuristic": "stable_stage_hud_and_shop_visible_before_after_with_shop_embedding_change",
        "meaning": "review priority only; visual change can be camera, cursor, purchase, roll, or other UI",
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Janela visual para revisão: {len(candidates)}/1000; ações confirmadas: 0", flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--triplets", required=True, type=Path)
    parser.add_argument("--changes", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    mine(args.triplets, args.changes, args.output)


if __name__ == "__main__":
    main()
