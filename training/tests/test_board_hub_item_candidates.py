"""Artwork similarity yields inspectable candidates, never semantic item IDs."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from training.board_hub_item_candidates import load_reference, run


ROOT = Path(__file__).parents[2]
PROFILE = json.loads((ROOT / "configs/ui/match001-inventory-v1.json").read_text())


class ItemCandidateTests(unittest.TestCase):
    def test_reference_is_pinned_and_complete_catalog_is_separate_from_replay(self):
        folder = next((ROOT / "knowledge/riot-ddragon/16.19.1/pt_BR/TFTSet18").iterdir())
        manifest, entries = load_reference(folder)
        self.assertEqual(manifest["tft_patch"], None)
        self.assertEqual(len(entries), 1188)
        self.assertEqual(manifest["components"]["items"]["count"], len(entries))

    def test_exact_art_groups_aliases_without_establishing_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            icon_dir = Path(temp)
            art = np.zeros((28, 28, 3), dtype=np.uint8)
            art[:, :14] = (230, 90, 25)
            other = np.zeros((28, 28, 3), dtype=np.uint8)
            other[:, :] = (30, 180, 90)
            for name, pixels in (("a.png", art), ("alias.png", art), ("other.png", other)):
                Image.fromarray(pixels).save(icon_dir / name)
            frame = Image.new("RGB", (1920, 1080))
            frame.paste((170, 90, 20), (27, 273, 48, 294))
            frame.paste(Image.fromarray(art), (18, 323))
            entries = [{"id": name, "icon": filename} for name, filename in
                       (("A", "a.png"), ("A_alias", "alias.png"), ("B", "other.png"))]
            result = run(frame, PROFILE, {"reference_sha256": "test", "version": "16.19.1"},
                         entries, icon_dir)
            self.assertEqual(result["inventory"]["panel_status"], "located")
            self.assertEqual(result["icon_assets_available"], 3)
            self.assertEqual(result["unique_artworks"], 2)
            self.assertEqual(len(result["candidate_slots"]), 1)
            row = result["candidate_slots"][0]
            self.assertEqual(row["status"], "candidate_only")
            self.assertEqual(row["candidates"][0]["ids_with_same_template"], ["A", "A_alias"])
            self.assertEqual(row["candidates"][0]["catalog_options"],
                             [{"visual_id": "A", "name": "A"},
                              {"visual_id": "A_alias", "name": "A_alias"}])
            self.assertEqual(row["candidates"][0]["rms"], 0)
            self.assertIsNone(row["item_id"])
            self.assertFalse(result["item_identity_established"])
            self.assertFalse(result["game_state_updated"])
            (icon_dir / "other.png").unlink()
            partial = run(frame, PROFILE, {"reference_sha256": "test", "version": "16.19.1"},
                          entries, icon_dir)
            self.assertEqual(partial["candidate_slots"][0]["status"], "incomplete_catalog")


if __name__ == "__main__":
    unittest.main()
