"""Open the bundled local UI without loading a .NET/Python bridge."""

from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys
import time
import webbrowser


def browser_executable() -> Path | None:
    if sys.platform != "win32":
        return None
    roots = [os.environ.get(name, "") for name in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
    for root in roots:
        if not root:
            continue
        for relative in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
            candidate = Path(root) / relative
            if candidate.is_file():
                return candidate
    for name in ("msedge.exe", "chrome.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def open_local_window(url: str, profile_name: str) -> subprocess.Popen | None:
    """Edge/Chrome app window first; the system browser remains a fallback."""
    executable = browser_executable()
    if executable:
        profile = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AgenteTFT-HUD-HM4" / profile_name
        profile.mkdir(parents=True, exist_ok=True)
        args = [str(executable), f"--app={url}", "--new-window", f"--user-data-dir={profile}",
                "--no-first-run", "--no-default-browser-check",
                "--window-size=1120,800" if profile_name == "setup-browser" else "--window-size=1440,900"]
        process = subprocess.Popen(args, cwd=str(executable.parent),
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        time.sleep(0.3)
        if process.poll() not in (None, 0):
            raise RuntimeError("O navegador local encerrou antes de mostrar a janela.")
        return process
    if webbrowser.open(url, new=1):
        return None
    raise RuntimeError("Nenhum navegador disponível para mostrar a interface local.")
