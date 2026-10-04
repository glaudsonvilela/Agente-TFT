from copy import deepcopy
import unittest

from trainer.simulation.combat import simulate
from trainer.simulation.event_combat import Battle
from trainer.simulation.modifiers import Stats
from trainer.simulation.state import Player,Unit,UnsupportedRule
from trainer.simulation.traits import active_traits,contributions
from trainer.simulation.match import resolve_round
from trainer.simulation.state import World
from training.tests.test_hex_simulator import fixture


def content():
    c=fixture();c['combat_version']=2
    c['combat_rules'].update(attack_windup_fraction=.25,projectile_hexes_per_second=0,max_events=10000)
    c['items']={};c['traits']={};c['augments']={}
    return c


def players():
    return [Player(0,1,0,units=[Unit('a','fixture',zone='board',position=(0,3))]),
            Player(0,1,0,units=[Unit('b','fixture',zone='board',position=(0,3))])]


def amount(n):return [{'coefficient':n}]


class Layers(unittest.TestCase):
    def test_base_percentage_does_not_compound_item_order(self):
        a=Stats(dict(ad=100))
        a.add('sword','ad',.1,'base_pct');a.add('sword2','ad',.1,'base_pct')
        self.assertAlmostEqual(a.get('ad'),120)
        a.add('flat','ad',20);self.assertEqual(a.get('ad'),140)

    def test_strongest_debuff_falls_back_when_it_expires(self):
        stats=Stats(dict(wound=0))
        stats.add('weak','wound',.2,expires=10,group='wound',strongest=True)
        stats.add('strong','wound',.5,expires=2,group='wound',strongest=True)
        self.assertEqual(stats.get('wound',1),.5)
        self.assertEqual(stats.get('wound',2),.2)
        self.assertEqual(stats.get('wound',10),0)


class Traits(unittest.TestCase):
    def test_duplicates_bench_and_emblem_do_not_inflate_trait(self):
        c=content();c['champions']['fixture']['traits']=['x'];c['champions']['second']=deepcopy(c['champions']['fixture'])
        c['champions']['second']['traits']=[]
        c['items']['emblem']={'grants_traits':['x']}
        c['traits']['x']={'tiers':[{'min':2,'members':{'modifiers':[{'stat':'armor','mode':'flat','value':25}]}}]}
        p=Player(0,4,0,units=[Unit('a','fixture',zone='board',position=(0,0)),
                            Unit('b','fixture',zone='board',position=(0,1)),
                            Unit('c','second',items=['emblem'])])
        self.assertEqual(active_traits(p,c),[])
        p.units[2].zone='board';p.units[2].position=(0,2)
        traits=active_traits(p,c)
        self.assertEqual(traits[0]['count'],2)
        rows,_=contributions(p,c);self.assertEqual(len(rows['b']['modifiers']),1)

    def test_unknown_active_trait_rejected_but_inactive_is_allowed(self):
        c=content();c['champions']['fixture']['traits']=['x']
        c['traits']['x']={'unsupported':True,'tiers':[{'min':2}]}
        self.assertEqual(active_traits(players()[0],c),[])
        c['traits']['x']['tiers'][0]['min']=1
        with self.assertRaises(UnsupportedRule):active_traits(players()[0],c)


