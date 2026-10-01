from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ALLOWED_FIELDS = {"scene", "hp", "gold", "level", "xp", "stage", "shop", "board_unit_ids", "lobby_player_ids"}
ALLOWED_SCENES = {
    "planning_shop",
    "board_bench",
    "scouting_opponents",
    "augment",
    "transition",
    "combat",
    "other",
}


def _validate_confidence(value: Any, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field}.confidence must be numeric")
    value = float(value)
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field}.confidence must be in [0,1]")
    return value


def validate_prelabels(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("prelabels root must be an object")
    if value.get("schema_version") != 1:
        raise ValueError("prelabels schema_version must be 1")
    frames = value.get("frames")
    if not isinstance(frames, list):
        raise ValueError("prelabels.frames must be an array")

    for i, frame in enumerate(frames):
        if not isinstance(frame, dict):
            raise ValueError(f"frames[{i}] must be an object")
        if not isinstance(frame.get("timestamp_ms"), int):
            raise ValueError(f"frames[{i}].timestamp_ms must be an integer")
        if not isinstance(frame.get("image"), str):
            raise ValueError(f"frames[{i}].image must be a string")
        suggestions = frame.get("suggestions")
        if not isinstance(suggestions, dict):
            raise ValueError(f"frames[{i}].suggestions must be an object")

        for field, item in suggestions.items():
            if field not in ALLOWED_FIELDS:
                raise ValueError(f"frames[{i}].suggestions contains unsupported field {field!r}")
            if not isinstance(item, dict) or "value" not in item:
                raise ValueError(f"frames[{i}].suggestions.{field} must contain value")
            _validate_confidence(item.get("confidence"), f"frames[{i}].suggestions.{field}")

            value_item = item["value"]
            if field == "scene" and value_item not in ALLOWED_SCENES:
                raise ValueError(f"invalid scene {value_item!r}")
            if field in {"hp", "gold", "level", "xp"} and not (
                isinstance(value_item, int) and not isinstance(value_item, bool)
            ):
                raise ValueError(f"{field}.value must be an integer")
            if field == "stage" and not isinstance(value_item, str):
                raise ValueError("stage.value must be a string")
            if field == "shop" and not (
                isinstance(value_item, list)
                and len(value_item) == 5
                and all(v is None or isinstance(v, str) for v in value_item)
            ):
                raise ValueError("shop.value must be a 5-slot string/null array")
            if field in {"board_unit_ids", "lobby_player_ids"} and not (
                isinstance(value_item, list) and all(isinstance(v, str) for v in value_item)
            ):
                raise ValueError(f"{field}.value must be a string array")
    return value


def merge_prelabels(annotation_dir: Path, prelabels_path: Path) -> dict:
    annotations_path = annotation_dir / "annotations.json"
    annotations = json.loads(annotations_path.read_text(encoding="utf-8"))
    prelabels = validate_prelabels(json.loads(prelabels_path.read_text(encoding="utf-8")))

    if prelabels.get("source_video") != annotations.get("source_video"):
        raise ValueError("source_video mismatch")

    by_key = {
        (row.get("timestamp_ms"), row.get("image")): row
        for row in prelabels["frames"]
    }

    matched = 0
    missing = 0
    out_frames = []
    for frame in annotations.get("frames") or []:
        key = (frame.get("timestamp_ms"), frame.get("image"))
        suggestion = by_key.get(key)
        if suggestion is None:
            missing += 1
            continue
        matched += 1
        out_frames.append({
            "timestamp_ms": frame.get("timestamp_ms"),
            "image": frame.get("image"),
            "suggestions": suggestion.get("suggestions", {}),
        })

    output = {
        "schema_version": 1,
        "source_video": annotations.get("source_video"),
        "frames": out_frames,
    }
    output_path = annotation_dir / "prelabels.json"
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return {
        "output": str(output_path),
        "matched_frames": matched,
        "missing_frames": missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate and import AI suggestions as prelabels.json without changing ground truth."
    )
    parser.add_argument("annotation_dir", type=Path)
    parser.add_argument("prelabels", type=Path)
    args = parser.parse_args()

    result = merge_prelabels(args.annotation_dir, args.prelabels)
    print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
