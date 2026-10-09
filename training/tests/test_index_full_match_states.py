"""Keep uncertain OCR out of the full-match training index."""

import unittest

from training.index_full_match_states import reconcile_gold_reads


class GoldOcrConsensusTests(unittest.TestCase):
    def test_accepts_primary_with_one_agreeing_view(self):
        self.assertEqual(
            reconcile_gold_reads({
                "gray_psm13": "51", "gray_psm7": "51", "contrast_psm7": "31",
            }),
            (51, "corroborated"),
        )

    def test_rejects_three_different_readings(self):
        self.assertEqual(
            reconcile_gold_reads({
                "gray_psm13": "51", "gray_psm7": "31", "contrast_psm7": "81",
            }),
            (None, "disagreement"),
        )

    def test_does_not_fall_back_to_bad_secondary_when_primary_is_blank(self):
        self.assertEqual(
            reconcile_gold_reads({
                "gray_psm13": "", "gray_psm7": "7", "contrast_psm7": "7",
            }),
            (None, "unreadable"),
        )

    def test_rejects_non_numeric_primary(self):
        self.assertEqual(
            reconcile_gold_reads({
                "gray_psm13": "5l", "gray_psm7": "51", "contrast_psm7": "51",
            }),
            (None, "unreadable"),
        )


if __name__ == "__main__":
    unittest.main()
