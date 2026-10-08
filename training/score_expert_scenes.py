"""Score whether sampled VOD frames show the TFT board.

This older scene gate has a limited one-match evaluation. Its scores are
sampling hints; high confidence must not become a verified scene/action label.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def score(moments: Path, frames: Path, model: Path, output: Path) -> dict:
    import onnxruntime as ort

    if output.exists():
        raise ValueError("use a new output directory")
    rows = [json.loads(line) for line in moments.open()]
    if not rows or len({row["moment"] for row in rows}) != len(rows):
        raise ValueError("empty or duplicate moment queue")
    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    probabilities = []
    for offset in range(0, len(rows), 32):
        pixels = []
        for row in rows[offset:offset + 32]:
            path = frames / f"moment-{row['moment']:04d}.jpg"
            with Image.open(path) as image:
                pixels.append(np.asarray(image.convert("RGB").resize(
                    (160, 90), Image.Resampling.BILINEAR), dtype=np.float32)
                    .transpose(2, 0, 1) / 255.0)
        logits = session.run(None, {input_name: np.stack(pixels)})[0]
        shifted = np.exp(logits - logits.max(axis=1, keepdims=True))
        probabilities.extend((shifted[:, 1] / shifted.sum(axis=1)).tolist())
        print(f"CENAS {min(offset+32, len(rows))}/{len(rows)}", flush=True)
    output.mkdir(parents=True)
    values = np.asarray(probabilities, dtype=np.float32)
    np.save(output / "scene_gate_probabilities.npy", values)
    report = {"moments": len(rows), "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
              "moment_queue_sha256": hashlib.sha256(moments.read_bytes()).hexdigest(),
              "input_size": [160, 90], "threshold_0_99_candidates": int((values >= 0.99).sum()),
              "status": "sampling_hint_only", "human_verified": False,
              "limitation": "scene gate evaluated on only one held-out match; possible false positives"}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--moments", type=Path, required=True)
    parser.add_argument("--frames", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    score(args.moments, args.frames, args.model, args.output)


if __name__ == "__main__":
    main()
