"""Build a training-only reference gallery and evaluate disjoint match crops.

An unknown annotation is not a reliable negative champion label. Report named
units separately from unreviewed ones. Reused test partitions are development
comparisons, not a new independent release validation.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

from training.train_unit_identity import samples
from apps.hud_mapper.hm.unit_gallery import gallery_tensor, rank_gallery


def evaluate(args):
    import numpy as np
    from PIL import Image
    import onnxruntime as ort

    if args.output.exists() or not 64 <= args.size <= 224:
        raise ValueError("New output folder and bounded input size required")
    document = json.loads(args.annotations.read_text(encoding="utf-8"))
    reference = json.loads(
        (args.reference / "reference.json").read_text(encoding="utf-8")
    )
    raw_catalog = (args.reference / "champions.json").read_bytes()
    if (
        hashlib.sha256(raw_catalog).hexdigest()
        != reference["components"]["champions"]["sha256"]
    ):
        raise ValueError("Catalog hash mismatch")
    catalog = json.loads(raw_catalog)
    rows = samples(document, args.images, catalog, reference["reference_sha256"])
    options = ort.SessionOptions()
    options.intra_op_num_threads = options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    session = ort.InferenceSession(
        str(args.encoder), options, providers=["CPUExecutionProvider"]
    )
    features, tensors = {}, {}
    for split, records in rows.items():
        images = []
        for row in records:
            with Image.open(args.images / row["image"]) as image:
                images.append(gallery_tensor(image, [row["box"]], args.size)[0])
        tensors[split] = np.stack(images)
        features[split] = np.concatenate(
            [
                session.run(["embeddings"], {"units": tensors[split][i : i + 4]})[0]
                for i in range(0, len(images), 4)
            ]
        )
    labels = [row["label"] for row in rows["train"]]
    predictions, metrics = {}, {}
    for split in ("validation", "test"):
        decoded = rank_gallery(features[split], features["train"], labels)
        values = [
            dict(**row, **prediction) for row, prediction in zip(rows[split], decoded)
        ]
        named = [row for row in values if row["label"] != "__unknown__"]
        metrics[split] = dict(
            crops=len(values),
            named_crops=len(named),
            named_top1_correct=sum(
                row["candidates"][0]["unit_id"] == row["label"] for row in named
            ),
            named_candidates_accepted=sum(
                row["candidate_id"] is not None for row in named
            ),
            named_wrong_candidates_accepted=sum(
                row["candidate_id"] not in (None, row["label"]) for row in named
            ),
            unreviewed_crops=len(values) - len(named),
            candidates_on_unreviewed_crops=sum(
                row["candidate_id"] is not None
                for row in values
                if row["label"] == "__unknown__"
            ),
        )
        predictions[split] = values
    timings = []
    benchmark = tensors["test"][:12]
    for index in range(11):
        start = time.perf_counter()
        session.run(["embeddings"], {"units": benchmark})
        duration = (time.perf_counter() - start) * 1000
        if index:
            timings.append(duration)
    args.output.mkdir(parents=True)
    shutil.copyfile(args.encoder, args.output / "encoder.onnx")
    np.save(args.output / "gallery.npy", features["train"], allow_pickle=False)
    metadata = dict(
        schema_version=1,
        input_size=args.size,
        labels=labels,
        threshold=0.8,
        margin=0.08,
        set_key=catalog["set_key"],
        reference_sha256=reference["reference_sha256"],
        annotations_sha256=hashlib.sha256(args.annotations.read_bytes()).hexdigest(),
        gallery_sources=rows["train"],
        game_state_write_allowed=False,
    )
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2))
    plan = dict(
        mode="diagnostic_candidates",
        files={
            name: hashlib.sha256((args.output / name).read_bytes()).hexdigest()
            for name in ("encoder.onnx", "gallery.npy", "metadata.json")
        },
    )
    (args.output / "lab-plan.json").write_text(json.dumps(plan, indent=2))
    report = dict(
        schema_version=1,
        mode="development_comparison",
        metrics=metrics,
        gallery_champions=len(set(labels) - {"__unknown__"}),
        gallery_samples=len(labels),
        catalog_champions=len(catalog["entries"]),
        encoder_sha256=plan["files"]["encoder.onnx"],
        encoder_bytes=(args.output / "encoder.onnx").stat().st_size,
        inference_ms=dict(
            batch=len(benchmark),
            threads=1,
            median=float(np.median(timings)),
            p95=float(np.percentile(timings, 95)),
        ),
        torch_imported="torch" in sys.modules,
        runtime_approved=False,
        independent_human_ground_truth=False,
        reused_test_partition=True,
        strategic_state_verified=False,
    )
    (args.output / "report.json").write_text(json.dumps(report, indent=2))
    (args.output / "predictions.json").write_text(json.dumps(predictions, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("annotations", "images", "reference", "encoder", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--size", type=int, required=True)
    evaluate(parser.parse_args())
