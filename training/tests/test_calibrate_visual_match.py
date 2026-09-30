from __future__ import annotations

import unittest

from training.calibrate_visual_match import (
    Example,
    brier,
    split_deterministic,
    train,
)


class CalibrationTests(unittest.TestCase):
    def fixture(self) -> list[Example]:
        return [
            Example(0.99, 0.40, 1),
            Example(0.96, 0.30, 1),
            Example(0.94, 0.25, 1),
            Example(0.91, 0.20, 1),
            Example(0.85, 0.01, 0),
            Example(0.70, 0.02, 0),
            Example(0.50, 0.10, 0),
            Example(0.20, 0.01, 0),
        ]

    def test_training_orders_clear_positive_above_negative(self) -> None:
        rows = self.fixture()
        model = train(rows, epochs=5000, learning_rate=0.1)
        positive = model.predict(Example(0.98, 0.35, 1))
        negative = model.predict(Example(0.60, 0.02, 0))
        self.assertGreater(positive, negative)
        self.assertLess(brier(model, rows), 0.20)

    def test_deterministic_split_preserves_rows(self) -> None:
        rows = self.fixture()
        train_rows, validation_rows = split_deterministic(rows, 0.25)
        self.assertEqual(len(train_rows) + len(validation_rows), len(rows))

    def test_invalid_training_arguments_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            train(self.fixture(), epochs=0)


if __name__ == "__main__":
    unittest.main()
