#!/usr/bin/env python3
"""Run one targeted autonomous source through the full pre-training pipeline.

Stages:
1. verified 1080p acquisition (if source.mp4 is absent);
2. dense annotation-only collection + shop/purchase consensus;
3. strict tooltip/name temporal consensus fallback when shop produces no gold;
4. autonomous gold adjudication;
5. silver propagation when every supported class already exists in the frozen head.

No training occurs here. Human review is never required.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261006"
)
DEFAULT_SELECTION = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/missing-classes-training-20261005/"
    "optimizer-study-resume-20261005-101237/optimizer-study-selection.json"
)


def die(message: str) -> "NoReturn":
    raise SystemExit(f"TARGETED_AUTONOMOUS_PIPELINE_ERROR: {message}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"cannot read JSON {path}: {exc}")


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


def verify_existing_source(base: Path, url: str) -> Path | None:
    video = base / "source.mp4"
    metadata = base / "source-metadata.json"
    url_file = base / "source-url.txt"
    if not video.exists():
        return None
    if not metadata.is_file() or not url_file.is_file():
        die("source.mp4 exists without acquisition metadata/url provenance")
    if url_file.read_text(encoding="utf-8").strip() != url:
        die("existing source URL differs from requested URL")
    doc = load_json(metadata)
    if (
        doc.get("source_url") != url
        or doc.get("width") != 1920
        or doc.get("height") != 1080
        or doc.get("training_performed") is not False
        or doc.get("runtime_approved") is not False
    ):
        die("existing source metadata does not satisfy acquisition contract")
    return video.resolve()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--url", required=True)
    p.add_argument("--source-id", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    args = p.parse_args()

    repo = args.repo.expanduser().resolve()
    root = args.root.expanduser()
    base = root / args.slug
    selection_path = args.selection.expanduser().resolve()

    if not (repo / "tools/unit-features-lab/Cargo.toml").is_file():
        die(f"not an Agente-TFT checkout: {repo}")
    if "/" in args.slug or args.slug in {"", ".", ".."}:
        die("--slug must be a simple directory name")
    if not args.source_id.startswith(("youtube:", "twitch:")):
        die("--source-id must be an explicit source token")
    if not args.url.startswith("https://"):
        die("--url must be https")
    if not selection_path.is_file():
        die(f"frozen selection not found: {selection_path}")

    base.mkdir(parents=True, exist_ok=True)
    video = verify_existing_source(base, args.url)
    if video is None:
        run_stream(
            [
                "bash",
                str(repo / "scripts/acquire_targeted_video_1080p.sh"),
                args.url,
                str(base),
            ],
            repo,
        )
        video = verify_existing_source(base, args.url)
        if video is None:
            die("acquisition finished without a verified source.mp4")

    dense = base / "annotation-2s-shop-dense"
    shop = base / "autonomous-shop-supervision-v1"
    run_stream(
        [
            sys.executable,
            str(repo / "scripts/run_autonomous_shop_supervision.py"),
            "--source",
            str(video),
            "--dense-collection",
            str(dense),
            "--output",
            str(shop),
            "--source-id",
            args.source_id,
            "--source-url",
            args.url,
        ],
        repo,
    )

    shop_gold = shop / "shop-consensus" / "auto-labels.json"
    if not shop_gold.is_file():
        die("shop supervision finished without gold label file")
    shop_gold_rows = load_json(shop_gold)
    if not isinstance(shop_gold_rows, list):
        die("shop gold label file must be a list")

    summary: dict[str, Any] = {
        "schema_version": 1,
        "source_id": args.source_id,
        "source_url": args.url,
        "base": str(base),
        "dense_collection": str(dense),
        "shop_supervision": str(shop),
        "shop_gold_auto_labels": len(shop_gold_rows),
        "human_review_required": False,
        "training_performed": False,
        "runtime_approved": False,
    }

    gold = shop_gold
    gold_rows = shop_gold_rows
    gold_teacher = "shop_purchase_bench"

    if not gold_rows:
        tooltip = base / "autonomous-tooltip-supervision-v1"
        run_stream(
            [
                sys.executable,
                str(repo / "scripts/run_autonomous_source_supervision.py"),
                "--collection",
                str(dense),
                "--output",
                str(tooltip),
            ],
            repo,
        )
        tooltip_gold = tooltip / "tooltip-consensus" / "auto-labels.json"
        if not tooltip_gold.is_file():
            die("tooltip supervision finished without auto-labels.json")
        tooltip_rows = load_json(tooltip_gold)
        if not isinstance(tooltip_rows, list):
            die("tooltip gold label file must be a list")
        summary["tooltip_supervision"] = str(tooltip)
        summary["tooltip_gold_auto_labels"] = len(tooltip_rows)
        if tooltip_rows:
            gold = tooltip_gold
            gold_rows = tooltip_rows
            gold_teacher = "tooltip_temporal_consensus"

    summary["gold_teacher"] = gold_teacher if gold_rows else None
    summary["gold_auto_labels"] = len(gold_rows)

    if not gold_rows:
        summary["status"] = "complete_no_gold_after_independent_teachers"
        summary["next"] = (
            "Acquire another training-side source or add a genuinely independent "
            "game-derived teacher; do not weaken OCR/association thresholds."
        )
        out = base / "autonomous-source-summary.json"
        out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
        print("\nTARGETED_AUTONOMOUS_SOURCE_OK=true")
        print("GOLD_AUTO_LABELS=0")
        print("SUPPORTED_GOLD_ANCHORS=0")
        print("SILVER_AUTO_LABELS=0")
        print("HUMAN_REVIEW_REQUIRED=false")
        print("TRAINING_PERFORMED=false")
        print("RUNTIME_APPROVED=false")
        return 0

    adjudication = base / "autonomous-gold-adjudication-v2"
    run_stream(
        [
            sys.executable,
            str(repo / "scripts/adjudicate_autonomous_gold_anchors.py"),
            "--collection",
            str(dense),
            "--anchors",
            str(gold),
            "--output",
            str(adjudication),
        ],
        repo,
    )

    supported = adjudication / "supported-gold-anchors.json"
    if not supported.is_file():
        die("adjudication finished without supported-gold-anchors.json")
    supported_rows = load_json(supported)
    if not isinstance(supported_rows, list):
        die("supported gold file must be a list")
    summary["gold_adjudication"] = str(adjudication)
    summary["supported_gold_anchors"] = len(supported_rows)
    summary["supported_gold_ids"] = sorted(
        {str(row.get("unit_id")) for row in supported_rows if isinstance(row, dict)}
    )

    if not supported_rows:
        summary["status"] = "complete_no_supported_gold"
        summary["next"] = "Acquire another source; all current gold evidence was quarantined."
        out = base / "autonomous-source-summary.json"
        out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))
        print("\nTARGETED_AUTONOMOUS_SOURCE_OK=true")
        print(f"GOLD_AUTO_LABELS={len(gold_rows)}")
        print("SUPPORTED_GOLD_ANCHORS=0")
        print("SILVER_AUTO_LABELS=0")
        print("TRAINING_PERFORMED=false")
        return 0

    selection = load_json(selection_path)
    model_path = Path(str(selection.get("selected_model_path", ""))).expanduser()
    if not model_path.is_file():
        die("selected frozen model path is missing")
    model = load_json(model_path)
    labels = set((model.get("head") or {}).get("labels") or [])
    supported_ids = {
        str(row["unit_id"])
        for row in supported_rows
        if isinstance(row, dict) and isinstance(row.get("unit_id"), str)
    }
    unseen = sorted(supported_ids - labels)

    if unseen:
        summary["status"] = "complete_bootstrap_gold_ready"
        summary["unseen_supported_classes"] = unseen
        summary["silver_auto_labels"] = 0
        summary["next"] = (
            "Train a gold-only bootstrap challenger for unseen classes before "
            "attempting neural silver propagation."
        )
    else:
        propagation = base / "autonomous-propagation-supported-v1"
        run_stream(
            [
                sys.executable,
                str(repo / "scripts/propagate_autonomous_gold_anchors.py"),
                "--collection",
                str(dense),
                "--anchors",
                str(supported),
                "--output",
                str(propagation),
            ],
            repo,
        )
        silver = propagation / "silver-auto-labels.json"
        if not silver.is_file():
            die("propagation finished without silver-auto-labels.json")
        silver_rows = load_json(silver)
        if not isinstance(silver_rows, list):
            die("silver label file must be a list")
        summary["status"] = "complete_supported_and_propagated"
        summary["autonomous_propagation"] = str(propagation)
        summary["silver_auto_labels"] = len(silver_rows)
        summary["next"] = "Train a weighted autonomous challenger without changing validation/test."

    out = base / "autonomous-source-summary.json"
    out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print("\nTARGETED_AUTONOMOUS_SOURCE_OK=true")
    print(f"BASE={base}")
    print(f"GOLD_AUTO_LABELS={len(gold_rows)}")
    print(f"SUPPORTED_GOLD_ANCHORS={len(supported_rows)}")
    print(f"SILVER_AUTO_LABELS={summary.get('silver_auto_labels', 0)}")
    if unseen:
        print("BOOTSTRAP_UNSEEN_CLASSES=" + ",".join(unseen))
    print("HUMAN_REVIEW_REQUIRED=false")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
