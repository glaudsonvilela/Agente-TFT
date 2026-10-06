#!/usr/bin/env python3
"""Run autonomous game-derived supervision on a targeted collection.

Stage 1: catalog-backed tooltip OCR.
Stage 2: strict temporal consensus auto-labeling.

No human review is required. No neural weights are changed by this runner.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_COLLECTION = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/"
    "elder-dragon-shurkou/annotation-2s"
)
DEFAULT_CATALOG = Path(
    "knowledge/riot-ddragon/16.19.1/pt_BR/TFTSet18/"
    "5dafba7d15d09fb77b4ba83af78f3a46f0986121f68c46e3be6bf41da85c823f/"
    "champions.json"
)
DEFAULT_OUTPUT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/"
    "elder-dragon-shurkou/autonomous-supervision-v1"
)


def die(message: str) -> "NoReturn":
    raise SystemExit(f"AUTONOMOUS_SUPERVISION_ERROR: {message}")


def preserve_failed_output(path: Path) -> None:
    if not path.exists():
        return
    for i in range(1, 100):
        candidate = path.with_name(f"{path.name}.failed-{i:02d}")
        if not candidate.exists():
            path.rename(candidate)
            print(f"AUTONOMOUS_SUPERVISION_RESUME=preserved:{candidate}")
            return
    die(f"too many failed outputs beside {path}")


def print_success(summary: dict, output: Path) -> None:
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nAUTONOMOUS_SUPERVISION_OK=true")
    print(f"OUTPUT={output}")
    print(f"GOLD_AUTO_LABELS={summary.get('gold_auto_labels')}")
    print("HUMAN_REVIEW_REQUIRED=false")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")


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
        die(f"command failed ({code}); see {log}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--collection", type=Path, default=DEFAULT_COLLECTION)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    repo = args.repo.expanduser().resolve()
    collection = args.collection.expanduser().resolve()
    catalog = (
        args.catalog.expanduser().resolve()
        if args.catalog
        else (repo / DEFAULT_CATALOG).resolve()
    )
    output = args.output.expanduser()

    summary_path = output / "summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if (
            summary.get("human_review_required") is False
            and summary.get("training_performed") is False
            and summary.get("runtime_approved") is False
        ):
            print("AUTONOMOUS_SUPERVISION_RESUME=already_complete")
            print_success(summary, output)
            return 0
        die("existing summary does not satisfy autonomous supervision contract")
    if output.exists():
        preserve_failed_output(output)
    if not (collection / "report.json").is_file() or not (
        collection / "observations.jsonl"
    ).is_file():
        die("targeted collection is incomplete")
    if not catalog.is_file():
        die(f"catalog not found: {catalog}")

    try:
        report = json.loads((collection / "report.json").read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"invalid collection report: {exc}")
    if report.get("status") != "complete":
        die("collection report is not complete")
    if report.get("training_performed") is not False:
        die("collection unexpectedly reports training")

    output.mkdir(parents=True)
    tooltip = output / "tooltip"
    labels = output / "tooltip-consensus"
    tooltip_log = output / "tooltip-miner.log"
    consensus_log = output / "tooltip-consensus.log"

    run_stream(
        [
            "cargo",
            "run",
            "--release",
            "--manifest-path",
            str(repo / "tools/unit-features-lab/Cargo.toml"),
            "--bin",
            "mine-tooltip-labels",
            "--",
            str(collection),
            str(catalog),
            str(tooltip),
        ],
        repo,
        tooltip_log,
    )

    proposals = tooltip / "proposals.json"
    if not proposals.is_file():
        die("tooltip miner did not produce proposals.json")

    run_stream(
        [
            sys.executable,
            str(repo / "scripts/autolabel_tooltip_temporal_consensus.py"),
            "--proposals",
            str(proposals),
            "--output",
            str(labels),
        ],
        repo,
        consensus_log,
    )

    label_report = json.loads((labels / "report.json").read_text(encoding="utf-8"))
    summary = {
        "schema_version": 1,
        "source_id": report.get("source_id"),
        "collection": str(collection),
        "tooltip_scanned": json.loads(
            (tooltip / "report.json").read_text(encoding="utf-8")
        ).get("scanned"),
        "tooltip_proposals": json.loads(
            (tooltip / "report.json").read_text(encoding="utf-8")
        ).get("proposals"),
        "gold_auto_labels": label_report.get("auto_labels"),
        "gold_auto_ids": label_report.get("auto_labeled_ids"),
        "human_review_required": False,
        "training_performed": False,
        "runtime_approved": False,
        "next": (
            "If gold anchors exist, propagate them temporally with frozen embeddings. "
            "If none exist, add autonomous shop/purchase evidence; do not request human labels."
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print_success(summary, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
