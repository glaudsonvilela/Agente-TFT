"""Add verified third-source champion crops without changing held-out splits."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from PIL import Image


def _pixels(path: Path):
    with Image.open(path) as image:
        return hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()


def build(base: Path, labels: Path, catalog: Path, output: Path,
          exclusions: Path | None = None):
    classes = sorted(path.name for path in (base / "train").iterdir() if path.is_dir())
    if len(classes) != 65:
        raise ValueError("Expected 65 existing classifier classes")
    units = json.loads(catalog.read_text())["champions"]
    by_id = {unit["api_name"]: unit["name"] for unit in units}
    rows = json.loads(labels.read_text())
    rejected = {row["index"]: row for row in json.loads(exclusions.read_text())} if exclusions else {}
    for index, row in rejected.items():
        if not 0 <= index < len(rows) or rows[index]["pixel_sha256"] != row["pixel_sha256"]:
            raise ValueError(f"Stale exclusion at row {index}")
    seen = set()
    for split in ("train", "val", "test"):
        for name in classes:
            target = output / split / name
            target.mkdir(parents=True, exist_ok=True)
            for path in (base / split / name).glob("*"):
                if not path.is_file():
                    continue
                sha = _pixels(path)
                if sha in seen:
                    raise ValueError(f"Repeated crop in existing splits: {path}")
                seen.add(sha)
                link = target / path.name
                if not link.exists():
                    link.symlink_to(path.resolve())
    additions = Counter()
    for index, row in enumerate(rows):
        if index in rejected:
            continue
        if row.get("unit_id") == "__unknown__":
            continue
        if row.get("review") != "assistant_visual_review" or \
                row.get("model_predictions_used_as_labels") is not False:
            raise ValueError(f"Unreviewed identity at row {index}")
        name = by_id.get(row["unit_id"])
        if name not in classes:
            raise ValueError(f"Unknown classifier identity: {row['unit_id']}")
        path = Path(row["path"])
        sha = _pixels(path)
        if sha != row["pixel_sha256"] or sha in seen:
            raise ValueError(f"Changed or duplicate reviewed crop: {path}")
        seen.add(sha)
        (output / "train" / name / f"third-reviewed-{index:04d}{path.suffix}").symlink_to(
            path.resolve())
        additions[name] += 1
    report = {"review_method": "assistant_visual_review",
              "model_predictions_used_as_labels": False,
              "independent_human_ground_truth": False,
              "source_group": "twitch-v2891052706-entire-source",
              "source_group_split": "train",
              "added": dict(sorted(additions.items())),
              "total_added": sum(additions.values()),
              "excluded_after_visual_audit": [rejected[key] for key in sorted(rejected)],
              "heldout_files_unchanged": True,
              "caveat": "Additional crops share a source match with existing train samples; pose independence is not established."}
    (output / "extension-audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--exclusions", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.base, args.labels, args.catalog, args.output,
                           args.exclusions),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
