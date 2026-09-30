from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

SCENE_TYPES = {
    "planning_shop",
    "board_bench",
    "scouting_opponents",
    "augment",
    "transition",
    "combat",
    "other",
}
STAGE_RE = re.compile(r"^\d+-\d+$")


def _error(report: dict[str, Any], code: str, detail: str) -> None:
    report["errors"].append({"code": code, "detail": detail})


def _warning(report: dict[str, Any], code: str, detail: str) -> None:
    report["warnings"].append({"code": code, "detail": detail})


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_annotations(
    value: Any,
    *,
    annotation_dir: Path | None = None,
    video_duration_ms: int | None = None,
    expected_video_name: str | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "ready_for_calibration": False,
        "sample_sufficient_for_first_pass": False,
        "errors": [],
        "warnings": [],
        "counts": {
            "frames": 0,
            "frames_with_any_ground_truth": 0,
            "fields": {},
            "scenes": {},
        },
    }

    if not isinstance(value, dict):
        _error(report, "ANNOTATION_ROOT_NOT_OBJECT", "annotation file must be a JSON object")
        return report

    if value.get("schema_version") != 1:
        _error(report, "UNSUPPORTED_SCHEMA_VERSION", "schema_version must be 1")

    source_video = value.get("source_video")
    if not isinstance(source_video, str) or not source_video.strip():
        _error(report, "SOURCE_VIDEO_MISSING", "source_video must be a non-empty string")
    elif expected_video_name and Path(source_video).name != Path(expected_video_name).name:
        _error(
            report,
            "SOURCE_VIDEO_MISMATCH",
            f"annotations reference {source_video!r}, expected {expected_video_name!r}",
        )

    frames = value.get("frames")
    if not isinstance(frames, list):
        _error(report, "FRAMES_NOT_ARRAY", "frames must be an array")
        return report

    report["counts"]["frames"] = len(frames)
    if len(frames) < 20:
        _warning(
            report,
            "FIRST_PASS_SAMPLE_SMALL",
            f"{len(frames)} frames found; 20-50 strategic timestamps are recommended for the first pass",
        )
    else:
        report["sample_sufficient_for_first_pass"] = True
    if len(frames) > 200:
        _warning(
            report,
            "FIRST_PASS_SAMPLE_LARGE",
            f"{len(frames)} frames found; start with a smaller strategic sample before scaling",
        )

    timestamps: set[int] = set()
    images: set[str] = set()
    field_counts: Counter[str] = Counter()
    scene_counts: Counter[str] = Counter()
    gt_frames = 0

    for index, frame in enumerate(frames):
        prefix = f"frames[{index}]"
        if not isinstance(frame, dict):
            _error(report, "FRAME_NOT_OBJECT", f"{prefix} must be an object")
            continue

        timestamp = frame.get("timestamp_ms")
        if not _is_int(timestamp):
            _error(report, "TIMESTAMP_INVALID", f"{prefix}.timestamp_ms must be an integer")
        elif timestamp < 0:
            _error(report, "TIMESTAMP_NEGATIVE", f"{prefix}.timestamp_ms must be >= 0")
        else:
            if timestamp in timestamps:
                _error(report, "TIMESTAMP_DUPLICATE", f"{prefix}.timestamp_ms duplicates {timestamp}")
            timestamps.add(timestamp)
            if video_duration_ms is not None and timestamp > video_duration_ms:
                _error(
                    report,
                    "TIMESTAMP_OUTSIDE_VIDEO",
                    f"{prefix}.timestamp_ms={timestamp} exceeds video duration {video_duration_ms}",
                )

        image = frame.get("image")
        if image is not None:
            if not isinstance(image, str) or not image.strip():
                _error(report, "IMAGE_INVALID", f"{prefix}.image must be a non-empty string when present")
            else:
                if image in images:
                    _error(report, "IMAGE_DUPLICATE", f"{prefix}.image duplicates {image!r}")
                images.add(image)
                if annotation_dir is not None and not (annotation_dir / image).is_file():
                    _error(report, "IMAGE_MISSING", f"{prefix}.image does not exist: {image}")

        scene = frame.get("scene")
        if scene is not None:
            if scene not in SCENE_TYPES:
                _error(
                    report,
                    "SCENE_INVALID",
                    f"{prefix}.scene must be one of {sorted(SCENE_TYPES)}",
                )
            else:
                scene_counts[scene] += 1

        frame_has_gt = False

        for field in ("hp", "gold", "level", "xp"):
            if field not in frame:
                continue
            frame_has_gt = True
            field_counts[field] += 1
            item = frame[field]
            if not _is_int(item):
                _error(report, "FIELD_TYPE_INVALID", f"{prefix}.{field} must be an integer")
                continue
            if item < 0:
                _error(report, "FIELD_RANGE_INVALID", f"{prefix}.{field} must be >= 0")

        if "hp" in frame and _is_int(frame["hp"]) and frame["hp"] > 100:
            _warning(report, "HP_UNUSUAL", f"{prefix}.hp={frame['hp']} is above the standard 100 starting HP")

        if "level" in frame and _is_int(frame["level"]) and not 1 <= frame["level"] <= 20:
            _error(report, "LEVEL_RANGE_INVALID", f"{prefix}.level must be in [1,20]")

        if "stage" in frame:
            frame_has_gt = True
            field_counts["stage"] += 1
            stage = frame["stage"]
            if not isinstance(stage, str) or not STAGE_RE.fullmatch(stage):
                _error(report, "STAGE_INVALID", f"{prefix}.stage must look like '4-2'")

        if "shop" in frame:
            frame_has_gt = True
            field_counts["shop"] += 1
            shop = frame["shop"]
            if not isinstance(shop, list):
                _error(report, "SHOP_NOT_ARRAY", f"{prefix}.shop must be an array")
            else:
                if len(shop) != 5:
                    _error(report, "SHOP_LENGTH_INVALID", f"{prefix}.shop must contain exactly 5 slots")
                for slot_index, unit_id in enumerate(shop):
                    if unit_id is not None and (not isinstance(unit_id, str) or not unit_id):
                        _error(
                            report,
                            "SHOP_UNIT_INVALID",
                            f"{prefix}.shop[{slot_index}] must be a unit id string or null",
                        )

        for field in ("board_unit_ids", "lobby_player_ids"):
            if field not in frame:
                continue
            frame_has_gt = True
            field_counts[field] += 1
            rows = frame[field]
            if not isinstance(rows, list):
                _error(report, "ID_LIST_NOT_ARRAY", f"{prefix}.{field} must be an array")
                continue
            for row_index, item in enumerate(rows):
                if not isinstance(item, str) or not item:
                    _error(
                        report,
                        "ID_LIST_VALUE_INVALID",
                        f"{prefix}.{field}[{row_index}] must be a non-empty string",
                    )
            if field == "lobby_player_ids" and len(rows) != len(set(rows)):
                _error(report, "LOBBY_ID_DUPLICATE", f"{prefix}.lobby_player_ids contains duplicates")

        if frame_has_gt:
            gt_frames += 1
        else:
            _warning(report, "FRAME_WITHOUT_GROUND_TRUTH", f"{prefix} has no ground-truth fields filled")

    report["counts"]["frames_with_any_ground_truth"] = gt_frames
    report["counts"]["fields"] = dict(sorted(field_counts.items()))
    report["counts"]["scenes"] = dict(sorted(scene_counts.items()))

    if frames and gt_frames == 0:
        _error(report, "NO_GROUND_TRUTH", "no frame has any ground-truth field filled")

    recommended_scenes = {
        "planning_shop",
        "board_bench",
        "scouting_opponents",
        "augment",
        "transition",
    }
    if scene_counts:
        missing_scenes = sorted(recommended_scenes - set(scene_counts))
        if missing_scenes:
            _warning(
                report,
                "SCENE_COVERAGE_INCOMPLETE",
                "missing recommended scene labels: " + ", ".join(missing_scenes),
            )
    else:
        _warning(
            report,
            "SCENE_LABELS_ABSENT",
            "scene labels are optional but recommended to verify strategic sample coverage",
        )

    report["ready_for_calibration"] = not report["errors"]
    return report


