"""Regression checks for combat → settlement → shop, not TFT balance proofs."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from trainer.simulation.combat import simulate
from trainer.simulation.match import begin_round, new_match, resolve_round
from trainer.simulation.state import (
    Action,
    IllegalAction,
    Offer,
    Player,
    World,
    UnsupportedRule,
    apply,
)
from training.tests.test_event_combat import content as event_content, players
from training.tests.test_hex_simulator import fixture


class DependencyRegressions(unittest.TestCase):
    def match_content(self):
        return json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "configs/simulation/hex-lab-v1.json"
            ).read_text()
        )

    def test_legacy_combat_does_not_silently_drop_augments(self):
        teams = players()
        teams[0].augments = ["unimplemented_economy_or_combat_augment"]
        with self.assertRaisesRegex(UnsupportedRule, "augment"):
            simulate(teams, fixture())

    def test_event_combat_still_applies_supported_augment(self):
        c = event_content()
        c["augments"]["armor"] = {
            "modifiers": [{"stat": "armor", "mode": "flat", "value": 100}]
        }
        teams = players()
        teams[0].augments = ["armor"]
        self.assertEqual(simulate(teams, c)["winner"], 0)
        teams[0].augments = ["unknown"]
        with self.assertRaisesRegex(UnsupportedRule, "augment"):
            simulate(teams, c)

    def test_second_round_start_cannot_refresh_shop_for_free(self):
        c = self.match_content()
        world = begin_round(new_match(c, 7), c)
        before = deepcopy(world)
        with self.assertRaisesRegex(IllegalAction, "round"):
            begin_round(world, c)
        self.assertEqual(world, before)

    def test_settlement_cannot_repeat_or_accept_planning_actions(self):
        c = self.match_content()
        world = begin_round(new_match(c, 7), c)
        settled, _ = resolve_round(world, c, 3)
        before = deepcopy(settled)
        with self.assertRaisesRegex(IllegalAction, "round"):
            resolve_round(settled, c, 3)
        with self.assertRaises(IllegalAction):
            apply(settled, 0, Action("reroll"), c)
        self.assertEqual(settled, before)
        following = begin_round(settled, c)
        self.assertEqual(following.round_number, world.round_number + 1)
        self.assertTrue(
            all(p.phase == "planning" for p in following.players if p.hp > 0)
        )

    def test_locked_shop_persists_across_settlement(self):
        c = self.match_content()
        world = begin_round(new_match(c, 7), c)
        world = apply(world, 0, Action("lock", (True,)), c)
        offered = deepcopy(world.players[0].shop)
        settled, _ = resolve_round(world, c, 3)
        following = begin_round(settled, c)
        self.assertEqual(following.players[0].shop, offered)

    def test_invalid_odds_cannot_create_partial_shop_or_spend_gold(self):
        for weights in (
            [float("nan"), 0, 0, 0, 0],
            [1.2, -0.2, 0, 0, 0],
            [True, 0, 0, 0, 0],
        ):
            with self.subTest(weights=weights):
                c = fixture()
                c["economy"]["shop_odds"]["1"] = weights
                world = World([Player(10, 1, 0)], {"fixture": 20})
                before = deepcopy(world)
                with self.assertRaisesRegex(UnsupportedRule, "odds"):
                    apply(world, 0, Action("reroll"), c)
                self.assertEqual(world, before)

    def test_unknown_offer_cannot_invent_a_pool_identity(self):
        c = fixture()
        world = World(
            [Player(10, 1, 0, shop=[Offer("champion", "missing", 1)] + [None] * 4)],
            {"fixture": 20},
        )
        before = deepcopy(world)
        with self.assertRaisesRegex(UnsupportedRule, "champion"):
            apply(world, 0, Action("reroll"), c)
        self.assertEqual(world, before)

    def test_unmodeled_planning_augment_is_not_treated_as_normal_shop(self):
        c = fixture()
        world = World([Player(10, 1, 0, augments=["free_rolls"])], {"fixture": 20})
        with self.assertRaisesRegex(UnsupportedRule, "augment"):
            apply(world, 0, Action("reroll"), c)


if __name__ == "__main__":
    unittest.main()
