#!/usr/bin/env python3
"""Sample a gameplay video for visual review without creating training labels."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw


def video_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float)
    args = parser.parse_args()

    video = args.video.resolve(strict=True)
    if args.samples < 1 or args.samples > 100:
        parser.error("--samples must be between 1 and 100")
    duration = video_duration(video)
    end = min(duration, args.end if args.end is not None else duration)
    if not (0 <= args.start < end):
        parser.error("sampling interval must fall inside the video")

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    times = [
        args.start + (end - args.start) * (index + 0.5) / args.samples
        for index in range(args.samples)
    ]
    entries = []
    sheet = Image.new("RGB", (480 * 3, 300 * ((len(times) + 2) // 3)), "#161616")
    draw = ImageDraw.Draw(sheet)
    for index, second in enumerate(times):
        frame = output / f"frame-{index:03d}-{second:.1f}s.jpg"
        if not frame.exists():
            subprocess.run(
                [
                    "ffmpeg", "-loglevel", "error", "-ss", f"{second:.3f}",
                    "-i", str(video), "-frames:v", "1", "-q:v", "2",
                    "-y", str(frame),
                ],
                check=True,
            )
        with Image.open(frame) as source:
            thumbnail = source.convert("RGB")
            thumbnail.thumbnail((480, 270))
            width, height = source.size
        x, y = index % 3 * 480, index // 3 * 300
        sheet.paste(thumbnail, (x, y))
        draw.text((x + 8, y + 275), f"{index:03d} | {second:.1f}s", fill="white")
        entries.append(
            {
                "frame": frame.name,
                "second": round(second, 3),
                "width": width,
                "height": height,
                "identity_verified": False,
                "boxes_verified": False,
            }
        )
    sheet.save(output / "contact.jpg", quality=88)
    (output / "review_manifest.json").write_text(
        json.dumps(
            {
                "source": str(video),
                "source_duration_seconds": duration,
                "note": "These are unreviewed source frames, not training labels.",
                "frames": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(output / "contact.jpg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
