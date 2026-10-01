from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class Match001LayoutConfigTests(unittest.TestCase):
    def load(self, relative: str) -> dict:
        return json.loads((ROOT / relative).read_text(encoding="utf-8"))

    def assert_rect(self, rect: dict) -> None:
        for key in ("x", "y", "width", "height"):
            self.assertIn(key, rect)
            self.assertIsInstance(rect[key], (int, float))
        self.assertGreaterEqual(rect["x"], 0)
        self.assertGreaterEqual(rect["y"], 0)
        self.assertGreater(rect["width"], 0)
        self.assertGreater(rect["height"], 0)
        self.assertLessEqual(rect["x"] + rect["width"], 1)
        self.assertLessEqual(rect["y"] + rect["height"], 1)

    def test_roi_profile_is_normalized_and_unique(self):
        value = self.load("configs/roi/tft-1920x1080-match001-v1.json")
        self.assertEqual(value["reference_width"], 1920)
        self.assertEqual(value["reference_height"], 1080)
        keys = [row["key"] for row in value["rois"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn("player_list", keys)
        self.assertNotIn("hp", keys)
        for row in value["rois"]:
            self.assert_rect(row["rect"])
            self.assertGreater(row["sample_step"], 0)
            self.assertGreaterEqual(row["change_threshold"], 0)
            self.assertLessEqual(row["change_threshold"], 1)

    def test_hud_layout_contains_only_static_fields(self):
        value = self.load("configs/hud/tft-1920x1080-match001-v1.json")
        fields = [row["field"] for row in value["regions"]]
        self.assertEqual(fields, ["stage", "gold", "level", "xp"])
        self.assertNotIn("hp", fields)
        for row in value["regions"]:
            self.assert_rect(row["rect"])


if __name__ == "__main__":
    unittest.main()
