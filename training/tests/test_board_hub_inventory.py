"""Visual inventory evidence stays separate from item identity and GameState."""
import copy
import json
from pathlib import Path
import unittest

from training.board_hub_inventory import observe, validate_profile


PROFILE = json.loads((Path(__file__).parents[2] / "configs/ui/match001-inventory-v1.json").read_text())
WIDTH, HEIGHT = 1920, 1080


def paint(image, x, y, width, height, color):
    row = bytes(color) * width
    for py in range(y, y + height):
        start = (py * WIDTH + x) * 3
        image[start:start + len(row)] = row


class InventoryTests(unittest.TestCase):
    def test_located_panel_distinguishes_icon_empty_and_unknown(self):
        frame = bytearray(WIDTH * HEIGHT * 3)
        paint(frame, 27, 273, 21, 21, (170, 90, 20))
        paint(frame, 18, 323, 30, 29, (130, 130, 130))  # neutral item icon, not only saturated colors
        paint(frame, 18, 376, 30, 4, (130, 130, 130))   # too little visual support
        result = observe(frame, WIDTH, HEIGHT, PROFILE)
        self.assertEqual(result["panel_status"], "located")
        self.assertEqual([slot["status"] for slot in result["slots"][:4]],
                         ["unclassified_stack", "icon_candidate", "unknown", "empty_appearance"])
        self.assertTrue(all(slot["item_id"] is None for slot in result["slots"]))
        self.assertFalse(result["game_state_updated"])

    def test_missing_panel_does_not_report_empty_items(self):
        frame = bytearray(WIDTH * HEIGHT * 3)
        result = observe(frame, WIDTH, HEIGHT, PROFILE)
        self.assertEqual(result["panel_status"], "unavailable")
        self.assertEqual({slot["status"] for slot in result["slots"]}, {"unavailable"})

    def test_resolution_buffer_and_profile_errors(self):
        frame = bytearray(WIDTH * HEIGHT * 3)
        for width, height, pixels in ((1280, 720, frame), (WIDTH, HEIGHT, frame[:-1])):
            with self.assertRaises(ValueError):
                observe(pixels, width, height, PROFILE)
        bad = copy.deepcopy(PROFILE)
        bad["icon_inner_size"]["width"] = 100
        with self.assertRaises(ValueError):
            validate_profile(bad)


if __name__ == "__main__":
    unittest.main()
