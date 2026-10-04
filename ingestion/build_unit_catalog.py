from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


COMMUNITYDRAGON_GAME_ROOT = "https://raw.communitydragon.org/latest/game/"


@dataclass(frozen=True)
class SetInfo:
    key: str
    number: int | None
    name: str
    champions: list[dict[str, Any]]
    traits: list[dict[str, Any]]


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("TFT source JSON must be an object")
    return value


def iter_sets(data: dict[str, Any]) -> list[SetInfo]:
    result: list[SetInfo] = []

    sets = data.get("sets")
    if isinstance(sets, dict):
        for key, value in sets.items():
            if not isinstance(value, dict):
                continue
            result.append(
                SetInfo(
                    key=str(key),
                    number=parse_int(key),
                    name=str(value.get("name") or ""),
                    champions=list_of_dicts(value.get("champions")),
                    traits=list_of_dicts(value.get("traits")),
                )
            )

    set_data = data.get("setData")
    if isinstance(set_data, list):
        for index, value in enumerate(set_data):
            if not isinstance(value, dict):
                continue
            number = parse_int(value.get("number"))
            mutator = str(value.get("mutator") or "").strip()
            name = str(value.get("name") or "")
            key = mutator or (str(number) if number is not None else f"setData:{index}")

            duplicate = any(
                item.key == key
                and item.name == name
                and len(item.champions) == len(list_of_dicts(value.get("champions")))
                for item in result
            )
            if duplicate:
                continue

            result.append(
                SetInfo(
                    key=key,
                    number=number,
                    name=name,
                    champions=list_of_dicts(value.get("champions")),
                    traits=list_of_dicts(value.get("traits")),
                )
            )

    return result


def parse_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def communitydragon_asset_url(path: Any) -> str | None:
    if not isinstance(path, str):
        return None
    value = path.strip().replace("\\", "/")
    if not value:
        return None

    lower = value.lower()
    marker = "assets/"
    index = lower.find(marker)
    if index >= 0:
        lower = lower[index:]

    lower = lower.lstrip("/")
    if not lower:
        return None
    return COMMUNITYDRAGON_GAME_ROOT + lower


def playable_champion(champion: dict[str, Any]) -> bool:
    api_name = str(champion.get("apiName") or "").strip()
    name = str(champion.get("name") or "").strip()
    cost = parse_int(champion.get("cost"))
    traits = champion.get("traits")

    if not api_name or not name:
        return False
    if cost is None or not 1 <= cost <= 5:
        return False
    if not isinstance(traits, list) or not traits:
        return False
    if bool(champion.get("isSpawn", False)):
        return False
    return True


def normalize_champion(champion: dict[str, Any]) -> dict[str, Any]:
    raw_stats = champion.get("stats")
    stats = None
    if isinstance(raw_stats, dict):
        stats = {}
        for key in ("hp", "damage", "attackSpeed", "armor", "magicResist",
                    "range", "mana", "initialMana", "critChance", "critMultiplier"):
            value = raw_stats.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                stats[key] = value
    raw_ability = champion.get("ability")
    ability = None
    if isinstance(raw_ability, dict):
        variables = []
        for row in raw_ability.get("variables", []):
            if not isinstance(row, dict) or not isinstance(row.get("name"), str):
                continue
            values = row.get("value")
            if isinstance(values, list) and all(
                isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                for value in values
            ):
                variables.append({"name": row["name"], "values": values})
        ability = {"name": str(raw_ability.get("name") or ""),
                   "description": str(raw_ability.get("desc") or ""),
                   "variables": variables}
    return {
        "api_name": str(champion["apiName"]),
        "character_name": str(champion.get("characterName") or ""),
        "name": str(champion["name"]),
        "cost": int(champion["cost"]),
        "role": champion.get("role"),
        "traits": [str(value) for value in champion.get("traits", [])],
        "stats": stats,
        "ability": ability,
        "icon_path": champion.get("icon"),
        "square_icon_path": champion.get("squareIcon"),
        "tile_icon_path": champion.get("tileIcon"),
        "icon_url": communitydragon_asset_url(champion.get("icon")),
        "square_icon_url": communitydragon_asset_url(champion.get("squareIcon")),
        "tile_icon_url": communitydragon_asset_url(champion.get("tileIcon")),
    }


def find_set(sets: list[SetInfo], selector: str) -> SetInfo:
    selector_folded = selector.casefold()
    matches = [
        item
        for item in sets
        if item.key.casefold() == selector_folded
        or item.name.casefold() == selector_folded
        or (item.number is not None and str(item.number) == selector)
    ]

    if not matches:
        raise ValueError(f"set not found: {selector}")
    if len(matches) > 1:
        descriptions = ", ".join(
            f"{item.key!r}/{item.name!r}" for item in matches
        )
        raise ValueError(
            f"set selector is ambiguous: {selector}; matches: {descriptions}"
        )
    return matches[0]


def build_catalog(source: dict[str, Any], target: SetInfo) -> dict[str, Any]:
    champions = [
        normalize_champion(champion)
        for champion in target.champions
        if playable_champion(champion)
    ]
    champions.sort(key=lambda row: (row["cost"], row["name"].casefold(), row["api_name"]))

    api_names = [row["api_name"] for row in champions]
    if len(api_names) != len(set(api_names)):
        raise ValueError("duplicate champion apiName in normalized set")

    return {
        "schema_version": 1,
        "source": "communitydragon_tft",
        "set": {
            "key": target.key,
            "number": target.number,
            "name": target.name,
        },
        "champions": champions,
        "champion_count": len(champions),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize a CommunityDragon TFT set into a local unit catalog."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--list-sets", action="store_true")
    parser.add_argument("--set", dest="set_selector")
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source = load_json(args.source)
    sets = iter_sets(source)

    if args.list_sets:
        rows = [
            {
                "key": item.key,
                "number": item.number,
                "name": item.name,
                "champions": len(item.champions),
            }
            for item in sets
        ]
        print(json.dumps(rows, indent=2, ensure_ascii=False, sort_keys=True))
        return 0

    if not args.set_selector:
        raise SystemExit("--set is required unless --list-sets is used")
    if args.output is None:
        raise SystemExit("--output is required when building a catalog")

    target = find_set(sets, args.set_selector)
    catalog = build_catalog(source, target)
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
                "champion_count": catalog["champion_count"],
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
