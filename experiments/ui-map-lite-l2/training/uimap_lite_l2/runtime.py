"""Standalone deployment-side inference: no PyTorch, training, OCR or auto-activation."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from .common import require,sha,load,save,decisions,quantile,contained


class LiteRuntime:
    def __init__(self,path,expected,threads=1):
        path=Path(path)
        require(path.is_file() and not path.is_symlink() and path.stat().st_size<8*1024**2,'invalid ONNX model')
        require(sha(path)==expected,'ONNX checksum')
        require(type(threads) is int and threads in (1,2),'thread budget')
        import onnxruntime as ort
        opts=ort.SessionOptions();opts.intra_op_num_threads=threads;opts.inter_op_num_threads=1
        opts.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        opts.add_session_config_entry('session.intra_op.allow_spinning','0')
        opts.add_session_config_entry('session.inter_op.allow_spinning','0')
        self.session=ort.InferenceSession(str(path),opts,providers=['CPUExecutionProvider'])
        ins=self.session.get_inputs();outs=self.session.get_outputs()
        require(len(ins)==len(outs)==1 and ins[0].name=='image' and ins[0].shape==[1,3,192,320]
                and ins[0].type=='tensor(float)' and outs[0].name=='panels' and outs[0].shape==[1,2,5], 'ONNX IO contract')

    def infer(self,x):
        a=np.asarray(x);require(a.shape==(1,3,192,320) and a.dtype==np.float32
            and np.isfinite(a).all() and a.min()>=0 and a.max()<=1,'bad input tensor')
        out=self.session.run(['panels'],{'image':np.ascontiguousarray(a)})[0]
        require(out.shape==(1,2,5) and np.isfinite(out).all(),'bad model output')
        return out


def main():
    import argparse,json,sys,time,resource,platform
    from PIL import Image
    from .data import image_input
    from .refine import refine_panels
    from .evaluate import benchmark
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle',type=Path,required=True);ap.add_argument('--image-root',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    try:
        meta=load(args.bundle/'deployment-candidate.json');plan=load(args.bundle/'plan.json')['plan']
        rows=load(args.bundle/'manifest.json');require(len(rows)==40,'standalone requires all 40 frames')
        require(meta['validated'] and meta['model']=='candidate-model.onnx' and meta['activation_allowed'] is False,'bad deployment metadata')
        start=time.perf_counter_ns();engine=LiteRuntime(args.bundle/meta['model'],meta['sha256'])
        loading=(time.perf_counter_ns()-start)/1e6
        arrays=[];details=[]
        for r in rows:
            p=contained(args.image_root,r['image']);require(sha(p)==r['sha256'],'original changed')
            start=time.perf_counter_ns()
            with Image.open(p) as im:
                original=np.array(im.convert('RGB'));x=image_input(im)
            prep=(time.perf_counter_ns()-start)/1e6;tic=time.perf_counter_ns()
            out=engine.infer(x[None])[0];forward=(time.perf_counter_ns()-tic)/1e6
            tic=time.perf_counter_ns();decision=decisions(out,plan['evaluation_policy'])
            refined,trace,refine_ms=refine_panels(original,out,plan)
            post=(time.perf_counter_ns()-tic)/1e6;total=(time.perf_counter_ns()-start)/1e6
            arrays.append(x);details.append(dict(timestamp_ms=r['timestamp_ms'],decode_resize_ms=prep,
                forward_ms=forward,postprocess_and_refine_ms=post,total_ms=total,refine_ms=refine_ms,
                coarse=decision,refined=decisions(refined,plan['evaluation_policy']),refinement=trace))
        timing=benchmark(engine.infer,np.stack(arrays))
        require('torch' not in sys.modules,'Torch imported in runtime process')
        summary=dict(policy='uimap-lite-l2-runtime-only',torch_loaded=False,frames=len(rows),
            model_load_ms=loading,resident_inference=timing,process_max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            memory_scope='standalone Python/Numpy/Pillow/ORT, input cache and refinements, not weights only',
            environment=dict(python=platform.python_version(),machine=platform.machine()),
            profile_promoted=False,game_state_updated=False,native_rust_connected=False)
        for field in ('decode_resize_ms','forward_ms','postprocess_and_refine_ms','total_ms'):
            summary[field+'_p50']=quantile([r[field] for r in details],.5)
            summary[field+'_p95']=quantile([r[field] for r in details],.95)
        save(args.output,dict(summary=summary,records=details))
        print('LITE2_RUNTIME_SUMMARY='+json.dumps(summary),flush=True)
    except Exception as e:ap.exit(2,'LITE2_RUNTIME_ERROR='+str(e)+'\n')

if __name__=='__main__':main()
