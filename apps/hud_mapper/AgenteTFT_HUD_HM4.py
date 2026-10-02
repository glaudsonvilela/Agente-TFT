"""HM4 simplified automatic GUI entry."""
from pathlib import Path
import os, sys, time, traceback

def main():
    if sys.stderr is None or sys.stdout is None:
        root = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'AgenteTFT-HUD-HM4' / 'logs'
        root.mkdir(parents=True, exist_ok=True)
        path = root / ('startup-' + str(time.time_ns()) + '-' + str(os.getpid()) + '.log')
        log = path.open('x', encoding='utf-8', buffering=1)
        if sys.stderr is None:
            sys.stderr = log
        if sys.stdout is None:
            sys.stdout = log
    try:
        from hm.runtime_app import main as run
        return run("hm4")
    except Exception:
        traceback.print_exc()
        if not any(x in sys.argv for x in ('--headless', '--ui-smoke')):
            from tkinter import messagebox
            messagebox.showerror('HUD Mapper HM4', 'Falha na inicialização. Consulte AgenteTFT-HUD-HM4/logs.')
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
