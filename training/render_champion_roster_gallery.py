#!/usr/bin/env python3
"""Render all 65 set units with one candidate body crop and honest coverage."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def candidate_score(row: dict) -> tuple:
    image = Image.open(row["natural_crop"])
    width, height = image.size
    image.close()
    source = row.get("source_resolution") or [0, 0]
    return (
        row.get("review_status") == "user_confirmed_candidate",
        source[0] >= 3840,
        min(width, height),
        width * height,
    )


def render_page(rows: list[dict], number: int) -> Image.Image:
    columns, cell_w, cell_h = 5, 310, 330
    page = Image.new("RGB", (columns * cell_w, 60 + ((len(rows) + columns - 1) // columns) * cell_h), "#101821")
    draw = ImageDraw.Draw(page)
    title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
    draw.text((18, 16), f"TFT Set 18 — 65 campeões | folha {number}/3 | imagens candidatas", font=title_font, fill="#eaf3ff")
    for index, row in enumerate(rows):
        x, y = index % columns * cell_w, 60 + index // columns * cell_h
        draw.rounded_rectangle((x + 6, y + 4, x + cell_w - 6, y + cell_h - 6), radius=10, fill="#1b2937")
        if row["preview_crop"]:
            with Image.open(row["preview_crop"]) as source:
                thumb = source.convert("RGB")
                thumb.thumbnail((cell_w - 25, 245))
            page.paste(thumb, (x + (cell_w - thumb.width) // 2, y + 10 + (245 - thumb.height) // 2))
        else:
            draw.text((x + 72, y + 115), "SEM RECORTE", font=small_font, fill="#e2ad7d")
        draw.text((x + 15, y + 261), row["name"], font=title_font, fill="#f5f8ff")
        draw.text((x + 15, y + 292), f"{row['candidate_crops']} recortes | 0 poses aprovadas", font=small_font,
                  fill="#b8cddd")
        if row["preview_review_id"]:
            draw.text((x + 15, y + 312), f"exemplo {row['preview_review_id']}", font=small_font, fill="#8aa9c0")
    return page


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    shop = json.loads(args.shop.read_text(encoding="utf-8"))["rows"]
    roster = json.loads(args.roster.read_text(encoding="utf-8"))["records"]
    if len(shop) != 65:
        raise ValueError("Expected exactly 65 Set 18 shop units")
    counts = Counter(row["game_id"] for row in roster)
    report = []
    for unit in sorted(shop, key=lambda row: row["name_pt_br"].casefold()):
        candidates = [row for row in roster if row["game_id"] == unit["game_id"]]
        chosen = max(candidates, key=candidate_score) if candidates else None
        report.append({
            "name": unit["name_pt_br"],
            "game_id": unit["game_id"],
            "candidate_crops": counts[unit["game_id"]],
            "approved_distinct_poses": 0,
            "preview_crop": chosen["natural_crop"] if chosen else None,
            "preview_review_id": chosen["review_id"] if chosen else None,
            "training_ready": False,
        })
    args.output_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    for number, start in enumerate(range(0, len(report), 25), 1):
        page = render_page(report[start:start + 25], number)
        page.save(args.output_dir / f"roster-gallery-{number:02d}.jpg", quality=94)
        pages.append(page)
    pages[0].save(args.output_dir / "roster-gallery-all-65.pdf", save_all=True,
                  append_images=pages[1:], resolution=120)
    with (args.output_dir / "roster-gallery-all-65.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=report[0].keys())
        writer.writeheader()
        writer.writerows(report)
    (args.output_dir / "roster-gallery-all-65.json").write_text(
        json.dumps({"units": report, "candidate_crops_total": len(roster),
                    "classes_with_crops": sum(row["candidate_crops"] > 0 for row in report),
                    "classes_at_five_crops": sum(row["candidate_crops"] >= 5 for row in report),
                    "classes_at_five_approved_poses": 0}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{len(report)} units; {sum(row['candidate_crops'] > 0 for row in report)} with candidates; "
          f"{sum(row['candidate_crops'] >= 5 for row in report)} at five raw crops; zero approved")


if __name__ == "__main__":
    main()
