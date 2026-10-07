#!/usr/bin/env python3
"""Persist admitted autonomous supervision into the central BigBANANA corpus.

Only already-adjudicated gold and conservative silver rows are accepted.
Pixels are deduplicated globally. Conflicting identities for the same pixels
fail closed. The corpus is training-only and never changes labels.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any


def die(message: str) -> "NoReturn":
    raise SystemExit(f"AUTONOMOUS_CORPUS_ERROR: {message}")


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"cannot read {path}: {exc}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def validate_row(row: Any, source_id: str, tier: str) -> tuple[str, str]:
    if not isinstance(row, dict):
        die(f"{tier} row must be object")
    if (
        row.get("source_id") != source_id
        or row.get("training_eligible") is not True
        or row.get("human_review_required") is not False
    ):
        die(f"{tier} provenance mismatch")
    unit_id = row.get("unit_id")
    pixel = row.get("pixel_sha256")
    if not isinstance(unit_id, str) or not unit_id:
        die(f"{tier} unit_id missing")
    if not isinstance(pixel, str) or len(pixel) != 64 or any(c not in "0123456789abcdef" for c in pixel):
        die(f"{tier} pixel sha invalid")
    if tier == "gold":
        if (
            row.get("decision") not in {"supported", "bootstrap_supported"}
            or row.get("label_source") not in {
                "autonomous_shop_purchase_bench_consensus_v1",
                "autonomous_tooltip_temporal_consensus_v1",
            }
            or row.get("model_prediction_used_as_label") is not False
        ):
            die("gold provenance contract failed")
    else:
        weight = row.get("recommended_training_weight")
        if (
            row.get("supervision_tier") != "silver_auto"
            or row.get("label_source") not in {
                "silver_auto_dino_frozen_temporal_consensus_v1",
                "silver_auto_shop_multiteacher_temporal_v1",
            }
            or type(weight) not in (int, float)
            or not 0.0 < float(weight) <= 0.35
        ):
            die("silver provenance/weight contract failed")
    return unit_id, pixel


def copy_row(
    row: dict[str, Any],
    *,
    source_id: str,
    tier: str,
    collection: Path,
    source_root: Path,
    pixel_index: dict[str, dict[str, str]],
) -> dict[str, Any] | None:
    unit_id, pixel = validate_row(row, source_id, tier)
    existing = pixel_index.get(pixel)
    if existing is not None:
        if existing.get("unit_id") != unit_id:
            die(f"pixel identity conflict: {pixel}")
        return None

    relative = row.get("crop")
    if not isinstance(relative, str) or not relative:
        die(f"{tier} crop missing")
    source = (collection / relative).resolve()
    if not source.is_file() or not source.is_relative_to(collection):
        die(f"{tier} crop outside collection")
    if sha256(source) == pixel:
        # File hash is not the pixel hash for PNG crops; this branch is fine but
        # never used as identity proof. The row's pixel hash remains authoritative
        # and is rechecked by the Rust trainer after image decode.
        pass

    target_rel = Path("crops") / f"{pixel}.png"
    target = source_root / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        die(f"unexpected pre-existing corpus crop: {target}")
    shutil.copy2(source, target)

    rewritten = dict(row)
    rewritten["crop"] = target_rel.as_posix()
    rewritten["corpus_ingested"] = True
    rewritten["corpus_source_id"] = source_id
    pixel_index[pixel] = {
        "source_id": source_id,
        "unit_id": unit_id,
        "tier": tier,
    }
    return rewritten


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--collection", type=Path, required=True)
    p.add_argument("--gold", type=Path, required=True)
    p.add_argument("--silver", type=Path, required=True)
    p.add_argument("--source-id", required=True)
    args = p.parse_args()

    manifest_path = args.manifest.expanduser().resolve()
    corpus_root = manifest_path.parent
    corpus_root.mkdir(parents=True, exist_ok=True)
    collection = args.collection.expanduser().resolve()
    if not collection.is_dir():
        die("collection missing")
    gold_rows = load(args.gold)
    silver_rows = load(args.silver)
    if not isinstance(gold_rows, list) or not gold_rows:
        die("gold rows must be a nonempty list")
    if not isinstance(silver_rows, list):
        die("silver rows must be a list")

    lock_path = corpus_root / ".corpus.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)

        manifest = (
            load(manifest_path)
            if manifest_path.is_file()
            else {
                "schema_version": 1,
                "policy": "central_autonomous_corpus_v1",
                "sources": [],
                "human_review_required": False,
            }
        )
        if (
            manifest.get("schema_version") != 1
            or manifest.get("policy") != "central_autonomous_corpus_v1"
            or not isinstance(manifest.get("sources"), list)
        ):
            die("existing corpus manifest incompatible")

        existing_source = next(
            (row for row in manifest["sources"] if row.get("source_id") == args.source_id),
            None,
        )
        if existing_source is not None:
            print("AUTONOMOUS_CORPUS_RESUME=already_ingested")
            print(f"SOURCE_ID={args.source_id}")
            print(f"SOURCES={len(manifest['sources'])}")
            return 0

        index_path = corpus_root / "pixel-index.json"
        pixel_index = load(index_path) if index_path.is_file() else {}
        if not isinstance(pixel_index, dict):
            die("pixel index incompatible")

        source_key = hashlib.sha256(args.source_id.encode("utf-8")).hexdigest()
        source_root = corpus_root / "sources" / source_key
        if source_root.exists():
            die("source directory exists without manifest entry")
        source_root.mkdir(parents=True)

        accepted_gold = []
        accepted_silver = []
        try:
            for row in gold_rows:
                copied = copy_row(
                    row,
                    source_id=args.source_id,
                    tier="gold",
                    collection=collection,
                    source_root=source_root,
                    pixel_index=pixel_index,
                )
                if copied is not None:
                    accepted_gold.append(copied)
            for row in silver_rows:
                copied = copy_row(
                    row,
                    source_id=args.source_id,
                    tier="silver",
                    collection=collection,
                    source_root=source_root,
                    pixel_index=pixel_index,
                )
                if copied is not None:
                    accepted_silver.append(copied)

            if not accepted_gold:
                shutil.rmtree(source_root)
                print("AUTONOMOUS_CORPUS_OK=true")
                print("INGESTED=0")
                print("REASON=no_unique_gold")
                return 0

            gold_path = source_root / "gold.json"
            silver_path = source_root / "silver.json"
            write_atomic(gold_path, accepted_gold)
            write_atomic(silver_path, accepted_silver)

            config = {
                "collection": str(source_root),
                "source_id": args.source_id,
                "gold_labels": str(gold_path),
                "silver_labels": str(silver_path),
                "gold_weight": 1.0,
                "silver_weight": 0.35,
                "use_declared_silver_weights": True,
                "gold_count": len(accepted_gold),
                "silver_count": len(accepted_silver),
            }
            manifest["sources"].append(config)
            manifest["sources"].sort(key=lambda row: row["source_id"])
            manifest["counts"] = {
                "sources": len(manifest["sources"]),
                "gold": sum(int(row.get("gold_count", 0)) for row in manifest["sources"]),
                "silver": sum(int(row.get("silver_count", 0)) for row in manifest["sources"]),
                "unique_pixels": len(pixel_index),
            }
            write_atomic(index_path, pixel_index)
            write_atomic(manifest_path, manifest)
        except Exception:
            if source_root.exists() and not any(
                row.get("source_id") == args.source_id for row in manifest.get("sources", [])
            ):
                shutil.rmtree(source_root, ignore_errors=True)
            raise

    print("AUTONOMOUS_CORPUS_OK=true")
    print(f"SOURCE_ID={args.source_id}")
    print(f"GOLD_ADDED={len(accepted_gold)}")
    print(f"SILVER_ADDED={len(accepted_silver)}")
    print(f"SOURCES={len(manifest['sources'])}")
    print(f"UNIQUE_PIXELS={len(pixel_index)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
