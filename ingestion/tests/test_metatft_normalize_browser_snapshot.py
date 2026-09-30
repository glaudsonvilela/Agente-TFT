from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ingestion.metatft.normalize_browser_snapshot import (
    CatalogResolver,
    normalize_browser_snapshot,
    parse_frequency_cell,
)


class MetaTftBrowserNormalizerTests(unittest.TestCase):
    def trait_snapshot(self):
        return {
            "source": "metatft_public_browser",
            "source_url": "https://www.metatft.com/traits?set=TFTSet18",
            "captured_at_epoch": 1000.0,
            "title": "MetaTFT Traits - Best Meta TFT Traits",
            "headings": ["Top TFT Trait Tier List"],
            "tables": [
                {
                    "table_index": 0,
                    "rows": [
                        [
                            "Trait",
                            "Tier",
                            "Avg Place",
                            "Win Rate",
                            "Levels",
                            "Frequency",
                        ],
                        ["Heroic", "S", "3.92", "16.5%", "2/4/6", "120,500 7.8%"],
                        ["Warden", "A", "4.21", "12.4%", "2/4/6", "98,000 6.1%"],
                    ],
                }
            ],
            "body_text": "Ranked\n18.3b\nLast 3 Days\nPlatinum +\nSet 18",
            "links": [],
            "repeated_blocks": [],
        }

    def test_parses_trait_table_and_context(self):
        normalized = normalize_browser_snapshot(self.trait_snapshot())
        self.assertEqual(normalized["patch"], "18.3b")
        self.assertEqual(normalized["set"], "TFTSet18")
        self.assertEqual(normalized["queue"], "ranked")
        self.assertEqual(normalized["rank_filter"], "platinum_plus")
        self.assertEqual(normalized["window"], "last_3_days")
        self.assertEqual(len(normalized["entities"]), 2)

        heroic = normalized["entities"][0]
        self.assertEqual(heroic["kind"], "trait")
        self.assertEqual(heroic["performance"]["avg_place"], 3.92)
        self.assertEqual(heroic["performance"]["win_rate"], 0.165)
        self.assertEqual(heroic["performance"]["frequency"], 0.078)
        self.assertEqual(heroic["performance"]["sample_size"], 120500)

    def test_crosswalk_resolves_communitydragon_api_name(self):
        raw = self.trait_snapshot()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "traits.json"
            path.write_text(
                json.dumps(
                    {
                        "traits": [
                            {
                                "api_name": "TFT18_Trait_Heroic",
                                "name": "Heroic",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            resolver = CatalogResolver.from_catalogs(trait_catalog=path)
            normalized = normalize_browser_snapshot(raw, resolver=resolver)

        heroic = next(
            entity
            for entity in normalized["entities"]
            if entity["name"] == "Heroic"
        )
        self.assertEqual(heroic["id"], "TFT18_Trait_Heroic")

    def test_leaderboard_table_becomes_player_entities(self):
        raw = {
            "source_url": "https://www.metatft.com/leaderboard/br",
            "captured_at_epoch": 1000.0,
            "title": "TFT Leaderboard",
            "headings": [],
            "tables": [
                {
                    "table_index": 0,
                    "rows": [
                        ["Rank", "Player", "LP", "Avg Place", "Win Rate", "Games"],
                        ["1", "PlayerA", "1800", "3.80", "18.2%", "230"],
                    ],
                }
            ],
            "body_text": "Ranked\n18.3b\nLast 3 Days",
            "links": [],
            "repeated_blocks": [],
        }
        normalized = normalize_browser_snapshot(raw)
        self.assertEqual(len(normalized["entities"]), 1)
        player = normalized["entities"][0]
        self.assertEqual(player["kind"], "player")
        self.assertEqual(player["name"], "PlayerA")
        self.assertEqual(player["performance"]["sample_size"], 230)

    def test_unknown_table_is_preserved_in_diagnostics(self):
        raw = self.trait_snapshot()
        raw["tables"] = [
            {
                "table_index": 0,
                "rows": [
                    ["Foo", "Bar"],
                    ["x", "y"],
                ],
            }
        ]
        normalized = normalize_browser_snapshot(raw)
        self.assertEqual(normalized["entities"], [])
        self.assertEqual(
            len(normalized["diagnostics"]["unparsed_tables"]),
            1,
        )

    def test_frequency_cell_parses_count_and_rate(self):
        self.assertEqual(
            parse_frequency_cell("72,205 20.9%"),
            (0.209, 72205),
        )


if __name__ == "__main__":
    unittest.main()
