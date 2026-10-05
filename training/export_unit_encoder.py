"""Export frozen public visual features; no optimizer or game labels involved.

Training-only dependencies stay outside the Windows runtime. DINOv2 source is
an explicit local checkout; MobileNet weights use torchvision's official URL.
"""

import argparse
import hashlib
import json
from pathlib import Path

DINO_REVISION = "7764ea0f912e53c92e82eb78a2a1631e92725fc8"


def export(args):
    import torch

    if args.output.exists() or args.size not in (140, 224):
        raise ValueError("New output directory and 140 or 224 pixels required")
    torch.set_num_threads(2)
    torch.hub.set_dir(str(args.cache))
    if args.backbone == "mobilenet_v3_small":
        from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights

        weights = MobileNet_V3_Small_Weights.IMAGENET1K_V1
        model = mobilenet_v3_small(weights=weights).eval()
        base = torch.nn.Sequential(model.features, model.avgpool, torch.nn.Flatten())
        source = weights.url
    else:
        if args.dinov2_source is None:
            raise ValueError("Explicit reviewed DINOv2 source directory required")
        source = f"https://github.com/facebookresearch/dinov2/tree/{DINO_REVISION}"
        if args.dinov2_source.name != "facebookresearch_dinov2_" + DINO_REVISION:
            raise ValueError("Use the pinned torch.hub checkout recorded in evidence")
        base = torch.hub.load(
            str(args.dinov2_source), "dinov2_vits14", source="local"
        ).eval()
        if args.dinov2_blocks != 12:
            # Experimental truncation, NOT equivalent to distillation or the
            # original checkpoint. Its gallery must be rebuilt and evaluated.
            base.blocks = torch.nn.ModuleList(list(base.blocks)[: args.dinov2_blocks])

    class Encoder(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.base = base
            self.register_buffer(
                "mean", torch.tensor([0.485, 0.456, 0.406])[None, :, None, None]
            )
            self.register_buffer(
                "std", torch.tensor([0.229, 0.224, 0.225])[None, :, None, None]
            )

        def forward(self, units):
            return torch.nn.functional.normalize(
                self.base((units - self.mean) / self.std), dim=1
            )

    encoder = Encoder().eval()
    args.output.mkdir(parents=True)
    path = args.output / "encoder.onnx"
    torch.onnx.export(
        encoder,
        torch.zeros(1, 3, args.size, args.size),
        str(path),
        input_names=["units"],
        output_names=["embeddings"],
        dynamic_axes={"units": {0: "batch"}, "embeddings": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    import onnx
    import numpy as np
    import onnxruntime as ort

    onnx.checker.check_model(str(path))
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    rng = np.random.default_rng(20261004)
    sample = rng.random((2, 3, args.size, args.size), dtype=np.float32)
    with torch.inference_mode():
        expected = encoder(torch.from_numpy(sample)).numpy()
    delta = float(
        np.abs(expected - session.run(["embeddings"], {"units": sample})[0]).max()
    )
    if delta >= 0.001:
        raise ValueError("PyTorch/ONNX parity failed")
    report = dict(
        backbone=args.backbone,
        input_size=args.size,
        source=source,
        encoder_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        bytes=path.stat().st_size,
        parameters=sum(p.numel() for p in encoder.parameters()),
        export_max_abs_error=delta,
        training_performed=False,
        runtime_approved=False,
    )
    if args.backbone == "dinov2_vits14":
        report["transformer_blocks"] = args.dinov2_blocks
        report["experimental_truncation"] = args.dinov2_blocks != 12
        report["accuracy_equivalence_claimed"] = False
    if args.quantize:
        from onnxruntime.quantization import quantize_dynamic, QuantType

        target = args.output / "encoder-int8.onnx"
        quantize_dynamic(
            str(path),
            str(target),
            weight_type=QuantType.QInt8,
            op_types_to_quantize=["MatMul", "Gemm"],
            per_channel=True,
        )
        report["quantized"] = dict(
            path=target.name,
            bytes=target.stat().st_size,
            sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            accuracy_requires_separate_evaluation=True,
        )
    (args.output / "export.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backbone", choices=["mobilenet_v3_small", "dinov2_vits14"], required=True
    )
    parser.add_argument("--size", type=int, default=224)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--dinov2-source", type=Path)
    parser.add_argument(
        "--dinov2-blocks",
        type=int,
        choices=(6, 9, 12),
        default=12,
        help="Experimental block truncation; requires a new gallery/evaluation",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quantize", action="store_true")
    export(parser.parse_args())
