"""The combined board view preserves missing identities and fixed topology."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from training.board_hub_snapshot import build_snapshot


ROOT = Path(__file__).parents[2]
read_json = lambda name: json.loads((ROOT / name).read_text())
BOARD = read_json("configs/ui/match001-board-bench-v1.json")
POSITION = read_json("configs/ui/match001-bar-to-cell-candidates-v1.json")
EQUIPPED = read_json("configs/ui/match001-equipped-icons-v1.json")
INVENTORY = read_json("configs/ui/match001-inventory-v1.json")


class SnapshotTests(unittest.TestCase):
    def test_same_marker_has_candidate_cell_and_equipped_art_but_no_champion(self):
        with tempfile.TemporaryDirectory() as temp:
            icon_dir = Path(temp)
            art = Image.new("RGB", (48, 48))
            pixels = np.asarray(art).copy()
            pixels[:, :24] = (230, 45, 25)
            art = Image.fromarray(pixels)
            art.save(icon_dir / "a.png")
            frame = Image.new("RGB", (1920, 1080))
            frame.paste((170, 90, 20), (27, 273, 48, 294))
            frame.paste(art.resize((28, 28)), (18, 323))
            frame.paste(art.resize((23, 23)), (625, 330))
            read = {"timestamp_ms": 1300000, "profile": BOARD["id"],
                    "projection_status": "reference_arena_match",
                    "markers": [{"id": 0, "color": "green",
                                 "rect": {"x": 631, "y": 320, "width": 64, "height": 4}}]}
            manifest = {"reference_sha256": "test", "version": "16.19.1", "set_key": "TFTSet18"}
            entries = [{"key": "TFTSet18/items/a", "id": "a", "icon": "a.png"}]
            context = {"schema_version": 1, "set_key": "TFTSet18", "tft_patch": "18.3",
                       "version_basis": "user date and Riot schedule"}
            result = build_snapshot(frame, read, BOARD, POSITION, EQUIPPED, INVENTORY,
                                    manifest, entries, icon_dir, "set_path", context)
            self.assertEqual(result["arena_projection_status"], "reference_arena_match")
            self.assertEqual(result["position_status"], "candidate_only")
            self.assertEqual(result["tft_patch"], "18.3")
            self.assertEqual(result["visual_reference_patch_compatibility"], "unverified")
            self.assertEqual((len(result["board_cells"]), len(result["bench_slots"])), (28, 9))
            self.assertEqual(result["board_cells"][1]["marker_candidates"], [0])
            self.assertIsNone(result["board_cells"][1]["occupancy"])
            self.assertEqual(result["observed_markers"][0]["equipped_slots"][0]["status"],
                             "icon_candidate")
            self.assertEqual(result["inventory"]["candidate_slots"][0]["slot"], 1)
            self.assertIsNone(result["observed_markers"][0]["champion_id"])
            self.assertFalse(any(result["capabilities"].values()))
            context["set_key"] = "TFTSet17"
            with self.assertRaisesRegex(ValueError, "context"):
                build_snapshot(frame, read, BOARD, POSITION, EQUIPPED, INVENTORY,
                               manifest, entries, icon_dir, "set_path", context)


if __name__ == "__main__":
    unittest.main()
