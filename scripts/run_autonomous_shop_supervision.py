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


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--dense-collection", type=Path, default=DEFAULT_DENSE)
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--source-id", default=SOURCE_ID)
    p.add_argument("--source-url", default=SOURCE_URL)
    args = p.parse_args()

    repo = args.repo.expanduser().resolve()
    source = args.source.expanduser().resolve()
    dense = args.dense_collection.expanduser()
    output = args.output.expanduser()
    catalog = (repo / CATALOG).resolve()

    if not source.is_file():
        die(f"source video not found: {source}")
    if not catalog.is_file():
        die(f"catalog not found: {catalog}")
    if output.exists():
        die(f"output already exists: {output}")

    output.mkdir(parents=True)
    logs = output / "logs"
    logs.mkdir()

    # Reuse only a complete dense annotation-only collection. Otherwise create it.
    dense_report_path = dense / "report.json"
    if dense.exists():
        if not dense_report_path.is_file():
            die(f"dense collection exists without report.json: {dense}")
        dense_report = load_json(dense_report_path)
        if not (
            dense_report.get("status") == "complete"
            and dense_report.get("collection_mode") == "annotation_only"
            and dense_report.get("review_interval_seconds") == 2
            and dense_report.get("sample_interval_seconds") == 2
            and dense_report.get("training_performed") is False
            and dense_report.get("inference_performed") is False
        ):
            die("existing dense collection does not satisfy autonomous shop contract")
    else:
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
        dense_report = load_json(dense_report_path)

    if dense_report.get("source_id") != args.source_id:
        die("dense collection source ID mismatch")

    miner = output / "shop-miner"
    run_stream(
        [
            "cargo",
            "run",
            "--release",
            "--manifest-path",
            str(repo / "tools/unit-features-lab/Cargo.toml"),
            "--bin",
            "mine-shop-transitions",
            "--",
            str(dense),
            str(catalog),
            str(miner),
        ],
        repo,
        logs / "shop-miner.log",
    )

    transitions = miner / "transition-proposals.json"
    if not transitions.is_file():
        die("shop miner did not produce transition-proposals.json")

    labels = output / "shop-consensus"
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
        logs / "shop-consensus.log",
    )

    miner_report = load_json(miner / "report.json")
    label_report = load_json(labels / "report.json")

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

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nAUTONOMOUS_SHOP_SUPERVISION_OK=true")
    print(f"OUTPUT={output}")
    print(f"SHOP_TRANSITION_PROPOSALS={summary['shop_transition_proposals']}")
    print(f"GOLD_AUTO_LABELS={summary['gold_auto_labels']}")
    print("HUMAN_REVIEW_REQUIRED=false")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
