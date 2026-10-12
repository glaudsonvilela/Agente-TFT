import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from training.prepare_challenger_strategy import audit


ROOT = Path(__file__).parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ChallengerSelectionTests(unittest.TestCase):
    @patch("training.prepare_challenger_strategy._video_resolution", return_value=[1920, 1080])
    def test_three_whole_matches_split_without_leakage(self, probe):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            games = []
            for index in range(3):
                video = folder / f"game{index}.mp4"
                video.write_bytes(f"video {index}".encode())
                review = folder / f"game{index}.json"
                match_id = f"MATCH-{index}"
                review.write_text(json.dumps(dict(match_id=match_id,
                    actions=[dict(before_ms=100, action="buy", after_ms=200)])))
                games.append(dict(match_id=match_id, set_key="TFTSet18",
                    patch="18.4B", rank="challenger",
                    rank_evidence_url="https://example.org/rank",
                    patch_evidence_url="https://example.org/patch",
                    source_url="https://example.org/video", usage_permission=True,
                    video_path=str(video), video_sha256=digest(video),
                    reviewed_actions_path=str(review),
                    reviewed_actions_sha256=digest(review)))
            selection = dict(schema_version=1, set_key="TFTSet18",
                             patch="18.4B", games=games)
            plan = audit(selection, ROOT)
            self.assertTrue(plan["data_split_ready"])
            self.assertFalse(plan["rule_coverage_ready"])
            self.assertFalse(plan["training_ready"])
            self.assertIn("trait_effects", plan["unverified_rules"])
            self.assertEqual({row["split"] for row in plan["games"]},
                             {"train", "validation", "test"})
            selection["games"][2]["video_path"] = games[0]["video_path"]
            selection["games"][2]["video_sha256"] = games[0]["video_sha256"]
            with self.assertRaisesRegex(ValueError, "same video"):
                audit(selection, ROOT)

            probe.return_value = [1280, 720]
            selection["games"][2]["video_path"] = str(folder / "game2.mp4")
            selection["games"][2]["video_sha256"] = digest(folder / "game2.mp4")
            with self.assertRaisesRegex(ValueError, "1920x1080"):
                audit(selection, ROOT)

    def test_empty_selection_is_not_ready(self):
        plan = audit(dict(schema_version=1, set_key="TFTSet18",
                          patch="18.4B", games=[]), ROOT)
        self.assertFalse(plan["training_ready"])


if __name__ == "__main__":
    unittest.main()
