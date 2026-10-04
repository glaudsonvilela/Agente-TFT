import numpy as np
import unittest

from simulation.rollout_stats import rollout_stats


class RolloutStatsTests(unittest.TestCase):
    def test_jit_and_python_match_on_discounted_paths(self):
        values = np.array([[[1, 2], [-2, 1]], [[0, 4], [2, 2]]], dtype=np.float64)
        baseline = rollout_stats(values, discount=0.5, use_jit=False)
        self.assertTrue(np.allclose(rollout_stats(values, discount=0.5), baseline, rtol=1e-12))
        self.assertTrue(np.allclose(baseline[:, 0], [0.25, 2.5]))
        self.assertTrue(np.allclose(baseline[:, 2], [0.5, 0.0]))

    def test_invalid_rollouts_are_rejected(self):
        for values, discount in [
            (np.zeros((0, 1, 1)), 1.0), (np.ones((1, 1)), 1.0),
            (np.ones((1, 1, 1)), 1.1), (np.full((1, 1, 1), np.nan), 1.0),
        ]:
            with self.subTest(values=values.shape, discount=discount), self.assertRaises(ValueError):
                rollout_stats(values, discount=discount)
