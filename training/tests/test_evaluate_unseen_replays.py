import tempfile
import unittest
from pathlib import Path

from training.evaluate_unseen_replays import _source_audit


class SourceAuditTest(unittest.TestCase):
    def test_detects_alias_used_by_training_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text('{"source_splits":{"twitch:2893526719":["train"]}}')
            audit = _source_audit("v2893526719", ["2893526719"], [manifest])
            self.assertEqual(len(audit["known_manifest_matches"]), 1)
            self.assertFalse(audit["source_id_absent_from_known_training_manifests"])

    def test_absence_is_scoped_to_checked_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "manifest.json"
            manifest.write_text('{"source_splits":{"some-other-match":["train"]}}')
            audit = _source_audit("new-source", [], [manifest])
            self.assertTrue(audit["source_id_absent_from_known_training_manifests"])
            self.assertFalse(audit["same_match_reupload_excluded"])


if __name__ == "__main__":
    unittest.main()
