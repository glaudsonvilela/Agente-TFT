"""Build a tiny CPU portrait index from exact square game UI assets.

This is a nearest-template recognizer, not a neural network.  It avoids the
unreliable 3D champion crops and keeps the source icons intact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from prepare_trait_icon_catalog import COMMUNITY_DRAGON_EXPORT, DEFAULT_OUTPUT

DEFAULT_MODEL = DEFAULT_OUTPUT.parent / "model"
FEATURE_SIZE = 16


def feature(image: Image.Image) -> np.ndarray:
    gray = image.convert("L").resize((FEATURE_SIZE, FEATURE_SIZE), Image.Resampling.BILINEAR)
    values = np.asarray(gray, dtype=np.float32).reshape(-1).copy()
    values -= values.mean()
    norm = float(np.linalg.norm(values))
    if norm < 1.0:
        raise ValueError("portrait contains no texture")
    return values / norm


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    catalog = args.catalog
    manifest_bytes = (catalog / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest["patch"] != "18.4B" or manifest["data_dragon"] != "16.20.1":
        raise ValueError("model requires the 18.4B icon catalog")
    entries = manifest["entries"]
    if len(entries) != 74 or len({entry["id"] for entry in entries}) != 74:
        raise ValueError("expected 65 shop identities and nine game-only Lux variants")
    exported = COMMUNITY_DRAGON_EXPORT.read_bytes()
    if hashlib.sha256(exported).hexdigest() != manifest["community_dragon_export_sha256"]:
        raise ValueError("game export changed after icon download")
    set18 = next(row for row in json.loads(exported)["setData"] if row.get("number") == 18)
    by_id = {row["apiName"]: row for row in set18["champions"]}
    traits = {row["name"]: row["apiName"] for row in set18["traits"]}

    features: list[np.ndarray] = []
    labels: list[str] = []
    kinds: list[str] = []
    names: dict[str, str] = {}
    members: dict[str, list[str]] = {trait: [] for trait in traits}
    for entry in entries:
        identity = entry["id"]
        names[identity] = entry["name"]
        for trait in by_id[identity].get("traits", []):
            if trait in members:
                members[trait].append(identity)
        for kind in ("tileIcon", "squareIcon"):
            asset = entry["ui_assets"][kind]
            path = catalog / asset["file"]
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != asset["sha256"]:
                raise ValueError(f"icon changed: {path}")
            with Image.open(path) as image:
                features.append(feature(image))
            labels.append(identity)
            kinds.append(kind)

    args.output.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output / "portraits.npz", features=np.stack(features),
                        labels=np.asarray(labels), kinds=np.asarray(kinds))
    index = {
        "schema_version": 1, "set": "TFTSet18", "patch": "18.4B",
        "data_dragon": "16.20.1", "feature_size": FEATURE_SIZE,
        "catalog_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "id_to_name": names,
        "trait_name_to_id": traits,
        "trait_members_by_name": {trait: sorted(set(ids)) for trait, ids in members.items()},
        "templates": len(labels),
        "method": "full_square_ui_icons_grayscale_normalized_correlation",
    }
    (args.output / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")
    print(f"Indexed {len(entries)} champions, {len(labels)} full-square UI portraits, "
          f"{len(traits)} traits at {args.output}")


if __name__ == "__main__":
    main()
