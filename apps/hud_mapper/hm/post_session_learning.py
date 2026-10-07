"""Launch post-session shadow learning only after a sealed HM4 session.

Linux/source checkouts can execute the repository learner directly. Verified
HM4.5 Windows packages launch the bundled learner inside their pinned WSL
distro. Missing capabilities fail closed by persisting a queued job.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _queued(reason: str) -> dict:
    return {
        "schema_version": 1,
        "status": "queued_waiting_for_packaged_wsl_trainer",
        "reason": reason,
        "training_started": False,
        "active_model_changed": False,
        "promotion_mode": "shadow_candidate_only",
        "human_review_required": False,
        "runtime_approved": False,
    }


def _windows_core_package() -> tuple[str, dict] | None:
    if os.name != "nt":
        return None
    app_root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3]
    core = app_root / "core"
    manifest_path = core / "core-package.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        manifest.get("schema_version") != 1
        or manifest.get("post_session_trainer_bundled") is not True
        or manifest.get("post_session_trainer_health") is not True
        or manifest.get("learner_minjo_kh_included") is not False
    ):
        return None
    family = manifest.get("distro_name")
    digest = manifest.get("sha256")
    if not isinstance(family, str) or not isinstance(digest, str) or len(digest) != 64:
        return None
    return f"{family}-{digest}", manifest


def _wsl_path(distro: str, path: Path) -> str:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["wsl.exe", "--distribution", distro, "--exec", "wslpath", "-u", str(path)],
        text=True,
        errors="replace",
        capture_output=True,
        timeout=20,
        check=False,
        creationflags=flags,
    )
    value = (result.stdout or "").replace("\x00", "").strip()
    if result.returncode != 0 or not value.startswith("/"):
        detail = (result.stderr or result.stdout or "").replace("\x00", "").strip()
        raise RuntimeError("WSL não converteu a pasta da sessão: " + detail[:300])
    return value


def _launch_windows_wsl(session: Path, log: Path) -> dict | None:
    package = _windows_core_package()
    if package is None:
        return None
    distro, manifest = package
    try:
        linux_session = _wsl_path(distro, session)
    except Exception as exc:
        return _queued("wsl_session_path_failed:" + str(exc)[:300])

    command = [
        "wsl.exe",
        "--distribution",
        distro,
        "--exec",
        "/usr/bin/env",
        "AGENTE_TFT_UNIT_LAB_BIN_DIR=/opt/agente-tft/bin",
        "PYTHONPATH=/opt/agente-tft:/opt/agente-tft/apps/hud_mapper:/opt/agente-tft/apps/e1_replay",
        "OMP_THREAD_LIMIT=1",
        "OPENBLAS_NUM_THREADS=1",
        "python3",
        "/opt/agente-tft/scripts/run_post_session_shadow_learning.py",
        "--repo",
        "/opt/agente-tft",
        "--selection",
        "/opt/agente-tft/learner/selection.json",
        "--session",
        linux_session,
        "--ffmpeg",
        "/usr/bin/ffmpeg",
    ]
    try:
        handle = log.open("ab")
        process = subprocess.Popen(
            command,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                         | getattr(subprocess, "DETACHED_PROCESS", 0),
            close_fds=True,
        )
        handle.close()
    except OSError as exc:
        return _queued("wsl_learner_launch_failed:" + str(exc)[:300])

    return {
        "schema_version": 1,
        "status": "running_shadow_learning_wsl",
        "pid": process.pid,
        "started_unix": time.time(),
        "distro": distro,
        "rootfs_sha256": manifest.get("sha256"),
        "learner_model_sha256": manifest.get("learner_model_sha256"),
        "learner_encoder_sha256": manifest.get("learner_encoder_sha256"),
        "linux_session": linux_session,
        "training_started": True,
        "active_model_changed": False,
        "promotion_mode": "shadow_candidate_only",
        "human_review_required": False,
        "runtime_approved": False,
    }


def launch_post_session_learning(session_dir: str | Path) -> dict:
    session = Path(session_dir).resolve()
    job_path = session / "shadow-learning" / "post-session-job.json"
    if job_path.is_file():
        return json.loads(job_path.read_text(encoding="utf-8"))

    summary_path = session / "summary.json"
    sealed_path = session / "shadow-learning" / "SEALED.json"
    complete_path = session / "COMPLETE.json"
    if not all(p.is_file() for p in (summary_path, sealed_path, complete_path)):
        value = {
            "schema_version": 1,
            "status": "not_eligible",
            "reason": "sealed_complete_session_required",
            "training_started": False,
            "active_model_changed": False,
        }
        _write(job_path, value)
        return value

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    sealed = json.loads(sealed_path.read_text(encoding="utf-8"))
    if (
        summary.get("execution_complete") is not True
        or sealed.get("ready_for_post_session_learning") is not True
    ):
        value = {
            "schema_version": 1,
            "status": "not_eligible",
            "reason": "session_or_learning_capture_incomplete",
            "training_started": False,
            "active_model_changed": False,
        }
        _write(job_path, value)
        return value

    log = session / "shadow-learning" / "post-session-launch.log"

    # Linux/source execution path.
    repo = Path(__file__).resolve().parents[3]
    runner = repo / "scripts" / "run_post_session_shadow_learning.py"
    cargo = repo / "tools" / "unit-features-lab" / "Cargo.toml"
    if runner.is_file() and cargo.is_file() and os.name != "nt":
        with log.open("ab") as handle:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(runner),
                    "--repo",
                    str(repo),
                    "--session",
                    str(session),
                ],
                cwd=repo,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        value = {
            "schema_version": 1,
            "status": "running_shadow_learning",
            "pid": process.pid,
            "started_unix": time.time(),
            "runner": str(runner),
            "training_started": True,
            "active_model_changed": False,
            "promotion_mode": "shadow_candidate_only",
            "human_review_required": False,
            "runtime_approved": False,
        }
    elif os.name == "nt":
        value = _launch_windows_wsl(session, log) or _queued(
            "verified_post_session_trainer_not_available_in_installed_core"
        )
    else:
        value = _queued("source_post_session_trainer_not_available")

    _write(job_path, value)
    return value
