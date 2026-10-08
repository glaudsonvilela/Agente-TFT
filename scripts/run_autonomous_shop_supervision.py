#!/usr/bin/env python3
"""Run autonomous shop/purchase/bench supervision for the Elder Dragon source.

Pipeline:
1. dense annotation-only recollection (2 s sample + 2 s full review frame);
2. exact catalog-backed shop OCR + disappearance mining;
3. strict autonomous purchase-to-bench consensus labels.

No human review, no neural weights changed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from native_lab import command as native_lab_command

DEFAULT_SOURCE = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/"
    "elder-dragon-shurkou/source.mp4"
)
DEFAULT_DENSE = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/"
    "elder-dragon-shurkou/annotation-2s-shop-dense"
)
DEFAULT_OUTPUT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/"
    "elder-dragon-shurkou/autonomous-shop-supervision-v1"
)
CATALOG = Path(
    "knowledge/riot-ddragon/16.19.1/pt_BR/TFTSet18/"
    "5dafba7d15d09fb77b4ba83af78f3a46f0986121f68c46e3be6bf41da85c823f/"
    "champions.json"
)
SOURCE_ID = "youtube:Ot358nhRJl0"
SOURCE_URL = "https://www.youtube.com/watch?v=Ot358nhRJl0"


def die(message: str) -> "NoReturn":
    raise SystemExit(f"AUTONOMOUS_SHOP_SUPERVISION_ERROR: {message}")


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


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"cannot read {path}: {exc}")


def retry_path(path: Path) -> Path:
    """Preserve an incomplete attempt and choose a fresh sibling."""
    for i in range(1, 100):
        candidate = path.with_name(f"{path.name}-retry-{i:02d}")
        if not candidate.exists():
            return candidate
    die(f"too many preserved retry directories beside {path}")


def valid_dense(path: Path, source_id: str, source_url: str) -> dict | None:
    report_path = path / "report.json"
    if not report_path.is_file():
        return None
    report = load_json(report_path)
    if (
        report.get("status") == "complete"
        and report.get("collection_mode") == "annotation_only"
        and report.get("review_interval_seconds") == 2
        and report.get("sample_interval_seconds") == 2
        and report.get("training_performed") is False
        and report.get("inference_performed") is False
        and report.get("source_id") == source_id
        and report.get("source_url") == source_url
    ):
        return report
    return None


def print_success(summary: dict, output: Path) -> None:
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nAUTONOMOUS_SHOP_SUPERVISION_OK=true")
    print(f"OUTPUT={output}")
    print(f"SHOP_TRANSITION_PROPOSALS={summary.get('shop_transition_proposals')}")
    print(f"GOLD_AUTO_LABELS={summary.get('gold_auto_labels')}")
    print("HUMAN_REVIEW_REQUIRED=false")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--dense-collection", type=Path, default=DEFAULT_DENSE)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--source-id", default=SOURCE_ID)
    p.add_argument("--source-url", default=SOURCE_URL)
    args = p.parse_args()

    if args.source_id != SOURCE_ID and args.source_url == SOURCE_URL:
        die("a custom source ID requires its matching --source-url")

    repo = args.repo.expanduser().resolve()
    source = args.source.expanduser().resolve()
    dense = args.dense_collection.expanduser()
    output = args.output.expanduser()
    catalog = (repo / CATALOG).resolve()

    if not source.is_file():
        die(f"source video not found: {source}")
    if not catalog.is_file():
        die(f"catalog not found: {catalog}")

    # Idempotent completion: a finished run can be invoked again safely.
    summary_path = output / "summary.json"
    if summary_path.is_file():
        summary = load_json(summary_path)
        if (
            summary.get("source_id") == args.source_id
            and summary.get("human_review_required") is False
            and summary.get("training_performed") is False
            and summary.get("runtime_approved") is False
        ):
            print("AUTONOMOUS_SHOP_SUPERVISION_RESUME=already_complete")
            print_success(summary, output)
            return 0
        die("existing summary does not match the current safety/source contract")

    output.mkdir(parents=True, exist_ok=True)
    logs = output / "logs"
    logs.mkdir(exist_ok=True)

    # Reuse a complete dense annotation-only collection. Preserve an incomplete
    # attempt and create a fresh sibling instead of deleting or overwriting it.
    dense_report = valid_dense(dense, args.source_id, args.source_url) if dense.exists() else None
    if dense.exists() and dense_report is None:
        preserved = dense
        dense = retry_path(dense)
        print(f"AUTONOMOUS_SHOP_SUPERVISION_RESUME=preserve_incomplete_dense:{preserved}")
    if dense_report is None:
        run_stream(
            [
                sys.executable,
                str(repo / "scripts/collect_targeted_annotation_source.py"),
                "--input",
                str(source),
                "--source-id",
                args.source_id,
                "--source-url",
                args.source_url,
                "--output",
                str(dense),
                "--sample-interval-seconds",
                "2",
                "--review-interval-seconds",
                "2",
            ],
            repo,
            logs / "dense-collection.log",
        )
        dense_report = valid_dense(dense, args.source_id, args.source_url)
        if dense_report is None:
            die("new dense collection did not satisfy autonomous shop contract")

    if dense_report.get("source_id") != args.source_id:
        die("dense collection source ID mismatch")

    miner = output / "shop-miner"
    miner_report_path = miner / "report.json"
    transitions = miner / "transition-proposals.json"
    miner_report = None
    if miner_report_path.is_file() and transitions.is_file():
        candidate = load_json(miner_report_path)
        if candidate.get("status") == "complete" and candidate.get("source_id") == args.source_id:
            miner_report = candidate
            print("AUTONOMOUS_SHOP_SUPERVISION_RESUME=reuse_shop_miner")
    if miner.exists() and miner_report is None:
        preserved = miner
        miner = retry_path(miner)
        miner_report_path = miner / "report.json"
        transitions = miner / "transition-proposals.json"
        print(f"AUTONOMOUS_SHOP_SUPERVISION_RESUME=preserve_incomplete_miner:{preserved}")
    if miner_report is None:
        run_stream(
        native_lab_command(
            repo,
            "mine-shop-transitions",
            [str(dense), str(catalog), str(miner)],
        ),
        repo,
        logs / f"{miner.name}.log",
        )
        if not transitions.is_file() or not miner_report_path.is_file():
            die("shop miner did not produce its sealed outputs")
        miner_report = load_json(miner_report_path)

    labels = output / "shop-consensus"
    label_report_path = labels / "report.json"
    label_report = None
    if label_report_path.is_file():
        candidate = load_json(label_report_path)
        if (
            candidate.get("policy") == "autonomous_shop_purchase_bench_consensus_v1"
            and candidate.get("human_review_required") is False
            and candidate.get("training_performed") is False
        ):
            label_report = candidate
            print("AUTONOMOUS_SHOP_SUPERVISION_RESUME=reuse_shop_consensus")
    if labels.exists() and label_report is None:
        preserved = labels
        labels = retry_path(labels)
        label_report_path = labels / "report.json"
        print(f"AUTONOMOUS_SHOP_SUPERVISION_RESUME=preserve_incomplete_consensus:{preserved}")
    if label_report is None:
        run_stream(
        [
            sys.executable,
            str(repo / "scripts/autolabel_shop_purchase_consensus.py"),
            "--transitions",
            str(transitions),
            "--collection",
            str(dense),
            "--output",
            str(labels),
        ],
        repo,
        logs / f"{labels.name}.log",
        )
        if not label_report_path.is_file():
            die("shop consensus did not produce report.json")
        label_report = load_json(label_report_path)

    summary = {
        "schema_version": 1,
        "source_id": args.source_id,
        "source_url": args.source_url,
        "dense_collection": str(dense),
        "dense_frames": dense_report.get("frames"),
        "dense_unit_crops": dense_report.get("unit_crops"),
        "shop_frames": miner_report.get("frames"),
        "shop_transition_proposals": miner_report.get("transition_proposals"),
        "gold_auto_labels": label_report.get("gold_auto_labels"),
        "gold_auto_ids": label_report.get("gold_auto_ids"),
        "human_review_required": False,
        "model_prediction_used_as_label": False,
        "training_performed": False,
        "runtime_approved": False,
        "next": (
            "If gold_auto labels exist, use them as trusted anchors for temporal/embedding "
            "propagation. If zero, add a third autonomous signal rather than human review."
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print_success(summary, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
