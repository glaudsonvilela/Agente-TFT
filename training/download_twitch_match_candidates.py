"""Resume targeted 1080p Twitch match cuts from storyboard candidate intervals.

Metadata checks here do not establish that a cut contains a complete ranked game.
Loading, round 1-1, result, patch, and player must be checked separately.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def parse_time(value: str) -> int:
    hours, minutes, seconds = (int(part) for part in value.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def probe_video(path: Path) -> dict:
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate",
            "-show_entries", "format=duration", "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--vod-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-slot", type=int, default=1)
    parser.add_argument("--stop-slot", type=int)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    vod = next(v for v in config["source_vods"] if v["twitch_id"] == args.vod_id)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for slot, (start, end) in enumerate(vod["interval_candidates_hhmmss"], start=1):
        if slot < args.start_slot or (args.stop_slot is not None and slot > args.stop_slot):
            continue
        stem = f"setsuko-{args.vod_id}-slot{slot:02d}-candidate-1080p"
        path = args.output_dir / f"{stem}.mp4"
        sidecar = args.output_dir / f"{stem}.json"
        if path.exists() and sidecar.exists():
            old = json.loads(sidecar.read_text(encoding="utf-8"))
            if old.get("source_interval_hhmmss") == [start, end]:
                print(f"SKIP {stem}", flush=True)
                continue
        log_path = args.output_dir / f"{stem}.download.log"
        command = [
            "yt-dlp", "-f", "1080p60", "--download-sections", f"*{start}-{end}",
            "--no-progress", "-o", str(args.output_dir / f"{stem}.%(ext)s"),
            f"https://www.twitch.tv/videos/{args.vod_id}",
        ]
        print(f"START {stem} {start}-{end}", flush=True)
        with log_path.open("w", encoding="utf-8") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        probe = probe_video(path)
        stream = probe["streams"][0]
        if (stream["width"], stream["height"]) != (1920, 1080):
            raise RuntimeError(f"{path}: expected 1920x1080, got {stream}")
        duration = float(probe["format"]["duration"])
        expected = parse_time(end) - parse_time(start)
        if duration < expected * 0.9:
            raise RuntimeError(f"{path}: cut too short ({duration:.1f}s vs {expected}s)")
        sidecar.write_text(
            json.dumps(
                {
                    "source_vod_id": args.vod_id,
                    "source_interval_hhmmss": [start, end],
                    "video": path.name,
                    "duration_seconds": duration,
                    "resolution": [stream["width"], stream["height"]],
                    "frame_rate": stream["avg_frame_rate"],
                    "review_status": "metadata_only; complete_match_and_patch_unverified",
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        print(f"DONE {stem} {duration:.1f}s", flush=True)


if __name__ == "__main__":
    main()
