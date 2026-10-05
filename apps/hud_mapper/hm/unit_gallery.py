"""Frozen visual encoder + reviewed gameplay gallery; no strategic assertions.

The gallery belongs to a seasonal catalog. Similarity is not a probability and
repeated frames do not manufacture independent evidence of identity.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import time

from .unit_identity import MAX_UNITS, unit_box


def rank_gallery(vectors, gallery, labels, threshold=0.8, margin=0.08):
    import numpy as np

    vectors, gallery = np.asarray(vectors), np.asarray(gallery)
    if (
        vectors.ndim != 2
        or gallery.ndim != 2
        or vectors.shape[1] != gallery.shape[1]
        or len(labels) != len(gallery)
        or not len(gallery)
        or len(set(labels)) < 2
        or not np.isfinite(vectors).all()
        or not np.isfinite(gallery).all()
        or any(not isinstance(v, str) or not v for v in labels)
        or any(
            type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
            for v in (threshold, margin)
        )
    ):
        raise ValueError("Invalid visual gallery")
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    gallery_norms = np.linalg.norm(gallery, axis=1, keepdims=True)
    if np.any(norms < 1e-8) or np.any(gallery_norms < 1e-8):
        raise ValueError("Empty visual embedding")
    similarities = (vectors / norms) @ (gallery / gallery_norms).T
    classes = sorted(set(labels))
    label_array = np.asarray(labels)
    # Several views of the same champion must not become runner-up classes.
    scores = np.stack(
        [similarities[:, label_array == c].max(axis=1) for c in classes], axis=1
    )
    result = []
    for row in scores:
        order = np.argsort(-row, kind="stable")
        best, runner_up = int(order[0]), int(order[1])
        gap = float(row[best] - row[runner_up])
        accepted = (
            classes[best] != "__unknown__" and row[best] >= threshold and gap >= margin
        )
        result.append(
            dict(
                candidate_id=classes[best] if accepted else None,
                status="identity_candidate" if accepted else "unknown",
                similarity_margin=gap,
                identity_verified=False,
                candidates=[
                    dict(unit_id=classes[int(i)], similarity=float(row[i]))
                    for i in order[:3]
                ],
            )
        )
    return result


def gallery_tensor(image, boxes, size):
    import numpy as np
    from PIL import Image

    return np.stack(
        [
            np.asarray(
                image.crop(box)
                .convert("RGB")
                .resize((size, size), Image.Resampling.BICUBIC),
                dtype=np.float32,
            ).transpose(2, 0, 1)
            / 255
            for box in boxes
        ]
    )


class UnitGalleryObserver:
    def __init__(self, root: Path):
        import numpy as np
        import onnxruntime as ort

        plan = json.loads(
            (root / "configs/catalog/active-unit-gallery-v1.json").read_text(
                encoding="utf-8"
            )
        )
        if plan.get("mode") != "diagnostic_candidates":
            raise ValueError("Gallery is not approved for semantic state")
        folder = root / "models/unit-gallery"
        budgets = {
            "encoder.onnx": 96 * 1024**2,
            "gallery.npy": 8 * 1024**2,
            "metadata.json": 1024**2,
        }
        if set(plan["files"]) != set(budgets):
            raise ValueError("Unexpected gallery files")
        for name, budget in budgets.items():
            path = folder / name
            if path.stat().st_size > budget:
                raise ValueError("Gallery byte budget exceeded")
            if hashlib.sha256(path.read_bytes()).hexdigest() != plan["files"][name]:
                raise ValueError("Gallery checksum mismatch")
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        active = json.loads(
            (root / "configs/catalog/active-visual-reference-v1.json").read_text(
                encoding="utf-8"
            )
        )
        reference = json.loads(
            (root / active["reference"] / "reference.json").read_text(encoding="utf-8")
        )
        raw = (root / active["reference"] / "champions.json").read_bytes()
        if (
            hashlib.sha256(raw).hexdigest()
            != reference["components"]["champions"]["sha256"]
            or metadata["reference_sha256"] != reference["reference_sha256"]
            or metadata["set_key"] != active["set_key"]
            or metadata.get("game_state_write_allowed") is not False
        ):
            raise ValueError("Gallery catalog mismatch")
        self.names = {row["id"]: row["name"] for row in json.loads(raw)["entries"]}
        self.labels = metadata["labels"]
        if (
            not isinstance(self.labels, list)
            or not 2 <= len(self.labels) <= 4096
            or not all(isinstance(v, str) for v in self.labels)
            or not set(self.labels) <= set(self.names) | {"__unknown__"}
        ):
            raise ValueError("Invalid gallery identities")
        self.size = metadata["input_size"]
        if type(self.size) is not int or not 64 <= self.size <= 224:
            raise ValueError("Invalid encoder resolution")
        self.gallery = np.load(folder / "gallery.npy", allow_pickle=False)
        self.threshold, self.margin = metadata["threshold"], metadata["margin"]
        rank_gallery(
            self.gallery[:1], self.gallery, self.labels, self.threshold, self.margin
        )
        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.session = ort.InferenceSession(
            str(folder / "encoder.onnx"), options, providers=["CPUExecutionProvider"]
        )
        if (
            self.session.get_inputs()[0].name != "units"
            or self.session.get_inputs()[0].shape[1:] != [3, self.size, self.size]
            or self.session.get_outputs()[0].name != "embeddings"
            or self.session.get_outputs()[0].shape[1:] != [self.gallery.shape[1]]
        ):
            raise ValueError("Encoder tensor contract mismatch")
        self.sha = plan["files"]["encoder.onnx"]

    def observe(self, image, read):
        started = time.perf_counter()
        proposals, seen = [], set()
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
            values = gallery_tensor(image, [box for _, box in proposals], self.size)
            vectors = self.session.run(["embeddings"], {"units": values})[0]
            if len(vectors) != len(proposals):
                raise ValueError("Encoder batch mismatch")
            records = rank_gallery(
                vectors, self.gallery, self.labels, self.threshold, self.margin
            )
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
            recognizer="frozen_encoder_gameplay_gallery",
            mode="diagnostic_candidates",
            scores_are_calibrated=False,
            game_state_write_allowed=False,
            trained_champions=len(set(self.labels) - {"__unknown__"}),
            catalog_champions=len(self.names),
        )
