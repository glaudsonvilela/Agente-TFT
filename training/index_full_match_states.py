"""Index visible HUD readings in a contiguous native-resolution match.

The output is sparse observation evidence. OCR never assigns actions, fills
hidden values, or decides whether the player's choices were good.
"""

from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageEnhance


REGIONS = {
    "stage": (760, 3, 855, 37),
    "gold": (1023, 881, 1065, 916),
    "level": (345, 878, 430, 916),
}


def read_text(image: Image.Image, region: tuple[int, int, int, int], whitelist: str) -> str:
    crop = image.crop(region).convert("L")
    crop = ImageEnhance.Contrast(crop).enhance(2)
    crop = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.LANCZOS)
    stream = BytesIO()
    crop.save(stream, format="PNG")
    result = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "7", "-l", "eng",
         "-c", f"tessedit_char_whitelist={whitelist}"],
        input=stream.getvalue(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        check=True,
    )
    return result.stdout.decode("utf-8", errors="replace").strip()


def parse_fields(raw: dict[str, str]) -> dict[str, int | str | None]:
    stage = re.search(r"(?<!\d)([1-9]-[1-9])(?!\d)", raw["stage"])
    gold = re.search(r"(?<!\d)(\d{1,3})(?!\d)", raw["gold"])
    level = re.search(r"(?<!\d)([1-9])(?!\d)", raw["level"])
    return {
        "stage": stage.group(1) if stage else None,
        "gold": int(gold.group(1)) if gold else None,
        "level": int(level.group(1)) if level else None,
    }


def index(frames_dir: Path, output: Path, start_seconds: float, fps: int, stride: int) -> int:
    if fps <= 0 or stride <= 0:
        raise ValueError("fps and stride must be positive")
    frames = sorted(frames_dir.glob("frame-*.jpg"))
    if not frames:
        raise ValueError("no numbered frames")
    numbers = [int(path.stem.split("-")[-1]) for path in frames]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError("frame sequence must start at 1 with no gaps")
    if output.exists():
        raise ValueError("use a new output path")

    output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with output.open("w") as stream:
        for frame_number in numbers[::stride]:
            path = frames[frame_number - 1]
            with Image.open(path) as image:
                if image.size != (1920, 1080):
                    raise ValueError(f"expected 1920x1080: {path}")
                raw = {
                    "stage": read_text(image, REGIONS["stage"], "0123456789-"),
                    "gold": read_text(image, REGIONS["gold"], "0123456789"),
                    "level": read_text(image, REGIONS["level"], "0123456789"),
                }
            row = {
                "frame": path.name,
                "source_seconds": round(start_seconds + (frame_number - 1) / fps, 3),
                "raw_ocr": raw,
                "parsed": parse_fields(raw),
                "action_label": None,
                "outcome_label": None,
            }
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1
            if written % 50 == 0:
                print(f"indexed {written} HUD samples", flush=True)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--start-seconds", required=True, type=float)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--stride", type=int, default=50,
                        help="50 frames at 10 fps gives one observation every five seconds")
    args = parser.parse_args()
    count = index(args.frames_dir, args.output, args.start_seconds, args.fps, args.stride)
    print(f"{count} sparse HUD observations; no inferred action labels", flush=True)


if __name__ == "__main__":
    main()
