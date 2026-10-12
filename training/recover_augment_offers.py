"""Recover visible augment cards from a full English or Portuguese 1080p VOD.

This supplemental pass fills a missing observation lane. It does not infer
which card the player chose and is never an action-training label.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/hud_mapper")]
from hm.augment_reader import AugmentReader  # noqa: E402


def recover(video: Path, output: Path, windows: list[tuple[float, float]], *,
            fps: int = 2) -> dict:
    if fps < 1 or not video.is_file():
        raise ValueError("existing video and positive sampling rate required")
    if output.exists():
        raise FileExistsError(output)
    reader = AugmentReader(ROOT / "configs")
    counts = dict(sampled_frames=0, visible_frames=0, distinct_offers=0)
    last_offer = None
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as stream:
        for epoch, (start, duration) in enumerate(windows):
            if start < 0 or duration <= 0:
                raise ValueError("valid video windows required")
            with tempfile.TemporaryDirectory(prefix="tft-augment-") as temporary:
                pattern = str(Path(temporary) / "frame-%05d.jpg")
                subprocess.run([
                    "ffmpeg", "-nostdin", "-v", "error", "-ss", str(start),
                    "-i", str(video), "-t", str(duration), "-vf", f"fps={fps}",
                    "-q:v", "2", "-y", pattern,
                ], check=True)
                frames = sorted(Path(temporary).glob("frame-*.jpg"))
                for index, image_path in enumerate(frames):
                    with Image.open(image_path) as source:
                        image = source.convert("RGB")
                    counts["sampled_frames"] += 1
                    estimated_ms = round((start + index / fps) * 1000)
                    observation = reader.observe(image.tobytes(), *image.size,
                        frame_id=counts["sampled_frames"],
                        source_ms=estimated_ms, epoch=epoch)
                    if not observation or not observation.get("selection_visible"):
                        continue
                    counts["visible_frames"] += 1
                    offer = tuple(row.get("observed_title") for row in observation["options"])
                    if offer != last_offer:
                        last_offer = offer
                        counts["distinct_offers"] += 1
                    observation.update(supplemental_pass=True,
                        source_video=str(video), timestamp_estimated_from_fps=True,
                        game_action_label=False, selection_confirmed=False,
                        regions=[dict(id=f"augment.offer.{row['slot']}",
                                      box=row["card_box"],
                                      status="observed_card_pixels_not_label")
                                 for row in observation["options"]])
                    stream.write(json.dumps(observation, ensure_ascii=False) + "\n")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--window", required=True, action="append",
                        help="start:duration in seconds; repeat for each choice round")
    args = parser.parse_args()
    windows = [tuple(map(float, value.split(":"))) for value in args.window]
    if any(len(window) != 2 for window in windows):
        parser.error("each window must be start:duration")
    print(json.dumps(recover(args.video, args.output, windows)), flush=True)


if __name__ == "__main__":
    main()
