#!/usr/bin/env python3
"""Build a bounded, review-only queue from new Sherlock SSD images.

The queue is deliberately NOT a training manifest. Model candidates may be used
only to prioritize what a human/assistant should inspect. They are never copied
into identity labels. Evaluation/development sources are blocked from admission.

Inputs:
- inventory_new_ssd_training_images.py output (pixel novelty)
- current supervised manifest (train/validation/test source policy)
- private VOD collection report.json + observations.jsonl files

Outputs:
- queue.json: prioritized crop review candidates
- contact-sheet-input.json: native 128x144 crops, numbered in queue order
- context.json: full-frame/Lux context candidates
- summary.json: counts only

No weights are fitted and no existing dataset is modified.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

DEFAULT_ROOT = Path("/mnt/sherlock-ssd/AgenteTFT")
DEFAULT_INVENTORY = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/new-image-inventory-20261005/inventory.json"
)
DEFAULT_OUTPUT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/new-image-review-queue-20261005"
)
DEFAULT_ANNOTATIONS = Path(
    "configs/training/unit-gallery-transfer-reviewed-expanded-20261005.json"
)
MINJO = Path("configs/training/unit-gallery-tristana-evaluation-20261005.json")
KH = Path("configs/training/unit-gallery-lux-kh-evaluation-20261005.json")

MISSING_LUX = [
    "DA_18_Lux_Coven",
    "DA_18_Lux_Fae",
    "DA_18_Lux_Inferno",
    "DA_18_Lux_Moonbeam",
    "DA_18_Lux_Primal",
    "DA_18_Lux_Sunbeam",
    "DA_Lux18_Base",
    "DA_Lux18_Blackthorn",
    "DA_Lux18_Blossom",
]
SINGLE_SOURCE = [
    "DA_18_ElderDragon",
    "DA_18_Kayle",
    "DA_18_KhaZix",
    "DA_18_Lux_Elderwood",
    "DA_18_MasterYi_AD",
    "DA_18_Morgana",
    "DA_18_Xayah",
    "DA_CrimsonRaptor18",
    "DA_Karma18",
    "DA_Murkwolf18",
]
TARGET_IDS = set(SINGLE_SOURCE)

# Evaluation/development paths are blocked even if private metadata is incomplete.
BLOCKED_PATH_MARKERS = (
    "long-vod-20261005",              # six-hour development evaluation
    "tristana-resumed-10s",           # Minjo/T4lJ2S2iH_o development evaluation
    "tristana-pool-10s",
    "lux-kh-evaluation",
    "lux-kh-tooltip",
)

# Non-source/derived directories are never considered collections.
IGNORE_PATH_MARKERS = (
    "/build/",
    "/build-cache/",
    "/venv/",
    "/site-packages/",
    "/model-reference/",
    "/champion-art/",
    "/gallery-expansion",
    "/tooltip-review/",
    "/shop-strips/",
    "/contact-sheet",
    "/optimizer-study-resume-",
    "/new-image-inventory-",
    "/new-image-review-queue-",
)


def die(message: str) -> "NoReturn":
    raise SystemExit(f"REVIEW_QUEUE_ERROR: {message}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"cannot read JSON {path}: {exc}")


def source_token(frame: dict[str, Any]) -> str | None:
    for key in ("source_video_id", "source_id"):
        value = frame.get(key)
        if isinstance(value, str) and value:
            return value
    url = frame.get("source_url")
    if isinstance(url, str) and url:
        return url
    return None


def manifest_source_policy(path: Path) -> tuple[set[str], set[str]]:
    doc = load_json(path)
    train: set[str] = set()
    blocked: set[str] = set()
    for frame in doc.get("frames", []):
        if not isinstance(frame, dict):
            continue
        src = source_token(frame)
        if not src:
            continue
        if frame.get("identity_split") == "train":
            train.add(src)
        else:
            blocked.add(src)
    return train, blocked


def evaluation_sources(path: Path) -> set[str]:
    doc = load_json(path)
    result = set()
    for frame in doc.get("frames", []):
        if isinstance(frame, dict):
            src = source_token(frame)
            if src:
                result.add(src)
    for src in doc.get("sources", []):
        if isinstance(src, dict):
            value = src.get("source_id") or src.get("source_url")
            if isinstance(value, str) and value:
                result.add(value)
    return result


def normalize_path(path: Path) -> str:
    return "/" + "/".join(path.parts) + "/"


def contains_marker(path: Path, markers: Iterable[str]) -> bool:
    value = normalize_path(path)
    return any(marker in value for marker in markers)


def new_pixel_hashes(inventory_path: Path) -> set[str]:
    inv = load_json(inventory_path)
    rows = inv.get("images")
    if not isinstance(rows, list):
        die("inventory.json missing images list")
    return {
        str(row["pixel_sha256"])
        for row in rows
        if isinstance(row, dict)
        and row.get("genuinely_new") is True
        and isinstance(row.get("pixel_sha256"), str)
    }


def find_collections(root: Path) -> list[Path]:
    found = []
    for base, dirs, files in os.walk(root):
        p = Path(base)
        dirs[:] = [
            d
            for d in sorted(dirs)
            if not contains_marker(p / d, IGNORE_PATH_MARKERS)
        ]
        if contains_marker(p, IGNORE_PATH_MARKERS):
            dirs[:] = []
            continue
        if "report.json" in files and "observations.jsonl" in files:
            found.append(p)
    return sorted(set(found))


def load_observations(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                # Interrupted collection may have one truncated tail. Ignore only
                # the final invalid record; never infer labels from it.
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def candidate_unit(unit: dict[str, Any]) -> tuple[str | None, float | None, str]:
    accepted = unit.get("candidate_id")
    if isinstance(accepted, str) and accepted:
        score = None
        candidates = unit.get("candidates")
        if isinstance(candidates, list) and candidates:
            top = candidates[0]
            if isinstance(top, dict) and top.get("unit_id") == accepted:
                raw = top.get("similarity")
                if isinstance(raw, (int, float)) and math.isfinite(raw):
                    score = float(raw)
        return accepted, score, "accepted_suggestion"

    candidates = unit.get("candidates")
    if isinstance(candidates, list) and candidates:
        top = candidates[0]
        if isinstance(top, dict):
            ident = top.get("unit_id")
            raw = top.get("similarity")
            score = (
                float(raw)
                if isinstance(raw, (int, float)) and math.isfinite(raw)
                else None
            )
            if isinstance(ident, str) and ident:
                return ident, score, "top1_suggestion"
    return None, None, "no_suggestion"


def evenly_sample(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(rows) <= limit:
        return rows
    if limit <= 1:
        return [rows[0]]
    positions = {
        round(i * (len(rows) - 1) / (limit - 1))
        for i in range(limit)
    }
    return [rows[i] for i in sorted(positions)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-per-target-source", type=int, default=6)
    parser.add_argument("--max-lux-context-per-source", type=int, default=24)
    args = parser.parse_args()

    repo = args.repo.expanduser().resolve()
    root = args.root.expanduser().resolve()
    inventory = args.inventory.expanduser().resolve()
    output = args.output.expanduser()

    if output.exists():
        die(f"output already exists: {output}")
    if not root.is_dir():
        die(f"SSD root not found: {root}")
    if str(root).startswith("/mnt/sherlock-ssd") and not Path("/mnt/sherlock-ssd").is_mount():
        die("/mnt/sherlock-ssd is not mounted")
    if args.max_per_target_source < 1 or args.max_lux_context_per_source < 1:
        die("review limits must be positive")

    annotations = (repo / DEFAULT_ANNOTATIONS).resolve()
    train_sources, blocked_sources = manifest_source_policy(annotations)
    blocked_sources |= evaluation_sources((repo / MINJO).resolve())
    blocked_sources |= evaluation_sources((repo / KH).resolve())
    novel_pixels = new_pixel_hashes(inventory)

    collections = find_collections(root)
    collection_rows = []
    raw_target_candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    lux_context_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    blocked = []
    allowed = []

    for collection in collections:
        report = load_json(collection / "report.json")
        partition = report.get("partition")
        source_id = report.get("source_id")
        source_url = report.get("source_url")
        mode = report.get("collection_mode", "embeddings")

        if partition != "training_pool_unlabeled":
            blocked.append(
                {
                    "directory": str(collection),
                    "source_id": source_id,
                    "reason": f"partition={partition!r}",
                }
            )
            continue
        if not isinstance(source_id, str) or not source_id:
            blocked.append(
                {
                    "directory": str(collection),
                    "source_id": source_id,
                    "reason": "missing_source_id",
                }
            )
            continue
        if source_id in blocked_sources or contains_marker(collection, BLOCKED_PATH_MARKERS):
            blocked.append(
                {
                    "directory": str(collection),
                    "source_id": source_id,
                    "reason": "development_or_evaluation_source_blocked",
                }
            )
            continue

        source_is_new_to_train = source_id not in train_sources
        allowed.append(
            {
                "directory": str(collection),
                "source_id": source_id,
                "source_url": source_url,
                "collection_mode": mode,
                "new_source_relative_to_current_train": source_is_new_to_train,
            }
        )

        observations = load_observations(collection / "observations.jsonl")
        new_obs = [
            obs
            for obs in observations
            if isinstance(obs.get("frame_pixel_sha256"), str)
            and obs["frame_pixel_sha256"] in novel_pixels
            and obs.get("exact_duplicate_frame") is not True
        ]

        # Candidate-assisted prioritization for the ten source-diversity IDs.
        # Suggestions are NEVER labels and remain explicitly unverified.
        for obs in new_obs:
            seconds = obs.get("source_seconds_nominal")
            frame_rel = obs.get("review_frame")
            full_frame = (
                str((collection / frame_rel).resolve())
                if isinstance(frame_rel, str) and (collection / frame_rel).is_file()
                else None
            )
            for unit in obs.get("units", []):
                if not isinstance(unit, dict):
                    continue
                ident, score, suggestion_kind = candidate_unit(unit)
                if ident not in TARGET_IDS:
                    continue
                crop_rel = unit.get("crop")
                if not isinstance(crop_rel, str):
                    continue
                crop_path = (collection / crop_rel).resolve()
                if not crop_path.is_file():
                    continue
                row = {
                    "target_id_suggestion": ident,
                    "suggestion_kind": suggestion_kind,
                    "suggestion_score": score,
                    "identity_label": None,
                    "identity_reviewed": False,
                    "model_prediction_used_as_label": False,
                    "training_eligible": False,
                    "source_id": source_id,
                    "source_url": source_url,
                    "new_source_relative_to_current_train": source_is_new_to_train,
                    "source_seconds_nominal": seconds,
                    "collection": str(collection),
                    "crop_path": str(crop_path),
                    "crop_pixel_sha256": unit.get("pixel_sha256"),
                    "full_frame_path": full_frame,
                    "box": unit.get("box"),
                }
                raw_target_candidates[(ident, source_id)].append(row)

        # Missing Lux variants cannot be found by a classifier that has no class
        # for them. For Lux-named training acquisitions, queue full review frames
        # as context only; exact form must be established manually.
        collection_name = collection.name.casefold()
        if "lux" in collection_name and "kh" not in collection_name:
            context_rows = []
            for obs in new_obs:
                frame_rel = obs.get("review_frame")
                if not isinstance(frame_rel, str):
                    continue
                frame_path = (collection / frame_rel).resolve()
                if not frame_path.is_file():
                    continue
                context_rows.append(
                    {
                        "purpose": "missing_lux_form_context",
                        "possible_targets": MISSING_LUX,
                        "identity_label": None,
                        "identity_reviewed": False,
                        "model_prediction_used_as_label": False,
                        "training_eligible": False,
                        "source_id": source_id,
                        "source_url": source_url,
                        "new_source_relative_to_current_train": source_is_new_to_train,
                        "source_seconds_nominal": obs.get("source_seconds_nominal"),
                        "collection": str(collection),
                        "full_frame_path": str(frame_path),
                        "frame_pixel_sha256": obs.get("frame_pixel_sha256"),
                    }
                )
            lux_context_by_source[source_id].extend(context_rows)

        collection_rows.append(
            {
                "directory": str(collection),
                "source_id": source_id,
                "collection_mode": mode,
                "new_source_relative_to_current_train": source_is_new_to_train,
                "new_observations": len(new_obs),
            }
        )

    # Bound each target/source so one long VOD cannot dominate review.
    queue = []
    for (target, source_id), rows in sorted(raw_target_candidates.items()):
        def key(row: dict[str, Any]) -> tuple[int, int, float, float]:
            new_source = 1 if row["new_source_relative_to_current_train"] else 0
            accepted = 1 if row["suggestion_kind"] == "accepted_suggestion" else 0
            score = row["suggestion_score"]
            numeric_score = float(score) if isinstance(score, (int, float)) else -1.0
            seconds = row["source_seconds_nominal"]
            numeric_seconds = float(seconds) if isinstance(seconds, (int, float)) else 0.0
            return (-new_source, -accepted, -numeric_score, numeric_seconds)

        selected = sorted(rows, key=key)[: args.max_per_target_source]
        queue.extend(selected)

    queue.sort(
        key=lambda row: (
            0 if row["new_source_relative_to_current_train"] else 1,
            row["target_id_suggestion"],
            row["source_id"],
            float(row["source_seconds_nominal"] or 0),
        )
    )
    for index, row in enumerate(queue, 1):
        row["review_number"] = index

    lux_context = []
    for source_id, rows in sorted(lux_context_by_source.items()):
        selected = evenly_sample(
            sorted(
                rows,
                key=lambda r: float(r["source_seconds_nominal"] or 0),
            ),
            args.max_lux_context_per_source,
        )
        lux_context.extend(selected)
    for index, row in enumerate(lux_context, 1):
        row["review_number"] = index

    output.mkdir(parents=True)
    queue_doc = {
        "schema_version": 1,
        "kind": "candidate_assisted_review_queue_not_labels",
        "current_training_manifest": str(DEFAULT_ANNOTATIONS),
        "target_single_source_ids": SINGLE_SOURCE,
        "missing_lux_ids": MISSING_LUX,
        "queue": queue,
        "policy": {
            "model_suggestions_are_labels": False,
            "automatic_admission_to_training": False,
            "evaluation_sources_blocked": True,
            "minjo_kh_allowed_in_training": False,
            "human_or_assistant_visual_review_required": True,
            "runtime_approved": False,
        },
    }
    (output / "queue.json").write_text(
        json.dumps(queue_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "context.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "lux_context_review_queue",
                "rows": lux_context,
                "policy": queue_doc["policy"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Existing Rust contact-sheet tool understands this list. No labels included.
    contact_rows = [
        {
            "path": row["crop_path"],
            "review_number": row["review_number"],
            "target_id_suggestion": row["target_id_suggestion"],
            "source_id": row["source_id"],
            "model_prediction_used_as_label": False,
            "training_eligible": False,
            "crop_transform": "upper_88x80_v1",
        }
        for row in queue
    ]
    (output / "contact-sheet-input.json").write_text(
        json.dumps(contact_rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    target_counts = Counter(row["target_id_suggestion"] for row in queue)
    new_source_counts = Counter(
        row["target_id_suggestion"]
        for row in queue
        if row["new_source_relative_to_current_train"]
    )
    summary = {
        "collections_found": len(collections),
        "allowed_training_collections": len(allowed),
        "blocked_collections": len(blocked),
        "collections_with_new_observations": sum(
            row["new_observations"] > 0 for row in collection_rows
        ),
        "review_crop_candidates": len(queue),
        "lux_context_frames": len(lux_context),
        "targets_represented_in_queue": dict(sorted(target_counts.items())),
        "targets_with_new_source_candidates": dict(sorted(new_source_counts.items())),
        "missing_target_suggestions": sorted(TARGET_IDS - set(target_counts)),
        "missing_lux_forms_still_require_manual_context_review": MISSING_LUX,
        "training_performed": False,
        "runtime_approved": False,
        "next": (
            "Generate the contact sheet, inspect numbered crops/context, record only "
            "visually confirmed identities with source provenance, then build a new "
            "training-only manifest. Suggestions must not become labels automatically."
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "blocked-collections.json").write_text(
        json.dumps(blocked, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "allowed-collections.json").write_text(
        json.dumps(allowed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nREVIEW_QUEUE_OK=true")
    print(f"OUTPUT={output}")
    print(f"REVIEW_CROP_CANDIDATES={len(queue)}")
    print(f"LUX_CONTEXT_FRAMES={len(lux_context)}")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
