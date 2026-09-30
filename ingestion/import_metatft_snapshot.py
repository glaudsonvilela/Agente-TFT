from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ALLOWED_HOSTS = {"metatft.com", "www.metatft.com"}
VALID_KINDS = {"comp", "unit", "item", "trait", "augment", "player"}


def _finite_optional(value: Any, field: str) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _rate(value: Any, field: str) -> float | None:
    number = _finite_optional(value, field)
    if number is None:
        return None
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{field} must be in [0,1]")
    return number


def _avg_place(value: Any) -> float | None:
    number = _finite_optional(value, "avg_place")
    if number is None:
        return None
    if not 1.0 <= number <= 8.0:
        raise ValueError("avg_place must be in [1,8]")
    return number


def _frequency(value: Any) -> float | None:
    number = _finite_optional(value, "frequency")
    if number is None:
        return None
    if number < 0.0:
        raise ValueError("frequency must be >= 0")
    return number


def _sample_size(value: Any) -> int | None:
    if value is None or value == "":
        return None
    number = int(value)
    if number <= 0:
        raise ValueError("sample_size must be > 0")
    return number


def validate_source_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise ValueError("MetaTFT source_url must use https")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("source_url must point to metatft.com")
    return value


def normalize_entity(entity: dict[str, Any]) -> dict[str, Any]:
    kind = str(entity.get("kind") or "").strip().lower()
    if kind not in VALID_KINDS:
        raise ValueError(f"invalid MetaTFT entity kind: {kind!r}")

    entity_id = str(entity.get("id") or "").strip()
    name = str(entity.get("name") or "").strip()
    if not entity_id:
        raise ValueError("entity id cannot be empty")
    if not name:
        raise ValueError("entity name cannot be empty")

    unit_ids = entity.get("unit_ids") or []
    trait_ids = entity.get("trait_ids") or []
    tags = entity.get("tags") or []
    if not isinstance(unit_ids, list) or not isinstance(trait_ids, list) or not isinstance(tags, list):
        raise ValueError("unit_ids, trait_ids and tags must be arrays")

    performance = entity.get("performance") or {}
    if not isinstance(performance, dict):
        raise ValueError("performance must be an object")

    return {
        "kind": kind,
        "id": entity_id,
        "name": name,
        "unit_ids": [str(value) for value in unit_ids],
        "trait_ids": [str(value) for value in trait_ids],
        "performance": {
            "avg_place": _avg_place(performance.get("avg_place")),
            "top4_rate": _rate(performance.get("top4_rate"), "top4_rate"),
            "win_rate": _rate(performance.get("win_rate"), "win_rate"),
            "frequency": _frequency(performance.get("frequency")),
            "sample_size": _sample_size(performance.get("sample_size")),
        },
        "tags": [str(value) for value in tags],
    }


def normalize_snapshot(raw: dict[str, Any]) -> dict[str, Any]:
    source_url = validate_source_url(str(raw.get("source_url") or "").strip())
    captured_at_ms = int(raw.get("captured_at_ms") or 0)
    if captured_at_ms <= 0:
        raise ValueError("captured_at_ms must be > 0")

    entities = raw.get("entities")
    if not isinstance(entities, list):
        raise ValueError("entities must be an array")

    normalized_entities = [
        normalize_entity(entity)
        for entity in entities
        if isinstance(entity, dict)
    ]

    metadata = raw.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")

    return {
        "schema_version": 1,
        "source": "metatft_public",
        "source_url": source_url,
        "captured_at_ms": captured_at_ms,
        "patch": raw.get("patch"),
        "set": raw.get("set"),
        "queue": raw.get("queue"),
        "rank_filter": raw.get("rank_filter"),
        "window": raw.get("window"),
        "entities": normalized_entities,
        "metadata": {
            str(key): str(value)
            for key, value in metadata.items()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize a public/exported MetaTFT snapshot for the local "
            "Agente TFT meta context."
        )
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SystemExit("input must be a JSON object")

    normalized = normalize_snapshot(raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    counts: dict[str, int] = {}
    for entity in normalized["entities"]:
        counts[entity["kind"]] = counts.get(entity["kind"], 0) + 1

    print(
        json.dumps(
            {
                "output": str(args.output),
                "source_url": normalized["source_url"],
                "patch": normalized["patch"],
                "set": normalized["set"],
                "counts": counts,
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
