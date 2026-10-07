#!/usr/bin/env python3
"""Prune completed raw neural evidence without touching learned corpus or models.

Default is dry-run. Use --apply only on BigBANANA.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import time


TERMINAL = {"complete", "failed"}


def load_terminal_sessions(db_path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not db_path.is_file():
        return result
    with sqlite3.connect(db_path) as db:
        for kind, identifier, payload in db.execute(
            "SELECT kind,id,payload FROM records WHERE kind='neural_session'"
        ):
            del kind
            try:
                doc = json.loads(payload)
            except json.JSONDecodeError:
                continue
            status = doc.get("status")
            if status in TERMINAL:
                result[identifier] = status
    return result


def age_days(path: Path, now: float) -> float:
    return max(0.0, (now - path.stat().st_mtime) / 86400.0)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--data-root",
        type=Path,
        default=Path("/var/lib/agente-tft-trainer"),
    )
    p.add_argument("--raw-days", type=float, default=7.0)
    p.add_argument("--work-days", type=float, default=3.0)
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    if not (1.0 <= args.raw_days <= 365.0):
        raise SystemExit("raw-days outside 1..365")
    if not (1.0 <= args.work_days <= 365.0):
        raise SystemExit("work-days outside 1..365")

    root = args.data_root.resolve()
    db = root / "trainer.sqlite3"
    terminal = load_terminal_sessions(db)
    now = time.time()

    candidates: list[tuple[str, Path, float]] = []
    evidence_root = root / "neural-evidence"
    if evidence_root.is_dir():
        for folder in evidence_root.iterdir():
            if (
                folder.is_dir()
                and folder.name in terminal
                and age_days(folder, now) >= args.raw_days
            ):
                candidates.append(("raw_evidence", folder, age_days(folder, now)))

    work_root = root / "neural-work"
    if work_root.is_dir():
        for folder in work_root.iterdir():
            if (
                folder.is_dir()
                and folder.name in terminal
                and age_days(folder, now) >= args.work_days
            ):
                candidates.append(("workspace", folder, age_days(folder, now)))

    # Explicit allowlist: these learned/promotion roots are never traversed.
    protected = {
        (root / "neural-corpus").resolve(),
        (root / "learning-champion").resolve(),
        (root / "champions").resolve(),
        (root / "neural-candidates").resolve(),
        (root / "neural-jobs").resolve(),
    }
    deleted = 0
    bytes_removed = 0
    rows = []
    for kind, path, days in sorted(candidates, key=lambda row: str(row[1])):
        resolved = path.resolve()
        if any(resolved == protected_root or resolved.is_relative_to(protected_root)
               for protected_root in protected):
            raise SystemExit(f"refusing to prune protected path: {resolved}")
        size = sum(
            p.stat().st_size
            for p in resolved.rglob("*")
            if p.is_file()
        )
        rows.append({
            "kind": kind,
            "session_id": path.name,
            "path": str(path),
            "age_days": round(days, 3),
            "bytes": size,
        })
        if args.apply:
            shutil.rmtree(path)
            deleted += 1
            bytes_removed += size

    print(json.dumps({
        "schema_version": 1,
        "policy": "bigbanana_neural_retention_v1",
        "apply": args.apply,
        "terminal_sessions": len(terminal),
        "candidates": rows,
        "candidate_count": len(rows),
        "deleted": deleted,
        "bytes_removed": bytes_removed,
        "raw_days": args.raw_days,
        "work_days": args.work_days,
        "protected_roots": sorted(str(p) for p in protected),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
