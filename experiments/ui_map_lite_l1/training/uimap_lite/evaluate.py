"""Metrics distinguish generated geometry, natural images, and inference-only timing."""
from __future__ import annotations
import time
import numpy as np
from .common import PANELS, corners, percentile, box_from_rect


def evaluate_arrays(predictions, target, visible):
    size = np.asarray([1920,1080,1920,1080], dtype=np.float32)
    error = np.abs(corners(predictions[:,:,:4])-corners(target))*size
    accepted = predictions[:,:,4] >= 2.1972245773362196
    results = {}
    for i, name in enumerate(PANELS):
        mask = visible[:,i].astype(bool)
        errors = error[mask,i].reshape(-1)
        accepted_errors = error[mask & accepted[:,i],i].reshape(-1)
        results[name] = dict(visible_examples=int(mask.sum()), hidden_examples=int((~mask).sum()),
            coordinate_mae_px=float(errors.mean()) if len(errors) else None,
            coordinate_error_p95_px=percentile(errors,.95),
            accepted_visible=int((mask & accepted[:,i]).sum()),
            accepted_hidden=int((~mask & accepted[:,i]).sum()),
            accepted_coordinate_mae_px=float(accepted_errors.mean()) if len(accepted_errors) else None,
            note='Synthetic seed-conditioned geometry, not real-match accuracy')
    return results


def fixed_predictions(plan, n):
    result = np.zeros((n,2,5),dtype=np.float32)
    for i,panel in enumerate(PANELS):
        result[:,i,:4] = box_from_rect(plan['panels'][panel]['rect'])
        result[:,i,4] = 20  # No adaptive visibility in the fixed-coordinate comparator.
    return result


def benchmark(infer, examples, warmup=30, repeats=120):
    for i in range(warmup):
        infer(examples[i % len(examples)][None])
    samples=[]
    for i in range(repeats):
        start=time.perf_counter_ns()
        infer(examples[i % len(examples)][None])
        samples.append((time.perf_counter_ns()-start)/1e6)
    return dict(warmup=warmup, batch=1, repetitions=repeats,
        p50_ms=percentile(samples,.5), p95_ms=percentile(samples,.95),
        min_ms=min(samples), max_ms=max(samples),
        measured_scope='resident inference call only, no capture/decode/resize/training',
        target_10ms_p95_met=percentile(samples,.95)<=10)
