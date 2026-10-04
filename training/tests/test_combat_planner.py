"""Planning must compare equal evidence and preserve the observed board."""

from copy import deepcopy
import unittest
from unittest.mock import patch

import numpy as np

from trainer.simulation.state import Player, Unit, UnsupportedRule
from training.combat_choice_lab import alternatives
from training.combat_planner import select


class FixedValueModel:
    def predict(self, pairs):
        # A confident prediction alone cannot justify changing the board.
        return np.asarray([[0.4, 0.2, 0.4]] + [[0.0, 0.0, 1.0]] * (len(pairs) - 1))


class CombatPlanningTests(unittest.TestCase):
    def setUp(self):
        self.choices = [
            (dict(type="hold"), "original"),
            (dict(type="position"), "moved"),
        ]
        self.model = FixedValueModel()

    def test_every_alternative_uses_the_same_seeds_and_equal_counts(self):
        calls = []

        def combat(pair, content, *, seed):
            calls.append((pair, seed))
            return dict(winner=0 if pair == "moved" else 1)

        with patch("training.combat_planner.simulate", side_effect=combat):
            result = select(self.choices, self.model, {}, seed=7, rounds=4)
        self.assertEqual(result["selected"], 1)
        self.assertEqual(result["completed_rounds"], 4)
        self.assertEqual(
            [seed for pair, seed in calls if pair == "original"],
            [seed for pair, seed in calls if pair == "moved"],
        )
        self.assertFalse(result["runtime_promoted"])

    def test_tied_simulations_do_not_turn_model_confidence_into_improvement(self):
        with patch("training.combat_planner.simulate", return_value=dict(winner=0)):
            result = select(self.choices, self.model, {}, seed=7)
        self.assertEqual(result["selected"], 0)
        self.assertEqual(result["reason"], "no_counterfactual_gain")

    def test_expired_budget_discards_an_incomplete_round(self):
        elapsed = [0.0]

        def combat(pair, content, *, seed):
            elapsed[0] = 1.0
            return dict(winner=1)

        with patch(
            "training.combat_planner.time.perf_counter", side_effect=lambda: elapsed[0]
        ), patch("training.combat_planner.simulate", side_effect=combat):
            result = select(self.choices, self.model, {}, seed=7, seconds=0.75)
        self.assertEqual(result["selected"], 0)
        self.assertEqual(result["completed_rounds"], 0)
        self.assertEqual(result["simulated_combats"], 1)
        self.assertEqual(result["reason"], "no_completed_comparison")

    def test_missing_rules_propagate_instead_of_becoming_fabricated_outcomes(self):
        with patch(
            "training.combat_planner.simulate", side_effect=UnsupportedRule("trait")
        ):
            with self.assertRaises(UnsupportedRule):
                select(self.choices, self.model, {}, seed=7)

    def test_alternatives_are_independent_and_swaps_keep_distinct_cells(self):
        teams = [
            Player(
                0,
                2,
                0,
                units=[
                    Unit("a", "unit", zone="board", position=(0, 0)),
                    Unit("b", "unit", zone="board", position=(0, 1)),
                ],
            ),
            Player(0, 1, 0),
        ]
        original = deepcopy(teams)
        choices = alternatives(teams, "rod")
        for _, pair in choices:
            cells = [u.position for u in pair[0].units]
            self.assertEqual(len(cells), len(set(cells)))
        swap = next(
            pair
            for action, pair in choices
            if action == dict(type="position", unit_id="a", position=(0, 1))
        )
        self.assertEqual([u.position for u in swap[0].units], [(0, 1), (0, 0)])
        equipped = [pair for action, pair in choices if action["type"] == "equip"]
        equipped[0][0].units[0].items.append("unrelated")
        self.assertEqual(teams, original)
        self.assertNotIn("unrelated", equipped[1][0].units[0].items)


if __name__ == "__main__":
    unittest.main()
