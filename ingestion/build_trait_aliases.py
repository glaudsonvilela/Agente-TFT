"""Pin seasonal trait names in another locale to stable trait IDs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ingestion.build_trait_catalog import build_catalog
from ingestion.knowledge_release import canonical, read_release


def build(source: Path, release: Path, locale: str, source_build: str) -> dict:
    raw = source.read_bytes()
    catalog = build_catalog(json.loads(raw), "TFTSet18")
    manifest, components = read_release(release)
    if manifest["set"]["key"] != catalog["set"]["key"]:
        raise ValueError("Trait alias set mismatch")
    primary = {row["api_name"]: row["name"] for row in components["traits"]["traits"]}
    foreign = {row["api_name"]: row["name"] for row in catalog["traits"]}
    if set(primary) != set(foreign) or len(set(foreign.values())) != len(foreign):
        raise ValueError("Trait IDs or translated names are not unique")
    return dict(schema_version=1, set_key=catalog["set"]["key"], locale=locale,
                source_build=source_build,
                source_sha256=hashlib.sha256(raw).hexdigest(),
                target_release_sha256=manifest["release_sha256"],
                traits=[dict(api_name=key, name=foreign[key]) for key in sorted(primary)])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--locale", required=True)
    parser.add_argument("--source-build", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = build(args.source, args.release, args.locale, args.source_build)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical(data))


if __name__ == "__main__":
    main()
