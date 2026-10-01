from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from training.replay_labeler import atomic_save_annotations, load_annotations, safe_frame_path


class ReplayLabelerTests(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        frames = root / "frames"
        frames.mkdir(parents=True)
        (frames / "0001.jpg").write_bytes(b"jpg")
        annotations = root / "annotations.json"
        annotations.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source_video": "match.mp4",
                    "frames": [
                        {
                            "timestamp_ms": 1000,
                            "image": "frames/0001.jpg",
                            "scene": "planning_shop",
                            "hp": 100,
                            "shop": ["A", "B", "C", "D", "E"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return annotations

    def test_atomic_save_creates_backup_and_preserves_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.fixture(Path(directory))
            value = load_annotations(path)
            value["frames"][0]["gold"] = 10
            report = atomic_save_annotations(path, value)

            self.assertEqual(load_annotations(path)["frames"][0]["gold"], 10)
            self.assertTrue(path.with_name("annotations.json.bak").is_file())
            self.assertTrue(report["ready_for_calibration"])

    def test_atomic_save_rejects_structural_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.fixture(Path(directory))
            value = load_annotations(path)
            value["frames"][0]["shop"] = ["A"]
            with self.assertRaises(ValueError):
                atomic_save_annotations(path, value)

    def test_safe_frame_path_allows_existing_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            result = safe_frame_path(root, "0001.jpg")
            self.assertEqual(result, (root / "frames" / "0001.jpg").resolve())

    def test_safe_frame_path_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            self.assertIsNone(safe_frame_path(root, "../annotations.json"))


if __name__ == "__main__":
    unittest.main()
