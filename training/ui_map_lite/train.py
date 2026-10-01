"""Finite local training; exported arrays only. Never trains/updates the active agent."""
from __future__ import annotations
import argparse
import importlib.metadata
import json
from pathlib import Path
import time
import numpy as np
import torch
from .core import ARCHITECTURE, require, sha, write_json, statistics
from .data import prepare, generate, fixed_boxes
from .model import UIMapLite


def verify_sources(sources):
    for path, digest in sources.items():
        require(sha(Path(path))==digest, 'source changed during experiment: '+path)


def train(prepared: dict, output: Path, steps=600, parent: Path|None=None):
    require(type(steps) is int and 1<=steps<=1200,'training step budget')
    require(not output.exists(),'training output exists; no overwrite')
    output.mkdir(parents=True)
    torch.set_num_threads(2)
    torch.manual_seed(20261001)
    torch.use_deterministic_algorithms(True)
    model=UIMapLite()
    parent_sha=None
    if parent is not None:
        require(parent.stat().st_size<2*1024**2,'excessive parent model')
        parent_sha=sha(parent);model.load_arrays(parent)
    initial={k:v.detach().clone() for k,v in model.state_dict().items()}
    plan=dict(architecture=ARCHITECTURE,steps=steps,batch_size=16,seed=20261001,
        training_generator_seed=41,validation_generator_seed=43,test_generator_seed=47,
        train_examples=512,validation_examples=96,test_examples=128,
        seeds=prepared['seeds'],regions=prepared['boxes'],source_frames=prepared.get('frames',[]),
        input_files_sha256=prepared.get('provenance',{}),parent_sha256=parent_sha,parent_is_folded_warm_start=True,optimizer_resumed=False,
        supervision='known_paste_geometry_of_weak_development_crops',
        geometry_source='existing versioned profiles; not per-frame semantic annotation',
        test_sources_used_for_training=False,independent_match_validation=False,
        auto_training_service=False,runtime_connected=False)
    write_json(output/'plan.json',plan)
    x,y=generate(prepared,'train',512,41)
    xv,yv=generate(prepared,'validation',96,43)
    xt,yt=generate(prepared,'test',128,47)
    xx=torch.from_numpy(x);yy=torch.from_numpy(y)
    optimizer=torch.optim.Adam(model.parameters(),lr=.002)
    rng=np.random.default_rng(20261001)
    losses=[];started=time.perf_counter()
    with (output/'training.jsonl').open('x') as log:
        for step in range(steps):
            indices=rng.integers(0,len(xx),16)
            model.train();optimizer.zero_grad(set_to_none=True)
            prediction=model(xx[indices]).reshape(-1,2,5)
            target=yy[indices].reshape(-1,2,5)
            visible=target[:,:,4]
            coord=((prediction[:,:,:4]-target[:,:,:4]).square().mean(-1)*visible).sum()/visible.sum().clamp_min(1)
            visibility=torch.nn.functional.binary_cross_entropy(prediction[:,:,4],visible)
            loss=40*coord+visibility
            require(bool(torch.isfinite(loss)),'nonfinite training loss')
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);optimizer.step()
            losses.append(float(loss.detach()))
            if step%50==0 or step==steps-1:
                row=dict(step=step+1,loss=losses[-1],coordinate_loss=float(coord.detach()),
                         visibility_loss=float(visibility.detach()))
                log.write(json.dumps(row)+'\n');log.flush()
                print('UIMAP1_TRAIN='+json.dumps(row),flush=True)
    elapsed=time.perf_counter()-started
    changed=sum(not torch.equal(v,initial[k]) for k,v in model.named_parameters())
    require(changed>0,'training did not change any parameter tensor')
    model.eval()
    def predict(a):
        with torch.inference_mode():
            return np.concatenate([model(torch.from_numpy(b)).numpy() for b in np.array_split(a,8)])
    pv,pt=predict(xv),predict(xt)
    report=dict(architecture=ARCHITECTURE,model_trained=True,optimizer_steps=steps,
        parameter_count=sum(p.numel() for p in model.parameters()),changed_parameter_tensors=changed,
        training_seconds=elapsed,first_50_loss_mean=float(np.mean(losses[:50])),
        last_50_loss_mean=float(np.mean(losses[-50:])),parent_sha256=parent_sha,
        validation=statistics(pv,yv,fixed_boxes(prepared['boxes'])),
        test=statistics(pt,yt,fixed_boxes(prepared['boxes'])),
        versions={k:importlib.metadata.version(k) for k in ('torch','numpy','Pillow')},
        semantic_tft_accuracy=None,profile_promoted=False,game_state_updated=False,
        model_selection='final fixed step; no selection on held-out scores')
    model.export_arrays(output/'model.npz')
    # Parity inputs/outputs: real calculations, read by the inference-only process.
    with (output/'parity.npz').open('xb') as f:
        np.savez(f,inputs=xt[:8],outputs=pt[:8])
    write_json(output/'training-report.json',report)
    verify_sources(prepared.get('provenance',{}))
    if parent is not None:
        require(sha(parent)==parent_sha,'parent checkpoint changed')
    write_json(output/'TRAINED.json',{name:sha(output/name) for name in
               ('plan.json','training-report.json','model.npz','parity.npz','training.jsonl')})
    print('UIMAP1_TRAINED='+json.dumps(dict(parameters=report['parameter_count'],
        steps=steps,weights_bytes=(output/'model.npz').stat().st_size,seconds=elapsed)),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('project','spec','image-root','manifest','output'):
        p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--parent',type=Path)
    a=p.parse_args()
    try:
        prepared=prepare(a.project.resolve(),a.spec.resolve(),a.image_root.resolve(),a.manifest.resolve())
        # Hash all U1 sources; this is provenance, not a semantic code audit.
        for source in Path(__file__).parent.glob('*.py'):
            prepared['provenance'][str(source.resolve())]=sha(source)
        print('UIMAP1_PREFLIGHT_OK=true',flush=True)
        train(prepared,a.output,parent=a.parent)
    except (ValueError,OSError,KeyError,TypeError,RuntimeError) as e:
        if a.output.is_dir() and not (a.output/'TRAINED.json').exists():
            failure=a.output/'FAILED.json'
            if not failure.exists():write_json(failure,dict(error=str(e),execution_complete=False))
        p.exit(2,'UIMAP1_TRAIN_ERROR='+str(e)+'\n')


if __name__=='__main__':
    main()
