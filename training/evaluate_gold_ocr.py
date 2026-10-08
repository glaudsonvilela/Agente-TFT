"""Check offline gold OCR against manually reviewed full-match frames.

Run with --frames-dir pointing to the 10-fps extraction on the SSD. This is a
regression check for the training index, not an estimate of live-match accuracy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from training.index_full_match_states import REGIONS, read_text, reconcile_gold_reads


DEFAULT_LABELS = (
    Path(__file__).resolve().parents[1]
    / "docs/evidence/full-match-gold-ocr-review-20261008.json"
)


def evaluate(frames_dir: Path, labels_path: Path) -> dict:
    labels = json.loads(labels_path.read_text())
    manifest = json.loads((frames_dir.parent / "manifest.json").read_text())
    if (manifest["source_sha256"] != labels["source_sha256"]
            or manifest["fps"] != labels["frames_fps"]):
        raise ValueError("labels do not match the source video and sampling rate")
    correct = unknown = wrong = 0
    errors = []
    for name, expected in labels["gold_by_frame"].items():
        with Image.open(frames_dir / name) as image:
            if image.size != tuple(labels["dimensions"]):
                raise ValueError(f"unexpected frame size: {name}")
            reads = {
                "gray_psm13": read_text(image, REGIONS["gold"], "0123456789", psm=13, contrast=1),
                "gray_psm7": read_text(image, REGIONS["gold"], "0123456789", contrast=1),
                "contrast_psm7": read_text(image, REGIONS["gold"], "0123456789"),
            }
        observed, status = reconcile_gold_reads(reads)
        if observed == expected:
            correct += 1
        elif observed is None:
            unknown += 1
            errors.append({"frame": name, "expected": expected, "status": status, "views": reads})
        else:
            wrong += 1
            errors.append({"frame": name, "expected": expected, "observed": observed, "views": reads})
    return {"checked": correct + unknown + wrong, "correct": correct,
            "unknown": unknown, "wrong": wrong, "exceptions": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames-dir", type=Path, required=True)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    args = parser.parse_args()
    result = evaluate(args.frames_dir, args.labels)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["wrong"] or result["unknown"] > 1:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
