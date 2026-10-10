#!/usr/bin/env python3
"""Prepare a source-aware, visually diverse review queue for champion training.

This script does not assign identities from model predictions or start training.
It keeps the original runtime crop, exports a body-focused view for inspection,
and reports where five genuinely different observations are still missing.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


FRAME = re.compile(r"frame-(\d{6})-(.+)\.(?:jpg|png)$")
FRESH = re.compile(r"fresh-(.+)-(\d{9})-(\d{4})\.(?:jpg|png)$")
THIRD = re.compile(r"third-reviewed-(\d{4})\.png$")


def _source_id(value: str) -> str:
    twitch = re.search(r"(?:twitch:|twitch-v)(\d+)", value)
    if twitch:
        return "twitch:" + twitch.group(1)
    youtube = re.search(r"youtube[-:]([^-/]+)", value)
    if youtube:
        return "youtube:" + youtube.group(1)
    return value


def _provenance(path: str, frames: list[dict]) -> tuple[str, float | None, str]:
    filename = Path(path).name
    if match := FRAME.fullmatch(filename):
        index = int(match.group(1))
        if index >= len(frames):
            raise ValueError(f"Frame index outside reviewed annotation: {path}")
        frame = frames[index]
        source = frame.get("source_video_id") or frame.get("match_group")
        if not source:
            raise ValueError(f"Frame without source: {path}")
        return _source_id(source), frame.get("source_ms"), "reviewed_frame"
    if filename.startswith("fresh-xayah-"):
        return "youtube:D2Z1RGiokYs", None, "reviewed_xayah_source"
    if match := FRESH.fullmatch(filename):
        return "youtube:" + match.group(1), float(match.group(2)), "reviewed_video"
    if THIRD.fullmatch(filename):
        return "twitch:2891052706", None, "reviewed_extension"
    raise ValueError(f"Unknown crop provenance: {path}")


def _body_view(image: Image.Image) -> Image.Image:
    """Show the unit body with less HUD; keep aspect ratio, without sharpening."""
    width, height = image.size
    area = image.crop((round(width * .04), round(height * .19),
                       round(width * .96), round(height * .98)))
    area.thumbnail((224, 224), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (224, 224), (22, 22, 25))
    canvas.paste(area, ((224 - area.width) // 2, (224 - area.height) // 2))
    return canvas


def _visual_feature(image: Image.Image) -> np.ndarray:
    width, height = image.size
    body = image.crop((round(width * .04), round(height * .19),
                       round(width * .96), round(height * .98)))
    rgb = np.asarray(body.convert("RGB"))
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256])
    hist = cv2.normalize(hist, hist).flatten()
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.resize(cv2.Canny(gray, 60, 140), (12, 12),
                       interpolation=cv2.INTER_AREA).flatten() / 255.0
    return np.concatenate([hist, edges.astype(np.float32) * .08])


def _near_exact_components(paths: list[str], audit: dict) -> tuple[dict[str, str], set[str]]:
    parent = {path: path for path in paths}

    def find(path: str) -> str:
        if parent[path] != path:
            parent[path] = find(parent[path])
        return parent[path]

    for section, keys in (("extension_matches", ("extension", "legacy")),
                          ("legacy_pairs", ("left", "right"))):
        for row in audit[section]:
            left, right = row[keys[0]], row[keys[1]]
            if left in parent and right in parent:
                parent[find(left)] = find(right)
    groups = defaultdict(list)
    for path in paths:
        groups[find(path)].append(path)
    conflicts = {path for group in groups.values()
                 if len({Path(path).parent.name for path in group}) > 1
                 for path in group}
    return {path: find(path) for path in paths}, conflicts


def prepare(corpus: Path, annotations: Path, audit_file: Path,
            output: Path, per_class: int = 5,
            supplements: list[Path] | None = None,
            exclusions_file: Path | None = None) -> dict:
    if output.exists():
        raise FileExistsError(f"Use a new output directory: {output}")
    manifest = json.loads((corpus / "manifest.json").read_text())
    frames = json.loads(annotations.read_text())["frames"]
    audit = json.loads(audit_file.read_text())
    manual_exclusions = {}
    if exclusions_file:
        for row in json.loads(exclusions_file.read_text())["excluded"]:
            if row["path"] in manual_exclusions:
                raise ValueError(f"Duplicate manual exclusion: {row['path']}")
            manual_exclusions[row["path"]] = row
    train = [row for row in manifest["records"] if row["path"].startswith("train/")]
    paths = [row["path"] for row in train]
    components, conflicts = _near_exact_components(paths, audit)
    leaked = {row["right"] for row in audit["cross_split_pairs"]}
    excluded = Counter()
    candidates = defaultdict(list)
    seen_components = set()
    for row in sorted(train, key=lambda row: (row["path"], row["sha256"])):
        path = row["path"]
        if path in manual_exclusions:
            if row["sha256"] != manual_exclusions[path]["sha256"]:
                raise ValueError(f"Manual exclusion points to changed crop: {path}")
            excluded["visually_unusable_crop"] += 1
            continue
        if path in conflicts:
            excluded["contradictory_label"] += 1
            continue
        if path in leaked:
            excluded["near_exact_holdout_copy"] += 1
            continue
        component = components[path]
        if component in seen_components:
            excluded["near_exact_training_copy"] += 1
            continue
        seen_components.add(component)
        image_path = corpus / path
        if hashlib.sha256(image_path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError(f"Corpus image changed: {path}")
        source, timestamp, origin = _provenance(path, frames)
        with Image.open(image_path) as image:
            feature = _visual_feature(image)
            focus = _body_view(image)
        candidates[row["class"]].append({
            "path": path, "sha256": row["sha256"], "source": source,
            "source_ms": timestamp, "origin": origin,
            "label_status": row["label_status"], "feature": feature,
            "focus": focus,
        })

    for supplement in supplements or []:
        document = json.loads(supplement.read_text())
        if document.get("review_method") != "assistant_visual_review" or \
                document.get("model_predictions_used_as_labels") is not False or \
                document.get("label") not in manifest["classes"]:
            raise ValueError(f"Supplement lacks reviewed identity: {supplement}")
        source = _source_id(document["source_id"])
        for crop in document["added_crops"]:
            image_path = Path(crop["crop_path"])
            if hashlib.sha256(image_path.read_bytes()).hexdigest() != crop["sha256"]:
                raise ValueError(f"Supplement image changed: {image_path}")
            with Image.open(image_path) as image:
                feature = _visual_feature(image)
                focus = _body_view(image)
            candidates[document["label"]].append({
                "path": str(image_path), "sha256": crop["sha256"],
                "source": source, "source_ms": float(crop["second"]) * 1000,
                "origin": "supplement_reviewed_video",
                "label_status": "assistant_visual_review", "feature": feature,
                "focus": focus,
            })

    output.mkdir(parents=True)
    selected = []
    coverage = {}
    for name in manifest["classes"]:
        pool = candidates[name]
        candidate_count = len(pool)
        chosen = []
        used_sources = set()
        while pool and len(chosen) < per_class:
            def rank(item: dict) -> tuple[float, float, str]:
                novelty = (min(float(np.linalg.norm(item["feature"] - previous["feature"]))
                               for previous in chosen) if chosen else 0.0)
                return (float(item["source"] not in used_sources), novelty, item["path"])

            best = max(pool, key=rank)
            pool.remove(best)
            chosen.append(best)
            used_sources.add(best["source"])
        coverage[name] = {"selected": len(chosen), "distinct_sources": len(used_sources),
                          "remaining_to_five": max(0, per_class - len(chosen)),
                          "audited_candidates": candidate_count}
        for item in chosen:
            code = hashlib.sha256(item["path"].encode()).hexdigest()[:16]
            focused = output / "focused" / f"{code}.png"
            focused.parent.mkdir(parents=True, exist_ok=True)
            item["focus"].save(focused)
            selected.append({"class": name} | {key: value for key, value in item.items()
                             if key not in {"feature", "focus"}} |
                            {"focused_path": str(focused.relative_to(output)),
                             "review_status": "needs_fresh_visual_confirmation"})

    # A compact gallery makes wrong labels and bad crops visible before training.
    font = ImageFont.load_default()
    for page_index in range((len(selected) + 39) // 40):
        page = selected[page_index * 40:(page_index + 1) * 40]
        sheet = Image.new("RGB", (5 * 455, 8 * 280), (20, 21, 25))
        draw = ImageDraw.Draw(sheet)
        for cell_index, item in enumerate(page):
            x = (cell_index % 5) * 455
            y = (cell_index // 5) * 280
            original_path = Path(item["path"])
            if not original_path.is_absolute():
                original_path = corpus / original_path
            with Image.open(original_path) as original:
                display = original.convert("RGB")
                display.thumbnail((210, 220))
            with Image.open(output / item["focused_path"]) as focused:
                sheet.paste(display, (x + (210 - display.width) // 2, y + 25))
                sheet.paste(focused.convert("RGB"), (x + 220, y + 25))
            label = item["class"]
            draw.text((x + 5, y + 4), f"{page_index*40+cell_index+1:03}  {label}",
                      fill="white", font=font)
            draw.text((x + 5, y + 252), item["source"][:60], fill=(190, 190, 190), font=font)
        sheet.save(output / f"review-{page_index+1:02d}.jpg", quality=88)

    report = {
        "schema_version": 1,
        "status": "review_queue_not_training_data",
        "model_predictions_used_as_labels": False,
        "per_class_target": per_class,
        "selection": "prefer distinct source, then diverse body appearance after near-exact deduplication",
        "focused_crop": "4%-96% width, 19%-98% height, letterboxed to 224 square for review only",
        "excluded": dict(excluded),
        "selected_count": len(selected),
        "classes_ready_for_review": sum(row["selected"] >= per_class for row in coverage.values()),
        "classes_with_five_sources": sum(row["distinct_sources"] >= per_class for row in coverage.values()),
        "classes_missing_five": [name for name, row in coverage.items() if row["remaining_to_five"]],
        "coverage": coverage,
        "selected": selected,
    }
    (output / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--per-class", type=int, default=5)
    parser.add_argument("--supplement", action="append", type=Path, default=[])
    parser.add_argument("--exclusions", type=Path)
    args = parser.parse_args()
    if args.per_class < 1:
        raise ValueError("--per-class must be positive")
    result = prepare(args.corpus, args.annotations, args.audit,
                     args.output, args.per_class, args.supplement, args.exclusions)
    print(json.dumps({key: result[key] for key in
                      ("selected_count", "classes_ready_for_review", "classes_with_five_sources",
                       "classes_missing_five", "excluded")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
