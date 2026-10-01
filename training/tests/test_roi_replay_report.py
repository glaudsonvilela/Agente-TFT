from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from training.roi_replay_report import canonical_roi, load_events, summarize


class RoiReplayReportTests(unittest.TestCase):
    def test_summarize_counts_raw_and_semantic_events(self):
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
                "timestamp_ms": 1800,
                "changes": [{"roi": "shop", "score": 0.4}],
            },
            {
                "frame_id": 3,
                "timestamp_ms": 4000,
                "changes": [{"roi": "board", "score": 0.5}],
            },
        ]

        report = summarize(events)
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["raw"]["total_changes"], 4)
        self.assertEqual(report["semantic"]["total_changes"], 4)
        self.assertEqual(report["semantic"]["per_roi"]["shop"]["changes"], 2)
        self.assertEqual(report["semantic"]["per_roi"]["shop"]["episodes"], 1)
        self.assertAlmostEqual(
            report["semantic"]["per_roi"]["shop"]["score_p50"],
            0.3,
        )
        self.assertEqual(
            report["semantic"]["per_roi"]["shop"]["gap_ms_p50"],
            800.0,
        )
        self.assertEqual(
            report["top_cochanges"][0]["rois"],
            ["gold", "shop"],
        )

    def test_global_cut_is_kept_raw_but_removed_from_semantic(self):
        all_rois = [
            "bench",
            "board",
            "gold",
            "items",
            "levelxp",
            "playerlist",
            "shop",
            "stage",
        ]
        events = [
            {
                "frame_id": 1,
                "timestamp_ms": 1000,
                "changes": [
                    {"roi": roi, "score": 1.0}
                    for roi in all_rois
                ],
            },
            {
                "frame_id": 2,
                "timestamp_ms": 5000,
                "changes": [{"roi": "shop", "score": 0.4}],
            },
        ]

        report = summarize(events, global_cut_min_rois=6)
        self.assertEqual(report["global_cuts"]["frames"], 1)
        self.assertEqual(report["raw"]["total_changes"], 9)
        self.assertEqual(report["semantic"]["total_changes"], 1)
        self.assertEqual(report["semantic"]["per_roi"]["shop"]["changes"], 1)
        self.assertNotIn("board", report["semantic"]["per_roi"])

    def test_episode_gap_splits_distant_changes(self):
        events = [
            {
                "timestamp_ms": 1000,
                "changes": [{"roi": "gold", "score": 0.1}],
            },
            {
                "timestamp_ms": 1800,
                "changes": [{"roi": "gold", "score": 0.2}],
            },
            {
                "timestamp_ms": 5000,
                "changes": [{"roi": "gold", "score": 0.3}],
            },
        ]

        report = summarize(events, episode_gap_ms=1500)
        self.assertEqual(report["semantic"]["per_roi"]["gold"]["changes"], 3)
        self.assertEqual(report["semantic"]["per_roi"]["gold"]["episodes"], 2)

    def test_roi_names_are_canonicalized(self):
        self.assertEqual(canonical_roi("LevelXp"), "level_xp")
        self.assertEqual(canonical_roi("PlayerList"), "player_list")
        self.assertEqual(canonical_roi("Shop"), "shop")

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
        self.assertEqual(report["raw"]["total_changes"], 0)
        self.assertEqual(report["raw"]["per_roi"], {})
        self.assertEqual(report["semantic"]["per_roi"], {})
        self.assertIsNone(report["duration_between_changes_ms"])


if __name__ == "__main__":
    unittest.main()
