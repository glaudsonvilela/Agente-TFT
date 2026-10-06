#!/usr/bin/env python3
"""Bootstrap a source-diverse Kha'Zix acquisition from the private SSD review queue.

This runner uses the historical queue only to LOCATE a new training-side source.
Model suggestions from the queue never become labels.

Pipeline:
1. find exactly one new-source Kha'Zix queue row;
2. verify the referenced collection is training_pool_unlabeled;
3. acquire a bounded source window around the candidate timestamp;
4. run dense autonomous shop + tooltip supervision;
5. if direct gold remains zero, run the calibrated low-weight multi-teacher shop silver.

No human review and no training occur in this runner.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_QUEUE = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/new-image-review-queue-20261005/queue.json"
)
DEFAULT_OUTPUT_ROOT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261006/"
    "khazix-cross-source-queue-v2"
)
CHECKPOINT = Path("docs/evidence/recognizer-training-20261005/checkpoint.json")
ANNOTATIONS = Path("configs/training/unit-gallery-transfer-reviewed-expanded-20261005.json")
TARGET_ID = "DA_18_KhaZix"


def die(message: str) -> "NoReturn":
    raise SystemExit(f"KHAZIX_QUEUE_BOOTSTRAP_ERROR: {message}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"cannot read JSON {path}: {exc}")



def source_token(frame: dict[str, Any]) -> str | None:
    for key in ("source_video_id", "source_id"):
        value = frame.get(key)
        if isinstance(value, str) and value:
            return value
    value = frame.get("source_url")
    return value if isinstance(value, str) and value else None


def current_khazix_train_sources(manifest: dict[str, Any]) -> set[str]:
    sources: set[str] = set()
    for frame in manifest.get("frames", []):
        if not isinstance(frame, dict) or frame.get("identity_split") != "train":
            continue
        has_khazix = any(
            isinstance(entity, dict)
            and isinstance(entity.get("identity"), dict)
            and entity["identity"].get("id") == TARGET_ID
            for entity in frame.get("entities", [])
        )
        if has_khazix:
            src = source_token(frame)
            if src:
                sources.add(src)
    return sources


def checkpoint_source_partitions(checkpoint: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for source in checkpoint.get("sources", []):
        if not isinstance(source, dict):
            continue
        partition = source.get("partition")
        if not isinstance(partition, str) or not partition:
            continue
        for value in (
            source.get("source_id"),
            source.get("url"),
            (source.get("progress") or {}).get("source_id")
            if isinstance(source.get("progress"), dict)
            else None,
            (source.get("progress") or {}).get("source_url")
            if isinstance(source.get("progress"), dict)
            else None,
        ):
            if isinstance(value, str) and value:
                result[value] = partition
    return result


def allowed_training_partition(partition: str | None) -> bool:
    return partition in {"training", "training_pool_unlabeled"}


def select_cross_source_candidate(
    rows: list[Any],
    source_partitions: dict[str, str],
    existing_khazix_sources: set[str],
) -> dict[str, Any]:
    eligible: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    for raw in rows:
        if not isinstance(raw, dict) or raw.get("target_id_suggestion") != TARGET_ID:
            continue
        source_id = raw.get("source_id")
        source_url = raw.get("source_url")
        if not isinstance(source_id, str) or not source_id:
            rejected["missing_source_id"] = rejected.get("missing_source_id", 0) + 1
            continue
        if source_id in existing_khazix_sources:
            rejected["already_supervises_khazix"] = rejected.get("already_supervises_khazix", 0) + 1
            continue
        partition = source_partitions.get(source_id)
        if partition is None and isinstance(source_url, str):
            partition = source_partitions.get(source_url)
        if not allowed_training_partition(partition):
            rejected[f"checkpoint_partition:{partition or 'missing'}"] = (
                rejected.get(f"checkpoint_partition:{partition or 'missing'}", 0) + 1
            )
            continue
        if (
            raw.get("model_prediction_used_as_label") is not False
            or raw.get("training_eligible") is not False
        ):
            rejected["queue_contract_violation"] = rejected.get("queue_contract_violation", 0) + 1
            continue
        row = dict(raw)
        row["checkpoint_partition"] = partition
        eligible.append(row)

    if not eligible:
        die(
            "no cross-source KhaZix queue candidate survives current checkpoint policy; "
            f"rejected={json.dumps(rejected, sort_keys=True)}"
        )

    def rank(row: dict[str, Any]) -> tuple[int, float, float]:
        accepted = 1 if row.get("suggestion_kind") == "accepted_suggestion" else 0
        score = row.get("suggestion_score")
        numeric_score = float(score) if isinstance(score, (int, float)) else -1.0
        seconds = row.get("source_seconds_nominal")
        numeric_seconds = float(seconds) if isinstance(seconds, (int, float)) else 0.0
        return (-accepted, -numeric_score, numeric_seconds)

    eligible.sort(key=rank)
    selected = eligible[0]
    selected["_selection_audit"] = {
        "eligible_candidates": len(eligible),
        "rejected": rejected,
        "existing_khazix_train_sources": sorted(existing_khazix_sources),
    }
    return selected


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_stream(command: list[str], cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
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
    code = proc.wait()
    if code != 0:
        die(f"command failed ({code}): {' '.join(command)}")


def probe_video(path: Path) -> dict[str, Any]:
    raw = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration",
            "-of", "json", str(path),
        ],
        text=True,
    )
    doc = json.loads(raw)
    stream = doc["streams"][0]
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "duration": float(doc["format"]["duration"]),
    }


def acquire_window(url: str, start: int, end: int, output: Path) -> None:
    yt = Path.home() / ".local/bin/yt-dlp"
    executable = str(yt) if yt.is_file() else "yt-dlp"
    tmp = output.with_name(".window-download.mp4")
    if tmp.exists():
        tmp.unlink()
    section = f"*{start}-{end}"
    run_stream(
        [
            executable,
            "--no-playlist",
            "--download-sections", section,
            "--force-keyframes-at-cuts",
            "-f",
            "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
            "--merge-output-format", "mp4",
            "-o", str(tmp),
            url,
        ],
        output.parent,
    )
    if not tmp.is_file():
        die("bounded acquisition did not produce the expected mp4")
    info = probe_video(tmp)
    if (info["width"], info["height"]) != (1920, 1080):
        die(f"targeted window must be 1920x1080, got {info['width']}x{info['height']}")
    tmp.rename(output)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    p.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    p.add_argument("--before-seconds", type=int, default=180)
    p.add_argument("--after-seconds", type=int, default=300)
    args = p.parse_args()

    repo = args.repo.expanduser().resolve()
    queue_path = args.queue.expanduser().resolve()
    out = args.output_root.expanduser()

    if not (repo / "tools/unit-features-lab/Cargo.toml").is_file():
        die("run from an Agente-TFT checkout")
    if not queue_path.is_file():
        die(f"private queue missing: {queue_path}")
    if not (60 <= args.before_seconds <= 600 and 120 <= args.after_seconds <= 900):
        die("window bounds outside conservative budget")

    queue_doc = load_json(queue_path)
    rows = queue_doc.get("queue")
    if not isinstance(rows, list):
        die("queue.json missing queue list")

    checkpoint_path = (repo / CHECKPOINT).resolve()
    annotations_path = (repo / ANNOTATIONS).resolve()
    if not checkpoint_path.is_file() or not annotations_path.is_file():
        die("current checkpoint/annotations are required for source-policy revalidation")
    checkpoint = load_json(checkpoint_path)
    annotations = load_json(annotations_path)
    source_partitions = checkpoint_source_partitions(checkpoint)
    existing_khazix_sources = current_khazix_train_sources(annotations)

    row = select_cross_source_candidate(
        rows,
        source_partitions=source_partitions,
        existing_khazix_sources=existing_khazix_sources,
    )

    source_id = row.get("source_id")
    source_url = row.get("source_url")
    seconds = row.get("source_seconds_nominal")
    collection = Path(str(row.get("collection", ""))).expanduser()
    if not isinstance(source_id, str) or not source_id:
        die("queue row missing source_id")
    if not isinstance(source_url, str) or not source_url.startswith("https://"):
        die("queue row missing https source_url")
    if not isinstance(seconds, (int, float)):
        die("queue row missing source timestamp")
    seconds = int(seconds)
    report_path = collection / "report.json"
    if not report_path.is_file():
        die(f"referenced collection missing report.json: {collection}")
    report = load_json(report_path)
    current_partition = row.get("checkpoint_partition")
    if (
        report.get("source_id") != source_id
        or report.get("partition") != "training_pool_unlabeled"
        or not allowed_training_partition(current_partition)
        or report.get("training_performed") is not False
        or report.get("runtime_approved") is not False
    ):
        die("referenced collection fails current training-side provenance contract")

    start = max(0, seconds - args.before_seconds)
    end = seconds + args.after_seconds
    out.mkdir(parents=True, exist_ok=True)

    metadata_path = out / "queue-source-metadata.json"
    if metadata_path.is_file():
        meta = load_json(metadata_path)
        expected = {
            "target_id": TARGET_ID,
            "source_id": source_id,
            "source_url": source_url,
            "queue_timestamp_seconds": seconds,
            "window_start_seconds": start,
            "window_end_seconds": end,
        }
        for key, value in expected.items():
            if meta.get(key) != value:
                die(f"existing metadata mismatch for {key}")
    else:
        metadata = {
            "schema_version": 1,
            "target_id": TARGET_ID,
            "source_id": source_id,
            "source_url": source_url,
            "queue_timestamp_seconds": seconds,
            "queue_crop_pixel_sha256": row.get("crop_pixel_sha256"),
            "queue_suggestion_kind": row.get("suggestion_kind"),
            "queue_suggestion_score": row.get("suggestion_score"),
            "queue_model_prediction_used_as_label": False,
            "queue_training_eligible": False,
            "source_collection": str(collection),
            "source_collection_report_sha256": sha256_file(report_path),
            "checkpoint_sha256": sha256_file(checkpoint_path),
            "checkpoint_partition": current_partition,
            "selection_audit": row.get("_selection_audit"),
            "window_start_seconds": start,
            "window_end_seconds": end,
            "human_review_required": False,
            "training_performed": False,
            "runtime_approved": False,
        }
        metadata_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    video = out / "source-window.mp4"
    if not video.is_file():
        acquire_window(source_url, start, end, video)
    info = probe_video(video)
    if (info["width"], info["height"]) != (1920, 1080):
        die("existing source window is not 1920x1080")

    window_source_id = f"{source_id}#window={start}-{end}"
    dense = out / "annotation-2s-shop-dense"
    shop = out / "autonomous-shop-supervision-v1"
    run_stream(
        [
            sys.executable,
            str(repo / "scripts/run_autonomous_shop_supervision.py"),
            "--source", str(video),
            "--dense-collection", str(dense),
            "--output", str(shop),
            "--source-id", window_source_id,
            "--source-url", source_url,
        ],
        repo,
    )

    shop_gold = shop / "shop-consensus" / "auto-labels.json"
    if not shop_gold.is_file():
        die("shop supervision missing auto-labels.json")
    shop_rows = load_json(shop_gold)
    if not isinstance(shop_rows, list):
        die("shop auto-labels must be a list")

    tooltip_rows: list[dict[str, Any]] = []
    tooltip = out / "autonomous-tooltip-supervision-v1"
    if not shop_rows:
        run_stream(
            [
                sys.executable,
                str(repo / "scripts/run_autonomous_source_supervision.py"),
                "--collection", str(dense),
                "--output", str(tooltip),
            ],
            repo,
        )
        tooltip_file = tooltip / "tooltip-consensus" / "auto-labels.json"
        if not tooltip_file.is_file():
            die("tooltip supervision missing auto-labels.json")
        value = load_json(tooltip_file)
        if not isinstance(value, list):
            die("tooltip auto-labels must be a list")
        tooltip_rows = value

    gold_rows = shop_rows if shop_rows else tooltip_rows
    gold_source = (
        shop_gold
        if shop_rows
        else tooltip / "tooltip-consensus" / "auto-labels.json"
    )

    summary: dict[str, Any] = {
        "schema_version": 1,
        "target_id": TARGET_ID,
        "source_id": source_id,
        "window_source_id": window_source_id,
        "source_url": source_url,
        "checkpoint_partition": current_partition,
        "selection_audit": row.get("_selection_audit"),
        "window_start_seconds": start,
        "window_end_seconds": end,
        "window_duration_seconds": info["duration"],
        "shop_gold_auto_labels": len(shop_rows),
        "tooltip_gold_auto_labels": len(tooltip_rows),
        "human_review_required": False,
        "training_performed": False,
        "runtime_approved": False,
    }

    if gold_rows:
        adjudication = out / "autonomous-gold-adjudication-v2"
        run_stream(
            [
                sys.executable,
                str(repo / "scripts/adjudicate_autonomous_gold_anchors.py"),
                "--collection", str(dense),
                "--anchors", str(gold_source),
                "--output", str(adjudication),
            ],
            repo,
        )
        supported = load_json(adjudication / "supported-gold-anchors.json")
        if not isinstance(supported, list):
            die("supported gold output invalid")
        summary["supported_gold_anchors"] = len(supported)
        summary["status"] = "complete_with_direct_gold"
        summary["gold_adjudication"] = str(adjudication)
    else:
        transitions = shop / "shop-miner" / "transition-proposals.json"
        rescue = out / "multiteacher-shop-silver-v1"
        run_stream(
            [
                sys.executable,
                str(repo / "scripts/run_multiteacher_shop_silver.py"),
                "--collection", str(dense),
                "--transitions", str(transitions),
                "--target-id", TARGET_ID,
                "--output", str(rescue),
            ],
            repo,
        )
        rescue_report = load_json(rescue / "report.json")
        summary["silver_auto_labels"] = int(rescue_report.get("silver_auto_labels", 0))
        summary["silver_auto_ids"] = rescue_report.get("silver_auto_ids") or {}
        summary["status"] = "complete_multiteacher_silver"
        summary["multiteacher_rescue"] = str(rescue)

    summary_path = out / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2, sort_keys=True))
    print("\nKHAZIX_QUEUE_BOOTSTRAP_OK=true")
    print(f"SELECTED_QUEUE_SOURCE_ID={source_id}")
    print(f"SELECTED_QUEUE_PARTITION={current_partition}")
    print(f"EXISTING_KHAZIX_TRAIN_SOURCES={','.join(sorted(existing_khazix_sources))}")
    print(f"SOURCE_ID={source_id}")
    print(f"WINDOW={start}-{end}")
    print(f"SHOP_GOLD_AUTO_LABELS={len(shop_rows)}")
    print(f"TOOLTIP_GOLD_AUTO_LABELS={len(tooltip_rows)}")
    print(f"SUPPORTED_GOLD_ANCHORS={summary.get('supported_gold_anchors', 0)}")
    print(f"SILVER_AUTO_LABELS={summary.get('silver_auto_labels', 0)}")
    print("QUEUE_MODEL_PREDICTION_USED_AS_LABEL=false")
    print("HUMAN_REVIEW_REQUIRED=false")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
