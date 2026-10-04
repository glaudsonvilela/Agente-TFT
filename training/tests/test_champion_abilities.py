"""Ability-only fixtures: these are NOT whole-match or replay accuracy tests."""
from copy import deepcopy
from pathlib import Path
import json
import pytest

from ingestion.simulation_bindings import load_bindings
from trainer.simulation.event_combat import Battle,validate_effects
from trainer.simulation.state import Unit,UnsupportedRule
from training.tests.test_event_combat import content,players,amount

PACK=Path(__file__).resolve().parents[2]/'configs/simulation/seasons/TFTSet18/18.3/manifest.json'
RULES=load_bindings(PACK)['champions']
PROGRAMS=[k for k,v in RULES.items() if 'spell' in v]


def sandbox(key,stars=1,allies=1,enemies=1):
    c=content();p=players();p[0].level=allies;p[1].level=enemies
    c['champions']['actor']=deepcopy(c['champions']['fixture'])
    spec=c['champions']['actor'];spec.update({k:deepcopy(RULES[key][k]) for k in ('spell','hooks','identity') if k in RULES[key]})
    for row in c['champions'].values():
        row['combat'].update(hp=100000,ad=0,mana=100000,initial_mana=0,mana_per_attack=0,mana_per_second=0,crit_chance=0,range=7)
    p[0].units=[Unit('a','actor',stars=stars,zone='board',position=(0,3))]+[
        Unit(f'ally{i}','fixture',zone='board',position=(0,i)) for i in range(allies-1)]
    p[1].units=[Unit(f'enemy{i}','fixture',zone='board',position=(0,i)) for i in range(enemies)]
    b=Battle(p,c,trace=True);a=b.units[0];z=b.by_id['enemy0'];a.casts=1
    return b,a,z


def cast(b,a,z):b.effects(a,z,a.spell['effects'])


@pytest.mark.parametrize('key',PROGRAMS)
@pytest.mark.parametrize('stars',[1,2,3])
def test_program_executes_with_explicit_sandbox_stats(key,stars):
    b,a,z=sandbox(key,stars,allies=4,enemies=4)
    a.tags={'shared'};b.units[1].tags={'shared'}
    a.hp-=5000
    validate_effects(a.spell['effects']);cast(b,a,z)
    b.duration=3;b.run()
    assert all(u.hp>=0 for u in b.units)


def test_no_blocked_ability_gets_a_generic_fallback():
    assert len(RULES)==74
    for key,r in RULES.items():
        if r['ability_status']=='blocked':assert r['blockers'] and 'spell' not in r,key
        assert r['replay_validated'] is False


def test_soraka_marks_are_per_target_and_per_caster():
    b,a,z=sandbox('DA_18_Soraka',enemies=2)
    cast(b,a,z);assert z.hp==99775
    cast(b,a,z);assert z.hp==99250
    other=b.by_id['enemy1'];cast(b,a,other);assert other.hp==99775
    z.marks={("different-caster",'star')};cast(b,a,z);assert z.hp==99025


def test_diana_six_orbs_total_not_six_per_enemy_and_flat_shield():
    b,a,z=sandbox('DA_18_Diana',enemies=3)
    for i,u in enumerate(b.units[1:]):u.position=(4,i+2)
    a.values.base['ap']=200
    cast(b,a,z)
    assert a.shields[0].amount==150
    assert sum(100000-u.hp for u in b.units[1:])==900
    assert all(u.hp==99700 for u in b.units[1:])


def test_hecarim_stun_star_scaling_and_resistance_expiry():
    b,a,z=sandbox('DA_18_Hecarim',3,enemies=4)
    cast(b,a,z)
    assert b.get(a,'armor')==50 and b.get(a,'mr')==50
    assert sum(bool(b.status(u,'stun')) for u in b.units[1:])==3
    assert max(b.status(u,'stun') for u in b.units[1:])==1.75
    b.now=3;assert b.get(a,'armor')==0


def test_fiddlesticks_drain_total_heal_not_multiplied_by_target_count():
    b,a,z=sandbox('DA_Fiddlesticks18',enemies=4);a.hp=90000
    cast(b,a,z);b.duration=2;b.run()
    assert a.hp==90410
    assert sum(b.get(u,'mr')==-10 for u in b.units[1:])==3


def test_azir_replaces_six_attacks_then_removes_as_bonus():
    b,a,z=sandbox('DA_18_Azir');a.values.base['ad']=100
    cast(b,a,z);assert b.get(a,'attack_speed')==2.5
    # Execute exactly six attack releases, without invoking a fabricated seasonal role.
    b.duration=2.39;b.run()
    hits=[e for e in b.history if e['kind']=='damage' and e['source']=='a']
    assert a.attacks==6
    assert len(hits)==12 and all(e['amount']==46 and e['tag']=='spell' for e in hits)
    assert not a.empowers and b.get(a,'attack_speed')==1


def test_shen_ally_keeps_attack_and_uses_shens_ap_for_bonus():
    b,a,z=sandbox('DA_18_Shen',allies=2);ally=b.units[1]
    ally.position=(3,2);ally.hp-=100;a.values.base['ap']=200;ally.values.base['ap']=10;ally.values.base['ad']=11
    cast(b,a,z)
    assert [s.amount for s in a.shields]==[700]
    assert [s.amount for s in ally.shields]==[400]
    assert len(ally.empowers)==1
    b.duration=.3;b.run()
    damages=[e for e in b.history if e['kind']=='damage']
    assert any(e['source']==ally.uid and e['amount']==11 for e in damages)
    assert any(e['source']==a.uid and e['amount']==70 for e in damages)


