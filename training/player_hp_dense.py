"""HP2: automatic, bounded dense replay evidence. No OCR/rule/label changes."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

RADIUS_MS = 1000
STEP_MS = 250
MAX_WINDOWS = 10
MAX_FRAMES = 12
STATUSES = {"accepted", "negative_display", "badge_not_found", "badge_ambiguous",
            "search_budget_exceeded", "ocr_uncertain", "ocr_conflict", "read_error"}


def load_json(path: Path) -> Any:
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError(f"JSON exceeds 16 MiB: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    # New evidence only. Never replace source reports/manifests/profiles.
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_reads(report: Any) -> list[dict]:
    rows = report.get("records") if isinstance(report, dict) else None
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValueError("HP report requires 1..1000 records")
    reads = []
    last = -1
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("read"), dict):
            raise ValueError("each HP record must contain a read object")
        r = row["read"]
        at, status = r.get("timestamp_ms"), r.get("status")
        if type(at) is not int or not last < at <= 86_400_000 or status not in STATUSES:
            raise ValueError("HP records require unique increasing timestamps and known statuses")
        if status == "accepted":
            hp, confidence = r.get("hp"), r.get("confidence")
            if type(hp) is not int or not 0 <= hp <= 300 or r.get("signed_hp") != hp:
                raise ValueError("accepted HP must have matching signed/unsigned integers")
            if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0.7 <= confidence <= 1:
                raise ValueError("invalid accepted confidence")
        location = r.get("location")
        if not isinstance(location, dict) or not isinstance(location.get("candidates"), list):
            raise ValueError("missing localization diagnostics")
        reads.append(r)
        last = at
    return reads


def build_plan(report: Any) -> dict:
    """Choose by failure status and observed changes, never by expected labels."""
    reads = validate_reads(report)
    events: dict[int, dict] = {}
    seen_marker = False
    previous_hp = None
    control = None
    for r in reads:
        at, status = r["timestamp_ms"], r["status"]
        reasons = []
        priority = 3
        if status == "accepted":
            if control is None:
                control = at
            if previous_hp is not None and r["hp"] > previous_hp:
                reasons.append("observed_increase_not_proven_error")
                priority = 0
            previous_hp = r["hp"]
        elif status in {"read_error", "ocr_conflict", "badge_ambiguous", "search_budget_exceeded"}:
            reasons.append(status)
            priority = 0
        elif status in {"ocr_uncertain", "negative_display"}:
            reasons.append(status)
            priority = 1
        elif status == "badge_not_found" and seen_marker:
            reasons.append("marker_missing_after_detection")
            priority = 2
        if len(r.get("location", {}).get("candidates", [])) == 1:
            seen_marker = True
        if reasons:
            events[at] = {"center_ms": at, "reasons": reasons, "priority": priority}
    selected = []
    if control is not None:
        selected.append({"center_ms": control, "reasons": ["accepted_control_not_ground_truth"], "priority": -1})
    skipped = []
    for event in sorted(events.values(), key=lambda x: (x["priority"], x["center_ms"])):
        neighbor = next((s for s in selected if abs(s["center_ms"] - event["center_ms"]) <= 2 * RADIUS_MS), None)
        if neighbor:
            neighbor.setdefault("nearby_events", []).append(event)
        elif len(selected) < MAX_WINDOWS:
            selected.append(event)
        else:
            skipped.append(event)
    if not selected:
        raise ValueError("no detected marker or actionable event; cannot build dense probe")
    selected.sort(key=lambda x: x["center_ms"])
    for i, s in enumerate(selected):
        s.update(id=f"window-{i:02d}", start_ms=max(0, s["center_ms"] - RADIUS_MS),
                 end_ms=s["center_ms"] + RADIUS_MS + 1)
    return {"schema_version": 1, "windows": selected, "skipped_budget": skipped,
            "radius_ms": RADIUS_MS, "step_ms": STEP_MS, "max_frames_per_window": MAX_FRAMES,
            "labels_used": False, "selection_is_retrospective": True,
            "note": "targeted diagnostic sample, not representative accuracy or prospective drift evaluation"}


def video_metadata(video: Path) -> dict:
    result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                             "-show_entries", "stream=width,height,start_time:format=start_time,duration",
                             "-of", "json", str(video)], capture_output=True, timeout=30, check=True)
    meta = json.loads(result.stdout)
    stream = meta["streams"][0]
    for entry in (stream, meta["format"]):
        # This delivery supports the zero-origin Match001 clock only. Fail rather
        # than silently mixing seek-relative time and an arbitrary source origin.
        start = float(entry.get("start_time", "nan"))
        if not math.isfinite(start) or abs(start) > 0.001:
            raise ValueError("HP2 requires a verified zero-origin video/stream timestamp")
    duration = float(meta["format"]["duration"])
    if not math.isfinite(duration) or not 0 < duration <= 86400:
        raise ValueError("invalid video duration")
    if not 0 < stream["width"] * stream["height"] <= 4096 * 2160:
        raise ValueError("video dimensions exceed HP2 budget")
    return meta


def parse_pts(log: str) -> list[dict]:
    bases = re.findall(r"config in time_base:\s*(\d+/\d+)", log)
    if len(set(bases)) != 1:
        raise ValueError("missing/changing showinfo time base")
    time_base = Fraction(bases[0])
    if time_base <= 0:
        raise ValueError("invalid time base")
    matches = re.findall(r"\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:[^\s]+.*?\bchecksum:([A-Fa-f0-9]+)", log)
    rows = []
    previous = -1
    for n, pts, checksum in matches:
        exact_ms = int(pts) * time_base * 1000
        at = math.ceil(exact_ms)  # Never label a frame earlier than its actual PTS.
        if int(n) != len(rows) or at <= previous or len(rows) >= MAX_FRAMES:
            raise ValueError("duplicate/unordered/excessive decoded PTS")
        rows.append({"timestamp_ms": at, "source_pts": int(pts), "source_time_base": bases[0],
                     "decoded_checksum": checksum, "timestamp_rounding": "ceil_ms"})
        previous = at
    if not rows:
        raise ValueError("no selected decoded frames")
    return rows


def extract_window(video: Path, window: dict, out: Path, duration_ms: int) -> dict:
    if not 0 <= window["start_ms"] <= window["center_ms"] < duration_ms:
        raise ValueError("window center outside source video")
    end_ms = min(window["end_ms"], duration_ms)
    start = window["start_ms"] / 1000
    end = end_ms / 1000
    out.mkdir()  # Unique window; refuse overwrite.
    frames = out / "frames"
    frames.mkdir()
    vf = (f"trim=start={start:.3f}:end={end:.3f},"
          f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{STEP_MS/1000:.3f})',showinfo")
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info", "-n",
               "-copyts", "-start_at_zero", "-ss", f"{start:.3f}", "-t", f"{end-start+0.5:.3f}",
               "-i", str(video), "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", vf,
               "-fps_mode", "passthrough", "-c:v", "png", "-threads:v", "1",
               "-frames:v", str(MAX_FRAMES), str(frames / "frame_%03d.png")]
    write_json(out / "decode_command.json", command)
    log_path = out / "decode.stderr"
    with log_path.open("xb") as log:
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=log, timeout=90, check=True)
    if log_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("excessive decoder log")
    pts = parse_pts(log_path.read_text(encoding="utf-8", errors="replace"))
    images = sorted(frames.glob("frame_*.png"))
    if len(images) != len(pts):
        raise ValueError("decoded frame/PTS count mismatch; evidence not usable")
    if len(pts) == MAX_FRAMES:
        raise ValueError("frame cap reached; possible truncation, refusing success")
    if len(pts) < 2:
        raise ValueError("dense window has fewer than two source frames")
    for row, path in zip(pts, images):
        if not window["start_ms"] <= row["timestamp_ms"] <= end_ms:
            raise ValueError("decoded timestamp outside requested window")
        row.update(image=str(path.relative_to(out)), sha256=sha256(path))
    manifest = {"schema_version": 1, "frames": pts, "labels_used": False,
                "source_video": str(video), "window": window,
                "time_basis": "decoded source PTS (zero-origin), not a synthetic frame counter",
                "retrospective_selection": True}
    write_json(out / "manifest.json", manifest)
    return manifest


def analyze_window(report: dict, manifest: dict) -> dict:
    reads = validate_reads(report)
    if [r["timestamp_ms"] for r in reads] != [r["timestamp_ms"] for r in manifest["frames"]]:
        raise ValueError("probe output does not match decoded manifest timestamps")
    if report.get("summary", {}).get("game_state_updated") is not False or report["summary"].get("profile_promoted") is not False:
        raise ValueError("expected diagnostic-only probe")
    flags = []
    previous = None
    for r in reads:
        if r["status"] != "accepted":
            previous = None
            continue
        if previous is not None and r["timestamp_ms"] - previous["timestamp_ms"] <= 750 and r["hp"] > previous["hp"]:
            flags.append({"timestamp_ms": r["timestamp_ms"], "from": previous["hp"], "to": r["hp"],
                          "kind": "observed_increase_not_proven_error"})
        previous = r
    runs = []
    for r in reads:
        key = (r["status"], r.get("signed_hp"))
        if runs and key == (runs[-1]["status"], runs[-1]["signed_hp"]):
            runs[-1]["frames"] += 1
            runs[-1]["last_ms"] = r["timestamp_ms"]
        else:
            runs.append({"status": key[0], "signed_hp": key[1], "frames": 1,
                         "first_ms": r["timestamp_ms"], "last_ms": r["timestamp_ms"]})
    confirmed = [row["freshness"]["current"] for row in report["records"] if row.get("freshness", {}).get("current") is not None]
    return {"window": manifest["window"], "frames": len(reads), "statuses": dict(Counter(r["status"] for r in reads)),
            "confirmed_frames": len(confirmed), "runs": runs, "flags": flags,
            "repeated_decoded_checksums": len(reads) - len({r["decoded_checksum"] for r in manifest["frames"]}),
            "max_gap_ms": max((b["timestamp_ms"]-a["timestamp_ms"] for a,b in zip(reads, reads[1:])), default=None),
            "note": "temporal agreement is not correctness, independence or account identity; no value correction"}


def prepare(args: argparse.Namespace) -> None:
    video, source, out = args.video.resolve(strict=True), args.source.resolve(strict=True), args.output.resolve(strict=True)
    if not video.is_file() or not out.is_dir():
        raise ValueError("require local video and existing NEW output directory")
    plan = build_plan(load_json(source))
    meta = video_metadata(video)
    plan.update(source_report=str(source), source_report_sha256=sha256(source),
                source_video=str(video), video_size=video.stat().st_size, video_mtime_ns=video.stat().st_mtime_ns,
                source_video_hash="not_computed; size/mtime are not content identity", video_metadata=meta)
    write_json(out / "plan.json", plan)
    for w in plan["windows"]:
        print(f"HP2_EXTRACT={w['id']} center_ms={w['center_ms']} reasons={','.join(w['reasons'])}", flush=True)
        extract_window(video, w, out / w["id"], math.floor(float(meta["format"]["duration"]) * 1000))
        if (video.stat().st_size, video.stat().st_mtime_ns) != (plan["video_size"], plan["video_mtime_ns"]):
            raise ValueError("source video changed during extraction")
    write_json(out / "prepared.json", {"complete": True, "windows": len(plan["windows"])})


def summarize(out: Path) -> None:
    plan = load_json(out / "plan.json")
    if not load_json(out / "prepared.json")["complete"]:
        raise ValueError("incomplete frame extraction")
    windows = []
    for w in plan["windows"]:
        folder = out / w["id"]
        manifest, report = load_json(folder / "manifest.json"), load_json(folder / "report.json")
        windows.append(analyze_window(report, manifest))
    statuses = Counter()
    for w in windows:
        statuses.update(w["statuses"])
    summary = {"schema_version": 1, "windows": len(windows), "frames": sum(w["frames"] for w in windows),
               "statuses": dict(statuses), "confirmed_frames": sum(w["confirmed_frames"] for w in windows),
               "increase_flags": sum(len(w["flags"]) for w in windows),
               "execution_complete": statuses["read_error"] == 0, "exact_accuracy": None,
               "metric_kind": "targeted_temporal_diagnostics", "labels_used": False,
               "game_state_updated": False, "profile_promoted": False, "ocr_changed": False,
               "warning": "targeted clips selected retrospectively; no independent accuracy or adaptation claim"}
    write_json(out / "report.json", {"summary": summary, "windows": windows})
    for window in windows:
        print("HP2_WINDOW=" + json.dumps(window, ensure_ascii=False))
    print("HP2_SUMMARY=" + json.dumps(summary, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("source", type=Path)
    p.add_argument("video", type=Path)
    p.add_argument("output", type=Path)
    sub.add_parser("summarize").add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        prepare(args) if args.command == "prepare" else summarize(args.output)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f"HP2_ERROR={exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
