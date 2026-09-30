from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from ingestion.build_item_catalog import build_catalog as build_item_catalog
from ingestion.build_trait_catalog import build_catalog as build_trait_catalog
from ingestion.build_unit_catalog import (
    build_catalog as build_unit_catalog,
    find_set,
    iter_sets,
    load_json,
)


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_catalog(path: Path, value: Any) -> dict[str, Any]:
    data = (
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    path.write_bytes(data)
    return {
        "path": path.name,
        "sha256": sha256_bytes(data),
        "size_bytes": len(data),
    }


def build_pack(
    source: dict[str, Any],
    *,
    set_selector: str,
    output_dir: Path,
) -> dict[str, Any]:
    selected = find_set(iter_sets(source), set_selector)
    output_dir.mkdir(parents=True, exist_ok=True)

    units = build_unit_catalog(source, selected)
    items = build_item_catalog(source)
    traits = build_trait_catalog(source, selected.key)

    files = {
        "units": write_catalog(output_dir / "units.json", units),
        "items": write_catalog(output_dir / "items.json", items),
        "traits": write_catalog(output_dir / "traits.json", traits),
    }

    identity = {
        "schema_version": 1,
        "source": "communitydragon_tft",
        "set": {
            "key": selected.key,
            "number": selected.number,
            "name": selected.name,
        },
        "counts": {
            "units": units["champion_count"],
            "items": items["item_count"],
            "traits": traits["trait_count"],
        },
        "files": files,
    }

    pack_hash = sha256_bytes(canonical_json_bytes(identity))
    manifest = {
        **identity,
        "pack_sha256": pack_hash,
    }
    write_catalog(output_dir / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a local TFT Knowledge Pack for one explicit set."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--set", dest="set_selector", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    source = load_json(args.source)
    manifest = build_pack(
        source,
        set_selector=args.set_selector,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "set": manifest["set"],
                "counts": manifest["counts"],
                "pack_sha256": manifest["pack_sha256"],
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
