from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ingestion.build_knowledge_pack import build_pack


class KnowledgePackTests(unittest.TestCase):
    def fixture(self):
        return {
            "items": [
                {
                    "apiName": "TFT_Item_Test",
                    "name": "Item",
                    "effects": {},
                }
            ],
            "sets": {
                "17": {
                    "name": "Example",
                    "traits": [
                        {
                            "apiName": "TFT17_Trait",
                            "name": "Trait",
                            "effects": [],
                        }
                    ],
                    "champions": [
                        {
                            "apiName": "TFT17_A",
                            "name": "Alpha",
                            "cost": 1,
                            "traits": ["TFT17_Trait"],
                        }
                    ],
                }
            },
            "setData": [],
        }

    def test_builds_reproducible_pack_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = build_pack(
                self.fixture(),
                set_selector="17",
                output_dir=root,
            )

            self.assertEqual(first["counts"]["units"], 1)
            self.assertEqual(first["counts"]["items"], 1)
            self.assertEqual(first["counts"]["traits"], 1)
            self.assertTrue((root / "units.json").exists())
            self.assertTrue((root / "items.json").exists())
            self.assertTrue((root / "traits.json").exists())
            self.assertTrue((root / "manifest.json").exists())

            second = build_pack(
                self.fixture(),
                set_selector="17",
                output_dir=root,
            )
            self.assertEqual(
                first["pack_sha256"],
                second["pack_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
