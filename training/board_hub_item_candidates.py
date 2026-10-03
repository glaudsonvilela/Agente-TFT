"""Offline inventory artwork candidates; visual ranking never establishes item IDs."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from ingestion.knowledge_release import canonical, digest, require
from ingestion.riot_ddragon_reference import BASE
from training.board_hub_inventory import observe


def load_reference(folder: Path) -> tuple[dict, list[dict]]:
    manifest = json.loads((folder / "reference.json").read_bytes())
    body = {key: value for key, value in manifest.items() if key != "reference_sha256"}
    require(manifest.get("policy") == "riot_visual_reference_v1"
            and digest(canonical(body)) == manifest.get("reference_sha256"), "invalid visual reference")
    component = manifest["components"]["items"]
    require(component["path"] == "items.json", "invalid item catalog path")
    raw = (folder / "items.json").read_bytes()
    require(digest(raw) == component["sha256"], "item catalog hash mismatch")
    catalog = json.loads(raw)
    require(catalog["version"] == manifest["version"] and catalog["locale"] == manifest["locale"]
            and catalog["set_key"] == manifest["set_key"] and len(catalog["entries"]) == component["count"],
            "item catalog identity mismatch")
    return manifest, catalog["entries"]


def select_entries(entries: list[dict], set_key: str, scope: str) -> list[dict]:
    if scope == "all":
        return entries
    if scope != "set_path":
        raise ValueError("invalid item matching scope")
    selected = [entry for entry in entries if entry.get("key", "").startswith(set_key + "/")]
    if not selected:
        raise ValueError("no provider items under selected set path")
    return selected


def fetch_icon(entry: dict, icon_dir: Path) -> bool:
    """Fetch only the versioned Riot CDN URL written by the pinned reference."""
    icon = entry["icon"]
    require(icon == Path(icon).name and icon.endswith(".png"), "unsafe icon filename")
    require(entry["icon_url"].startswith(BASE + "/")
            and entry["icon_url"].endswith("/img/tft-item/" + icon), "unsafe icon URL")
    path = icon_dir / icon
    if path.is_file():
        return False
    with urlopen(entry["icon_url"], timeout=20) as response:
        data = response.read(1_000_001)
    if len(data) > 1_000_000 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise OSError("invalid icon bytes")
    path.write_bytes(data)
    return True


def load_templates(entries: list[dict], icon_dir: Path, size: int = 28) -> tuple[list[dict], int]:
    import numpy as np
    from PIL import Image

    grouped: dict[str, dict] = {}
    available = 0
    for entry in entries:
        path = icon_dir / entry["icon"]
        if not path.is_file():
            continue
        with Image.open(path) as source:
            resized = source.convert("RGB").resize((size, size), Image.Resampling.BILINEAR)
        pixels = np.asarray(resized, dtype=np.float32)
        template_hash = hashlib.sha256(pixels.tobytes()).hexdigest()
        group = grouped.setdefault(template_hash, {"template_hash": template_hash, "pixels": pixels, "ids": []})
        group["ids"].append(entry["id"])
        available += 1
    return list(grouped.values()), available


def rank_slot(frame, rect: dict, templates: list[dict]) -> list[dict]:
    import numpy as np

    if not templates:
        return []
    stack = np.stack([group["pixels"] for group in templates])
    scores = np.full(len(templates), np.inf, dtype=np.float32)
    y = rect["y"]
    for x0 in range(rect["x"] + 6, rect["x"] + 13):
        for y0 in range(y + 9, y + 17):
            patch = frame[y0:y0 + 28, x0:x0 + 28]
            if patch.shape != (28, 28, 3):
                continue
            current = np.sqrt(np.mean((stack - patch) ** 2, axis=(1, 2, 3)))
            scores = np.minimum(scores, current)
    ranked = np.argsort(scores)[:3]
    return [{"ids_with_same_template": sorted(set(templates[index]["ids"])),
             "template_sha256": templates[index]["template_hash"],
             "rms": round(float(scores[index]), 3)} for index in ranked]


def run(image, profile: dict, manifest: dict, entries: list[dict], icon_dir: Path,
        match_scope: str = "all") -> dict:
    import numpy as np

    rgb = image.convert("RGB")
    inventory = observe(rgb.tobytes(), rgb.width, rgb.height, profile)
    selected = select_entries(entries, manifest.get("set_key", ""), match_scope)
    templates, available = load_templates(selected, icon_dir)
    frame = np.asarray(rgb, dtype=np.float32)
    rows = []
    for slot in inventory["slots"]:
        if slot["status"] != "icon_candidate":
            continue
        candidates = rank_slot(frame, slot["rect"], templates)
        rows.append({"slot": slot["slot"], "status": "candidate_only" if available == len(selected)
                     else "incomplete_catalog", "candidates": candidates,
                     "margin_to_second": round(candidates[1]["rms"] - candidates[0]["rms"], 3)
                     if len(candidates) > 1 else None, "item_id": None})
    return {"schema_version": 1, "policy": "board_hub_item_candidates_v1",
            "reference_sha256": manifest["reference_sha256"], "data_dragon_version": manifest["version"],
            "tft_patch": None, "icon_assets_available": available,
            "catalog_entries": len(entries), "matching_entries": len(selected),
            "matching_scope": match_scope, "unique_artworks": len(templates),
            "inventory": inventory, "candidate_slots": rows,
            "item_identity_established": False, "game_state_updated": False}


def main() -> None:
    from PIL import Image

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--icon-dir", type=Path, required=True)
    parser.add_argument("--match-scope", choices=("all", "set_path"), default="all")
    parser.add_argument("--fetch-missing", action="store_true")
    args = parser.parse_args()
    manifest, entries = load_reference(args.reference)
    args.icon_dir.mkdir(parents=True, exist_ok=True)
    fetch_errors = []
    selected = select_entries(entries, manifest["set_key"], args.match_scope)
    if args.fetch_missing:
        def attempt(entry):
            for _ in range(2):
                try:
                    return fetch_icon(entry, args.icon_dir)
                except (OSError, TimeoutError):
                    pass
            return entry["icon"]

        with ThreadPoolExecutor(max_workers=8) as pool:
            fetch_errors = [value for value in pool.map(attempt, selected) if isinstance(value, str)]
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    with Image.open(args.image) as image:
        result = run(image, profile, manifest, entries, args.icon_dir, args.match_scope)
    result["icon_fetch_errors"] = fetch_errors
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
