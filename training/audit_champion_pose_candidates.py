#!/usr/bin/env python3
"""Audit reset-era champion candidates without promoting any crop to training.

Image similarity only flags possible repeated views. It cannot establish that
two crops show the same pose, or that either crop has a correct identity.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image


@lru_cache(maxsize=None)
def probe_resolution(path: str) -> tuple[int, int] | None:
    if not path or not Path(path).is_file():
        return None
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0", path,
        ], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None
    if result.returncode:
        return None
    try:
        width, height = result.stdout.strip().split(",", maxsplit=1)
        return int(width), int(height)
    except ValueError:
        return None


def source_tier(row: dict) -> tuple[str, str]:
    resolution = row.get("source_resolution")
    if not resolution:
        resolution = probe_resolution(row.get("source_video_local", ""))
        provenance = "ffprobe_source_video" if resolution else "unknown"
    else:
        provenance = "roster_manifest"
    if not resolution:
        return "unknown", provenance
    width, height = resolution
    if width >= 3840 and height >= 2160:
        return "4k", provenance
    if width >= 1920 and height >= 1080:
        return "1080p_or_higher", provenance
    return "below_1080p", provenance


def image_metrics(path: Path) -> dict:
    with Image.open(path) as opened:
        gray = opened.convert("L")
        width, height = gray.size
        resized = np.asarray(gray.resize((9, 8), Image.Resampling.BOX), dtype=np.uint8)
        pixels = np.asarray(gray, dtype=np.float32)
    center = pixels[1:-1, 1:-1]
    laplacian = (pixels[:-2, 1:-1] + pixels[2:, 1:-1]
                 + pixels[1:-1, :-2] + pixels[1:-1, 2:] - 4 * center)
    dhash = (resized[:, 1:] > resized[:, :-1]).reshape(-1)
    bits = sum(int(bit) << position for position, bit in enumerate(dhash))
    return {
        "crop_width": width,
        "crop_height": height,
        "laplacian_variance": round(float(laplacian.var()), 2),
        "dhash64": f"{bits:016x}",
    }


def audit(roster: dict, shop: dict) -> dict:
    user_rows = [row for row in roster["records"]
                 if row.get("review_status") == "user_confirmed_candidate"]
    classes = defaultdict(list)
    for row in user_rows:
        crop = Path(row["natural_crop"])
        metrics = image_metrics(crop)
        tier, tier_origin = source_tier(row)
        classes[row["champion"]].append({
            "review_id": row["review_id"],
            "crop": str(crop),
            "source_video": row.get("source_video_local"),
            "source_second": row.get("source_second"),
            "source_tier": tier,
            "source_tier_origin": tier_origin,
            "zone": row.get("zone"),
            **metrics,
        })

    class_report = {}
    for entry in shop["rows"]:
        classes.setdefault(entry["name_pt_br"], [])
    for champion, rows in sorted(classes.items()):
        four_k = [row for row in rows if row["source_tier"] == "4k"]
        # Near-time source repetitions and visual lookalikes are review flags,
        # never automated proof of duplicate poses.
        possible_repeats = []
        for index, left in enumerate(four_k):
            for right in four_k[index + 1:]:
                same_video = left["source_video"] == right["source_video"]
                seconds_apart = (abs(float(left["source_second"]) - float(right["source_second"]))
                                 if left["source_second"] is not None and right["source_second"] is not None
                                 else None)
                hash_distance = (int(left["dhash64"], 16) ^ int(right["dhash64"], 16)).bit_count()
                if (same_video and seconds_apart is not None and seconds_apart <= 2) or hash_distance <= 5:
                    possible_repeats.append({
                        "ids": [left["review_id"], right["review_id"]],
                        "same_video": same_video,
                        "seconds_apart": seconds_apart,
                        "dhash_distance": hash_distance,
                    })
        class_report[champion] = {
            "user_confirmed": len(rows),
            "from_4k": len(four_k),
            "four_k_source_videos": len({row["source_video"] for row in four_k}),
            "four_k_zone_verified": sum(row["zone"] in {"board", "bench", "enemy_board", "enemy_bench", "tabuleiro", "banco"} for row in four_k),
            "possible_repeat_pairs": possible_repeats,
            "four_k_candidates": four_k,
            "all_candidates": rows,
            "missing_to_five_4k_crops": max(0, 5 - len(four_k)),
            "five_distinct_poses_approved": False,
        }
    return {
        "schema_version": 1,
        "scope": "user-confirmed reset-era crop review only",
        "metric_warning": "Laplacian variance is a within-corpus focus hint; dHash pairs are review hints, not pose or identity decisions.",
        "training_eligibility_changed": False,
        "totals": {
            "user_confirmed_crops": len(user_rows),
            "roster_classes": len(class_report),
            "classes_with_user_confirmation": sum(bool(rows) for rows in classes.values()),
            "confirmed_4k_crops": sum(item["from_4k"] for item in class_report.values()),
            "classes_with_five_4k_crops_before_pose_review": sum(item["from_4k"] >= 5 for item in class_report.values()),
            "classes_with_five_approved_distinct_poses": 0,
        },
        "classes": class_report,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--shop", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(json.loads(args.roster.read_text(encoding="utf-8")),
                   json.loads(args.shop.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["totals"], ensure_ascii=False))


if __name__ == "__main__":
    main()
