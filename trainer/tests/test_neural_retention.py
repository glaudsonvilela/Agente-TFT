from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
import time


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prune_neural_storage.py"
SPEC = importlib.util.spec_from_file_location("prune_neural_storage_test_target", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _record(db: Path, session_id: str, status: str):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS records (kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,id))"
        )
        conn.execute(
            "INSERT OR REPLACE INTO records(kind,id,payload) VALUES(?,?,?)",
            ("neural_session", session_id, json.dumps({
                "neural_session_id": session_id,
                "status": status,
            })),
        )


def _age(path: Path, days: int):
    old = time.time() - days * 86400
    path.touch()
    import os
    os.utime(path, (old, old))


def test_retention_selects_only_old_terminal_sessions(tmp_path):
    db = tmp_path / "trainer.sqlite3"
    _record(db, "done", "complete")
    _record(db, "failed", "failed")
    _record(db, "active", "processing")

    for root_name in ("neural-evidence", "neural-work"):
        root = tmp_path / root_name
        for sid in ("done", "failed", "active"):
            folder = root / sid
            folder.mkdir(parents=True)
            payload = folder / "payload.bin"
            payload.write_bytes(b"x" * 32)
            _age(folder, 10)
            _age(payload, 10)

    terminal = MODULE.load_terminal_sessions(db)
    assert terminal == {"done": "complete", "failed": "failed"}
    now = time.time()
    assert MODULE.age_days(tmp_path / "neural-evidence" / "done", now) >= 9
    assert "active" not in terminal


def test_retention_protected_roots_are_separate_from_raw_storage(tmp_path):
    for name in (
        "neural-corpus",
        "learning-champion",
        "champions",
        "neural-candidates",
        "neural-jobs",
    ):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "keep.txt").write_text("keep")
    assert (tmp_path / "neural-corpus" / "keep.txt").is_file()
    assert (tmp_path / "champions" / "keep.txt").is_file()
