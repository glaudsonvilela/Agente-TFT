from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ingestion.build_unit_catalog import (
    communitydragon_asset_url,
    find_set,
    iter_sets,
    load_json,
)


def normalize_effects(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, raw in value.items():
        key = str(key)
        if raw is None or isinstance(raw, (bool, int, float, str)):
            normalized[key] = raw
        else:
            normalized[key] = str(raw)
    return normalized


def is_tft_item(item: dict[str, Any]) -> bool:
    api_name = str(item.get("apiName") or "").strip()
    name = str(item.get("name") or "").strip()
    if not api_name or not name:
        return False
    return api_name.startswith("TFT") or api_name.startswith("TFT_Item")


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    composition = item.get("composition")
    if not isinstance(composition, list):
        composition = []

    return {
        "api_name": str(item.get("apiName") or ""),
        "name": str(item.get("name") or ""),
        "desc": str(item.get("desc") or ""),
        "incompatible_traits": [
            str(value) for value in item.get("incompatibleTraits", [])
        ]
        if isinstance(item.get("incompatibleTraits"), list)
        else [],
        "composition": [str(value) for value in composition],
        "effects": normalize_effects(item.get("effects")),
        "unique": bool(item.get("unique", False)),
        "icon_path": item.get("icon"),
        "icon_url": communitydragon_asset_url(item.get("icon")),
    }


def build_catalog(source: dict[str, Any]) -> dict[str, Any]:
    raw_items = source.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("CommunityDragon source has no items array")

    items = [
        normalize_item(item)
        for item in raw_items
        if isinstance(item, dict) and is_tft_item(item)
    ]
    items.sort(key=lambda row: (row["name"].casefold(), row["api_name"]))

    api_names = [row["api_name"] for row in items]
    if len(api_names) != len(set(api_names)):
        raise ValueError("duplicate item apiName in normalized catalog")

    return {
        "schema_version": 1,
        "source": "communitydragon_tft",
        "items": items,
        "item_count": len(items),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize CommunityDragon TFT items into a local catalog."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = load_json(args.source)
    catalog = build_catalog(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "item_count": catalog["item_count"],
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
