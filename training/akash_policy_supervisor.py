"""Run an audited policy trainer on Akash with a durable wall-clock budget.

The work directory must be an Akash persistent volume. A container restart may
discard the current batch, but it cannot reset the deadline or silently start
new weights. The child trainer must save a sealed checkpoint.json atomically,
accept --resume, and write complete.flag only after a successful final save.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_persistent(workdir: Path, volume: Path) -> None:
    root = volume.resolve()
    target = workdir.resolve()
    if root == Path("/") or not os.path.ismount(root) or not target.is_relative_to(root):
        raise ValueError("job directory must be inside the mounted persistent volume")


def checkpoint_valid(workdir: Path) -> bool:
    seal_path = workdir / "checkpoint.json"
    if not seal_path.is_file() or seal_path.is_symlink():
        return False
    seal = json.loads(seal_path.read_text())
    name, expected = seal.get("path"), seal.get("sha256")
    if not isinstance(name, str) or Path(name).name != name or not isinstance(expected, str):
        raise ValueError("unsafe checkpoint seal")
    artifact = workdir / name
    if not artifact.is_file() or artifact.is_symlink():
        raise ValueError("sealed checkpoint is missing")
    if file_sha256(artifact) != expected:
        raise ValueError("checkpoint hash mismatch")
    return True


def preflight(repo: Path, selection: Path, dataset: Path, content: Path) -> dict:
    """Keep video demonstrations and simulator branches behind separate gates."""
    from training.audit_full_simulator_18_4b import audit as simulator_audit
    from training.prepare_challenger_strategy import audit as selection_audit

    selected = selection_audit(json.loads(selection.read_text()), repo)
    simulation = simulator_audit()
    blockers = []
    if not selected["training_ready"]:
        blockers.append("reviewed_1080p_challenger_matches_or_patch_rules_missing")
    if not simulation["synthetic_rollouts_allowed_for_player_policy"]:
        blockers.append("18.4B_full_match_simulator_not_validated")
    label_count = 0
    if not dataset.is_file() or not content.is_file():
        blockers.append("reviewed_action_dataset_or_compiled_content_missing")
    else:
        from training.decision_lab import prepare, sha
        from training.event_lab import engine_identity
        compiled = json.loads(content.read_text())
        _, labels = prepare(json.loads(dataset.read_text()), patch=compiled["patch"],
                            content_sha256=sha(content),
                            engine_sha256=engine_identity()["sha256"],
                            evidence_root=dataset.parent)
        label_count = labels["rows"]
    return dict(training_ready=not blockers, blockers=blockers,
                selected_matches=selected["selected_matches"],
                reviewed_actions=label_count,
                simulator_ready=simulation["synthetic_rollouts_allowed_for_player_policy"],
                input_sha256={name: file_sha256(path) for name, path in
                              (("selection", selection), ("dataset", dataset),
                               ("content", content)) if path.is_file()},
                simulator_catalog_sha256=simulation["catalog_sha256"])


def run(workdir: Path, command: list[str], *, seconds: int, input_identity: str = "",
        now=time.time,
        sleep=time.sleep) -> dict:
    if not command or not 1 <= seconds <= 86400:
        raise ValueError("command and 1..86400 second budget required")
    workdir.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (workdir / "worker.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = workdir / "job.json"
        command_hash = hashlib.sha256(json.dumps([command, input_identity]).encode()).hexdigest()
        if path.exists():
            state = json.loads(path.read_text())
            if state["command_sha256"] != command_hash or state["budget_seconds"] != seconds:
                raise ValueError("existing job has different command or budget")
        else:
            state = dict(schema_version=1, command_sha256=command_hash,
                         input_identity=input_identity,
                         budget_seconds=seconds, deadline_utc=now() + seconds,
                         attempts=0, status="created")
            atomic_json(path, state)
        if (workdir / "complete.flag").exists():
            state["status"] = "completed"
            atomic_json(path, state)
            return state
        stopped = False
        child = None
        def stop(*_):
            nonlocal stopped
            stopped = True
            if child is not None and child.poll() is None:
                child.terminate()
        previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            while now() < state["deadline_utc"] and not stopped:
                resumed = checkpoint_valid(workdir)
                if state["attempts"] and not resumed:
                    raise ValueError("refusing to restart without a valid checkpoint")
                state.update(status="running", attempts=state["attempts"] + 1,
                             resumed_from_checkpoint=resumed, updated_utc=now())
                atomic_json(path, state)
                env = {**os.environ, "TFT_CHECKPOINT_DIR": str(workdir),
                       "TFT_DEADLINE_UTC": str(state["deadline_utc"])}
                with (workdir / "training.log").open("ab") as log:
                    child = subprocess.Popen(command + (["--resume"] if resumed else []),
                                             cwd=workdir, env=env, stdout=log,
                                             stderr=subprocess.STDOUT)
                    while child.poll() is None and not stopped:
                        if now() >= state["deadline_utc"]:
                            child.terminate()
                            try:
                                child.wait(timeout=25)
                            except subprocess.TimeoutExpired:
                                child.kill()
                            break
                        sleep(1)
                    if stopped and child.poll() is None:
                        try:
                            child.wait(timeout=25)
                        except subprocess.TimeoutExpired:
                            child.kill()
                    code = child.wait()
                state.update(last_exit_code=code, updated_utc=now())
                if (workdir / "complete.flag").exists():
                    if not checkpoint_valid(workdir):
                        raise ValueError("completion without sealed checkpoint")
                    state["status"] = "completed"
                    break
                if stopped or now() >= state["deadline_utc"]:
                    state["status"] = "stopped" if stopped else "budget_exhausted"
                    break
                if code == 0:
                    raise ValueError("trainer exited without complete.flag")
                if not checkpoint_valid(workdir):
                    raise ValueError("trainer crashed before saving a checkpoint")
                state["status"] = "retrying_from_checkpoint"
                atomic_json(path, state)
                sleep(min(30, 2 ** min(state["attempts"], 5)))
            else:
                state["status"] = "budget_exhausted" if not stopped else "stopped"
        except Exception as error:
            state.update(status="failed", error=f"{type(error).__name__}: {error}")
            atomic_json(path, state)
            raise
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
        atomic_json(path, state)
        return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--content", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--persistent-root", type=Path, default=Path("/workspace"))
    parser.add_argument("--seconds", type=int, default=32400)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    ensure_persistent(args.workdir, args.persistent_root)
    gate = preflight(args.repo, args.selection, args.dataset, args.content)
    if not gate["training_ready"]:
        print(json.dumps(gate, ensure_ascii=False), flush=True)
        raise SystemExit(2)
    identity = hashlib.sha256(json.dumps({
        "inputs": gate["input_sha256"],
        "simulator_catalog": gate["simulator_catalog_sha256"],
    }, sort_keys=True).encode()).hexdigest()
    result = run(args.workdir, command, seconds=args.seconds,
                 input_identity=identity)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
