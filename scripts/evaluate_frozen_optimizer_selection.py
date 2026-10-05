#!/usr/bin/env python3
"""Evaluate the frozen optimizer-study selection on Minjo and KH.

No fitting, no model selection, no hyperparameter update. This script reads the
selection and metadata produced by resume_recognizer_optimizer_study.py, seals
the selected model by SHA-256, verifies source isolation in the Rust evaluator,
and writes fresh reports beside the optimizer study.

If the retained arm is optimizer-default-parity, the new predictions must match
the historical transfer-vertical Minjo/KH reports exactly. That is a regression
check, not a new selection criterion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

TRAINING_ANNOTATIONS = Path(
    "configs/training/unit-gallery-transfer-reviewed-expanded-20261005.json"
)
MINJO_ANNOTATIONS = Path("configs/training/unit-gallery-tristana-evaluation-20261005.json")
KH_ANNOTATIONS = Path("configs/training/unit-gallery-lux-kh-evaluation-20261005.json")
REFERENCE = Path(
    "knowledge/riot-ddragon/16.19.1/pt_BR/TFTSet18/"
    "5dafba7d15d09fb77b4ba83af78f3a46f0986121f68c46e3be6bf41da85c823f"
)
HISTORICAL_MINJO = Path(
    "docs/evidence/recognizer-training-20261005/transfer-vertical-minjo-evaluation.json"
)
HISTORICAL_KH = Path(
    "docs/evidence/recognizer-training-20261005/transfer-vertical-kh-evaluation.json"
)
DEFAULT_PRIVATE_ROOT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/missing-classes-training-20261005"
)
DEFAULT_SSD_ROOT = Path("/mnt/sherlock-ssd/AgenteTFT")


def die(message: str) -> "NoReturn":
    raise SystemExit(f"OPTIMIZER_HOLDOUT_ERROR: {message}")


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        die(f"cannot read JSON {path}: {exc}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=True)
    except FileNotFoundError:
        die(f"required path does not exist: {path}")


def annotation_images(doc: dict[str, Any]) -> list[str]:
    frames = doc.get("frames")
    if not isinstance(frames, list) or not frames:
        die("evaluation manifest has no frames")
    result: list[str] = []
    for frame in frames:
        value = frame.get("image")
        if not isinstance(value, str) or not value:
            die("evaluation frame without image path")
        if value not in result:
            result.append(value)
    return result


def root_contains_all(root: Path, relatives: list[str]) -> bool:
    return root.is_dir() and all((root / item).is_file() for item in relatives)


def find_files_named(roots: Iterable[Path], name: str) -> Iterable[Path]:
    seen: set[Path] = set()
    for root in roots:
        root = root.expanduser()
        if not root.exists():
            continue
        try:
            for path in root.rglob(name):
                if path.is_file():
                    resolved = path.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        yield resolved
        except PermissionError:
            continue


def locate_images_root(
    manifest: Path,
    explicit: Path | None,
    repo: Path,
    private_root: Path,
) -> Path:
    doc = load_json(manifest)
    relatives = annotation_images(doc)
    for root in [explicit, private_root, private_root.parent, DEFAULT_SSD_ROOT, repo]:
        if root is not None and root_contains_all(root.expanduser(), relatives):
            return root.expanduser().resolve()

    first = Path(relatives[0])
    for hit in find_files_named([private_root, DEFAULT_SSD_ROOT], first.name):
        if tuple(hit.parts[-len(first.parts) :]) != tuple(first.parts):
            continue
        root = hit
        for _ in first.parts:
            root = root.parent
        if root_contains_all(root, relatives):
            return root.resolve()

    die(
        f"could not locate image root for {manifest.name}; "
        "pass the explicit --images-minjo/--images-kh path"
    )


def run_stream(command: list[str], cwd: Path, log: Path) -> None:
    print("+", " ".join(command), flush=True)
    with log.open("w", encoding="utf-8") as handle:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            handle.write(line)
        code = proc.wait()
    if code != 0:
        die(f"evaluation command failed ({code}); see {log}")


def comparable_predictions(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = report.get("evaluation", {}).get("predictions")
    if not isinstance(rows, list):
        die("evaluation report missing predictions")
    return rows


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    e = report.get("evaluation")
    if not isinstance(e, dict):
        die("evaluation report missing metrics")
    return {
        "named": int(e["named"]),
        "correct": int(e["named_top1_correct"]),
        "named_macro_recall": float(e["named_macro_recall"]),
        "cross_entropy": float(e["cross_entropy"]),
        "new_source_relative_to_training_manifest": bool(
            report["new_source_relative_to_training_manifest"]
        ),
        "training_performed": bool(report["training_performed"]),
        "batch_matches_training": bool(report["batch_matches_training"]),
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Evaluate frozen optimizer-study selection on Minjo/KH."
    )
    p.add_argument("--selection", type=Path, required=True)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--images-minjo", type=Path)
    p.add_argument("--images-kh", type=Path)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    repo = canonical(args.repo)
    selection_path = canonical(args.selection)
    selection = load_json(selection_path)

    if selection.get("status") != "selection_frozen_before_minjo_kh_evaluation":
        die("selection is not frozen for Minjo/KH evaluation")
    if selection.get("minjo_kh_evaluated_in_this_run") is not False:
        die("selection metadata does not preserve the pre-evaluation gate")

    model = canonical(Path(str(selection.get("selected_model_path", ""))))
    expected_model_sha = str(selection.get("selected_model_sha256", ""))
    if not expected_model_sha or sha256_file(model) != expected_model_sha:
        die("selected model SHA-256 mismatch")

    study_root = selection_path.parent
    metadata_path = canonical(study_root / "run-metadata.json")
    metadata = load_json(metadata_path)
    if metadata.get("status") != "complete_selection_frozen":
        die("optimizer run metadata is not complete/frozen")

    encoder = canonical(Path(str(metadata.get("encoder", ""))))
    encoder_sha = str(metadata.get("encoder_sha256", ""))
    if not encoder_sha or sha256_file(encoder) != encoder_sha:
        die("encoder SHA-256 mismatch")
    onnxruntime = canonical(Path(str(metadata.get("onnxruntime", ""))))

    training_annotations = canonical(repo / TRAINING_ANNOTATIONS)
    reference = canonical(repo / REFERENCE)
    if not (reference / "reference.json").is_file() or not (
        reference / "champions.json"
    ).is_file():
        die("visual Data Dragon reference is incomplete")

    private_root = DEFAULT_PRIVATE_ROOT
    if not Path("/mnt/sherlock-ssd").is_mount():
        die("/mnt/sherlock-ssd is not mounted")

    evaluations = [
        (
            "minjo",
            canonical(repo / MINJO_ANNOTATIONS),
            args.images_minjo,
            canonical(repo / HISTORICAL_MINJO),
        ),
        (
            "kh",
            canonical(repo / KH_ANNOTATIONS),
            args.images_kh,
            canonical(repo / HISTORICAL_KH),
        ),
    ]

    out = study_root / "development-evaluation"
    if out.exists():
        die(f"development evaluation output already exists: {out}")
    out.mkdir()
    specs = out / "specs"
    logs = out / "logs"
    specs.mkdir()
    logs.mkdir()

    results: dict[str, Any] = {}
    selected_arm = str(selection.get("selected_arm", ""))

    for name, annotations, explicit_images, historical_path in evaluations:
        images = locate_images_root(annotations, explicit_images, repo, private_root)
        report_path = out / f"{name}.json"
        spec_path = specs / f"{name}.json"
        spec = {
            "model": str(model),
            "model_sha256": expected_model_sha,
            "training_annotations": str(training_annotations),
            "annotations": str(annotations),
            "images": str(images),
            "reference": str(reference),
            "encoder": str(encoder),
            "encoder_sha256": encoder_sha,
            "onnxruntime": str(onnxruntime),
            "output": str(report_path),
        }
        write_json(spec_path, spec)
        run_stream(
            [
                "cargo",
                "run",
                "--release",
                "--manifest-path",
                str(repo / "tools/unit-features-lab/Cargo.toml"),
                "--bin",
                "evaluate-classifier",
                "--",
                "--spec",
                str(spec_path),
            ],
            repo,
            logs / f"{name}.log",
        )
        report = load_json(report_path)
        summary = summarize(report)
        if summary["training_performed"]:
            die(f"{name}: evaluator unexpectedly reports training")
        if not summary["batch_matches_training"]:
            die(f"{name}: evaluation batch differs from training")
        if not summary["new_source_relative_to_training_manifest"]:
            die(f"{name}: source is not isolated from training")

        parity = None
        if selected_arm == "optimizer-default-parity":
            historical = load_json(historical_path)
            same = comparable_predictions(report) == comparable_predictions(historical)
            parity = {
                "historical_report": str(historical_path.relative_to(repo)),
                "prediction_parity": same,
                "historical_metrics": summarize(historical),
            }
            if not same:
                die(f"{name}: baseline selection failed historical prediction parity")

        results[name] = {
            "report": str(report_path),
            "annotations": str(annotations.relative_to(repo)),
            "images": str(images),
            "metrics": summary,
            "historical_parity": parity,
        }

    summary_path = out / "summary.json"
    summary = {
        "status": "complete_frozen_development_evaluation",
        "selection": str(selection_path),
        "selected_arm": selected_arm,
        "selected_model_sha256": expected_model_sha,
        "training_performed": False,
        "selection_changed_after_evaluation": False,
        "development_sources_used_for_hyperparameter_tuning": False,
        "results": results,
        "independent_final_holdout": False,
        "runtime_approved": False,
        "next": (
            "Do not retune from Minjo/KH. Increase source diversity, resolve remaining "
            "Lux forms and unknown rejection using training-only sources, then reserve "
            "a truly untouched source for final evaluation."
        ),
    }
    write_json(summary_path, summary)

    print("\nOPTIMIZER_HOLDOUT_OK=true")
    print(f"SUMMARY={summary_path}")
    for name in ("minjo", "kh"):
        m = results[name]["metrics"]
        print(f"{name.upper()}={m['correct']}/{m['named']}")
        print(f"{name.upper()}_MACRO_RECALL={m['named_macro_recall']:.12f}")
    print("TRAINING_PERFORMED=false")
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
