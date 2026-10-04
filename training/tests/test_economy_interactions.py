"""Cross-system economy checks using declared outcomes and tiny exact pools."""

from copy import deepcopy
import json
from math import comb
from pathlib import Path
import unittest
from unittest.mock import patch

from trainer.simulation.state import (
    Player,
    Unit,
    Offer,
    World,
    Action,
    IllegalAction,
    UnsupportedRule,
    apply,
)
from trainer.simulation.economy import accounted_copies
from trainer.simulation.round_economy import project_pvp
from trainer.simulation.shop_probability import next_shop_probability
from trainer.simulation.match import begin_round, resolve_round
from training.tests.test_hex_simulator import fixture

ROOT = Path(__file__).resolve().parents[2]


def rules():
    return json.loads(
        (ROOT / "configs/simulation/core/standard-economy-v2.json").read_text()
    )


def two_cost_content():
    c = fixture()
    c["champions"]["other"] = deepcopy(c["champions"]["fixture"])
    c["champions"]["expensive"] = deepcopy(c["champions"]["fixture"])
    c["champions"]["expensive"]["cost"] = 2
    c["economy"]["shop_odds"] = {"1": [1.0, 0, 0, 0, 0], "2": [0.5, 0.5, 0, 0, 0]}
    return c


class RoundEconomy(unittest.TestCase):
    def test_stage_damage_revision_changes_survival_and_next_income(self):
        for stage, hp, expected_hp, eliminated in [(3, 7, 0, True), (4, 9, 1, False)]:
            with self.subTest(stage=stage):
                p = Player(50, 2, 0, stage=stage, hp=hp)
                result, r = project_pvp(
                    p, fixture(), rules(), outcome="loss", surviving_enemy_champions=1
                )
                self.assertEqual(result.hp, expected_hp)
                self.assertEqual(r["eliminated"], eliminated)
                self.assertEqual(r["base_income"], 0 if eliminated else 5)

    def test_victory_gold_reaches_interest_before_base_or_streak_income(self):
        p = Player(9, 1, 0, stage=2, streak=1)
        before = deepcopy(p)
        result, receipt = project_pvp(
            p, fixture(), rules(), outcome="win", surviving_enemy_champions=0
        )
        self.assertEqual(p, before)
        self.assertEqual(
            (
                receipt["win_gold"],
                receipt["interest_basis"],
                receipt["interest"],
                receipt["streak_gold"],
            ),
            (1, 10, 1, 1),
        )
        self.assertEqual(result.gold, 17)
        self.assertEqual((result.level, result.xp), (2, 0))
        with self.assertRaisesRegex(IllegalAction, "already settled"):
            project_pvp(
                result, fixture(), rules(), outcome="win", surviving_enemy_champions=0
            )

    def test_losing_streak_thresholds_and_reset_change_income(self):
        for previous, expected in [(-1, 1), (-3, 1), (-4, 2), (-5, 3), (5, 0)]:
            p = Player(50, 2, 0, stage=4, streak=previous)
            result, receipt = project_pvp(
                p, fixture(), rules(), outcome="loss", surviving_enemy_champions=4
            )
            self.assertEqual(result.hp, 89)
            self.assertEqual(receipt["streak_gold"], expected)
            self.assertEqual(result.gold, 60 + expected)
        self.assertEqual(result.streak, -1)

    def test_lethal_loss_stops_next_income_and_experience(self):
        p = Player(50, 2, 0, hp=10, stage=5, streak=-5)
        result, r = project_pvp(
            p, fixture(), rules(), outcome="loss", surviving_enemy_champions=1
        )
        self.assertEqual((result.hp, result.gold, result.xp), (0, 50, 0))
        self.assertEqual(
            (r["base_income"], r["interest"], r["streak_gold"], r["natural_xp"]),
            (0, 0, 0, 0),
        )
        self.assertTrue(r["eliminated"])

    def test_paid_roll_crossing_fifty_loses_an_extra_gold_of_next_interest(self):
        c = fixture()
        w = World([Player(50, 1, 0, stage=2)], {"fixture": 20})
        held, _ = project_pvp(
            w.players[0], c, rules(), outcome="loss", surviving_enemy_champions=1
        )
        rolled = apply(w, 0, Action("reroll"), c)
        spent, r = project_pvp(
            rolled.players[0], c, rules(), outcome="loss", surviving_enemy_champions=1
        )
        self.assertEqual(held.gold - spent.gold, 3)
        self.assertEqual(r["interest"], 4)

    def test_draw_pve_missing_stage_and_unknown_augments_not_invented(self):
        for outcome in ("draw", "pve"):
            with self.assertRaises(UnsupportedRule):
                project_pvp(
                    Player(0, 1, 0, stage=2),
                    fixture(),
                    rules(),
                    outcome=outcome,
                    surviving_enemy_champions=0,
                )
        with self.assertRaises(UnsupportedRule):
            project_pvp(
                Player(0, 1, 0),
                fixture(),
                rules(),
                outcome="loss",
                surviving_enemy_champions=1,
            )
        with self.assertRaisesRegex(UnsupportedRule, "augment"):
            project_pvp(
                Player(0, 1, 0, stage=2, augments=["unknown"]),
                fixture(),
                rules(),
                outcome="loss",
                surviving_enemy_champions=1,
            )

    def test_match_uses_surviving_owned_champions_and_settles_once(self):
        c = fixture()
        c["match_rules"] = dict(
            income_model="ordinary_pvp_economy",
            round_economy=rules(),
            pairing="seeded_shuffle_with_bye",
            loot="none",
            streaks="outcome_signed",
        )
        units = [
            Unit("owned-a", "fixture", zone="board", position=(0, 0)),
            Unit("owned-b", "fixture", zone="board", position=(0, 0)),
        ]
        w = World(
            [
                Player(9, 1, 0, stage=2, units=[units[0]]),
                Player(9, 1, 0, hp=2, stage=2, units=[units[1]]),
            ],
            {"fixture": 18},
            pool_totals={"fixture": 20},
        )
        original = deepcopy(w)
        with self.assertRaisesRegex(UnsupportedRule, "full calendar unavailable"):
            begin_round(w, c)

        def fight(teams, content, seed):
            winning_index = next(i for i, p in enumerate(teams) if p.hp == 100)
            return dict(
                winner=winning_index,
                duration_seconds=1,
                units=[
                    dict(
                        uid=p.units[0].uid,
                        team=i,
                        health=100 if i == winning_index else 0,
                    )
                    for i, p in enumerate(teams)
                ]
                + [dict(uid="a:summon:extra", team=winning_index, health=100)],
            )

        with patch("trainer.simulation.match.simulate", side_effect=fight):
            settled, report = resolve_round(w, c, seed=4)
        self.assertEqual(w, original)
        self.assertEqual(settled.players[0].gold, 16)
        self.assertEqual(settled.players[1].hp, 0)
        self.assertEqual(settled.players[1].units, [])
        self.assertEqual(settled.pool["fixture"], 19)
        self.assertEqual(accounted_copies(settled, c), w.pool_totals)
        receipt = next(
            r for r in report["fights"][0]["economy_receipts"] if r["seat"] == 1
        )
        self.assertEqual(receipt["player_damage"], 3)
        with self.assertRaises(IllegalAction):
            resolve_round(settled, c, seed=4)


