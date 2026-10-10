#!/usr/bin/env python3
"""Follow user-reviewed TFT unit crops by health bar; never create training labels.

Inputs are original decoded 3840x2160 frames named ``<video>-<second>.jpg``.
Every propagated crop remains a review candidate. A separate, explicit review
must decide identity, crop quality, and whether the pose is genuinely new.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.optimize import linear_sum_assignment


PREVIEW_SIZE = (2048, 1152)


def preview_box(row: dict) -> list[int]:
    if "box_preview_2048" in row:
        return row["box_preview_2048"]
    if row.get("source_resolution") == [3840, 2160] and "box_source_3840" in row:
        box = row["box_source_3840"]
        return [round(value * (PREVIEW_SIZE[0] / 3840 if index % 2 == 0
                               else PREVIEW_SIZE[1] / 2160))
                for index, value in enumerate(box)]
    raise ValueError(f"Review {row.get('id', '?')} has no supported 4K crop box")


def health_bars(image: Image.Image) -> list[tuple[int, int, int, int]]:
    rgb = np.asarray(image.resize(PREVIEW_SIZE).convert("RGB"), dtype=np.int16)
    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    mask = ((green > 140) & (green * 10 > red * 14)
            & (green * 10 > blue * 13) & (red < 150) & (blue < 170))
    mask[:250] = False
    mask[900:] = False
    mask[:, :300] = False
    mask[:, 1650:] = False
    mask = ndimage.binary_opening(mask, structure=np.ones((2, 4), dtype=bool))
    labels, _ = ndimage.label(mask)
    found = []
    for component in ndimage.find_objects(labels):
        if component is None:
            continue
        ys, xs = component
        x, y = xs.start, ys.start
        width, height = xs.stop - x, ys.stop - y
        if 28 <= width <= 160 and 3 <= height <= 24 and width > height * 4:
            found.append((x, y, width, height))
    return sorted(found, key=lambda bar: (bar[1], bar[0]))


def center(bar: tuple[int, int, int, int]) -> tuple[float, float]:
    x, y, width, height = bar
    return x + width / 2, y + height / 2


def seed_bar(box: list[int], bars: list[tuple[int, int, int, int]]):
    x0, y0, x1, y1 = box
    matching = [bar for bar in bars if x0 <= center(bar)[0] <= x1
                and y0 <= center(bar)[1] <= y1]
    if len(matching) == 1:
        return matching[0]
    # Item icons can split one full bar into a short fragment at a crop edge.
    # Keep the full bar only when it clearly dominates; two real bars are mixed.
    matching.sort(key=lambda bar: bar[2], reverse=True)
    if len(matching) == 2 and matching[0][2] >= 60 \
            and matching[1][2] < matching[0][2] * .7:
        return matching[0]
    return None


def match_bars(previous: list[tuple[int, int, int, int]],
               current: list[tuple[int, int, int, int]],
               maximum_pixels: float = 50) -> dict[int, int]:
    if not previous or not current:
        return {}
    old = np.asarray([center(bar) for bar in previous])
    new = np.asarray([center(bar) for bar in current])
    distances = np.linalg.norm(old[:, None, :] - new[None, :, :], axis=2)
    old_indices, new_indices = linear_sum_assignment(distances)
    return {int(a): int(b) for a, b in zip(old_indices, new_indices)
            if distances[a, b] <= maximum_pixels}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-manifest", type=Path, required=True)
    parser.add_argument("--frames", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    manifest = json.loads(args.review_manifest.read_text())
    if manifest.get("model_predictions_used_as_labels") is not False:
        raise ValueError("Source review is missing its no-model-label guarantee")
    if not args.frames or len(args.frames) < 2:
        raise ValueError("Provide the seed frame and at least one later frame")
    if len({path.parent for path in args.frames}) != 1:
        raise ValueError("Frames must come from one original-video extraction")

    frames = []
    for path in args.frames:
        with Image.open(path) as image:
            if image.size != (3840, 2160):
                raise ValueError(f"Not an original 4K frame: {path}")
            bars = health_bars(image)
        frames.append({"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
                       "bars": bars})

    seeds = []
    for row in manifest["records"]:
        if row.get("review_status") != "user_confirmed_candidate":
            continue
        if not str(row.get("identity_confirmed_by", "")).startswith("user_"):
            continue
        box = preview_box(row)
        bar = seed_bar(box, frames[0]["bars"])
        if bar is None:
            continue
        seeds.append({"seed_id": row["id"], "identity_suggestion": row["identity"],
                      "identity_origin": row["identity_confirmed_by"],
                      "current_box_preview_2048": box,
                      "bar": bar, "last_frame": 0})

    tracks = []
    for index in range(1, len(frames)):
        previous = frames[index - 1]["bars"]
        current = frames[index]["bars"]
        assignments = match_bars(previous, current)
        for seed in seeds:
            if seed["last_frame"] != index - 1:
                continue
            try:
                old_index = previous.index(seed["bar"])
            except ValueError:
                continue
            if old_index not in assignments:
                continue
            new_bar = current[assignments[old_index]]
            old_cx, old_cy = center(seed["bar"])
            new_cx, new_cy = center(new_bar)
            dx, dy = round(new_cx - old_cx), round(new_cy - old_cy)
            box = [value + (dx if position % 2 == 0 else dy)
                   for position, value in enumerate(seed["current_box_preview_2048"])]
            tracks.append({"seed_id": seed["seed_id"],
                           "identity_suggestion": seed["identity_suggestion"],
                           "identity_origin": seed["identity_origin"],
                           "frame": frames[index]["path"],
                           "bar_preview_2048": new_bar, "box_preview_2048": box,
                           "review_status": "temporal_transfer_pending_visual_review",
                           "may_train": False})
            seed["bar"] = new_bar
            seed["current_box_preview_2048"] = box
            seed["last_frame"] = index

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "schema_version": 1,
        "source_review_manifest": str(args.review_manifest),
        "model_predictions_used_as_labels": False,
        "all_transfers_require_visual_review": True,
        "frames": [{key: value for key, value in frame.items() if key != "bars"}
                   for frame in frames],
        "tracks": tracks,
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"bars: {[len(frame['bars']) for frame in frames]}; "
          f"confirmed seeds: {len(seeds)}; review-only transfers: {len(tracks)}")


if __name__ == "__main__":
    main()
