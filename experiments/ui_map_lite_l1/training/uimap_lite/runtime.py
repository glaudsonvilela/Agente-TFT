"""Deployment-side CPU ONNX reader: deliberately no torch import and no trainer."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from .common import require, sha, load, proposals


class LiteRuntime:
    def __init__(self, model_path: Path, expected_sha256: str, threads: int = 1):
        require(model_path.is_file() and not model_path.is_symlink(), 'model file missing or symlink')
        require(model_path.stat().st_size < 8*1024**2, 'model exceeds L1 size budget')
        require(sha(model_path) == expected_sha256, 'model checksum mismatch')
        require(threads in (1,2), 'unsupported thread budget')
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.add_session_config_entry('session.intra_op.allow_spinning','0')
        options.add_session_config_entry('session.inter_op.allow_spinning','0')
        self.session = ort.InferenceSession(str(model_path), options,
                                           providers=['CPUExecutionProvider'])
        require(len(self.session.get_inputs())==1 and len(self.session.get_outputs())==1, 'graph IO mismatch')
        inp = self.session.get_inputs()[0]
        require(inp.name=='image' and inp.shape==[1,3,192,320] and inp.type=='tensor(float)', 'input contract mismatch')

    def infer(self, image):
        x=np.asarray(image)
        require(x.shape==(1,3,192,320) and x.dtype==np.float32 and np.isfinite(x).all(), 'invalid frame tensor')
        require(x.min()>=0 and x.max()<=1, 'input must be normalized RGB [0,1]')
        result=self.session.run(['panels'], {'image':np.ascontiguousarray(x)})[0]
        require(result.shape==(1,2,5) and np.isfinite(result).all(), 'invalid graph output')
        return result


def main():
    import argparse
    import json
    import resource
    import sys
    import time
    from .data import input_image
    from .evaluate import benchmark
    from .common import save
    parser=argparse.ArgumentParser(description='Standalone inference only; no Torch/trainer')
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:
        metadata=load(args.bundle/'deployment-candidate.json')
        require(metadata['model']=='candidate-model.onnx' and metadata['validated'] is True,
                'unvalidated candidate graph')
        start=time.perf_counter_ns()
        engine=LiteRuntime(args.bundle/'candidate-model.onnx',metadata['sha256'])
        load_ms=(time.perf_counter_ns()-start)/1e6
        x=input_image(args.image)
        result=engine.infer(x[None])
        timing=benchmark(engine.infer,np.repeat(x[None],2,axis=0))
        require('torch' not in sys.modules,'Torch was unexpectedly loaded in deployment process')
        report=dict(policy='uimap-lite-l1-runtime-only',torch_loaded=False,model_load_ms=load_ms,
            resident_inference=timing,process_max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            memory_scope='standalone ONNX runtime process, including Python/Numpy/Pillow',
            panels=proposals(result[0]),profile_promoted=False,game_state_updated=False,
            native_rust_connected=False)
        save(args.output,report)
        print('LITE1_RUNTIME_SUMMARY='+json.dumps(report),flush=True)
    except Exception as error:parser.exit(2,'LITE1_RUNTIME_ERROR='+str(error)+'\n')

if __name__=='__main__':main()
