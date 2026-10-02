"""Load an immutable, completed L1 run; never select a baseline by score."""
from pathlib import Path
from .common import load,sha,require


def validate_baseline(path):
    p=Path(path).resolve(strict=True)
    if not (p/'COMPLETE.json').exists() and (p/'run/COMPLETE.json').exists():p=p/'run'
    seal=load(p/'COMPLETE.json');require(isinstance(seal,dict) and 0<len(seal)<=32,'invalid L1 seal')
    for name,digest in seal.items():
        require(Path(name).name==name and isinstance(digest,str) and len(digest)==64,'unsafe L1 seal')
        f=p/name;require(f.is_file() and not f.is_symlink() and sha(f)==digest,'L1 changed: '+name)
    require({'weights.npz','report.json','sources.json','plan.json'}<=set(seal),'incomplete L1 seal')
    report=load(p/'report.json')['summary']
    require(report['policy']=='uimap-lite-l1-v1' and report['execution_complete'] and report['model_trained'], 'not completed L1')
    provenance=dict(path=str(p),weights_sha256=sha(p/'weights.npz'),seal_sha256=sha(p/'COMPLETE.json'),
                    historical_summary=report,selection='latest_completed_by_directory_mtime_not_metric')
    return p,provenance


def locate(root):
    rows=[]
    for p in Path(root).glob('match-001-ui-map-l1.*/run'):
        if (p/'COMPLETE.json').is_file():rows.append(p)
    require(rows,'No completed L1 found. Set UI_MAP_L1_RUN to the existing L1 run directory.')
    # Stop on corruption in the most recent complete run, never skip to a convenient older score.
    selected=sorted(rows,key=lambda p:(p.parent.stat().st_mtime_ns,str(p)))[-1]
    return validate_baseline(selected)[0]
