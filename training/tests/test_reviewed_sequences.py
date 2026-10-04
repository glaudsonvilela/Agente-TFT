from copy import deepcopy
import unittest

from training.reviewed_sequences import assign_splits, build
from training.tests.test_board_review import frame


def documents():
    frames = []
    for i, slot in enumerate((2, 2, 8)):
        f = frame()
        f.update(
            sha256=str(i + 1) * 64,
            pixel_sha256=str(i + 4) * 64,
            source_ms=i * 1000,
            match_group=None,
            hud={"gold": 17, "level": 5},
        )
        f["layout"]["units"] = [
            dict(
                key="a",
                zone="bench",
                owner="self",
                box=[10, 10, 30, 30],
                bench_slot=slot,
            )
        ]
        frames.append(f)
    doc = dict(
        schema_version=2,
        kind="board_review",
        source_sha256="a" * 64,
        source_url="https://example.com/video",
        frames=frames,
    )
    actions = dict(
        schema_version=1,
        kind="reviewed_action_sequences",
        source_sha256="a" * 64,
        source_url=doc["source_url"],
        transitions=[
            dict(
                id="move-1",
                before=frames[0]["sha256"],
                after=frames[-1]["sha256"],
                evidence_frames=[frames[1]["sha256"]],
                evidence_kind="visible_execution",
                review=dict(
                    method="assistant_visual_review",
                    model_predictions_used_as_labels=False,
                ),
                action=dict(
                    kind="move",
                    unit_key="a",
                    **{"from": dict(zone="bench", slot=2)},
                    to=dict(zone="bench", slot=8)
                ),
            )
        ],
    )
    return actions, doc


class DemonstrationTests(unittest.TestCase):
    def test_only_past_observation_enters_input_unknowns_stay_absent(self):
        actions, doc = documents()
        doc["frames"][0]["future_placement"] = 1
        doc["frames"][0]["layout"]["future_reward"] = 10
        doc["frames"][0]["layout"]["units"][0]["wins_next_fight"] = True
        doc["frames"][2]["hud"]["gold"] = 90
        rows, report = build(actions, doc)
        row = rows[0]
        self.assertEqual(row["input"]["observed"]["hud"]["gold"], 17)
        self.assertNotIn("future_placement", row["input"]["observed"])
        self.assertNotIn("future_reward", row["input"]["observed"]["layout"])
        self.assertNotIn(
            "wins_next_fight", row["input"]["observed"]["layout"]["units"][0]
        )
        self.assertNotIn("inventory", row["input"]["observed"])
        self.assertTrue(row["eligible_for_action_imitation"])
        self.assertFalse(row["eligible_for_full_state_policy"])
        self.assertFalse(row["eligible_for_outcome_value"])
        self.assertEqual(report["patch_bound_transitions"], 0)

    def test_narration_model_predictions_and_future_evidence_rejected(self):
        for change in (
            "narration",
            "prediction",
            "future",
            "time",
            "location",
            "patch",
            "round",
            "evidence_phase",
        ):
            actions, doc = documents()
            t = actions["transitions"][0]
            if change == "narration":
                t["evidence_kind"] = "narrated_recommendation"
            elif change == "prediction":
                t["review"]["model_predictions_used_as_labels"] = True
            elif change == "future":
                t["evidence_frames"] = [doc["frames"][2]["sha256"]]
            elif change == "time":
                doc["frames"][2]["source_ms"] = 0
            elif change == "location":
                t["action"]["to"]["slot"] = 5
            elif change == "round":
                doc["frames"][0]["hud"]["stage"] = "2-5"
                doc["frames"][2]["hud"]["stage"] = "2-6"
            elif change == "evidence_phase":
                doc["frames"][1]["phase"] = "combat"
            else:
                doc["frames"][2]["patch_binding"] = dict(
                    set_key="set",
                    patch="patch",
                    release_sha256="b" * 64,
                    evidence="fixture",
                )
            with self.subTest(change=change), self.assertRaises(ValueError):
                build(actions, doc)

    def test_overlap_and_cross_match_are_rejected(self):
        actions, doc = documents()
        other = deepcopy(actions["transitions"][0])
        other["id"] = "move-2"
        actions["transitions"].append(other)
        with self.assertRaisesRegex(ValueError, "overlapping"):
            build(actions, doc)
        actions, doc = documents()
        doc["frames"][1]["match_group"] = "other"
        with self.assertRaisesRegex(ValueError, "crosses"):
            build(actions, doc)

    def test_whole_source_and_duplicate_match_stay_in_holdout(self):
        a, doc = documents()
        rows, _ = build(a, doc)
        duplicate = deepcopy(rows[0])
        duplicate["id"] = "other"
        duplicate["source_sha256"] = "b" * 64
        rows.append(duplicate)
        result = assign_splits(rows, test_sources=["a" * 64])
        self.assertEqual([r["split"] for r in result], ["test", "test"])
        with self.assertRaisesRegex(ValueError, "different holdouts"):
            assign_splits(rows, validation_sources=["b" * 64], test_sources=["a" * 64])
        with self.assertRaises(ValueError):
            assign_splits(rows, test_sources=["c" * 64])

    def test_known_cross_platform_match_groups_join_without_identical_pixels(self):
        actions, doc = documents()
        rows, _ = build(actions, doc)
        rows[0]["match_group"] = "same-match"
        copy = deepcopy(rows[0])
        copy["source_sha256"] = "b" * 64
        copy["input"]["pixel_sha256"] = "8" * 64
        copy["validation_only"].update(
            next_pixel_sha256="9" * 64, evidence_pixels=["0" * 64]
        )
        rows.append(copy)
        self.assertEqual(
            [r["split"] for r in assign_splits(rows, test_sources=["a" * 64])],
            ["test", "test"],
        )


if __name__ == "__main__":
    unittest.main()
