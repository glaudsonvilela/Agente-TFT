"""Run reproducible synthetic matches and bounded hex/action search on CPU."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import resource
import time

from trainer.simulation.combat import simulate
from trainer.simulation.match import play
from trainer.simulation.search import search
from trainer.simulation.state import Player, Unit, World
from .transcribe_sources import atomic, digest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--content',type=Path,default=Path('configs/simulation/hex-lab-v1.json'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--matches',type=int,default=10)
    p.add_argument('--paths',type=int,default=500)
    p.add_argument('--seconds',type=int,default=120)
    args=p.parse_args()
    if not 1<=args.matches<=500 or not 1<=args.paths<=5000 or not 1<=args.seconds<=3600:
        p.error('budget outside laboratory limits')
    content=json.loads(args.content.read_text()); started=time.monotonic(); matches=[]
    for seed in range(args.matches):
        if time.monotonic()-started>=args.seconds: break
        matches.append(play(content,seed))
    world=World([Player(5,2,0,units=[Unit('a','lab_fighter',zone='board',position=(0,3)),
                                   Unit('b','lab_caster',zone='board',position=(3,3))],inventory=['lab_sword']),
                 Player(5,2,0,units=[Unit('c','lab_tank',zone='board',position=(0,3)),
                                    Unit('d','lab_caster',zone='board',position=(3,3))])],
                {c:10 for c in content['champions']})
    def evaluate(state,seed):
        result=simulate(state.players,content,seed=seed)
        return 0. if result['winner'] is None else 1. if result['winner']==0 else -1.
    remaining=args.seconds-(time.monotonic()-started)
    result=search(world,0,content,evaluate,simulations=args.paths,seconds=remaining,depth=2) if remaining>0 else None
    if result:
        result['action']=asdict(result['action'])
        for c in result['candidates']: c['action']=asdict(c['action'])
    report=dict(schema_version=1,scope='experimental_hex_lab',content_sha256=digest(args.content),
                matches_requested=args.matches,matches_completed=sum(m['completed'] for m in matches),
                matches_truncated=sum(m['truncated'] for m in matches),
                combat_calls=sum(m['combat_calls'] for m in matches),matches=matches,search=result,
                elapsed_seconds=time.monotonic()-started,peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                current_patch_training_ready=False,runtime_promoted=False)
    args.output.parent.mkdir(parents=True,exist_ok=True);atomic(args.output,report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('matches','search')},indent=2))
    if result: print(json.dumps({k:v for k,v in result.items() if k!='candidates'},indent=2))


if __name__=='__main__': main()
