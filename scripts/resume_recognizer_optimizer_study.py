#!/usr/bin/env python3
"""Resume the bounded recognizer optimizer study from PR #47.

This helper intentionally does not promote a model and does not touch Minjo/KH
holdouts. It reproduces the selected transfer baseline first, requires exact
head/prediction parity, then compares two bounded L2 schedules using validation
only. The winner is frozen before any later external-source evaluation.

Private media/models stay on the Sherlock SSD. No existing output directory is
overwritten or deleted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

EXPECTED_PROTOCOL = Path("docs/evidence/recognizer-training-20261005/optimizer-study-protocol.json")
EXPECTED_CHECKPOINT = Path("docs/evidence/recognizer-training-20261005/checkpoint.json")
EXPECTED_BASELINE_REPORT = Path(
    "docs/evidence/recognizer-training-20261005/transfer-vertical-training-report.json"
)
DEFAULT_ANNOTATIONS = Path(
    "configs/training/unit-gallery-transfer-reviewed-expanded-20261005.json"
)
DEFAULT_REFERENCE = Path(
    "knowledge/releases/TFTSet18/18.3/"
    "0674657d3f7c165d37045fbd45d8f7c56b20aef064660e6906c3985f0c8a0299"
)
DEFAULT_PRIVATE_ROOT = Path(
    "/mnt/sherlock-ssd/AgenteTFT/diagnostics/missing-classes-training-20261005"
)
DEFAULT_SSD_ROOT = Path("/mnt/sherlock-ssd/AgenteTFT")


def die(message: str) -> "NoReturn":
    raise SystemExit(f"OPTIMIZER_STUDY_ERROR: {message}")


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


def run_stream(command: list[str], cwd: Path, log_path: Path) -> None:
    print("+", " ".join(command), flush=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
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
            log.write(line)
        code = proc.wait()
    if code != 0:
        die(f"command failed ({code}); see {log_path}")


def git_value(repo: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=repo,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def find_files_named(roots: Iterable[Path], pattern: str) -> Iterable[Path]:
    seen: set[Path] = set()
    for root in roots:
        root = root.expanduser()
        if not root.exists():
            continue
        try:
            for path in root.rglob(pattern):
                if path.is_file():
                    resolved = path.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        yield resolved
        except PermissionError:
            continue


def locate_encoder(explicit: Path | None, expected_sha: str, roots: list[Path]) -> Path:
    env = os.environ.get("AGENTE_TFT_ENCODER")
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    if env:
        candidates.append(Path(env))
    candidates.extend(find_files_named(roots, "*.onnx"))
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            if sha256_file(path) == expected_sha:
                return path.resolve()
        except OSError:
            continue
    die(
        "DINO encoder with the protocol SHA-256 was not found. "
        "Pass --encoder /path/model.onnx or set AGENTE_TFT_ENCODER."
    )


def locate_onnxruntime(explicit: Path | None, roots: list[Path]) -> Path:
    env = os.environ.get("ONNXRUNTIME_LIB")
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    if env:
        candidates.append(Path(env))

    search_roots = roots + [
        Path("/usr/lib"),
        Path("/usr/local/lib"),
        Path.home() / ".local/lib",
        Path.home() / ".cache",
    ]
    candidates.extend(find_files_named(search_roots, "libonnxruntime.so*"))
    for path in candidates:
        if path.exists() and path.is_file():
            return path.resolve()
    die(
        "libonnxruntime.so was not found. Pass --onnxruntime /path/libonnxruntime.so "
        "or set ONNXRUNTIME_LIB."
    )


def annotation_images(doc: dict[str, Any]) -> list[str]:
    frames = doc.get("frames")
    if not isinstance(frames, list) or not frames:
        die("annotation manifest has no frames")
    values: list[str] = []
    for frame in frames:
        value = frame.get("image")
        if not isinstance(value, str) or not value:
            die("annotation frame without image path")
        if value not in values:
            values.append(value)
    return values


def root_contains_all(root: Path, relatives: list[str]) -> bool:
    return root.is_dir() and all((root / item).is_file() for item in relatives)


def locate_images_root(
    explicit: Path | None,
    annotations_doc: dict[str, Any],
    repo: Path,
    private_root: Path,
) -> Path:
    relatives = annotation_images(annotations_doc)
    env = os.environ.get("AGENTE_TFT_IMAGES_ROOT")
    direct = [
        explicit,
        Path(env) if env else None,
        repo,
        private_root,
        private_root.parent,
        DEFAULT_SSD_ROOT,
        Path("/home/hobit/Agente-TFT"),
    ]
    for item in direct:
        if item is not None:
            root = item.expanduser()
            if root_contains_all(root, relatives):
                return root.resolve()

    # Previous training necessarily used one common root. Recover it from the
    # first relative path and then verify every manifest image before accepting.
    first = Path(relatives[0])
    search_roots = [private_root, private_root.parent, DEFAULT_SSD_ROOT, repo]
    for hit in find_files_named(search_roots, first.name):
        parts = hit.parts
        rel_parts = first.parts
        if len(parts) < len(rel_parts):
            continue
        if tuple(parts[-len(rel_parts) :]) != tuple(rel_parts):
            continue
        root = hit
        for _ in rel_parts:
            root = root.parent
        if root_contains_all(root, relatives):
            return root.resolve()

    die(
        "could not recover the common image root for the reviewed manifest. "
        "Pass --images /path/root or set AGENTE_TFT_IMAGES_ROOT. "
        "The root must contain every relative path stored in the manifest."
    )


def compare_predictions(
    baseline_report: dict[str, Any], rerun_report: dict[str, Any]
) -> tuple[bool, str]:
    try:
        base_variant = baseline_report["variants"]["dino"]
        new_variant = rerun_report["variants"]["dino"]
        if base_variant["selected_epoch"] != new_variant["selected_epoch"]:
            return False, "selected epoch changed"
        for split in ("train", "validation", "test"):
            base = base_variant["evaluation"][split]
            new = new_variant["evaluation"][split]
            fields = (
                "named",
                "named_top1_correct",
                "named_macro_recall",
                "cross_entropy",
                "predictions",
            )
            for field in fields:
                if base.get(field) != new.get(field):
                    return False, f"{split}.{field} changed"
    except (KeyError, TypeError) as exc:
        return False, f"missing report field: {exc}"
    return True, "exact training/validation/test prediction parity"


def validation_metrics(report: dict[str, Any]) -> dict[str, Any]:
    try:
        variant = report["variants"]["dino"]
        validation = variant["evaluation"]["validation"]
        return {
            "selected_epoch": int(variant["selected_epoch"]),
            "named": int(validation["named"]),
            "correct": int(validation["named_top1_correct"]),
            "named_macro_recall": float(validation["named_macro_recall"]),
            "cross_entropy": float(validation["cross_entropy"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        die(f"invalid training report: {exc}")


def metric_key(metrics: dict[str, Any]) -> tuple[float, float]:
    return (float(metrics["named_macro_recall"]), -float(metrics["cross_entropy"]))


def write_spec(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resume PR #47 bounded recognizer optimizer study."
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--private-root", type=Path, default=DEFAULT_PRIVATE_ROOT)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--images", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--encoder", type=Path)
    parser.add_argument("--onnxruntime", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--skip-tests", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo = canonical(args.repo)
    protocol_path = canonical(repo / EXPECTED_PROTOCOL)
    checkpoint_path = canonical(repo / EXPECTED_CHECKPOINT)
    baseline_report_path = canonical(repo / EXPECTED_BASELINE_REPORT)

    protocol = load_json(protocol_path)
    checkpoint = load_json(checkpoint_path)
    baseline_report = load_json(baseline_report_path)

    annotations = canonical(
        args.annotations if args.annotations else repo / DEFAULT_ANNOTATIONS
    )
    expected_annotations_sha = str(protocol.get("annotations_sha256", ""))
    if sha256_file(annotations) != expected_annotations_sha:
        die("annotation manifest SHA-256 does not match optimizer-study protocol")
    annotations_doc = load_json(annotations)

    private_root = canonical(args.private_root)
    if str(private_root).startswith("/mnt/sherlock-ssd") and not Path(
        "/mnt/sherlock-ssd"
    ).is_mount():
        die("/mnt/sherlock-ssd is not mounted")

    latest = checkpoint.get("latest_transfer_experiment")
    if not isinstance(latest, dict):
        die("checkpoint is missing latest_transfer_experiment")
    baseline_model_path = canonical(Path(str(latest.get("model_private_path", ""))))
    baseline_model = load_json(baseline_model_path)

    baseline_sha = sha256_file(baseline_model_path)
    expected_baseline_sha = str(protocol.get("baseline_head_sha256", ""))
    if baseline_sha != expected_baseline_sha:
        die(
            "private transfer baseline SHA-256 does not match protocol; "
            "refusing to compare against a different head"
        )

    fixed = protocol.get("fixed")
    if not isinstance(fixed, dict):
        die("optimizer protocol missing fixed settings")
    expected_encoder_sha = str(fixed.get("encoder", ""))
    if baseline_model.get("encoder_sha256") != expected_encoder_sha:
        die("baseline encoder identity differs from optimizer protocol")
    if baseline_model.get("augmentation") != "vertical_alignment_v1":
        die("baseline augmentation is not vertical_alignment_v1")
    if baseline_model.get("embedding_batch_size") != 1:
        die("baseline embedding batch policy is not one crop")
    crop_transform = baseline_model.get("crop_transform")
    if crop_transform != "upper_88x80_v1":
        die(f"unexpected baseline crop transform: {crop_transform!r}")
    input_size = baseline_model.get("input_size")
    if not isinstance(input_size, int):
        die("baseline model does not record input_size")

    reference = canonical(args.reference if args.reference else repo / DEFAULT_REFERENCE)
    if not (reference / "reference.json").is_file() or not (
        reference / "champions.json"
    ).is_file():
        die(f"invalid sealed reference directory: {reference}")

    images = locate_images_root(args.images, annotations_doc, repo, private_root)

    search_roots = [DEFAULT_SSD_ROOT, private_root, repo, Path.home() / "Agente-TFT"]
    encoder = locate_encoder(args.encoder, expected_encoder_sha, search_roots)
    onnxruntime = locate_onnxruntime(args.onnxruntime, search_roots)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    output_root = (
        args.output_root.expanduser()
        if args.output_root
        else private_root / f"optimizer-study-resume-{timestamp}"
    )
    if output_root.exists():
        die(f"output root already exists: {output_root}")
    output_root.mkdir(parents=True)
    specs_dir = output_root / "specs"
    logs_dir = output_root / "logs"
    cache_dir = output_root / "embedding-cache"
    cache_dir.mkdir()

    metadata = {
        "status": "running",
        "started_at_unix": int(time.time()),
        "repo_head": git_value(repo, "rev-parse", "HEAD"),
        "repo_branch": git_value(repo, "branch", "--show-current"),
        "protocol": str(EXPECTED_PROTOCOL),
        "protocol_sha256": sha256_file(protocol_path),
        "checkpoint_sha256": sha256_file(checkpoint_path),
        "annotations": str(annotations),
        "annotations_sha256": sha256_file(annotations),
        "images": str(images),
        "reference": str(reference),
        "encoder": str(encoder),
        "encoder_sha256": sha256_file(encoder),
        "onnxruntime": str(onnxruntime),
        "baseline_model": str(baseline_model_path),
        "baseline_model_sha256": baseline_sha,
        "runtime_approved": False,
        "independent_final_holdout": False,
    }
    (output_root / "run-metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if not args.skip_tests:
        run_stream(
            [
                "cargo",
                "test",
                "--release",
                "--manifest-path",
                str(repo / "tools/unit-features-lab/Cargo.toml"),
                "training::tests",
            ],
            repo,
            logs_dir / "focused-tests.log",
        )

    base_spec: dict[str, Any] = {
        "annotations": str(annotations),
        "images": str(images),
        "reference": str(reference),
        "encoder": str(encoder),
        "encoder_sha256": expected_encoder_sha,
        "onnxruntime": str(onnxruntime),
        "input_size": input_size,
        "only_dino": True,
        "retrieval_only": False,
        "augmentation": "vertical_alignment_v1",
        "crop_transform": crop_transform,
        "embedding_batch_size": 1,
        "embedding_cache": str(cache_dir),
    }

    def run_arm(name: str, optimizer: dict[str, Any] | None) -> dict[str, Any]:
        arm_out = output_root / name
        spec = dict(base_spec)
        spec["output"] = str(arm_out)
        if optimizer is not None:
            spec["optimizer"] = optimizer
        spec_path = specs_dir / f"{name}.json"
        write_spec(spec_path, spec)
        run_stream(
            [
                "cargo",
                "run",
                "--release",
                "--manifest-path",
                str(repo / "tools/unit-features-lab/Cargo.toml"),
                "--bin",
                "train-classifier",
                "--",
                "--spec",
                str(spec_path),
            ],
            repo,
            logs_dir / f"{name}.log",
        )
        report_path = canonical(arm_out / "report.json")
        model_path = canonical(arm_out / "dino-head.json")
        report = load_json(report_path)
        model = load_json(model_path)
        return {
            "name": name,
            "output": str(arm_out),
            "report_path": str(report_path),
            "model_path": str(model_path),
            "model_sha256": sha256_file(model_path),
            "metrics": validation_metrics(report),
            "_report": report,
            "_model": model,
        }

    default_arm = run_arm("optimizer-default-parity", None)
    same_head = (
        baseline_model.get("head") == default_arm["_model"].get("head")
        and baseline_model.get("selected_epoch")
        == default_arm["_model"].get("selected_epoch")
    )
    same_predictions, parity_reason = compare_predictions(
        baseline_report, default_arm["_report"]
    )
    if not same_head or not same_predictions:
        die(
            "historical-default parity failed; challengers were not run. "
            f"head_equal={same_head}, prediction_parity={same_predictions}, "
            f"reason={parity_reason}"
        )

    arms = protocol.get("arms")
    if not isinstance(arms, list):
        die("protocol arms missing")
    optimizer_by_name: dict[str, dict[str, Any]] = {}
    for arm in arms:
        if isinstance(arm, dict) and isinstance(arm.get("optimizer"), dict):
            optimizer_by_name[str(arm.get("name"))] = arm["optimizer"]

    required = ("optimizer-l2-1e4", "optimizer-l2-1e5")
    for name in required:
        if name not in optimizer_by_name:
            die(f"protocol missing optimizer definition for {name}")

    l2_1e4 = run_arm("optimizer-l2-1e4", optimizer_by_name["optimizer-l2-1e4"])
    l2_1e5 = run_arm("optimizer-l2-1e5", optimizer_by_name["optimizer-l2-1e5"])

    public_arms = []
    for item in (default_arm, l2_1e4, l2_1e5):
        public_arms.append(
            {
                "name": item["name"],
                "output": item["output"],
                "report_path": item["report_path"],
                "model_path": item["model_path"],
                "model_sha256": item["model_sha256"],
                "metrics": item["metrics"],
            }
        )

    baseline_key = metric_key(default_arm["metrics"])
    challengers = [l2_1e4, l2_1e5]
    challenger = max(challengers, key=lambda item: metric_key(item["metrics"]))
    selected = (
        challenger
        if metric_key(challenger["metrics"]) > baseline_key
        else default_arm
    )

    selection = {
        "status": "selection_frozen_before_minjo_kh_evaluation",
        "selection_rule": protocol.get("selection"),
        "parity": {
            "head_equal": True,
            "predictions_equal": True,
            "reason": parity_reason,
            "baseline_artifact_sha256": baseline_sha,
            "rerun_artifact_sha256": default_arm["model_sha256"],
            "artifact_hash_equality_required": False,
            "note": (
                "The rerun model serializes explicit optimizer metadata introduced "
                "after the historical baseline; exact head and predictions are the "
                "parity gate."
            ),
        },
        "arms": public_arms,
        "selected_arm": selected["name"],
        "selected_model_path": selected["model_path"],
        "selected_model_sha256": selected["model_sha256"],
        "selected_metrics": selected["metrics"],
        "retained_existing_baseline": selected["name"] == "optimizer-default-parity",
        "independent_final_holdout": False,
        "runtime_approved": False,
        "minjo_kh_evaluated_in_this_run": False,
        "next": (
            "Evaluate only the frozen selected challenger on Minjo/KH development "
            "sources, then improve source diversity/unknown rejection before a truly "
            "independent final holdout. Do not promote to HUD from this study."
        ),
    }
    selection_path = output_root / "optimizer-study-selection.json"
    selection_path.write_text(
        json.dumps(selection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    metadata["status"] = "complete_selection_frozen"
    metadata["finished_at_unix"] = int(time.time())
    metadata["selection"] = str(selection_path)
    (output_root / "run-metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print("\nOPTIMIZER_STUDY_OK=true")
    print(f"OUTPUT_ROOT={output_root}")
    print(f"SELECTION={selection_path}")
    print(f"SELECTED_ARM={selection['selected_arm']}")
    print(
        "SELECTED_VALIDATION="
        f"{selection['selected_metrics']['correct']}/"
        f"{selection['selected_metrics']['named']}"
    )
    print(
        "SELECTED_MACRO_RECALL="
        f"{selection['selected_metrics']['named_macro_recall']:.12f}"
    )
    print(
        "SELECTED_CROSS_ENTROPY="
        f"{selection['selected_metrics']['cross_entropy']:.12f}"
    )
    print("RUNTIME_APPROVED=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
