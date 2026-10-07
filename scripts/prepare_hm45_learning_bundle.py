#!/usr/bin/env python3
"""Stage a portable frozen recognizer baseline for the HM4.5 WSL learner.

The source selection/run-metadata may point to private SSD paths. This tool
copies only the sealed assets required for post-session challenger training and
rewrites paths to the fixed /opt/agente-tft/learner layout used inside WSL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

DEFAULT_SELECTION = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/missing-classes-training-20261005/"
    "optimizer-study-resume-20261005-101237/optimizer-study-selection.json"
)
WSL_ROOT = Path("/opt/agente-tft/learner")


def die(message: str) -> "NoReturn":
    raise SystemExit(f"HM45_LEARNER_BUNDLE_ERROR: {message}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"cannot read JSON {path}: {exc}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def required(value: str | Path, name: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.exists():
        die(f"{name} not found: {path}")
    return path


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    selection_path = required(args.selection, "selection")
    output = args.output.expanduser()
    if output.exists():
        die(f"new output directory required: {output}")
    output.mkdir(parents=True)

    selection = load_json(selection_path)
    if selection.get("status") != "selection_frozen_before_minjo_kh_evaluation":
        die("selection is not frozen before Minjo/KH development evaluation")
    if selection.get("selected_arm") != "optimizer-default-parity":
        die("portable learner currently requires optimizer-default-parity champion")

    metadata_path = required(selection_path.parent / "run-metadata.json", "run metadata")
    metadata = load_json(metadata_path)

    model = required(str(selection.get("selected_model_path", "")), "selected model")
    model_sha = str(selection.get("selected_model_sha256", ""))
    if not model_sha or sha256(model) != model_sha:
        die("selected model checksum mismatch")

    encoder = required(str(metadata.get("encoder", "")), "encoder")
    encoder_sha = str(metadata.get("encoder_sha256", ""))
    if not encoder_sha or sha256(encoder) != encoder_sha:
        die("encoder checksum mismatch")

    annotations = required(str(metadata.get("annotations", "")), "annotations")
    images = required(str(metadata.get("images", "")), "images root")
    reference = required(str(metadata.get("reference", "")), "reference root")
    if not images.is_dir() or not reference.is_dir():
        die("images/reference must be directories")

    doc = load_json(annotations)
    frames = doc.get("frames")
    if not isinstance(frames, list) or not frames:
        die("annotations frames missing")

    portable_images = output / "data" / "images"
    copied_images = 0
    copied_bytes = 0
    for frame in frames:
        if not isinstance(frame, dict) or not isinstance(frame.get("image"), str):
            die("invalid frame image path")
        relative = Path(frame["image"])
        if relative.is_absolute() or ".." in relative.parts:
            die(f"unsafe annotation image path: {relative}")
        src = (images / relative).resolve()
        if not src.is_file() or not src.is_relative_to(images):
            die(f"annotation image missing/outside root: {relative}")
        dst = portable_images / relative
        copy_file(src, dst)
        copied_images += 1
        copied_bytes += dst.stat().st_size

    portable_annotations = output / "data" / "annotations.json"
    copy_file(annotations, portable_annotations)
    portable_model = output / "model" / "dino-head.json"
    copy_file(model, portable_model)
    portable_encoder = output / "encoder" / "dino.onnx"
    copy_file(encoder, portable_encoder)
    shutil.copytree(reference, output / "reference")

    rewritten_selection = dict(selection)
    rewritten_selection["selected_model_path"] = str(WSL_ROOT / "model" / "dino-head.json")
    rewritten_selection["portable_wsl_bundle"] = True
    rewritten_selection["source_selection_sha256"] = sha256(selection_path)

    rewritten_metadata = dict(metadata)
    rewritten_metadata.update(
        {
            "annotations": str(WSL_ROOT / "data" / "annotations.json"),
            "images": str(WSL_ROOT / "data" / "images"),
            "reference": str(WSL_ROOT / "reference"),
            "encoder": str(WSL_ROOT / "encoder" / "dino.onnx"),
            "onnxruntime": str(WSL_ROOT / "libonnxruntime.so"),
            "portable_wsl_bundle": True,
            "source_run_metadata_sha256": sha256(metadata_path),
        }
    )

    (output / "selection.json").write_text(
        json.dumps(rewritten_selection, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "run-metadata.json").write_text(
        json.dumps(rewritten_metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": 1,
        "policy": "hm45_portable_frozen_recognizer_baseline_v1",
        "champion": "optimizer-default-parity",
        "selection_status": selection["status"],
        "model_sha256": model_sha,
        "encoder_sha256": encoder_sha,
        "annotations_sha256": sha256(portable_annotations),
        "reference_json_sha256": sha256(output / "reference" / "reference.json"),
        "image_files": copied_images,
        "image_bytes": copied_bytes,
        "validation_named": selection.get("selected_metrics", {}).get("named"),
        "validation_correct": selection.get("selected_metrics", {}).get("correct"),
        "validation_macro_recall": selection.get("selected_metrics", {}).get("named_macro_recall"),
        "minjo_kh_included": False,
        "active_runtime_model": False,
        "runtime_approved": False,
    }
    (output / "learner-package.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("HM45_LEARNER_BUNDLE_OK=true")
    print(f"OUTPUT={output}")
    print(f"IMAGE_FILES={copied_images}")
    print(f"IMAGE_BYTES={copied_bytes}")
    print(f"MODEL_SHA256={model_sha}")
    print(f"ENCODER_SHA256={encoder_sha}")
    print("MINJO_KH_INCLUDED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