class Effects(unittest.TestCase):
    def battle(self,c=None):return Battle(players(),c or content(),seed=7,trace=True)

    def test_damage_shield_wound_heal_and_omnivamp(self):
        b=self.battle();a,z=b.units;a.hp=50
        a.values.add('vamp','omnivamp',.5)
        b.effects(a,z,[dict(op='shield',amount=amount(10),duration=2)])
        self.assertEqual(b.hit(a,z,30,'physical','spell'),20)
        self.assertEqual(a.hp,60)
        z.values.add('wound','wound',.5)
        self.assertEqual(b.heal(a,z,20),10)
        self.assertEqual(z.hp,90)

    def test_periodic_hooks_keep_their_individual_clocks(self):
        c=content();c['champions']['fixture']['hooks']=[
            dict(event='periodic',interval=1,limit=2,effects=[dict(op='stat',target={'kind':'self'},stat='ap',amount=amount(3))]),
            dict(event='periodic',interval=3,limit=1,effects=[dict(op='stat',target={'kind':'self'},stat='ap',amount=amount(7))])]
        c['combat_rules']['duration']=3.1
        b=self.battle(c);b.run()
        self.assertEqual(b.units[0].values.get('ap',3.1),113)

    def test_stun_interrupts_cast_and_immunity_prevents_it(self):
        b=self.battle();a,z=b.units
        effect=dict(op='status',name='stun',duration=2)
        b.effects(a,z,[effect]);self.assertEqual(z.version,1);self.assertEqual(b.status(z,'stun'),2)
        a.values.add('qss','cc_immune',1)
        b.effects(z,a,[effect]);self.assertEqual(a.version,0);self.assertEqual(b.status(a,'stun'),0)

    def test_death_summon_and_permanent_spell_kill(self):
        c=content();c['champions']['child']=deepcopy(c['champions']['fixture'])
        c['champions']['fixture']['hooks']=[dict(event='death',effects=[dict(op='summon',target={'kind':'self'},champion='child',count=1)]),
            dict(event='kill',damage_tag='spell',effects=[dict(op='permanent_stat',target={'kind':'self'},stat='ap',amount=amount(2))])]
        b=self.battle(c);a,z=b.units
        b.hit(a,z,1000,'true','spell')
        self.assertEqual(a.permanent_delta,{'ap':2})
        self.assertEqual(len(b.units),3)
        self.assertEqual(b.units[-1].team,1)
        self.assertNotEqual(b.units[-1].position,a.position)

    def test_on_attack_trigger_limit(self):
        c=content();c['champions']['fixture']['hooks']=[dict(event='attack',limit=2,effects=[
            dict(op='stat',target={'kind':'self'},stat='attack_speed',mode='base_pct',amount=amount(.1))])]
        b=self.battle(c);a,z=b.units
        for _ in range(5):b.hook('attack',a,z)
        self.assertAlmostEqual(b.get(a,'attack_speed'),1.2)

    def test_active_augment_applies_to_whole_team(self):
        c=content();c['augments']['armor']={'modifiers':[{'stat':'armor','value':40,'mode':'flat'}]}
        p=players();p[0].augments=['armor']
        b=Battle(p,c);self.assertEqual(b.get(b.units[0],'armor'),40)
        self.assertEqual(b.get(b.units[1],'armor'),0)

    def test_periodic_damage_snapshots_ability_power(self):
        b=self.battle();a,z=b.units
        b.effects(a,z,[dict(op='over_time',duration=2,ticks=2,scaling_time='snapshot',stacking='stack',effects=[
            dict(op='damage',amount=[dict(coefficient=.1,stat='ap')],damage_type='magic')])])
        a.values.add('later_ap','ap',100)
        # Check the frozen scheduled amount directly before combat starts.
        payload=b.queue[0][-1]
        self.assertEqual(payload['effects'][0]['amount'],amount(10))

    def test_trace_and_input_immutability(self):
        c=content();p=players();original=deepcopy(p)
        a=simulate(p,c,seed=42,trace=True)
        self.assertEqual(a,simulate(p,c,seed=42,trace=True))
        self.assertEqual(p,original);self.assertTrue(a['events'])

    def test_mana_overflow_is_carried_and_lock_blocks_generation(self):
        c=content();spec=c['champions']['fixture']
        spec['combat'].update(initial_mana=35,mana_per_second=10,hp=[1000,1800,3240])
        spec['spell']=dict(kind='effects',cast_seconds=.5,mana_lock_seconds=1,effects=[])
        c['combat_rules'].update(first_action_seconds=0,duration=.75)
        b=self.battle(c);b.run()
        self.assertEqual(b.units[0].mana,5)
        b.gain_mana(b.units[0],7);self.assertEqual(b.units[0].mana,5)
        b.now=1;b.gain_mana(b.units[0],7);self.assertEqual(b.units[0].mana,12)

    def test_crownguard_does_not_proc_from_another_item_shield(self):
        c=content();c['combat_rules']['duration']=2.1
        c['items']['crown']=dict(combat_handler='effects',hooks=[
            dict(event='combat_start',effects=[dict(op='shield',key='crown',target={'kind':'self'},amount=amount(1000),duration=2)]),
            dict(event='shield_end',shield_key='crown',limit=1,effects=[dict(op='stat',target={'kind':'self'},stat='ap',amount=amount(25))])])
        p=players();p[0].units[0].items=['crown','crown']
        b=Battle(p,c);a,z=b.units
        b.effects(a,a,[dict(op='shield',amount=amount(1),duration=.2)])
        b.run();self.assertEqual(a.values.get('ap',b.now),150)

    def test_spell_stun_cancels_pending_cast(self):
        c=content();c['champions']['stunner']=deepcopy(c['champions']['fixture'])
        c['champions']['fixture']['spell']=dict(kind='effects',cast_seconds=1,effects=[dict(op='damage',amount=amount(1000),damage_type='true')])
        c['champions']['stunner']['spell']=dict(kind='effects',cast_seconds=.1,effects=[dict(op='status',name='stun',duration=2)])
        for spec in c['champions'].values():spec['combat']['initial_mana']=30
        p=players();p[1].units[0].champion='stunner';c['combat_rules']['duration']=1.5
        result=simulate(p,c,trace=True)
        self.assertFalse(any(e['kind']=='damage' and e.get('tag')=='spell' for e in result['events']))

    def test_launched_projectiles_can_produce_simultaneous_death(self):
        c=content();c['champions']['fixture']['combat'].update(ad=[100,150,225],range=4)
        result=simulate(players(),c,seed=9)
        self.assertIsNone(result['winner'])
        self.assertEqual([u['health'] for u in result['units']],[0,0])

    def test_dot_keeps_running_after_caster_death_with_an_ally_alive(self):
        c=content();c['champions']['fixture']['combat']['ad']=[0,0,0]
        p=players();p[0].units.append(Unit('ally','fixture',zone='board',position=(3,3)));p[0].level=2
        b=Battle(p,c);a=b.by_id['a'];z=b.by_id['b']
        b.effects(a,z,[dict(op='over_time',duration=2,ticks=2,scaling_time='snapshot',stacking='stack',
                           effects=[dict(op='damage',amount=amount(10),damage_type='true')])])
        b.hit(z,a,1000,'true','attack');b.run()
        self.assertEqual(z.hp,80)

    def test_round_persists_kill_stacks_and_gold_without_mutating_input(self):
        c=content();c['champions']['fixture']['combat']['initial_mana']=30
        c['champions']['fixture']['spell']=dict(kind='effects',cast_seconds=.1,effects=[dict(op='damage',amount=amount(1000),damage_type='true')])
        c['champions']['fixture']['hooks']=[dict(event='kill',effects=[
            dict(op='permanent_stat',target={'kind':'self'},stat='ap',amount=amount(2)),
            dict(op='resource',target={'kind':'self'},resource='gold',amount=amount(1))])]
        c['match_rules']=dict(tie_damage=0,loss_damage=0,base_income=0,interest_cap=0,interest_step=10,natural_xp=0,
                              pairing='seeded_shuffle_with_bye',loot='none',streaks='none')
        world=World(players(),{'fixture':10});before=deepcopy(world)
        after,_=resolve_round(world,c,seed=7)
        self.assertEqual(world,before)
        self.assertEqual(sum(p.gold for p in after.players),1)
        self.assertEqual(sum(u.permanent.get('ap',0) for p in after.players for u in p.units),2)

    def test_critical_overflow_is_rejected_without_an_explicit_conversion(self):
        c=content();c['champions']['fixture']['combat']['crit_chance']=1.2
        with self.assertRaises(UnsupportedRule):self.battle(c)

    def test_frequent_burn_refresh_keeps_tick_cadence(self):
        c=content();c['champions']['fixture']['combat'].update(ad=[0,0,0],hp=[1000,1800,3240])
        c['combat_rules']['duration']=3.1
        burn=dict(op='over_time',key='burn',duration=3,ticks=3,scaling_time='snapshot',stacking='refresh_strongest',
                  group='burn',effects=[dict(op='damage',amount=amount(10),damage_type='true')])
        c['champions']['fixture']['hooks']=[dict(event='periodic',interval=.25,effects=[dict(burn,target={'kind':'nearest_enemies','count':1})])]
        b=self.battle(c);b.run()
        # First application at .25; ticks at 1.25 and 2.25 despite refreshes.
        self.assertEqual([u.hp for u in b.units],[980,980])


if __name__=='__main__':unittest.main()
