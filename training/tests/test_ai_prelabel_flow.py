from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from training.export_ai_batch import build_manifest, export_zip
from training.import_ai_prelabels import merge_prelabels, validate_prelabels


class AiPrelabelFlowTests(unittest.TestCase):
    def fixture(self, root: Path) -> Path:
        frames = root / "frames"
        frames.mkdir(parents=True)
        (frames / "0001.jpg").write_bytes(b"jpg-a")
        (frames / "0002.jpg").write_bytes(b"jpg-b")
        annotations = root / "annotations.json"
        annotations.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source_video": "TFT_MATCH_001.mp4",
                    "frames": [
                        {"timestamp_ms": 0, "image": "frames/0001.jpg"},
                        {"timestamp_ms": 50000, "image": "frames/0002.jpg"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        return annotations

    def test_export_batch_contains_manifest_and_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            output = root / "batch.zip"
            result = export_zip(root, output)

            self.assertEqual(result["frames"], 2)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertIn("manifest.json", names)
                self.assertIn("frames/0001.jpg", names)
                self.assertIn("frames/0002.jpg", names)

    def test_manifest_preserves_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            manifest = build_manifest(root)
            self.assertEqual(manifest["source_video"], "TFT_MATCH_001.mp4")
            self.assertEqual(manifest["frames"][1]["timestamp_ms"], 50000)
            self.assertEqual(manifest["frames"][1]["image"], "frames/0002.jpg")

    def test_validate_prelabels_rejects_invalid_confidence(self):
        value = {
            "schema_version": 1,
            "source_video": "TFT_MATCH_001.mp4",
            "frames": [
                {
                    "timestamp_ms": 0,
                    "image": "frames/0001.jpg",
                    "suggestions": {
                        "hp": {"value": 100, "confidence": 1.4}
                    },
                }
            ],
        }
        with self.assertRaises(ValueError):
            validate_prelabels(value)

    def test_merge_prelabels_writes_separate_file_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            annotations_path = self.fixture(root)
            original = annotations_path.read_text(encoding="utf-8")

            prelabels = root / "incoming.json"
            prelabels.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "source_video": "TFT_MATCH_001.mp4",
                        "frames": [
                            {
                                "timestamp_ms": 0,
                                "image": "frames/0001.jpg",
                                "suggestions": {
                                    "scene": {"value": "planning_shop", "confidence": 0.99},
                                    "gold": {"value": 14, "confidence": 0.82},
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            result = merge_prelabels(root, prelabels)
            self.assertEqual(result["matched_frames"], 1)
            self.assertTrue((root / "prelabels.json").is_file())
            self.assertEqual(annotations_path.read_text(encoding="utf-8"), original)

            saved = json.loads((root / "prelabels.json").read_text(encoding="utf-8"))
            self.assertEqual(
                saved["frames"][0]["suggestions"]["gold"]["value"],
                14,
            )


if __name__ == "__main__":
    unittest.main()
