"""Build and self-test a minimal headless WSL rootfs with the real analysis core."""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build/hm45-core"
CONTEXT = BUILD / "context"
APP = CONTEXT / "app"
VERSION = "0.6.4"
# Archive family only. Setup and runtime append the rootfs SHA-256 to the
# registered distro name so updates never reuse an older guest or catalog.
DISTRO = "AgenteTFT-Core-v2"
IMAGE = "agente-tft-hm45-core:0.6.4"


def copy(source: Path, destination: Path) -> None:
    if not source.exists():
        raise SystemExit(f"Missing HM4.5 core input: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination,
                        ignore=shutil.ignore_patterns("target", "__pycache__", "*.pyc", ".pytest_cache"))
    else:
        shutil.copy2(source, destination)


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, text=True, **kwargs)


def main() -> None:
    assets = ROOT / "build/hm4-live-assets"
    report = json.loads((assets / "ASSET_REPORT.json").read_text(encoding="utf-8"))
    if report.get("model_mode") != "shadow_diagnostic" or report.get("matching_item_entries", 0) < 100:
        raise SystemExit("Pinned model and icon bank were not verified")
    catalog = json.loads((ROOT / "configs/catalog/active-visual-reference-v1.json").read_text(encoding="utf-8"))
    knowledge = json.loads((ROOT / "configs/catalog/active-knowledge-release-v1.json").read_text(encoding="utf-8"))
    if CONTEXT.exists():
        shutil.rmtree(CONTEXT)
    APP.mkdir(parents=True)
    copy(ROOT / "scripts/hm45_core/Dockerfile", CONTEXT / "Dockerfile")
    copy(ROOT / "rust", CONTEXT / "rust")
    copy(ROOT / "tools/e1-native", CONTEXT / "tools/e1-native")
    copy(ROOT / "tools/hm-hp-native", CONTEXT / "tools/hm-hp-native")
    copy(ROOT / "tools/unit-features-lab", CONTEXT / "tools/unit-features-lab")
    copy(ROOT / "apps/hud_mapper/hm", APP / "apps/hud_mapper/hm")
    copy(ROOT / "apps/e1_replay/e1", APP / "apps/e1_replay/e1")
    copy(ROOT / "apps/hud_mapper/hm45_core_server.py", APP / "hm45_core_server.py")
    copy(ROOT / "apps/hud_mapper/hm45_protocol.py", APP / "hm45_protocol.py")
    copy(ROOT / "training", APP / "training")
    copy(ROOT / "ingestion", APP / "ingestion")
    copy(ROOT / "configs", APP / "configs")
    # Shared resource arithmetic only; no neural trainer or tensor dependency.
    for name in ("__init__.py", "economy.py", "round_economy.py", "state.py"):
        copy(ROOT / "trainer/simulation" / name, APP / "trainer/simulation" / name)
    copy(assets / "models", APP / "models")
    copy(assets / catalog["icon_dir"], APP / catalog["icon_dir"])
    copy(ROOT / catalog["reference"], APP / catalog["reference"])
    copy(ROOT / knowledge["reference"], APP / knowledge["reference"])
    copy(ROOT / "scripts/hm45_core/health-check", APP / "bin/health-check")

    learner_scripts = (
        "native_lab.py",
        "collect_targeted_annotation_source.py",
        "run_autonomous_shop_supervision.py",
        "autolabel_shop_purchase_consensus.py",
        "run_autonomous_source_supervision.py",
        "autolabel_tooltip_temporal_consensus.py",
        "adjudicate_autonomous_gold_anchors.py",
        "propagate_autonomous_gold_anchors.py",
        "train_weighted_autonomous_challenger.py",
        "run_post_session_shadow_learning.py",
    )
    for name in learner_scripts:
        copy(ROOT / "scripts" / name, APP / "scripts" / name)

    learner_selection = Path(os.environ.get(
        "AGENTE_TFT_HM45_LEARNER_SELECTION",
        "/mnt/sherlock-ssd/AgenteTFT/diagnostics/missing-classes-training-20261005/"
        "optimizer-study-resume-20261005-101237/optimizer-study-selection.json",
    ))
    run([
        sys.executable,
        str(ROOT / "scripts/prepare_hm45_learning_bundle.py"),
        "--selection", str(learner_selection),
        "--output", str(APP / "learner"),
    ])
    learner_package = json.loads((APP / "learner/learner-package.json").read_text(encoding="utf-8"))
    if (learner_package.get("champion") != "optimizer-default-parity"
            or learner_package.get("minjo_kh_included") is not False):
        raise SystemExit("Portable learner baseline failed frozen-selection policy")

    run(["docker", "build", "--pull", "--tag", IMAGE, str(CONTEXT)])
    health = run(["docker", "run", "--rm", "--network=none", IMAGE,
                  "self-test", "--version", VERSION], capture_output=True)
    if "AGENTETFT_CORE_HEALTH_OK" not in health.stdout:
        raise SystemExit("Linux core failed ROI/L3/OCR/B4 self-test")
    learner_health = run([
        "docker", "run", "--rm", "--network=none",
        "--entrypoint", "/bin/sh", IMAGE, "-lc",
        "set -eu; "
        "test -x /opt/agente-tft/bin/vod-collector; "
        "test -x /opt/agente-tft/bin/adjudicate-autonomous-gold; "
        "test -x /opt/agente-tft/bin/propagate-autonomous-anchors; "
        "test -x /opt/agente-tft/bin/train-classifier; "
        "test -f /opt/agente-tft/learner/selection.json; "
        "test -f /opt/agente-tft/learner/encoder/dino.onnx; "
        "test -e /opt/agente-tft/learner/libonnxruntime.so; "
        "test -f /opt/agente-tft/scripts/run_post_session_shadow_learning.py; "
        "ffmpeg -version >/dev/null; "
        "python3 -c \"import onnxruntime, PIL; print('AGENTETFT_LEARNER_HEALTH_OK')\"",
    ], capture_output=True)
    if "AGENTETFT_LEARNER_HEALTH_OK" not in learner_health.stdout:
        raise SystemExit("Linux post-session learner failed package self-test")
    BUILD.mkdir(parents=True, exist_ok=True)
    rootfs = BUILD / f"{DISTRO}.tar"
    container = run(["docker", "create", IMAGE], capture_output=True).stdout.strip()
    try:
        run(["docker", "export", "--output", str(rootfs), container])
    finally:
        run(["docker", "rm", container], capture_output=True)
    with rootfs.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    manifest = dict(schema_version=1, distro_name=DISTRO, rootfs_file=rootfs.name,
                    sha256=digest, version=VERSION,
                    analysis_health_contract="l3_ocr_b4_roi_v1",
                    linux_container_self_test=True,
                    post_session_trainer_bundled=True,
                    post_session_trainer_health=True,
                    learner_policy=learner_package["policy"],
                    learner_model_sha256=learner_package["model_sha256"],
                    learner_encoder_sha256=learner_package["encoder_sha256"],
                    learner_validation_macro_recall=learner_package.get("validation_macro_recall"),
                    learner_minjo_kh_included=False,
                    windows_wsl_field_test=False,
                    model_sha256=report["model_sha256"],
                    board_reference_sha256=report["reference_sha256"])
    (BUILD / "core-package.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(dict(rootfs=str(rootfs), bytes=rootfs.stat().st_size,
                          sha256=digest,
                          health="L3/OCR/HP/B4 + post-session learner OK")), flush=True)


if __name__ == "__main__":
    main()
