#!/usr/bin/env python3
"""Train the first weighted autonomous recognizer challenger.

Base: frozen optimizer-default-parity / transfer-vertical protocol.
Extra train-only supervision:
- adjudicated supported gold anchors, weight 1.0
- conservative silver propagation, weight 0.35

Validation/test partitions from the sealed base manifest remain unchanged.
Minjo/KH are not used for selection in this runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
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
DEFAULT_GOLD = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/"
    "elder-dragon-shurkou/autonomous-gold-adjudication-v1/"
    "supported-gold-anchors.json"
)
DEFAULT_SILVER = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/"
    "elder-dragon-shurkou/autonomous-propagation-supported-v1/"
    "silver-auto-labels.json"
)
DEFAULT_PRIVATE_ROOT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/missing-classes-training-20261005"
)


def die(message: str) -> "NoReturn":
    raise SystemExit(f"AUTONOMOUS_CHALLENGER_ERROR: {message}")


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
        die(f"command failed ({code}); see {log}")


def metric_key(metrics: dict[str, Any]) -> tuple[float, float]:
    recall = float(metrics["named_macro_recall"])
    loss = float(metrics["cross_entropy"])
    return (recall, -loss)


def validation_metrics(report: dict[str, Any]) -> dict[str, Any]:
    row = report["variants"]["dino"]["evaluation"]["validation"]
    return {
        "named": int(row["named"]),
        "correct": int(row["named_top1_correct"]),
        "named_macro_recall": float(row["named_macro_recall"]),
        "cross_entropy": float(row["cross_entropy"]),
    }


def assert_gold(rows: Any) -> None:
    if not isinstance(rows, list) or not rows:
        die("supported gold anchor list is empty")
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("decision") not in {"supported", "bootstrap_supported"}
            or row.get("label_source") not in {"autonomous_shop_purchase_bench_consensus_v1", "autonomous_tooltip_temporal_consensus_v1"}
            or row.get("training_eligible") is not True
            or row.get("human_review_required") is not False
            or row.get("model_prediction_used_as_label") is not False
        ):
            die("supported gold provenance contract failed")


def assert_silver(rows: Any) -> None:
    if not isinstance(rows, list):
        die("silver autonomous labels must be a list")
    for row in rows:
        if (
            not isinstance(row, dict)
            or row.get("supervision_tier") != "silver_auto"
            or row.get("label_source") not in {
                "silver_auto_dino_frozen_temporal_consensus_v1",
                "silver_auto_shop_multiteacher_temporal_v1",
            }
            or row.get("training_eligible") is not True
            or row.get("human_review_required") is not False
            or not (0.0 < float(row.get("recommended_training_weight", -1)) <= 0.35)
        ):
            die("silver autonomous provenance/weight contract failed")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    p.add_argument("--collection", type=Path, default=DEFAULT_COLLECTION)
    p.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    p.add_argument("--silver", type=Path, default=DEFAULT_SILVER)
    p.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    p.add_argument("--output-root", type=Path)
    p.add_argument("--autonomous-corpus", type=Path)
    p.add_argument("--embedding-cache", type=Path)
    p.add_argument("--skip-tests", action="store_true")
    args = p.parse_args()

    repo = required(args.repo)
    selection_path = required(args.selection)
    collection = required(args.collection)
    gold = required(args.gold)
    silver = required(args.silver)
    private_root = required(args.private_root)

    if str(private_root).startswith("/mnt/sherlock-ssd") and not Path(
        "/mnt/sherlock-ssd"
    ).is_mount():
        die("/mnt/sherlock-ssd is not mounted")

    gold_rows = load_json(gold)
    silver_rows = load_json(silver)
    assert_gold(gold_rows)
    assert_silver(silver_rows)
    if not gold_rows and not silver_rows:
        die("no autonomous supervision available")
    source_ids = {
        row.get("source_id")
        for row in [*gold_rows, *silver_rows]
        if isinstance(row, dict) and isinstance(row.get("source_id"), str)
    }
    if len(source_ids) != 1:
        die(f"autonomous gold/silver must belong to exactly one source, got {sorted(source_ids)}")
    source_id = next(iter(source_ids))

    corpus_sources = None
    corpus_path = None
    if args.autonomous_corpus is not None:
        corpus_path = required(args.autonomous_corpus)
        corpus = load_json(corpus_path)
        if (
            corpus.get("schema_version") != 1
            or corpus.get("policy") != "central_autonomous_corpus_v1"
            or not isinstance(corpus.get("sources"), list)
            or not corpus["sources"]
        ):
            die("autonomous corpus manifest incompatible")
        corpus_sources = []
        seen_corpus_ids = set()
        for index, row in enumerate(corpus["sources"]):
            if not isinstance(row, dict):
                die(f"autonomous corpus source {index} is not an object")
            source = row.get("source_id")
            if not isinstance(source, str) or not source or source in seen_corpus_ids:
                die("autonomous corpus source_id invalid/duplicate")
            seen_corpus_ids.add(source)
            collection_path = required(Path(str(row.get("collection", ""))))
            gold_path = required(Path(str(row.get("gold_labels", ""))))
            silver_path = required(Path(str(row.get("silver_labels", ""))))
            gold_weight = float(row.get("gold_weight", -1))
            silver_weight = float(row.get("silver_weight", -1))
            if not (0 < silver_weight <= gold_weight <= 1):
                die("autonomous corpus weights invalid")
            corpus_sources.append(
                {
                    "collection": str(collection_path),
                    "source_id": source,
                    "gold_labels": str(gold_path),
                    "silver_labels": str(silver_path),
                    "gold_weight": gold_weight,
                    "silver_weight": silver_weight,
                    "use_declared_silver_weights": bool(
                        row.get("use_declared_silver_weights", False)
                    ),
                }
            )
        if source_id not in seen_corpus_ids:
            die("current autonomous source is not present in central corpus")

    selection = load_json(selection_path)
    if selection.get("status") not in {
        "selection_frozen_before_minjo_kh_evaluation",
        "central_stable_champion",
    }:
        die("baseline selection is not an approved frozen/central champion")
    baseline_arm = selection.get("selected_arm")
    if not isinstance(baseline_arm, str) or not baseline_arm:
        die("baseline selected arm missing")
    baseline_metrics = selection.get("selected_metrics")
    if not isinstance(baseline_metrics, dict):
        die("baseline validation metrics missing")

    baseline_model = required(Path(str(selection.get("selected_model_path", ""))))
    baseline_model_sha = str(selection.get("selected_model_sha256", ""))
    if not baseline_model_sha or sha256_file(baseline_model) != baseline_model_sha:
        die("baseline model SHA-256 mismatch")
    baseline_model_doc = load_json(baseline_model)

    metadata = load_json(required(selection_path.parent / "run-metadata.json"))
    annotations = required(Path(str(metadata.get("annotations", ""))))
    images = required(Path(str(metadata.get("images", ""))))
    reference = required(Path(str(metadata.get("reference", ""))))
    encoder = required(Path(str(metadata.get("encoder", ""))))
    onnxruntime = required(Path(str(metadata.get("onnxruntime", ""))))
    encoder_sha = str(metadata.get("encoder_sha256", ""))
    if not encoder_sha or sha256_file(encoder) != encoder_sha:
        die("encoder hash mismatch")

    if baseline_model_doc.get("encoder_sha256") != encoder_sha:
        die("baseline encoder identity mismatch")
    if baseline_model_doc.get("crop_transform") != "upper_88x80_v1":
        die("unexpected baseline crop transform")
    if baseline_model_doc.get("augmentation") != "vertical_alignment_v1":
        die("unexpected baseline augmentation")
    if baseline_model_doc.get("embedding_batch_size") != 1:
        die("unexpected baseline embedding batch size")
    optimizer = baseline_model_doc.get("optimizer")
    if not isinstance(optimizer, dict):
        die("baseline optimizer metadata missing")

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    output_root = (
        args.output_root.expanduser()
        if args.output_root
        else private_root / f"autonomous-challenger-{timestamp}"
    )
    if output_root.exists():
        die(f"output root already exists: {output_root}")
    output_root.mkdir(parents=True)
    logs = output_root / "logs"
    specs = output_root / "specs"
    cache = (
        args.embedding_cache.expanduser().resolve()
        if args.embedding_cache is not None
        else output_root / "embedding-cache"
    )
    specs.mkdir()
    cache.mkdir(parents=True, exist_ok=True)

    run_metadata = {
        "status": "running",
        "baseline_selection": str(selection_path),
        "baseline_model": str(baseline_model),
        "baseline_model_sha256": baseline_model_sha,
        "baseline_validation": baseline_metrics,
        "annotations": str(annotations),
        "annotations_sha256": sha256_file(annotations),
        "images": str(images),
        "reference": str(reference),
        "encoder": str(encoder),
        "encoder_sha256": encoder_sha,
        "embedding_cache": str(cache),
        "embedding_cache_shared": args.embedding_cache is not None,
        "onnxruntime": str(onnxruntime),
        "autonomous_collection": str(collection),
        "gold_labels": str(gold),
        "gold_labels_sha256": sha256_file(gold),
        "gold_count": len(gold_rows),
        "gold_weight": 1.0,
        "silver_labels": str(silver),
        "silver_labels_sha256": sha256_file(silver),
        "silver_count": len(silver_rows),
        "silver_weight": 0.35,
        "source_id": source_id,
        "autonomous_corpus": str(corpus_path) if corpus_path else None,
        "autonomous_corpus_sha256": sha256_file(corpus_path) if corpus_path else None,
        "autonomous_corpus_sources": len(corpus_sources) if corpus_sources else 1,
        "minjo_kh_used_for_selection": False,
        "runtime_approved": False,
    }
    (output_root / "run-metadata.json").write_text(
        json.dumps(run_metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    if not args.skip_tests:
        run_stream(
            [
                "cargo",
                "test",
                "--release",
                "--manifest-path",
                str(repo / "tools/unit-features-lab/Cargo.toml"),
                "training::tests",
            ],
            repo,
            logs / "weighted-training-tests.log",
        )

    challenger_out = output_root / "weighted-autonomous"
    spec = {
        "annotations": str(annotations),
        "images": str(images),
        "reference": str(reference),
        "encoder": str(encoder),
        "encoder_sha256": encoder_sha,
        "onnxruntime": str(onnxruntime),
        "input_size": int(baseline_model_doc["input_size"]),
        "only_dino": True,
        "retrieval_only": False,
        "augmentation": "vertical_alignment_v1",
        "crop_transform": "upper_88x80_v1",
        "embedding_batch_size": 1,
        "embedding_cache": str(cache),
        "optimizer": optimizer,
        "output": str(challenger_out),
    }
    if corpus_sources is not None:
        spec["autonomous_training_sources"] = corpus_sources
    else:
        spec["autonomous_training"] = {
            "collection": str(collection),
            "source_id": source_id,
            "gold_labels": str(gold),
            "silver_labels": str(silver),
            "gold_weight": 1.0,
            "silver_weight": 0.35,
            "use_declared_silver_weights": True,
        }
    spec_path = specs / "weighted-autonomous.json"
    spec_path.write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    run_stream(
        native_lab_command(repo, "train-classifier", ["--spec", str(spec_path)]),
        repo,
        logs / "weighted-autonomous.log",
    )

    report_path = required(challenger_out / "report.json")
    model_path = required(challenger_out / "dino-head.json")
    report = load_json(report_path)
    challenger_metrics = validation_metrics(report)

    baseline_key = metric_key(
        {
            "named_macro_recall": baseline_metrics["named_macro_recall"],
            "cross_entropy": baseline_metrics["cross_entropy"],
        }
    )
    challenger_key = metric_key(challenger_metrics)
    selected = "weighted-autonomous" if challenger_key > baseline_key else baseline_arm

    result = {
        "status": "selection_frozen_before_minjo_kh_evaluation",
        "selection_rule": "validation_named_macro_recall_then_lower_cross_entropy",
        "baseline": {
            "arm": baseline_arm,
            "model": str(baseline_model),
            "model_sha256": baseline_model_sha,
            "validation": {
                "named": int(baseline_metrics["named"]),
                "correct": int(baseline_metrics["correct"]),
                "named_macro_recall": float(baseline_metrics["named_macro_recall"]),
                "cross_entropy": float(baseline_metrics["cross_entropy"]),
            },
        },
        "challenger": {
            "arm": "weighted-autonomous",
            "model": str(model_path),
            "model_sha256": sha256_file(model_path),
            "report": str(report_path),
            "validation": challenger_metrics,
            "gold_auto": len(gold_rows),
            "gold_weight": 1.0,
            "silver_auto": len(silver_rows),
            "silver_weight": 0.35,
        },
        "selected_arm": selected,
        "selected_model_path": (
            str(model_path) if selected == "weighted-autonomous" else str(baseline_model)
        ),
        "selected_model_sha256": (
            sha256_file(model_path)
            if selected == "weighted-autonomous"
            else baseline_model_sha
        ),
        "minjo_kh_evaluated_in_this_run": False,
        "independent_final_holdout": False,
        "human_review_required": False,
        "runtime_approved": False,
        "next": (
            "Evaluate only the frozen selected arm on development sources if the "
            "challenger wins; then continue source-diverse autonomous acquisition "
            "before a truly independent final holdout and shadow runtime."
        ),
    }
    selection_out = output_root / "autonomous-challenger-selection.json"
    selection_out.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    run_metadata["status"] = "complete_selection_frozen"
    run_metadata["selection"] = str(selection_out)
    (output_root / "run-metadata.json").write_text(
        json.dumps(run_metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("\nAUTONOMOUS_CHALLENGER_OK=true")
    print(f"OUTPUT_ROOT={output_root}")
    print(f"SELECTION={selection_out}")
    print(
        "BASELINE_VALIDATION="
        f"{int(baseline_metrics['correct'])}/{int(baseline_metrics['named'])}"
    )
    print(
        "BASELINE_MACRO_RECALL="
        f"{float(baseline_metrics['named_macro_recall']):.12f}"
    )
    print(
        "CHALLENGER_VALIDATION="
        f"{challenger_metrics['correct']}/{challenger_metrics['named']}"
    )
    print(
        "CHALLENGER_MACRO_RECALL="
        f"{challenger_metrics['named_macro_recall']:.12f}"
    )
    print(
        "CHALLENGER_CROSS_ENTROPY="
        f"{challenger_metrics['cross_entropy']:.12f}"
    )
    print(f"SELECTED_ARM={selected}")
    print("MINJO_KH_USED_FOR_SELECTION=false")
    print("HUMAN_REVIEW_REQUIRED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
