import unittest

from training.simulate_reviewed_economy_branches import buy_xp_branches


class ReviewedEconomyBranchesTest(unittest.TestCase):
    def test_level_crossing_matches_reviewed_video_and_hold_branch(self):
        row = dict(type="buy_xp", stage="3-1", before="frame-002894.jpg",
                   after="frame-002895.jpg", gold_before=34, gold_after=30,
                   level_before=5, level_after=6, xp_before=18, xp_after=2,
                   xp_to_next_before=20, xp_cost=4, xp_gained=4)
        result = buy_xp_branches(row)
        self.assertEqual(result["branches"]["hold"],
                         {"gold": 34, "level": 5, "xp": 18})
        self.assertEqual(result["branches"]["buy_xp"],
                         {"gold": 30, "level": 6, "xp": 2})
        self.assertIsNone(result["policy_preference_label"])
        row["gold_after"] = 31
        with self.assertRaisesRegex(ValueError, "disagrees"):
            buy_xp_branches(row)


if __name__ == "__main__":
    unittest.main()
