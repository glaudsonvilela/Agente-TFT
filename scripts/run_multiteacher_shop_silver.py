#!/usr/bin/env python3
"""Run train-only calibrated multi-teacher shop rescue.

This is a low-weight silver teacher for existing classes only. It never lowers
the gold OCR threshold, creates gold labels, bootstraps unseen classes, trains
weights, or requires human review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_SELECTION = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/missing-classes-training-20261005/"
    "optimizer-study-resume-20261005-101237/optimizer-study-selection.json"
)


def die(message: str) -> "NoReturn":
    raise SystemExit(f"MULTITEACHER_SHOP_SILVER_RUNNER_ERROR: {message}")


def required(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=True)
    except FileNotFoundError:
        die(f"required path not found: {path}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"cannot read JSON {path}: {exc}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_stream(command: list[str], cwd: Path, log: Path) -> None:
    print("+", " ".join(command), flush=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as handle:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            handle.write(line)
        code = proc.wait()
    if code != 0:
        die(f"native rescue failed ({code}); see {log}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    p.add_argument("--collection", type=Path, required=True)
    p.add_argument("--transitions", type=Path, required=True)
    p.add_argument("--target-id", action="append", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    repo = required(args.repo)
    selection_path = required(args.selection)
    collection = required(args.collection)
    transitions = required(args.transitions)
    output = args.output.expanduser()

    report_path = output / "report.json"
    if report_path.is_file():
        report = load_json(report_path)
        if (
            report.get("policy") == "silver_auto_shop_multiteacher_temporal_v1"
            and report.get("human_review_required") is False
            and report.get("training_performed") is False
        ):
            print("MULTITEACHER_SHOP_SILVER_RESUME=already_complete")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print("\nMULTITEACHER_SHOP_SILVER_OK=true")
            print(f"SILVER_AUTO_LABELS={report.get('silver_auto_labels')}")
            print(f"SILVER_AUTO_IDS={json.dumps(report.get('silver_auto_ids') or {}, sort_keys=True)}")
            print("RECOMMENDED_TRAINING_WEIGHT=0.20")
            print("HUMAN_REVIEW_REQUIRED=false")
            print("TRAINING_PERFORMED=false")
            print("RUNTIME_APPROVED=false")
            return 0
        die("existing output does not satisfy multi-teacher rescue contract")
    if output.exists():
        die("output exists but is incomplete; preserve it and choose a new --output")

    selection = load_json(selection_path)
    if selection.get("status") != "selection_frozen_before_minjo_kh_evaluation":
        die("baseline selection is not frozen before development evaluation")
    if selection.get("selected_arm") != "optimizer-default-parity":
        die("unexpected baseline selected arm")

    model = required(Path(str(selection.get("selected_model_path", ""))))
    model_sha = str(selection.get("selected_model_sha256", ""))
    if not model_sha or sha256_file(model) != model_sha:
        die("selected model hash mismatch")

    metadata = load_json(required(selection_path.parent / "run-metadata.json"))
    annotations = required(Path(str(metadata.get("annotations", ""))))
    images = required(Path(str(metadata.get("images", ""))))
    reference = required(Path(str(metadata.get("reference", ""))))
    encoder = required(Path(str(metadata.get("encoder", ""))))
    onnxruntime = required(Path(str(metadata.get("onnxruntime", ""))))
    encoder_sha = str(metadata.get("encoder_sha256", ""))
    if not encoder_sha or sha256_file(encoder) != encoder_sha:
        die("encoder hash mismatch")

    collection_report = load_json(required(collection / "report.json"))
    if not (
        collection_report.get("status") == "complete"
        and collection_report.get("collection_mode") == "annotation_only"
        and collection_report.get("training_performed") is False
        and collection_report.get("inference_performed") is False
    ):
        die("collection is not complete annotation-only")

    output.parent.mkdir(parents=True, exist_ok=True)
    spec_path = output.parent / f"{output.name}-spec.json"
    log_path = output.parent / f"{output.name}.log"
    if spec_path.exists() or log_path.exists():
        die("spec/log already exists; preserve prior attempt and choose a new --output")

    targets = sorted(set(args.target_id))
    spec = {
        "collection": str(collection),
        "transitions": str(transitions),
        "target_ids": targets,
        "annotations": str(annotations),
        "images": str(images),
        "reference": str(reference),
        "model": str(model),
        "model_sha256": model_sha,
        "encoder": str(encoder),
        "encoder_sha256": encoder_sha,
        "onnxruntime": str(onnxruntime),
        "output": str(output),
        "min_silver_ocr_confidence": 70.0,
        "gold_ocr_confidence": 94.0,
        "max_persistence_seconds": 8,
        "max_persistence_distance_px": 70.0,
        "retrieval_safety_margin": 0.03,
        "teacher_margin": 0.01,
        "min_confirmed_unique_crops": 2,
        "per_event_label_limit": 2,
        "per_target_label_limit": 24,
    }
    spec_path.write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    run_stream(
        [
            "cargo",
            "run",
            "--release",
            "--manifest-path",
            str(repo / "tools/unit-features-lab/Cargo.toml"),
            "--bin",
            "mine-multiteacher-shop-silver",
            "--",
            "--spec",
            str(spec_path),
        ],
        repo,
        log_path,
    )

    report = load_json(required(report_path))
    if report.get("human_review_required") is not False:
        die("rescue unexpectedly requires human review")
    if report.get("training_performed") is not False:
        die("rescue unexpectedly reports training")
    if abs(float(report.get("recommended_training_weight", -1)) - 0.20) > 1e-9:
        die("unexpected rescue training weight")

    print("\nMULTITEACHER_SHOP_SILVER_OK=true")
    print(f"OUTPUT={output}")
    print(f"SILVER_AUTO_LABELS={report.get('silver_auto_labels')}")
    print(f"SILVER_AUTO_IDS={json.dumps(report.get('silver_auto_ids') or {}, sort_keys=True)}")
    print(f"CALIBRATION={json.dumps(report.get('calibration') or {}, sort_keys=True)}")
    print(f"REJECTED={json.dumps(report.get('rejected') or {}, sort_keys=True)}")
    print("GOLD_OCR_THRESHOLD_UNCHANGED=94")
    print("RECOMMENDED_TRAINING_WEIGHT=0.20")
    print("HUMAN_REVIEW_REQUIRED=false")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
