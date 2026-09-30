from __future__ import annotations

import unittest

from ingestion.build_unit_catalog import (
    build_catalog,
    communitydragon_asset_url,
    find_set,
    iter_sets,
)


class UnitCatalogTests(unittest.TestCase):
    def fixture(self):
        return {
            "items": [],
            "sets": {
                "17": {
                    "name": "Example Set",
                    "traits": [{"apiName": "TFT17_Trait"}],
                    "champions": [
                        {
                            "apiName": "TFT17_A",
                            "characterName": "TFT17_A",
                            "name": "Alpha",
                            "cost": 1,
                            "role": "Carry",
                            "traits": ["TFT17_Trait"],
                            "icon": "ASSETS/Characters/TFT17_A/HUD/icon.tex",
                            "squareIcon": "ASSETS/Characters/TFT17_A/HUD/square.png",
                            "tileIcon": "ASSETS/Characters/TFT17_A/HUD/tile.png",
                        },
                        {
                            "apiName": "TFT17_Spawn",
                            "name": "Spawn",
                            "cost": 1,
                            "traits": ["TFT17_Trait"],
                            "isSpawn": True,
                        },
                        {
                            "apiName": "TFT17_Bad",
                            "name": "Bad",
                            "cost": 0,
                            "traits": ["TFT17_Trait"],
                        },
                    ],
                }
            },
            "setData": [],
        }

    def test_lists_and_finds_explicit_set(self):
        sets = iter_sets(self.fixture())
        selected = find_set(sets, "17")
        self.assertEqual(selected.name, "Example Set")

    def test_catalog_filters_non_playable_units(self):
        source = self.fixture()
        target = find_set(iter_sets(source), "17")
        catalog = build_catalog(source, target)
        self.assertEqual(catalog["champion_count"], 1)
        self.assertEqual(catalog["champions"][0]["api_name"], "TFT17_A")

    def test_asset_path_maps_to_latest_game_root(self):
        self.assertEqual(
            communitydragon_asset_url(
                "ASSETS/Characters/TFT17_A/HUD/Square.PNG"
            ),
            "https://raw.communitydragon.org/latest/game/assets/characters/tft17_a/hud/square.png",
        )

    def test_missing_set_is_explicit(self):
        with self.assertRaises(ValueError):
            find_set(iter_sets(self.fixture()), "does-not-exist")


if __name__ == "__main__":
    unittest.main()
