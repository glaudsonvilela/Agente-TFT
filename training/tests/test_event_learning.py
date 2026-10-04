import unittest
import numpy as np
from training.event_lab import train, encode
from trainer.simulation.state import Player, Unit


class ValueLearning(unittest.TestCase):
    def test_features_preserve_position_stars_and_item_identity(self):
        teams = [
            Player(
                0,
                1,
                0,
                units=[
                    Unit(
                        "a",
                        "unit",
                        stars=2,
                        zone="board",
                        position=(3, 6),
                        items=["rod"],
                    )
                ],
            ),
            Player(0, 1, 0),
        ]
        values = (
            encode(teams, ["unit"], ["rod", "sword"])
            .reshape(2, -1)[:, :-2]
            .reshape(2, 4, 7, 4)
        )
        np.testing.assert_allclose(values[0, 3, 6], [1, 2 / 3, 1 / 3, 0])
        self.assertEqual(np.count_nonzero(values[1]), 0)

    def test_duplicate_champions_are_not_silently_overwritten(self):
        teams = [
            Player(
                0,
                2,
                0,
                units=[
                    Unit("a", "unit", zone="board", position=(0, 0)),
                    Unit("b", "unit", zone="board", position=(3, 6)),
                ],
            ),
            Player(0, 1, 0),
        ]
        values = encode(teams, ["unit"], []).reshape(2, -1)[:, :-2].reshape(2, 4, 7, 2)
        self.assertEqual(values[0, :, :, 0].sum(), 2)
        self.assertEqual(values[0, 0, 0, 0], 1)
        self.assertEqual(values[0, 3, 6, 0], 1)

    def test_unseen_champion_or_item_does_not_become_an_empty_board(self):
        teams = [
            Player(0, 1, 0, units=[Unit("a", "unseen", zone="board", position=(0, 0))]),
            Player(0, 1, 0),
        ]
        with self.assertRaisesRegex(ValueError, "vocabulary"):
            encode(teams, ["unit"], [])
        teams[0].units[0].champion = "unit"
        teams[0].units[0].items = ["unseen"]
        with self.assertRaisesRegex(ValueError, "vocabulary"):
            encode(teams, ["unit"], [])

    def test_separate_seed_split_has_real_optimizer_updates(self):
        rng = np.random.default_rng(91)
        x = rng.uniform(0, 1, (200, 8)).astype("float32")
        y = np.where(x[:, :4].sum(axis=1) > x[:, 4:].sum(axis=1), 2, 0)
        train_ids = np.arange(160)
        validation_ids = np.arange(160, 200)
        _, result = train(x, y, train_ids, validation_ids, epochs=40, seed=3)
        self.assertGreater(result["optimizer_steps"], 0)
        self.assertLess(
            result["final_validation"]["cross_entropy"],
            result["initial_validation"]["cross_entropy"],
        )
        self.assertEqual(result["validation_scenarios"], 40)
        self.assertFalse(result["real_tft_improvement_proven"])
        self.assertFalse(result["runtime_promoted"])


if __name__ == "__main__":
    unittest.main()
