from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class SourceSpec:
    url: str
    format: str
    ttl_seconds: int

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "SourceSpec":
        return cls(
            url=str(data["url"]),
            format=str(data.get("format", "bin")),
            ttl_seconds=max(0, int(data.get("ttl_seconds", 0))),
        )


def load_specs(path: Path) -> dict[str, SourceSpec]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {name: SourceSpec.from_mapping(spec) for name, spec in raw.items()}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_payload(data: bytes, fmt: str) -> None:
    if not data:
        raise ValueError("source payload is empty")
    if fmt == "json":
        json.loads(data)


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_name = tmp.name
    os.replace(temp_name, path)


def fetch_bytes(url: str, timeout_seconds: int = 60) -> tuple[bytes, dict[str, str]]:
    request = Request(
        url,
        headers={
            "User-Agent": "Agente-TFT/0.1 knowledge-sync",
            "Accept": "*/*",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        data = response.read()
        headers = {
            "etag": response.headers.get("ETag", ""),
            "last_modified": response.headers.get("Last-Modified", ""),
            "content_type": response.headers.get("Content-Type", ""),
        }
    return data, headers


def read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"manifest_version": 1, "sources": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def target_extension(fmt: str) -> str:
    return ".json" if fmt == "json" else ".bin"


def is_fresh(
    manifest: dict[str, Any],
    source_name: str,
    target: Path,
    ttl_seconds: int,
    now_epoch: float,
) -> bool:
    if ttl_seconds <= 0 or not target.exists():
        return False
    entry = manifest.get("sources", {}).get(source_name)
    if not entry:
        return False
    downloaded = float(entry.get("downloaded_at_epoch", 0))
    return downloaded + ttl_seconds > now_epoch


def sync_source(
    source_name: str,
    spec: SourceSpec,
    output_dir: Path,
    manifest_path: Path,
    *,
    force: bool = False,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    now_epoch = time.time() if now_epoch is None else now_epoch
    manifest = read_manifest(manifest_path)
    target = output_dir / f"{source_name}{target_extension(spec.format)}"

    if not force and is_fresh(
        manifest, source_name, target, spec.ttl_seconds, now_epoch
    ):
        return {
            "source": source_name,
            "status": "fresh",
            "path": str(target),
        }

    data, headers = fetch_bytes(spec.url)
    validate_payload(data, spec.format)
    digest = sha256_bytes(data)

    atomic_write(target, data)

    manifest.setdefault("manifest_version", 1)
    manifest.setdefault("sources", {})
    manifest["sources"][source_name] = {
        "url": spec.url,
        "format": spec.format,
        "downloaded_at_epoch": now_epoch,
        "ttl_seconds": spec.ttl_seconds,
        "sha256": digest,
        "size_bytes": len(data),
        "etag": headers.get("etag", ""),
        "last_modified": headers.get("last_modified", ""),
        "content_type": headers.get("content_type", ""),
        "path": str(target),
    }

    atomic_write(
        manifest_path,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )

    return {
        "source": source_name,
        "status": "updated",
        "path": str(target),
        "sha256": digest,
        "size_bytes": len(data),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize Agente TFT Knowledge Pack source files."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("sources.json"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("knowledge/raw"),
    )
    parser.add_argument(
        "--source",
        default="all",
        help="source name from sources.json, or 'all'",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--list", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    specs = load_specs(args.config)

    if args.list:
        for name, spec in specs.items():
            print(f"{name}\t{spec.url}")
        return 0

    if args.source == "all":
        selected = list(specs.items())
    else:
        if args.source not in specs:
            raise SystemExit(f"unknown source: {args.source}")
        selected = [(args.source, specs[args.source])]

    manifest = args.output_dir / "manifest.json"

    results = []
    for name, spec in selected:
        results.append(
            sync_source(
                name,
                spec,
                args.output_dir,
                manifest,
                force=args.force,
            )
        )

    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
