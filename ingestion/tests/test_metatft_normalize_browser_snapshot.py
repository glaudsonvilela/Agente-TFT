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



class MetaTftRichUnitTests(unittest.TestCase):
    def test_detail_unit_extracts_items_and_positioning(self):
        raw = {
            "source": "metatft_public_browser",
            "source_url": "https://www.metatft.com/units/KhaZix",
            "captured_at_epoch": 1000.0,
            "title": "KhaZix TFT - Best Items and BiS Build",
            "headings": ["Kha'Zix TFT Builds, Items and Stats"],
            "tables": [],
            "body_text": (
                "Stats on how Kha'Zix performs in the current TFT Set 18 meta.\n"
                "Kha'Zix Stats\n"
                "4.53\n"
                "Avg Place\n"
                "Positioning\n"
                "Kha'Zix should be positioned in the front row.\n"
                "Recommended Builds\n"
                "We recommend Lich Bane, Edge of Night, Hand Of Justice "
                "as the best build for Kha'Zix in TFT.\n"
                "Top Items\n"
                "The best items for Kha'Zix are Hand Of Justice, "
                "Rabadon's Deathcap, Edge of Night and Nashor's Tooth\n"
                "Ranked\n18.3b\nLast 3 Days\nPlatinum +"
            ),
            "sections": [],
            "links": [],
            "repeated_blocks": [],
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            units = root / "units.json"
            items = root / "items.json"

            units.write_text(
                json.dumps(
                    {
                        "champions": [
                            {
                                "api_name": "TFT18_KhaZix",
                                "name": "Kha'Zix",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            items.write_text(
                json.dumps(
                    {
                        "items": [
                            {"api_name": "TFT_Item_LichBane", "name": "Lich Bane"},
                            {"api_name": "TFT_Item_EdgeOfNight", "name": "Edge of Night"},
                            {"api_name": "TFT_Item_HandOfJustice", "name": "Hand Of Justice"},
                            {"api_name": "TFT_Item_RabadonsDeathcap", "name": "Rabadon's Deathcap"},
                            {"api_name": "TFT_Item_NashorsTooth", "name": "Nashor's Tooth"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            resolver = CatalogResolver.from_catalogs(
                unit_catalog=units,
                item_catalog=items,
            )
            normalized = normalize_browser_snapshot(raw, resolver=resolver)

        self.assertEqual(len(normalized["entities"]), 1)
        unit = normalized["entities"][0]
        self.assertEqual(unit["id"], "TFT18_KhaZix")
        self.assertEqual(
            unit["attributes"]["recommended_item_ids"],
            [
                "TFT_Item_LichBane",
                "TFT_Item_EdgeOfNight",
                "TFT_Item_HandOfJustice",
            ],
        )
        self.assertEqual(
            unit["attributes"]["positioning"],
            "in the front row",
        )

    def test_trait_detail_unit_table_is_typed_as_units(self):
        raw = {
            "source_url": "https://www.metatft.com/traits/heroic",
            "captured_at_epoch": 1000.0,
            "title": "TFT heroic Trait - Stats, Units and Best Comps",
            "headings": ["TFT heroic Trait"],
            "tables": [
                {
                    "table_index": 0,
                    "rows": [
                        ["Unit", "Tier", "Avg Place", "Win Rate", "Frequency"],
                        ["Kha'Zix", "S", "3.90", "16.0%", "20,000 4.0%"],
                    ],
                }
            ],
            "body_text": "Ranked\n18.3b\nLast 3 Days\nPlatinum +\nSet 18",
            "links": [],
            "repeated_blocks": [],
            "sections": [],
        }

        normalized = normalize_browser_snapshot(raw)
        self.assertEqual(len(normalized["entities"]), 1)
        self.assertEqual(normalized["entities"][0]["kind"], "unit")



class MetaTftCompCardTests(unittest.TestCase):
    def test_comp_card_requires_enough_signal_and_resolves_units(self):
        raw = {
            "source": "metatft_public_browser",
            "source_url": "https://www.metatft.com/comps",
            "captured_at_epoch": 1000.0,
            "title": "MetaTFT Comps",
            "headings": ["TFT Meta Comps"],
            "tables": [],
            "body_text": "Ranked\n18.3b\nLast 3 Days\nPlatinum +\nSet 18",
            "links": [],
            "sections": [],
            "repeated_blocks": [
                {
                    "index": 0,
                    "tag": "LI",
                    "text": (
                        "Void Flex\n"
                        "S\n"
                        "3.91\n"
                        "Avg Place\n"
                        "17.2%\n"
                        "Win Rate\n"
                        "18,250 5.4%\n"
                        "Frequency"
                    ),
                    "image_alts": ["Kha'Zix", "Rakan", "Akali", "Void"],
                    "links": [
                        {
                            "text": "Void Flex",
                            "href": "https://www.metatft.com/comps/void-flex",
                        }
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            units = root / "units.json"
            traits = root / "traits.json"

            units.write_text(
                json.dumps(
                    {
                        "champions": [
                            {"api_name": "TFT18_KhaZix", "name": "Kha'Zix"},
                            {"api_name": "TFT18_Rakan", "name": "Rakan"},
                            {"api_name": "TFT18_Akali", "name": "Akali"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            traits.write_text(
                json.dumps(
                    {
                        "traits": [
                            {"api_name": "TFT18_Void", "name": "Void"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            resolver = CatalogResolver.from_catalogs(
                unit_catalog=units,
                trait_catalog=traits,
            )
            normalized = normalize_browser_snapshot(raw, resolver=resolver)

        self.assertEqual(len(normalized["entities"]), 1)
        comp = normalized["entities"][0]
        self.assertEqual(comp["kind"], "comp")
        self.assertEqual(comp["name"], "Void Flex")
        self.assertEqual(
            comp["unit_ids"],
            ["TFT18_KhaZix", "TFT18_Rakan", "TFT18_Akali"],
        )
        self.assertEqual(comp["trait_ids"], ["TFT18_Void"])
        self.assertEqual(comp["performance"]["avg_place"], 3.91)
        self.assertEqual(comp["performance"]["win_rate"], 0.172)
        self.assertAlmostEqual(
            comp["performance"]["frequency"],
            0.054,
            places=9,
        )
        self.assertEqual(comp["performance"]["sample_size"], 18250)

    def test_weak_comp_like_block_stays_unparsed(self):
        raw = {
            "source_url": "https://www.metatft.com/comps",
            "captured_at_epoch": 1000.0,
            "title": "MetaTFT Comps",
            "headings": [],
            "tables": [],
            "body_text": "Ranked\n18.3b",
            "links": [],
            "sections": [],
            "repeated_blocks": [
                {
                    "index": 0,
                    "tag": "LI",
                    "text": "Random UI\n4.10\nAvg Place",
                    "image_alts": [],
                    "links": [],
                }
            ],
        }

        normalized = normalize_browser_snapshot(raw)
        self.assertEqual(normalized["entities"], [])
        self.assertEqual(
            len(normalized["diagnostics"]["unparsed_comp_blocks"]),
            1,
        )
