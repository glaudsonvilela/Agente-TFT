import copy
import unittest

from training.audit_expert_video_sources import audit


class ExpertVideoAuditTest(unittest.TestCase):
    def setUp(self):
        self.document = {
            "schema_version": 1, "kind": "expert_video_source_candidates",
            "target_set": "TFTSet18", "target_patch": "18.4B",
            "videos": [{
                "id": "TqgvJ3l_-y0", "channel": "Wasianiverson", "region_candidate": "AMER",
                "source_kind": "single_match_candidate", "duration_seconds": 1796,
                "patch_evidence": "uploaded_after_18.4B",
            }],
        }

    def test_upload_date_is_only_a_candidate(self):
        result = audit(self.document)
        self.assertEqual(result["candidate_videos"], 1)
        self.assertEqual(result["reviewed_training_sources"], 0)
        self.assertIn("client_patch_verified", result["videos"][0]["missing_review"])

    def test_multi_game_vod_requires_segments(self):
        doc = copy.deepcopy(self.document)
        doc["videos"][0]["source_kind"] = "multi_match_vod"
        self.assertIn("reviewed_match_segments", audit(doc)["videos"][0]["missing_review"])

    def test_duplicate_video_is_rejected(self):
        doc = copy.deepcopy(self.document)
        doc["videos"].append(copy.deepcopy(doc["videos"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            audit(doc)

    def test_twitch_archive_has_its_own_url_and_requires_match_segments(self):
        doc = copy.deepcopy(self.document)
        row = doc["videos"][0]
        row.update(platform="twitch", id="2897329575", source_kind="multi_match_vod")
        result = audit(doc)["videos"][0]
        self.assertEqual(result["url"], "https://www.twitch.tv/videos/2897329575")
        self.assertIn("reviewed_match_segments", result["missing_review"])
        self.assertEqual(audit(doc)["twitch_archive_duration_seconds"], 1796)

    def test_unverified_or_unsupported_hud_language_blocks_training(self):
        row = self.document["videos"][0]
        result = audit(self.document)
        self.assertIn("supported_hud_language", result["videos"][0]["missing_review"])
        row["hud_language"] = "zh_CN"
        result = audit(self.document)
        self.assertIn("supported_hud_language", result["videos"][0]["missing_review"])
        row["hud_language"] = "en_US"
        result = audit(self.document)
        self.assertNotIn("supported_hud_language", result["videos"][0]["missing_review"])
        self.assertIn("hud_language_verified", result["videos"][0]["missing_review"])


if __name__ == "__main__":
    unittest.main()
