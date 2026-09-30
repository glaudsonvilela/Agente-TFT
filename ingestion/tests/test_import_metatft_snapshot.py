from __future__ import annotations

import unittest

from ingestion.import_metatft_snapshot import normalize_snapshot


class MetaTftSnapshotTests(unittest.TestCase):
    def fixture(self):
        return {
            "source_url": "https://www.metatft.com/comps",
            "captured_at_ms": 1000,
            "patch": "18.3b",
            "set": "TFTSet18",
            "queue": "ranked",
            "rank_filter": "platinum_plus",
            "window": "last_3_days",
            "entities": [
                {
                    "kind": "comp",
                    "id": "comp-x",
                    "name": "X Comp",
                    "unit_ids": ["TFT18_X", "TFT18_Y"],
                    "trait_ids": ["TFT18_Trait_A"],
                    "performance": {
                        "avg_place": 3.9,
                        "top4_rate": 0.58,
                        "win_rate": 0.15,
                        "frequency": 0.08,
                        "sample_size": 5000,
                    },
                    "tags": ["fast8"],
                }
            ],
            "metadata": {
                "collection": "public_snapshot",
            },
        }

    def test_normalizes_valid_snapshot(self):
        normalized = normalize_snapshot(self.fixture())
        self.assertEqual(normalized["source"], "metatft_public")
        self.assertEqual(normalized["entities"][0]["kind"], "comp")
        self.assertEqual(
            normalized["entities"][0]["performance"]["avg_place"],
            3.9,
        )

    def test_rejects_non_metatft_source(self):
        fixture = self.fixture()
        fixture["source_url"] = "https://example.com/comps"
        with self.assertRaises(ValueError):
            normalize_snapshot(fixture)

    def test_rejects_invalid_rate(self):
        fixture = self.fixture()
        fixture["entities"][0]["performance"]["top4_rate"] = 1.2
        with self.assertRaises(ValueError):
            normalize_snapshot(fixture)

    def test_rejects_invalid_average_place(self):
        fixture = self.fixture()
        fixture["entities"][0]["performance"]["avg_place"] = 9.0
        with self.assertRaises(ValueError):
            normalize_snapshot(fixture)


if __name__ == "__main__":
    unittest.main()
