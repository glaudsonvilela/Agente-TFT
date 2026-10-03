"""Verify and stage pinned offline Brazilian Portuguese voice packs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = ROOT / "build/hm45-voice-downloads"
OUTPUT = ROOT / "build/hm45-voice-assets"
PACKS = {
    "dii": ("vits-piper-pt_BR-dii-high-int8.tar.bz2",
            "8a5b0195eff80a0240f18a3f1d528d4bef08f1b702126cee858d700365fc4111", "high", "README.md"),
    "cadu": ("vits-piper-pt_BR-cadu-medium-int8.tar.bz2",
             "78f1caf0a74cc6cb8dedaff87affd232ee653d5b0394d4cf4d2e97ecbfa5ff3d", "medium", "MODEL_CARD"),
    "faber": ("vits-piper-pt_BR-faber-medium-int8.tar.bz2",
              "dbc8b1d7d729fd417ea78a350ed35696c928770ac93513d3f507bd4e88eee3fd", "medium", "MODEL_CARD"),
}


def prepare(downloads: Path = DOWNLOADS, output: Path = OUTPUT):
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    report = {"source": "https://github.com/k2-fsa/sherpa-onnx/releases/tag/tts-models",
              "voices": {}}
    for key, (filename, expected_sha, quality, card) in PACKS.items():
        archive = downloads / filename
        if not archive.is_file():
            raise FileNotFoundError(f"Arquivo de voz ausente: {archive}")
        actual_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise ValueError(f"Hash incorreto para {filename}")
        voice_dir = output / key
        voice_dir.mkdir()
        prefix = filename.removesuffix(".tar.bz2") + "/"
        needed = {f"pt_BR-{key}-{quality}.onnx": voice_dir / "model.onnx",
                  "tokens.txt": voice_dir / "tokens.txt", card: voice_dir / card}
        extracted = set()
        with tarfile.open(archive, "r:bz2") as tar:
            for member in tar:
                if not member.isfile() or not member.name.startswith(prefix):
                    continue
                relative = member.name[len(prefix):]
                destination = needed.get(relative)
                if key == "cadu" and relative.startswith("espeak-ng-data/"):
                    parts = Path(relative).parts
                    if ".." in parts or len(parts) > 6:
                        raise ValueError("Caminho inválido no pacote de voz")
                    destination = output / relative
                if destination is None:
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                extracted.add(relative)
        if not set(needed).issubset(extracted):
            raise ValueError(f"Modelo de voz incompleto: {key}")
        report["voices"][key] = {"archive_sha256": actual_sha,
                                 "model_sha256": hashlib.sha256((voice_dir / "model.onnx").read_bytes()).hexdigest()}
    if not (output / "espeak-ng-data/phondata").is_file():
        raise ValueError("Dados de pronúncia ausentes")
    (output / "VOICE_REPORT.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(prepare(), indent=2))
