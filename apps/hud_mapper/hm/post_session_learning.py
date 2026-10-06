"""Launch post-session shadow learning only after a sealed HM4 session.

Source checkouts can execute the repository learner immediately. Packaged
Windows builds that do not yet contain the Linux trainer fail closed by
persisting a queued job; they never claim that training happened.
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
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


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
    if summary.get("execution_complete") is not True or sealed.get("ready_for_post_session_learning") is not True:
        value = {
            "schema_version": 1,
            "status": "not_eligible",
            "reason": "session_or_learning_capture_incomplete",
            "training_started": False,
            "active_model_changed": False,
        }
        _write(job_path, value)
        return value

    # Repository/source execution path. PyInstaller builds resolve __file__ into
    # the packaged tree, where scripts/tools are deliberately absent today.
    repo = Path(__file__).resolve().parents[3]
    runner = repo / "scripts" / "run_post_session_shadow_learning.py"
    cargo = repo / "tools" / "unit-features-lab" / "Cargo.toml"
    log = session / "shadow-learning" / "post-session-launch.log"

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
    else:
        value = {
            "schema_version": 1,
            "status": "queued_waiting_for_packaged_wsl_trainer",
            "reason": "post_session_trainer_not_yet_bundled_in_windows_runtime",
            "training_started": False,
            "active_model_changed": False,
            "promotion_mode": "shadow_candidate_only",
            "human_review_required": False,
            "runtime_approved": False,
        }

    _write(job_path, value)
    return value
