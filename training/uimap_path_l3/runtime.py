"""Fresh ONNX-only process; a shared RGB buffer, coarse map, optional diagnostic refinement."""
import argparse,json,platform,resource,time
from pathlib import Path
import numpy as np
from . import legacy
from uimap_lite_l2.common import load,save,sha,require,quantile,contained
from uimap_lite_l2.runtime import LiteRuntime
from uimap_lite_l2.evaluate import benchmark
from .pixels import decode
from .geometry import panel_decisions,board_status
from .refine import refine_diagnostic


def run(bundle,image_root,output):
    import sys
    meta=load(bundle/'deployment-candidate.json');plan=load(bundle/'plan.json')
    require(plan['model_schema']=='l3_edge_nodes_bilinear_targets_v1' and plan['activation_allowed'] is False,'L3 schema')
    require(meta['validated'] and meta['activation_allowed'] is False,'unvalidated ONNX graph')
    seal=load(bundle/'COMPLETE.json')
    for n in ('plan.json','manifest.json','deployment-candidate.json','candidate-model.onnx'):
        require(seal.get(n)==sha(bundle/n),'runtime input seal: '+n)
    require(plan['base_plan_sha256']==sha(legacy.L2/'configs/plan.json'),'runtime base plan changed')
    base=load(legacy.L2/'configs/plan.json');rows=load(bundle/'manifest.json')
    require(len(rows)==40,'complete frame batch required')
    started=time.perf_counter_ns();engine=LiteRuntime(bundle/'candidate-model.onnx',meta['sha256'])
    loading=(time.perf_counter_ns()-started)/1e6
    records=[];inputs=[]
    for row in rows:
        p=contained(image_root,row['image']);require(sha(p)==row['sha256'],'image changed')
        tic=time.perf_counter_ns();frame=decode(p,row['timestamp_ms'])
        t=time.perf_counter_ns();raw=engine.infer(frame.tensor[None])[0];forward=(time.perf_counter_ns()-t)/1e6
        t=time.perf_counter_ns();d=panel_decisions(raw,base['evaluation_policy'],frame.frame_id)
        decision=(time.perf_counter_ns()-t)/1e6
        total=(time.perf_counter_ns()-tic)/1e6
        # Diagnostic timing is outside the usable-map path. It cannot silently move the map.
        _,trace,stats=refine_diagnostic(frame.rgb,raw,base)
        records.append(dict(timestamp_ms=frame.frame_id,decode_resize_ms=frame.decode_resize_ms,forward_ms=forward,
            decision_ms=decision,total_without_refinement_ms=total,edge_diagnostic_ms=stats['ms'],
            panels=d,board=board_status(),edge_diagnostic=trace))
        inputs.append(frame.tensor)
    timing=benchmark(engine.infer,np.stack(inputs))
    for row in rows:
        require(sha(contained(image_root,row['image']))==row['sha256'],'image changed during runtime')
    require(sha(bundle/'candidate-model.onnx')==meta['sha256'],'ONNX changed during runtime')
    require('torch' not in sys.modules,'trainer leaked into runtime')
    summary=dict(policy='uimap-path-l3-runtime',frames=40,torch_loaded=False,model_load_ms=loading,
        resident_inference=timing,refinement_applied=False,process_max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        memory_scope='Python+ORT+prepared40frames+diagnostic strips; not native Rust deployment',
        profile_promoted=False,game_state_updated=False,native_rust_connected=False,board_mapping_established=False,
        environment=dict(python=platform.python_version(),numpy=np.__version__))
    for field in ('decode_resize_ms','forward_ms','decision_ms','total_without_refinement_ms','edge_diagnostic_ms'):
        summary[field+'_p50']=quantile([x[field] for x in records],.5)
        summary[field+'_p95']=quantile([x[field] for x in records],.95)
    save(output,dict(summary=summary,records=records));print('LITE3_RUNTIME_SUMMARY='+json.dumps(summary),flush=True)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('bundle','image-root','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args()
    try:run(a.bundle,a.image_root,a.output)
    except Exception as e:p.exit(2,'LITE3_RUNTIME_ERROR='+str(e)+'\n')
if __name__=='__main__':main()
