"""The app must not silently load an older English OCR model."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from hm.runtime_app import runtime_paths


class BestOcrSelectionTests(unittest.TestCase):
    def test_packaged_model_is_verified_before_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "tesseract/tesseract"
            model = root / "tesseract/tessdata/eng.traineddata"
            plan = root / "configs/ocr/active-model.json"
            for path in (executable, model, plan):
                path.parent.mkdir(parents=True, exist_ok=True)
            executable.write_bytes(b"test executable")
            model.write_bytes(b"best model")
            plan.write_text(json.dumps({"eng_sha256": hashlib.sha256(b"best model").hexdigest()}))
            with patch.object(sys, "_MEIPASS", str(root), create=True), patch.dict(os.environ):
                self.assertEqual(runtime_paths()["tesseract"], str(executable))
                self.assertEqual(os.environ["TESSDATA_PREFIX"], str(model.parent))
                self.assertEqual(os.environ["AGENTE_TFT_RESIDENT_OCR"], "required")
                model.write_bytes(b"old model")
                with self.assertRaisesRegex(RuntimeError, "differs from tessdata_best"):
                    runtime_paths()


if __name__ == "__main__":
    unittest.main()
