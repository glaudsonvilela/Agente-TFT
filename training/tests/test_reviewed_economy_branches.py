import unittest

from training.simulate_reviewed_economy_branches import (
    buy_xp_branches, reroll_branches,
)


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

    def test_reroll_draw_is_observed_afterward_not_exposed_as_prediction(self):
        row = dict(type="reroll", stage="6-2", before="frame-009785.jpg",
                   after="frame-009786.jpg", gold_before=10, gold_after=8,
                   reroll_cost=2, shop_before=["Kayle", "Ezreal", "Morgana",
                                               "Brambleback", "Xayah"],
                   shop_after=["Taric", "Amumu", "Pebbles", "Malphite",
                                               "Warwick"])
        result = reroll_branches(row)
        self.assertEqual(result["branches"]["hold"]["gold"], 10)
        self.assertEqual(result["branches"]["reroll"],
                         {"gold": 8, "shop": None})
        self.assertEqual(result["observed_outcome"]["shop"][0], "Taric")
        self.assertIsNone(result["policy_preference_label"])
        row["gold_after"] = 9
        with self.assertRaisesRegex(ValueError, "disagrees"):
            reroll_branches(row)


if __name__ == "__main__":
    unittest.main()
