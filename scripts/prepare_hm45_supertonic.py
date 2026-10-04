"""Stage the chosen Supertonic 3 F1 voice from a pinned public release."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "build/hm45-voice-assets"
REPO = "Supertone/supertonic-3"
REVISION = "3cadd1ee6394adea1bd021217a0e650ede09a323"
FILES = {
    "LICENSE": "0d944a9110fed9a9602d60e0423a272903e7bd21ab060490774efc77c2275e9f",
    "onnx/duration_predictor.onnx": "c3eb91414d5ff8a7a239b7fe9e34e7e2bf8a8140d8375ffb14718b1c639325db",
    "onnx/text_encoder.onnx": "c7befd5ea8c3119769e8a6c1486c4edc6a3bc8365c67621c881bbb774b9902ff",
    "onnx/vector_estimator.onnx": "883ac868ea0275ef0e991524dc64f16b3c0376efd7c320af6b53f5b780d7c61c",
    "onnx/vocoder.onnx": "085de76dd8e8d5836d6ca66826601f615939218f90e519f70ee8a36ed2a4c4ba",
    "onnx/tts.json": "42078d3aef1cd43ab43021f3c54f47d2d75ceb4e75f627f118890128b06a0d09",
    "onnx/unicode_indexer.json": "9bf7346e43883a81f8645c81224f786d43c5b57f3641f6e7671a7d6c493cb24f",
    "voice_styles/F1.json": "bbdec6ee00231c2c742ad05483df5334cab3b52fda3ba38e6a07059c4563dbc2",
}


def prepare(output: Path = OUTPUT):
    from huggingface_hub import hf_hub_download

    report_path = output / "VOICE_REPORT.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    destination = output / "supertonic-f1"
    destination.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        source = Path(hf_hub_download(REPO, name, revision=REVISION))
        with source.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError(f"Supertonic 3 mudou: {name}")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    report["voices"]["supertonic-f1"] = {
        "source": f"https://huggingface.co/{REPO}/tree/{REVISION}",
        "style": "F1",
        "model_file_sha256": {name: digest for name, digest in FILES.items()},
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report["voices"]["supertonic-f1"]


if __name__ == "__main__":
    print(json.dumps(prepare(), indent=2))
