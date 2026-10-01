from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from training.roi_replay_report import load_events, summarize


class RoiReplayReportTests(unittest.TestCase):
    def test_summarize_counts_rois_and_scores(self):
        events = [
            {
                "frame_id": 1,
                "timestamp_ms": 1000,
                "changes": [
                    {"roi": "shop", "score": 0.2},
                    {"roi": "gold", "score": 0.1},
                ],
            },
            {
                "frame_id": 2,
                "timestamp_ms": 2000,
                "changes": [{"roi": "shop", "score": 0.4}],
            },
            {
                "frame_id": 3,
                "timestamp_ms": 3000,
                "changes": [{"roi": "board", "score": 0.5}],
            },
        ]

        report = summarize(events)
        self.assertEqual(report["total_changes"], 4)
        self.assertEqual(report["frames_with_changes"], 3)
        self.assertEqual(report["per_roi"]["shop"]["changes"], 2)
        self.assertAlmostEqual(report["per_roi"]["shop"]["score_p50"], 0.3)
        self.assertEqual(report["per_roi"]["shop"]["gap_ms_p50"], 1000.0)
        self.assertEqual(report["top_cochanges"][0]["rois"], ["gold", "shop"])

    def test_load_events_tracks_malformed_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text(
                json.dumps({"timestamp_ms": 1, "changes": []})
                + "\nnot-json\n"
                + json.dumps([1, 2, 3])
                + "\n",
                encoding="utf-8",
            )
            events, malformed = load_events(path)
            self.assertEqual(len(events), 1)
            self.assertEqual(malformed, 2)

    def test_empty_input_is_safe(self):
        report = summarize([])
        self.assertEqual(report["total_changes"], 0)
        self.assertEqual(report["per_roi"], {})
        self.assertIsNone(report["duration_between_changes_ms"])


if __name__ == "__main__":
    unittest.main()
