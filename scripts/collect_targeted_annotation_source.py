#!/usr/bin/env python3
"""Collect a targeted new TFT source for visual review only.

This runner:
- requires a local 1920x1080 video
- discovers the previously validated board profile by SHA-256
- invokes the native Rust vod-collector in annotation_only mode
- never runs DINO, never creates identity labels, never trains
- writes into a new private Sherlock SSD directory

Example:
  python3 scripts/collect_targeted_annotation_source.py \
    --input /mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/elder-dragon-shurkou/source.mp4 \
    --source-id youtube:Ot358nhRJl0 \
    --source-url https://www.youtube.com/watch?v=Ot358nhRJl0 \
    --output /mnt/sherlock-ssd/AgenteTFT/diagnostics/targeted-new-sources-20261005/elder-dragon-shurkou/annotation-2s
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

BOARD_PROFILE_SHA256 = "50023142d6cc2d1a920b116f5e3e6452c5be89fbbdd3f849e37d02f23ab552c9"
DEFAULT_SEARCH_ROOTS = [
    Path("/mnt/sherlock-ssd/AgenteTFT"),
    Path.cwd(),
]


def die(message: str) -> "NoReturn":
    raise SystemExit(f"TARGETED_COLLECTION_ERROR: {message}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_video(path: Path) -> tuple[int, int, float]:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height:format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        die(f"ffprobe failed: {proc.stderr.strip()}")
    try:
        doc = json.loads(proc.stdout)
        stream = doc["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
        duration = float(doc["format"]["duration"])
    except Exception as exc:
        die(f"invalid ffprobe output: {exc}")
    if not math.isfinite(duration) or duration <= 0:
        die("video duration is invalid")
    return width, height, duration


def candidate_jsons(root: Path):
    if not root.exists():
        return
    for base, dirs, files in os.walk(root):
        dirs[:] = [
            d
            for d in dirs
            if d not in {".git", "target", "build-cache", "venv", "__pycache__"}
        ]
        for name in files:
            if not name.endswith(".json"):
                continue
            path = Path(base) / name
            try:
                if path.stat().st_size > 512 * 1024:
                    continue
            except OSError:
                continue
            yield path


def find_board_profile(explicit: Path | None, repo: Path) -> Path:
    if explicit:
        path = explicit.expanduser().resolve()
        if not path.is_file():
            die(f"board profile not found: {path}")
        if sha256_file(path) != BOARD_PROFILE_SHA256:
            die("explicit board profile SHA-256 differs from the sealed profile")
        return path

    env = os.environ.get("AGENTE_TFT_BOARD_PROFILE")
    if env:
        path = Path(env).expanduser().resolve()
        if path.is_file() and sha256_file(path) == BOARD_PROFILE_SHA256:
            return path
        die("AGENTE_TFT_BOARD_PROFILE does not match the sealed profile hash")

    roots = [Path("/mnt/sherlock-ssd/AgenteTFT"), repo]
    checked: set[Path] = set()
    for root in roots:
        for path in candidate_jsons(root) or []:
            try:
                resolved = path.resolve()
                if resolved in checked:
                    continue
                checked.add(resolved)
                if sha256_file(resolved) == BOARD_PROFILE_SHA256:
                    return resolved
            except (OSError, PermissionError):
                continue

    die(
        "sealed board profile was not found. "
        "Pass --board-profile PATH or set AGENTE_TFT_BOARD_PROFILE."
    )


def run_stream(command: list[str], cwd: Path, log_path: Path) -> None:
    print("+", " ".join(command), flush=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
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
            log.write(line)
        code = proc.wait()
    if code != 0:
        die(f"collector failed ({code}); see {log_path}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--source-id", required=True)
    p.add_argument("--source-url", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--start-seconds", type=int, default=0)
    p.add_argument("--duration-seconds", type=int)
    p.add_argument("--sample-interval-seconds", type=int, default=2)
    p.add_argument("--review-interval-seconds", type=int, default=10)
    p.add_argument("--board-profile", type=Path)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    repo = args.repo.expanduser().resolve()
    video = args.input.expanduser().resolve()
    output = args.output.expanduser()

    if not (repo / "tools/unit-features-lab/Cargo.toml").is_file():
        die(f"not an Agente-TFT checkout: {repo}")
    if not video.is_file():
        die(f"input video not found: {video}")
    if output.exists():
        die(f"output already exists: {output}")
    if str(output).startswith("/mnt/sherlock-ssd") and not Path(
        "/mnt/sherlock-ssd"
    ).is_mount():
        die("/mnt/sherlock-ssd is not mounted")

    width, height, total_duration = probe_video(video)
    if (width, height) != (1920, 1080):
        die(
            f"collector requires 1920x1080; got {width}x{height}. "
            "Use a native 1080p source to preserve geometry."
        )

    if args.start_seconds < 0:
        die("--start-seconds must be >= 0")
    if not (1 <= args.sample_interval_seconds <= 60):
        die("--sample-interval-seconds must be in 1..60")
    if (
        args.review_interval_seconds < args.sample_interval_seconds
        or args.review_interval_seconds > 3600
        or args.review_interval_seconds % args.sample_interval_seconds != 0
    ):
        die(
            "--review-interval-seconds must be a bounded multiple of the sample interval"
        )

    available = max(0, int(total_duration) - args.start_seconds)
    duration = args.duration_seconds if args.duration_seconds is not None else available
    if duration <= 0:
        die("requested source window is empty")
    duration = min(duration, available, 43200)
    if duration <= 0:
        die("no duration remains after applying source bounds")

    profile = find_board_profile(args.board_profile, repo)

    output.parent.mkdir(parents=True, exist_ok=True)
    spec_path = output.parent / f"{output.name}-spec.json"
    log_path = output.parent / f"{output.name}-collector.log"
    if spec_path.exists() or log_path.exists():
        die("spec/log path already exists; choose a new output name")

    spec: dict[str, Any] = {
        "collection_mode": "annotation_only",
        "partition": "training_pool_unlabeled",
        "training_labels_allowed": False,
        "decode_mode": "all",
        "input": str(video),
        "source_id": args.source_id,
        "source_url": args.source_url,
        "start_seconds": args.start_seconds,
        "duration_seconds": duration,
        "sample_interval_seconds": args.sample_interval_seconds,
        "review_interval_seconds": args.review_interval_seconds,
        "board_profile": str(profile),
        "output": str(output),
    }
    spec_path.write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    metadata = {
        "schema_version": 1,
        "kind": "targeted_annotation_only_collection",
        "source_id": args.source_id,
        "source_url": args.source_url,
        "input": str(video),
        "input_sha256": sha256_file(video),
        "video_width": width,
        "video_height": height,
        "video_duration_seconds": total_duration,
        "window_start_seconds": args.start_seconds,
        "window_duration_seconds": duration,
        "board_profile": str(profile),
        "board_profile_sha256": sha256_file(profile),
        "collection_mode": "annotation_only",
        "automatic_labels": False,
        "training_performed": False,
        "runtime_approved": False,
    }
    metadata_path = output.parent / f"{output.name}-metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    run_stream(
        [
            "cargo",
            "run",
            "--release",
            "--manifest-path",
            str(repo / "tools/unit-features-lab/Cargo.toml"),
            "--bin",
            "vod-collector",
            "--",
            "--spec",
            str(spec_path),
        ],
        repo,
        log_path,
    )

    report_path = output / "report.json"
    if not report_path.is_file():
        die("collector finished without report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("collection_mode") != "annotation_only":
        die("collector report is not annotation_only")
    if report.get("training_performed") is not False:
        die("collector unexpectedly reports training")
    if report.get("inference_performed") is not False:
        die("collector unexpectedly reports inference")

    print("\nTARGETED_COLLECTION_OK=true")
    print(f"OUTPUT={output}")
    print(f"SOURCE_ID={args.source_id}")
    print(f"FRAMES={report.get('frames')}")
    print(f"UNIT_CROPS={report.get('unit_crops')}")
    print(f"SAVED_REVIEW_FRAMES={report.get('saved_review_frames')}")
    print("INFERENCE_PERFORMED=false")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
