"""Immutable official TFT visual reference, separate from UI geometry and replay patch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.request import urlopen

from ingestion.knowledge_release import canonical, digest, require

BASE = "https://ddragon.leagueoflegends.com/cdn"
MAX_DOWNLOAD = 8 * 1024 * 1024
VERSION = re.compile(r"\d+\.\d+\.\d+\Z")
LOCALE = re.compile(r"[a-z]{2}_[A-Z]{2}\Z")
SET = re.compile(r"TFTSet\d+\Z")


def source_url(version: str, locale: str, kind: str) -> str:
    require(VERSION.fullmatch(version) is not None, "explicit Data Dragon version required")
    require(LOCALE.fullmatch(locale) is not None, "invalid locale")
    require(kind in ("tft-champion", "tft-item"), "invalid Data Dragon type")
    return f"{BASE}/{version}/data/{locale}/{kind}.json"


def download(url: str) -> bytes:
    with urlopen(url, timeout=20) as response:
        data = response.read(MAX_DOWNLOAD + 1)
    require(len(data) <= MAX_DOWNLOAD, "Data Dragon response too large")
    return data


def parse_snapshot(data: bytes, kind: str, version: str) -> dict:
    require(len(data) <= MAX_DOWNLOAD, "Data Dragon snapshot too large")
    value = json.loads(data)
    require(isinstance(value, dict) and value.get("type") == kind and value.get("version") == version,
            "Data Dragon type/version mismatch")
    require(isinstance(value.get("data"), dict) and value["data"], "empty Data Dragon catalog")
    return value


def entries(snapshot: dict, kind: str, version: str, set_key: str) -> list[dict]:
    group = kind
    prefix = f"/Sets/{set_key}/"
    result = []
    for key, row in snapshot["data"].items():
        if kind == "tft-champion" and prefix not in key:
            continue
        require(isinstance(key, str) and isinstance(row, dict), "invalid Data Dragon entry")
        icon = row.get("image", {}).get("full") if isinstance(row.get("image"), dict) else None
        require(isinstance(icon, str) and re.fullmatch(r"[A-Za-z0-9_.-]+\.png", icon), "invalid Data Dragon icon")
        require(isinstance(row.get("id"), str) and isinstance(row.get("name"), str), "missing entry identity")
        result.append({"key": key, "id": row["id"], "name": row["name"],
                       "icon": icon, "icon_url": f"{BASE}/{version}/img/{group}/{icon}"})
    require(result, "no champions for selected set")
    return sorted(result, key=lambda row: row["key"])


def build(champion_data: bytes, item_data: bytes, *, version: str, locale: str,
          set_key: str, output_root: Path) -> tuple[Path, dict]:
    source_url(version, locale, "tft-champion")
    require(SET.fullmatch(set_key) is not None, "explicit set key required")
    sources = {"champions": champion_data, "items": item_data}
    kinds = {"champions": "tft-champion", "items": "tft-item"}
    catalogs = {}
    for name, data in sources.items():
        snapshot = parse_snapshot(data, kinds[name], version)
        catalogs[name] = {"schema_version": 1, "source": "riot_data_dragon",
                          "version": version, "locale": locale, "set_key": set_key,
                          "scope": set_key if name == "champions" else "all_items_in_provider_snapshot",
                          "entries": entries(snapshot, kinds[name], version, set_key)}
    parts = {name: canonical(catalog) for name, catalog in catalogs.items()}
    identity = {"schema_version": 1, "policy": "riot_visual_reference_v1", "version": version,
                "locale": locale, "set_key": set_key, "tft_patch": None,
                "replay_binding": False, "geometry_included": False,
                "components": {name: {"path": name + ".json", "sha256": digest(parts[name]),
                                       "source_sha256": digest(sources[name]),
                                       "source_url": source_url(version, locale, kinds[name]),
                                       "count": len(catalogs[name]["entries"])} for name in sources}}
    manifest = dict(identity, reference_sha256=digest(canonical(identity)))
    parent = Path(output_root) / version / locale / set_key
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / manifest["reference_sha256"]

    def verify_existing() -> None:
        require(not destination.is_symlink(), "symlink reference")
        for name, data in {**parts, "reference.json": canonical(manifest)}.items():
            filename = name if name.endswith(".json") else name + ".json"
            require((destination / filename).read_bytes() == data, "reference content changed")

    if destination.exists():
        verify_existing()
        return destination, manifest
    staging = Path(tempfile.mkdtemp(prefix=".building-", dir=parent))
    try:
        for name, data in parts.items():
            (staging / (name + ".json")).write_bytes(data)
        (staging / "reference.json").write_bytes(canonical(manifest))
        try:
            staging.rename(destination)
        except OSError:
            if not destination.is_dir():
                raise
            verify_existing()
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--locale", default="pt_BR")
    parser.add_argument("--set", dest="set_key", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("knowledge/riot-ddragon"))
    args = parser.parse_args()
    try:
        champion = download(source_url(args.version, args.locale, "tft-champion"))
        item = download(source_url(args.version, args.locale, "tft-item"))
        path, manifest = build(champion, item, version=args.version, locale=args.locale,
                               set_key=args.set_key, output_root=args.output_root)
        print(json.dumps({"path": str(path), "reference": manifest}, ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"RIOT_REFERENCE_ERROR={exc}\n")


if __name__ == "__main__":
    main()
