#!/usr/bin/env python3
"""Prioritize a targeted annotation-only collection with the frozen winning model.

This is a review-ranking step only. It never creates labels or trains.
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
DEFAULT_COLLECTION = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/"
    "elder-dragon-shurkou/annotation-2s"
)
DEFAULT_OUTPUT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/"
    "elder-dragon-shurkou/frozen-priority-v1"
)
TARGET_IDS = [
    "DA_18_ElderDragon",
    "DA_18_Kayle",
    "DA_18_KhaZix",
    "DA_18_MasterYi_AD",
    "DA_18_Morgana",
    "DA_18_Xayah",
    "DA_CrimsonRaptor18",
    "DA_Karma18",
    "DA_Murkwolf18",
]


def die(message: str) -> "NoReturn":
    raise SystemExit(f"TARGETED_PRIORITY_ERROR: {message}")


def load_json(path: Path) -> dict[str, Any]:
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


def canonical(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=True)
    except FileNotFoundError:
        die(f"required path not found: {path}")


def run_stream(command: list[str], cwd: Path, log: Path) -> None:
    print("+", " ".join(command), flush=True)
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
        die(f"prioritizer failed ({code}); see {log}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--collection", type=Path, default=DEFAULT_COLLECTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--per-target-limit", type=int, default=20)
    parser.add_argument("--context-limit", type=int, default=30)
    args = parser.parse_args()

    repo = canonical(args.repo)
    selection_path = canonical(args.selection)
    collection = canonical(args.collection)
    output = args.output.expanduser()

    if output.exists():
        die(f"output already exists: {output}")
    if not (collection / "report.json").is_file() or not (
        collection / "observations.jsonl"
    ).is_file():
        die("collection is missing report.json or observations.jsonl")

    selection = load_json(selection_path)
    if selection.get("status") != "selection_frozen_before_minjo_kh_evaluation":
        die("optimizer selection is not the frozen pre-Minjo/KH selection")
    if selection.get("selected_arm") != "optimizer-default-parity":
        die("unexpected selected arm; checkpoint expected optimizer-default-parity")

    model = canonical(Path(str(selection.get("selected_model_path", ""))))
    model_sha = str(selection.get("selected_model_sha256", ""))
    if not model_sha or sha256_file(model) != model_sha:
        die("selected model SHA-256 mismatch")

    metadata = load_json(canonical(selection_path.parent / "run-metadata.json"))
    encoder = canonical(Path(str(metadata.get("encoder", ""))))
    encoder_sha = str(metadata.get("encoder_sha256", ""))
    if not encoder_sha or sha256_file(encoder) != encoder_sha:
        die("encoder SHA-256 mismatch")
    onnxruntime = canonical(Path(str(metadata.get("onnxruntime", ""))))

    if not (1 <= args.per_target_limit <= 100):
        die("--per-target-limit must be in 1..100")
    if not (1 <= args.context_limit <= 120):
        die("--context-limit must be in 1..120")

    output.parent.mkdir(parents=True, exist_ok=True)
    spec_path = output.parent / f"{output.name}-spec.json"
    log_path = output.parent / f"{output.name}.log"
    if spec_path.exists() or log_path.exists():
        die("spec/log already exists; choose a new output name")

    spec = {
        "collection": str(collection),
        "model": str(model),
        "model_sha256": model_sha,
        "encoder": str(encoder),
        "encoder_sha256": encoder_sha,
        "onnxruntime": str(onnxruntime),
        "output": str(output),
        "target_ids": TARGET_IDS,
        "per_target_limit": args.per_target_limit,
        "time_bucket_seconds": 10,
        "context_limit": args.context_limit,
    }
    spec_path.write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    run_stream(
        [
            "cargo",
            "run",
            "--release",
            "--manifest-path",
            str(repo / "tools/unit-features-lab/Cargo.toml"),
            "--bin",
            "prioritize-annotation-collection",
            "--",
            "--spec",
            str(spec_path),
        ],
        repo,
        log_path,
    )

    report = load_json(canonical(output / "report.json"))
    if report.get("training_performed") is not False:
        die("prioritizer unexpectedly reports training")
    if report.get("automatic_labels") is not False:
        die("prioritizer unexpectedly permits automatic labels")

    print("\nTARGETED_PRIORITY_OK=true")
    print(f"OUTPUT={output}")
    print(f"COLLECTION_UNIT_CROPS={report.get('collection_unit_crops')}")
    print(f"QUEUED_CANDIDATES={report.get('queued_candidates')}")
    print(f"LATE_CONTEXT_FRAMES={report.get('late_context_frames')}")
    for target, summary in (report.get("per_target") or {}).items():
        print(
            f"TARGET={target} "
            f"DIVERSE={summary.get('diverse_temporal_candidates')} "
            f"QUEUED={summary.get('queued')}"
        )
    print("TRAINING_PERFORMED=false")
    print("AUTOMATIC_LABELS=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
