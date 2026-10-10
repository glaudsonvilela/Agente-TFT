#!/usr/bin/env python3
"""Make a single priority sheet and complete PDF of still-unresolved crops."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SOURCES = {
    "E": ("elderwood-4k-crops", "review_decisions_20261010.json"),
    "F": ("firsttime-4k-crops", "review_decisions_firsttime_20261010.json"),
    "S": ("sivir-1440-crops", "review_decisions_sivir_20261010.json"),
    "N": ("nidalee-1440-crops", "review_decisions_nidalee_20261010.json"),
    "V": ("vi-1080-crops", None),
}
PRIORITY = [
    "E-041", "E-043", "E-044", "E-045", "E-058", "E-059", "E-060",
    "F-001", "F-002", "F-007", "F-032", "F-048",
    "S-001", "S-002", "S-021", "S-030", "S-032", "S-058",
    "N-005", "N-009", "N-025", "N-035", "V-001", "V-003",
]


def render(rows: list[dict]) -> Image.Image:
    width, height, columns = 330, 300, 4
    page = Image.new("RGB", (width * columns, height * ((len(rows) + columns - 1) // columns)), "#111923")
    draw = ImageDraw.Draw(page)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 21)
    for index, row in enumerate(rows):
        x, y = index % columns * width, index // columns * height
        with Image.open(row["crop"]) as original:
            thumb = original.convert("RGB")
            thumb.thumbnail((width - 20, height - 50))
        page.paste(thumb, (x + (width - thumb.width) // 2, y + 5))
        draw.text((x + 10, y + height - 36), row["id"], font=font, fill="white")
        resolution = row["resolution"]
        draw.text((x + 105, y + height - 33), f"{resolution[0]}x{resolution[1]}", fill="#a8bed0")
    return page


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    args = parser.parse_args()
    source_dir = args.source_dir
    roster = json.loads(args.roster.read_text(encoding="utf-8"))
    labeled = {row["review_id"] for row in roster["records"]}
    excluded: set[str] = set()
    remaining: list[dict] = []
    total = 0
    for prefix, (folder, decision_file) in SOURCES.items():
        if decision_file:
            decisions = json.loads((Path(__file__).parent / decision_file).read_text(encoding="utf-8"))
            excluded.update(f"{prefix}-{ident}" for ident in decisions.get("confirmed_non_champion", []))
        manifest = json.loads((source_dir / folder / "review_manifest.json").read_text(encoding="utf-8"))
        total += len(manifest["records"])
        for row in manifest["records"]:
            ident = f"{prefix}-{row['id']}"
            if ident in labeled or ident in excluded:
                continue
            remaining.append({
                "id": ident,
                "crop": str(source_dir / folder / row["crop"]),
                "source_video": row["source_video"],
                "second": row["second"],
                "resolution": row["source_resolution"],
                "status": "unresolved_or_quality_pending",
            })
    by_id = {row["id"]: row for row in remaining}
    missing = set(PRIORITY) - set(by_id)
    if missing:
        raise ValueError(f"Priority ID already resolved or missing: {sorted(missing)}")
    render([by_id[ident] for ident in PRIORITY]).save(source_dir / "unresolved-priority-20261010.jpg", quality=93)
    pages = [render(remaining[index:index + 20]) for index in range(0, len(remaining), 20)]
    pages[0].save(source_dir / "unresolved-full-20261010.pdf", save_all=True,
                  append_images=pages[1:], resolution=120)
    report = {
        "schema_version": 1,
        "total_source_candidates": total,
        "registered_identity_candidates_in_these_sources": sum(
            row["review_id"].split("-")[0] in SOURCES for row in roster["records"]),
        "excluded_non_champion": len(excluded),
        "unresolved_count": len(remaining),
        "priority_review_ids": PRIORITY,
        "remaining": remaining,
        "training_eligible_from_this_batch": 0,
    }
    (source_dir / "unresolved-audit-20261010.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "total_source_candidates", "registered_identity_candidates_in_these_sources",
        "excluded_non_champion", "unresolved_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
