"""Mine silver digit crops from real TFT HUD frames with OCR consensus.

The OCR output is a teacher proposal, not independently verified ground truth.
Each source remains entirely in one split; accepted glyph boxes and values are
recorded so later review can correct mistakes without contaminating test data.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re
import subprocess

import cv2


FIELDS = {
    "stage": (766, 5, 802, 30),
    "gold": (1020, 885, 1053, 910),
    "level": (390, 883, 412, 907),
}
DIGITS = set("0123456789")


def ocr(image, mode: str):
    encoded = cv2.imencode(".png", image)[1].tobytes()
    call = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", mode,
         "-c", "tessedit_char_whitelist=0123456789-", "tsv"],
        input=encoded, capture_output=True, timeout=10, check=True,
    )
    rows = list(csv.DictReader(call.stdout.decode().splitlines(), delimiter="\t"))
    words = [row for row in rows if row.get("level") == "5" and row.get("text", "").strip()]
    return "".join(row["text"].strip() for row in words), min(
        (float(row["conf"]) for row in words), default=-1)


def boxes(image):
    encoded = cv2.imencode(".png", image)[1].tobytes()
    call = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "7",
         "-c", "tessedit_char_whitelist=0123456789-", "makebox"],
        input=encoded, capture_output=True, timeout=10, check=True,
    )
    height = image.shape[0]
    result = []
    for line in call.stdout.decode().splitlines():
        parts = line.split()
        if len(parts) != 6:
            continue
        glyph, left, bottom, right, top, _ = parts
        result.append((glyph, int(left), height-int(top), int(right), height-int(bottom)))
    return result


def valid(field, text):
    if field == "stage":
        return bool(re.fullmatch(r"[1-9]-[1-9]", text))
    if not re.fullmatch(r"\d{1,3}", text):
        return False
    value = int(text)
    return 0 <= value <= 150 if field == "gold" else 1 <= value <= 10


def record_frame(path, split, output, serial, audit, counts):
    image = cv2.imread(str(path))
    if image is None or image.shape[:2] != (1080, 1920):
        return
    for field, (x0, y0, x1, y1) in FIELDS.items():
        region = image[y0:y1, x0:x1]
        scaled = cv2.resize(region, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
        first, confidence = ocr(scaled, "7")
        second, _ = ocr(scaled, "8")
        if first != second or not valid(field, first) or confidence < 25:
            continue
        glyphs = boxes(scaled)
        if "".join(glyph for glyph, *_ in glyphs) != first:
            continue
        for position, (glyph, left, top, right, bottom) in enumerate(glyphs):
            if glyph not in DIGITS or right <= left or bottom <= top:
                continue
            left, top = max(0, left-2), max(0, top-2)
            right, bottom = min(scaled.shape[1], right+2), min(scaled.shape[0], bottom+2)
            crop = scaled[top:bottom, left:right]
            if crop.size == 0:
                continue
            destination = output / split / glyph
            destination.mkdir(parents=True, exist_ok=True)
            name = f"{serial:06d}-{field}-{position}.png"
            cv2.imwrite(str(destination / name), crop)
            counts[split][glyph] += 1
            audit.append({"source": str(path), "split": split, "field": field,
                          "teacher_value": first, "teacher_confidence": confidence,
                          "glyph": glyph, "glyph_position": position,
                          "crop": [left, top, right, bottom], "file": str(destination / name)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("annotations", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", action="append", default=[], help="split:/path/to/frames")
    args = parser.parse_args()
    annotations = json.loads(args.annotations.read_text())["frames"]
    root = args.annotations.parent / "images"
    inputs = []
    for row in annotations:
        if row["scene"] == "board":
            split = {"validation": "val", "train": "train", "test": "test"}[row["identity_split"]]
            inputs.append((split, root / row["image"]))
    for specification in args.source:
        split, folder = specification.split(":", 1)
        if split not in ("train", "val", "test"):
            parser.error(f"Invalid split: {split}")
        paths = sorted(Path(folder).glob("*.jpg")) + sorted(Path(folder).glob("*.png"))
        if not paths:
            parser.error(f"No frames in {folder}")
        inputs.extend((split, path) for path in paths)
    audit = []
    counts = {split: Counter() for split in ("train", "val", "test")}
    for serial, (split, path) in enumerate(inputs):
        record_frame(path, split, args.output, serial, audit, counts)
        if serial % 50 == 0:
            print(f"OCR {serial + 1}/{len(inputs)}", flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "audit.json").write_text(json.dumps({
        "label_kind": "ocr_consensus_silver_not_ground_truth",
        "input_frames": len(inputs), "accepted_glyphs": len(audit),
        "counts": {split: dict(count) for split, count in counts.items()},
        "glyphs": audit,
    }, ensure_ascii=False, indent=2))
    print(json.dumps({"input_frames": len(inputs), "accepted_glyphs": len(audit),
                      "counts": {split: dict(count) for split, count in counts.items()}},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
