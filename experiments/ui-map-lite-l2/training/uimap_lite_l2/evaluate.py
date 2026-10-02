"""One decision function for both metrics and runtime; no visibility-only acceptance."""
from __future__ import annotations
import hashlib
import time
import numpy as np
from .common import PANELS,decisions,quantile,require


def metrics(predicted,target,visible,policy):
    predicted=np.asarray(predicted);target=np.asarray(target);visible=np.asarray(visible)
    require(predicted.shape==(len(target),2,5) and target.shape==(len(target),2,4)
            and visible.shape==(len(target),2),'metric shape')
    require(len(target)>0 and np.isfinite(predicted).all() and np.isfinite(target).all()
            and np.isin(visible,[0,1]).all(),'invalid evaluation arrays')
    ds=[decisions(p,policy) for p in predicted]
    error=abs(predicted[:,:,:4]-target)*[1920,1080,1920,1080]
    result={}
    for i,name in enumerate(PANELS):
        vis=visible[:,i].astype(bool)
        above=np.array([r[i]['visibility_above_threshold'] for r in ds]);valid=np.array([r[i]['geometry_valid'] for r in ds])
        accept=np.array([r[i]['accepted_as_coarse'] for r in ds])
        e=error[vis,i].flatten();ae=error[vis&accept,i].flatten()
        result[name]=dict(visible_examples=int(vis.sum()),hidden_examples=int((~vis).sum()),
            visibility_pass_visible=int((above&vis).sum()),visibility_pass_hidden=int((above&~vis).sum()),
            geometry_invalid=int((~valid).sum()),accepted_visible=int((accept&vis).sum()),
            accepted_hidden=int((accept&~vis).sum()),accepted_visible_fraction=float((accept&vis).sum()/max(1,vis.sum())),
            coordinate_mae_px=float(e.mean()) if len(e) else None,coordinate_error_p95_px=quantile(e,.95),
            accepted_coordinate_mae_px=float(ae.mean()) if len(ae) else None,
            accepted_coordinate_error_p95_px=quantile(ae,.95),
            within_20px_all_corners=int((vis&(error[:,i].max(-1)<=20)).sum()),
            note='Generated geometry conditional on source seeds. Accepted = visibility AND geometry, not production approval.')
    return result


def gate(m,p):
    return all(v['coordinate_mae_px'] is not None and v['coordinate_mae_px']<=p['max_coordinate_error_px']
        and v['coordinate_error_p95_px']<=p['max_p95_coordinate_error_px']
        and v['accepted_hidden']<=p['maximum_hidden_accepted']
        and v['accepted_visible_fraction']>=p['minimum_visible_acceptance_fraction'] for v in m.values())


def benchmark(infer,examples,warmup=30,repeats=120):
    examples=np.asarray(examples,dtype=np.float32)
    require(len(examples)>1 and repeats>=len(examples),'multiple-frame benchmark required')
    ids=[hashlib.sha256(x.tobytes()).hexdigest() for x in examples]
    require(len(set(ids))>1,'benchmark needs visually distinct prepared frames')
    for i in range(warmup):infer(examples[i%len(examples)][None])
    times=[]
    for i in range(repeats):
        start=time.perf_counter_ns();infer(examples[i%len(examples)][None]);times.append((time.perf_counter_ns()-start)/1e6)
    return dict(warmup=warmup,repetitions=repeats,batch=1,source_frames=len(examples),distinct_prepared_tensors=len(set(ids)),
        p50_ms=quantile(times,.5),p95_ms=quantile(times,.95),min_ms=min(times),max_ms=max(times),
        target_10ms_p95_met=quantile(times,.95)<=10,
        measured_scope='resident forward only across multiple prepared frames; excludes decode, resize, decision, refinement')
