"""Offline inventory artwork candidates; visual ranking never establishes item IDs."""
from __future__ import annotations

import argparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import copy
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from ingestion.knowledge_release import canonical, digest, require
from ingestion.riot_ddragon_reference import BASE
from training.board_hub_inventory import observe
from training.board_hub_frame import PreparedFrame


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
    if scope not in {"set_path", "set_plus_core"}:
        raise ValueError("invalid item matching scope")
    selected = [entry for entry in entries if entry.get("key", "").startswith(set_key + "/")
                or (scope == "set_plus_core" and
                    (entry.get("id", "").startswith("TFT_Item_") or
                     entry.get("key", "").startswith("Set5_RadiantItems/")))]
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


@dataclass
class TemplateBank:
    groups: list[dict]
    matrix: object
    squared_norms: object
    size: int
    # Exact source pixels only: a changed icon always runs the matcher again.
    recent_rankings: OrderedDict = field(default_factory=OrderedDict)
    cache_hits: int = 0
    cache_misses: int = 0

    def __len__(self) -> int:
        return len(self.groups)


def load_templates(entries: list[dict], icon_dir: Path, size: int = 28) -> tuple[TemplateBank, int]:
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
        group = grouped.setdefault(template_hash, {"template_hash": template_hash, "pixels": pixels,
                                                   "ids": [], "labels": {}})
        group["ids"].append(entry["id"])
        group["labels"][entry["id"]] = entry.get("name") or entry["id"]
        available += 1
    groups = list(grouped.values())
    matrix = np.stack([group["pixels"].reshape(-1) for group in groups]).astype(np.float64) if groups else np.empty((0, size * size * 3), dtype=np.float64)
    norms = np.einsum('ij,ij->i', matrix, matrix)
    return TemplateBank(groups, matrix, norms, size), available


def rank_patch_groups(groups: list[list], templates: TemplateBank) -> list[list[dict]]:
    """Rank independent icon searches with one matrix operation per frame."""
    import numpy as np

    results = [[] for _ in groups]
    if not templates.groups:
        return results
    missing = []
    pending = {}
    for index, patches in enumerate(groups):
        if not patches:
            continue
        # Exact crop bytes, never the previous frame's proposed identity.
        key = hashlib.blake2b(
            b"".join(patch.tobytes() for patch in patches), digest_size=16).digest()
        if key in templates.recent_rankings:
            templates.cache_hits += 1
            templates.recent_rankings.move_to_end(key)
            results[index] = copy.deepcopy(templates.recent_rankings[key])
        elif key in pending:
            templates.cache_hits += 1
            pending[key][2].append(index)
        else:
            templates.cache_misses += 1
            pending[key] = (patches, key, [index])
            missing.append(pending[key])
    if not missing:
        return results
    observed = np.concatenate([
        np.stack([patch.reshape(-1) for patch in patches])
        for patches, _, _ in missing]).astype(np.float64)
    norms = np.einsum('ij,ij->i', observed, observed)
    squared = norms[:, None] + templates.squared_norms[None, :] - 2 * observed @ templates.matrix.T
    start = 0
    for patches, key, positions in missing:
        group_scores = squared[start:start + len(patches)]
        start += len(patches)
        best_patch = np.argmin(group_scores, axis=0)
        scores = np.sqrt(np.maximum(0, group_scores.min(axis=0)) /
                         (templates.size * templates.size * 3))
        ranked = np.argsort(scores)[:3]
        result = [{"ids_with_same_template": sorted(set(templates.groups[item]["ids"])),
                 "catalog_options": [{"visual_id": item_id,
                                      "name": templates.groups[item]["labels"][item_id]}
                                     for item_id in sorted(templates.groups[item]["labels"])],
                 "template_sha256": templates.groups[item]["template_hash"],
                 "sample_index": int(best_patch[item]),
                 "rms": round(float(scores[item]), 3)} for item in ranked]
        templates.recent_rankings[key] = copy.deepcopy(result)
        templates.recent_rankings.move_to_end(key)
        if len(templates.recent_rankings) > 64:
            templates.recent_rankings.popitem(last=False)
        for index in positions:
            results[index] = copy.deepcopy(result)
    return results


def rank_patches(patches: list, templates: TemplateBank) -> list[dict]:
    return rank_patch_groups([patches], templates)[0]


def rank_slot(frame, rect: dict, templates: TemplateBank) -> list[dict]:
    if not templates:
        return []
    patches = []
    rects = []
    y = rect["y"]
    for x0 in range(rect["x"] + 6, rect["x"] + 13):
        for y0 in range(y + 9, y + 17):
            patch = frame[y0:y0 + 28, x0:x0 + 28]
            if patch.shape != (28, 28, 3):
                continue
            patches.append(patch)
            rects.append({"x": x0, "y": y0, "width": 28, "height": 28})
    ranked = rank_patches(patches, templates)
    for row in ranked:
        row["sample_rect"] = rects[row.pop("sample_index")]
    return ranked


def run(image, profile: dict, manifest: dict, entries: list[dict], icon_dir: Path,
        match_scope: str = "all", preloaded_templates: tuple[TemplateBank, int] | None = None,
        prepared_frame: PreparedFrame | None = None, selected_entries: list[dict] | None = None) -> dict:
    prepared = prepared_frame or PreparedFrame.from_image(image)
    rgb = prepared.rgb
    inventory = observe(prepared.pixels, rgb.width, rgb.height, profile,
                        frame_array=prepared.array)
    selected = selected_entries if selected_entries is not None else select_entries(
        entries, manifest.get("set_key", ""), match_scope)
    templates, available = preloaded_templates if preloaded_templates is not None else load_templates(selected, icon_dir)
    # Keep the full frame byte-sized; only tiny candidate patches need floats.
    frame = prepared.array
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
    parser.add_argument("--match-scope", choices=("all", "set_path", "set_plus_core"), default="all")
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
