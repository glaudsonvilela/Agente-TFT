"""Small ONNX classifier for actual unit crops, separate from shop artwork.

Identity scores alone never establish stars, equipment, ownership or occupancy.
This first model is an explicitly limited laboratory observer.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time

INPUT_SIZE = (64, 72)
MAX_UNITS = 37


def unit_box(rect: dict, size: tuple[int, int]) -> list[int] | None:
    """Keep the crop contract identical in training and runtime; do not pad edges."""
    if not isinstance(rect, dict) or any(
        type(rect.get(k)) is not int for k in ("x", "y", "width", "height")
    ):
        return None
    if not 0 < rect["width"] <= 90 or not 0 < rect["height"] <= 8:
        return None
    center = rect["x"] + rect["width"] // 2
    box = [center - 64, rect["y"] + 8, center + 64, rect["y"] + 152]
    return (
        box
        if 0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1]
        else None
    )


def image_tensor(image, boxes):
    import numpy as np
    from PIL import Image

    return np.stack(
        [
            np.asarray(
                image.crop(box)
                .convert("RGB")
                .resize(INPUT_SIZE, Image.Resampling.BILINEAR),
                dtype=np.float32,
            ).transpose(2, 0, 1)
            / 255
            for box in boxes
        ]
    )


def decode_scores(logits, classes, threshold=0.9, margin=0.25):
    import numpy as np

    values = np.asarray(logits)
    if (
        values.ndim != 2
        or values.shape[1] != len(classes)
        or not np.isfinite(values).all()
    ):
        raise ValueError("Invalid unit classifier output")
    scores = np.exp(values - values.max(axis=1, keepdims=True))
    scores /= scores.sum(axis=1, keepdims=True)
    rows = []
    for probabilities in scores:
        order = np.argsort(-probabilities, kind="stable")
        best, second = int(order[0]), int(order[1])
        accepted = (
            classes[best] != "__unknown__"
            and probabilities[best] >= threshold
            and probabilities[best] - probabilities[second] >= margin
        )
        rows.append(
            dict(
                candidate_id=classes[best] if accepted else None,
                status="identity_candidate" if accepted else "unknown",
                candidates=[
                    dict(unit_id=classes[int(i)], score=float(probabilities[i]))
                    for i in order[:3]
                ],
                identity_verified=False,
            )
        )
    return rows


class UnitIdentityObserver:
    def __init__(self, root: Path):
        import onnxruntime as ort

        plan = json.loads(
            (root / "configs/catalog/active-unit-identity-v1.json").read_text()
        )
        if plan.get("mode") != "diagnostic_candidates":
            raise ValueError("Unit identity release is not approved for semantic state")
        folder = root / "models/unit-identity"
        if set(plan["files"]) != {"unit-identity.onnx", "metadata.json"}:
            raise ValueError("Unexpected unit model artifacts")
        for name, digest in plan["files"].items():
            path = folder / name
            if path.stat().st_size > 2 * 1024**2:
                raise ValueError("Unit model exceeds byte budget")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError("Unit model checksum/budget mismatch")
        self.metadata = json.loads((folder / "metadata.json").read_text())
        visual = json.loads(
            (root / "configs/catalog/active-visual-reference-v1.json").read_text()
        )
        reference = json.loads(
            (root / visual["reference"] / "reference.json").read_text()
        )
        raw = (root / visual["reference"] / "champions.json").read_bytes()
        if (
            hashlib.sha256(raw).hexdigest()
            != reference["components"]["champions"]["sha256"]
        ):
            raise ValueError("Unit catalog checksum mismatch")
        catalog = json.loads(raw)
        self.names = {c["id"]: c["name"] for c in catalog["entries"]}
        self.classes = self.metadata["classes"]
        if (
            len(self.classes) < 2
            or len(set(self.classes)) != len(self.classes)
            or "__unknown__" not in self.classes
            or not set(self.classes) <= set(self.names) | {"__unknown__"}
            or self.metadata.get("reference_sha256") != reference["reference_sha256"]
            or self.metadata.get("set_key") != visual["set_key"]
            or self.metadata.get("input_size") != list(INPUT_SIZE)
            or self.metadata.get("game_state_write_allowed") is not False
            or self.metadata.get("model_sha256") != plan["files"]["unit-identity.onnx"]
        ):
            raise ValueError("Unit classifier catalog/shape/policy mismatch")
        self.sha = self.metadata["model_sha256"]
        self.threshold = self.metadata["threshold"]
        self.margin = self.metadata["margin"]
        if any(
            type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
            for v in (self.threshold, self.margin)
        ):
            raise ValueError("Invalid unit thresholds")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(
            str(folder / "unit-identity.onnx"),
            options,
            providers=["CPUExecutionProvider"],
        )
        if self.session.get_inputs()[0].shape[1:] != [3, 72, 64]:
            raise ValueError("Unit model input changed")

    def observe(self, image, read: dict) -> dict:
        started = time.perf_counter()
        proposals = []
        seen = set()
        for marker in read.get("markers", []):
            if marker.get("color") != "green":
                continue
            key = marker.get("id")
            if type(key) is not int or key in seen or len(proposals) >= MAX_UNITS:
                raise ValueError("Ambiguous or excessive unit proposals")
            seen.add(key)
            box = unit_box(marker.get("rect"), image.size)
            if box is not None:
                proposals.append((key, box))
        records = []
        if proposals:
            values = image_tensor(image, [box for _, box in proposals])
            logits = self.session.run(["logits"], {"units": values})[0]
            if logits.shape[0] != len(proposals):
                raise ValueError("Unit result batch mismatch")
            records = decode_scores(logits, self.classes, self.threshold, self.margin)
            for row, (key, box) in zip(records, proposals):
                row.update(
                    marker_id=key,
                    box=box,
                    candidate_name=self.names.get(row["candidate_id"]),
                )
        return dict(
            active=True,
            records=records,
            model_sha256=self.sha,
            processing_ms=(time.perf_counter() - started) * 1000,
            scope="reviewed_unit_crops_subset",
            mode="diagnostic_candidates",
            scores_are_calibrated=False,
            game_state_write_allowed=False,
            trained_champions=len(self.classes) - 1,
            catalog_champions=len(self.names),
        )
