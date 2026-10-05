"""Train on reviewed 3D unit crops; evaluate on entirely different matches.

Riot shop portraits bind IDs but are never substituted for gameplay training
images. Unreviewed champions remain unknown. This lab cannot promote a model.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

from training.board_review import require, validate


def samples(document, root, catalog, reference_sha):
    from apps.hud_mapper.hm.unit_identity import unit_box

    validate(document, root)
    ids = {entry["id"] for entry in catalog["entries"]}
    groups, sessions, pixels = {}, {}, {}
    result = {key: [] for key in ("train", "validation", "test")}
    for frame in document["frames"]:
        split = frame.get("identity_split")
        require(split in result, "explicit identity split required")
        require(
            frame.get("patch_binding", {}).get("set_key") == catalog["set_key"],
            "review/catalog set mismatch",
        )
        for index, key in (
            (groups, "match_group"),
            (sessions, "session_id"),
            (pixels, "pixel_sha256"),
        ):
            value = frame.get(key)
            require(isinstance(value, str) and value, "split provenance missing")
            require(
                index.setdefault(value, split) == split, "match/session/pixel leakage"
            )
        layout = {u["key"]: u for u in frame["layout"]["units"]}
        for entity in frame["entities"]:
            identity = entity["identity"]
            label = (
                identity.get("id") if identity["state"] == "known" else "__unknown__"
            )
            require(
                label in ids | {"__unknown__"}, "reviewed champion absent from catalog"
            )
            unit = layout[entity["key"]]
            require(
                unit["box"]
                == unit_box(unit.get("bar_rect"), tuple(frame["image_size"])),
                "training/runtime crop mismatch",
            )
            result[split].append(
                dict(
                    image=frame["image"],
                    box=unit["box"],
                    label=label,
                    frame_sha256=frame["sha256"],
                    key=entity["key"],
                    match_group=frame["match_group"],
                    reference_sha256=reference_sha,
                )
            )
        # Explicitly reviewed HUD rectangles are negative unit examples, not
        # unlabeled units being relabeled as empty background.
        for n, negative in enumerate(frame.get("identity_negatives", [])):
            box = negative.get("box")
            require(
                negative.get("basis") == "assistant_reviewed_nonunit_hud",
                "negative review missing",
            )
            require(
                isinstance(box, list)
                and len(box) == 4
                and all(type(v) is int for v in box)
                and 0 <= box[0] < box[2] <= frame["image_size"][0]
                and 0 <= box[1] < box[3] <= frame["image_size"][1],
                "negative box invalid",
            )
            result[split].append(
                dict(
                    image=frame["image"],
                    box=box,
                    label="__unknown__",
                    frame_sha256=frame["sha256"],
                    key=f"negative-{n}",
                    match_group=frame["match_group"],
                    reference_sha256=reference_sha,
                )
            )
    require(all(result.values()), "three nonempty match splits required")
    return result


def run(args):
    import numpy as np
    from PIL import Image
    import torch
    from torch import nn
    import onnxruntime as ort
    from apps.hud_mapper.hm.unit_identity import INPUT_SIZE, image_tensor, decode_scores

    require(100 <= args.steps <= 3000, "step budget must be 100..3000")
    require(not args.output.exists(), "use a new output directory")
    doc_bytes = args.annotations.read_bytes()
    document = json.loads(doc_bytes)
    reference = json.loads((args.reference / "reference.json").read_text())
    raw_catalog = (args.reference / "champions.json").read_bytes()
    require(
        hashlib.sha256(raw_catalog).hexdigest()
        == reference["components"]["champions"]["sha256"],
        "catalog checksum mismatch",
    )
    catalog = json.loads(raw_catalog)
    rows = samples(document, args.images, catalog, reference["reference_sha256"])
    classes = sorted({s["label"] for s in rows["train"]})
    require(
        "__unknown__" in classes and len(classes) > 2,
        "known classes and reviewed negatives needed",
    )
    require(
        all(s["label"] in classes for split in rows.values() for s in split),
        "unseen labels need explicit unknown review",
    )
    require(
        any(s["label"] == "__unknown__" for s in rows["validation"]),
        "validation needs unknown examples",
    )
    args.output.mkdir(parents=True)
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.manual_seed(20261004)
    np.random.seed(20261004)

    def tensors(partition):
        images = []
        for sample in partition:
            with Image.open(args.images / sample["image"]) as image:
                images.append(image_tensor(image, [sample["box"]])[0])
        return torch.from_numpy(np.stack(images)), torch.tensor(
            [classes.index(s["label"]) for s in partition]
        )

    tensors_by_split = {key: tensors(value) for key, value in rows.items()}
    x, y = tensors_by_split["train"]
    model = nn.Sequential(
        nn.Conv2d(3, 12, 5, stride=2, padding=2),
        nn.ReLU(),
        nn.Conv2d(12, 24, 3, stride=2, padding=1),
        nn.ReLU(),
        nn.Conv2d(24, 32, 3, stride=2, padding=1),
        nn.ReLU(),
        nn.AdaptiveAvgPool2d((3, 2)),
        nn.Flatten(),
        nn.Linear(192, len(classes)),
    )
    initial = [p.detach().clone() for p in model.parameters()]
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.002)
    weights = torch.bincount(y).float().reciprocal()
    generator = torch.Generator().manual_seed(20261004)
    started = time.monotonic()
    losses = []
    with (args.output / "training.jsonl").open("x") as log:
        for step in range(args.steps):
            indices = torch.multinomial(
                weights[y], 24, replacement=True, generator=generator
            )
            batch = x[indices].clone()
            # Only brightness/noise and small translations; no left-right flips
            # that invent a view not seen by the TFT camera.
            shifts = torch.randint(-3, 4, (2,), generator=generator).tolist()
            batch = torch.roll(batch, shifts, (2, 3))
            if shifts[0] > 0:
                batch[:, :, : shifts[0], :] = 0
            if shifts[0] < 0:
                batch[:, :, shifts[0] :, :] = 0
            if shifts[1] > 0:
                batch[:, :, :, : shifts[1]] = 0
            if shifts[1] < 0:
                batch[:, :, :, shifts[1] :] = 0
            batch = (
                batch * (torch.rand(24, 1, 1, 1) * 0.3 + 0.85)
                + torch.randn_like(batch) * 0.015
            ).clamp(0, 1)
            loss = nn.functional.cross_entropy(model(batch), y[indices])
            require(bool(torch.isfinite(loss)), "nonfinite training loss")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
            if step % 50 == 0 or step == args.steps - 1:
                log.write(json.dumps(dict(step=step + 1, loss=losses[-1])) + "\n")
                log.flush()
    model.eval()
    with torch.inference_mode():
        logits = {
            split: model(values[0]).numpy()
            for split, values in tensors_by_split.items()
        }
    # Fixed thresholds; validation and test are reports, never an optimization
    # target. In particular, high softmax is not calibrated correctness.
    threshold, margin = 0.9, 0.25
    reports, predictions = {}, {}
    for split, observations in rows.items():
        decoded = decode_scores(logits[split], classes, threshold, margin)
        correct, accepted, wrong = Counter(), Counter(), Counter()
        output = []
        for sample, prediction in zip(observations, decoded):
            label = sample["label"]
            predicted = prediction["candidate_id"] or "__unknown__"
            correct[label] += predicted == label
            accepted[label] += predicted != "__unknown__"
            wrong[label] += predicted != "__unknown__" and predicted != label
            output.append(dict(**sample, predicted=predicted, **prediction))
        counts = Counter(row["label"] for row in observations)
        reports[split] = dict(
            crops=len(observations),
            matches=len({r["match_group"] for r in observations}),
            correct=sum(correct.values()),
            accepted=sum(accepted.values()),
            false_accepts=sum(wrong.values()),
            by_class={
                key: dict(
                    samples=value,
                    correct=correct[key],
                    accepted=accepted[key],
                    false_accepts=wrong[key],
                )
                for key, value in counts.items()
            },
        )
        predictions[split] = output
    torch.onnx.export(
        model,
        torch.zeros(1, 3, 72, 64),
        str(args.output / "unit-identity.onnx"),
        input_names=["units"],
        output_names=["logits"],
        dynamic_axes={"units": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    runtime = ort.InferenceSession(
        str(args.output / "unit-identity.onnx"),
        options,
        providers=["CPUExecutionProvider"],
    )
    test_x = tensors_by_split["test"][0].numpy()
    parity = float(
        np.abs(runtime.run(None, {"units": test_x})[0] - logits["test"]).max()
    )
    require(parity < 0.001, "ONNX parity failed")
    timing = []
    for _ in range(60):
        t = time.perf_counter()
        runtime.run(None, {"units": test_x})
        timing.append((time.perf_counter() - t) * 1000)
    model_raw = (args.output / "unit-identity.onnx").read_bytes()
    metadata = dict(
        schema_version=1,
        kind="unit_identity",
        set_key=catalog["set_key"],
        reference_sha256=reference["reference_sha256"],
        classes=classes,
        input_size=list(INPUT_SIZE),
        crop="bar_center_x+-64;y+8..y+152",
        resize="bilinear_rgb",
        model_sha256=hashlib.sha256(model_raw).hexdigest(),
        threshold=threshold,
        margin=margin,
        scores_are_calibrated=False,
        game_state_write_allowed=False,
    )
    report = dict(
        schema_version=1,
        kind="unit_identity_training",
        status="trained_evaluated_not_promoted",
        annotation_sha256=hashlib.sha256(doc_bytes).hexdigest(),
        partitions=reports,
        optimizer_steps=args.steps,
        changed_parameter_tensors=sum(
            not torch.equal(a, b) for a, b in zip(initial, model.parameters())
        ),
        parameters=sum(p.numel() for p in model.parameters()),
        model_bytes=len(model_raw),
        model_sha256=metadata["model_sha256"],
        onnx_max_absolute_error=parity,
        seconds=time.monotonic() - started,
        loss_first_25=float(np.mean(losses[:25])),
        loss_last_25=float(np.mean(losses[-25:])),
        batch_size=len(test_x),
        inference_cpu_batch_ms_p50=float(np.percentile(timing[10:], 50)),
        inference_cpu_batch_ms_p95=float(np.percentile(timing[10:], 95)),
        trained_champions=len(classes) - 1,
        catalog_champions=len(catalog["entries"]),
        missing_champions=sorted({e["id"] for e in catalog["entries"]} - set(classes)),
        runtime_approved=False,
        complete_board_states=0,
        limitations=[
            "Assistant visual labels, no independent human review",
            "Few examples and limited per-class match coverage",
            "Detector proposal recall not measured by crop classification",
            "No star, ownership, ground-cell or item confirmation",
        ],
    )
    for name, value in (
        ("metadata", metadata),
        ("report", report),
        ("predictions", predictions),
    ):
        (args.output / f"{name}.json").write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=600)
    run(parser.parse_args())
