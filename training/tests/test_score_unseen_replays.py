import unittest

from training.score_unseen_replays import score


class UnseenReplayScoreTest(unittest.TestCase):
    def test_unreviewed_zones_and_duplicate_predictions_do_not_inflate_recall(self):
        observations = [{"source_id": "unseen", "second": 10,
                         "detections": [{"class_name": "board_unit", "box": [0, 0, 20, 20]},
                                        {"class_name": "board_unit", "box": [0, 0, 20, 20]},
                                        {"class_name": "enemy_unit", "box": [0, 0, 20, 20]}],
                         "records": [{"zone": "board_unit", "box": [0, 0, 20, 20],
                                      "candidate_name": "Alistar"}],
                         "bench_records": [], "enemy_records": []}]
        review = {"schema_version": 1,
                  "review_method": "assistant_visual_review_from_raw_video",
                  "model_predictions_used_as_labels": False,
                  "frames": [{"source_id": "unseen", "second": 10,
                              "reviewed_zones": ["board"],
                              "units": [{"zone": "board", "point": [10, 10],
                                         "name": "Alistar",
                                         "identity_status": "visually_verified"}]}]}
        result = score(observations, review)
        self.assertEqual(result["coverage"]["detector"]["board"],
                         {"true_positive": 1, "false_positive": 1, "false_negative": 0})
        self.assertEqual(result["coverage"]["detector"]["enemy"], {})
        self.assertEqual(result["identity_on_visually_verified_matches"],
                         {"reviewed_matches": 1, "correct": 1})

    def test_rejects_prediction_as_truth(self):
        review = {"schema_version": 1,
                  "review_method": "assistant_visual_review_from_raw_video",
                  "model_predictions_used_as_labels": True, "frames": []}
        with self.assertRaises(ValueError):
            score([], review)

    def test_identity_probe_does_not_score_unreviewed_zone_coverage(self):
        observations = [{"source_id": "new", "second": 12, "detections": [],
                         "records": [{"zone": "board_unit", "box": [0, 0, 20, 20],
                                      "candidate_name": "Hecarim"}],
                         "bench_records": [], "enemy_records": []}]
        review = {"schema_version": 1,
                  "review_method": "assistant_visual_review_from_raw_video",
                  "model_predictions_used_as_labels": False,
                  "frames": [{"source_id": "new", "second": 12,
                              "reviewed_zones": [],
                              "identity_only_units": [{"zone": "board", "point": [10, 10],
                                                       "name": "Kha'Zix",
                                                       "identity_status": "visually_verified",
                                                       "evidence": "Selected unit panel in raw frame"}]}]}
        result = score(observations, review)
        self.assertEqual(result["coverage"]["full_reader"]["board"], {})
        self.assertEqual(result["identity_on_visually_verified_matches"],
                         {"reviewed_probes": 1, "reviewed_matches": 1, "correct": 0})


if __name__ == "__main__":
    unittest.main()
