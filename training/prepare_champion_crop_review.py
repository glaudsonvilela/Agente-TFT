#!/usr/bin/env python3
"""Make unlabeled, native-resolution unit crops from gameplay review frames.

Health bars only propose a location. The crop is never treated as a champion
label or a training example until its identity, box and pose are reviewed.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from training.track_fresh_champion_crops import PREVIEW_SIZE, health_bars


def crop_box(bar: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[int, int, int, int]:
    x, y, width, _ = bar
    sx, sy = size[0] / PREVIEW_SIZE[0], size[1] / PREVIEW_SIZE[1]
    return (
        max(0, round((x - width * 0.35) * sx)),
        max(0, round((y - width * 0.12) * sy)),
        min(size[0], round((x + width * 1.35) * sx)),
        min(size[1], round((y + width * 2.05) * sy)),
    )


def supported_health_bar(preview: np.ndarray, bar: tuple[int, int, int, int], source_width: int) -> bool:
    x, y, width, height = bar
    if height > 8 or width * source_width / PREVIEW_SIZE[0] < 60:
        return False
    above = preview[max(0, y - 1), x:x + width]
    below = preview[min(PREVIEW_SIZE[1] - 1, y + height + 1), x:x + width]
    return (np.mean(above.mean(axis=1) < 90) >= 0.55
            and np.mean(below.mean(axis=1) < 90) >= 0.45)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--per-page", type=int, default=36)
    args = parser.parse_args()
    if args.per_page < 1 or args.per_page > 100:
        parser.error("--per-page must be between 1 and 100")
    source = args.source_dir.resolve(strict=True)
    source_manifest = json.loads((source / "review_manifest.json").read_text())
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    records: list[dict] = []
    for frame in source_manifest["frames"]:
        path = source / frame["frame"]
        with Image.open(path) as image:
            image = image.convert("RGB")
            preview = np.asarray(image.resize(PREVIEW_SIZE), dtype=np.uint8)
            for bar in health_bars(image):
                if not supported_health_bar(preview, bar, image.width):
                    continue
                box = crop_box(bar, image.size)
                if box[2] - box[0] < 45 or box[3] - box[1] < 60:
                    continue
                ident = f"{len(records) + 1:03d}"
                crop_path = output / f"{ident}.png"
                image.crop(box).save(crop_path)
                records.append({
                    "id": ident,
                    "crop": crop_path.name,
                    "crop_sha256": sha256(crop_path.read_bytes()).hexdigest(),
                    "frame": str(path),
                    "second": frame["second"],
                    "source_video": source_manifest["source"],
                    "source_resolution": list(image.size),
                    "box_source": list(box),
                    "bar_preview_2048": list(bar),
                    "identity": None,
                    "box_verified": False,
                    "pose_verified": False,
                    "may_train": False,
                })
    for start in range(0, len(records), args.per_page):
        page = Image.new("RGB", (4 * 280, 260 * ((min(args.per_page, len(records) - start) + 3) // 4)), "#121821")
        draw = ImageDraw.Draw(page)
        for cell, record in enumerate(records[start:start + args.per_page]):
            x, y = cell % 4 * 280, cell // 4 * 260
            with Image.open(output / record["crop"]) as crop:
                thumb = crop.copy()
                thumb.thumbnail((248, 215))
            page.paste(thumb, (x + (280 - thumb.width) // 2, y + 4))
            width, height = record["source_resolution"]
            draw.text((x + 8, y + 225), f"{record['id']} | {record['second']:.1f}s | {width}x{height}", fill="white")
        page.save(output / f"review-{start // args.per_page + 1:02d}.jpg", quality=92)
    (output / "review_manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "source_review_manifest": str(source / "review_manifest.json"),
        "model_predictions_used_as_labels": False,
        "all_crops_require_identity_box_pose_review": True,
        "records": records,
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(records)} unlabeled candidate crops; review pages: {(len(records) + args.per_page - 1) // args.per_page}")


if __name__ == "__main__":
    main()
