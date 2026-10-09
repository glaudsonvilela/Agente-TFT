#!/usr/bin/env python3
"""Reinspect sparse shop disappearances at native resolution and 250 ms cadence.

The sparse OCR name remains a proposal. Only the existing shop/bench consensus
may produce a training label from the newly collected frames.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from densify_tooltip_events import dense_collection_spec, verify_indexed_media


def windows_for(proposals: list, source_id: str, duration: int) -> list[tuple[int, int]]:
    intervals = []
    for row in proposals:
        if not isinstance(row, dict) or row.get("source_id") != source_id:
            continue
        before, after = row.get("before_seconds"), row.get("after_seconds")
        if not (type(before) is int and type(after) is int and
                0 <= before < after <= duration and after - before <= 2):
            continue
        intervals.append((max(0, before - 4), min(duration, after + 4)))
    windows = []
    for start, end in sorted(intervals):
        if windows and start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(end, windows[-1][1]))
        else:
            windows.append((start, end))
    return windows


def run(command: list[str], log: Path) -> None:
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                check=False)
    if result.returncode:
        raise SystemExit(f"Dense shop stage failed ({result.returncode}); see {log}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--proposals", type=Path, required=True)
    p.add_argument("--collection", type=Path, required=True)
    p.add_argument("--base-spec", type=Path, required=True)
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--collector-bin", type=Path, required=True)
    p.add_argument("--miner-bin", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()

    report = json.loads((args.collection / "report.json").read_text())
    spec = json.loads(args.base_spec.read_text())
    proposals = json.loads(args.proposals.read_text())
    if (report.get("status") != "complete" or
            report.get("partition") != "training_pool_unlabeled" or
            spec.get("source_id") != report.get("source_id") or
            spec.get("partition") != report.get("partition") or
            spec.get("collection_mode") != "annotation_only" or
            spec.get("training_labels_allowed") is not False or
            spec.get("start_seconds") != 0 or
            not isinstance(proposals, list)):
        raise SystemExit("Sparse collection/proposals provenance is invalid")
    verify_indexed_media(report, spec)
    if not all(path.is_file() for path in (args.catalog, args.collector_bin, args.miner_bin)):
        raise SystemExit("Catalog or Rust binary missing")
    duration = spec.get("duration_seconds")
    if type(duration) is not int or duration < 1:
        raise SystemExit("Invalid source duration")
    windows = windows_for(proposals, report["source_id"], duration)
    args.output.mkdir(parents=True, exist_ok=True)
    plan = {"schema_version": 1, "source_id": report["source_id"],
            "partition": report["partition"], "sample_interval_ms": 250,
            "windows": windows, "sparse_proposals_are_labels": False}
    (args.output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(f"DENSE_SHOP_WINDOWS={len(windows)}", flush=True)
    if not args.execute:
        return 0

    consensus = Path(__file__).with_name("autolabel_shop_purchase_consensus.py")
    total = 0
    for start, end in windows:
        root = args.output / f"window-{start:06d}-{end:06d}"
        root.mkdir(exist_ok=True)
        collection, mined, labeled = (root / name for name in
                                      ("collection", "shop-proposals", "shop-consensus"))
        dense_spec = dense_collection_spec(spec, collection, start, end, 250)
        spec_path = root / "collection-spec-private.json"
        if spec_path.exists() and json.loads(spec_path.read_text()) != dense_spec:
            raise SystemExit(f"Dense shop spec changed: {spec_path}")
        spec_path.write_text(json.dumps(dense_spec, indent=2) + "\n")
        if not (collection / "report.json").exists():
            run([str(args.collector_bin), "--spec", str(spec_path)], root / "collector.log")
        dense_report = json.loads((collection / "report.json").read_text())
        if (dense_report.get("status") != "complete" or
                dense_report.get("source_id") != report["source_id"] or
                dense_report.get("partition") != report["partition"] or
                dense_report.get("input") != dense_spec["input"] or
                dense_report.get("start_seconds") != start or
                dense_report.get("requested_seconds") != end - start or
                dense_report.get("sample_interval_ms") != 250):
            raise SystemExit(f"Dense shop collection invalid: {collection}")
        if not (mined / "report.json").exists():
            run([str(args.miner_bin), str(collection), str(args.catalog), str(mined)],
                root / "miner.log")
        mined_report = json.loads((mined / "report.json").read_text())
        if (mined_report.get("status") != "complete" or
                mined_report.get("source_id") != report["source_id"] or
                mined_report.get("partition") != report["partition"]):
            raise SystemExit(f"Dense shop proposals invalid: {mined}")
        if not (labeled / "report.json").exists():
            run([sys.executable, str(consensus), "--transitions",
                 str(mined / "transition-proposals.json"), "--collection",
                 str(collection), "--output", str(labeled)], root / "consensus.log")
        result = json.loads((labeled / "report.json").read_text())
        count = result.get("training_eligible_labels", 0)
        total += count
        print(f"{root.name}: confirmed={count}", flush=True)
    print(f"DENSE_SHOP_CONFIRMED={total}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
