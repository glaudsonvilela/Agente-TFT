from copy import deepcopy
import unittest

from hm.motor2_player_feed import make_frame
from training.export_motor2_player_sft import export


class Motor2SftExportTests(unittest.TestCase):
    def fixture(self):
        frames, labels = [], []
        for split, index in (("train", 1), ("validation", 2)):
            choices = [dict(action=dict(type=kind), policy="partial_state_live_v1")
                       for kind in ("hold_econ", "prepare_level")]
            result = dict(origin="rust_live_opportunity_v1", id=index,
                source_ms=1000 * index, whole_state=dict(stage="3-2", gold=50,
                    hp=80, level=6, xp=12, fresh_shop_offers=0),
                macro_state=dict(phase="middle", pressure="normal"),
                candidates=choices, selected_index=0,
                ranked=[dict(index=i, action_type=row["action"]["type"],
                             decision_key=f"decision:{i}", utility=.2 + i,
                             base_utility=.2 + i) for i, row in enumerate(choices)])
            frame = make_frame(result, patch="18.4B", set_key="TFTSet18",
                               match_id=f"match-{index}", epoch=0)
            frames.append(frame)
            labels.append(dict(match_id=f"match-{index}", frame_id=index,
                observation_sha256=frame["observation_sha256"],
                before_ms=1000 * index, action_ms=1000 * index + 100,
                after_ms=1000 * index + 200,
                state_coverage="complete_observable_state",
                source_sha256=f"source-{index}", review_evidence_id="review",
                split=split, legal_decision_keys=["decision:0", "decision:1"],
                chosen_decision_key="decision:0"))
        review = dict(schema_version=1, kind="reviewed_motor2_actions",
                      patch="18.4B", set_key="TFTSet18", actions=labels,
                      evidence_registry={"review": dict(path="review.json",
                                                        sha256="a" * 64)})
        return frames, review

    def convert(self, frames, review):
        return export(frames, review, patch="18.4B", content_sha256="content",
                      engine_sha256="engine")

    def test_reviewed_expert_action_does_not_copy_rust_preference(self):
        frames, review = self.fixture()
        document = self.convert(frames, review)
        self.assertEqual(len(document["records"]), 2)
        self.assertEqual(document["records"][0]["chosen"], 0)
        self.assertEqual(document["records"][0]["candidates"][1]["legal"], True)
        self.assertEqual(document["records"][0]["candidates"][1]["features"][1], 1.2)

    def test_missing_or_future_label_is_rejected(self):
        frames, review = self.fixture()
        bad = deepcopy(review)
        bad["actions"][0]["observation_sha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "exact"):
            self.convert(frames, bad)
        bad = deepcopy(review)
        bad["actions"][0]["action_ms"] = bad["actions"][0]["before_ms"]
        with self.assertRaisesRegex(ValueError, "after"):
            self.convert(frames, bad)
        bad = deepcopy(review)
        bad["actions"][0]["chosen_decision_key"] = "unknown"
        with self.assertRaisesRegex(ValueError, "legal"):
            self.convert(frames, bad)


if __name__ == "__main__":
    unittest.main()
