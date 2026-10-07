"""Frozen DINO encoder + supervised softmax head for local unit candidates.

This is the runtime counterpart of tools/unit-features-lab training::Head.
The server may replace the approved encoder/head bundle between matches, never
during a session. Scores remain uncalibrated candidate evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time

from .unit_identity import MAX_UNITS, unit_box


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resize_bilinear(rgb, out_h: int, out_w: int):
    import numpy as np

    src = np.asarray(rgb, dtype=np.float32)
    in_h, in_w, channels = src.shape
    if channels != 3 or in_h < 1 or in_w < 1:
        raise ValueError("Invalid RGB crop")
    xs = ((np.arange(out_w, dtype=np.float32) + 0.5) * in_w / out_w - 0.5)
    ys = ((np.arange(out_h, dtype=np.float32) + 0.5) * in_h / out_h - 0.5)
    xs = np.clip(xs, 0.0, in_w - 1.0)
    ys = np.clip(ys, 0.0, in_h - 1.0)
    x0 = np.floor(xs).astype(np.int32)
    y0 = np.floor(ys).astype(np.int32)
    x1 = np.minimum(x0 + 1, in_w - 1)
    y1 = np.minimum(y0 + 1, in_h - 1)
    xf = (xs - x0).reshape(1, out_w, 1)
    yf = (ys - y0).reshape(out_h, 1, 1)
    top = src[y0[:, None], x0[None, :]] * (1.0 - xf) + src[y0[:, None], x1[None, :]] * xf
    bottom = src[y1[:, None], x0[None, :]] * (1.0 - xf) + src[y1[:, None], x1[None, :]] * xf
    return top * (1.0 - yf) + bottom * yf


def _resize_bilinear_u8(rgb, out_h: int, out_w: int):
    import numpy as np

    # Rust UnitCrop::from_frame writes every resized pixel back to u8 using
    # round(), before any later tensor resize. Preserve that quantization
    # boundary so the same DINO/head produces the same runtime evidence.
    resized = _resize_bilinear(rgb, out_h, out_w)
    return np.clip(np.floor(resized + 0.5), 0, 255).astype(np.uint8)


def _upper_88x80_v1(image, box, side: int):
    import numpy as np

    # unit_box is exactly the reviewed/training 128x144 crop contract.
    raw = np.asarray(image.crop(box).convert("RGB"), dtype=np.uint8)
    if raw.shape != (144, 128, 3):
        raw = _resize_bilinear_u8(raw, 144, 128)
    upper = raw[24:104, 20:108]
    transformed = _resize_bilinear_u8(upper, 144, 128)
    tensor = _resize_bilinear(transformed, side, side) / 255.0
    return tensor.transpose(2, 0, 1).astype(np.float32)


class UnitHeadObserver:
    def __init__(self, root: Path, neural_root: Path):
        import numpy as np
        import onnxruntime as ort

        root = Path(root)
        neural_root = Path(neural_root)
        plan_path = neural_root / "configs/catalog/active-unit-head-v1.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if (
            plan.get("schema_version") != 1
            or plan.get("kind") != "dino_softmax_unit_classifier"
            or plan.get("mode") != "diagnostic_candidates"
        ):
            raise ValueError("Unit head plan is not runtime compatible")

        folder = neural_root / "models/unit-head"
        budgets = {
            "encoder.onnx": 128 * 1024**2,
            "dino-head.json": 32 * 1024**2,
        }
        if set(plan.get("files", {})) != set(budgets):
            raise ValueError("Unexpected unit head artifacts")
        for name, budget in budgets.items():
            path = folder / name
            if not path.is_file() or path.stat().st_size > budget:
                raise ValueError("Unit head artifact missing or over budget")
            if _sha256(path) != plan["files"][name]:
                raise ValueError("Unit head checksum mismatch")

        model = json.loads((folder / "dino-head.json").read_text(encoding="utf-8"))
        if (
            model.get("schema_version") != 1
            or model.get("feature_mode") != "dino"
            or model.get("crop_transform") != "upper_88x80_v1"
            or model.get("encoder_sha256") != plan["files"]["encoder.onnx"]
            or model.get("probabilities_calibrated") is not False
        ):
            raise ValueError("Unit head training/runtime contract mismatch")

        visual = json.loads(
            (root / "configs/catalog/active-visual-reference-v1.json").read_text(encoding="utf-8")
        )
        reference = json.loads(
            (root / visual["reference"] / "reference.json").read_text(encoding="utf-8")
        )
        champions_raw = (root / visual["reference"] / "champions.json").read_bytes()
        if (
            hashlib.sha256(champions_raw).hexdigest()
            != reference["components"]["champions"]["sha256"]
            or plan.get("reference_sha256") != reference["reference_sha256"]
            or plan.get("set_key") != visual["set_key"]
        ):
            raise ValueError("Unit head belongs to another catalog")
        catalog = json.loads(champions_raw)
        self.names = {row["id"]: row["name"] for row in catalog["entries"]}

        head = model.get("head")
        if not isinstance(head, dict):
            raise ValueError("Unit head missing classifier")
        self.labels = head.get("labels")
        self.dimensions = head.get("dimensions")
        weights = head.get("weights")
        biases = head.get("biases")
        if (
            not isinstance(self.labels, list)
            or len(self.labels) < 2
            or len(set(self.labels)) != len(self.labels)
            or not set(self.labels) <= set(self.names) | {"__unknown__"}
            or not isinstance(self.dimensions, int)
            or not 1 <= self.dimensions <= 4096
            or not isinstance(weights, list)
            or len(weights) != len(self.labels) * self.dimensions
            or not isinstance(biases, list)
            or len(biases) != len(self.labels)
        ):
            raise ValueError("Invalid unit classifier dimensions")
        values = [*weights, *biases]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError("Nonfinite unit classifier weights")
        self.weights = np.asarray(weights, dtype=np.float32).reshape(len(self.labels), self.dimensions)
        self.biases = np.asarray(biases, dtype=np.float32)

        self.size = model.get("input_size")
        if not isinstance(self.size, int) or not 64 <= self.size <= 224:
            raise ValueError("Unit head input_size outside runtime budget")
        self.min_probability = plan.get("min_probability")
        self.min_margin = plan.get("min_margin")
        if any(
            type(v) not in (int, float) or not math.isfinite(v) or not 0.0 <= v <= 1.0
            for v in (self.min_probability, self.min_margin)
        ):
            raise ValueError("Unit head acceptance gates missing")

        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(
            str(folder / "encoder.onnx"), options, providers=["CPUExecutionProvider"]
        )
        inputs, outputs = self.session.get_inputs(), self.session.get_outputs()
        if (
            len(inputs) != 1
            or len(inputs[0].shape) != 4
            or inputs[0].shape[1:] != [3, self.size, self.size]
            or not outputs
            or outputs[0].name != "embeddings"
            or len(outputs[0].shape) != 2
            or outputs[0].shape[1] != self.dimensions
        ):
            raise ValueError("DINO encoder tensor contract mismatch")
        self.input_name = inputs[0].name
        self.sha = plan["files"]["dino-head.json"]

    def observe(self, image, read):
        import numpy as np

        started = time.perf_counter()
        proposals = []
        seen = set()
        for marker in read.get("markers", []):
            if marker.get("color") != "green":
                continue
            key = marker.get("id")
            if type(key) is not int or key in seen or len(seen) >= MAX_UNITS:
                raise ValueError("Ambiguous or excessive unit proposals")
            seen.add(key)
            box = unit_box(marker.get("rect"), image.size)
            if box is not None:
                proposals.append((key, box))

        records = []
        if proposals:
            batch = np.stack([
                _upper_88x80_v1(image, box, self.size)
                for _, box in proposals
            ])
            vectors = self.session.run(["embeddings"], {self.input_name: batch})[0]
            if vectors.shape != (len(proposals), self.dimensions) or not np.isfinite(vectors).all():
                raise ValueError("Invalid DINO embeddings")
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            if np.any(norms <= 1e-8):
                raise ValueError("Empty DINO embedding")
            vectors = vectors / norms
            logits = vectors @ self.weights.T + self.biases
            logits -= logits.max(axis=1, keepdims=True)
            probabilities = np.exp(logits)
            probabilities /= probabilities.sum(axis=1, keepdims=True)
            if not np.isfinite(probabilities).all():
                raise ValueError("Invalid unit softmax output")

            for (key, box), scores in zip(proposals, probabilities):
                order = np.argsort(-scores, kind="stable")
                best, second = int(order[0]), int(order[1])
                margin = float(scores[best] - scores[second])
                accepted = (
                    self.labels[best] != "__unknown__"
                    and float(scores[best]) >= self.min_probability
                    and margin >= self.min_margin
                )
                candidate = self.labels[best] if accepted else None
                records.append({
                    "marker_id": key,
                    "box": box,
                    "candidate_id": candidate,
                    "candidate_name": self.names.get(candidate),
                    "status": "identity_candidate" if accepted else "unknown",
                    "softmax_score_uncalibrated": float(scores[best]),
                    "softmax_margin_uncalibrated": margin,
                    "identity_verified": False,
                    "candidates": [
                        {
                            "unit_id": self.labels[int(i)],
                            "score_uncalibrated": float(scores[int(i)]),
                        }
                        for i in order[:3]
                    ],
                })

        return {
            "active": True,
            "records": records,
            "model_sha256": self.sha,
            "processing_ms": (time.perf_counter() - started) * 1000,
            "recognizer": "dino_softmax_head",
            "mode": "diagnostic_candidates",
            "scores_are_calibrated": False,
            "game_state_write_allowed": False,
            "trained_champions": len(set(self.labels) - {"__unknown__"}),
            "catalog_champions": len(self.names),
        }
