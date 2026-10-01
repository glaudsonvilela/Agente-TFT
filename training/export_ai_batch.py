from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path


def build_manifest(annotation_dir: Path) -> dict:
    annotations_path = annotation_dir / "annotations.json"
    value = json.loads(annotations_path.read_text(encoding="utf-8"))
    frames = value.get("frames")
    if not isinstance(frames, list):
        raise ValueError("annotations.frames must be an array")

    rows = []
    for index, frame in enumerate(frames, start=1):
        if not isinstance(frame, dict):
            continue
        image = frame.get("image")
        timestamp_ms = frame.get("timestamp_ms")
        if not isinstance(image, str) or not isinstance(timestamp_ms, int):
            continue
        image_path = annotation_dir / image
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
        rows.append({
            "frame_index": index,
            "timestamp_ms": timestamp_ms,
            "image": image,
            "filename": image_path.name,
        })

    return {
        "schema_version": 1,
        "source_video": value.get("source_video"),
        "frames": rows,
        "instructions": {
            "output_schema": "training/AI_PRELABEL_SCHEMA.md",
            "rule": "suggestions only; do not treat AI output as ground truth",
        },
    }


def export_zip(annotation_dir: Path, output: Path) -> dict:
    manifest = build_manifest(annotation_dir)
    output.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        )
        for row in manifest["frames"]:
            source = annotation_dir / row["image"]
            archive.write(source, arcname=f"frames/{row['filename']}")

    return {
        "output": str(output),
        "frames": len(manifest["frames"]),
        "source_video": manifest.get("source_video"),
        "bytes": output.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export replay frames + manifest as a batch for AI-assisted prelabeling."
    )
    parser.add_argument("annotation_dir", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("training/ai_batches/match-001-ai-batch.zip"),
    )
    args = parser.parse_args()

    result = export_zip(args.annotation_dir, args.output)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
