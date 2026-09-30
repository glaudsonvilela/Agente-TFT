from __future__ import annotations

import unittest

from ingestion.build_trait_catalog import build_catalog


class TraitCatalogTests(unittest.TestCase):
    def fixture(self):
        return {
            "sets": {
                "17": {
                    "name": "Example",
                    "champions": [],
                    "traits": [
                        {
                            "apiName": "TFT17_Trait_Test",
                            "name": "Test Trait",
                            "desc": "Trait desc",
                            "icon": "ASSETS/Traits/test.png",
                            "effects": [
                                {
                                    "minUnits": 2,
                                    "maxUnits": 3,
                                    "style": 1,
                                    "variables": {"Bonus": 10},
                                }
                            ],
                        }
                    ],
                }
            },
            "setData": [],
        }

    def test_builds_explicit_set_traits(self):
        catalog = build_catalog(self.fixture(), "17")
        self.assertEqual(catalog["trait_count"], 1)
        trait = catalog["traits"][0]
        self.assertEqual(trait["api_name"], "TFT17_Trait_Test")
        self.assertEqual(trait["effects"][0]["min_units"], 2)


if __name__ == "__main__":
    unittest.main()
