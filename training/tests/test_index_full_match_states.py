"""Keep uncertain OCR out of the full-match training index."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from training.index_full_match_states import index, reconcile_gold_reads


class GoldOcrConsensusTests(unittest.TestCase):
    def test_accepts_primary_with_one_agreeing_view(self):
        self.assertEqual(
            reconcile_gold_reads({
                "gray_psm13": "51", "gray_psm7": "51", "contrast_psm7": "31",
            }),
            (51, "corroborated"),
        )

    def test_rejects_three_different_readings(self):
        self.assertEqual(
            reconcile_gold_reads({
                "gray_psm13": "51", "gray_psm7": "31", "contrast_psm7": "81",
            }),
            (None, "disagreement"),
        )

    def test_does_not_fall_back_to_bad_secondary_when_primary_is_blank(self):
        self.assertEqual(
            reconcile_gold_reads({
                "gray_psm13": "", "gray_psm7": "7", "contrast_psm7": "7",
            }),
            (None, "unreadable"),
        )

    def test_rejects_non_numeric_primary(self):
        self.assertEqual(
            reconcile_gold_reads({
                "gray_psm13": "5l", "gray_psm7": "51", "contrast_psm7": "51",
            }),
            (None, "unreadable"),
        )


class ResumeTests(unittest.TestCase):
    def test_resume_requires_matching_frame_and_time(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGB", (1920, 1080)).save(root / "frame-000001.jpg")
            output = root / "index.jsonl"
            output.write_text('{"frame":"frame-000001.jpg","source_seconds":99}\n')
            with patch("training.index_full_match_states.prepare_ocr_model"):
                with self.assertRaisesRegex(ValueError, "does not match"):
                    index(root, output, 78, 5, 1, resume=True)


if __name__ == "__main__":
    unittest.main()
