from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
import time
import urllib.robotparser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ALLOWED_HOSTS = {"metatft.com", "www.metatft.com"}
ALLOWED_PREFIXES = (
    "/comps",
    "/pro-comps",
    "/units",
    "/items",
    "/traits",
    "/augments",
    "/augment-comparison",
    "/explorer",
    "/leaderboard",
)
USER_AGENT = "Agente-TFT-MetaCollector/0.1 (+local research cache)"


def validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("MetaTFT URL must use https")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("URL must point to metatft.com")
    if not any(parsed.path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        raise ValueError(f"MetaTFT path is not allowlisted: {parsed.path}")
    return url


def slug_for_url(url: str) -> str:
    parsed = urlparse(url)
    raw = (parsed.path.strip("/") or "home") + ("?" + parsed.query if parsed.query else "")
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in raw)[:120]
    return f"{safe}-{digest}"


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")

    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write(data)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_name = tmp.name

    os.replace(temp_name, path)


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "captures": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("collector manifest must be a JSON object")
    value.setdefault("schema_version", 1)
    value.setdefault("captures", {})
    return value


def due_for_capture(
    manifest: dict[str, Any],
    url: str,
    *,
    now_epoch: float,
    min_interval_seconds: int,
) -> bool:
    if min_interval_seconds <= 0:
        return True

    entry = manifest.get("captures", {}).get(url)
    if not isinstance(entry, dict):
        return True

    last = float(entry.get("captured_at_epoch", 0))
    return last + min_interval_seconds <= now_epoch


def robots_allows(url: str) -> bool:
    validate_public_url(url)
    robots = urllib.robotparser.RobotFileParser()
    robots.set_url("https://www.metatft.com/robots.txt")
    robots.read()
    return robots.can_fetch(USER_AGENT, url)


async def capture_public_page(
    url: str,
    *,
    timeout_ms: int = 30_000,
    settle_ms: int = 3_000,
) -> dict[str, Any]:
    validate_public_url(url)

    if not robots_allows(url):
        raise PermissionError(f"robots.txt does not allow collection: {url}")

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Install with: "
            "python -m pip install playwright && playwright install chromium"
        ) from exc

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(
                user_agent=USER_AGENT,
                viewport={"width": 1600, "height": 1000},
            )
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            await page.wait_for_timeout(settle_ms)

            snapshot = await page.evaluate(
                """() => {
                    const visibleText = (el) => {
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') return '';
                        return (el.innerText || '').trim();
                    };

                    const tables = [...document.querySelectorAll('table')].map((table, tableIndex) => {
                        const rows = [...table.querySelectorAll('tr')].map(row =>
                            [...row.querySelectorAll('th,td')].map(cell => visibleText(cell))
                        );
                        return { table_index: tableIndex, rows };
                    });

                    const headings = [...document.querySelectorAll('h1,h2,h3')]
                        .map(el => visibleText(el))
                        .filter(Boolean);

                    return {
                        title: document.title,
                        final_url: location.href,
                        headings,
                        tables,
                        body_text: document.body ? document.body.innerText : ''
                    };
                }"""
            )

            return {
                "schema_version": 1,
                "source": "metatft_public_browser",
                "source_url": url,
                "captured_at_epoch": time.time(),
                "title": snapshot.get("title"),
                "final_url": snapshot.get("final_url"),
                "headings": snapshot.get("headings", []),
                "tables": snapshot.get("tables", []),
                "body_text": snapshot.get("body_text", ""),
            }
        finally:
            await browser.close()


async def collect(
    urls: list[str],
    *,
    output_dir: Path,
    min_interval_seconds: int,
    force: bool,
) -> dict[str, Any]:
    for url in urls:
        validate_public_url(url)

    manifest_path = output_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    now_epoch = time.time()
    results: list[dict[str, Any]] = []

    for url in urls:
        if not force and not due_for_capture(
            manifest,
            url,
            now_epoch=now_epoch,
            min_interval_seconds=min_interval_seconds,
        ):
            results.append({"url": url, "status": "fresh"})
            continue

        snapshot = await capture_public_page(url)
        filename = slug_for_url(url) + ".json"
        target = output_dir / filename
        atomic_write_json(target, snapshot)

        manifest["captures"][url] = {
            "captured_at_epoch": snapshot["captured_at_epoch"],
            "path": str(target),
            "sha256": hashlib.sha256(
                target.read_bytes()
            ).hexdigest(),
        }
        atomic_write_json(manifest_path, manifest)

        results.append({
            "url": url,
            "status": "updated",
            "path": str(target),
        })

    return {
        "schema_version": 1,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture visible public MetaTFT pages through a headless browser."
    )
    parser.add_argument("urls", nargs="+")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("knowledge/meta/raw/metatft"),
    )
    parser.add_argument(
        "--min-interval-seconds",
        type=int,
        default=900,
        help="Default 900s (15 min); avoids high-frequency collection.",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if args.min_interval_seconds < 0:
        raise SystemExit("--min-interval-seconds must be >= 0")

    result = asyncio.run(
        collect(
            args.urls,
            output_dir=args.output_dir,
            min_interval_seconds=args.min_interval_seconds,
            force=args.force,
        )
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
