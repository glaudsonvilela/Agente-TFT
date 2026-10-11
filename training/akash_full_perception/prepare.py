#!/usr/bin/env python3
"""Build a reset-only, reviewable Akash experiment bundle.

The bundle carries the complete current perception context. Only user-confirmed
champion crops become supervised labels; other HUD proposals remain evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import tarfile


REPO = Path(__file__).resolve().parents[2]
RESET = Path("/mnt/sherlock-ssd/AgenteTFT/champion-reset-20261009")
DINO = Path("/mnt/sherlock-ssd/AgenteTFT/diagnostics/bigbanana-neural-bundle-20261007-1535/learner/encoder/dino.onnx")
REPLAYS = (
    "replay-cyber-arena-25s-1080.mp4",
    "replay-pond-25s-1080.mp4",
    "replay-multi-arena-50s-1080.mp4",
    "replay-profile-12s.mp4",
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def add_file(source: Path, target: Path, inventory: list[dict]) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    bundle_root = next(parent for parent in reversed(target.parents) if parent.name in {"core", "replay"})
    inventory.append({"path": str(target.relative_to(bundle_root)),
                      "sha256": digest(target), "bytes": target.stat().st_size})


def add_tree(source: Path, target: Path, inventory: list[dict], suffixes: set[str] | None = None) -> None:
    for path in sorted(source.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and (suffixes is None or path.suffix in suffixes):
            add_file(path, target / path.relative_to(source), inventory)


def archive(folder: Path, path: Path) -> None:
    with tarfile.open(path, "w:gz") as tar:
        for item in sorted(folder.rglob("*")):
            if item.is_file():
                tar.add(item, arcname=str(item.relative_to(folder)), recursive=False)


def build(output: Path, reset: Path = RESET) -> dict:
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Output must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    core = output / "core"
    replay = output / "replay"
    core.mkdir()
    replay.mkdir()
    inventory: list[dict] = []
    roster_path = reset / "roster/unified-reviewed-candidates-20261010.json"
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    rows = [r for r in roster["records"] if r.get("review_status") == "user_confirmed_candidate"]
    if not rows or roster.get("old_weights_used") is not False:
        raise ValueError("Expected reset-only, user-confirmed champion records")
    names = sorted({r["champion"] for r in rows})
    packed = []
    for index, row in enumerate(rows):
        source = Path(row["natural_crop"])
        if digest(source) != row["natural_crop_sha256"]:
            raise ValueError(f"Crop hash mismatch: {row['review_id']}")
        relative = Path("champions") / f"{index:04d}{source.suffix.lower()}"
        add_file(source, core / relative, inventory)
        packed.append({
            "review_id": row["review_id"], "champion": row["champion"],
            "game_id": row.get("game_id"), "zone": row.get("zone"),
            "image": str(relative), "sha256": row["natural_crop_sha256"],
            "source_video": Path(row["source_video_local"]).stem,
            "source_second": row.get("source_second"),
            "review_status": row["review_status"],
        })
    (core / "champions.json").write_text(json.dumps(packed, ensure_ascii=False, indent=2) + "\n")
    add_file(reset / "roster/set18-shop-roster-20261010.json", core / "roster/all-65.json", inventory)
    add_file(reset / "experiments/full-hud-readiness-20261010/report.json", core / "audits/full-hud-readiness.json", inventory)
    add_file(DINO, core / "models/dino.onnx", inventory)
    add_tree(REPO / "apps/hud_mapper/hm", core / "software/hm", inventory, {".py"})
    add_tree(REPO / "apps/hud_mapper/assets", core / "software/assets", inventory)
    add_tree(REPO / "training", core / "software/training", inventory, {".py"})
    add_tree(REPO / "telemetry", core / "software/telemetry", inventory, {".py", ".json", ".md"})
    add_tree(REPO / "ui/tauri-design", core / "software/ui", inventory, {".js", ".json", ".html", ".css"})
    add_tree(REPO / "configs", core / "software/configs", inventory, {".json", ".toml", ".yaml", ".yml"})
    add_tree(REPO / "rust/crates", core / "software/rust/crates", inventory, {".rs", ".toml", ".md"})
    add_tree(REPO / "knowledge/releases", core / "software/knowledge/releases", inventory, {".json"})
    add_tree(REPO / "build/hm4-live-assets/board-hub-icons", core / "software/item-icons", inventory, {".png"})
    add_tree(REPO / "build/hm4-live-assets/models/item-icons", core / "software/item-model", inventory,
             {".onnx", ".json"})
    for source_name in ("train.py",):
        add_file(Path(__file__).parent / source_name, core / source_name, inventory)
    replay_inventory: list[dict] = []
    for name in REPLAYS:
        add_file(reset / "experiments/full-hud-readiness-20261010" / name,
                 replay / "replays" / name, replay_inventory)
    release = {
        "schema_version": 1,
        "purpose": "experimental_akash_full_perception_reset_only",
        "champion_supervision": "user_confirmed_candidate_only",
        "old_tft_weights_included": False,
        "model_predictions_used_as_labels": False,
        "champion_crops": len(rows), "champion_classes_in_crops": len(names),
        "roster_classes": 65,
        "champion_counts": dict(sorted(Counter(r["champion"] for r in rows).items())),
        "component_states": {
            "champions": "experimental_training",
            "map_board_enemy_board_benches": "calibration_and_code_included_not_supervised_training",
            "items": "existing_catalog_icons_and_model_included_not_retrained",
            "shop_gold_xp_level_stage_hp_player_names_streak": "reader_code_and_profiles_included_not_retrained",
            "synergies": "trait_rules_and_code_included_not_retrained",
            "telemetry_opponents": "rust_and_python_code_included_not_retrained",
        },
        "quality_limit": "Five distinct approved poses and full HUD labels are still incomplete; no production promotion.",
        "inventory": inventory,
        "replay_inventory": replay_inventory,
    }
    (core / "bundle-manifest.json").write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n")
    archive(core, output / "akash-core.tar.gz")
    archive(replay, output / "akash-replays.tar.gz")
    summary = {k: release[k] for k in ("purpose", "champion_crops", "champion_classes_in_crops", "roster_classes", "component_states")}
    summary["archives"] = {name: {"bytes": (output / name).stat().st_size, "sha256": digest(output / name)}
                           for name in ("akash-core.tar.gz", "akash-replays.tar.gz")}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reset", type=Path, default=RESET)
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.reset), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
