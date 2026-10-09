#!/usr/bin/env python3
"""Measure the installed TFT visual reader on source videos outside its corpus.

Outputs are diagnostic observations, not labels or accuracy. The source audit
checks known training manifests; it cannot detect a reupload of the same match.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from types import SimpleNamespace

from PIL import Image, ImageDraw

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT), str(PROJECT / "apps/hud_mapper"),
                str(PROJECT / "apps/e1_replay")]

from hm.board_worker import BoardWorker  # noqa: E402
from hm.yolo_hud import YoloHudObserver  # noqa: E402

COLORS = {"board_unit": "#28df6d", "bench_unit": "#e8b951",
          "enemy_unit": "#f26363", "enemy_candidate": "#f26363"}


def _probe(video: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration", "-of", "json", str(video)],
        check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return {"width": stream["width"], "height": stream["height"],
            "duration_seconds": float(data["format"]["duration"]),
            "file_bytes": video.stat().st_size}


def _frame(video: Path, second: float) -> Image.Image:
    # ffmpeg's software path also opens AV1 replays that OpenCV fails to decode
    # on this Ubuntu machine.
    process = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-hwaccel", "none",
         "-ss", str(second), "-i", str(video), "-frames:v", "1", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "pipe:1"], capture_output=True, check=True)
    expected = 1920 * 1080 * 3
    if len(process.stdout) != expected:
        raise ValueError(f"Cannot decode 1920x1080 frame at {second}s: {video}")
    return Image.frombytes("RGB", (1920, 1080), process.stdout)


def _source_audit(name: str, references: list[Path]) -> dict:
    # A basename/ID match is a definite leak. An absent match only establishes
    # that none of these known manifests lists the source.
    matches = []
    for reference in references:
        text = reference.read_text(encoding="utf-8")
        if name in text:
            matches.append(str(reference))
    return {"source_id": name, "known_manifest_matches": matches,
            "source_id_absent_from_known_training_manifests": not matches,
            "same_match_reupload_excluded": False}


def _draw_review(image: Image.Image, detections: list[dict], path: Path) -> None:
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    for index, row in enumerate(detections):
        if row["class_name"] not in COLORS:
            continue
        box = row["box"]
        color = COLORS[row["class_name"]]
        draw.rectangle(box, outline=color, width=4)
        x, y = box[:2]
        draw.rectangle((x, max(0, y - 26), x + 45, y), fill="#121212")
        draw.text((x + 4, max(0, y - 23)), str(index), fill=color)
    canvas.save(path, quality=90)


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * p))], 1)


def _distance(before: dict, after: dict) -> float:
    a, b = before["box"], after["box"]
    center_a = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2)
    center_b = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    return ((center_a[0] - center_b[0]) ** 2 +
            (center_a[1] - center_b[1]) ** 2) ** .5


def _stability(rows: list[dict]) -> dict:
    counts = defaultdict(Counter)
    by_source = defaultdict(list)
    for row in rows:
        by_source[row["source_id"]].append(row)
    for source_rows in by_source.values():
        for left, right in zip(source_rows, source_rows[1:]):
            if right["second"] - left["second"] > 2.1:
                continue
            for zone in ("records", "bench_records", "enemy_records"):
                # The runtime repeats bench units inside `records`; count each
                # physical unit once in this diagnostic.
                first_rows = ([r for r in left[zone] if r.get("zone") != "bench_unit"]
                              if zone == "records" else left[zone])
                second_rows = ([r for r in right[zone] if r.get("zone") != "bench_unit"]
                               if zone == "records" else right[zone])
                used = set()
                for first in first_rows:
                    hits = sorted(((_distance(first, second), i, second)
                                   for i, second in enumerate(second_rows)
                                   if i not in used), key=lambda hit: hit[0])
                    hits = [hit for hit in hits if hit[0] <= 35]
                    if not hits:
                        continue
                    _, index, second = hits[0]
                    used.add(index)
                    counts[zone]["nearby_box_pairs"] += 1
                    counts[zone]["name_switches"] += first["candidate_name"] != second["candidate_name"]
    return {"by_zone": {zone: dict(counts[zone]) for zone in
                        ("records", "bench_records", "enemy_records")},
            "nearby_box_pairs": sum(row["nearby_box_pairs"] for row in counts.values()),
            "name_switches": sum(row["name_switches"] for row in counts.values()),
            "caveat": "Spatial pairs are approximate; this is consistency, not identity accuracy."}


def run(args: argparse.Namespace) -> dict:
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config.get("schema_version") != 1 or not config.get("sources"):
        raise ValueError("Expected config schema_version=1 and nonempty sources")
    references = [Path(path) for path in config["known_training_manifests"]]
    if not all(path.is_file() for path in references):
        raise FileNotFoundError("Known training manifest missing")
    sources = []
    for entry in config["sources"]:
        video = Path(entry["video"]).resolve()
        if not video.is_file():
            raise FileNotFoundError(video)
        source_id = entry["source_id"]
        audit = _source_audit(source_id, references)
        if audit["known_manifest_matches"]:
            raise ValueError(f"Source appears in training manifest: {source_id}")
        info = _probe(video)
        if (info["width"], info["height"]) != (1920, 1080):
            raise ValueError(f"Expected 1920x1080: {video}")
        moments = entry["seconds"]
        if (not moments or len(moments) != len(set(moments)) or
                any(not isinstance(t, (int, float)) or t < 0 or
                    t >= info["duration_seconds"] - 1 for t in moments)):
            raise ValueError(f"Invalid sample times: {source_id}")
        sources.append(dict(source_id=source_id, video=str(video),
                            seconds=sorted(moments), **info, audit=audit))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "frames").mkdir(exist_ok=True)
    observer = YoloHudObserver(args.project, args.bundle)
    board = BoardWorker(str(args.binary), str(args.project / "configs"))
    rows = []
    try:
        for source in sources:
            for index, second in enumerate(source["seconds"]):
                image = _frame(Path(source["video"]), second)
                rgb = image.tobytes()
                frame = SimpleNamespace(id=len(rows) + 1, epoch=1, width=1920,
                                        height=1080, pts_ms=int(second * 1000), rgb=rgb)
                start = time.perf_counter()
                read = board.observe(frame)
                board_ms = (time.perf_counter() - start) * 1000
                units, _items = observer.observe(image, read, {"slots": []},
                    {"icon_inner_offset": {"x": 0, "y": 0},
                     "icon_inner_size": {"width": 0, "height": 0}})
                total_ms = (time.perf_counter() - start) * 1000
                stem = f"{source['source_id']}-{index:02d}-{int(second * 1000):09d}"
                raw_name = f"frames/{stem}-raw.jpg"
                review_name = f"frames/{stem}-review.jpg"
                image.save(args.output / raw_name, quality=90)
                _draw_review(image, units["detections"], args.output / review_name)
                row = {"source_id": source["source_id"], "second": second,
                       "frame_raw": raw_name, "frame_review": review_name,
                       "timing_ms": {"board": round(board_ms, 1),
                                     "yolo": round(total_ms - board_ms, 1),
                                     "total": round(total_ms, 1),
                                     **{key: round(value, 1) for key, value in
                                        units["timing_ms"].items()}},
                       "markers": len(read.get("markers") or []),
                       "detections": units["detections"],
                       "records": units["records"],
                       "bench_records": units["bench_records"],
                       "enemy_records": units["enemy_records"]}
                rows.append(row)
                print(f"{source['source_id']} {second:6.1f}s | "
                      f"{total_ms:6.0f} ms | "
                      f"{sum(r.get('zone') != 'bench_unit' for r in units['records']):2d} tabuleiro, "
                      f"{len(units['bench_records']):2d} reserva, "
                      f"{len(units['enemy_records']):2d} inimigos", flush=True)
    finally:
        board.close()
    with (args.output / "observations.jsonl").open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["source_id"]].append(row)
    per_source = {}
    for source_id, source_rows in grouped.items():
        per_source[source_id] = {
            "frames": len(source_rows),
            "median_total_ms": round(statistics.median(r["timing_ms"]["total"] for r in source_rows), 1),
            "p95_total_ms": _percentile([r["timing_ms"]["total"] for r in source_rows], .95),
            "board_records": sum(sum(u.get("zone") != "bench_unit" for u in r["records"])
                                 for r in source_rows),
            "bench_records": sum(len(r["bench_records"]) for r in source_rows),
            "enemy_records": sum(len(r["enemy_records"]) for r in source_rows),
            "detector_classes": dict(Counter(d["class_name"] for r in source_rows
                                             for d in r["detections"])),
        }
    report = {"schema_version": 1, "purpose": "unseen-source diagnostic measurement",
              "ground_truth_annotations": 0, "identity_accuracy": None,
              "localization_recall": None, "predictions_used_as_labels": False,
              "source_audit": sources, "installed_detector_sha256": observer.sha,
              "installed_champion_sha256": json.loads((args.bundle /
                  "configs/catalog/active-yolo-hud-v1.json").read_text())["files"]["champions.onnx"],
              "sampled_frames": len(rows), "per_source": per_source,
              "temporal_consistency": _stability(rows),
              "limitations": ["No independent ground truth for these source videos yet.",
                              "Source IDs absent from known train manifests; same-match reuploads not ruled out.",
                              "Timestamps are sampled, not a continuous real-time FPS benchmark."]}
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=PROJECT)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    report = run(parser.parse_args())
    print(json.dumps({"frames": report["sampled_frames"],
                      "per_source": report["per_source"],
                      "temporal_consistency": report["temporal_consistency"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
