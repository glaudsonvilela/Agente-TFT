"""Prepare a reproducible L3 region experiment from three sealed HM4 sessions.

The source pixels have no semantic champion/item labels. The existing U1
trainer uses only the known geometry of synthetic pasted bench/shop crops.
Keep one entire capture session in each split; do not promote this model.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def select(rows: list[dict], count: int) -> list[dict]:
    if len(rows) < count:
        raise ValueError("Not enough verified images for the requested split")
    chosen = []
    used = set()
    for i in range(count):
        target = round((i + .5) * len(rows) / count - .5)
        for distance in range(len(rows)):
            for index in (target - distance, target + distance):
                if 0 <= index < len(rows) and rows[index]["sha256"] not in used:
                    chosen.append(rows[index])
                    used.add(rows[index]["sha256"])
                    break
            else:
                continue
            break
        else:
            raise ValueError("Split contains duplicate image bytes")
    return sorted(chosen, key=lambda row: row["timestamp_ms"])


def prepare(sessions_root: Path, output: Path, project: Path, session_names: list[str]) -> dict:
    if len(session_names) != 3 or len(set(session_names)) != 3:
        raise ValueError("Provide three distinct sessions: train, validation, test")
    if output.exists():
        raise ValueError("Output already exists")
    source_spec = json.loads((project / "configs/vision/uimap-lite-u1.json").read_text())
    groups = []
    all_rows = []
    for name in session_names:
        session = sessions_root / name
        if not session.is_dir() or session.resolve().parent != sessions_root.resolve():
            raise ValueError("Session path is missing or outside source root")
        sealed = json.loads((session / "training-manifest.json").read_text())
        if sealed.get("training_executed") or sealed.get("ground_truth_available"):
            raise ValueError("Unexpected source provenance")
        rows = []
        start = datetime.strptime(name.removeprefix("hm4-")[:15], "%Y%m%d-%H%M%S")
        start_ms = (start.hour * 3600 + start.minute * 60 + start.second) * 1000
        for sample in sealed["samples"]:
            relative = Path(sample["image"])
            if relative.parts[0] != "samples" or len(relative.parts) != 2:
                raise ValueError("Invalid sample path")
            path = session / relative
            if digest(path) != sample["image_sha256"]:
                raise ValueError(f"Sample hash mismatch: {path}")
            row = {"image": f"{name}/{relative.as_posix()}",
                   "timestamp_ms": start_ms + round(sample["source_ms"]),
                   "sha256": sample["image_sha256"],
                   "source_session": name,
                   "source_ms": sample["source_ms"]}
            rows.append(row)
        groups.append(sorted(rows, key=lambda row: row["timestamp_ms"]))
        all_rows.extend(rows)
    all_rows.sort(key=lambda row: row["timestamp_ms"])
    if len(all_rows) > 128 or len({r["timestamp_ms"] for r in all_rows}) != len(all_rows):
        raise ValueError("Frame budget or timestamp collision")
    seeds = []
    for split, rows, count in zip(("train", "validation", "test"), groups, (24, 4, 4)):
        seeds.extend({"image": row["image"], "sha256": row["sha256"], "split": split}
                     for row in select(rows, count))
    if len({s["sha256"] for s in seeds}) != len(seeds):
        raise ValueError("Duplicate image bytes across splits")
    spec = {**source_spec, "seeds": seeds,
            "supervision": "known_synthetic_paste_geometry_from_three_HM45_sessions",
            "warning": "Same replay may appear in multiple capture sessions; no independent match or champion/item labels. Experimental shadow model only.",
            "source_sessions": session_names}
    manifest = {"frames": all_rows, "split_unit": "capture_session",
                "ground_truth_available": False, "independent_match_validation": False}
    output.mkdir(parents=True)
    (output / "spec.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    report = {"samples": len(all_rows), "seeds": len(seeds),
              "split_counts": dict(zip(("train", "validation", "test"), map(len, groups))),
              "source_sessions": session_names,
              "training_label_kind": "synthetic_panel_geometry_only",
              "champion_item_labels": 0, "independent_match_validation": False}
    (output / "source-report.json").write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("sessions", nargs=3, help="train validation test")
    args = parser.parse_args()
    print(json.dumps(prepare(args.sessions_root.resolve(), args.output.resolve(),
                             args.project.resolve(), args.sessions), ensure_ascii=False))


if __name__ == "__main__":
    main()
