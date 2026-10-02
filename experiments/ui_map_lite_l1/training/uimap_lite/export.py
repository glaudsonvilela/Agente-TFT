"""Fixed-shape ONNX export; equivalence must pass before a deployment candidate exists."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import numpy as np
from .common import require, sha, save
from .runtime import LiteRuntime


def export_checked(model, examples, output: Path, required: bool):
    available = all(importlib.util.find_spec(m) is not None for m in ('onnx','onnxruntime'))
    if not available:
        require(not required, 'ONNX export dependencies missing; training artifacts retained, no valid export claimed')
        return dict(exported=False, validated=False, reason='dependencies_not_available', native_rust_tested=False)
    import torch
    import onnx
    path=output/'candidate-model.onnx'
    require(not path.exists(), 'ONNX output already exists')
    model.eval()
    torch.onnx.export(model, torch.from_numpy(examples[:1]), str(path),
        input_names=['image'], output_names=['panels'], opset_version=17, dynamo=False,
        external_data=False)
    onnx.checker.check_model(str(path))
    runtime=LiteRuntime(path,sha(path))
    worst=0.
    with torch.inference_mode():
        for example in examples[:16]:
            x=example[None]
            reference=model(torch.from_numpy(x)).numpy()
            predicted=runtime.infer(x)
            worst=max(worst,float(np.max(np.abs(reference-predicted))))
    require(worst<=1e-4,'ONNX/PyTorch mismatch; candidate cannot be used')
    result=dict(exported=True,validated=True,sha256=sha(path),bytes=path.stat().st_size,
        max_abs_error=worst, samples=min(16,len(examples)),opset=17,
        active_profile_written=False,native_rust_tested=False)
    save(output/'deployment-candidate.json', dict(schema_version=1,model='candidate-model.onnx',
        **result, input_shape=[1,3,192,320],output_shape=[1,2,5], activation_allowed=False,
        panels=['bench','shop'], requires_refinement=True))
    return result
