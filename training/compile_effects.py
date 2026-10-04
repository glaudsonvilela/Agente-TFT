"""Compile a sealed catalog plus a separately versioned seasonal rules pack.

Mechanics live in trainer.simulation. Names, fields, coefficients, trigger rules,
role metrics and star progression are supplied by the selected data pack.
Compilation never implies replay validation or HUD promotion.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ingestion.knowledge_release import read_release, canonical
from ingestion.simulation_bindings import load_bindings,substitute,referenced_fields
from ingestion.numeric_overrides import apply_overrides
from trainer.simulation.event_combat import validate_effects
from trainer.simulation.state import UnsupportedRule


def validate_hooks(hooks):
    for hook in hooks:
        validate_effects(hook['effects'])
        validate_effects(hook.get('at_limit_effects',[]))


def compile_item(row,rules):
    rule=rules['entities'].get(row['api_name']);fields=row['effects']
    if rule is None:return dict(unsupported=True,name=row['name'],reason='effect binding missing')
    fields=apply_overrides(fields,rule.get('numeric_overrides',[]),rules.get('patch'))
    known=set(rules['base_fields'])|referenced_fields(rule)
    if set(fields)-known:raise UnsupportedRule(f'unreviewed item numeric fields: {row["api_name"]}')
    mods=[]
    for key,binding in rules['base_fields'].items():
        if key in fields:
            mods.append(dict(stat=binding['stat'],mode=binding['mode'],
                             value=substitute({'$field':key,'scale':binding['scale']},fields)))
    for alias in rule.get('aliases',[]):
        if abs(substitute(alias['left'],fields)-substitute(alias['right'],fields))>1e-6:
            raise UnsupportedRule('numeric aliases disagree; never apply twice')
    template=substitute(rule['template'],fields)
    mods.extend(template.get('modifiers',[]));hooks=template.get('hooks',[]);validate_hooks(hooks)
    return dict(name=row['name'],combat_handler='effects',component=rule.get('component',False),
                unique=row['unique'],modifiers=mods,hooks=hooks,status='candidate_not_replay_validated',
                **({'grants_traits':template['grants_traits']} if 'grants_traits' in template else {}),
                **({'numeric_overrides':deepcopy(rule['numeric_overrides'])} if rule.get('numeric_overrides') else {}))


def compile_trait(row,rules):
    rule=rules['entities'].get(row['api_name'],{});tiers=[]
    effects=deepcopy(row['effects'])
    for effect in effects:
        binding=rule.get('tiers',{}).get(str(effect['min_units']),{})
        effect['variables']=apply_overrides(effect['variables'],binding.get('numeric_overrides',[]),rules.get('patch'))
    for effect in effects:
        tier=dict(min=effect['min_units'],max=effect['max_units'])
        binding=rule.get('tiers',{}).get(str(effect['min_units']))
        if binding is None:tier['unsupported']=True
        else:
            if set(effect['variables'])-referenced_fields(binding):
                raise UnsupportedRule(f'unreviewed trait numeric fields: {row["api_name"]}')
            tier.update(substitute(binding['template'],effect['variables'],effects))
            if binding.get('numeric_overrides'):
                tier['numeric_overrides']=deepcopy(binding['numeric_overrides'])
            for scope in ('team','members'):validate_hooks(tier.get(scope,{}).get('hooks',[]))
        tiers.append(tier)
    status='candidate_not_replay_validated' if tiers and all(not t.get('unsupported') for t in tiers) else 'missing_handler'
    return dict(name=row['name'],tiers=tiers,status=status)


def compile_catalog(manifest,catalogs,bindings):
    if bindings['release_sha256']!=manifest['release_sha256'] or bindings['patch']!=manifest['tft_patch'] or bindings['set_key']!=manifest['set']['key']:
        raise UnsupportedRule('binding and sealed catalog identity differ')
    if bindings.get('status')!='candidate_not_replay_validated' or bindings.get('runtime_promoted') is not False:
        raise UnsupportedRule('candidate compiler cannot promote a release')
    for name in ('items','traits','champions','profile'):
        if 'patch' in bindings[name] and bindings[name]['patch']!=bindings['patch']:
            raise UnsupportedRule(f'seasonal component patch mismatch: {name}')
    profile=bindings['profile']
    trait_names={t['name']:t['api_name'] for t in catalogs['traits']['traits']}
    champions={}
    for row in catalogs['units']['champions']:
        key=row['api_name'];spec=dict(name=row['name'],cost=row['cost'],traits=[trait_names[n] for n in row['traits']])
        binding=bindings['champions'].get(key)
        if binding is None or binding.get('ability_status')=='blocked':
            if binding and ('spell' in binding or not binding.get('blockers')):
                raise UnsupportedRule('blocked ability must list blockers and cannot expose a runnable spell')
            spec.update(unsupported=True,reason='ability binding incomplete',
                        ability_status='blocked',ability_blockers=deepcopy((binding or {}).get('blockers',['binding missing'])))
        else:
            if binding.get('ability_status') not in (None,'candidate_not_replay_validated'):
                raise UnsupportedRule('unknown ability status')
            validate_effects(binding['spell']['effects']);validate_hooks(binding.get('hooks',[]))
            spec['ability_status']='candidate_not_replay_validated'
            spec['ability_program']={k:deepcopy(binding[k]) for k in ('spell','hooks','modifiers') if k in binding}
            spec['ability_notes']=deepcopy(binding.get('notes',[]))
            spec['supported_stars']=deepcopy(binding.get('supported_stars',[1,2,3]))
            if 'identity' in binding:spec['identity']=binding['identity']
            role=profile['roles'].get(binding.get('role'))
            if role is None:
                spec.update(unsupported=True,reason='ability program available; mana role/timing integration unverified')
                champions[key]=spec
                continue
            v=row['stats'];missing=[k for k in ('hp','damage','armor','magicResist','attackSpeed','mana','initialMana','range','critChance','critMultiplier') if v.get(k) is None]
            if missing:raise UnsupportedRule(f'missing attributes: {key}: {missing}')
            spec.update(combat=dict(hp=[v['hp']*n for n in profile['star_multipliers']['hp']],
                ad=[v['damage']*n for n in profile['star_multipliers']['ad']],
                ap=profile['base_ap'],armor=v['armor'],mr=v['magicResist'],attack_speed=v['attackSpeed'],range=v['range'],
                mana=v['mana'],initial_mana=v['initialMana'],**deepcopy(role),
                crit_chance=v['critChance'],crit_multiplier=v['critMultiplier']),
                spell=deepcopy(binding['spell']),hooks=deepcopy(binding.get('hooks',[])),modifiers=deepcopy(binding.get('modifiers',[])),status='candidate_not_replay_validated')
            validate_effects(spec['spell']['effects'])
        champions[key]=spec
    if set(bindings['champions'])-set(champions):raise UnsupportedRule('binding entity missing from release')
    items={r['api_name']:compile_item(r,bindings['items']) for r in catalogs['items']['items']}
    if set(bindings['items']['entities'])-set(items):raise UnsupportedRule('bound item missing from release')
    recipes={'+'.join(sorted(r['composition'])):r['api_name'] for r in catalogs['items']['items']
             if len(r['composition'])==2 and items[r['api_name']].get('combat_handler')=='effects'}
    traits={r['api_name']:compile_trait(r,bindings['traits']) for r in catalogs['traits']['traits']}
    if set(bindings['traits']['entities'])-set(traits):raise UnsupportedRule('bound trait missing from release')
    report=dict(abilities=dict(scope=deepcopy(bindings.get('ability_scope',{})),total=len(champions),inventoried=sum(k in bindings['champions'] for k in champions),
                candidate_programs=sum(v.get('ability_status')=='candidate_not_replay_validated' for v in champions.values()),
                replay_validated=0,blocked={k:v.get('ability_blockers',[]) for k,v in champions.items() if v.get('ability_status')=='blocked'},
                role_integration_pending=sorted(k for k,v in champions.items() if v.get('ability_program') and v.get('unsupported')),
                all_abilities_ready=False),
                champions=dict(total=len(champions),candidate_effects=sum(not v.get('unsupported') for v in champions.values()),
                              replay_validated=0,missing_handlers=sorted(k for k,v in champions.items() if v.get('unsupported'))),
                items=dict(global_catalog_total=len(items),set_membership_verified=False,
                           candidate_effects=sum(v.get('combat_handler')=='effects' for v in items.values()),replay_validated=0),
                traits=dict(total=len(traits),candidate_effects=sum(t['status']=='candidate_not_replay_validated' for t in traits.values()),replay_validated=0,
                            tier_total=sum(len(t['tiers']) for t in traits.values()),
                            candidate_tiers=sum(not tier.get('unsupported') for t in traits.values() for tier in t['tiers']),
                            partial_handlers=sorted(k for k,t in traits.items() if t['status']=='missing_handler' and any(not tier.get('unsupported') for tier in t['tiers'])),
                            missing_handlers=sorted(k for k,t in traits.items() if t['status']=='missing_handler')),
                unresolved=bindings['unresolved'],current_patch_training_ready=False,runtime_promoted=False,
                full_match_ready=False,augments_ready=False,seasonal_events_ready=False)
    return dict(schema_version=3,combat_version=2,scope='experimental_hex_lab',patch=bindings['patch'],
                release_sha256=manifest['release_sha256'],bindings_sha256=hashlib.sha256(canonical(bindings)).hexdigest(),
                champions=champions,items=items,traits=traits,augments={},recipes=recipes,
                data_components=deepcopy(bindings['components']),
                lab_sampling=deepcopy(profile['lab_sampling']),
                combat_rules=deepcopy(profile['timing_profile']['combat_rules']),coverage=report)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release',type=Path,required=True)
    p.add_argument('--bindings',type=Path,default=Path('configs/simulation/seasons/TFTSet18/18.3/manifest.json'))
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();manifest,catalogs=read_release(a.release)
    result=compile_catalog(manifest,catalogs,load_bindings(a.bindings))
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(canonical(result))
    print(json.dumps(result['coverage'],indent=2))


if __name__=='__main__':main()
