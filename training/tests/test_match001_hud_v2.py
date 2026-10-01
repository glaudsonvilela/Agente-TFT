from __future__ import annotations

import json
import math
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[2]
BOXES = [(766, 5, 36, 25), (1020, 885, 33, 25), (390, 883, 22, 24), (466, 884, 49, 20)]


def f32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


class Match001HudV2Tests(unittest.TestCase):
    def setUp(self):
        self.layout = json.loads((ROOT / "configs/hud/tft-1920x1080-match001-v2.json").read_text())

    def test_same_contract_and_static_fields_only(self):
        self.assertEqual(self.layout["schema_version"], 1)
        self.assertEqual([r["field"] for r in self.layout["regions"]], ["stage", "gold", "level", "xp"])
        self.assertEqual((self.layout["reference_width"], self.layout["reference_height"]), (1920, 1080))

    def test_normalized_boxes_stay_inside_frame(self):
        for region in self.layout["regions"]:
            r = region["rect"]
            self.assertGreaterEqual(r["x"], 0)
            self.assertGreaterEqual(r["y"], 0)
            self.assertGreater(r["width"], 0)
            self.assertGreater(r["height"], 0)
            self.assertLessEqual(r["x"] + r["width"], 1)
            self.assertLessEqual(r["y"] + r["height"], 1)

    def test_f32_rasterization_matches_measured_pixels(self):
        for region, expected in zip(self.layout["regions"], BOXES, strict=True):
            r = {key: f32(v) for key, v in region["rect"].items()}
            x, y = math.floor(f32(r["x"] * 1920)), math.floor(f32(r["y"] * 1080))
            right = math.ceil(f32(f32(r["x"] + r["width"]) * 1920))
            bottom = math.ceil(f32(f32(r["y"] + r["height"]) * 1080))
            self.assertEqual((x, y, right - x, bottom - y), expected)

    def test_does_not_lower_default_confidence_to_fit_replay(self):
        for r in self.layout["regions"]:
            self.assertNotIn("policy", r)


if __name__ == "__main__":
    unittest.main()
