"""Whole-path comparison: immutable L2 -> canonical pixels -> L3 -> measured contracts."""
import argparse,json,platform,signal,time
from pathlib import Path
from collections import Counter
import numpy as np
from . import legacy
from uimap_lite_l2.common import load,save,sha,require,quantile
from uimap_lite_l2.data import source_manifest
from uimap_lite_l2.evaluate import benchmark
from .evidence import baseline,locate,validate_plan,seal_output
from .pixels import decode
from .geometry import panel_decisions,board_status
from .refine import refine_diagnostic
from .data import Renderer
from .evaluate import grouped,failures


def run(args):
    import torch
    from .train import fit
    from .model import MODEL_SCHEMA
    from uimap_lite_l2.model import load_weights as old_weights
    from uimap_lite_l2.refine import refine_panels as old_refine
    from uimap_lite_l2.export import export_checked
    out=args.output.absolute();require(not out.exists(),'output already exists')
    plan=load(args.plan);base_file=legacy.L2/'configs/plan.json';base=validate_plan(plan,base_file)
    rows,sources=source_manifest(args.image_root,base,args.manifest)
    bp,receipt=baseline(args.baseline)
    require(load(bp/'manifest.json')==rows,'L3 must use exactly the same 40 L2 images/timestamps')
    for p in [args.plan,base_file,bp/'weights.npz',bp/'COMPLETE.json']:
        sources[str(p.resolve())]=sha(p)
    for p in Path(__file__).parent.glob('*.py'):sources[str(p.resolve())]=sha(p)
    out.mkdir(parents=True,exist_ok=False)
    save(out/'sources.json',sources);save(out/'manifest.json',rows);save(out/'plan.json',plan);save(out/'baseline.json',receipt)
    try:
        render={s:Renderer(args.image_root,base,plan,s) for s in ('train','validation','test')}
        model,training,parity=fit(render['train'],render['validation'],plan,out,bp/'weights.npz')
        torch.set_num_threads(1);old=old_weights(bp/'weights.npz')
        def forward(engine,x):
            with torch.inference_mode():return engine(torch.from_numpy(np.array(x,dtype=np.float32,copy=True))).numpy()
        oldpred=[];oldref=[];newpred=[];target=[];visible=[];modes=[];records=[]
        print('LITE3_PHASE=paired_same_pixel_holdout',flush=True)
        for i in range(plan['test_samples']):
            frame,y,v,meta=render['test'].sample(plan['test_seed']+i)
            a=forward(old,frame.tensor[None])[0];b=forward(model,frame.tensor[None])[0]
            r,trace,stats=refine_diagnostic(frame.rgb,a,base)
            oldpred.append(a);oldref.append(r);newpred.append(b);target.append(y);visible.append(v);modes.append(meta['mode'])
            records.append(dict(metadata=meta,target=y.tolist(),visible=v.tolist(),l2=a.tolist(),
                                l2_refined=r.tolist(),l3=b.tolist(),refinement=trace))
        groups={k:grouped(p,target,visible,modes,base['evaluation_policy']) for k,p in
                [('l2',oldpred),('l2_refined',oldref),('l3',newpred)]}
        save(out/'holdout.json',dict(groups=groups,records=records,independent_matches=False))
        exported=export_checked(model,parity,out,args.require_onnx)
        original=[];inputs=[];parity_ok=True;old_times=[];new_times=[];states=Counter()
        for row in rows:
            frame=decode(args.image_root/row['image'],row['timestamp_ms']);x=frame.tensor[None]
            a=forward(old,x)[0];tic=time.perf_counter_ns();b=forward(model,x)[0];ms=(time.perf_counter_ns()-tic)/1e6
            # Refinement is a DIAGNOSTIC branch, not the delivered map.
            r0,t0,ms0=old_refine(frame.rgb,a,base)
            r1,t1,stat=refine_diagnostic(frame.rgb,a,base)
            equal=np.array_equal(r0,r1) and t0==t1;parity_ok=parity_ok and equal
            old_times.append(ms0);new_times.append(stat['ms'])
            ds=panel_decisions(b,base['evaluation_policy'],row['timestamp_ms']);states.update(z['panel']+':'+z['state'] for z in ds)
            original.append(dict(**row,l2=panel_decisions(a,base['evaluation_policy'],row['timestamp_ms']),l3=ds,
                    board=board_status(),decode_resize_ms=frame.decode_resize_ms,forward_ms=ms,
                    l2_edge_proposals_identical=equal,l2_full_refine_ms=ms0,lazy_refine=stat))
            inputs.append(frame.tensor)
        require(parity_ok,'strip optimization changed L2 proposals; stop')
        save(out/'original-frames.json',original)
        timing=benchmark(lambda x:forward(model,x),np.stack(inputs))
        summary=dict(policy=plan['id'],execution_complete=True,model_schema=MODEL_SCHEMA,**training,
            groups=groups,diagnostic_failures=failures(groups['l3']),natural_accuracy=None,
            canonical_native_render=True,same_pixels_compared=True,
            initialization='L2_weights_transfer_not_L2_predictions_as_labels',initial_coordinate_grid_changed=True,
            previous_local_trial_rejected=True,original_frames=40,original_panel_states=dict(states),
            preprocessing_contract_preserved=True,l2_weights_preserved=True,l2_edge_proposals_identical=parity_ok,
            full_refine_ms_p50=quantile(old_times,.5),lazy_refine_ms_p50=quantile(new_times,.5),
            full_refine_ms_p95=quantile(old_times,.95),lazy_refine_ms_p95=quantile(new_times,.95),
            edge_refinement_applied_to_maps=False,torch_resident=timing,export=exported,
            board_mapping_established=False,readers_modified=False,profile_promoted=False,game_state_updated=False,
            continuous_learning_connected=False,native_rust_connected=False,server_used=False,
            environment=dict(python=platform.python_version(),torch=torch.__version__,numpy=np.__version__))
        for p,d in sources.items():require(sha(Path(p))==d,'source changed: '+p)
        baseline(bp);save(out/'report.json',dict(summary=summary));seal_output(out)
        print('LITE3_SUMMARY='+json.dumps(summary),flush=True);return summary
    except BaseException as e:
        if not (out/'COMPLETE.json').exists():save(out/'FAILED.json',dict(error=str(e),execution_complete=False,profile_promoted=False))
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('image-root','manifest','plan','baseline','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--require-onnx',action='store_true');args=p.parse_args()
    def stop(*_):raise InterruptedError('L3 stopped; incomplete artifacts retained')
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:run(args)
    except Exception as e:p.exit(2,'LITE3_ERROR='+str(e)+'\n')

if __name__=='__main__':main()
