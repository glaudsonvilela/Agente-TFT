"""Equipped artwork stays linked to bar evidence, without a unit or item ID."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from training.board_hub_equipped_candidates import run
from training.board_hub_item_candidates import select_entries


ROOT = Path(__file__).parents[2]
BOARD = json.loads((ROOT / "configs/ui/match001-board-bench-v1.json").read_text())
POSITION = json.loads((ROOT / "configs/ui/match001-bar-to-cell-candidates-v1.json").read_text())
EQUIPPED = json.loads((ROOT / "configs/ui/match001-equipped-icons-v1.json").read_text())


class EquippedCandidateTests(unittest.TestCase):
    def test_set_path_scope_uses_catalog_not_video_inventory(self):
        rows = [{"key": "TFTSet18/Set18_Items/a", "id": "a"},
                {"key": "TFTSet17/Set17_Items/b", "id": "b"}]
        self.assertEqual([x["id"] for x in select_entries(rows, "TFTSet18", "set_path")], ["a"])
        self.assertEqual(len(select_entries(rows, "TFTSet18", "all")), 2)
        expanded = rows + [{"key": "TFT_Item_GuinsoosRageblade", "id": "TFT_Item_GuinsoosRageblade"},
                           {"key": "Set5_RadiantItems/one", "id": "radiant"}]
        self.assertEqual([x["id"] for x in select_entries(expanded, "TFTSet18", "set_plus_core")],
                         ["a", "TFT_Item_GuinsoosRageblade", "radiant"])

    def test_visible_equipped_icon_links_to_marker_and_candidate_cell(self):
        with tempfile.TemporaryDirectory() as temp:
            icon_dir = Path(temp)
            art = np.zeros((23, 23, 3), dtype=np.uint8)
            art[:, :12] = (235, 45, 25)
            other = np.zeros((23, 23, 3), dtype=np.uint8)
            other[:, :] = (20, 210, 70)
            Image.fromarray(art).save(icon_dir / "a.png")
            Image.fromarray(other).save(icon_dir / "b.png")
            frame = Image.new("RGB", (1920, 1080), (70, 70, 70))
            frame.paste(Image.fromarray(art), (625, 330))
            read = {"profile": BOARD["id"], "projection_status": "reference_arena_match",
                    "markers": [{"id": 0, "color": "green",
                                 "rect": {"x": 631, "y": 320, "width": 64, "height": 4}}]}
            entries = [{"key": "TFTSet18/a", "id": "a", "icon": "a.png"},
                       {"key": "TFTSet18/b", "id": "b", "icon": "b.png"}]
            manifest = {"reference_sha256": "test", "version": "16.19.1", "set_key": "TFTSet18"}
            result = run(frame, read, BOARD, POSITION, EQUIPPED, manifest, entries, icon_dir,
                         "set_path")
            row = result["markers"][0]
            self.assertEqual((row["position_candidate"]["row"],
                              row["position_candidate"]["cell_or_slot"]), (0, 1))
            self.assertEqual(row["slots"][0]["status"], "icon_candidate")
            self.assertEqual(row["slots"][0]["candidates"][0]["ids_with_same_template"], ["a"])
            self.assertEqual(row["slots"][0]["candidates"][0]["sample_rect"],
                             {"x": 625, "y": 330, "width": 23, "height": 23})
            self.assertEqual(row["slots"][1]["status"], "empty_appearance")
            self.assertIsNone(row["slots"][0]["item_id"])
            self.assertIsNone(row["unit_id"])
            self.assertFalse(result["game_state_updated"])
            read["projection_status"] = "unresolved"
            self.assertEqual(run(frame, read, BOARD, POSITION, EQUIPPED, manifest,
                                 entries, icon_dir, "set_path")["markers"], [])


if __name__ == "__main__":
    unittest.main()
