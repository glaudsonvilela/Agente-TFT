"""Match001 inventory icon evidence. Presence never supplies an item ID."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate_profile(profile: dict) -> None:
    if profile.get("schema_version") != 1 or profile.get("id") != "match001-inventory-v1":
        raise ValueError("unsupported inventory profile")
    if (profile.get("reference_width"), profile.get("reference_height")) != (1920, 1080):
        raise ValueError("inventory profile resolution mismatch")
    if profile.get("slot_count") != 10 or profile.get("slot_zero_role") != "unclassified_stack_not_item_id":
        raise ValueError("inventory slot contract mismatch")
    for key in ("anchor_orange_min_fraction", "occupied_min_bright_fraction", "empty_max_bright_fraction"):
        value = profile.get(key)
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise ValueError(f"invalid {key}")
    if profile["empty_max_bright_fraction"] >= profile["occupied_min_bright_fraction"]:
        raise ValueError("inventory thresholds overlap")
    if type(profile.get("bright_min_channel")) is not int or not 0 <= profile["bright_min_channel"] <= 255:
        raise ValueError("invalid bright pixel threshold")
    for key, dimensions in (("anchor", ("x", "y", "width", "height")),
                            ("slot_origin", ("x", "y")), ("slot_size", ("width", "height")),
                            ("icon_inner_offset", ("x", "y")), ("icon_inner_size", ("width", "height"))):
        value = profile.get(key)
        if not isinstance(value, dict) or set(value) != set(dimensions) or any(type(value[d]) is not int for d in dimensions):
            raise ValueError(f"invalid {key}")
    if type(profile.get("slot_step_y")) is not int or profile["slot_step_y"] <= 0:
        raise ValueError("invalid slot spacing")
    outer, inner, offset = profile["slot_size"], profile["icon_inner_size"], profile["icon_inner_offset"]
    if (outer["width"] <= 0 or outer["height"] <= 0 or inner["width"] <= 0 or inner["height"] <= 0
            or offset["x"] < 0 or offset["y"] < 0
            or offset["x"] + inner["width"] > outer["width"]
            or offset["y"] + inner["height"] > outer["height"]):
        raise ValueError("inventory icon is outside slot")
    for rect in (profile["anchor"], slot_rect(profile, 0), slot_rect(profile, profile["slot_count"] - 1)):
        if (rect["x"] < 0 or rect["y"] < 0 or rect["width"] <= 0 or rect["height"] <= 0
                or rect["x"] + rect["width"] > 1920 or rect["y"] + rect["height"] > 1080):
            raise ValueError("inventory region outside frame")


def slot_rect(profile: dict, index: int) -> dict:
    return {"x": profile["slot_origin"]["x"],
            "y": profile["slot_origin"]["y"] + index * profile["slot_step_y"],
            **profile["slot_size"]}


def pixel_fraction(rgb: bytes, width: int, rect: dict, predicate) -> float:
    matches = 0
    for y in range(rect["y"], rect["y"] + rect["height"]):
        row = (y * width + rect["x"]) * 3
        for x in range(rect["width"]):
            index = row + x * 3
            matches += bool(predicate(rgb[index], rgb[index + 1], rgb[index + 2]))
    return matches / (rect["width"] * rect["height"])


def observe(rgb: bytes, width: int, height: int, profile: dict, *, frame_array=None) -> dict:
    validate_profile(profile)
    if (width, height) != (1920, 1080) or len(rgb) != width * height * 3:
        raise ValueError("inventory frame dimensions or buffer mismatch")
    if frame_array is not None and frame_array.shape != (height, width, 3):
        raise ValueError("inventory array dimensions mismatch")
    if frame_array is None:
        anchor = pixel_fraction(rgb, width, profile["anchor"],
                                lambda r, g, b: r > 55 and r > g * 1.25 and g > b * 1.3)
    else:
        import numpy as np
        a = profile["anchor"]
        crop = frame_array[a["y"]:a["y"] + a["height"], a["x"]:a["x"] + a["width"]]
        r, g, b = (crop[:, :, channel].astype(np.float32) for channel in range(3))
        anchor = float(np.count_nonzero((r > 55) & (r > g * 1.25) & (g > b * 1.3))) / (a["width"] * a["height"])
    panel = "located" if anchor >= profile["anchor_orange_min_fraction"] else "unavailable"
    slots = []
    for index in range(profile["slot_count"]):
        rect = slot_rect(profile, index)
        inner = {"x": rect["x"] + profile["icon_inner_offset"]["x"],
                 "y": rect["y"] + profile["icon_inner_offset"]["y"],
                 **profile["icon_inner_size"]}
        if frame_array is None:
            bright = pixel_fraction(rgb, width, inner,
                                    lambda r, g, b: max(r, g, b) > profile["bright_min_channel"])
        else:
            crop = frame_array[inner["y"]:inner["y"] + inner["height"],
                               inner["x"]:inner["x"] + inner["width"]]
            bright = float(np.count_nonzero(np.any(crop > profile["bright_min_channel"], axis=2))) / (inner["width"] * inner["height"])
        if panel == "unavailable":
            status = "unavailable"
        elif index == 0:
            status = "unclassified_stack"
        elif bright >= profile["occupied_min_bright_fraction"]:
            status = "icon_candidate"
        elif bright <= profile["empty_max_bright_fraction"]:
            status = "empty_appearance"
        else:
            status = "unknown"
        slots.append({"slot": index, "rect": rect, "status": status,
                      "bright_fraction": round(bright, 6), "item_id": None})
    return {"schema_version": 1, "profile": profile["id"], "panel_status": panel,
            "anchor_orange_fraction": round(anchor, 6), "slots": slots,
            "item_identity_established": False, "game_state_updated": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--image", type=Path, required=True)
    args = parser.parse_args()
    from PIL import Image
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    with Image.open(args.image) as image:
        image = image.convert("RGB")
        result = observe(image.tobytes(), image.width, image.height, profile)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
