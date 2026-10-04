"""Connect HM4.5 sessions to their installed WSL core, without silent fallback."""

from __future__ import annotations

from pathlib import Path
import os
import sys

from hm45_setup_core import load_package
from hm45_vm_client import VMCore, RemoteNativeWorker, RemoteObserver


def start(options, session_id):
    if os.name != "nt":
        raise RuntimeError("O núcleo WSL 2 está disponível somente no Windows.")
    package = load_package(Path(sys.executable).resolve().parent / "core")
    core = VMCore(package.distro, Path(options.output) / "vm-core-stderr.log")
    try:
        if core.ready.get("version") != package.version:
            raise RuntimeError("A versão da VM não corresponde ao instalador.")
        model = RemoteObserver(core, options.model) if options.model else None
        reader = RemoteNativeWorker(core, "reader")
        hp = RemoteNativeWorker(core, "hp")
        return core, model, reader, hp
    except Exception:
        core.close()
        raise
