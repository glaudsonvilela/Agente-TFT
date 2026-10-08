import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from training.mine_dense_action_candidates import mine
from training.validate_dense_action_review import validate


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
            self.assertEqual(set(rows[0]["review_rank_by_region"]),
                             {"stage", "gold", "xp", "shop", "bench", "board",
                              "items", "opponents"})
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

    def test_review_checks_xp_level_crossing_and_frame_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def pair(start):
                row = {}
                for side, number in (("before", start), ("after", start + 1)):
                    name = f"frame-{number:04d}.jpg"
                    data = name.encode()
                    (root / name).write_bytes(data)
                    row[side] = name
                    row[f"{side}_sha256"] = hashlib.sha256(data).hexdigest()
                return row

            action = dict(pair(1), type="buy_xp", stage="4-1", gold_before=47,
                          gold_after=43, xp_cost=4, xp_gained=4, level_before=7,
                          level_after=8, xp_before=51, xp_after=1,
                          xp_to_next_before=54, visual_evidence="XP bar crosses level")
            hard_case = dict(pair(3), review_status="natural_round_transition",
                             stage_before="3-7", stage_after="4-1", gold_before=53,
                             gold_after=64, visual_evidence="Planning banner appears")
            manifest = root / "review.json"
            record = {"source_resolution": [1920, 1080], "sampling_fps": 5,
                      "actions": [action], "hard_cases": [hard_case]}
            manifest.write_text(json.dumps(record))
            self.assertEqual(validate(manifest, root)["reviewed_actions"], 1)
            action["xp_after"] = 2
            manifest.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "XP bar"):
                validate(manifest, root)


if __name__ == "__main__":
    unittest.main()