def test_nidalee_third_javelin_selects_least_items_then_farthest():
    b,a,z=sandbox('DA_Nidalee18_AP',enemies=3)
    z.item_count=3;b.units[-1].position=(7,6);b.units[-1].item_count=0
    cast(b,a,z);b.duration=1.0;b.run()
    hits=[e for e in b.history if e['kind']=='damage' and e['source']=='a']
    assert a.attacks==3
    assert [e['amount'] for e in hits]==[170,170,330]
    assert hits[-1]['target']==b.units[-1].uid


def test_ivern_shield_critical_and_stack_only_after_six_casts():
    b,a,z=sandbox('DA_18_Ivern',allies=3)
    a.values.base['precision']=1;a.values.base['crit_chance']=1
    cast(b,a,z)
    assert sum(len(u.shields) for u in b.units if u.team==0)==2
    assert a.shields[0].amount==pytest.approx(185*1.4)
    a.casts=6;cast(b,a,z);assert b.get(a,'attack_speed')==1
    a.casts=7;cast(b,a,z);assert b.get(a,'attack_speed')==2
    cast(b,a,z);assert b.get(a,'attack_speed')==3
    assert b.get(a,'damage_amp')==.1
    b.now=6;assert b.get(a,'damage_amp')==0


def test_lux_freezes_line_hits_and_applies_falloff_once_per_target():
    b,a,z=sandbox('DA_Lux18_Blossom',enemies=3)
    a.position=(0,3)
    for i,u in enumerate(b.units[1:]):u.position=(2+2*i,3)
    cast(b,a,z)
    assert [100000-u.hp for u in b.units[1:]]==[412.5,281.25,187.5]


def test_lux_shared_trait_mana_and_unique_three_star_identity():
    b,a,z=sandbox('DA_18_Lux_Sunbeam',allies=3)
    a.tags={'x'};a.stars=3;b.units[1].tags={'x'};b.units[2].tags={'y'}
    b.units[1].stars=3;b.units[2].stars=3
    cast(b,a,z)
    assert (a.mana,b.units[1].mana,b.units[2].mana)==(100,100,0)
    # Two copies of fixture count once, plus Lux itself: +30%.
    assert 100000-z.hp==pytest.approx(6500*1.3)


def test_lux_fae_heals_from_actual_damage_not_raw_ap():
    b,a,z=sandbox('DA_18_Lux_Fae');a.hp=90000;z.values.base['mr']=100
    cast(b,a,z)
    assert a.hp==pytest.approx(90000+187.5*.18)


def test_cleanse_invalidates_delayed_stun_recovery():
    b,a,z=sandbox('DA_18_Soraka')
    b.effects(z,a,[dict(op='status',name='stun',duration=2)])
    version=a.version
    b.effects(a,a,[dict(op='cleanse',statuses=['stun','root'])])
    assert not b.status(a,'stun') and a.version==version+1


def test_invalid_nested_effect_and_unavailable_context_fail_closed():
    with pytest.raises(UnsupportedRule):validate_effects([dict(op='sequence',effects=[dict(op='guess')])])
    b,a,z=sandbox('DA_18_Soraka')
    with pytest.raises(UnsupportedRule):b.effects(a,z,[dict(op='heal',amount=[dict(coefficient=1,context='damage')])])

@pytest.mark.parametrize('key,stat,value',[
    ('DA_18_Lux_Coven','armor',-8),('DA_18_Lux_Coven','mr',-8),
    ('DA_18_Lux_Moonbeam','vulnerable',.08)])
def test_lux_enemy_debuff_variants(key,stat,value):
    b,a,z=sandbox(key);cast(b,a,z);assert b.get(z,stat)==value
    if stat=='vulnerable':b.now=4;assert b.get(z,stat)==0


def test_lux_blackthorn_primal_elderwood_and_inferno():
    b,a,z=sandbox('DA_Lux18_Blackthorn');cast(b,a,z);assert b.status(z,'stun')==1
    b,a,z=sandbox('DA_18_Lux_Primal');cast(b,a,z);cast(b,a,z)
    assert b.get(a,'attack_speed')==1.6
    b.now=6;assert b.get(a,'attack_speed')==1
    b,a,z=sandbox('DA_18_Lux_Elderwood',allies=2);cast(b,a,z);cast(b,a,z)
    assert all(b.get(u,'hp')==105000 for u in b.units[:2])
    b,a,z=sandbox('DA_18_Lux_Inferno');z.hp=1;cast(b,a,z);assert a.mana==10


def test_empower_refresh_does_not_stack_or_leak_modifiers():
    b,a,z=sandbox('DA_18_Azir')
    for _ in range(100):cast(b,a,z)
    assert len(a.empowers)==1 and len(a.values.modifiers)==1
    assert b.get(a,'attack_speed')==2.5
    b.duration=2.39;b.run();assert not a.empowers and not a.values.modifiers


def test_roleless_program_cannot_silently_enter_a_real_catalog_battle():
    from ingestion.knowledge_release import read_release
    from training.compile_effects import compile_catalog
    pack=load_bindings(PACK);release=PACK.parents[5]/'knowledge/releases/TFTSet18/18.3'/pack['release_sha256']
    if not release.exists():pytest.skip('sealed catalog absent in CI')
    manifest,catalog=read_release(release);compiled=compile_catalog(manifest,catalog,pack)
    assert compiled['champions']['DA_18_Diana']['ability_program']
    assert compiled['champions']['DA_18_Diana']['unsupported']
    p=players();p[0].units[0].champion='DA_18_Diana'
    p[1].units[0].champion='DA_18_Veigar'
    with pytest.raises(UnsupportedRule):Battle(p,compiled)
