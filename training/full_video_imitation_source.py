"""Index complete match videos for temporal imitation without dropping time.

This is a source audit and window index, not an imitation trainer. Windows are
overlapping views into the original MP4 files; no clips or still-frame corpus
are generated. Every decoded source frame belongs to at least one window.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from fractions import Fraction


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def window_frames(frame_count: int, length: int = 120,
                  stride: int = 60) -> list[tuple[int, int]]:
    """Return half-open frame intervals with complete temporal coverage."""
    if frame_count < 1 or length < 1 or not 1 <= stride <= length:
        raise ValueError("positive frames/length and stride <= length required")
    if frame_count <= length:
        return [(0, frame_count)]
    starts = list(range(0, frame_count - length + 1, stride))
    if starts[-1] + length < frame_count:
        starts.append(frame_count - length)
    windows = [(start, start + length) for start in starts]
    if windows[0][0] != 0 or windows[-1][1] != frame_count or any(
            current[0] > previous[1] for previous, current in zip(windows, windows[1:])):
        raise AssertionError("video window coverage has a gap")
    return windows


def probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames,duration",
         "-of", "json", str(path)], capture_output=True, text=True, check=True,
    )
    streams = json.loads(result.stdout).get("streams", [])
    if len(streams) != 1:
        raise ValueError(f"one video stream required: {path}")
    stream = streams[0]
    if [stream.get("width"), stream.get("height")] != [1920, 1080]:
        raise ValueError(f"native 1920x1080 video required: {path}")
    nominal_fps = Fraction(stream["r_frame_rate"])
    average_fps = Fraction(stream["avg_frame_rate"])
    if nominal_fps != 60 or not 59.9 <= float(average_fps) <= 60.1:
        raise ValueError(f"60 fps nominal video required: {path}")
    frames = int(stream["nb_frames"])
    if frames < 1:
        raise ValueError(f"empty video: {path}")
    return {"resolution": [1920, 1080], "fps_nominal": 60,
            "fps_average": float(average_fps),
            "frames": frames, "duration_seconds": float(stream["duration"])}


def index_corpus(corpus: Path, *, verify_hashes: bool = True,
                 match_id: str | None = None) -> dict:
    manifest = json.loads((corpus / "manifest.json").read_text())
    matches = manifest["matches"]
    if not matches or len({row["match_id"] for row in matches}) != len(matches):
        raise ValueError("distinct complete matches required")
    if match_id is not None:
        matches = [row for row in matches if row["match_id"] == match_id]
        if len(matches) != 1:
            raise ValueError(f"match not found: {match_id}")
    results = []
    for row in matches:
        path = (corpus / row["video"]).resolve()
        if path.parent != corpus.resolve() or not path.is_file():
            raise ValueError(f"missing or unsafe source video: {row['match_id']}")
        metadata = probe(path)
        if abs(metadata["duration_seconds"] - row["video_duration_seconds"]) > 0.2:
            raise ValueError(f"video duration mismatch: {row['match_id']}")
        if verify_hashes and sha256(path) != row["video_sha256"]:
            raise ValueError(f"video digest mismatch: {row['match_id']}")
        windows = window_frames(metadata["frames"])
        results.append({"match_id": row["match_id"], "source_vod_id":
                        row["match_id"].split("-")[1], "video": str(path),
                        "video_sha256": row["video_sha256"], "bytes": path.stat().st_size,
                        **metadata, "window_count": len(windows),
                        "window_start_frames": [start for start, _ in windows],
                        "final_window_end_frame": windows[-1][1],
                        "temporal_coverage_complete": True,
                        "reviewed_action_count": row.get("reviewed_action_count", 0)})
    return {"schema_version": 1, "kind": "complete_video_imitation_sources",
            "training_started": False, "video_files_intact": True,
            "selected_match_id": match_id,
            "window_length_frames": 120, "window_stride_frames": 60,
            "frames_dropped_from_window_index": 0,
            "source_video_bytes": sum(row["bytes"] for row in results),
            "source_video_seconds": sum(row["duration_seconds"] for row in results),
            "reviewed_action_labels": sum(row["reviewed_action_count"] for row in results),
            "matches": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--match-id", help="Index one complete match for a pilot")
    parser.add_argument("--skip-hashes", action="store_true",
                        help="Skip the source SHA-256 check for a quick structural audit.")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("use a new output path")
    document = index_corpus(args.corpus, verify_hashes=not args.skip_hashes,
                            match_id=args.match_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in document.items() if key != "matches"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