class SharedShopProbability(unittest.TestCase):
    def test_exact_without_replacement_matches_hypergeometric(self):
        c = two_cost_content()
        w = World([Player(0, 1, 0)], {"fixture": 3, "other": 7, "expensive": 10})
        before = deepcopy(w)
        r = next_shop_probability(w, 0, "fixture", c)
        self.assertAlmostEqual(r["probability"], 1 - comb(7, 5) / comb(10, 5))
        two = next_shop_probability(w, 0, "fixture", c, at_least=2)
        self.assertAlmostEqual(
            two["probability"],
            sum(comb(3, k) * comb(7, 5 - k) / comb(10, 5) for k in (2, 3)),
        )
        self.assertEqual(w, before)
        self.assertFalse(r["hidden_pool_observed"])

    def test_own_reserved_offer_returns_but_opponent_reservation_stays_out(self):
        c = two_cost_content()
        shop = [Offer("champion", "fixture", 1)] + [None] * 4
        w = World(
            [
                Player(0, 1, 0, shop=deepcopy(shop)),
                Player(0, 1, 0, shop=deepcopy(shop)),
            ],
            {"fixture": 0, "other": 9, "expensive": 10},
        )
        r = next_shop_probability(w, 0, "fixture", c, slots=1)
        self.assertEqual(r["target_copies_available_after_refresh"], 1)
        self.assertAlmostEqual(r["probability"], 0.1)

    def test_level_up_changes_tier_odds_and_exhausted_tier_renormalizes(self):
        c = two_cost_content()
        w = World([Player(4, 1, 0)], {"fixture": 10, "other": 0, "expensive": 10})
        self.assertEqual(
            next_shop_probability(w, 0, "expensive", c, slots=1)["probability"], 0
        )
        leveled = apply(w, 0, Action("xp"), c)
        self.assertAlmostEqual(
            next_shop_probability(leveled, 0, "expensive", c, slots=1)["probability"],
            0.5,
        )
        leveled.pool["fixture"] = 0
        self.assertEqual(
            next_shop_probability(leveled, 0, "expensive", c, slots=1)["probability"], 1
        )

    def test_free_roll_precedes_gold_and_preserves_shared_pool(self):
        c = two_cost_content()
        w = World(
            [Player(2, 1, 0, free_rerolls=1)],
            {"fixture": 10, "other": 10, "expensive": 10},
            pool_totals={"fixture": 10, "other": 10, "expensive": 10},
        )
        free = apply(w, 0, Action("reroll"), c)
        self.assertEqual((free.players[0].gold, free.players[0].free_rerolls), (2, 0))
        paid = apply(free, 0, Action("reroll"), c)
        self.assertEqual(paid.players[0].gold, 0)
        self.assertEqual(accounted_copies(paid, c), w.pool_totals)
        with self.assertRaises(IllegalAction):
            apply(paid, 0, Action("reroll"), c)
        self.assertEqual(w.players[0].free_rerolls, 1)

    def test_round_credit_is_spent_first_and_unspent_credit_expires(self):
        c = fixture()
        w = World(
            [Player(5, 1, 0, stage=2, free_rerolls=2, round_free_rerolls=2)],
            {"fixture": 20},
        )
        used = apply(w, 0, Action("reroll"), c)
        self.assertEqual(
            (
                used.players[0].gold,
                used.players[0].round_free_rerolls,
                used.players[0].free_rerolls,
            ),
            (5, 1, 2),
        )
        settled, r = project_pvp(
            used.players[0], c, rules(), outcome="win", surviving_enemy_champions=0
        )
        self.assertEqual((settled.round_free_rerolls, settled.free_rerolls), (0, 2))
        self.assertEqual(r["round_rerolls_expired"], 1)


if __name__ == "__main__":
    unittest.main()
