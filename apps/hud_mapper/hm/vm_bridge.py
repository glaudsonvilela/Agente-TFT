"""Connect HM4.5 sessions to their installed WSL core, without silent fallback."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys

from hm45_setup_core import load_package
from hm45_vm_client import VMCore, RemoteNativeWorker, RemoteObserver


def _to_wsl_path(distro: str, path: Path) -> str:
    result = subprocess.run(
        ["wsl.exe", "--distribution", distro, "--exec", "wslpath", "-u", str(path)],
        text=True,
        errors="replace",
        capture_output=True,
        timeout=20,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    value = (result.stdout or "").replace("\x00", "").strip()
    if result.returncode != 0 or not value.startswith("/"):
        detail = (result.stderr or result.stdout or "").replace("\x00", "").strip()
        raise RuntimeError("Não foi possível mapear o champion neural para o WSL: " + detail[:300])
    return value


def _active_bundle_root(options) -> Path | None:
    try:
        from .model_update import active_model_metadata
        active = active_model_metadata()
    except Exception:
        active = None
    metadata = active or (Path(options.model).resolve() if options.model else None)
    if metadata is None or not metadata.is_file():
        return None
    if metadata.name != "deployment-candidate.json" or metadata.parent.name != "models":
        return None
    return metadata.parent.parent


def start(options, session_id):
    if os.name != "nt":
        raise RuntimeError("O núcleo WSL 2 está disponível somente no Windows.")
    package = load_package(Path(sys.executable).resolve().parent / "core")
    environment = {}
    bundle_root = _active_bundle_root(options)
    if bundle_root is not None:
        environment["AGENTE_TFT_RUNTIME_NEURAL_ROOT"] = _to_wsl_path(
            package.runtime_distro,
            bundle_root,
        )
    core = VMCore(
        package.runtime_distro,
        Path(options.output) / "vm-core-stderr.log",
        environment=environment,
    )
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
