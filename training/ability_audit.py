"""Report seasonal ability coverage without confusing inventory with execution."""
import argparse
import hashlib
import json
from pathlib import Path

from ingestion.simulation_bindings import load_bindings
from ingestion.knowledge_release import canonical
from trainer.simulation.event_combat import validate_effects
from training.compile_effects import validate_hooks
from trainer.simulation.state import UnsupportedRule


def audit(pack):
    rows=[]
    for key,rule in pack['champions'].items():
        program=rule.get('ability_status')=='candidate_not_replay_validated'
        if program:
            validate_effects(rule['spell']['effects']);validate_hooks(rule.get('hooks',[]))
        elif rule.get('ability_status')!='blocked' or not rule.get('blockers') or 'spell' in rule:
            raise UnsupportedRule('ambiguous ability coverage entry')
        rows.append(dict(id=key,name=rule['name'],status=rule['ability_status'],
                         role_bound=program and rule.get('role') in pack['profile']['roles'],
                         replay_validated=False,blockers=rule.get('blockers',[]),notes=rule.get('notes',[])))
    return dict(schema_version=1,kind='ability_implementation_audit',patch=pack['patch'],
                release_sha256=pack['release_sha256'],bindings_sha256=hashlib.sha256(canonical(pack)).hexdigest(),
                data_components=pack['components'],scope=pack.get('ability_scope',{}),
                catalog_entries=len(rows),candidate_programs=sum(r['status']=='candidate_not_replay_validated' for r in rows),
                blocked_programs=sum(r['status']=='blocked' for r in rows),
                role_bound_programs=sum(r['role_bound'] for r in rows),replay_validated=0,
                complete=False,current_patch_training_ready=False,runtime_promoted=False,entries=rows)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bindings',type=Path,default=Path('configs/simulation/seasons/TFTSet18/18.3/manifest.json'))
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();result=audit(load_bindings(a.bindings))
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(canonical(result))
    print(json.dumps({k:result[k] for k in ('catalog_entries','candidate_programs','blocked_programs','role_bound_programs','replay_validated','complete')}))


if __name__=='__main__':main()
