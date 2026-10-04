"""Bind a sealed seasonal catalog to explicit, opt-in candidate effect rules.

Never scrape descriptions into executable code or drop unknown active effects.
The report distinguishes numeric availability, implemented templates and actual
replay validation. A successful build is not a current-patch training approval.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from ingestion.knowledge_release import read_release, canonical
from trainer.simulation.event_combat import validate_effects
from trainer.simulation.state import UnsupportedRule


def terms(value,stat=None,owner='source'):
    return [dict(coefficient=value,**(dict(stat=stat,owner=owner) if stat else {}))]


def modifier(stat,value,mode='flat'):
    return dict(stat=stat,value=value,mode=mode)


def stat_effect(stat,value,mode='flat'):
    return dict(op='stat',target={'kind':'self'},stat=stat,mode=mode,amount=terms(value))


COMPONENTS=('BFSword','NeedlesslyLargeRod','RecurveBow','TearOfTheGoddess','ChainVest',
            'NegatronCloak','GiantsBelt','SparringGloves','FryingPan')
ITEMS=COMPONENTS+('WarmogsArmor','ArchangelsStaff','GuinsoosRageblade','SpearOfShojin',
                  'Bloodthirster','RabadonsDeathcap','Deathblade','Crownguard')
BASE_FIELDS={'AD':('ad','base_pct',1),'AP':('ap','flat',1),'AS':('attack_speed','base_pct',.01),
             'ManaRegen':('mana_per_second','flat',1),'Armor':('armor','flat',1),
             'MagicResist':('mr','flat',1),'Health':('hp','flat',1),
             'CritChance':('crit_chance','flat',.01),'StatOmnivamp':('omnivamp','flat',1),
             'BonusDamage':('damage_amp','flat',1),'BonusPercentHP':('hp','bonus_pct',1)}
ITEM_EXTRA_FIELDS={
    'ArchangelsStaff':{'APPerInterval','IntervalSeconds'},'GuinsoosRageblade':{'AttackSpeedPerStack'},
    'SpearOfShojin':{'FlatManaRestore'},'Bloodthirster':{'LifeSteal','HealthThreshold','ShieldHealthPercent','ShieldDuration'},
    'RabadonsDeathcap':{'{1543aa48}'},'Deathblade':{'{1543aa48}'},
    'Crownguard':{'ShieldSize','ShieldDuration','ShieldBonusAP'}}


def compile_item(row):
    short=row['api_name'].removeprefix('TFT_Item_');v=row['effects']
    if short not in ITEMS:return dict(unsupported=True,name=row['name'],reason='effect binding missing')
    if set(v)-set(BASE_FIELDS)-ITEM_EXTRA_FIELDS.get(short,set()):
        raise UnsupportedRule(f'unreviewed item numeric fields: {row["api_name"]}')
    mods=[modifier(stat,v[key]*scale,mode) for key,(stat,mode,scale) in BASE_FIELDS.items() if key in v]
    hooks=[]
    if short in ('Deathblade','RabadonsDeathcap') and abs(v['{1543aa48}']-v['BonusDamage'])>1e-6:
        raise UnsupportedRule('damage alias disagrees; do not apply twice')
    if short=='ArchangelsStaff':
        hooks=[dict(event='periodic',interval=v['IntervalSeconds'],effects=[stat_effect('ap',v['APPerInterval'])])]
    elif short=='GuinsoosRageblade':
        hooks=[dict(event='periodic',interval=1,effects=[stat_effect('attack_speed',v['AttackSpeedPerStack']/100,'base_pct')])]
    elif short=='SpearOfShojin':mods.append(modifier('mana_per_attack',v['FlatManaRestore']))
    elif short=='Bloodthirster':
        if abs(v['LifeSteal']/100-v['StatOmnivamp'])>1e-6:raise UnsupportedRule('omnivamp aliases disagree')
        hooks=[dict(event='health_below',threshold=v['HealthThreshold']/100,limit=1,effects=[
            dict(op='shield',target={'kind':'self'},amount=terms(v['ShieldHealthPercent']/100,'hp'),duration=v['ShieldDuration'])])]
    elif short=='Crownguard':
        hooks=[dict(event='combat_start',effects=[dict(op='shield',key='crown',target={'kind':'self'},
                    amount=terms(v['ShieldSize']/100,'hp'),duration=v['ShieldDuration'])]),
               dict(event='shield_end',shield_key='crown',limit=1,effects=[stat_effect('ap',v['ShieldBonusAP'])])]
    for hook in hooks:validate_effects(hook['effects'])
    return dict(name=row['name'],combat_handler='effects',component=short in COMPONENTS,
                unique=row['unique'],modifiers=mods,hooks=hooks,status='candidate_not_replay_validated')


TRAIT_BINDINGS={'DA_Juggernaut18','DA_18_Spellweaver','DA_18_Rapidfire','DA_FloraFatalis18'}


def compile_trait(row):
    key=row['api_name'];tiers=[]
    for effect in row['effects']:
        v=effect['variables'];tier=dict(min=effect['min_units'],max=effect['max_units'])
        if key=='DA_Juggernaut18':
            tier.update(members_replace_team=True,team=dict(modifiers=[modifier('durability',v['{f8c73243}'])]),
                        members=dict(modifiers=[modifier('durability',v['{6eab9c5e}'])]))
        elif key=='DA_18_Spellweaver':
            tier.update(members_replace_team=True,team=dict(modifiers=[modifier('ap',100*v['TeamwideAP'])]),
                        members=dict(modifiers=[modifier('ap',100*v['{b012bed0}'])],hooks=[
                            dict(event='ally_cast',caster_trait=key,effects=[stat_effect('ap',100*v['APPerCast'])])]))
        elif key=='DA_18_Rapidfire':
            tier.update(team=dict(modifiers=[modifier('attack_speed',v['{1d98dcec}'],'base_pct')]),
                        members=dict(hooks=[dict(event='attack',limit=int(v['MaxStacks']),
                                                effects=[stat_effect('attack_speed',v['ASperAttack'],'base_pct')])]))
        elif key=='DA_FloraFatalis18':
            # Higher tier inherits the lower tier mana reward explicitly.
            mana=row['effects'][0]['variables']['Mana']
            effects=[dict(op='mana',target={'kind':'self'},amount=terms(mana))]
            if 'PercentHeal' in v:
                effects.append(dict(op='heal',target={'kind':'lowest_hp_allies','count':1},amount=terms(v['PercentHeal'],'hp','target')))
            tier.update(members=dict(hooks=[dict(event='takedown',effects=effects)]))
        else:tier['unsupported']=True
        tiers.append(tier)
    return dict(name=row['name'],tiers=tiers,status='candidate_not_replay_validated' if key in TRAIT_BINDINGS else 'missing_handler')


def compile_catalog(manifest,catalogs,bindings):
    if bindings['release_sha256']!=manifest['release_sha256'] or bindings['patch']!=manifest['tft_patch'] or bindings['set_key']!=manifest['set']['key']:
        raise UnsupportedRule('binding and sealed catalog identity differ')
    if bindings.get('status')!='candidate_not_replay_validated' or bindings.get('runtime_promoted') is not False:
        raise UnsupportedRule('candidate compiler cannot promote a release')
    trait_names={t['name']:t['api_name'] for t in catalogs['traits']['traits']}
    champions={}
    for row in catalogs['units']['champions']:
        key=row['api_name'];spec=dict(name=row['name'],cost=row['cost'],traits=[trait_names[n] for n in row['traits']])
        binding=bindings['champions'].get(key)
        if binding is None:
            spec.update(unsupported=True,reason='ability/role/timing binding missing')
        else:
            if binding['role']!='caster':raise UnsupportedRule('unverified mana role')
            v=row['stats'];missing=[k for k in ('hp','damage','armor','magicResist','attackSpeed','mana','initialMana','range','critChance','critMultiplier') if v.get(k) is None]
            if missing:raise UnsupportedRule(f'missing attributes: {key}: {missing}')
            spec.update(combat=dict(hp=[v['hp']*n for n in (1,1.8,3.24)],ad=[v['damage']*n for n in (1,1.5,2.25)],
                ap=100,armor=v['armor'],mr=v['magicResist'],attack_speed=v['attackSpeed'],range=v['range'],
                mana=v['mana'],initial_mana=v['initialMana'],mana_per_attack=7,mana_per_second=2,mana_per_damage=0,
                crit_chance=v['critChance'],crit_multiplier=v['critMultiplier']),
                spell=deepcopy(binding['spell']),hooks=deepcopy(binding.get('hooks',[])),status='candidate_not_replay_validated')
            validate_effects(spec['spell']['effects'])
        champions[key]=spec
    if set(bindings['champions'])-set(champions):raise UnsupportedRule('binding entity missing from release')
    items={r['api_name']:compile_item(r) for r in catalogs['items']['items']}
    recipes={'+'.join(sorted(r['composition'])):r['api_name'] for r in catalogs['items']['items']
             if len(r['composition'])==2 and items[r['api_name']].get('combat_handler')=='effects'}
    traits={r['api_name']:compile_trait(r) for r in catalogs['traits']['traits']}
    report=dict(champions=dict(total=len(champions),candidate_effects=sum(not v.get('unsupported') for v in champions.values()),
                              replay_validated=0,missing_handlers=sorted(k for k,v in champions.items() if v.get('unsupported'))),
                items=dict(global_catalog_total=len(items),set_membership_verified=False,
                           candidate_effects=sum(v.get('combat_handler')=='effects' for v in items.values()),replay_validated=0),
                traits=dict(total=len(traits),candidate_effects=len(TRAIT_BINDINGS),replay_validated=0,
                            missing_handlers=sorted(set(traits)-TRAIT_BINDINGS)),
                unresolved=bindings['unresolved'],current_patch_training_ready=False,runtime_promoted=False,
                full_match_ready=False,augments_ready=False,seasonal_events_ready=False)
    return dict(schema_version=2,combat_version=2,scope='experimental_hex_lab',patch=bindings['patch'],
                release_sha256=manifest['release_sha256'],bindings_sha256=hashlib.sha256(canonical(bindings)).hexdigest(),
                champions=champions,items=items,traits=traits,augments={},recipes=recipes,
                combat_rules=deepcopy(bindings['timing_profile']['combat_rules']),coverage=report)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release',type=Path,required=True)
    p.add_argument('--bindings',type=Path,default=Path('configs/simulation/set18-effects-bindings-v1.json'))
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();manifest,catalogs=read_release(a.release)
    result=compile_catalog(manifest,catalogs,json.loads(a.bindings.read_text()))
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(canonical(result))
    print(json.dumps(result['coverage'],indent=2))


if __name__=='__main__':main()
