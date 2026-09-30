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

    def test_empty_input_is_explicit(self):
        report = summarize([])

        self.assertEqual(report["records"], 0)
        self.assertIsNone(report["state"]["shop_known_rate"])
        self.assertIsNone(report["opportunity"]["no_confident_rate"])
        self.assertIn("Coverage is not accuracy.", report["notes"])


if __name__ == "__main__":
    unittest.main()
