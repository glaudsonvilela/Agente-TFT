import copy
import unittest
import json
from pathlib import Path

from trainer.simulation.state import Action, IllegalAction, Offer, Player, Unit, World, UnsupportedRule, apply
from trainer.simulation.hexgrid import distance, neighbors, next_step, global_hex
from trainer.simulation.combat import simulate, materialize, mitigation
from trainer.simulation.search import search
from trainer.simulation.match import new_match, begin_round, resolve_round, play


def fixture():
    stats = dict(hp=[100,180,324], ad=[20,30,45], ap=100, armor=0, mr=0,
                 attack_speed=1, range=1, mana=30, initial_mana=0, mana_per_attack=10,
                 mana_per_second=0, mana_per_damage=0, crit_chance=0, crit_multiplier=1.4)
    champion = dict(cost=1, sale_prices={'1':1,'2':3,'3':9}, combat=stats, traits=[], spell={'kind':'none'})
    return dict(scope='experimental_hex_lab', champions={'fixture':champion},
                items={'sword':dict(component=True, combat_handler='stats', bonuses={'ad':10}),
                       'blade':dict(combat_handler='stats', bonuses={'ad':25})}, recipes={'sword+sword':'blade'},
                economy=dict(inventory_slots=10, xp_cost=4, xp_amount=4, xp_to_next={'1':2,'2':6},
                             reroll_cost=2, shop_odds={'1':[1,0,0,0,0],'2':[1,0,0,0,0]}),
                combat_rules=dict(duration=30, move_seconds=.25, first_action_seconds=.1, attack_speed_cap=5))


class Planning(unittest.TestCase):
    def setUp(self): self.content = fixture()

    def test_full_bench_merge_uses_existing_slot_and_keeps_original(self):
        units = [Unit(f'z{i}', 'fixture', position=(i,), stars=1 if i<2 else 2) for i in range(9)]
        world = World([Player(3,1,0,units=units,shop=[Offer('champion','fixture',1)]+[None]*4)], {'fixture':10})
        before = copy.deepcopy(world)
        after = apply(world,0,Action('buy',(0,)),self.content)
        self.assertEqual(world,before)
        self.assertEqual(after.players[0].gold,2)
        self.assertEqual(sum(3**(u.stars-1) for u in after.players[0].units),24)
        self.assertTrue(all(u.position[0] < 9 for u in after.players[0].units))

    def test_failed_purchase_preserves_rng_resources(self):
        world=World([Player(0,1,0,shop=[Offer('champion','fixture',1)]+[None]*4)], {'fixture':10})
        original=copy.deepcopy(world)
        with self.assertRaises(IllegalAction): apply(world,0,Action('buy',(0,)),self.content)
        self.assertEqual(world,original)

    def test_shared_pool_conservation_and_reproducible_reroll(self):
        world=World([Player(10,1,0),Player(10,1,0)],{'fixture':7},seed=53)
        a=apply(world,0,Action('reroll'),self.content)
        self.assertEqual(a,apply(world,0,Action('reroll'),self.content))
        b=apply(a,1,Action('reroll'),self.content)
        self.assertEqual(b.pool['fixture'],0)
        self.assertEqual(sum(x is not None for x in b.players[1].shop),2)
        c=apply(b,0,Action('buy',(0,)),self.content)
        d=apply(c,0,Action('sell',(c.players[0].units[0].uid,)),self.content)
        self.assertEqual(d.pool['fixture']+sum(o is not None for p in d.players for o in p.shop),7)

    def test_item_recipe_and_xp_carry(self):
        world=World([Player(10,1,0,units=[Unit('u','fixture')],inventory=['sword','sword'])],{'fixture':5})
        with self.assertRaises(UnsupportedRule): apply(world,0,Action('combine',(0,1)),self.content)
        world=apply(world,0,Action('equip',(0,'u')),self.content)
        world=apply(world,0,Action('equip',(0,'u')),self.content)
        self.assertEqual(world.players[0].units[0].items,['blade'])
        world=apply(world,0,Action('xp'),self.content)
        self.assertEqual((world.players[0].level,world.players[0].xp),(2,2))

    def test_swap_board_and_bench_at_unit_cap(self):
        world=World([Player(0,1,0,units=[Unit('a','fixture',zone='board',position=(0,0)),Unit('b','fixture')])],{})
        result=apply(world,0,Action('move',('b','board',(0,0))),self.content)
        self.assertEqual([(u.uid,u.zone,u.position) for u in result.players[0].units],
                         [('a','bench',(0,)),('b','board',(0,0))])


