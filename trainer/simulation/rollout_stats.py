"""JIT aggregation of already-generated rollout rewards; no TFT rules here."""
from __future__ import annotations

import numpy as np

try:
    from numba import njit
except ImportError:  # The lightweight API container does not need Numba.
    njit = None


def _validate(rewards: np.ndarray, discount: float) -> np.ndarray:
    values = np.asarray(rewards, dtype=np.float64)
    if values.ndim != 3 or not all(values.shape):
        raise ValueError("expected nonempty [actions, paths, steps] rewards")
    if not np.isfinite(values).all() or not 0.0 <= discount <= 1.0:
        raise ValueError("rewards and discount must be finite")
    return np.ascontiguousarray(values)


def _aggregate(rewards: np.ndarray, discount: float) -> np.ndarray:
    actions, paths, steps = rewards.shape
    result = np.empty((actions, 3), dtype=np.float64)
    for action in range(actions):
        total = 0.0
        squared = 0.0
        negative = 0
        for path in range(paths):
            score = 0.0
            weight = 1.0
            for step in range(steps):
                score += rewards[action, path, step] * weight
                weight *= discount
            total += score
            squared += score * score
            if score < 0.0:
                negative += 1
        mean = total / paths
        result[action, 0] = mean
        result[action, 1] = max(0.0, squared / paths - mean * mean) ** 0.5
        result[action, 2] = negative / paths
    return result


_aggregate_jit = njit(cache=True, nogil=True)(_aggregate) if njit is not None else None


def rollout_stats(rewards: np.ndarray, *, discount: float = 1.0, use_jit: bool = True) -> np.ndarray:
    """Return [mean, population stddev, fraction of negative returns] per action.

    Reward generation, legal actions, TFT combat and MCTS policy remain outside
    this kernel. Keep the Python path for exact parity checks and diagnostics.
    """
    values = _validate(rewards, discount)
    kernel = _aggregate_jit if use_jit and _aggregate_jit is not None else _aggregate
    return kernel(values, discount)


if __name__ == "__main__":
    import json
    from time import perf_counter

    rng = np.random.default_rng(20261004)
    synthetic = rng.normal(size=(5, 100, 12))  # 500 synthetic paths, not TFT matches.
    first = perf_counter()
    fast = rollout_stats(synthetic, discount=0.97)
    compile_ms = (perf_counter() - first) * 1000
    slow = rollout_stats(synthetic, discount=0.97, use_jit=False)
    assert np.allclose(fast, slow, rtol=1e-12, atol=1e-12)
    samples = 1000
    first = perf_counter()
    for _ in range(samples):
        rollout_stats(synthetic, discount=0.97, use_jit=False)
    python_ms = (perf_counter() - first) * 1000 / samples
    first = perf_counter()
    for _ in range(samples):
        rollout_stats(synthetic, discount=0.97)
    jit_ms = (perf_counter() - first) * 1000 / samples
    print(json.dumps({"paths": 500, "steps": 12, "jit_available": _aggregate_jit is not None,
                      "first_call_ms": round(compile_ms, 3),
                      "python_ms_per_call": round(python_ms, 4),
                      "jit_ms_per_call": round(jit_ms, 4),
                      "speedup": round(python_ms / jit_ms, 2),
                      "max_abs_error": float(np.max(np.abs(fast - slow))),
                      "game_rules_implemented": False}))
