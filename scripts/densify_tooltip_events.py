#!/usr/bin/env python3
"""Collect dense, source-partitioned windows around explicit unit tooltips.

The Rust collector and miner do all image work. This script only plans and
orchestrates their runs; a sparse proposal is never itself a training label.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"DENSIFY_TOOLTIP_ERROR: {message}")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"cannot read {path}: {exc}")


def exact_name_event(row: dict[str, Any], source_id: str, partition: str,
                     min_ocr: float, require_ring: bool) -> bool:
    unit_id = row.get("tooltip_unit_id")
    if not isinstance(unit_id, str) or not unit_id:
        return False
    if row.get("source_id") != source_id or row.get("partition", partition) != partition:
        return False
    if row.get("tooltip_unit_candidates") != [unit_id] or row.get("identity_requires_variant_review") is not False:
        return False
    conf = row.get("ocr_name_confidence")
    if not isinstance(conf, (int, float)) or not min_ocr <= conf <= 100:
        return False
    second = row.get("source_seconds_nominal")
    if not isinstance(second, int) or second < 0:
        return False
    if not require_ring:
        return True
    if row.get("selection_ring_status") not in {"unique_shape_candidate", "dominant_shape_candidate"}:
        return False
    marker = row.get("selected_ring_marker_candidate")
    if not isinstance(marker, int):
        return False
    candidates = row.get("association_candidates")
    if not isinstance(candidates, list):
        return False
    selected = [item for item in candidates if isinstance(item, dict) and item.get("marker_id") == marker]
    if len(selected) != 1 or not isinstance(selected[0].get("selection_ring"), dict):
        return False
    if selected[0]["selection_ring"].get("shape_pass") is not True:
        return False
    return True


def plan_windows(proposals: list[Any], source_id: str, partition: str,
                 duration: int, min_ocr: float, radius: int,
                 require_ring: bool = False) -> list[dict[str, Any]]:
    intervals = []
    for row in proposals:
        if not isinstance(row, dict) or not exact_name_event(row, source_id, partition, min_ocr, require_ring):
            continue
        second = row["source_seconds_nominal"]
        start = max(0, second - radius)
        end = min(duration, second + radius + 1)
        if start < end:
            intervals.append((start, end, second, row["tooltip_unit_id"]))
    windows: list[dict[str, Any]] = []
    for start, end, second, ident in sorted(intervals):
        if windows and start <= windows[-1]["end_seconds"]:
            previous = windows[-1]
            previous["end_seconds"] = max(previous["end_seconds"], end)
            previous["events"].append({"second": second, "unit_id": ident})
        else:
            windows.append({"start_seconds": start, "end_seconds": end,
                            "events": [{"second": second, "unit_id": ident}]})
    return windows


def checked_run(command: list[str], log: Path) -> None:
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        fail(f"command failed ({result.returncode}); see {log}")


def dense_collection_spec(base: dict[str, Any], output: Path,
                          start: int, end: int, sample_ms: int = 250) -> dict[str, Any]:
    if not 0 <= start < end:
        fail("invalid dense window")
    if sample_ms not in {250, 500, 1000}:
        fail("dense sampling must be 250, 500 or 1000 ms")
    result = dict(base)
    result.update(output=str(output), start_seconds=start,
                  duration_seconds=end - start, sample_interval_seconds=1,
                  review_interval_seconds=1, sample_interval_ms=sample_ms,
                  review_interval_ms=sample_ms, decode_mode="all")
    return result


def verify_indexed_media(report: dict[str, Any], spec: dict[str, Any]) -> None:
    """Sparse discovery and dense windows must seek the same indexed video."""
    source = spec.get("input")
    if not isinstance(source, str) or not source or not Path(source).is_file():
        fail("local indexed video required for dense collection")
    if Path(source).suffix.lower() in {".m3u8", ".ts"}:
        fail("HLS/TS seeks changed scenes at the same nominal time; remux to MP4 first")
    if report.get("input") != source:
        fail("sparse collection and dense base spec must use the same indexed video")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--collection", type=Path, required=True)
    parser.add_argument("--base-spec", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--collector-bin", type=Path, required=True)
    parser.add_argument("--miner-bin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-ocr-confidence", type=float, default=90)
    parser.add_argument("--radius-seconds", type=int, default=30)
    parser.add_argument("--sample-ms", type=int, choices=(250, 500, 1000), default=250)
    parser.add_argument("--require-ring", action="store_true",
                        help="Plan only when the sparse frame already shows a unique halo")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if not 80 <= args.min_ocr_confidence <= 100 or not 10 <= args.radius_seconds <= 120:
        fail("invalid OCR threshold or window radius")
    report = read_json(args.collection / "report.json")
    spec = read_json(args.base_spec)
    proposals = read_json(args.proposals)
    if not isinstance(report, dict) or report.get("status") != "complete" or not isinstance(proposals, list):
        fail("complete source collection and proposal list required")
    source_id = report.get("source_id")
    partition = report.get("partition")
    if partition not in {"training_pool_unlabeled", "evaluation_unlabeled"}:
        fail("unknown collection partition")
    if spec.get("source_id") != source_id or spec.get("partition") != partition:
        fail("base spec and collection source/partition differ")
    verify_indexed_media(report, spec)
    if spec.get("training_labels_allowed") is not False or spec.get("collection_mode") != "annotation_only":
        fail("base spec must be annotation-only with training labels disabled")
    duration = spec.get("duration_seconds")
    if not isinstance(duration, int) or duration < 1 or spec.get("start_seconds") != 0:
        fail("base spec must cover the source from zero")
    if not args.catalog.is_file() or not args.collector_bin.is_file() or not args.miner_bin.is_file():
        fail("catalog or Rust executable missing")
    windows = plan_windows(proposals, source_id, partition, duration,
                           args.min_ocr_confidence, args.radius_seconds, args.require_ring)
    args.output.mkdir(parents=True, exist_ok=True)
    plan = {"schema_version": 1, "source_id": source_id, "partition": partition,
            "min_ocr_confidence": args.min_ocr_confidence,
            "radius_seconds": args.radius_seconds, "windows": windows,
            "dense_sample_ms": args.sample_ms,
            "require_ring_at_discovery": args.require_ring,
            "sparse_proposals_are_labels": False}
    (args.output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    print(f"DENSE_WINDOWS={len(windows)}")
    if not args.execute:
        return 0

    consensus = Path(__file__).with_name("autolabel_tooltip_temporal_consensus.py")
    for window in windows:
        start, end = window["start_seconds"], window["end_seconds"]
        name = f"window-{start:06d}-{end:06d}"
        root = args.output / name
        root.mkdir(exist_ok=True)
        dense = root / "collection"
        mined = root / "tooltip-proposals"
        labeled = root / "identity-anchors"
        dense_spec = dense_collection_spec(spec, dense, start, end, args.sample_ms)
        spec_path = root / "collection-spec-private.json"
        if spec_path.exists() and read_json(spec_path) != dense_spec:
            fail(f"existing window spec changed: {spec_path}")
        spec_path.write_text(json.dumps(dense_spec, indent=2) + "\n", encoding="utf-8")
        if not dense.exists():
            checked_run([str(args.collector_bin), "--spec", str(spec_path)], root / "collector.log")
        dense_report = read_json(dense / "report.json")
        if (dense_report.get("status") != "complete" or dense_report.get("source_id") != source_id
                or dense_report.get("partition") != partition):
            fail(f"incomplete or mismatched dense collection: {dense}")
        if not mined.exists():
            checked_run([str(args.miner_bin), str(dense), str(args.catalog), str(mined)],
                        root / "miner.log")
        mined_report = read_json(mined / "report.json")
        if mined_report.get("source_id") != source_id or mined_report.get("partition") != partition:
            fail(f"mismatched mined proposals: {mined}")
        if not labeled.exists():
            checked_run([sys.executable, str(consensus), "--proposals", str(mined / "proposals.json"),
                         "--output", str(labeled)], root / "consensus.log")
        label_report = read_json(labeled / "report.json")
        print(f"{name}: labels={label_report['auto_labels']} train={label_report['training_eligible_labels']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
