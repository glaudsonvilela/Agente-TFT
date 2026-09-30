from __future__ import annotations

import unittest

from ingestion.normalize_cdragon import normalize_cdragon, select_set


def fixture() -> dict:
    return {
        "items": [
            {
                "apiName": "Item_A",
                "name": "Item A",
                "isAugment": False,
                "effects": {"x": 1},
            },
            {
                "apiName": "Aug_A",
                "name": "Augment A",
                "isAugment": True,
            },
            {
                "apiName": "Item_Other",
                "name": "Other",
                "isAugment": False,
            },
        ],
        "setData": [
            {
                "number": 17,
                "name": "Set 17",
                "mutator": "TFTSet17",
                "champions": [
                    {
                        "apiName": "TFT17_Champ",
                        "characterName": "TFT17_Champ",
                        "name": "Champion",
                        "cost": 4,
                        "traits": ["TFT17_Trait"],
                    }
                ],
                "traits": [
                    {
                        "apiName": "TFT17_Trait",
                        "name": "Trait",
                        "effects": [],
                    }
                ],
                "items": ["Item_A"],
                "augments": ["Aug_A"],
            },
            {
                "number": 16,
                "name": "Set 16",
                "mutator": "TFTSet16",
                "champions": [],
                "traits": [],
            },
        ],
        "sets": {},
    }


class NormalizeCdragonTests(unittest.TestCase):
    def test_selects_set_by_mutator(self) -> None:
        selected = select_set(fixture(), selector="TFTSet17")
        self.assertEqual(selected["number"], 17)

    def test_normalizes_compact_static_pack(self) -> None:
        data = normalize_cdragon(
            fixture(),
            selector="Set 17",
            source_sha256="abc",
            source_path="fixture.json",
        )

        self.assertEqual(data["counts"]["champions"], 1)
        self.assertEqual(data["counts"]["traits"], 1)
        self.assertEqual(data["counts"]["items"], 1)
        self.assertEqual(data["counts"]["augments"], 1)
        self.assertEqual(data["champions"][0]["api_name"], "TFT17_Champ")
        self.assertEqual(data["items"][0]["api_name"], "Item_A")
        self.assertEqual(data["augments"][0]["api_name"], "Aug_A")

    def test_supports_object_shaped_set_data(self) -> None:
        raw = fixture()
        raw["setData"] = {
            "17": raw["setData"][0],
            "16": raw["setData"][1],
        }
        selected = select_set(raw, selector="TFTSet17")
        self.assertEqual(selected["number"], 17)

    def test_ambiguous_selector_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            select_set(fixture(), selector="Set")


if __name__ == "__main__":
    unittest.main()
