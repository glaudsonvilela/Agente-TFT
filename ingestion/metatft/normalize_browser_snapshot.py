from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PATCH_RE = re.compile(r"^\d+\.\d+[a-z]?$", re.IGNORECASE)
SET_RE = re.compile(r"\bset\s+(\d+)\b", re.IGNORECASE)
PERCENT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
INTEGER_RE = re.compile(r"\b(\d[\d,]*)\b")
FLOAT_RE = re.compile(r"-?\d+(?:\.\d+)?")

WINDOW_PATTERNS = (
    "last 24 hours",
    "last 2 days",
    "last 3 days",
    "last 7 days",
    "last 14 days",
    "last 30 days",
)

RANK_PATTERNS = (
    "challenger",
    "grandmaster",
    "master",
    "diamond",
    "emerald",
    "platinum",
    "gold",
    "silver",
    "bronze",
    "iron",
)

HEADER_ALIASES = {
    "avg_place": {"avg place", "average place", "avg placement"},
    "win_rate": {"win rate", "win %", "winrate"},
    "top4_rate": {"top 4 rate", "top4 rate", "top 4 %", "top4 %"},
    "frequency": {"frequency", "play rate", "pick rate", "played"},
    "sample_size": {"games", "comps", "sample size", "matches"},
    "trait": {"trait"},
    "augment": {"augment"},
    "player": {"player", "summoner"},
    "unit": {"unit", "champion"},
    "item": {"item"},
    "comp": {"comp", "composition", "team comp"},
    "name": {"name"},
}


