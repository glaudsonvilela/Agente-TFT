from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def parse_timestamps_ms(value: str) -> list[int]:
    result: list[int] = []
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        timestamp = int(raw)
        if timestamp < 0:
            raise ValueError("timestamps must be >= 0")
        result.append(timestamp)
    return sorted(set(result))


def interval_timestamps(
    duration_ms: int,
    every_ms: int,
    *,
    start_ms: int = 0,
    max_frames: int | None = None,
) -> list[int]:
    if duration_ms < 0:
        raise ValueError("duration_ms must be >= 0")
    if every_ms <= 0:
        raise ValueError("every_ms must be > 0")
    if start_ms < 0:
        raise ValueError("start_ms must be >= 0")

    values: list[int] = []
    current = start_ms

    while current <= duration_ms:
        values.append(current)
        if max_frames is not None and len(values) >= max_frames:
            break
        current += every_ms

    return values


def annotation_template(
    source_video: Path,
    timestamps_ms: list[int],
    image_names: list[str],
) -> dict:
    if len(timestamps_ms) != len(image_names):
        raise ValueError("timestamps and image_names must have same length")

    return {
        "schema_version": 1,
        "source_video": source_video.name,
        "frames": [
            {
                "timestamp_ms": timestamp_ms,
                "image": image_name,
            }
            for timestamp_ms, image_name in zip(
                timestamps_ms,
                image_names,
                strict=True,
            )
        ],
    }


def probe_duration_ms(video: Path) -> int:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
    )
    seconds = float(result.stdout.strip())
    if seconds < 0:
        raise ValueError("ffprobe returned negative duration")
    return int(round(seconds * 1000))


def extract_frame(
    video: Path,
    timestamp_ms: int,
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    seconds = timestamp_ms / 1000.0

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{seconds:.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output),
    ]
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract replay frames and create an Agente TFT "
            "ground-truth annotation template."
        )
    )
    parser.add_argument("video", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timestamps-ms")
    parser.add_argument("--every-seconds", type=float)
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--max-frames", type=int)
    args = parser.parse_args()

    if not args.video.exists():
        raise SystemExit(f"video not found: {args.video}")

    if bool(args.timestamps_ms) == bool(args.every_seconds):
        raise SystemExit(
            "choose exactly one of --timestamps-ms or --every-seconds"
        )

    if args.max_frames is not None and args.max_frames <= 0:
        raise SystemExit("--max-frames must be > 0")

    if args.timestamps_ms:
        timestamps = parse_timestamps_ms(args.timestamps_ms)
        if args.max_frames is not None:
            timestamps = timestamps[: args.max_frames]
    else:
        assert args.every_seconds is not None
        if args.every_seconds <= 0:
            raise SystemExit("--every-seconds must be > 0")
        if args.start_seconds < 0:
            raise SystemExit("--start-seconds must be >= 0")

        duration_ms = probe_duration_ms(args.video)
        timestamps = interval_timestamps(
            duration_ms,
            int(round(args.every_seconds * 1000)),
            start_ms=int(round(args.start_seconds * 1000)),
            max_frames=args.max_frames,
        )

    frames_dir = args.output_dir / "frames"
    image_names: list[str] = []

    for index, timestamp_ms in enumerate(timestamps, start=1):
        filename = f"{index:04d}_{timestamp_ms:09d}ms.jpg"
        relative = f"frames/{filename}"
        extract_frame(
            args.video,
            timestamp_ms,
            frames_dir / filename,
        )
        image_names.append(relative)

    template = annotation_template(
        args.video,
        timestamps,
        image_names,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    annotation_path = args.output_dir / "annotations.json"
    annotation_path.write_text(
        json.dumps(
            template,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "video": str(args.video),
                "frames": len(timestamps),
                "annotations": str(annotation_path),
                "frames_dir": str(frames_dir),
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
