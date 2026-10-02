"""HM3 capture-only GUI entry. Startup diagnostics are separate from frame telemetry."""
from pathlib import Path
import os, sys, time, traceback


def main():
    # pythonw/PyInstaller --windowed can set stdout/stderr to None.
    # Keep errors inspectable without opening a console or importing a trainer.
    if sys.stderr is None or sys.stdout is None:
        root = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'AgenteTFT-HUD-HM3' / 'logs'
        root.mkdir(parents=True, exist_ok=True)
        path = root / ('startup-' + str(time.time_ns()) + '-' + str(os.getpid()) + '.log')
        log = path.open('x', encoding='utf-8', buffering=1)
        if sys.stderr is None:
            sys.stderr = log
        if sys.stdout is None:
            sys.stdout = log
    try:
        from hm.runtime_app import main as run
        return run()
    except Exception:
        traceback.print_exc()
        if not any(x in sys.argv for x in ('--headless', '--ui-smoke')):
            from tkinter import messagebox
            messagebox.showerror('HUD Mapper HM3', 'Falha na inicialização. Consulte o log em AgenteTFT-HUD-HM3/logs.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
