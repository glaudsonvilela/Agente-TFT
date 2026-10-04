import unittest

from ingestion.challenger_patterns import analyze


class ChallengerPatternsTests(unittest.TestCase):
    def test_counts_observed_top_one_without_inventing_rounds(self):
        matches = [{"metadata": {"match_id": "BR1_1"}, "info": {
            "game_version": "Version 16.19.1", "participants": [
                {"puuid": "challenger", "placement": 1,
                 "units": [{"character_id": "A"}, {"character_id": "B"},
                           {"character_id": "unknown"}]},
                {"puuid": "other", "placement": 2, "units": [{"character_id": "A"}]},
            ]}}]
        result = analyze(matches + matches, {"A": {}, "B": {}}, {"challenger"}, "Version 16.19")
        self.assertEqual(result["participant_matches"], 1)
        self.assertEqual(result["winner_matches"], 1)
        self.assertEqual(result["skipped"]["missing_or_duplicate_match_id"], 1)
        self.assertEqual({row["champions"][0] for row in result["champions"]}, {"A", "B"})
        self.assertFalse(result["round_decisions_available"])
        self.assertEqual(result["simulated_games"], 0)

    def test_rejects_implicit_cohort_or_version(self):
        for players, version in [(set(), "Version 16.19"), ({"x"}, "")]:
            with self.assertRaises(ValueError):
                analyze([], {}, players, version)
