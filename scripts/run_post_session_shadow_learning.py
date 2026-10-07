#!/usr/bin/env python3
"""Post-session autonomous shadow learning for one sealed HM4/HM4.5 session.

The live model is immutable during the match. After COMPLETE.json exists:
1. verify the dedicated shadow-learning capture;
2. reconstruct a 0.5 FPS learning video from the 2 s JPEG stream;
3. run autonomous shop and tooltip teachers;
4. adjudicate direct gold, propagate conservative silver;
5. train a challenger against the frozen champion;
6. write shadow-candidate.json only if the challenger wins validation.

This runner never promotes a model into the live runtime.
"""

from __future__ import annotations

import argparse
import os
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


def die(message: str) -> "NoReturn":
    raise SystemExit(f"POST_SESSION_SHADOW_LEARNING_ERROR: {message}")


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


def write_state(path: Path, **values: Any) -> None:
    old = load_json(path) if path.is_file() else {}
    old.update(values)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(old, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def verify_capture(session: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    complete = session / "COMPLETE.json"
    summary_path = session / "summary.json"
    sealed_path = session / "shadow-learning" / "SEALED.json"
    manifest_path = session / "shadow-learning" / "capture-manifest.json"
    for path in (complete, summary_path, sealed_path, manifest_path):
        if not path.is_file():
            die(f"sealed session file missing: {path}")

    summary = load_json(summary_path)
    if summary.get("execution_complete") is not True:
        die("session is not execution_complete")
    if summary.get("active_model_changed_during_session") not in (False, None):
        die("active model changed during session")

    sealed = load_json(sealed_path)
    manifest_raw = manifest_path.read_bytes()
    if sealed.get("manifest_sha256") != hashlib.sha256(manifest_raw).hexdigest():
        die("shadow-learning manifest checksum mismatch")
    if sealed.get("ready_for_post_session_learning") is not True:
        die("shadow-learning capture is too small")

    manifest = json.loads(manifest_raw)
    frames = manifest.get("frames")
    if not isinstance(frames, list) or len(frames) < 2:
        die("shadow-learning capture contains fewer than two frames")
    if manifest.get("training_performed_during_session") is not False:
        die("training unexpectedly occurred during live session")
    if manifest.get("active_model_changed_during_session") is not False:
        die("live model mutability contract violated")

    for index, row in enumerate(frames):
        if not isinstance(row, dict) or row.get("index") != index:
            die("shadow-learning frame sequence is not contiguous")
        if (row.get("width"), row.get("height")) != (1920, 1080):
            die("shadow-learning frame is not canonical 1920x1080")
        image = session / "shadow-learning" / str(row.get("image", ""))
        if not image.is_file():
            die(f"learning frame missing: {image}")
        if sha256_file(image) != row.get("image_sha256"):
            die(f"learning frame checksum mismatch: {image}")
    return summary, manifest, manifest_path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--session", type=Path, required=True)
    p.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    p.add_argument("--autonomous-corpus", type=Path)
    p.add_argument("--ffmpeg", default="ffmpeg")
    args = p.parse_args()

    repo = args.repo.expanduser().resolve()
    session = args.session.expanduser().resolve()
    selection = args.selection.expanduser().resolve()
    autonomous_corpus = (
        args.autonomous_corpus.expanduser().resolve()
        if args.autonomous_corpus is not None
        else None
    )
    if not selection.is_file():
        die(f"frozen selection not found: {selection}")
    cargo_manifest = repo / "tools/unit-features-lab/Cargo.toml"
    packaged_bins = os.environ.get("AGENTE_TFT_UNIT_LAB_BIN_DIR")
    if not cargo_manifest.is_file() and not packaged_bins:
        die(f"no source or packaged unit-lab runtime under: {repo}")
    if not session.is_dir():
        die(f"session directory not found: {session}")

    summary, capture, capture_manifest = verify_capture(session)
    work = session / "shadow-learning" / "post-session-v1"
    work.mkdir(parents=True, exist_ok=True)
    state = work / "state.json"

    if state.is_file():
        old = load_json(state)
        if old.get("status") == "complete":
            print("POST_SESSION_SHADOW_LEARNING_RESUME=already_complete")
            print(json.dumps(old, ensure_ascii=False, indent=2))
            return 0

    session_id = str(summary.get("session_id") or capture.get("session_id") or "")
    if not session_id:
        die("session_id missing")
    source_id = f"hm45-session:{session_id}"
    write_state(
        state,
        schema_version=1,
        status="verifying",
        session_id=session_id,
        source_id=source_id,
        active_model_changed_during_session=False,
        training_performed_during_session=False,
        human_review_required=False,
        runtime_approved=False,
    )

    video = work / "learning-source.mp4"
    if not video.is_file():
        write_state(state, status="reconstructing_learning_video")
        run_stream(
            [
                args.ffmpeg,
                "-hide_banner", "-loglevel", "warning", "-y",
                "-framerate", "0.5",
                "-i", str(session / "shadow-learning" / "frames" / "%06d.jpg"),
                "-an",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                str(video),
            ],
            repo,
            work / "ffmpeg.log",
        )
    if not video.is_file() or video.stat().st_size <= 0:
        die("learning video reconstruction failed")

    dense = work / "annotation-2s-shop-dense"
    shop = work / "autonomous-shop-supervision-v1"
    write_state(state, status="autonomous_shop_supervision")
    run_stream(
        [
            sys.executable,
            str(repo / "scripts/run_autonomous_shop_supervision.py"),
            "--source", str(video),
            "--dense-collection", str(dense),
            "--output", str(shop),
            "--source-id", source_id,
            "--source-url", f"session://{session_id}",
        ],
        repo,
        work / "shop-supervision.log",
    )

    shop_gold = shop / "shop-consensus" / "auto-labels.json"
    shop_rows = load_json(shop_gold)
    if not isinstance(shop_rows, list):
        die("shop auto-labels must be a list")

    tooltip_rows: list[dict[str, Any]] = []
    tooltip = work / "autonomous-tooltip-supervision-v1"
    gold_file = shop_gold
    gold_rows = shop_rows
    if not gold_rows:
        write_state(state, status="autonomous_tooltip_supervision")
        run_stream(
            [
                sys.executable,
                str(repo / "scripts/run_autonomous_source_supervision.py"),
                "--collection", str(dense),
                "--output", str(tooltip),
            ],
            repo,
            work / "tooltip-supervision.log",
        )
        tooltip_file = tooltip / "tooltip-consensus" / "auto-labels.json"
        tooltip_rows = load_json(tooltip_file)
        if not isinstance(tooltip_rows, list):
            die("tooltip auto-labels must be a list")
        if tooltip_rows:
            gold_file = tooltip_file
            gold_rows = tooltip_rows

    if not gold_rows:
        result = {
            "status": "complete",
            "outcome": "no_direct_gold_no_training",
            "session_id": session_id,
            "source_id": source_id,
            "shop_gold_auto_labels": 0,
            "tooltip_gold_auto_labels": 0,
            "challenger_trained": False,
            "shadow_candidate_created": False,
            "active_model_changed": False,
            "human_review_required": False,
            "runtime_approved": False,
        }
        write_state(state, **result)
        print("\nPOST_SESSION_SHADOW_LEARNING_OK=true")
        print("OUTCOME=no_direct_gold_no_training")
        return 0

    adjudication = work / "autonomous-gold-adjudication-v2"
    write_state(state, status="adjudicating_gold")
    run_stream(
        [
            sys.executable,
            str(repo / "scripts/adjudicate_autonomous_gold_anchors.py"),
            "--selection", str(selection),
            "--collection", str(dense),
            "--anchors", str(gold_file),
            "--output", str(adjudication),
        ],
        repo,
        work / "gold-adjudication.log",
    )
    supported = adjudication / "supported-gold-anchors.json"
    supported_rows = load_json(supported)
    if not isinstance(supported_rows, list):
        die("supported gold must be a list")

    if not supported_rows:
        write_state(
            state,
            status="complete",
            outcome="gold_quarantined_no_training",
            direct_gold_labels=len(gold_rows),
            supported_gold_anchors=0,
            challenger_trained=False,
            shadow_candidate_created=False,
            active_model_changed=False,
        )
        print("\nPOST_SESSION_SHADOW_LEARNING_OK=true")
        print("OUTCOME=gold_quarantined_no_training")
        return 0

    propagation = work / "autonomous-propagation-supported-v1"
    write_state(state, status="propagating_silver")
    run_stream(
        [
            sys.executable,
            str(repo / "scripts/propagate_autonomous_gold_anchors.py"),
            "--selection", str(selection),
            "--collection", str(dense),
            "--anchors", str(supported),
            "--output", str(propagation),
        ],
        repo,
        work / "silver-propagation.log",
    )
    silver = propagation / "silver-auto-labels.json"
    silver_rows = load_json(silver)
    if not isinstance(silver_rows, list):
        die("silver auto labels must be a list")

    corpus_counts = None
    if autonomous_corpus is not None:
        write_state(state, status="ingesting_central_autonomous_corpus")
        run_stream(
            [
                sys.executable,
                str(repo / "trainer/scripts/ingest_autonomous_corpus.py"),
                "--manifest", str(autonomous_corpus),
                "--collection", str(dense),
                "--gold", str(supported),
                "--silver", str(silver),
                "--source-id", source_id,
            ],
            repo,
            work / "autonomous-corpus-ingest.log",
        )
        if not autonomous_corpus.is_file():
            die("central autonomous corpus manifest was not created")
        corpus_doc = load_json(autonomous_corpus)
        if (
            corpus_doc.get("schema_version") != 1
            or corpus_doc.get("policy") != "central_autonomous_corpus_v1"
            or not isinstance(corpus_doc.get("sources"), list)
        ):
            die("central autonomous corpus manifest is incompatible")
        corpus_counts = corpus_doc.get("counts") or {}
        current_in_corpus = any(
            isinstance(row, dict) and row.get("source_id") == source_id
            for row in corpus_doc["sources"]
        )
        if not current_in_corpus:
            result = {
                "status": "complete",
                "outcome": "duplicate_supervision_no_training",
                "session_id": session_id,
                "source_id": source_id,
                "supported_gold_anchors": len(supported_rows),
                "silver_auto_labels": len(silver_rows),
                "central_corpus_counts": corpus_counts,
                "challenger_trained": False,
                "shadow_candidate_created": False,
                "active_model_changed": False,
                "human_review_required": False,
                "runtime_approved": False,
            }
            write_state(state, **result)
            print("\nPOST_SESSION_SHADOW_LEARNING_OK=true")
            print("OUTCOME=duplicate_supervision_no_training")
            print(f"CENTRAL_CORPUS_SOURCES={corpus_counts.get('sources', 0)}")
            print(f"CENTRAL_CORPUS_GOLD={corpus_counts.get('gold', 0)}")
            print(f"CENTRAL_CORPUS_SILVER={corpus_counts.get('silver', 0)}")
            return 0

    challenger = work / "challenger"
    write_state(
        state,
        status="training_challenger",
        central_corpus_counts=corpus_counts,
    )
    run_stream(
        [
            sys.executable,
            str(repo / "scripts/train_weighted_autonomous_challenger.py"),
            "--selection", str(selection),
            "--collection", str(dense),
            "--gold", str(supported),
            "--silver", str(silver),
            "--private-root", str(work),
            "--output-root", str(challenger),
            *(
                [
                    "--autonomous-corpus", str(autonomous_corpus),
                    "--embedding-cache", str(autonomous_corpus.parent / "embedding-cache"),
                ]
                if autonomous_corpus is not None
                else []
            ),
            "--skip-tests",
        ],
        repo,
        work / "challenger-training.log",
    )

    selection = load_json(challenger / "autonomous-challenger-selection.json")
    selected_arm = selection.get("selected_arm")
    shadow_candidate_created = selected_arm == "weighted-autonomous"
    if shadow_candidate_created:
        candidate = {
            "schema_version": 1,
            "status": "shadow_candidate_only",
            "session_id": session_id,
            "source_id": source_id,
            "model_path": selection.get("selected_model_path"),
            "model_sha256": selection.get("selected_model_sha256"),
            "selection_rule": selection.get("selection_rule"),
            "validation": (selection.get("challenger") or {}).get("validation"),
            "baseline_validation": (selection.get("baseline") or {}).get("validation"),
            "minjo_kh_used_for_selection": False,
            "active_runtime_replaced": False,
            "requires_future_shadow_sessions": True,
            "runtime_approved": False,
        }
        (work / "shadow-candidate.json").write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    result = {
        "status": "complete",
        "outcome": "shadow_candidate_created" if shadow_candidate_created else "baseline_retained",
        "session_id": session_id,
        "source_id": source_id,
        "shop_gold_auto_labels": len(shop_rows),
        "tooltip_gold_auto_labels": len(tooltip_rows),
        "supported_gold_anchors": len(supported_rows),
        "silver_auto_labels": len(silver_rows),
        "central_corpus_counts": corpus_counts,
        "challenger_trained": True,
        "selected_arm": selected_arm,
        "shadow_candidate_created": shadow_candidate_created,
        "active_model_changed": False,
        "human_review_required": False,
        "runtime_approved": False,
    }
    write_state(state, **result)

    print("\nPOST_SESSION_SHADOW_LEARNING_OK=true")
    print(f"OUTCOME={result['outcome']}")
    print(f"SUPPORTED_GOLD_ANCHORS={len(supported_rows)}")
    print(f"SILVER_AUTO_LABELS={len(silver_rows)}")
    if corpus_counts is not None:
        print(f"CENTRAL_CORPUS_SOURCES={corpus_counts.get('sources', 0)}")
        print(f"CENTRAL_CORPUS_GOLD={corpus_counts.get('gold', 0)}")
        print(f"CENTRAL_CORPUS_SILVER={corpus_counts.get('silver', 0)}")
    print(f"SELECTED_ARM={selected_arm}")
    print(f"SHADOW_CANDIDATE_CREATED={str(shadow_candidate_created).lower()}")
    print("ACTIVE_MODEL_CHANGED=false")
    print("HUMAN_REVIEW_REQUIRED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
