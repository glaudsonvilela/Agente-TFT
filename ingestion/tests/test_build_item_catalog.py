from __future__ import annotations

import unittest

from ingestion.build_item_catalog import build_catalog


class ItemCatalogTests(unittest.TestCase):
    def test_normalizes_tft_items(self):
        source = {
            "items": [
                {
                    "apiName": "TFT_Item_Test",
                    "name": "Test Item",
                    "desc": "Test",
                    "effects": {"AD": 10, "Flag": True},
                    "composition": ["TFT_Item_A", "TFT_Item_B"],
                    "icon": "ASSETS/Items/Icons/test.png",
                    "unique": True,
                },
                {
                    "apiName": "OtherGame_Item",
                    "name": "Other",
                },
            ]
        }
        catalog = build_catalog(source)
        self.assertEqual(catalog["item_count"], 1)
        item = catalog["items"][0]
        self.assertEqual(item["api_name"], "TFT_Item_Test")
        self.assertEqual(item["effects"]["AD"], 10)
        self.assertTrue(item["unique"])


if __name__ == "__main__":
    unittest.main()
