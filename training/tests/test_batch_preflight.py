from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

from training.simulator_lab.batch_preflight import review
from training.tests.test_hex_simulator import fixture


class BatchPreflight(unittest.TestCase):
    @patch("training.simulator_lab.batch_preflight.capacity")
    def test_flags_cannot_turn_synthetic_executor_into_ten_thousand_real_games(
        self, cap
    ):
        cap.return_value = {"disk_free_bytes": 10 * 1024**3}
        c = fixture()
        c["patch"] = "test"
        c["coverage"] = {
            k: True
            for k in (
                "full_match_ready",
                "augments_ready",
                "seasonal_events_ready",
                "current_patch_training_ready",
            )
        }
        c["match_rules"] = dict(
            interest_step=10,
            base_income=5,
            interest_cap=5,
            natural_xp=2,
            loss_damage=1,
            tie_damage=1,
            starting_level=1,
            starting_hp=100,
            pool_per_champion=30,
            starting_gold=0,
            pairing="seeded_shuffle_with_bye",
            loot="none",
            streaks="none",
        )
        events = dict(
            patch="test",
            wisps={"fake": dict(stage_distribution_verified=True)},
            coven=dict(cashout_tables={"fake": 1}),
        )
        before = deepcopy(c)
        r = review(c, events, matches=10000, output_directory=Path("."))
        self.assertEqual(r["status"], "blocked")
        self.assertIn("seasonal_full_match_executor_not_integrated", r["blockers"])
        self.assertEqual(r["completed_matches"], 0)
        self.assertFalse(r["launched"])
        self.assertFalse(r["training_started"])
        self.assertEqual(c, before)

    @patch("training.simulator_lab.batch_preflight.capacity")
    def test_missing_sources_and_low_disk_are_reported_without_time_estimate(self, cap):
        cap.return_value = {"disk_free_bytes": 1024}
        r = review(fixture(), dict(patch="other", wisps={}, coven={}))
        self.assertIn("less_than_2_gib_free_disk", r["blockers"])
        self.assertIn("wisp_stage_distribution", r["blockers"])
        self.assertIn("seasonal_patch_mismatch", r["blockers"])
        self.assertIsNone(r["estimated_seconds"])


if __name__ == "__main__":
    unittest.main()
