"""Fetch and verify the one English OCR model used by the Agente TFT packages."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "build/ocr/tessdata_best"
BASE_URL = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main"
PLAN = json.loads((ROOT / "configs/ocr/active-model.json").read_text())
FILES = {
    "eng.traineddata": PLAN["eng_sha256"],
    "LICENSE": PLAN["license_sha256"],
}
MODEL_SHA256 = FILES["eng.traineddata"]


def verified(path: Path, expected_sha256: str) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest() == expected_sha256


def prepare(destination: Path = DESTINATION, source_dir: Path | None = None) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        target = destination / name
        if verified(target, expected):
            continue
        if target.exists():
            raise ValueError(f"Existing OCR file has the wrong SHA-256: {target}")
        if source_dir is None:
            with urlopen(f"{BASE_URL}/{name}", timeout=30) as response:
                content = response.read()
        else:
            content = (source_dir / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"Downloaded OCR file has the wrong SHA-256: {name}")
        target.write_bytes(content)
    return destination


def require_model(destination: Path = DESTINATION) -> Path:
    if not all(verified(destination / name, digest) for name, digest in FILES.items()):
        raise FileNotFoundError(
            f"Verified tessdata_best is missing from {destination}; "
            "run scripts/prepare_tessdata_best.py"
        )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path,
                        help="Use an already downloaded copy, after checking its SHA-256")
    args = parser.parse_args()
    print(prepare(source_dir=args.source_dir))


if __name__ == "__main__":
    main()
