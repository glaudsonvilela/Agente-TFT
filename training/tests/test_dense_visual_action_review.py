import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from training.mine_dense_action_candidates import mine


class DenseVisualReviewTest(unittest.TestCase):
    def test_pixel_change_is_only_a_review_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / "frames"
            frames.mkdir()
            before = Image.new("RGB", (1920, 1080), "black")
            after = before.copy()
            ImageDraw.Draw(after).rectangle((560, 925, 750, 1075), fill="white")
            before.save(frames / "frame-0001.jpg")
            after.save(frames / "frame-0002.jpg")
            output = root / "queue.jsonl"
            rows = mine(frames, output)
            self.assertEqual(len(rows), 1)
            self.assertGreater(rows[0]["region_change"]["shop"], 0)
            self.assertEqual(rows[0]["executed_action_label"], None)
            self.assertEqual(json.loads(output.read_text())["review_status"],
                             "unreviewed_visual_transition")

    def test_missing_frame_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            frames = Path(directory)
            Image.new("RGB", (1920, 1080)).save(frames / "frame-0001.jpg")
            Image.new("RGB", (1920, 1080)).save(frames / "frame-0003.jpg")
            with self.assertRaisesRegex(ValueError, "gap"):
                mine(frames, frames / "queue.jsonl")


if __name__ == "__main__":
    unittest.main()
