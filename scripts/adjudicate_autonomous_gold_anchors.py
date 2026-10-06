#!/usr/bin/env python3
"""Adjudicate autonomous gold anchors against frozen classifier + supervised retrieval.

No human review, no retraining. Only anchors marked "supported" remain
eligible for the next autonomous challenger.
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
    "elder-dragon-shurkou/annotation-2s-shop-dense"
)
DEFAULT_ANCHORS = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/"
    "elder-dragon-shurkou/autonomous-shop-supervision-v1/"
    "shop-consensus/auto-labels.json"
)
DEFAULT_OUTPUT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/"
    "elder-dragon-shurkou/autonomous-gold-adjudication-v1"
)


def die(message: str) -> "NoReturn":
    raise SystemExit(f"AUTONOMOUS_GOLD_ADJUDICATION_RUNNER_ERROR: {message}")


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


def preserve_failed_attempt(path: Path) -> None:
    if not path.exists():
        return
    for i in range(1, 100):
        candidate = path.with_name(f"{path.name}.failed-{i:02d}")
        if not candidate.exists():
            path.rename(candidate)
            print(f"AUTONOMOUS_GOLD_ADJUDICATION_RESUME=preserved:{candidate}")
            return
    die(f"too many preserved failed attempts beside {path}")


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
        die(f"native adjudication failed ({code}); see {log}")


def print_done(report: dict[str, Any], output: Path) -> None:
    print("\nAUTONOMOUS_GOLD_ADJUDICATION_OK=true")
    print(f"OUTPUT={output}")
    print(f"ANCHORS={report.get('anchors')}")
    print(f"SUPPORTED_GOLD_ANCHORS={report.get('supported_gold_anchors')}")
    print(f"DECISION_COUNTS={json.dumps(report.get('decision_counts') or {}, sort_keys=True)}")
    print("HUMAN_REVIEW_REQUIRED=false")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    p.add_argument("--collection", type=Path, default=DEFAULT_COLLECTION)
    p.add_argument("--anchors", type=Path, default=DEFAULT_ANCHORS)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = p.parse_args()

    repo = required(args.repo)
    selection_path = required(args.selection)
    collection = required(args.collection)
    anchors = required(args.anchors)
    output = args.output.expanduser()

    report_path = output / "report.json"
    if report_path.is_file():
        report = load_json(report_path)
        if (
            report.get("policy") == "autonomous_gold_anchor_adjudication_v1"
            and report.get("human_review_required") is False
            and report.get("training_performed") is False
        ):
            print("AUTONOMOUS_GOLD_ADJUDICATION_RESUME=already_complete")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print_done(report, output)
            return 0
        die("existing output does not satisfy adjudication contract")
    if output.exists():
        die("output exists but is incomplete; preserve it and use a new --output path")

    selection = load_json(selection_path)
    if selection.get("status") != "selection_frozen_before_minjo_kh_evaluation":
        die("selected model is not frozen before development evaluation")
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

    annotations = required(Path(str(metadata.get("annotations", ""))))
    images = required(Path(str(metadata.get("images", ""))))
    reference = required(Path(str(metadata.get("reference", ""))))
    onnxruntime = required(Path(str(metadata.get("onnxruntime", ""))))

    anchors_doc = load_json(anchors)
    if not isinstance(anchors_doc, list) or not anchors_doc:
        die("gold anchors are missing")
    if any(
        not isinstance(row, dict)
        or row.get("label_source") != "autonomous_shop_purchase_bench_consensus_v1"
        or row.get("human_review_required") is not False
        or row.get("model_prediction_used_as_label") is not False
        or row.get("training_eligible") is not True
        for row in anchors_doc
    ):
        die("gold anchor provenance failed")

    output.parent.mkdir(parents=True, exist_ok=True)
    spec_path = output.parent / f"{output.name}-spec.json"
    log_path = output.parent / f"{output.name}.log"
    # A compile/runtime failure can leave only spec/log behind while producing
    # no output directory. Preserve those failed-attempt artifacts and retry
    # deterministically with the same requested output.
    if not output.exists():
        preserve_failed_attempt(spec_path)
        preserve_failed_attempt(log_path)

    spec = {
        "collection": str(collection),
        "anchors": str(anchors),
        "annotations": str(annotations),
        "images": str(images),
        "reference": str(reference),
        "model": str(model),
        "model_sha256": model_sha,
        "encoder": str(encoder),
        "encoder_sha256": encoder_sha,
        "onnxruntime": str(onnxruntime),
        "output": str(output),
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
            "adjudicate-autonomous-gold",
            "--",
            "--spec",
            str(spec_path),
        ],
        repo,
        log_path,
    )

    report = load_json(required(report_path))
    if report.get("human_review_required") is not False:
        die("adjudication unexpectedly requires human review")
    if report.get("training_performed") is not False:
        die("adjudication unexpectedly reports training")

    decisions = load_json(required(output / "anchor-decisions.json"))
    print(json.dumps(decisions, ensure_ascii=False, indent=2))
    print_done(report, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
