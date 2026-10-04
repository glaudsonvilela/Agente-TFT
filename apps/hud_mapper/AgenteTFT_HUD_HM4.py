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
        if '--setup-assistant' in sys.argv:
            from hm45_setup import main as setup_main
            return setup_main()
        from hm.runtime_app import main as run
        return run("hm4")
    except Exception:
        traceback.print_exc()
        if not any(x in sys.argv for x in ('--headless', '--ui-smoke', '--voice-smoke-output', '--replay-voice-validation')):
            from tkinter import messagebox
            messagebox.showerror('HUD Mapper HM4', 'Falha na inicialização. Consulte AgenteTFT-HUD-HM4/logs.')
        return 2

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
