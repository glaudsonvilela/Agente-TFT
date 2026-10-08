"""Entry point for the bundled Windows + VM setup assistant."""

from pathlib import Path
import sys

from hm45_setup_core import SetupError


def main() -> int:
    if sys.platform != "win32":
        raise SetupError("O assistente de instalação requer Windows.")
    from hm45_setup_web import run_setup
    app_exe = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve()
    return run_setup(app_exe, resume="--resume-core" in sys.argv,
                     resume_headless="--resume-headless" in sys.argv)
