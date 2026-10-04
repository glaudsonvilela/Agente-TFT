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
            (ROOT / "configs/simulation/core/standard-economy-v2.json").read_text()
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
        w.players[0].gold = 2
        w = observe_offer(w, 0, "freeroller", self.c, self.rules)
        w.players[0].gold = 1  # spent after the observed offer
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
        w = observe_offer(self.begin(key="3-1"), 0, "die_roll", self.c, self.rules)
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
        w = self.buy(self.begin(key="3-5"), "good_loss")
        w, r = self.settle(w)
        self.assertEqual(r["resource_events"][0]["amount"], 0)
        w = self.begin(w, "3-6")
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
        w.players[0].hp = 5
        w = observe_offer(w, 0, "sinister_deal", self.c, self.rules)
        w.players[0].hp = 3  # health can change after an offer is generated
        w, _ = buy_wisp(w, 0, self.c, self.rules)
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

    def test_offer_windows_reject_wrong_stage_and_non_pvp_without_mutation(self):
        for key, name in [
            ("2-2", "die_roll"),
            ("4-3", "freeroller"),
            ("2-4", "coin_flip"),
            ("2-7", "coin_flip"),
        ]:
            w = self.begin(key=key)
            before = deepcopy(w)
            with self.subTest(round=key, wisp=name), self.assertRaises(IllegalAction):
                observe_offer(w, 0, name, self.c, self.rules)
            self.assertEqual(w, before)

    def test_refresh_checks_affordability_after_payment_and_rolls_back(self):
        w = self.begin()
        w.players[0].gold = 3
        before = deepcopy(w)
        with self.assertRaisesRegex(IllegalAction, "insufficient"):
            observe_offer(w, 0, "freeroller", self.c, self.rules, refresh=True)
        self.assertEqual(w, before)
        w.players[0].round_free_rerolls = 1
        offered = observe_offer(w, 0, "freeroller", self.c, self.rules, refresh=True)
        self.assertEqual(offered.players[0].gold, 3)
        self.assertEqual(offered.players[0].round_free_rerolls, 0)
        self.assertEqual(accounted_copies(offered, self.c), w.pool_totals)

    def test_variant_costs_include_zero_cost_and_official_patch_precedence(self):
        for name, key, normal, upgraded in [
            ("die_roll", "3-1", 2, 3),
            ("experienced", "2-2", 1, 0),
            ("bronze_spoon", "2-2", 3, 2),
            ("payday", "3-5", 3, 3),
            ("blood_money", "3-1", 2, 2),
            ("all_fives", "6-1", 8, 8),
        ]:
            for tier, expected in [(0, normal), (3, upgraded)]:
                with self.subTest(wisp=name, tier=tier):
                    w = observe_offer(
                        self.begin(key=key, tier=tier), 0, name, self.c, self.rules
                    )
                    _, r = buy_wisp(w, 0, self.c, self.rules)
                    self.assertEqual(r["cost"], expected)
        w = self.begin(tier=3)
        w.players[0].gold = 0
        gained = self.buy(w, "experienced")
        self.assertEqual((gained.players[0].gold, gained.players[0].xp), (0, 2))

    def test_life_debt_uses_missing_health_before_healing_and_rounds_down(self):
        for hp, expected in [(28, 6), (29, 5)]:
            w = self.begin(key="5-1", tier=3)
            w.players[0].hp = hp
            result = self.buy(w, "life_debt")
            self.assertEqual(result.players[0].gold, 20 + expected)
            self.assertEqual(result.players[0].hp, hp + 3)

    def test_streak_wisps_change_next_income_and_do_not_flip_opposite_streak(self):
        for name, initial, outcome, resulting, gold in [
            ("drought", -3, "loss", -6, 3),
            ("flood", 3, "win", 5, 2),
        ]:
            w = self.begin()
            w.players[0].streak = initial
            w = self.buy(w, name)
            w, r = self.settle(
                w,
                outcome,
                survivors=int(outcome == "loss"),
                allies=int(outcome == "win"),
            )
            self.assertEqual(w.players[0].streak, resulting)
            self.assertEqual(r["economy"]["streak_gold"], gold)
            invalid = self.begin()
            invalid.players[0].streak = -initial
            with self.assertRaisesRegex(IllegalAction, "streak"):
                self.buy(invalid, name)

    def test_health_streak_unit_and_coven_offer_conditions(self):
        for name, key, field, value in [
            ("healing_pool", "2-2", "hp", 91),
            ("life_debt", "5-1", "hp", 31),
            ("sinister_deal", "2-2", "hp", 4),
            ("good_loss", "3-1", "streak", 3),
            ("golden_road", "2-2", "streak", -3),
        ]:
            w = self.begin(key=key)
            setattr(w.players[0], field, value)
            with self.subTest(wisp=name), self.assertRaises(IllegalAction):
                self.buy(w, name)
        with self.assertRaisesRegex(IllegalAction, "one-star"):
            self.buy(self.begin(key="3-1"), "pocket_change")
        trait = self.rules["coven"]["trait"]
        self.c["champions"]["fixture"]["traits"] = [trait]
        self.c["champions"]["fixture"]["trait_contributions"] = {trait: 3}
        with self.assertRaisesRegex(IllegalAction, "Coven"):
            self.buy(self.begin(), "minor_gambit")

    def test_cooldown_requires_history_and_persists_across_rounds(self):
        self.w.players[0].hp = 80
        with self.assertRaisesRegex(UnsupportedRule, "history"):
            self.buy(self.begin(), "healing_pool")
        w = begin_observed_round(
            self.w,
            0,
            "2-2",
            self.c,
            self.rules,
            self.calendar,
            initial_offer_history={},
        )
        w = self.buy(w, "healing_pool")
        w, _ = self.settle(w)
        w = self.begin(w, "2-3")
        with self.assertRaisesRegex(IllegalAction, "cooldown"):
            self.buy(w, "healing_pool")
        # At exactly ten calendar transitions the named cooldown has elapsed.
        index = list(self.calendar["rounds"]).index("3-3")
        w = begin_observed_round(
            self.w,
            0,
            "3-3",
            self.c,
            self.rules,
            self.calendar,
            initial_offer_history={"healing_pool": index - 10},
        )
        self.buy(w, "healing_pool")

    def test_forced_tier_shop_returns_reservations_and_respects_exhaustion(self):
        self.c["champions"]["two"] = deepcopy(self.c["champions"]["fixture"])
        self.c["champions"]["two"]["cost"] = 2
        self.w.pool["two"] = 2
        self.w.pool_totals["two"] = 3
        self.w.players.append(
            Player(0, 1, 0, shop=[Offer("champion", "two", 2)] + [None] * 4)
        )
        w = self.begin(tier=3)
        w.players[0].shop[4] = Offer("champion", "fixture", 1)
        w.pool["fixture"] -= 1
        before = deepcopy(w)
        result = self.buy(w, "all_twos")
        offers = [o for o in result.players[0].shop if o]
        self.assertEqual([o.entity for o in offers], ["two", "two"])
        self.assertEqual(sum(o is None for o in result.players[0].shop), 3)
        self.assertEqual(accounted_copies(result, self.c), w.pool_totals)
        self.assertEqual(result.players[0].gold, 20)  # cost 1, upgraded rebate 1
        self.assertEqual(result.players[1].shop[0], before.players[1].shop[0])
        self.assertEqual(w, before)
        self.assertEqual(result, self.buy(w, "all_twos"))

    def test_unknown_eligibility_price_and_calendar_are_not_silently_accepted(self):
        self.rules["wisps"]["coin_flip"]["eligibility"]["mystery"] = True
        with self.assertRaisesRegex(UnsupportedRule, "eligibility"):
            self.buy(self.begin(), "coin_flip")
        del self.rules["wisps"]["coin_flip"]["eligibility"]["mystery"]
        del self.rules["wisps"]["coin_flip"]["blossom_cost"]
        with self.assertRaisesRegex(UnsupportedRule, "price"):
            self.buy(self.begin(tier=3), "coin_flip")
        w, _ = self.settle(self.begin())
        changed = deepcopy(self.calendar)
        changed["rounds"]["2-3"]["kind"] = "pve"
        with self.assertRaisesRegex(UnsupportedRule, "calendar"):
            begin_observed_round(w, 0, "2-3", self.c, self.rules, changed)

    def test_all_bound_programs_run_both_variants_on_resource_snapshots(self):
        for key in self.rules["wisps"]:
            for tier in (0, 3):
                with self.subTest(wisp=key, tier=tier):
                    spec = self.rules["wisps"][key]
                    first = spec["eligibility"]["first_round"]
                    if self.calendar["rounds"][first]["augment"]:
                        first = successor(first, self.calendar)
                    snapshot = deepcopy(self.w)
                    snapshot.players[0].hp = 28
                    snapshot.players[0].units.append(
                        Unit("bench", "fixture", position=(0,))
                    )
                    snapshot.pool["fixture"] -= 1
                    w = begin_observed_round(
                        snapshot,
                        0,
                        first,
                        self.c,
                        self.rules,
                        self.calendar,
                        initial_blossom_tier=tier,
                        initial_offer_history={},
                    )
                    before = deepcopy(w)
                    w = self.buy(w, key)
                    self.assertEqual(before.players[0].seasonal["purchased"], 0)
                    w, r = self.settle(w)
                    self.assertEqual(w.players[0].seasonal["phase"], "settled")
                    self.assertEqual(accounted_copies(w, self.c), w.pool_totals)
                    self.assertFalse(r["full_match"])


if __name__ == "__main__":
    unittest.main()
