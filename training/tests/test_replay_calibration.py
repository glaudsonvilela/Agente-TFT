from __future__ import annotations

import unittest

from training.replay_calibration import summarize


class ReplayCalibrationTests(unittest.TestCase):
    def test_summarizes_state_and_opportunity_coverage(self):
        records = [
            {
                "recorded_at_ms": 100,
                "payload": {
                    "type": "state_snapshot",
                    "state": {
                        "player": {
                            "hp": {"value": 80},
                            "gold": {"value": 50},
                            "level": {"value": 7},
                            "xp": None,
                            "stage": {"value": "4-1"},
                            "shop": [
                                {"value": {"slot": 0, "unit_id": "A"}},
                                {"value": {"slot": 1, "unit_id": None}},
                            ],
                            "board": [{}, {}, {}],
                        },
                        "lobby": [{}, {}],
                    },
                },
            },
            {
                "recorded_at_ms": 200,
                "payload": {
                    "type": "complete_opportunity_cycle",
                    "cycle": {
                        "cycle": {
                            "decision": {
                                "action": {"type": "wait"},
                                "evidence": [
                                    {
                                        "code": "NO_CONFIDENT_CANDIDATE",
                                        "detail": "fixture",
                                    }
                                ],
                            },
                            "should_remote_evaluate": True,
                        }
                    },
                },
            },
            {
                "recorded_at_ms": 250,
                "payload": {
                    "type": "evaluator_feedback_snapshot",
                    "feedback": {},
                },
            },
            {
                "recorded_at_ms": 300,
                "payload": {
                    "type": "metric",
                    "name": "opportunity_eval_ms",
                    "value": 4.0,
                },
            },
            {
                "recorded_at_ms": 400,
                "payload": {
                    "type": "metric",
                    "name": "opportunity_eval_ms",
                    "value": 6.0,
                },
            },
        ]

        report = summarize(records)

        self.assertEqual(report["duration_ms"], 300)
        self.assertEqual(report["state"]["snapshots"], 1)
        self.assertEqual(report["state"]["field_coverage"]["hp"], 1.0)
        self.assertEqual(report["state"]["field_coverage"]["xp"], 0.0)
        self.assertEqual(report["state"]["shop_known_rate"], 0.5)

        self.assertEqual(report["opportunity"]["cycles"], 1)
        self.assertEqual(report["opportunity"]["complete_cycles"], 1)
        self.assertEqual(report["opportunity"]["decision_actions"]["wait"], 1)
        self.assertEqual(report["opportunity"]["no_confident_rate"], 1.0)
        self.assertEqual(report["opportunity"]["remote_evaluate_cycles"], 1)

        self.assertEqual(
            report["training_feedback"]["evaluator_feedback_snapshots"],
            1,
        )
        self.assertEqual(report["metrics"]["opportunity_eval_ms"]["p50"], 5.0)
        self.assertEqual(report["metrics"]["opportunity_eval_ms"]["max"], 6.0)


    def test_ground_truth_accuracy_metrics(self):
        records = [
            {
                "recorded_at_ms": 1000,
                "payload": {
                    "type": "state_snapshot",
                    "state": {
                        "observed_at_ms": 1000,
                        "player": {
                            "hp": {"value": 80},
                            "gold": {"value": 50},
                            "level": {"value": 7},
                            "xp": {"value": 20},
                            "stage": {"value": "4-1"},
                            "shop": [
                                {"value": {"slot": 0, "unit_id": "A"}},
                                {"value": {"slot": 1, "unit_id": "B"}},
                            ],
                            "board": [
                                {"unit_id": "A"},
                                {"unit_id": "C"},
                            ],
                        },
                        "lobby": [
                            {"player_id": "p2"},
                            {"player_id": "p3"},
                        ],
                    },
                },
            }
        ]

        annotations = {
            "schema_version": 1,
            "frames": [
                {
                    "timestamp_ms": 1010,
                    "hp": 80,
                    "gold": 49,
                    "level": 7,
                    "xp": 20,
                    "stage": "4-1",
                    "shop": ["A", "X"],
                    "board_unit_ids": ["A", "B"],
                    "lobby_player_ids": ["p2", "p3"],
                }
            ],
        }

        report = summarize(
            records,
            annotations=annotations,
            annotation_tolerance_ms=50,
        )
        ground = report["ground_truth"]

        self.assertEqual(ground["matched_frames"], 1)
        self.assertEqual(ground["unmatched_frames"], 0)
        self.assertEqual(ground["hud_exact_accuracy"]["hp"], 1.0)
        self.assertEqual(ground["hud_exact_accuracy"]["gold"], 0.0)
        self.assertEqual(ground["shop_slot_accuracy"], 0.5)
        self.assertEqual(ground["board_precision"], 0.5)
        self.assertEqual(ground["board_recall"], 0.5)
        self.assertEqual(ground["board_exact_rate"], 0.0)
        self.assertEqual(ground["lobby_precision"], 1.0)
        self.assertEqual(ground["lobby_recall"], 1.0)
        self.assertEqual(ground["lobby_exact_rate"], 1.0)

    def test_ground_truth_respects_timestamp_tolerance(self):
        records = [
            {
                "recorded_at_ms": 1000,
                "payload": {
                    "type": "state_snapshot",
                    "state": {
                        "observed_at_ms": 1000,
                        "player": {},
                        "lobby": [],
                    },
                },
            }
        ]
        annotations = {
            "schema_version": 1,
            "frames": [
                {"timestamp_ms": 2000, "hp": 80},
            ],
        }

        report = summarize(
            records,
            annotations=annotations,
            annotation_tolerance_ms=100,
        )

        self.assertEqual(report["ground_truth"]["matched_frames"], 0)
        self.assertEqual(report["ground_truth"]["unmatched_frames"], 1)

    def test_empty_input_is_explicit(self):
        report = summarize([])

        self.assertEqual(report["records"], 0)
        self.assertIsNone(report["state"]["shop_known_rate"])
        self.assertIsNone(report["opportunity"]["no_confident_rate"])
        self.assertIn("Coverage is not accuracy.", report["notes"])


if __name__ == "__main__":
    unittest.main()
