"""Bounded L2 train/validation/test. Immutable L1 weights evaluated on identical new test inputs."""
from __future__ import annotations
import argparse,copy,json,platform,resource,signal,time
from pathlib import Path
from collections import Counter
import numpy as np
from .common import (require,load,save,sha,contained,decisions,l1_to_corners,rect_corners,
                     POLICY,PANELS,quantile)
from .data import source_manifest,Compositor,input_path
from .evaluate import metrics,gate,benchmark
from .baseline import validate_baseline


def run(args):
    import torch
    from .model import UIMapSpatial,loss_function,save_weights,load_weights
    from legacy_l1.model import load_weights as load_l1
    from .refine import refine_panels
    from .export import export_checked
    from .viewer import write_viewer
    out=args.output.resolve();require(not out.exists(),'new run directory required')
    plan=load(args.plan);rows,sources=source_manifest(args.image_root,plan,args.manifest)
    base,baseinfo=validate_baseline(args.baseline)
    # Check identical original bytes against the L1 evidence despite an absolute-path relocation.
    old_sources=load(base/'sources.json')
    for r in rows:
        matching=[v for k,v in old_sources.items() if k.endswith('/'+r['image'])]
        require(matching and all(v==r['sha256'] for v in matching),'source differs from L1: '+r['image'])
    out.mkdir(parents=True,exist_ok=False)
    try:
        for p in [args.plan,args.manifest,base/'weights.npz',base/'COMPLETE.json']:
            sources[str(p.resolve())]=sha(p)
        for p in Path(__file__).parent.parent.rglob('*.py'):sources[str(p.resolve())]=sha(p)
        save(out/'sources.json',sources);save(out/'manifest.json',rows)
        save(out/'plan.json',dict(plan=plan,selection='validation_loss_only',test_used_for_selection=False,
            native_source_split_before_augmentation=True,auto_train_on_predictions=False,
            supervision='known transformations of seeded rectangles; not natural semantic ground truth'))
        save(out/'baseline.json',baseinfo)
        torch.set_num_threads(plan['thread_count']);torch.set_num_interop_threads(1)
        torch.manual_seed(plan['training_seed']);torch.use_deterministic_algorithms(True)
        model=UIMapSpatial();params=sum(x.numel() for x in model.parameters())
        require(params<=192778,'L2 must not exceed L1 parameter budget')
        save_weights(model,out/'initial-weights.npz')
        tr=Compositor(args.image_root,plan,'train');va=Compositor(args.image_root,plan,'validation')
        vd=tuple(torch.from_numpy(x) for x in va.batch(np.arange(plan['validation_samples'])+plan['validation_seed']*10000))
        def score():
            model.eval()
            with torch.inference_mode():
                a=[];b=[]
                for x in vd[0].split(12):
                    pred,maps=model.components(x);a.append(pred);b.append(maps)
                return float(loss_function(torch.cat(a),torch.cat(b),vd[1],vd[2]))
        initial=score();best=initial;beststep=0;state=copy.deepcopy(model.state_dict())
        optimizer=torch.optim.Adam(model.parameters(),lr=.0015)
        history=[];started=time.perf_counter()
        print('LITE2_MODEL='+json.dumps(dict(parameters=params,reference_L1_parameters=192778,
              output='four spatial heatmaps plus two visibility logits',pretrained_downloaded=False)),flush=True)
        with (out/'training.jsonl').open('x') as log:
            for step in range(plan['training_steps']):
                seeds=np.arange(plan['batch_size'])+step*plan['batch_size']+plan['training_seed']*10000
                data=tuple(torch.from_numpy(x) for x in tr.batch(seeds))
                model.train();optimizer.zero_grad(set_to_none=True)
                pred,maps=model.components(data[0]);loss=loss_function(pred,maps,data[1],data[2])
                require(torch.isfinite(loss).item(),'nonfinite loss')
                loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5.);optimizer.step()
                if (step+1)%100==0 or step+1==plan['training_steps']:
                    value=score();r=dict(step=step+1,train_loss=float(loss.detach()),validation_loss=value,
                                        elapsed_seconds=time.perf_counter()-started)
                    history.append(r);log.write(json.dumps(r)+'\n');log.flush();print('LITE2_TRAIN='+json.dumps(r),flush=True)
                    if value<best:best=value;state=copy.deepcopy(model.state_dict());beststep=step+1
        elapsed=time.perf_counter()-started
        model.load_state_dict(state);model.eval();save_weights(model,out/'weights.npz');model=load_weights(out/'weights.npz')
        l1=load_l1(base/'weights.npz')
        def infer(x):
            with torch.inference_mode():return model(torch.from_numpy(x)).numpy()
        def oldinfer(x):
            with torch.inference_mode():return l1_to_corners(l1(torch.from_numpy(x)).numpy())
        # Test is now accessed for the first time, after freezing the selected state.
        te=Compositor(args.image_root,plan,'test');tests=[];preds=[];oldpreds=[];refs=[];targets=[];vis=[];modes=[];inputs=[]
        print('LITE2_PHASE=paired_holdout_and_local_refinement',flush=True)
        for i in range(plan['test_samples']):
            x,y,v,meta,full=te.sample(plan['test_seed']*10000+i,full_resolution=True)
            p=infer(x[None])[0];old=oldinfer(x[None])[0];ref,trace,ms=refine_panels(np.asarray(full),p,plan)
            preds.append(p);oldpreds.append(old);refs.append(ref);targets.append(y);vis.append(v);modes.append(meta['mode']);inputs.append(x)
            tests.append(dict(index=i,metadata=meta,target=y.tolist(),visible=v.tolist(),l1=old.tolist(),
                              l2=p.tolist(),l2_refined=ref.tolist(),refinement=trace,refinement_ms=ms))
        arr={k:np.asarray(v) for k,v in [('l1',oldpreds),('l2',preds),('l2_refined',refs)]}
        target=np.asarray(targets);visible=np.asarray(vis);policy=plan['evaluation_policy']
        fixed=np.zeros_like(arr['l2']);fixed[:,:,4]=20
        for i,n in enumerate(PANELS):fixed[:,i,:4]=rect_corners(plan['panels'][n]['rect'])
        arr['fixed']=fixed
        paired={k:metrics(v,target,visible,policy) for k,v in arr.items()}
        per_mode={}
        for mode in sorted(set(modes)):
            ix=np.array([m==mode for m in modes]);per_mode[mode]={k:metrics(v[ix],target[ix],visible[ix],policy) for k,v in arr.items()}
        refinement_count=sum(t['applied'] for r in tests for t in r['refinement'])
        delta=abs(arr['l2_refined'][:,:,:4]-target)-abs(arr['l2'][:,:,:4]-target)
        changes=dict(applied=refinement_count,visible_panels_improved=int(((delta.mean(-1)<-1e-9)&(visible==1)).sum()),
                     visible_panels_worsened=int(((delta.mean(-1)>1e-9)&(visible==1)).sum()),
                     truth_used_only_after_decision_for_evaluation=True)
        save(out/'holdout.json',dict(records=tests,paired=paired,by_mode=per_mode,refinement=changes,
             independent_matches=False,all_comparisons_on_identical_generated_pixels=True))
        torch.set_num_threads(1)
        # Export equivalence uses validation examples, not new test-driven model selection.
        exported=export_checked(model,vd[0].numpy(),out,args.require_onnx)
        original=[];original_inputs=[];states=Counter()
        from PIL import Image
        with (out/'original-frames.jsonl').open('x') as f:
            for row in rows:
                path=contained(args.image_root,row['image']);tic=time.perf_counter_ns()
                with Image.open(path) as im:
                    full=np.asarray(im.convert('RGB')).copy();x=input_path(path)
                prep=(time.perf_counter_ns()-tic)/1e6;tic=time.perf_counter_ns();p=infer(x[None])[0]
                forward=(time.perf_counter_ns()-tic)/1e6
                ref,trace,ref_ms=refine_panels(full,p,plan);old=oldinfer(x[None])[0]
                pd=decisions(p,policy);states.update(n['panel']+':'+n['state'] for n in pd)
                record=dict(**row,l1=decisions(old,policy),l2=pd,refined=decisions(ref,policy),
                    refinement=trace,decode_resize_ms=prep,forward_ms=forward,refinement_ms=ref_ms,
                    ground_truth=None,game_state_updated=False)
                original.append(record);original_inputs.append(x);f.write(json.dumps(record)+'\n');f.flush()
        timing=benchmark(infer,np.stack(original_inputs))
        onnx_timing=None
        if exported['validated']:
            from .runtime import LiteRuntime
            engine=LiteRuntime(out/'candidate-model.onnx',exported['sha256'])
            onnx_timing=benchmark(engine.infer,np.stack(original_inputs))
        write_viewer(out/'viewer.html',original,args.image_root)
        for name,digest in sources.items():require(sha(Path(name))==digest,'input changed during run: '+name)
        validate_baseline(base)
        with np.load(out/'initial-weights.npz',allow_pickle=False) as initial_arrays:
            weight_change=sum(float(abs(p.detach().numpy()-initial_arrays[k]).sum()) for k,p in model.named_parameters())
        summary=dict(schema_version=2,policy=POLICY,execution_complete=True,parameters=params,
            L1_parameters=192778,npz_bytes=(out/'weights.npz').stat().st_size,model_trained=weight_change>0,
            parameter_l1_delta=weight_change,training_steps=plan['training_steps'],best_step=beststep,
            initial_validation_loss=initial,best_validation_loss=best,training_elapsed_seconds=elapsed,
            training_images=len(plan['train_images']),validation_seed_images=len(plan['validation_images']),
            test_seed_images=len(plan['test_images']),holdout_examples=plan['test_samples'],
            holdout_paired=paired,holdout_by_mode=per_mode,refinement=changes,
            diagnostic_geometry_gate_met=gate(paired['l2_refined'],policy),
            diagnostic_gate_note='Synthetic-only gate; passing cannot authorize readers or establish natural accuracy',
            original_frames=len(original),original_panel_states=dict(states),
            same_l1_weights_reused=True,baseline_weights_sha256=baseinfo['weights_sha256'],
            baseline_historical_metrics_directly_comparable=False,
            evaluation_runtime_decision_shared=True,source_split_independent_match=False,
            source_seed_coordinates_used=True,exact_real_accuracy=None,semantic_visibility_validated=False,
            current_readers_executed=False,ocr_executed=False,readers_modified=False,
            export=exported,torch_resident_inference=timing,onnx_resident_inference=onnx_timing,
            process_max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            rss_scope='whole trainer+evaluation; not runtime-only',
            environment=dict(python=platform.python_version(),torch=torch.__version__,numpy=np.__version__,
                training_threads=plan['thread_count'],benchmark_threads=1,machine=platform.machine()),
            sources_unchanged=True,profile_promoted=False,game_state_updated=False,native_rust_connected=False,
            continuous_learning_connected=False,online_weight_updates=False,server_used=False,
            geometry_refinement_implemented=True,manual_label_entry_required=False)
        save(out/'report.json',dict(summary=summary,history=history))
        with (out/'comparison.txt').open('x') as f:f.write('LITE2_SUMMARY='+json.dumps(summary,ensure_ascii=False)+'\n')
        save(out/'COMPLETE.json',{p.name:sha(p) for p in out.iterdir() if p.is_file()})
        print('LITE2_SUMMARY='+json.dumps(summary,ensure_ascii=False),flush=True)
        print('LITE2_REPORT='+str(out/'report.json'),flush=True);print('LITE2_COMPARISON='+str(out/'comparison.txt'),flush=True)
        return summary
    except BaseException as e:
        if not (out/'FAILED.json').exists():save(out/'FAILED.json',dict(execution_complete=False,error=str(e),profile_promoted=False))
        raise


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('image-root','manifest','plan','baseline','output'):ap.add_argument('--'+name,type=Path,required=True)
    ap.add_argument('--require-onnx',action='store_true');args=ap.parse_args()
    def stop(*_):raise InterruptedError('bounded L2 interrupted; artifacts retained')
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    try:run(args)
    except Exception as e:ap.exit(2,'LITE2_ERROR='+str(e)+'\n')
if __name__=='__main__':main()
