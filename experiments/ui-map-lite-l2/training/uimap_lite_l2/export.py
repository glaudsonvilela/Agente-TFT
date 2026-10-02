"""Export a candidate only; require actual forward equivalence on validation tensors."""
import importlib.util
import numpy as np
from .common import require,sha,save


def export_checked(model,examples,out,required):
    if not all(importlib.util.find_spec(k) for k in ('onnx','onnxruntime')):
        require(not required,'ONNX dependencies missing; no valid export claimed')
        return dict(exported=False,validated=False,reason='dependencies_missing_locally')
    import torch,onnx
    from .runtime import LiteRuntime
    p=out/'candidate-model.onnx';require(not p.exists(),'model output exists')
    model.eval()
    torch.onnx.export(model,torch.from_numpy(examples[:1]),str(p),input_names=['image'],output_names=['panels'],
        opset_version=17,dynamo=False,external_data=False)
    onnx.checker.check_model(str(p));engine=LiteRuntime(p,sha(p));worst=0
    with torch.inference_mode():
        for example in examples[:16]:
            x=example[None];expected=model(torch.from_numpy(x)).numpy();got=engine.infer(x)
            worst=max(worst,float(abs(got-expected).max()))
    require(worst<=1e-4,'ONNX equivalence failed')
    info=dict(exported=True,validated=True,sha256=sha(p),bytes=p.stat().st_size,
              max_abs_error=worst,samples=min(16,len(examples)),opset=17,native_rust_tested=False)
    save(out/'deployment-candidate.json',dict(schema_version=2,model=p.name,**info,activation_allowed=False,
         input_shape=[1,3,192,320],output_shape=[1,2,5],coordinate_format='normalized_tlbr',
         panels=['bench','shop'],requires_semantic_validation=True))
    return info