class Hexes(unittest.TestCase):
    def test_distance_rotation_and_neighbors(self):
        for r in range(8):
            for c in range(7):
                a=(r,c)
                for b in neighbors(a):
                    self.assertEqual(distance(a,b),1)
                    self.assertIn(a,neighbors(b))
                    self.assertEqual(distance(a,b),distance((7-r,6-c),(7-b[0],6-b[1])))
        self.assertEqual(global_hex(0,(0,3)),(3,3))
        self.assertEqual(global_hex(1,(0,3)),(4,3))

    def test_blocked_path_does_not_teleport(self):
        a=(2,2); b=(6,4)
        self.assertEqual(next_step(a,b,1,set(neighbors(a))),a)
        step=next_step(a,b,1,set())
        self.assertEqual(distance(a,step),1)


class Combat(unittest.TestCase):
    def players(self):
        return [Player(0,1,0,units=[Unit('a','fixture',zone='board',position=(0,3))]),
                Player(0,1,0,units=[Unit('b','fixture',zone='board',position=(0,3))])]

    def test_exact_attack_damage_and_no_input_mutation(self):
        content=fixture(); players=self.players(); players[0].units[0].items=['blade']
        original=copy.deepcopy(players)
        a=simulate(players,content,seed=17,trace=True)
        self.assertEqual(a,simulate(players,content,seed=17,trace=True))
        self.assertEqual(players,original)
        self.assertEqual(a['winner'],0)
        self.assertEqual(a['units'][0]['attacks'],3)
        self.assertEqual(a['units'][0]['damage_dealt'],100)
        self.assertEqual(mitigation(100),.5)

    def test_separate_star_progressions(self):
        players=self.players();players[0].units[0].stars=2
        unit=materialize(players,fixture())[0]
        self.assertEqual(unit.hp,180)
        self.assertEqual(unit.stats['ad'],30)

    def test_spell_and_dot_use_mana_and_resistance(self):
        for kind in ('target_damage','target_dot'):
            content=fixture(); champion=content['champions']['fixture']
            champion['combat']['initial_mana']=30
            champion['spell']=dict(kind=kind,amount=[100,150,225],scaling='ap',damage_type='magic',
                                   cast_seconds=.2,duration=2,ticks=4)
            result=simulate(self.players(),content,seed=4,trace=True)
            self.assertTrue(any(e['kind']=='cast' for e in result['events']))
            self.assertTrue(any(e['kind']=='damage' and e['damage_type']=='magic' for e in result['events']))

    def test_unknown_effects_fail_instead_of_generic_bonus(self):
        players=self.players(); content=fixture()
        content['champions']['fixture']['traits']=['unimplemented']
        with self.assertRaises(UnsupportedRule): simulate(players,content)
        content=fixture();players[0].units[0].items=['sword']
        content['items']['sword']['combat_handler']='stacking_proc'
        with self.assertRaises(UnsupportedRule): simulate(players,content)


class Search(unittest.TestCase):
    def test_planning_search_prefers_buy_when_evaluator_rewards_it(self):
        content=fixture()
        world=World([Player(1,1,0,shop=[Offer('champion','fixture',1)]+[None]*4)],{'fixture':10})
        result=search(world,0,content,lambda w,seed: 1 if w.players[0].units else -1,
                      simulations=100,seconds=10,depth=1,positions=False,seed=9)
        self.assertEqual(result['action'],Action('buy',(0,)))
        self.assertEqual(result['simulation_paths'],100)
        self.assertEqual(result['complete_matches'],0)
        self.assertFalse(world.players[0].units)


class Match(unittest.TestCase):
    def content(self):
        return json.loads((Path(__file__).resolve().parents[2]/'configs/simulation/hex-lab-v1.json').read_text())

    def test_elimination_releases_all_reserved_shops_atomically(self):
        content=self.content();content['match_rules']['starting_hp']=2
        world=new_match(content,7);original=copy.deepcopy(world)
        reserved=begin_round(world,content)
        self.assertEqual(world,original)
        self.assertEqual(sum(reserved.pool.values()),sum(world.pool.values())-40)
        result,record=resolve_round(reserved,content,17)
        self.assertEqual(result.pool,world.pool)
        self.assertEqual(len(record['eliminated']),8)

    def test_eight_player_game_finishes_reproducibly(self):
        content=self.content()
        first=play(content,19)
        self.assertEqual(first,play(content,19))
        self.assertTrue(first['completed'])
        self.assertEqual(len(first['placements']),8)
        self.assertEqual(sum(first['placements'].values()),36)


if __name__ == '__main__': unittest.main()
