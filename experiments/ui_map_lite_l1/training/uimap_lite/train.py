"""Train -> select on validation -> one holdout evaluation -> export -> diagnostic original frames."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import platform
import resource
import signal
import time
from collections import Counter
import numpy as np
from .common import load, save, sha, contained, require, proposals, VERSION
from .data import Compositor, source_manifest, input_image
from .evaluate import evaluate_arrays, fixed_predictions, benchmark


def run(args):
    import torch
    from .model import UIMapLite, loss_function, save_weights, load_weights
    from .export import export_checked
    from .viewer import write_viewer
    started=time.perf_counter()
    out=args.output.resolve()
    require(not out.exists(),'new run directory required; no overwrite')
    out.mkdir(parents=True,exist_ok=False)
    try:
        plan=load(args.plan)
        require(type(args.steps) is int and 1<=args.steps<=1800,'training step budget')
        records,sources=source_manifest(args.image_root,plan,args.manifest)
        sources[str(args.plan.resolve())]=sha(args.plan)
        sources[str(args.manifest.resolve())]=sha(args.manifest)
        for p in Path(__file__).parent.glob('*.py'):sources[str(p.resolve())]=sha(p)
        save(out/'sources.json',sources)
        save(out/'plan.json',dict(plan=plan,effective_steps=args.steps,source_split_before_augmentation=True,
            early_stop_selection='validation_only',test_used_for_selection=False,
            training_labels='known synthetic insertion/occlusion of seed crops',
            original_scene_annotations_used=False,auto_train_on_predictions=False))
        torch.set_num_threads(plan['thread_count'])
        torch.set_num_interop_threads(1)
        torch.manual_seed(plan['training_seed'])
        torch.use_deterministic_algorithms(True)
        model=UIMapLite()
        params=sum(p.numel() for p in model.parameters())
        require(params<=500000,'model size budget exceeded')
        save_weights(model,out/'initial-weights.npz')
        train=Compositor(args.image_root,plan,'train')
        val=Compositor(args.image_root,plan,'validation')
        test=Compositor(args.image_root,plan,'test')
        val_data=val.batch(np.arange(plan['validation_samples'])+plan['validation_seed']*10000)
        val_tensors=tuple(torch.from_numpy(x) for x in val_data)
        def score():
            model.eval()
            with torch.inference_mode():
                outputs=torch.cat([model(x) for x in val_tensors[0].split(16)])
                return float(loss_function(outputs,val_tensors[1],val_tensors[2]))
        initial=score()
        optimizer=torch.optim.Adam(model.parameters(),lr=.0015)
        best_score=float('inf');best_state=None;best_step=None;history=[]
        print('LITE1_MODEL='+json.dumps(dict(parameters=params,weight_bytes_fp32=params*4,
            pretrained_downloaded=False,train_images=len(plan['train_images']))),flush=True)
        with (out/'training.jsonl').open('x') as log:
            for step in range(args.steps):
                # No test rows or raw predicted labels participate in optimization.
                seeds=np.arange(plan['batch_size'])+step*plan['batch_size']+plan['training_seed']*10000
                data=tuple(torch.from_numpy(x) for x in train.batch(seeds))
                model.train();optimizer.zero_grad(set_to_none=True)
                loss=loss_function(model(data[0]),data[1],data[2])
                require(torch.isfinite(loss).item(),'nonfinite training loss')
                loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5.)
                optimizer.step()
                if (step+1)%100==0 or step+1==args.steps:
                    value=score()
                    record=dict(step=step+1,train_loss=float(loss.detach()),validation_loss=value,
                                elapsed_seconds=time.perf_counter()-started)
                    history.append(record);log.write(json.dumps(record)+'\n');log.flush()
                    print('LITE1_TRAIN='+json.dumps(record),flush=True)
                    if value<best_score:
                        best_score=value;best_state=copy.deepcopy(model.state_dict());best_step=step+1
        model.load_state_dict(best_state);model.eval()
        save_weights(model,out/'weights.npz')
        reloaded=load_weights(out/'weights.npz')
        # Testing is executed once after the chosen state is frozen.
        test_data=test.batch(np.arange(plan['test_samples'])+plan['test_seed']*10000)
        def infer(x):
            with torch.inference_mode():return reloaded(torch.from_numpy(x)).numpy()
        predictions=np.concatenate([infer(x) for x in np.array_split(test_data[0],12)])
        metrics=evaluate_arrays(predictions,test_data[1],test_data[2])
        fixed=evaluate_arrays(fixed_predictions(plan,len(predictions)),test_data[1],test_data[2])
        save(out/'holdout.json',dict(network=metrics,fixed_coordinates=fixed,
            scope='generated placements on held-out crop content from same match',
            known_synthetic_geometry=True,natural_patch_generalization_established=False))
        export=export_checked(reloaded,test_data[0],out,args.require_onnx)
        # Comparisons include outputs and hard failures, not just convenient counts.
        with torch.inference_mode():
            before=model(val_tensors[0][:1]).numpy()
        require(np.allclose(before,infer(val_data[0][:1]),rtol=0,atol=1e-7),'saved weights do not replay')
        torch.set_num_threads(1)
        timing=benchmark(infer,test_data[0][:10])
        onnx_timing=None
        if export['validated']:
            from .runtime import LiteRuntime
            onnx_timing=benchmark(LiteRuntime(out/'candidate-model.onnx',export['sha256']).infer,test_data[0][:10])
        original=[];states=Counter();decode_times=[];infer_times=[]
        seed_set=set(plan['train_images']+plan['validation_images']+plan['test_images'])
        with (out/'original-frames.jsonl').open('x') as f:
            for row in records:
                start=time.perf_counter_ns()
                image=input_image(contained(args.image_root,row['image']))
                decoded=(time.perf_counter_ns()-start)/1e6
                start=time.perf_counter_ns();raw=infer(image[None])[0]
                elapsed=(time.perf_counter_ns()-start)/1e6
                panels=proposals(raw)
                states.update(x['panel']+':'+x['state'] for x in panels)
                record=dict(**row,panels=panels,used_as_seed=row['image'] in seed_set,
                            raw_output=raw.tolist(),decode_resize_ms=decoded,inference_ms=elapsed,
                            semantic_ground_truth=None,game_state_updated=False)
                original.append(record);f.write(json.dumps(record,allow_nan=False)+'\n');f.flush()
                decode_times.append(decoded);infer_times.append(elapsed)
        write_viewer(out/'viewer.html',args.image_root,original)
        for name,digest in sources.items():require(sha(Path(name))==digest,'source changed during run: '+name)
        with np.load(out/'initial-weights.npz',allow_pickle=False) as initial_weights:
            parameter_l1_delta = sum(float(np.abs(p.detach().numpy()-initial_weights[k]).sum())
                for k,p in model.named_parameters())
        changed=parameter_l1_delta>1e-9
        summary=dict(schema_version=1,policy=VERSION,execution_complete=True,parameters=params,
            raw_weights_fp32_bytes=params*4,npz_bytes=(out/'weights.npz').stat().st_size,
            model_trained=changed,parameter_l1_delta=parameter_l1_delta,training_steps=args.steps,best_step=best_step,
            initial_validation_loss=initial,best_validation_loss=best_score,
            training_images=len(plan['train_images']),validation_seed_images=len(plan['validation_images']),
            test_seed_images=len(plan['test_images']),holdout_examples=len(predictions),
            original_frames=len(original),original_panel_states=dict(states),
            training_elapsed_seconds=history[-1]['elapsed_seconds'],
            diagnostic_geometry_gate_met=all(m['coordinate_mae_px']<=20 and
                m['coordinate_error_p95_px']<=40 and m['accepted_hidden']==0 for m in metrics.values()),
            diagnostic_gate_note='Not permission to promote even if passed: synthetic only, no natural UI labels',
            holdout_network=metrics,holdout_fixed_coordinates=fixed,
            torch_resident_inference=timing,onnx_resident_inference=onnx_timing,
            original_decode_resize_ms_p50=float(np.median(decode_times)),
            original_inference_ms_p50=float(np.median(infer_times)),export=export,
            process_max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            rss_scope='whole training/evaluation process, not deployment-only memory',
            environment=dict(python=platform.python_version(),torch=torch.__version__,
                numpy=np.__version__,processor=platform.processor(),machine=platform.machine(),
                training_threads=plan['thread_count'],benchmark_threads=1),
            sources_unchanged=True,exact_real_accuracy=None,semantic_visibility_validated=False,
            source_split_independent_match=False,source_seed_coordinates_used=True,
            manual_label_entry_required=False,profile_promoted=False,game_state_updated=False,
            geometry_refinement_implemented=False,native_rust_connected=False,
            continuous_learning_connected=False,online_weight_updates=False,
            current_readers_executed=False,ocr_executed=False,server_used=False,
            note='Coarse panel proposals only. Synthetic metrics are conditional on seeded rectangles and cannot prove naturally changed UI correctness. Existing readers unchanged.')
        save(out/'report.json',dict(summary=summary,training_history=history))
        with (out/'comparison.txt').open('x') as f:f.write('LITE1_SUMMARY='+json.dumps(summary,ensure_ascii=False)+'\n')
        save(out/'COMPLETE.json',{p.name:sha(p) for p in out.iterdir() if p.is_file()})
        print('LITE1_SUMMARY='+json.dumps(summary,ensure_ascii=False),flush=True)
        print('LITE1_REPORT='+str(out/'report.json'),flush=True)
        print('LITE1_COMPARISON='+str(out/'comparison.txt'),flush=True)
        return summary
    except BaseException as error:
        if not (out/'FAILED.json').exists():save(out/'FAILED.json',dict(execution_complete=False,error=str(error),profile_promoted=False))
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image-root',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--steps',type=int,default=600)
    parser.add_argument('--require-onnx',action='store_true')
    args=parser.parse_args()
    def stop(signum,frame):raise InterruptedError('bounded run interrupted; artifacts retained')
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:run(args)
    except Exception as error:parser.exit(2,'LITE1_ERROR='+str(error)+'\n')

if __name__=='__main__':main()
