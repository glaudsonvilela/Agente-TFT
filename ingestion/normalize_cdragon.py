from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _set_entries(raw: dict[str, Any]) -> list[dict[str, Any]]:
    data = raw.get("setData", [])
    if isinstance(data, list):
        return [entry for entry in data if isinstance(entry, dict)]
    if isinstance(data, dict):
        return [entry for entry in data.values() if isinstance(entry, dict)]
    raise ValueError("CommunityDragon setData must be a list or object")


def _set_identity(entry: dict[str, Any]) -> str:
    parts = [
        str(entry.get("number", "")),
        str(entry.get("name", "")),
        str(entry.get("mutator", "")),
    ]
    return " | ".join(part for part in parts if part)


def select_set(
    raw: dict[str, Any],
    *,
    selector: str,
) -> dict[str, Any]:
    selector_folded = selector.casefold().strip()
    if not selector_folded:
        raise ValueError("set selector cannot be empty")

    matches = [
        entry
        for entry in _set_entries(raw)
        if selector_folded in _set_identity(entry).casefold()
    ]

    if not matches:
        identities = [_set_identity(entry) for entry in _set_entries(raw)]
        raise ValueError(
            f"no set matched {selector!r}; available examples: {identities[:10]}"
        )

    if len(matches) > 1:
        identities = [_set_identity(entry) for entry in matches]
        raise ValueError(
            f"set selector {selector!r} is ambiguous: {identities[:10]}"
        )

    return matches[0]


def normalize_champion(champion: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_name": champion.get("apiName"),
        "character_name": champion.get("characterName"),
        "name": champion.get("name"),
        "cost": champion.get("cost"),
        "role": champion.get("role"),
        "traits": champion.get("traits") or [],
        "icon": champion.get("icon"),
        "tile_icon": champion.get("tileIcon"),
        "square_icon": champion.get("squareIcon"),
        "stats": champion.get("stats") or {},
        "ability": champion.get("ability") or {},
    }


def normalize_trait(trait: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_name": trait.get("apiName"),
        "name": trait.get("name"),
        "desc": trait.get("desc"),
        "icon": trait.get("icon"),
        "effects": trait.get("effects") or [],
    }


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "api_name": item.get("apiName"),
        "name": item.get("name"),
        "desc": item.get("desc"),
        "icon": item.get("icon"),
        "is_augment": bool(item.get("isAugment", False)),
        "unique": bool(item.get("unique", False)),
        "composition": item.get("composition") or [],
        "associated_traits": item.get("associatedTraits") or [],
        "incompatible_traits": item.get("incompatibleTraits") or [],
        "effects": item.get("effects") or {},
        "tags": item.get("tags") or [],
    }


def _dedupe_by_api_name(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    without_id: list[dict[str, Any]] = []

    for entry in entries:
        api_name = entry.get("api_name")
        if isinstance(api_name, str) and api_name:
            result[api_name] = entry
        else:
            without_id.append(entry)

    return sorted(result.values(), key=lambda entry: str(entry["api_name"])) + without_id


def normalize_cdragon(
    raw: dict[str, Any],
    *,
    selector: str,
    source_sha256: str,
    source_path: str,
) -> dict[str, Any]:
    selected = select_set(raw, selector=selector)

    champions = _dedupe_by_api_name(
        [
            normalize_champion(entry)
            for entry in selected.get("champions", [])
            if isinstance(entry, dict)
        ]
    )
    traits = _dedupe_by_api_name(
        [
            normalize_trait(entry)
            for entry in selected.get("traits", [])
            if isinstance(entry, dict)
        ]
    )

    raw_items = [
        normalize_item(entry)
        for entry in raw.get("items", [])
        if isinstance(entry, dict)
    ]

    # setData may expose explicit allowlists. If absent, keep all items and
    # let later indexes filter by API name / tags. This is more robust across patches.
    allowed_items = {
        str(value)
        for value in selected.get("items", [])
        if isinstance(value, str)
    }
    allowed_augments = {
        str(value)
        for value in selected.get("augments", [])
        if isinstance(value, str)
    }

    items: list[dict[str, Any]] = []
    augments: list[dict[str, Any]] = []

    for item in raw_items:
        api_name = item.get("api_name")
        if item["is_augment"]:
            if not allowed_augments or api_name in allowed_augments:
                augments.append(item)
        else:
            if not allowed_items or api_name in allowed_items:
                items.append(item)

    return {
        "schema_version": 1,
        "source": {
            "kind": "communitydragon",
            "path": source_path,
            "sha256": source_sha256,
        },
        "set": {
            "number": selected.get("number"),
            "name": selected.get("name"),
            "mutator": selected.get("mutator"),
            "selector": selector,
        },
        "counts": {
            "champions": len(champions),
            "traits": len(traits),
            "items": len(items),
            "augments": len(augments),
        },
        "champions": champions,
        "traits": traits,
        "items": _dedupe_by_api_name(items),
        "augments": _dedupe_by_api_name(augments),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize CommunityDragon TFT JSON into a compact local Knowledge Pack."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("knowledge/raw/communitydragon_tft_pt_br.json"),
    )
    parser.add_argument("--set", required=True, dest="set_selector")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("knowledge/database/tft_static.json"),
    )
    args = parser.parse_args()

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    normalized = normalize_cdragon(
        raw,
        selector=args.set_selector,
        source_sha256=sha256_file(args.input),
        source_path=str(args.input),
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(args.output),
                "set": normalized["set"],
                "counts": normalized["counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
