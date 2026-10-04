from copy import deepcopy
import json
from pathlib import Path
import unittest

from trainer.simulation.economy import accounted_copies
from trainer.simulation.state import (
    Player,
    Unit,
    World,
    Offer,
    Action,
    apply,
    legal_actions,
    UnsupportedRule,
    IllegalAction,
)
from trainer.simulation.round_calendar import describe, successor
from trainer.simulation.seasonal_events import (
    begin_observed_round,
    observe_offer,
    buy_wisp,
    end_planning,
    settle_observed_pvp,
    settle_observed_non_pvp,
    continue_coven,
)
from training.tests.test_hex_simulator import fixture

ROOT = Path(__file__).resolve().parents[2]


class SeasonalResources(unittest.TestCase):
    def setUp(self):
        self.rules = json.loads(
            (
                ROOT / "configs/simulation/seasons/TFTSet18/events/18.3B-economy.json"
            ).read_text()
        )
        self.calendar = json.loads(
            (ROOT / "configs/simulation/core/standard-calendar-v1.json").read_text()
        )
        self.economy = json.loads(
            (ROOT / "configs/simulation/core/standard-economy-v1.json").read_text()
        )
        self.c = fixture()
        self.c["patch"] = self.rules["patch"]
        self.w = World(
            [
                Player(
                    20,
                    2,
                    0,
                    stage=2,
                    units=[Unit("a", "fixture", zone="board", position=(0, 0))],
                )
            ],
            {"fixture": 19},
            pool_totals={"fixture": 20},
        )

    def begin(self, world=None, key="2-2", tier=0):
        return begin_observed_round(
            world or self.w,
            0,
            key,
            self.c,
            self.rules,
            self.calendar,
            initial_blossom_tier=tier,
        )

    def buy(self, w, name):
        w = observe_offer(w, 0, name, self.c, self.rules)
        return buy_wisp(w, 0, self.c, self.rules)[0]

    def settle(self, w, outcome="win", kills=1, survivors=0, allies=1):
        w = end_planning(w, 0, self.c, self.rules)
        return settle_observed_pvp(
            w,
            0,
            self.c,
            self.rules,
            self.calendar,
            self.economy,
            outcome=outcome,
            enemy_champion_kills=kills,
            surviving_enemy_champions=survivors,
            allied_survivors=allies,
        )

    def test_overlay_keeps_hidden_champion_reserved_and_reveals_at_combat(self):
        w = self.begin()
        w.players[0].shop[4] = Offer("champion", "fixture", 1)
        w.pool["fixture"] -= 1
        before = accounted_copies(w, self.c)
        w = observe_offer(w, 0, "freeroller", self.c, self.rules)
        self.assertEqual(accounted_copies(w, self.c), before)
        with self.assertRaisesRegex(IllegalAction, "covered"):
            apply(w, 0, Action("buy", (4,)), self.c)
        w = end_planning(w, 0, self.c, self.rules)
        self.assertIsNone(w.players[0].seasonal["offer"])
        self.assertEqual(w.players[0].shop[4].entity, "fixture")
        self.assertEqual(accounted_copies(w, self.c), before)
        with self.assertRaisesRegex(IllegalAction, "ended"):
            apply(w, 0, Action("xp"), self.c)
        with self.assertRaises(IllegalAction):
            buy_wisp(w, 0, self.c, self.rules)

    def test_blossom_rebate_cannot_fund_purchase_and_limit_is_per_round(self):
        w = self.begin(tier=7)
        w.players[0].gold = 1
        w = observe_offer(w, 0, "freeroller", self.c, self.rules)
        original = deepcopy(w)
        with self.assertRaisesRegex(IllegalAction, "insufficient"):
            buy_wisp(w, 0, self.c, self.rules)
        self.assertEqual(w, original)
        w.players[0].gold = 2
        w, receipt = buy_wisp(w, 0, self.c, self.rules)
        self.assertEqual((w.players[0].gold, w.players[0].free_rerolls), (4, 3))
        self.assertEqual(receipt["rebate"], 4)
        with self.assertRaisesRegex(IllegalAction, "limit"):
            observe_offer(w, 0, "beggars_wisp", self.c, self.rules)

    def test_blossom_nine_allows_two_and_prismatic_is_not_guessed(self):
        w = self.buy(self.begin(tier=9), "beggars_wisp")
        w = self.buy(w, "beggars_wisp")
        self.assertEqual(w.players[0].seasonal["purchased"], 2)
        with self.assertRaisesRegex(IllegalAction, "limit"):
            self.buy(w, "beggars_wisp")
        with self.assertRaises(UnsupportedRule):
            self.begin(tier=11)

    def test_refresh_consumes_credit_and_returns_all_shop_reservations(self):
        w = self.buy(self.begin(), "freeroller")
        original = deepcopy(w)
        w = observe_offer(w, 0, None, self.c, self.rules, refresh=True)
        self.assertEqual(w.players[0].free_rerolls, 1)
        self.assertEqual(w.players[0].gold, 18)
        self.assertEqual(accounted_copies(w, self.c), w.pool_totals)
        self.assertEqual(original.players[0].free_rerolls, 2)
        with self.assertRaises(UnsupportedRule):
            apply(w, 0, Action("reroll"), self.c)
        with self.assertRaises(UnsupportedRule):
            legal_actions(w, 0, self.c)

    def test_random_rewards_reproduce_and_failures_leave_rng_unchanged(self):
        w = observe_offer(self.begin(), 0, "die_roll", self.c, self.rules)
        original = deepcopy(w)
        a, ra = buy_wisp(w, 0, self.c, self.rules)
        b, rb = buy_wisp(w, 0, self.c, self.rules)
        self.assertEqual(a, b)
        self.assertEqual(ra, rb)
        self.assertEqual(w, original)
        self.assertTrue(1 <= ra["effects"][0]["results"][0] <= 6)
        bad = deepcopy(self.rules)
        bad["wisps"]["die_roll"]["normal"][0]["dice"] = 0
        with self.assertRaises(UnsupportedRule):
            buy_wisp(w, 0, self.c, bad)
        self.assertEqual(w, original)

    def test_delayed_rewards_survive_carousel_without_counting_it(self):
        w = self.buy(self.begin(), "golden_road")
        w, _ = self.settle(w)
        self.assertEqual(
            (
                w.players[0].seasonal["pending"][0]["combats"],
                w.players[0].seasonal["pending"][0]["wins"],
            ),
            (2, 1),
        )
        w = self.begin(w, "2-3")
        w, _ = self.settle(w, "loss", 0, 1, 0)
        w = self.begin(w, "2-4")
        w = end_planning(w, 0, self.c, self.rules)
        p = w.players[0]
        resources = {
            k: getattr(p, k)
            for k in (
                "gold",
                "xp",
                "level",
                "hp",
                "streak",
                "free_rerolls",
                "round_free_rerolls",
            )
        }
        w, receipt = settle_observed_non_pvp(
            w, 0, self.c, self.rules, self.calendar, resources=resources
        )
        self.assertFalse(receipt["rewards_simulated"])
        self.assertEqual(w.players[0].seasonal["pending"][0]["combats"], 1)
        w = self.begin(w, "2-5")
        w, r = self.settle(w)
        self.assertEqual(r["resource_events"][0]["amount"], 4)
        self.assertEqual(w.players[0].seasonal["pending"], [])

    def test_good_loss_only_pays_losses_and_expires_after_three_combats(self):
        w = self.buy(self.begin(), "good_loss")
        w, r = self.settle(w)
        self.assertEqual(r["resource_events"][0]["amount"], 0)
        w = self.begin(w, "2-3")
        w, r = self.settle(w, "loss", 0, 1, 0)
        self.assertEqual(r["resource_events"][0]["amount"], 4)
        self.assertEqual(w.players[0].seasonal["pending"][0]["combats"], 1)
        with self.assertRaises(IllegalAction):
            settle_observed_pvp(
                w,
                0,
                self.c,
                self.rules,
                self.calendar,
                self.economy,
                outcome="loss",
                enemy_champion_kills=0,
                surviving_enemy_champions=1,
                allied_survivors=0,
            )

    def test_coven_counts_distinct_board_identities_and_uses_patched_loss_value(self):
        trait = self.rules["coven"]["trait"]
        self.c["champions"]["fixture"]["traits"] = [trait]
        for i in range(2):
            key = f"extra{i}"
            self.c["champions"][key] = deepcopy(self.c["champions"]["fixture"])
            self.w.pool[key] = 19
            self.w.pool_totals[key] = 20
            self.w.players[0].units.append(
                Unit(key, key, zone="board", position=(0, i + 1))
            )
        self.w.players[0].level = 4
        self.w.players[0].units.append(Unit("duplicate", "fixture", position=(0,)))
        self.w.pool["fixture"] -= 1
        w = self.begin()
        w, r = self.settle(w, "loss", 2, 1, 0)
        self.assertEqual(r["coven_essence_gained"], 26)
        w = self.begin(w, "2-3")
        w, r = self.settle(w, "loss", 1, 1, 0)
        self.assertEqual(w.players[0].seasonal["coven_essence"], 50)
        with self.assertRaisesRegex(IllegalAction, "Coven"):
            self.begin(w, "2-4")
        w = continue_coven(w, 0, self.c, self.rules)
        self.begin(w, "2-4")

    def test_blossom_latches_after_combat_using_board_not_bench(self):
        trait = self.rules["blossom"]["trait"]
        self.c["champions"]["fixture"]["traits"] = [trait]
        self.c["champions"]["fixture"]["trait_contributions"] = {trait: 3}
        w = self.begin()
        w = self.buy(w, "beggars_wisp")
        self.assertEqual(w.players[0].gold, 23)
        w, _ = self.settle(w)
        self.assertEqual(w.players[0].seasonal["blossom_tier"], 3)
        w = self.begin(w, "2-3")
        before = w.players[0].gold
        w = self.buy(w, "beggars_wisp")
        self.assertEqual(w.players[0].gold, before + 5)

    def test_lethal_health_purchase_releases_units_and_shop_without_resurrection(self):
        w = self.begin()
        w.players[0].hp = 3
        w = self.buy(w, "sinister_deal")
        p = w.players[0]
        self.assertEqual((p.hp, p.phase), (0, "eliminated"))
        self.assertEqual(p.units, [])
        self.assertEqual(w.pool["fixture"], 20)
        with self.assertRaises(UnsupportedRule):
            self.begin(w, "2-3")

    def test_missing_wisp_patch_mismatch_and_special_rewards_are_not_invented(self):
        w = self.begin()
        original = deepcopy(w)
        with self.assertRaises(UnsupportedRule):
            observe_offer(w, 0, "unknown", self.c, self.rules)
        changed = deepcopy(self.c)
        changed["patch"] = "old"
        with self.assertRaisesRegex(UnsupportedRule, "patch"):
            buy_wisp(w, 0, changed, self.rules)
        self.assertEqual(w, original)
        w = self.begin(key="2-7")
        w = end_planning(w, 0, self.c, self.rules)
        with self.assertRaises(IllegalAction):
            settle_observed_non_pvp(
                w, 0, self.c, self.rules, self.calendar, resources={"gold": 10}
            )

    def test_calendar_handles_stage_transition_and_rejects_skips(self):
        self.assertEqual(successor("1-4", self.calendar), "2-1")
        self.assertEqual(successor("2-7", self.calendar), "3-1")
        self.assertTrue(describe("3-2", self.calendar)["augment"])
        self.assertEqual(describe("4-7", self.calendar)["kind"], "pve")
        w, _ = self.settle(self.begin())
        with self.assertRaisesRegex(IllegalAction, "skipped"):
            self.begin(w, "2-5")
        with self.assertRaises(UnsupportedRule):
            successor("8-7", self.calendar)

    def test_unknown_effect_conditions_and_augment_boundaries_are_not_ignored(self):
        self.rules["wisps"]["beggars_wisp"]["normal"][0]["only_if_win"] = True
        w = self.begin()
        with self.assertRaisesRegex(UnsupportedRule, "unknown seasonal effect"):
            observe_offer(w, 0, "beggars_wisp", self.c, self.rules)
        with self.assertRaisesRegex(UnsupportedRule, "augment choice"):
            self.begin(key="3-2")

    def test_combat_kernels_cannot_drop_seasonal_state_silently(self):
        from trainer.simulation.combat import materialize
        from trainer.simulation.event_combat import Battle

        p = self.begin().players[0]
        for kernel in (materialize, Battle):
            with self.assertRaisesRegex(UnsupportedRule, "seasonal resources"):
                kernel([p, deepcopy(p)], self.c)

    def test_all_bound_programs_run_both_variants_on_resource_snapshots(self):
        for key in self.rules["wisps"]:
            for tier in (0, 3):
                with self.subTest(wisp=key, tier=tier):
                    w = self.begin(tier=tier)
                    before = deepcopy(w)
                    w = self.buy(w, key)
                    self.assertEqual(before.players[0].seasonal["purchased"], 0)
                    w, r = self.settle(w)
                    self.assertEqual(w.players[0].seasonal["phase"], "settled")
                    self.assertEqual(accounted_copies(w, self.c), w.pool_totals)
                    self.assertFalse(r["full_match"])


if __name__ == "__main__":
    unittest.main()