def probe_video(video: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "path": str(video),
        "exists": video.is_file(),
        "ffmpeg_available": shutil.which("ffmpeg") is not None,
        "ffprobe_available": shutil.which("ffprobe") is not None,
        "duration_ms": None,
        "video_stream": None,
        "errors": [],
        "warnings": [],
    }
    if not video.is_file():
        report["errors"].append({"code": "VIDEO_MISSING", "detail": f"video not found: {video}"})
        return report

    if not report["ffprobe_available"]:
        report["errors"].append({"code": "FFPROBE_MISSING", "detail": "ffprobe is required to inspect replay video"})
        return report

    if not report["ffmpeg_available"]:
        report["warnings"].append({"code": "FFMPEG_MISSING", "detail": "ffmpeg is required to extract replay frames"})

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=index,codec_type,width,height,avg_frame_rate",
        "-of",
        "json",
        str(video),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
        report["errors"].append({"code": "FFPROBE_FAILED", "detail": str(error)})
        return report

    duration_raw = (payload.get("format") or {}).get("duration")
    try:
        duration_ms = int(round(float(duration_raw) * 1000))
    except (TypeError, ValueError):
        duration_ms = None
    if duration_ms is None or duration_ms <= 0:
        report["errors"].append({"code": "VIDEO_DURATION_INVALID", "detail": "video duration could not be determined"})
    else:
        report["duration_ms"] = duration_ms

    streams = payload.get("streams")
    if not isinstance(streams, list):
        streams = []
    video_streams = [row for row in streams if isinstance(row, dict) and row.get("codec_type") == "video"]
    if not video_streams:
        report["errors"].append({"code": "VIDEO_STREAM_MISSING", "detail": "no video stream found"})
    else:
        stream = video_streams[0]
        width = stream.get("width")
        height = stream.get("height")
        report["video_stream"] = {
            "index": stream.get("index"),
            "width": width,
            "height": height,
            "avg_frame_rate": stream.get("avg_frame_rate"),
        }
        if not _is_int(width) or not _is_int(height) or width <= 0 or height <= 0:
            report["errors"].append({"code": "VIDEO_DIMENSIONS_INVALID", "detail": "video dimensions are invalid"})
        elif width < 1280 or height < 720:
            report["warnings"].append({
                "code": "VIDEO_RESOLUTION_LOW",
                "detail": f"{width}x{height} may reduce HUD/shop OCR accuracy; native resolution is preferred",
            })

    return report


