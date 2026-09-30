from __future__ import annotations

import unittest
from pathlib import Path

from training.prepare_replay_annotations import (
    annotation_template,
    interval_timestamps,
    parse_timestamps_ms,
)


class ReplayAnnotationPreparationTests(unittest.TestCase):
    def test_parse_timestamps_is_sorted_and_deduplicated(self):
        self.assertEqual(
            parse_timestamps_ms("3000,1000,3000,2000"),
            [1000, 2000, 3000],
        )

    def test_interval_respects_start_and_limit(self):
        self.assertEqual(
            interval_timestamps(
                10_000,
                2_000,
                start_ms=1_000,
                max_frames=3,
            ),
            [1_000, 3_000, 5_000],
        )

    def test_annotation_template_keeps_frame_reference(self):
        value = annotation_template(
            Path("/tmp/match.mp4"),
            [1000, 2000],
            [
                "frames/0001_000001000ms.jpg",
                "frames/0002_000002000ms.jpg",
            ],
        )

        self.assertEqual(value["schema_version"], 1)
        self.assertEqual(value["source_video"], "match.mp4")
        self.assertEqual(value["frames"][0]["timestamp_ms"], 1000)
        self.assertEqual(
            value["frames"][1]["image"],
            "frames/0002_000002000ms.jpg",
        )

    def test_negative_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_timestamps_ms("100,-1")


if __name__ == "__main__":
    unittest.main()
