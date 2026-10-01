"""Fresh inference-only process: export, parity, generated test, real replay and latency."""
from __future__ import annotations
import argparse
from collections import Counter
import importlib.metadata
import json
from pathlib import Path
import resource
import sys
import time
import numpy as np
from .core import require,sha,load_json,write_json,decoded,percentile,statistics
from .data import prepare,generate,fixed_boxes,image_tensor
from .export import export
from .viewer import write_viewer
from .memory import snapshot


def evaluate(prepared, train_dir: Path, output: Path):
    require('torch' not in sys.modules,'inference process must not import the trainer')
    require(1<=len(prepared['frames'])<=128,'missing/excessive replay frames')
    seal=load_json(train_dir/'TRAINED.json')
    require(set(seal)=={'plan.json','training-report.json','model.npz','parity.npz','training.jsonl'},'invalid training seal')
    for n,digest in seal.items():require(sha(train_dir/n)==digest,'training artifact changed: '+n)
    plan=load_json(train_dir/'plan.json')
    require(plan['seeds']==prepared['seeds'] and plan['regions']==prepared['boxes'],'dataset/geometry changed')
    for path,digest in plan['input_files_sha256'].items():
        require(sha(Path(path))==digest,'training source changed')
    require(not output.exists(),'evaluation output exists')
    output.mkdir(parents=True)
    info=export(train_dir/'model.npz',output/'model.onnx')
    import onnxruntime as ort
    so=ort.SessionOptions();so.intra_op_num_threads=1;so.inter_op_num_threads=1
    so.add_session_config_entry('session.intra_op.allow_spinning','0')
    so.add_session_config_entry('session.inter_op.allow_spinning','0')
    so.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
    so.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    start=time.perf_counter();session=ort.InferenceSession(str(output/'model.onnx'),so,providers=['CPUExecutionProvider'])
    load_ms=(time.perf_counter()-start)*1000
    def infer(x):return session.run(['regions'],{'image':x.astype(np.float32,copy=False)})[0]
    require((train_dir/'parity.npz').stat().st_size<16*1024**2,'parity file budget')
    with np.load(train_dir/'parity.npz',allow_pickle=False) as f:
        inputs,expected=f['inputs'],f['outputs']
    require(inputs.shape==(8,3,192,320) and expected.shape==(8,10),'parity shape mismatch')
    actual=np.concatenate([infer(x[None]) for x in inputs]);difference=float(np.max(np.abs(actual-expected)))
    require(difference<=2e-5,'ONNX/torch parity failed')
    ready_memory = snapshot()
    xt,yt=generate(prepared,'test',128,47)
    pt=np.concatenate([infer(x[None]) for x in xt])
    generated=statistics(pt,yt,fixed_boxes(prepared['boxes']))
    timings=[]
    for x in inputs:infer(x[None])
    # 200 warmed batch-one passes, tensor in memory. Decode is timed separately below.
    for i in range(200):
        start=time.perf_counter();infer(xt[i%len(xt)][None]);timings.append((time.perf_counter()-start)*1000)
    records=[];counts=Counter();source_times=[];pass_times=[]
    image_root=Path(prepared['image_root'])
    for row in prepared['frames']:
        start=time.perf_counter();x=image_tensor(image_root/row['image']);decode_ms=(time.perf_counter()-start)*1000
        start=time.perf_counter();pred=infer(x)[0];ms=(time.perf_counter()-start)*1000
        regions=decoded(pred);counts.update(r['panel']+':'+r['status'] for r in regions)
        record=dict(row,regions=regions,neural_ms=ms,decode_and_resize_ms=decode_ms,
                    total_ms=ms+decode_ms,semantic_reference=None,
                    source_role=next((s['split'] for s in prepared['seeds'] if s['image']==row['image']),'observation_only'))
        records.append(record);source_times.append(decode_ms);pass_times.append(ms)
    train_report=load_json(train_dir/'training-report.json')
    summary=dict(schema_version=1,policy='uimap_lite_u1_generated_training_real_shadow',
        frames=len(records),parameters=info['parameters'],model_bytes=info['model_bytes'],
        operators=info['operators'],training_steps=train_report['optimizer_steps'],model_trained=True,
        training_parameters=train_report['parameter_count'],batchnorm_folded=True,
        training_seconds=train_report['training_seconds'],parity_max_absolute_error=difference,
        generated_test=generated,real_proposals=dict(counts),
        warmed_inference_ms_p50=percentile(timings,.5),warmed_inference_ms_p95=percentile(timings,.95),
        real_inference_ms_p50=percentile(pass_times,.5),real_inference_ms_p95=percentile(pass_times,.95),
        decode_resize_ms_p50=percentile(source_times,.5),model_load_ms=load_ms,
        inference_process_max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        inference_imported_torch='torch' in sys.modules,inference_threads=1,
        target_inference_p95_ms=10,target_met=percentile(timings,.95)<=10,
        independent_match_accuracy=None,ocr_executed=False,grounding_dino_executed=False,
        b1_modified=False,s4_modified=False,profile_promoted=False,game_state_updated=False,
        runtime_connected=False,continuous_training_service=False,live_capture_connected=False,
        precise_ocr_crop_refinement=False,semantic_visibility_calibrated=False,
        candidate_status='shadow_only_no_automatic_activation',
        note='Coarse region model, not units/HP or 3D. Generated crop geometry is known; TFT semantics are unverified. Fixed-coordinate baseline is not B1/S4 recognition.',
        versions={k:importlib.metadata.version(k) for k in ('onnxruntime','onnx','numpy','Pillow')})
    write_viewer(output/'viewer.html',records,image_root,prepared['boxes'])
    summary['memory_after_model_parity'] = ready_memory
    summary['memory_after_evaluation_and_viewer'] = snapshot()
    summary['rusage_peak_note'] = 'Legacy max_rss field is raw getrusage, may retain a pre-exec peak; use current-image telemetry, not weight size, for process memory.'
    report=dict(summary=summary,records=records,provenance=plan,
                training_report_sha256=sha(train_dir/'training-report.json'))
    write_json(output/'report.json',report)
    text='UIMAP1_SUMMARY='+json.dumps(summary,ensure_ascii=False)+'\n'
    (output/'comparison.txt').write_text(text,encoding='utf-8')
    for path,digest in plan['input_files_sha256'].items():require(sha(Path(path))==digest,'source changed')
    write_json(output/'COMPLETE.json',{n:sha(output/n) for n in ('report.json','comparison.txt','model.onnx','viewer.html')})
    print(text,flush=True)
    print('UIMAP1_REPORT='+str(output/'report.json'),flush=True)
    print('UIMAP1_COMPARISON='+str(output/'comparison.txt'),flush=True)
    print('UIMAP1_VIEWER='+str(output/'viewer.html'),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('project','spec','image-root','manifest','train','output'):
        p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args()
    try:
        prepared=prepare(a.project.resolve(),a.spec.resolve(),a.image_root.resolve(),a.manifest.resolve())
        prepared['image_root']=str(a.image_root.resolve())
        evaluate(prepared,a.train,a.output)
    except (ValueError,OSError,KeyError,TypeError,RuntimeError) as e:
        if a.output.is_dir() and not (a.output/'COMPLETE.json').exists():
            f=a.output/'FAILED.json'
            if not f.exists():write_json(f,dict(error=str(e),execution_complete=False))
        p.exit(2,'UIMAP1_ERROR='+str(e)+'\n')


if __name__=='__main__':main()
