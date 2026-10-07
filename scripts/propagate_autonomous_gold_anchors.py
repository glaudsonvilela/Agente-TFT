#!/usr/bin/env python3
"""Propagate autonomous gold anchors with frozen neural/temporal consensus.

Inputs are the completed dense Elder Dragon collection and autonomous shop
gold labels. Output is silver_auto only; no training or human review occurs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from native_lab import command as native_lab_command
from typing import Any

DEFAULT_SELECTION = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/missing-classes-training-20261005/"
    "optimizer-study-resume-20261005-101237/optimizer-study-selection.json"
)
DEFAULT_COLLECTION = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/"
    "elder-dragon-shurkou/annotation-2s-shop-dense"
)
DEFAULT_ANCHORS = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/"
    "elder-dragon-shurkou/autonomous-shop-supervision-v1/"
    "shop-consensus/auto-labels.json"
)
DEFAULT_OUTPUT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/"
    "elder-dragon-shurkou/autonomous-propagation-v1"
)


def die(message: str) -> "NoReturn":
    raise SystemExit(f"AUTONOMOUS_PROPAGATION_RUNNER_ERROR: {message}")


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


def required(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=True)
    except FileNotFoundError:
        die(f"required path not found: {path}")


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
        die(f"native propagation failed ({code}); see {log}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    p.add_argument("--collection", type=Path, default=DEFAULT_COLLECTION)
    p.add_argument("--anchors", type=Path, default=DEFAULT_ANCHORS)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--max-time-delta-seconds", type=int, default=180)
    p.add_argument("--min-anchor-similarity", type=float, default=0.94)
    p.add_argument("--min-anchor-margin", type=float, default=0.05)
    p.add_argument("--min-classifier-margin", type=float, default=0.01)
    p.add_argument("--per-label-limit", type=int, default=32)
    args = p.parse_args()

    repo = required(args.repo)
    selection_path = required(args.selection)
    collection = required(args.collection)
    anchors = required(args.anchors)
    output = args.output.expanduser()

    if output.exists():
        report = output / "report.json"
        if report.is_file():
            doc = load_json(report)
            if (
                doc.get("policy")
                == "silver_auto_dino_frozen_temporal_consensus_v1"
                and doc.get("human_review_required") is False
                and doc.get("training_performed") is False
            ):
                print("AUTONOMOUS_PROPAGATION_RESUME=already_complete")
                print(json.dumps(doc, ensure_ascii=False, indent=2))
                print("\nAUTONOMOUS_PROPAGATION_OK=true")
                print(f"OUTPUT={output}")
                print(f"SILVER_AUTO_LABELS={doc.get('silver_auto_labels')}")
                print("HUMAN_REVIEW_REQUIRED=false")
                print("TRAINING_PERFORMED=false")
                print("RUNTIME_APPROVED=false")
                return 0
        die(f"output already exists but is not a valid completed run: {output}")

    collection_report = load_json(collection / "report.json")
    if not (
        collection_report.get("status") == "complete"
        and collection_report.get("collection_mode") == "annotation_only"
        and collection_report.get("inference_performed") is False
        and collection_report.get("training_performed") is False
    ):
        die("collection does not satisfy annotation-only provenance contract")

    anchor_rows = load_json(anchors)
    if not isinstance(anchor_rows, list) or not anchor_rows:
        die("gold anchor list is empty")
    if any(
        not isinstance(row, dict)
        or row.get("label_source") not in {
            "autonomous_shop_purchase_bench_consensus_v1",
            "autonomous_tooltip_temporal_consensus_v1",
        }
        or row.get("human_review_required") is not False
        or row.get("model_prediction_used_as_label") is not False
        or row.get("training_eligible") is not True
        for row in anchor_rows
    ):
        die("gold anchor provenance contract failed")

    selection = load_json(selection_path)
    if selection.get("status") != "selection_frozen_before_minjo_kh_evaluation":
        die("selected model is not the frozen pre-Minjo/KH model")
    if selection.get("selected_arm") != "optimizer-default-parity":
        die("unexpected selected arm")

    model = required(Path(str(selection.get("selected_model_path", ""))))
    model_sha = str(selection.get("selected_model_sha256", ""))
    if not model_sha or sha256_file(model) != model_sha:
        die("selected model hash mismatch")

    metadata = load_json(required(selection_path.parent / "run-metadata.json"))
    encoder = required(Path(str(metadata.get("encoder", ""))))
    encoder_sha = str(metadata.get("encoder_sha256", ""))
    if not encoder_sha or sha256_file(encoder) != encoder_sha:
        die("encoder hash mismatch")
    onnxruntime = required(Path(str(metadata.get("onnxruntime", ""))))

    output.parent.mkdir(parents=True, exist_ok=True)
    spec_path = output.parent / f"{output.name}-spec.json"
    log_path = output.parent / f"{output.name}.log"
    if spec_path.exists() or log_path.exists():
        die("spec/log already exists; choose a new output name")

    spec = {
        "collection": str(collection),
        "anchors": str(anchors),
        "model": str(model),
        "model_sha256": model_sha,
        "encoder": str(encoder),
        "encoder_sha256": encoder_sha,
        "onnxruntime": str(onnxruntime),
        "output": str(output),
        "max_time_delta_seconds": args.max_time_delta_seconds,
        "min_anchor_similarity": args.min_anchor_similarity,
        "min_anchor_margin": args.min_anchor_margin,
        "min_classifier_margin": args.min_classifier_margin,
        "max_anchor_screen_distance_px": 900.0,
        "bucket_seconds": 4,
        "per_label_limit": args.per_label_limit,
    }
    spec_path.write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    run_stream(
        native_lab_command(repo, "propagate-autonomous-anchors", ["--spec", str(spec_path)]),
        repo,
        log_path,
    )

    report = load_json(required(output / "report.json"))
    if report.get("human_review_required") is not False:
        die("propagation unexpectedly requires human review")
    if report.get("training_performed") is not False:
        die("propagation unexpectedly reports training")

    print("\nAUTONOMOUS_PROPAGATION_OK=true")
    print(f"OUTPUT={output}")
    print(f"GOLD_ANCHORS={report.get('gold_anchors')}")
    print(f"SILVER_AUTO_LABELS={report.get('silver_auto_labels')}")
    for unit_id, stats in (report.get("per_label") or {}).items():
        print(
            f"ID={unit_id} "
            f"GOLD={stats.get('gold_anchors')} "
            f"RAW={stats.get('raw_consensus_candidates')} "
            f"SILVER={stats.get('selected_silver')}"
        )
    print("RECOMMENDED_TRAINING_WEIGHT=0.35")
    print("HUMAN_REVIEW_REQUIRED=false")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
