#!/usr/bin/env python3
"""Inventory genuinely new TFT images on the Sherlock SSD.

This is review-only. It never assigns champion identities, never edits training
manifests, never runs a model, and never promotes images into training.

It compares byte hashes and RGB pixel hashes against every board-review manifest
under configs/training, classifies image geometry, groups candidates by source
directory, and writes a deterministic review inventory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_ROOT = Path("/mnt/sherlock-ssd/AgenteTFT")
DEFAULT_OUTPUT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/new-image-inventory-20261005"
)

SKIP_DIR_NAMES = {
    "target",
    ".git",
    "__pycache__",
    "embedding-cache",
    "optimizer-study-resume-20261005-101237",
}

# Directories with derived crops/models/evaluation products are not source images.
SKIP_PATH_MARKERS = (
    "/trained-",
    "/head/",
    "/models/",
    "/model/",
    "/crops/",
    "/contact-sheet",
    "/development-evaluation/",
    "/optimizer-study-resume-",
)


def die(msg: str) -> "NoReturn":
    raise SystemExit(f"NEW_IMAGE_INVENTORY_ERROR: {msg}")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def existing_manifest_hashes(repo: Path) -> tuple[set[str], set[str], dict[str, list[str]]]:
    file_hashes: set[str] = set()
    pixel_hashes: set[str] = set()
    sources: dict[str, list[str]] = defaultdict(list)

    for path in sorted((repo / "configs" / "training").glob("*.json")):
        try:
            doc = load_json(path)
        except Exception:
            continue
        if not isinstance(doc, dict) or doc.get("schema_version") != 2:
            continue
        frames = doc.get("frames")
        if not isinstance(frames, list):
            continue
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            fh = frame.get("sha256")
            ph = frame.get("pixel_sha256")
            if isinstance(fh, str) and len(fh) == 64:
                file_hashes.add(fh)
            if isinstance(ph, str) and len(ph) == 64:
                pixel_hashes.add(ph)
            src = frame.get("source_video_id") or frame.get("source_url")
            if isinstance(src, str) and isinstance(fh, str):
                sources[fh].append(src)
    return file_hashes, pixel_hashes, sources


def image_kind(width: int, height: int) -> str:
    if width >= 1280 and height >= 720:
        return "full_frame"
    if width == 128 and height == 144:
        return "native_unit_crop"
    if width >= 512 and height >= 512:
        return "large_reference_or_crop"
    if width >= 192 and height >= 108:
        return "medium_image"
    return "small_image"


def skipped(path: Path) -> bool:
    if any(part in SKIP_DIR_NAMES for part in path.parts):
        return True
    text = "/" + "/".join(path.parts) + "/"
    return any(marker in text for marker in SKIP_PATH_MARKERS)


def inventory(repo: Path, root: Path, output: Path, max_files: int | None) -> dict[str, Any]:
    try:
        from PIL import Image
    except Exception as exc:
        die(f"Pillow is required to inspect dimensions/pixel hashes: {exc}")

    known_file, known_pixel, known_sources = existing_manifest_hashes(repo)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    seen_file: set[str] = set()
    seen_pixel: set[str] = set()

    candidates = []
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIR_NAMES)
        base_path = Path(base)
        if skipped(base_path):
            dirs[:] = []
            continue
        for name in sorted(files):
            p = base_path / name
            if p.suffix.lower() in IMAGE_EXTS and not skipped(p):
                candidates.append(p)
                if max_files is not None and len(candidates) >= max_files:
                    break
        if max_files is not None and len(candidates) >= max_files:
            break

    for i, path in enumerate(candidates, 1):
        try:
            data = path.read_bytes()
            file_sha = sha256_bytes(data)
            with Image.open(path) as im:
                rgb = im.convert("RGB")
                width, height = rgb.size
                pixel_sha = sha256_bytes(rgb.tobytes())
        except Exception as exc:
            errors.append({"path": str(path), "error": str(exc)})
            continue

        duplicate_inside_scan = file_sha in seen_file or pixel_sha in seen_pixel
        seen_file.add(file_sha)
        seen_pixel.add(pixel_sha)

        known_by_file = file_sha in known_file
        known_by_pixel = pixel_sha in known_pixel
        genuinely_new = not known_by_file and not known_by_pixel and not duplicate_inside_scan

        rel = path.relative_to(root)
        rows.append(
            {
                "path": str(path),
                "relative_path": str(rel),
                "directory": str(rel.parent),
                "bytes": len(data),
                "width": width,
                "height": height,
                "kind": image_kind(width, height),
                "sha256": file_sha,
                "pixel_sha256": pixel_sha,
                "known_manifest_file_hash": known_by_file,
                "known_manifest_pixel_hash": known_by_pixel,
                "known_sources": sorted(set(known_sources.get(file_sha, []))),
                "duplicate_inside_scan": duplicate_inside_scan,
                "genuinely_new": genuinely_new,
                "review_status": "unreviewed",
                "model_prediction_used_as_label": False,
                "training_eligible": False,
            }
        )

    new_rows = [r for r in rows if r["genuinely_new"]]
    per_dir: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in new_rows:
        grouped[row["directory"]].append(row)
    for directory, items in sorted(grouped.items()):
        kinds = Counter(i["kind"] for i in items)
        per_dir[directory] = {
            "new_images": len(items),
            "kinds": dict(sorted(kinds.items())),
            "bytes": sum(i["bytes"] for i in items),
            "sample_paths": [i["relative_path"] for i in items[:12]],
        }

    result = {
        "schema_version": 1,
        "kind": "review_only_new_ssd_image_inventory",
        "root": str(root),
        "scanned_images": len(rows),
        "scan_errors": len(errors),
        "known_manifest_file_hashes": len(known_file),
        "known_manifest_pixel_hashes": len(known_pixel),
        "new_unique_images": len(new_rows),
        "new_full_frames": sum(r["kind"] == "full_frame" for r in new_rows),
        "new_native_unit_crops": sum(r["kind"] == "native_unit_crop" for r in new_rows),
        "new_other_images": sum(
            r["kind"] not in {"full_frame", "native_unit_crop"} for r in new_rows
        ),
        "directories": per_dir,
        "images": rows,
        "errors": errors,
        "policy": {
            "automatic_labels": False,
            "training_performed": False,
            "training_manifest_modified": False,
            "minjo_kh_may_enter_training": False,
            "review_required_before_training": True,
            "runtime_approved": False,
        },
        "next": (
            "Review genuinely_new full frames/crops, identify source provenance and "
            "champion identity without model labels, then create a new training-only "
            "board-review manifest. Prioritize missing Lux forms and single-source IDs."
        ),
    }

    if output.exists():
        die(f"output directory already exists: {output}")
    output.mkdir(parents=True)
    (output / "inventory.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    summary = {
        "scanned_images": result["scanned_images"],
        "scan_errors": result["scan_errors"],
        "new_unique_images": result["new_unique_images"],
        "new_full_frames": result["new_full_frames"],
        "new_native_unit_crops": result["new_native_unit_crops"],
        "new_other_images": result["new_other_images"],
        "top_directories": sorted(
            (
                {
                    "directory": d,
                    "new_images": info["new_images"],
                    "kinds": info["kinds"],
                }
                for d, info in per_dir.items()
            ),
            key=lambda x: (-x["new_images"], x["directory"]),
        )[:30],
        "runtime_approved": False,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-files", type=int)
    args = parser.parse_args()

    repo = args.repo.expanduser().resolve()
    root = args.root.expanduser().resolve()
    output = args.output.expanduser()

    if not (repo / "configs" / "training").is_dir():
        die(f"not an Agente-TFT checkout: {repo}")
    if not root.is_dir():
        die(f"SSD image root not found: {root}")
    if str(root).startswith("/mnt/sherlock-ssd") and not Path("/mnt/sherlock-ssd").is_mount():
        die("/mnt/sherlock-ssd is not mounted")
    if args.max_files is not None and args.max_files <= 0:
        die("--max-files must be positive")

    summary = inventory(repo, root, output, args.max_files)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nNEW_IMAGE_INVENTORY_OK=true")
    print(f"OUTPUT={output}")
    print(f"NEW_UNIQUE_IMAGES={summary['new_unique_images']}")
    print(f"NEW_FULL_FRAMES={summary['new_full_frames']}")
    print(f"NEW_NATIVE_UNIT_CROPS={summary['new_native_unit_crops']}")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
