from copy import deepcopy
import unittest

from hm.motor2_player_feed import make_frame
from training.build_player_episodes import build_episodes


class PlayerEpisodeTests(unittest.TestCase):
    def fixture(self):
        frames = []
        for index, at in enumerate((0, 3000, 6000)):
            result = dict(origin="rust_live_opportunity_v1", id=index, source_ms=at,
                whole_state=dict(stage="2-1" if index == 0 else "3-2",
                                 gold=10 + index, hp=100 - 5 * index),
                macro_state=dict(phase="opening" if index == 0 else "middle",
                                 pressure="normal"), candidates=[], ranked=[],
                selected_index=None)
            frames.append(make_frame(result, patch="18.4B", set_key="TFTSet18",
                                     match_id="m1", epoch=0))
        manifest = dict(schema_version=1, kind="reviewed_full_matches",
            matches=[dict(match_id="m1", source_sha256="a" * 64,
                patch="18.4B", set_key="TFTSet18", start_ms=0, end_ms=7000,
                placement=3, full_video_reviewed=True, patch_reviewed=True,
                outcome_reviewed=True, outcome_evidence_id="result-frame",
                hud_language="en_US", ocr_locale_validated=True,
                player_pov_verified=True, player_rank_at_game_verified=True)])
        return frames, manifest

    def test_ordered_full_match_retains_state_and_final_result(self):
        frames, manifest = self.fixture()
        episode = build_episodes(list(reversed(frames)), manifest)[0]
        self.assertEqual([row["source_ms"] for row in episode["frames"]],
                         [0, 3000, 6000])
        self.assertEqual(episode["placement"], 3)
        self.assertTrue(episode["terminal_reward_only"])
        self.assertFalse(episode["action_labels_reviewed"])

    def test_missing_ending_and_patch_mismatch_are_rejected(self):
        frames, manifest = self.fixture()
        bad = deepcopy(manifest)
        bad["matches"][0]["end_ms"] = 20_000
        with self.assertRaisesRegex(ValueError, "end not captured"):
            build_episodes(frames, bad)
        bad = deepcopy(frames)
        bad[1]["patch"] = "18.3"
        with self.assertRaisesRegex(ValueError, "patch"):
            build_episodes(bad, manifest)

    def test_language_and_rank_must_be_reviewed(self):
        frames, manifest = self.fixture()
        bad = deepcopy(manifest)
        bad["matches"][0]["hud_language"] = "zh_CN"
        with self.assertRaisesRegex(ValueError, "HUD language"):
            build_episodes(frames, bad)
        bad = deepcopy(manifest)
        bad["matches"][0]["player_rank_at_game_verified"] = False
        with self.assertRaisesRegex(ValueError, "Challenger rank"):
            build_episodes(frames, bad)


if __name__ == "__main__":
    unittest.main()
