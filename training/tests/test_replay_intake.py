from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from training.replay_intake import validate_annotations


class ReplayIntakeTests(unittest.TestCase):
    def valid_annotations(self) -> dict:
        return {
            "schema_version": 1,
            "source_video": "match.mp4",
            "frames": [
                {
                    "timestamp_ms": i * 1000,
                    "image": f"frames/{i:04d}.jpg",
                    "scene": "planning_shop",
                    "hp": 100,
                    "gold": i,
                    "level": 4,
                    "stage": "2-1",
                    "shop": ["A", "B", "C", "D", "E"],
                    "board_unit_ids": ["A", "B"],
                    "lobby_player_ids": ["p1", "p2"],
                }
                for i in range(20)
            ],
        }

    def test_valid_annotations_are_ready(self):
        report = validate_annotations(self.valid_annotations())
        self.assertTrue(report["ready_for_calibration"])
        self.assertTrue(report["sample_sufficient_for_first_pass"])
        self.assertEqual(report["errors"], [])

    def test_duplicate_timestamp_is_blocker(self):
        value = self.valid_annotations()
        value["frames"][1]["timestamp_ms"] = value["frames"][0]["timestamp_ms"]
        report = validate_annotations(value)
        self.assertIn("TIMESTAMP_DUPLICATE", {row["code"] for row in report["errors"]})
        self.assertFalse(report["ready_for_calibration"])

    def test_shop_must_have_five_slots(self):
        value = self.valid_annotations()
        value["frames"][0]["shop"] = ["A", "B"]
        report = validate_annotations(value)
        self.assertIn("SHOP_LENGTH_INVALID", {row["code"] for row in report["errors"]})

    def test_timestamp_outside_video_is_blocker(self):
        value = self.valid_annotations()
        value["frames"][-1]["timestamp_ms"] = 50_000
        report = validate_annotations(value, video_duration_ms=20_000)
        self.assertIn("TIMESTAMP_OUTSIDE_VIDEO", {row["code"] for row in report["errors"]})

    def test_source_video_mismatch_is_blocker(self):
        report = validate_annotations(
            self.valid_annotations(),
            expected_video_name="other.mp4",
        )
        self.assertIn("SOURCE_VIDEO_MISMATCH", {row["code"] for row in report["errors"]})

    def test_missing_extracted_image_is_blocker_when_directory_is_known(self):
        value = self.valid_annotations()
        with tempfile.TemporaryDirectory() as directory:
            report = validate_annotations(value, annotation_dir=Path(directory))
        self.assertIn("IMAGE_MISSING", {row["code"] for row in report["errors"]})

    def test_small_sample_is_warning_not_structural_failure(self):
        value = self.valid_annotations()
        value["frames"] = value["frames"][:5]
        report = validate_annotations(value)
        self.assertTrue(report["ready_for_calibration"])
        self.assertFalse(report["sample_sufficient_for_first_pass"])
        self.assertIn("FIRST_PASS_SAMPLE_SMALL", {row["code"] for row in report["warnings"]})

    def test_duplicate_lobby_id_is_blocker(self):
        value = self.valid_annotations()
        value["frames"][0]["lobby_player_ids"] = ["p1", "p1"]
        report = validate_annotations(value)
        self.assertIn("LOBBY_ID_DUPLICATE", {row["code"] for row in report["errors"]})


if __name__ == "__main__":
    unittest.main()
