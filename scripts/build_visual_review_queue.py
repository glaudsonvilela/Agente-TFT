#!/usr/bin/env python3
"""Rank unlabeled unit crops and item-context frames for later review.

The queue is evidence only. Neither model guesses nor visual novelty become
training labels. Original frame indexes refer to the reconstructed 0.5 fps
video, whose frames follow the capture manifest in order.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from PIL import Image


EVENT_PRIORITY = {
    "shop_change": 3,
    "bench_or_item_change": 3,
    "board_change": 2,
    "periodic": 1,
    "unspecified": 1,
}


def fingerprint(path: Path) -> int:
    with Image.open(path) as image:
        gray = image.convert("L").resize((9, 8), Image.Resampling.BILINEAR)
        pixels = gray.tobytes()
    return sum((pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x)
               for y in range(8) for x in range(8))


def build_queue(capture: dict, collection: Path, max_units: int = 64,
                max_item_contexts: int = 32) -> dict:
    frames = capture["frames"]
    observations = collection / "observations.jsonl"
    units: list[dict] = []
    item_contexts: list[dict] = []
    seen_pixels: set[str] = set()
    for raw in observations.read_text(encoding="utf-8").splitlines():
        observation = json.loads(raw)
        index = observation.get("frame_index")
        if not isinstance(index, int) or not 0 <= index < len(frames):
            continue
        frame = frames[index]
        event = frame.get("capture_event") or "unspecified"
        frame_path = collection / str(observation.get("review_frame") or "")
        if not frame_path.is_file():
            continue
        context = {
            "frame_index": index,
            "frame_id": frame.get("frame_id"),
            "source_ms": frame.get("source_ms"),
            "capture_event": event,
            "review_frame": str(frame_path.resolve()),
            "ground_truth": False,
            "training_label": None,
        }
        if event == "bench_or_item_change":
            item_contexts.append({**context, "kind": "item_context_unlocalized"})
        for unit in observation.get("units") or []:
            pixel_sha = unit.get("pixel_sha256")
            crop = collection / str(unit.get("crop") or "")
            if not isinstance(pixel_sha, str) or pixel_sha in seen_pixels or not crop.is_file():
                continue
            seen_pixels.add(pixel_sha)
            candidates = unit.get("candidates") or []
            margin = None
            if len(candidates) >= 2:
                scores = [candidate.get("score", candidate.get("confidence"))
                          for candidate in candidates[:2]]
                if all(isinstance(score, (int, float)) for score in scores):
                    margin = abs(scores[0] - scores[1])
            units.append({**context, "kind": "unit_crop", "crop": str(crop.resolve()),
                          "pixel_sha256": pixel_sha, "fingerprint": fingerprint(crop),
                          "prediction_margin": margin})

    selected: list[dict] = []
    signatures: list[int] = []
    time_buckets: dict[int, int] = {}
    while units and len(selected) < max_units:
        def priority(row):
            bucket = int(float(row["source_ms"] or 0) // 10000)
            if time_buckets.get(bucket, 0) >= 2:
                return -1
            diversity = min((row["fingerprint"] ^ prior).bit_count()
                            for prior in signatures) if signatures else 64
            uncertainty = (1 - min(1.0, row["prediction_margin"])) if row["prediction_margin"] is not None else 0
            return EVENT_PRIORITY.get(row["capture_event"], 1) * 100 + diversity + uncertainty * 20

        best = max(units, key=priority)
        if priority(best) < 0:
            break
        units.remove(best)
        bucket = int(float(best["source_ms"] or 0) // 10000)
        time_buckets[bucket] = time_buckets.get(bucket, 0) + 1
        signatures.append(best["fingerprint"])
        selected.append(best)

    # Spread context frames across the match. These are localization tasks,
    # not item labels or confirmed item detections.
    item_contexts.sort(key=lambda row: (row["source_ms"], row["frame_index"]))
    if len(item_contexts) > max_item_contexts:
        step = len(item_contexts) / max_item_contexts
        item_contexts = [item_contexts[int(i * step)] for i in range(max_item_contexts)]
    for row in selected:
        row["fingerprint"] = f"{row['fingerprint']:016x}"
    return {
        "schema_version": 1,
        "policy": "visual_active_review_unlabeled_v1",
        "session_id": capture.get("session_id"),
        "collection_root": str(collection.resolve()),
        "unit_crops": selected,
        "item_contexts": item_contexts,
        "counts": {"unique_unit_candidates": len(seen_pixels),
                   "unit_review": len(selected), "item_context_review": len(item_contexts)},
        "labels_created": 0,
        "model_predictions_used_as_labels": False,
        "training_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-manifest", type=Path, required=True)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    capture = json.loads(args.capture_manifest.read_text(encoding="utf-8"))
    queue = build_queue(capture, args.collection)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(queue["counts"], ensure_ascii=False))


if __name__ == "__main__":
    main()
