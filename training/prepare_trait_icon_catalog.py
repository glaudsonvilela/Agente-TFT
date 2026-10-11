"""Fetch exact Set 18 portrait assets from Data Dragon and the game export.

The 65 shop units have Riot splash images.  Nine game-only Lux variants also
appear in trait tooltips, so all 74 receive their native square/tile assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import urlopen


VERSION = "16.20.1"
COMMUNITY_DRAGON_BUILD = "16.20"
COMMUNITY_DRAGON_EXPORT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/patch-18.4-20261007/pt_br-16.20.json"
)
ROSTER = Path(
    "/mnt/sherlock-ssd/AgenteTFT/champion-reset-20261009/experiments/"
    "combined-dino-corpus-20261011/source/roster/all-65.json"
)
DEFAULT_OUTPUT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/champion-reset-20261009/experiments/"
    "trait-icon-recognition-20261011/catalog"
)


def download(url: str) -> bytes:
    from urllib.request import Request
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/png,application/json,*/*"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))["rows"]
    url = f"https://ddragon.leagueoflegends.com/cdn/{VERSION}/data/pt_BR/tft-champion.json"
    data = json.loads(download(url))["data"]
    export_bytes = COMMUNITY_DRAGON_EXPORT.read_bytes()
    export = json.loads(export_bytes)
    set18 = next(item for item in export["setData"] if item.get("number") == 18)
    game_units = {item["apiName"]: item for item in set18["champions"]}
    entries = []
    for row in roster:
        key = row["riot_key"]
        if key not in data:
            raise ValueError(f"Riot key absent in {VERSION}: {key}")
        if row["game_id"] not in game_units:
            raise ValueError(f"Game export missing {row['game_id']}")
        icon = data[key]["image"]["full"]
        ui_assets = {}
        for kind in ("tileIcon", "squareIcon"):
            asset = game_units[row["game_id"]][kind]
            if not asset.startswith("assets/") or not asset.endswith(".tex"):
                raise ValueError(f"Bad {kind} path for {row['game_id']}: {asset}")
            png_path = asset[:-4].lower() + ".png"
            ui_assets[kind] = {
                "game_path": asset,
                "url": f"https://raw.communitydragon.org/{COMMUNITY_DRAGON_BUILD}/game/{png_path}",
                "file": f"{kind}/{row['game_id']}.png",
            }
        entries.append({
            "id": row["game_id"], "name": row["name_pt_br"],
            "cost": row["cost"], "riot_key": key, "icon": icon,
            "url": f"https://ddragon.leagueoflegends.com/cdn/{VERSION}/img/tft-champion/{icon}",
            "file": f"{row['game_id']}.png",
            "ui_assets": ui_assets,
        })
    # Trait panels contain Lux variants even though the shop roster has just
    # 65 distinct units.  Import only the nine named, trait-bearing variants;
    # unrelated neutral monsters and armory objects are not champions here.
    for game in set18["champions"]:
        identity = game["apiName"]
        if not identity.startswith("DA_") or "Lux" not in identity or identity in {e["id"] for e in entries}:
            continue
        if not game.get("traits"):
            continue
        ui_assets = {}
        for kind in ("tileIcon", "squareIcon"):
            asset = game[kind]
            if not asset.startswith("assets/") or not asset.endswith(".tex"):
                raise ValueError(f"Bad {kind} path for {identity}: {asset}")
            png_path = asset[:-4].lower() + ".png"
            ui_assets[kind] = {
                "game_path": asset,
                "url": f"https://raw.communitydragon.org/{COMMUNITY_DRAGON_BUILD}/game/{png_path}",
                "file": f"{kind}/{identity}.png",
            }
        entries.append({"id": identity, "name": game["name"], "cost": game.get("cost"),
                        "source_kind": "game_variant", "ui_assets": ui_assets})

    def save(entry: dict) -> dict:
        if "url" not in entry:
            return entry
        path = out / entry["file"]
        raw = path.read_bytes() if path.is_file() else download(entry["url"])
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"Not a PNG: {entry['url']}")
        path.write_bytes(raw)
        return {**entry, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(save, entry) for entry in entries]
        saved = [future.result() for future in as_completed(futures)]
    saved.sort(key=lambda entry: entry["id"])
    jobs = [(entry, kind, asset) for entry in saved
            for kind, asset in entry["ui_assets"].items()]

    def save_ui(job: tuple) -> tuple:
        entry, kind, asset = job
        path = out / asset["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = path.read_bytes() if path.is_file() else download(asset["url"])
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"Not a PNG: {asset['url']}")
        path.write_bytes(raw)
        return entry["id"], kind, hashlib.sha256(raw).hexdigest(), len(raw)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for identity, kind, sha, size in pool.map(save_ui, jobs):
            entry = next(item for item in saved if item["id"] == identity)
            entry["ui_assets"][kind].update(sha256=sha, bytes=size)
    if len(saved) != 74 or len({entry["id"] for entry in saved}) != 74:
        raise ValueError("Expected 65 shop units and nine game-only Lux variants")
    manifest = {"schema_version": 1, "set": "TFTSet18", "patch": "18.4B",
                "data_dragon": VERSION, "source": url,
                "community_dragon_build": COMMUNITY_DRAGON_BUILD,
                "community_dragon_export_sha256": hashlib.sha256(export_bytes).hexdigest(),
                "entries": saved}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    print(f"Saved {len(saved)} game portraits to {out}")


if __name__ == "__main__":
    main()
