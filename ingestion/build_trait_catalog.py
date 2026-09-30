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


def normalize_effect(effect: dict[str, Any]) -> dict[str, Any]:
    variables = effect.get("variables")
    if not isinstance(variables, dict):
        variables = {}

    normalized_variables: dict[str, Any] = {}
    for key, value in variables.items():
        if value is None or isinstance(value, (bool, int, float, str)):
            normalized_variables[str(key)] = value
        else:
            normalized_variables[str(key)] = str(value)

    return {
        "min_units": effect.get("minUnits"),
        "max_units": effect.get("maxUnits"),
        "style": effect.get("style"),
        "variables": normalized_variables,
    }


def normalize_trait(trait: dict[str, Any]) -> dict[str, Any]:
    effects = trait.get("effects")
    if not isinstance(effects, list):
        effects = []

    return {
        "api_name": str(trait.get("apiName") or ""),
        "name": str(trait.get("name") or ""),
        "desc": str(trait.get("desc") or ""),
        "icon_path": trait.get("icon"),
        "icon_url": communitydragon_asset_url(trait.get("icon")),
        "effects": [
            normalize_effect(effect)
            for effect in effects
            if isinstance(effect, dict)
        ],
    }


def build_catalog(source: dict[str, Any], set_selector: str) -> dict[str, Any]:
    selected = find_set(iter_sets(source), set_selector)
    traits = [
        normalize_trait(trait)
        for trait in selected.traits
        if str(trait.get("apiName") or "").strip()
        and str(trait.get("name") or "").strip()
    ]
    traits.sort(key=lambda row: (row["name"].casefold(), row["api_name"]))

    api_names = [row["api_name"] for row in traits]
    if len(api_names) != len(set(api_names)):
        raise ValueError("duplicate trait apiName in normalized set")

    return {
        "schema_version": 1,
        "source": "communitydragon_tft",
        "set": {
            "key": selected.key,
            "number": selected.number,
            "name": selected.name,
        },
        "traits": traits,
        "trait_count": len(traits),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize TFT traits for an explicit CommunityDragon set."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--set", dest="set_selector", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = load_json(args.source)
    catalog = build_catalog(source, args.set_selector)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "set": catalog["set"],
                "trait_count": catalog["trait_count"],
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
