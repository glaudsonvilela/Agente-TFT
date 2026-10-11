"""Conservative full-frame 1 fps scan of the local 1080p replay.

This checks framing and throughput across the recording.  It does not claim
that 1 fps inspection proves every champion identity at 60 fps.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys

from PIL import Image

from prepare_trait_icon_catalog import DEFAULT_OUTPUT

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/hud_mapper"))
from hm.trait_tooltip_session import TraitTooltipSession  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=Path, default=Path("/tmp/tft-full-1fps"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT.parent / "video-evaluation.json")
    args = parser.parse_args()
    files = sorted(args.frames.glob("*.jpg"))
    if not files:
        raise SystemExit("no 1080p replay frames found")
    session = TraitTooltipSession(DEFAULT_OUTPUT.parent / "model", min_interval_ms=0)
    timings = []
    results = []
    for i, path in enumerate(files):
        with Image.open(path) as source:
            frame = source.convert("RGB")
        if frame.size != (1920, 1080):
            raise ValueError(f"frame is clipped or resized: {path} {frame.size}")
        observation = session.observe(frame, i * 1000)
        record = {"frame": path.name}
        if observation["status"] in ("active_portraits_named", "insufficient_visual_evidence"):
            boxes = observation["boxes"]
            record.update({"trait": observation["trait"], "bounds": observation["bounds"],
                           "names": observation["candidate_names"],
                           "active_portraits": observation["active_portraits"],
                           "fully_identified_active": observation["status"] == "active_portraits_named",
                           "slots_in_frame": all(0 <= x0 < x1 <= frame.width and
                                                 0 <= y0 < y1 <= frame.height
                                                 for x0, y0, x1, y1 in boxes)})
        elapsed = observation["processing_ms"]
        timings.append(elapsed)
        if observation["status"] in ("active_portraits_named", "insufficient_visual_evidence"):
            record["processing_ms"] = round(elapsed, 2)
            results.append(record)
        if i % 50 == 0:
            print(f"processed {i + 1}/{len(files)} frames", flush=True)
    ordered = sorted(timings)
    report = {"sample_fps": 1, "source_frames": len(files), "detected_tooltip_frames": len(results),
              "all_slots_in_frame": all(r["slots_in_frame"] for r in results),
              "fully_identified_frames": sum(r["fully_identified_active"] for r in results),
              "latency_ms": {"median": round(statistics.median(timings), 2),
                             "p95": round(ordered[int(len(ordered) * .95)], 2),
                             "max": round(max(timings), 2)},
              "scope": "Full 1080p 1 fps replay scan; individual names remain visual candidates",
              "results": results}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