def normalized_key(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = text.replace("’", "'")
    return "".join(ch for ch in text if ch.isalnum())


def header_key(value: str) -> str:
    return " ".join(str(value).strip().casefold().split())


@dataclass(frozen=True)
class CatalogResolver:
    units: dict[str, str]
    items: dict[str, str]
    traits: dict[str, str]

    @classmethod
    def empty(cls) -> "CatalogResolver":
        return cls(units={}, items={}, traits={})

    @classmethod
    def from_catalogs(
        cls,
        *,
        unit_catalog: Path | None = None,
        item_catalog: Path | None = None,
        trait_catalog: Path | None = None,
    ) -> "CatalogResolver":
        return cls(
            units=_load_alias_map(
                unit_catalog,
                collection_keys=("champions", "units"),
                id_keys=("api_name", "apiName"),
            ),
            items=_load_alias_map(
                item_catalog,
                collection_keys=("items",),
                id_keys=("api_name", "apiName"),
            ),
            traits=_load_alias_map(
                trait_catalog,
                collection_keys=("traits",),
                id_keys=("api_name", "apiName"),
            ),
        )

    def resolve(self, kind: str, name: str) -> str | None:
        key = normalized_key(name)
        table = {
            "unit": self.units,
            "item": self.items,
            "trait": self.traits,
        }.get(kind)
        if table is None:
            return None
        return table.get(key)


def _load_alias_map(
    path: Path | None,
    *,
    collection_keys: tuple[str, ...],
    id_keys: tuple[str, ...],
) -> dict[str, str]:
    if path is None:
        return {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for key in collection_keys:
        value = raw.get(key)
        if isinstance(value, list):
            rows = [row for row in value if isinstance(row, dict)]
            break

    result: dict[str, str] = {}
    for row in rows:
        identifier = None
        for key in id_keys:
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                identifier = value.strip()
                break
        if not identifier:
            continue

        aliases = [
            row.get("name"),
            row.get("character_name"),
            row.get("api_name"),
            row.get("apiName"),
        ]
        for alias in aliases:
            if isinstance(alias, str) and alias.strip():
                result[normalized_key(alias)] = identifier

    return result


def load_raw(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("browser snapshot must be a JSON object")
    return value


def infer_context(raw: dict[str, Any]) -> dict[str, Any]:
    body_text = str(raw.get("body_text") or "")
    headings = raw.get("headings") or []
    title = str(raw.get("title") or "")
    corpus = "\n".join(
        [title]
        + [str(value) for value in headings if isinstance(value, str)]
        + body_text.splitlines()[:120]
    )

    lines = [" ".join(line.split()) for line in corpus.splitlines() if line.strip()]

    patch = None
    for line in lines:
        stripped = line.strip()
        if PATCH_RE.fullmatch(stripped):
            patch = stripped
            break

    set_value = None
    match = SET_RE.search(corpus)
    if match:
        set_value = f"TFTSet{match.group(1)}"

    queue = "ranked" if any(line.casefold() == "ranked" for line in lines) else None

    window = None
    folded = corpus.casefold()
    for pattern in WINDOW_PATTERNS:
        if pattern in folded:
            window = pattern.replace(" ", "_")
            break

    rank_filter = None
    for pattern in RANK_PATTERNS:
        if pattern in folded:
            suffix = "_plus" if f"{pattern} +" in folded or f"{pattern}+" in folded else ""
            rank_filter = pattern + suffix
            break

    return {
        "patch": patch,
        "set": set_value,
        "queue": queue,
        "rank_filter": rank_filter,
        "window": window,
    }


def page_kind(source_url: str, raw: dict[str, Any]) -> str | None:
    path = urlparse(source_url).path.rstrip("/")
    title = str(raw.get("title") or "").casefold()
    headings = " ".join(str(v) for v in raw.get("headings") or []).casefold()

    if path.startswith("/leaderboard"):
        return "player"
    if path == "/traits" or path.startswith("/traits/"):
        return "trait"
    if path == "/augments" or path.startswith("/augments/"):
        return "augment"
    if path == "/items" or path.startswith("/items/"):
        return "item"
    if path == "/units" or path.startswith("/units/"):
        return "unit"
    if path == "/comps" or path.startswith("/comps/") or path == "/pro-comps":
        return "comp"
    if path == "/trends":
        if "unit trends" in headings or "unit trends" in title:
            return "unit"
        if "item trends" in headings or "item trends" in title:
            return "item"
        if "trait trends" in headings or "trait trends" in title:
            return "trait"
    return None


def canonical_headers(row: list[Any]) -> list[str]:
    return [header_key(str(value)) for value in row]


def find_header_index(headers: list[str], semantic: str) -> int | None:
    aliases = HEADER_ALIASES[semantic]
    for index, value in enumerate(headers):
        if value in aliases:
            return index
    return None


def infer_table_kind(headers: list[str], fallback_kind: str) -> str:
    for semantic in ("player", "unit", "item", "trait", "augment", "comp"):
        if find_header_index(headers, semantic) is not None:
            return semantic
    return fallback_kind


def entity_name_index(headers: list[str], kind: str) -> int | None:
    for semantic in (kind, "name"):
        index = find_header_index(headers, semantic)
        if index is not None:
            return index
    if kind == "player":
        return find_header_index(headers, "player")
    return 0 if headers else None


def parse_percent(value: Any) -> float | None:
    text = str(value or "").strip()
    match = PERCENT_RE.search(text)
    if not match:
        return None
    number = float(match.group(1)) / 100.0
    if not 0.0 <= number <= 1.0:
        return None
    return number


def parse_avg_place(value: Any) -> float | None:
    text = str(value or "").strip()
    match = FLOAT_RE.search(text)
    if not match:
        return None
    number = float(match.group(0))
    if not 1.0 <= number <= 8.0:
        return None
    return number


def parse_frequency_cell(value: Any) -> tuple[float | None, int | None]:
    text = str(value or "").strip()
    rate = parse_percent(text)

    sample_size = None
    integers = INTEGER_RE.findall(text)
    for candidate in integers:
        compact = candidate.replace(",", "")
        try:
            number = int(compact)
        except ValueError:
            continue
        if number > 100:
            sample_size = number
            break

    return rate, sample_size


def parse_sample_size(value: Any) -> int | None:
    text = str(value or "").strip()
    match = INTEGER_RE.search(text)
    if not match:
        return None
    number = int(match.group(1).replace(",", ""))
    return number if number > 0 else None


def stable_source_id(kind: str, name: str, source_url: str) -> str:
    resolved_path = urlparse(source_url).path.rstrip("/").split("/")
    if len(resolved_path) >= 3 and resolved_path[-1]:
        slug = resolved_path[-1]
        if kind in {"unit", "trait", "augment", "item", "player"}:
            return f"metatft:{kind}:{slug}"
    return f"metatft:{kind}:{normalized_key(name)}"


def resolve_entity_id(
    *,
    kind: str,
    name: str,
    source_url: str,
    resolver: CatalogResolver,
) -> str:
    canonical = resolver.resolve(kind, name)
    return canonical or stable_source_id(kind, name, source_url)


def parse_table_entities(
    table: dict[str, Any],
    *,
    kind: str,
    source_url: str,
    resolver: CatalogResolver,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    rows = table.get("rows")
    if not isinstance(rows, list) or len(rows) < 2:
        return [], {"reason": "too_few_rows", "table": table}

    header_row = rows[0]
    if not isinstance(header_row, list):
        return [], {"reason": "invalid_header", "table": table}

    headers = canonical_headers(header_row)
    kind = infer_table_kind(headers, kind)
    name_idx = entity_name_index(headers, kind)
    avg_idx = find_header_index(headers, "avg_place")
    win_idx = find_header_index(headers, "win_rate")
    top4_idx = find_header_index(headers, "top4_rate")
    freq_idx = find_header_index(headers, "frequency")
    sample_idx = find_header_index(headers, "sample_size")

    metric_indices = [avg_idx, win_idx, top4_idx, freq_idx, sample_idx]
    if name_idx is None or all(index is None for index in metric_indices):
        return [], {
            "reason": "unsupported_headers",
            "headers": headers,
            "table_index": table.get("table_index"),
        }

    entities: list[dict[str, Any]] = []

    for raw_row in rows[1:]:
        if not isinstance(raw_row, list) or name_idx >= len(raw_row):
            continue

        name = " ".join(str(raw_row[name_idx] or "").split())
        if not name:
            continue

        avg_place = (
            parse_avg_place(raw_row[avg_idx])
            if avg_idx is not None and avg_idx < len(raw_row)
            else None
        )
        win_rate = (
            parse_percent(raw_row[win_idx])
            if win_idx is not None and win_idx < len(raw_row)
            else None
        )
        top4_rate = (
            parse_percent(raw_row[top4_idx])
            if top4_idx is not None and top4_idx < len(raw_row)
            else None
        )

        frequency = None
        sample_size = None
        if freq_idx is not None and freq_idx < len(raw_row):
            frequency, sample_from_frequency = parse_frequency_cell(raw_row[freq_idx])
            sample_size = sample_from_frequency

        if sample_idx is not None and sample_idx < len(raw_row):
            explicit_sample = parse_sample_size(raw_row[sample_idx])
            if explicit_sample is not None:
                sample_size = explicit_sample

        if all(
            value is None
            for value in (avg_place, win_rate, top4_rate, frequency, sample_size)
        ):
            continue

        entity_id = resolve_entity_id(
            kind=kind,
            name=name,
            source_url=source_url,
            resolver=resolver,
        )

        entities.append(
            {
                "kind": kind,
                "id": entity_id,
                "name": name,
                "unit_ids": [],
                "trait_ids": [],
                "performance": {
                    "avg_place": avg_place,
                    "top4_rate": top4_rate,
                    "win_rate": win_rate,
                    "frequency": frequency,
                    "sample_size": sample_size,
                },
                "tags": [],
                "attributes": {},
            }
        )

    return entities, None


def parse_named_list_sentence(
    body: str,
    pattern: str,
) -> list[str]:
    match = re.search(pattern, body, re.IGNORECASE | re.DOTALL)
    if not match:
        return []

    value = " ".join(match.group(1).split())
    value = re.sub(r"\s+as the best.*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+in TFT.*$", "", value, flags=re.IGNORECASE)

    parts = re.split(r"\s*,\s*|\s+and\s+", value)
    return [part.strip() for part in parts if part.strip()]


def resolve_names(
    resolver: CatalogResolver,
    kind: str,
    names: list[str],
) -> list[str]:
    result: list[str] = []
    for name in names:
        resolved = resolver.resolve(kind, name)
        result.append(resolved or name)
    return result


def extract_detail_entity(
    raw: dict[str, Any],
    *,
    kind: str,
    source_url: str,
    resolver: CatalogResolver,
) -> dict[str, Any] | None:
    if kind not in {"unit", "trait", "augment", "item"}:
        return None

    path_slug = urlparse(source_url).path.rstrip("/").split("/")[-1]
    if not path_slug or path_slug in {"units", "traits", "augments", "items"}:
        return None

    title = str(raw.get("title") or "")
    headings = [str(v) for v in raw.get("headings") or [] if isinstance(v, str)]
    name = None
    for candidate in headings + [title]:
        cleaned = re.sub(r"\s+TFT.*$", "", candidate, flags=re.IGNORECASE).strip()
        if cleaned and len(cleaned) <= 100:
            name = cleaned
            break
    if not name:
        name = path_slug.replace("-", " ")

    body = str(raw.get("body_text") or "")
    avg_match = re.search(
        r"(\d+(?:\.\d+)?)\s*\n?\s*Avg Place",
        body,
        re.IGNORECASE,
    )
    avg_place = None
    if avg_match:
        value = float(avg_match.group(1))
        if 1.0 <= value <= 8.0:
            avg_place = value

    attributes: dict[str, Any] = {}

    if kind == "unit":
        recommended_names = parse_named_list_sentence(
            body,
            rf"We recommend\s+(.+?)\s+as the best build for\s+{re.escape(name)}",
        )
        top_names = parse_named_list_sentence(
            body,
            rf"The best items for\s+{re.escape(name)}\s+are\s+(.+?)(?:\n|Ranked|$)",
        )

        if recommended_names:
            attributes["recommended_item_names"] = recommended_names
            attributes["recommended_item_ids"] = resolve_names(
                resolver,
                "item",
                recommended_names,
            )

        if top_names:
            attributes["top_item_names"] = top_names
            attributes["top_item_ids"] = resolve_names(
                resolver,
                "item",
                top_names,
            )

        position_match = re.search(
            rf"{re.escape(name)}\s+should be positioned\s+(.+?)(?:\.|\n)",
            body,
            re.IGNORECASE,
        )
        if position_match:
            positioning = " ".join(position_match.group(1).split()).strip()
            if positioning:
                attributes["positioning"] = positioning

        sections = raw.get("sections") or []
        if isinstance(sections, list):
            for section in sections:
                if not isinstance(section, dict):
                    continue
                heading = str(section.get("heading") or "").casefold()
                if "recommended builds" in heading:
                    image_alts = [
                        str(value).strip()
                        for value in section.get("image_alts") or []
                        if str(value).strip()
                    ]
                    if image_alts:
                        attributes["recommended_build_image_alts"] = image_alts
                if "top items" in heading:
                    image_alts = [
                        str(value).strip()
                        for value in section.get("image_alts") or []
                        if str(value).strip()
                    ]
                    if image_alts:
                        attributes["top_item_image_alts"] = image_alts

    if avg_place is None and not attributes:
        return None

    return {
        "kind": kind,
        "id": resolve_entity_id(
            kind=kind,
            name=name,
            source_url=source_url,
            resolver=resolver,
        ),
        "name": name,
        "unit_ids": [],
        "trait_ids": [],
        "performance": {
            "avg_place": avg_place,
            "top4_rate": None,
            "win_rate": None,
            "frequency": None,
            "sample_size": None,
        },
        "tags": ["detail_page"],
        "attributes": attributes,
    }

def normalize_browser_snapshot(
    raw: dict[str, Any],
    *,
    resolver: CatalogResolver | None = None,
) -> dict[str, Any]:
    resolver = resolver or CatalogResolver.empty()

    source_url = str(raw.get("source_url") or raw.get("final_url") or "").strip()
    if not source_url:
        raise ValueError("browser snapshot source_url is required")

    captured_at_epoch = float(raw.get("captured_at_epoch") or 0.0)
    if not math.isfinite(captured_at_epoch) or captured_at_epoch <= 0:
        raise ValueError("captured_at_epoch must be finite and > 0")

    kind = page_kind(source_url, raw)
    context = infer_context(raw)

    entities: list[dict[str, Any]] = []
    unparsed_tables: list[dict[str, Any]] = []

    tables = raw.get("tables") or []
    if kind and isinstance(tables, list):
        for table in tables:
            if not isinstance(table, dict):
                continue
            parsed, unparsed = parse_table_entities(
                table,
                kind=kind,
                source_url=source_url,
                resolver=resolver,
            )
            entities.extend(parsed)
            if unparsed is not None:
                unparsed_tables.append(unparsed)

    detail = (
        extract_detail_entity(
            raw,
            kind=kind,
            source_url=source_url,
            resolver=resolver,
        )
        if kind
        else None
    )
    if detail is not None:
        existing_ids = {entity["id"] for entity in entities}
        if detail["id"] not in existing_ids:
            entities.append(detail)

    # Deduplicate by kind/id while preserving the richest metric record.
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for entity in entities:
        key = (entity["kind"], entity["id"])
        current = deduped.get(key)
        if current is None or _metric_count(entity) > _metric_count(current):
            deduped[key] = entity

    return {
        "schema_version": 1,
        "source": "metatft_public",
        "source_url": source_url,
        "captured_at_ms": int(round(captured_at_epoch * 1000)),
        **context,
        "entities": list(deduped.values()),
        "metadata": {
            "collector": str(raw.get("source") or "metatft_public_browser"),
            "page_kind": kind or "unknown",
            "tables_total": str(len(tables) if isinstance(tables, list) else 0),
            "tables_unparsed": str(len(unparsed_tables)),
            "links_total": str(len(raw.get("links") or [])),
            "repeated_blocks_total": str(len(raw.get("repeated_blocks") or [])),
            "sections_total": str(len(raw.get("sections") or [])),
        },
        "diagnostics": {
            "unparsed_tables": unparsed_tables,
        },
    }


def _metric_count(entity: dict[str, Any]) -> int:
    performance = entity.get("performance") or {}
    return sum(value is not None for value in performance.values())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize a raw browser-captured MetaTFT page into MetaSnapshot JSON."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--unit-catalog", type=Path)
    parser.add_argument("--item-catalog", type=Path)
    parser.add_argument("--trait-catalog", type=Path)
    args = parser.parse_args()

    resolver = CatalogResolver.from_catalogs(
        unit_catalog=args.unit_catalog,
        item_catalog=args.item_catalog,
        trait_catalog=args.trait_catalog,
    )
    normalized = normalize_browser_snapshot(
        load_raw(args.input),
        resolver=resolver,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "output": str(args.output),
                "source_url": normalized["source_url"],
                "patch": normalized["patch"],
                "set": normalized["set"],
                "entities": len(normalized["entities"]),
                "page_kind": normalized["metadata"]["page_kind"],
                "tables_unparsed": normalized["metadata"]["tables_unparsed"],
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
