#!/usr/bin/env python3
"""Compare sealed localization candidates on identical replay frames.

Proposal counts measure model behavior, not semantic TFT accuracy.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort

from training.ui_map_lite.core import decoded
from training.ui_map_lite.data import image_tensor


def sealed_model(folder: Path) -> Path:
    seal = json.loads((folder / "COMPLETE.json").read_text(encoding="utf-8"))
    model = folder / "model.onnx"
    if hashlib.sha256(model.read_bytes()).hexdigest() != seal["model.onnx"]:
        raise ValueError("Candidate model seal mismatch")
    return model


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.manifest.read_text(encoding="utf-8"))["frames"]
    rows = [row for row in rows if row["image"].split("/")[0] == args.session]
    if not rows:
        raise ValueError("No frames for requested session")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    sessions = {name: ort.InferenceSession(str(sealed_model(folder)), options,
                                          providers=["CPUExecutionProvider"])
                for name, folder in (("previous", args.previous), ("candidate", args.candidate))}
    counts = {name: Counter() for name in sessions}
    for row in rows:
        image = args.image_root / row["image"]
        if hashlib.sha256(image.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Source image changed")
        tensor = image_tensor(image)
        for name, session in sessions.items():
            output = session.run(["regions"], {"image": tensor.astype(np.float32, copy=False)})[0][0]
            counts[name].update(region["panel"] + ":" + region["status"]
                                for region in decoded(output))
    result = {"session": args.session, "frames": len(rows),
              "previous": dict(counts["previous"]), "candidate": dict(counts["candidate"]),
              "semantic_accuracy": None, "candidate_promoted": False}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
