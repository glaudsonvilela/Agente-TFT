"""Portable entry point; no trainer import on the observation path."""
import sys
from pathlib import Path
if not getattr(sys,'frozen',False):
    root=Path(__file__).resolve().parents[2]
    sys.path.insert(0,str(root/'apps/e1_replay'))
    sys.path.insert(0,str(root/'experiments/ui-map-lite-l2/training'))
from hm.app import main
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print('HUD_MAPPER_ERROR='+str(exc),file=sys.stderr)
        raise
