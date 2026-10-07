"""Resolve unit-features-lab commands for source checkouts or packaged WSL.

Development uses Cargo so local code changes are compiled. Packaged HM4.5 sets
AGENTE_TFT_UNIT_LAB_BIN_DIR and executes the verified prebuilt Rust binaries.
"""
from __future__ import annotations

import os
from pathlib import Path


def command(repo: Path, binary: str, args: list[str]) -> list[str]:
    packaged = os.environ.get("AGENTE_TFT_UNIT_LAB_BIN_DIR")
    if packaged:
        path = Path(packaged) / binary
        if not path.is_file():
            raise RuntimeError(f"packaged unit-lab binary missing: {path}")
        return [str(path), *args]
    return [
        "cargo",
        "run",
        "--release",
        "--manifest-path",
        str(repo / "tools/unit-features-lab/Cargo.toml"),
        "--bin",
        binary,
        "--",
        *args,
    ]


def packaged() -> bool:
    return bool(os.environ.get("AGENTE_TFT_UNIT_LAB_BIN_DIR"))
