"""Create a resumable sparse HUD index from full-match 1080p frame samples.

OCR readings are weak observation labels. They are not actions, rewards, or
ground truth about hidden game state. Each 15-second frame stays linked to its
full source match and VOD so evaluation can hold out entire VODs.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

from PIL import Image

from training.index_full_match_states import (REGIONS, parse_fields,
                                              read_text, reconcile_gold_reads)
from scripts.prepare_tessdata_best import prepare as prepare_ocr_model


def observe(task: tuple[int, Path]) -> dict:
    number, path = task
    with Image.open(path) as image:
        if image.size != (1920, 1080):
            raise ValueError(f"expected 1920x1080: {path}")
        gold_views = {
            "gray_psm13": read_text(image, REGIONS["gold"], "0123456789",
                                    psm=13, contrast=1),
            "gray_psm7": read_text(image, REGIONS["gold"], "0123456789", contrast=1),
            "contrast_psm7": read_text(image, REGIONS["gold"], "0123456789"),
        }
        gold, gold_status = reconcile_gold_reads(gold_views)
        raw = {"stage": read_text(image, REGIONS["stage"], "0123456789-"),
               "gold": gold_views["gray_psm13"],
               "level": read_text(image, REGIONS["level"], "0123456789")}
    parsed = parse_fields(raw)
    parsed["gold"] = gold
    return {"frame_number": number, "frame": path.name,
            "clip_second": (number - 1) * 15,
            "raw_ocr": raw, "gold_ocr_views": gold_views,
            "gold_review_status": gold_status, "parsed": parsed,
            "action_label": None, "outcome_label": None}


def build(corpus: Path, frames_root: Path, output: Path, *, workers: int = 3) -> dict:
    prepare_ocr_model()
    manifest = json.loads((corpus / "manifest.json").read_text())
    if manifest["native_resolution"] != [1920, 1080]:
        raise ValueError("native 1080p corpus required")
    all_matches = []
    for match in manifest["matches"]:
        folder = frames_root / match["match_id"]
        frames = sorted(folder.glob("frame-*.jpg"))
        expected = int(match["video_duration_seconds"] // 15)
        if not expected <= len(frames) <= expected + 1:
            raise ValueError(f"incomplete 15-second frame sample: {folder} ({len(frames)} vs {expected})")
        numbers = [int(path.stem.split("-")[-1]) for path in frames]
        if numbers != list(range(1, len(frames) + 1)):
            raise ValueError(f"non-contiguous frames: {folder}")
        partial = output.parent / f"{match['match_id']}.hud-15s.jsonl"
        existing = [json.loads(line) for line in partial.read_text().splitlines()] if partial.exists() else []
        if any(row["frame_number"] != i + 1 for i, row in enumerate(existing)):
            raise ValueError(f"invalid resume index: {partial}")
        if len(existing) > len(frames):
            raise ValueError(f"resume index exceeds frames: {partial}")
        tasks = list(zip(numbers[len(existing):], frames[len(existing):]))
        print(f"index {match['match_id']}: {len(existing)}/{len(frames)} already", flush=True)
        with ProcessPoolExecutor(max_workers=workers) as pool, partial.open("a") as stream:
            for row in pool.map(observe, tasks, chunksize=4):
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                existing.append(row)
                if len(existing) % 30 == 0:
                    print(f"indexed {match['match_id']}: {len(existing)}/{len(frames)}", flush=True)
        all_matches.append({"match_id": match["match_id"],
                            "source_vod_id": match["match_id"].split("-")[1],
                            "source_url": match["source_url"],
                            "native_resolution": [1920, 1080],
                            "observations": existing})
    result = {"schema_version": 1, "kind": "weak_ocr_1080p_full_match_state_index",
              "interval_seconds": 15, "native_resolution": [1920, 1080],
              "target_patch": manifest["target_patch"],
              "client_patch_verified": manifest["client_patch_verified"],
              "matches": all_matches, "action_labels": 0,
              "outcome_labels": 0, "simulated_policy_labels": 0}
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False) + "\n")
    temporary.replace(output)
    return {"matches": len(all_matches),
            "observations": sum(len(m["observations"]) for m in all_matches)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--frames-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    print(json.dumps(build(args.corpus, args.frames_root, args.output,
                           workers=args.workers)), flush=True)


if __name__ == "__main__":
    main()