def build_report(
    *,
    annotations_path: Path | None = None,
    video_path: Path | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": 1,
        "ready": False,
        "video": None,
        "annotations": None,
        "blockers": [],
        "warnings": [],
    }

    video_report = probe_video(video_path) if video_path is not None else None
    duration_ms = video_report.get("duration_ms") if video_report else None

    annotation_report = None
    if annotations_path is not None:
        if not annotations_path.is_file():
            annotation_report = {
                "ready_for_calibration": False,
                "errors": [{"code": "ANNOTATIONS_MISSING", "detail": f"file not found: {annotations_path}"}],
                "warnings": [],
            }
        else:
            try:
                value = json.loads(annotations_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                annotation_report = {
                    "ready_for_calibration": False,
                    "errors": [{"code": "ANNOTATIONS_JSON_INVALID", "detail": str(error)}],
                    "warnings": [],
                }
            else:
                annotation_report = validate_annotations(
                    value,
                    annotation_dir=annotations_path.parent,
                    video_duration_ms=duration_ms,
                    expected_video_name=video_path.name if video_path is not None else None,
                )

    report["video"] = video_report
    report["annotations"] = annotation_report

    for section in (video_report, annotation_report):
        if not section:
            continue
        report["blockers"].extend(section.get("errors") or [])
        report["warnings"].extend(section.get("warnings") or [])

    if annotations_path is None:
        report["warnings"].append({
            "code": "ANNOTATIONS_NOT_CHECKED",
            "detail": "pass --annotations after extracting and filling ground truth",
        })
    if video_path is None:
        report["warnings"].append({
            "code": "VIDEO_NOT_CHECKED",
            "detail": "pass --video to verify duration, stream and timestamp bounds",
        })

    report["ready"] = bool(annotation_report) and annotation_report.get("ready_for_calibration") is True and not report["blockers"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a TFT replay and/or annotation set before calibration."
    )
    parser.add_argument("--video", type=Path)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.video is None and args.annotations is None:
        parser.error("provide --video, --annotations, or both")

    report = build_report(annotations_path=args.annotations, video_path=args.video)
    encoded = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")

    return 0 if not report["blockers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
