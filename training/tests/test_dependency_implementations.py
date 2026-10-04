"""Behavioral checks of economy and dynamic traits, distinct from replay parity."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from ingestion.knowledge_release import read_release
from ingestion.simulation_bindings import load_bindings
from trainer.simulation.economy import accounted_copies, new_planning_probe
from trainer.simulation.event_combat import Battle
from trainer.simulation.match import begin_round, new_match, resolve_round
from trainer.simulation.modifiers import formula
from trainer.simulation.search import search
from trainer.simulation.state import (
    Action,
    IllegalAction,
    Offer,
    Player,
    Unit,
    World,
    UnsupportedRule,
    apply,
    validate_world,
)
from training.compile_effects import compile_catalog
from training.tests.test_event_combat import content, players
from training.tests.test_hex_simulator import fixture

ROOT = Path(__file__).resolve().parents[2]


def seasonal_content():
    active = json.loads(
        (ROOT / "configs/catalog/active-knowledge-release-v1.json").read_text()
    )
    manifest, catalogs = read_release(ROOT / active["reference"])
    bindings = load_bindings(
        ROOT / "configs/simulation/seasons/TFTSet18/18.3/manifest.json"
    )
    return compile_catalog(manifest, catalogs, bindings)


class EconomyDependencies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.season = seasonal_content()

    def test_official_xp_threshold_and_carry_are_executable(self):
        w = new_planning_probe([Player(4, 7, 54)], self.season)
        result = apply(w, 0, Action("xp"), self.season)
        self.assertEqual(
            (result.players[0].level, result.players[0].xp, result.players[0].gold),
            (8, 2, 0),
        )
        self.assertEqual(w.players[0].level, 7)
        self.assertEqual(self.season["economy"]["xp_to_next"]["8"], 68)
        self.assertEqual(self.season["economy"]["xp_to_next"]["9"], 68)
        self.assertNotIn("11", self.season["economy"]["shop_odds"])

    def test_real_catalog_buy_sell_and_reroll_preserve_all_copies(self):
        world = new_planning_probe(
            [Player(100, 4, 0), Player(100, 4, 0)], self.season, 31
        )
        before = deepcopy(world)
        for seat in (0, 1):
            world = apply(world, seat, Action("reroll"), self.season)
            world = apply(world, seat, Action("buy", (0,)), self.season)
            world = apply(
                world,
                seat,
                Action("sell", (world.players[seat].units[0].uid,)),
                self.season,
            )
        self.assertEqual(accounted_copies(world, self.season), before.pool_totals)
        self.assertEqual(world.pool_totals, before.pool_totals)
        self.assertEqual(sum(1 for c in world.pool if "Lux" in c), 1)
        self.assertEqual(world.pool_totals["DA_Lux18_Base"], 9)

    def test_form_sale_and_reserved_offer_return_to_one_shared_pool(self):
        c = fixture()
        c["champions"]["variant"] = deepcopy(c["champions"]["fixture"])
        c["champions"]["variant"]["pool_identity"] = "fixture"
        c["economy"]["pool_by_cost"] = {"1": 30}
        p = Player(
            10,
            1,
            0,
            units=[Unit("owned", "variant", stars=2)],
            shop=[Offer("champion", "variant", 1)] + [None] * 4,
        )
        w = new_planning_probe([p], c)
        self.assertEqual(w.pool, {"fixture": 26})
        w = apply(w, 0, Action("sell", ("owned",)), c)
        self.assertEqual(w.pool, {"fixture": 29})
        w = apply(w, 0, Action("reroll"), c)
        self.assertEqual(w.pool, {"fixture": 25})
        self.assertTrue(all(o.entity == "fixture" for o in w.players[0].shop))
        self.assertEqual(accounted_copies(w, c), {"fixture": 30})

    def test_pool_ledger_rejects_minted_copies_and_duplicate_form_pools(self):
        w = new_planning_probe([Player(10, 1, 0)], self.season)
        w.pool["DA_Karma18"] += 1
        with self.assertRaisesRegex(IllegalAction, "conserved"):
            validate_world(w, self.season)
        w.pool["DA_Karma18"] -= 1
        w.pool["DA_18_Lux_Coven"] = 9
        with self.assertRaisesRegex(UnsupportedRule, "canonical pool"):
            validate_world(w, self.season)

    def test_incomplete_season_cannot_silently_run_as_full_match(self):
        w = new_planning_probe([Player(10, 1, 0)], self.season)
        for operation in (
            lambda: new_match(self.season, 1),
            lambda: begin_round(w, self.season),
            lambda: resolve_round(w, self.season, 1),
        ):
            with self.assertRaisesRegex(UnsupportedRule, "dependencies"):
                operation()
        w.rules_scope = "complete_rules"
        with self.assertRaisesRegex(UnsupportedRule, "dependencies"):
            apply(w, 0, Action("reroll"), self.season)

    def test_search_does_not_turn_missing_global_rules_into_hold_advice(self):
        w = new_planning_probe([Player(10, 1, 0)], self.season)
        w.rules_scope = "complete_rules"
        called = []
        with self.assertRaisesRegex(UnsupportedRule, "dependencies"):
            search(
                w, 0, self.season, lambda *_: called.append(True) or 0, simulations=1
            )
        self.assertEqual(called, [])

    def test_invalid_xp_curve_or_price_is_atomic(self):
        for key, value in (
            ("xp_cost", -4),
            ("xp_amount", True),
            ("xp_to_next", {"1": 0}),
            ("xp_to_next", {"1": -1}),
            ("xp_to_next", {"1": 2, "3": 6}),
        ):
            with self.subTest(key=key, value=value):
                c = fixture()
                c["economy"][key] = value
                w = World([Player(10, 1, 0)], {"fixture": 10})
                before = deepcopy(w)
                with self.assertRaises(UnsupportedRule):
                    apply(w, 0, Action("xp"), c)
                self.assertEqual(w, before)

    def test_eliminated_forms_and_locked_offers_return_without_new_pools(self):
        c = json.loads((ROOT / "configs/simulation/hex-lab-v1.json").read_text())
        canonical = next(iter(c["champions"]))
        c["champions"]["variant"] = deepcopy(c["champions"][canonical])
        c["champions"]["variant"]["pool_identity"] = canonical
        c["match_rules"].update(starting_hp=1, tie_damage=1)
        w = begin_round(new_match(c, 5), c)
        w.players[0].units.append(Unit("eliminated-form", "variant", stars=2))
        w.pool[canonical] -= 3
        w.players[0].shop_locked = True
        # Empty boards draw; all reservations must return on simultaneous elimination.
        before = deepcopy(w)
        after, result = resolve_round(w, c, 3)
        self.assertEqual(len(result["eliminated"]), 8)
        self.assertEqual(after.pool, after.pool_totals)
        self.assertNotIn("variant", after.pool)
        self.assertEqual(w, before)


class ContextualCombatDependencies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.season = seasonal_content()

    def battle(self, trait, count):
        c = content()
        c["traits"][trait] = deepcopy(self.season["traits"][trait])
        p = players()
        p[0].units = []
        p[0].level = count + 1
        for i in range(count):
            champion = f"member{i}"
            c["champions"][champion] = deepcopy(c["champions"]["fixture"])
            c["champions"][champion]["traits"] = [trait]
            p[0].units.append(Unit(f"m{i}", champion, zone="board", position=(0, i)))
        p[0].units.append(Unit("outsider", "fixture", zone="board", position=(3, 6)))
        p[1].level = 2
        p[1].units.append(Unit("enemy2", "fixture", zone="board", position=(3, 6)))
        return Battle(p, c, trace=True)

    def test_monolith_counts_retargeting_death_and_spell_scaling(self):
        b = self.battle("DA_18_Battlemage", 1)
        a, z, other = b.by_id["m0"], b.by_id["b"], b.by_id["enemy2"]
        self.assertEqual(b.get(a, "armor"), 0)
        b.acquire_target(z, [a])
        b.acquire_target(other, [a])
        self.assertEqual((b.get(a, "armor"), b.get(a, "mr")), (20, 20))
        scaled = formula(
            [{"coefficient": 2, "stat": "armor"}], a, z, b.now, stat_getter=b.get
        )
        self.assertEqual(scaled, 40)
        b.hit(z, a, 12, "physical", "attack")
        self.assertAlmostEqual(a.hp, 90)
        b.acquire_target(other, [b.by_id["outsider"]])
        self.assertEqual(b.get(a, "armor"), 10)
        z.hp = 0
        self.assertEqual(b.get(a, "armor"), 0)

    def test_hunter_timer_survives_stun_and_resets_after_target_change(self):
        b = self.battle("DA_18_Hunter", 2)
        a, z, other = b.by_id["m0"], b.by_id["b"], b.by_id["enemy2"]
        b.acquire_target(a, [z])
        b.now = 2.999
        self.assertEqual(b.get(a, "damage_amp"), 0)
        a.statuses["stun"] = [5]
        b.now = 3
        self.assertAlmostEqual(b.get(a, "damage_amp"), 0.1)
        b.acquire_target(a, [z])
        self.assertEqual(a.target_acquired_at, 0)
        b.acquire_target(a, [other])
        self.assertEqual(b.get(a, "damage_amp"), 0)
        b.now = 6
        self.assertAlmostEqual(b.get(a, "damage_amp"), 0.1)
        other.hp = 0
        self.assertEqual(b.get(a, "damage_amp"), 0)
        self.assertAlmostEqual(b.get(a, "ad"), 24, places=5)

    def test_ravager_checks_recipient_health_before_each_hit(self):
        b = self.battle("DA_18_Slayer", 2)
        a, z, other = b.by_id["m0"], b.by_id["b"], b.by_id["enemy2"]
        z.hp = 50
        other.hp = 49
        self.assertAlmostEqual(b.hit(a, z, 10, "physical", "attack"), 11.2, places=5)
        self.assertAlmostEqual(b.hit(a, other, 10, "magic", "spell"), 12.4, places=5)
        self.assertAlmostEqual(b.hit(a, z, 10, "physical", "attack"), 12.4, places=5)
        self.assertAlmostEqual(b.get(a, "omnivamp"), 0.1)

    def test_invoker_member_bonus_replaces_team_bonus_at_all_tiers(self):
        for count, member, team in ((2, 3, 1), (3, 4, 1), (4, 6, 2), (5, 8, 2)):
            with self.subTest(count=count):
                b = self.battle("DA_18_Invoker", count)
                self.assertEqual(b.get(b.by_id["m0"], "mana_per_second"), member)
                self.assertEqual(b.get(b.by_id["outsider"], "mana_per_second"), team)
                self.assertEqual(b.get(b.by_id["b"], "mana_per_second"), 0)

    def test_inferno_refreshes_within_trait_but_stacks_with_other_burn(self):
        b = self.battle("DA_18_Inferno", 2)
        a, ally, z = b.by_id["m0"], b.by_id["m1"], b.by_id["b"]
        for source in (a, a, ally):
            b.hook("damage_dealt", source, z, {"tag": "attack", "damage": 1})
        self.assertAlmostEqual(b.get(z, "wound"), 0.33)
        b.effects(
            a,
            z,
            [
                dict(
                    op="over_time",
                    key="item-burn",
                    duration=3,
                    ticks=3,
                    scaling_time="dynamic",
                    stacking="refresh_strongest",
                    group="item-burn",
                    effects=[
                        dict(
                            op="damage", damage_type="true", amount=[{"coefficient": 1}]
                        )
                    ],
                )
            ],
        )
        for unit in b.units:
            unit.hooks = []
            unit.values.base["ad"] = 0
        b.duration = 3.01
        b.run()
        self.assertAlmostEqual(z.hp, 94)
        self.assertEqual(b.get(z, "wound"), 0)

    def test_inferno_shop_tier_is_not_silently_replaced_by_combat_only_tier(self):
        with self.assertRaisesRegex(UnsupportedRule, "trait effect"):
            self.battle("DA_18_Inferno", 3)


if __name__ == "__main__":
    unittest.main()
