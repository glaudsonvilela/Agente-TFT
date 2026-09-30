from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]+")


def load_catalog(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("champions"), list):
        raise ValueError("invalid unit catalog")
    return data


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_name = tmp.name
    os.replace(temp_name, path)


def sanitize_id(value: str) -> str:
    value = SAFE_ID.sub("_", value.strip())
    if not value:
        raise ValueError("empty api_name after sanitization")
    return value[:180]


def preferred_asset(champion: dict[str, Any]) -> str | None:
    for field in ("square_icon_url", "tile_icon_url", "icon_url"):
        value = champion.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def extension_from_url(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return suffix
    return ".bin"


def fetch_bytes(url: str, timeout_seconds: int = 60) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "Agente-TFT/0.1 unit-assets",
            "Accept": "image/*,*/*;q=0.1",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        data = response.read()
    if not data:
        raise ValueError(f"empty asset payload: {url}")
    return data


def validate_image_signature(data: bytes, extension: str) -> None:
    if extension == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("expected PNG signature")
    if extension in {".jpg", ".jpeg"} and not data.startswith(b"\xff\xd8"):
        raise ValueError("expected JPEG signature")
    if extension == ".webp" and not (
        len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    ):
        raise ValueError("expected WEBP signature")


def download_one(
    champion: dict[str, Any],
    output_dir: Path,
    *,
    force: bool,
) -> dict[str, Any]:
    api_name = str(champion.get("api_name") or "").strip()
    if not api_name:
        return {"status": "skipped", "reason": "missing_api_name"}

    url = preferred_asset(champion)
    if not url:
        return {
            "api_name": api_name,
            "status": "skipped",
            "reason": "missing_asset_url",
        }

    extension = extension_from_url(url)
    filename = sanitize_id(api_name) + extension
    target = output_dir / filename

    if target.exists() and not force:
        data = target.read_bytes()
        return {
            "api_name": api_name,
            "status": "cached",
            "url": url,
            "path": str(target),
            "sha256": sha256_bytes(data),
            "size_bytes": len(data),
        }

    data = fetch_bytes(url)
    validate_image_signature(data, extension)
    atomic_write(target, data)

    return {
        "api_name": api_name,
        "status": "updated",
        "url": url,
        "path": str(target),
        "sha256": sha256_bytes(data),
        "size_bytes": len(data),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download champion image assets from a normalized unit catalog."
    )
    parser.add_argument("catalog", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("knowledge/assets/units"),
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.workers <= 0 or args.workers > 32:
        raise SystemExit("--workers must be in [1,32]")

    catalog = load_catalog(args.catalog)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(
                download_one,
                champion,
                args.output_dir,
                force=args.force,
            )
            for champion in catalog["champions"]
        ]

        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    {
                        "status": "error",
                        "error": str(exc),
                    }
                )

    results.sort(key=lambda row: str(row.get("api_name", "")))
    manifest = {
        "schema_version": 1,
        "catalog_set": catalog.get("set"),
        "assets": results,
        "counts": {
            "total": len(results),
            "updated": sum(row.get("status") == "updated" for row in results),
            "cached": sum(row.get("status") == "cached" for row in results),
            "skipped": sum(row.get("status") == "skipped" for row in results),
            "errors": sum(row.get("status") == "error" for row in results),
        },
    }

    manifest_path = args.output_dir / "manifest.json"
    atomic_write(
        manifest_path,
        (json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
    )

    print(json.dumps(manifest["counts"], indent=2, sort_keys=True))
    return 1 if manifest["counts"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
