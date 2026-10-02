"""Correlated traces, exclusive output directory, async disk writes, explicit loss."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
import copy, hashlib, json, math, os, queue, shutil, threading, time


def quantiles(values):
    v = sorted(float(x) for x in values if x is not None and math.isfinite(float(x)))
    if not v:
        return {'n': 0, 'p50_ms': None, 'p95_ms': None, 'p99_ms': None}
    def q(p):
        x = (len(v) - 1) * p
        i = int(x)
        return v[i] + (v[min(i + 1, len(v) - 1)] - v[i]) * (x - i)
    return dict(n=len(v), p50_ms=q(.5), p95_ms=q(.95), p99_ms=q(.99), max_ms=v[-1])


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024**2), b''):
            h.update(b)
    return h.hexdigest()


class Journal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=False)
        if shutil.disk_usage(self.path).free < 128 * 1024**2:
            raise OSError('Ao menos 128 MiB livres no destino; não apagar sessões antigas.')
        self.q = queue.Queue(maxsize=2048)
        self.error = None
        self.dropped = 0
        self.write_ns = 0
        self.enqueue_ns = 0
        self.closed = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def emit(self, event):
        start = time.perf_counter_ns()
        if self.closed:
            return
        if self.error:
            raise OSError(self.error)
        try:
            self.q.put_nowait(copy.deepcopy(event))
        except queue.Full:
            self.dropped += 1
            self.error = 'telemetry queue overflow; run cannot be complete'
            raise OSError(self.error)
        finally:
            self.enqueue_ns += time.perf_counter_ns() - start

    def _run(self):
        try:
            with (self.path / 'trace.jsonl').open('x', encoding='utf-8') as f:
                since = 0
                while True:
                    value = self.q.get()
                    if value is None:
                        break
                    t = time.perf_counter_ns()
                    f.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + '\n')
                    since += 1
                    if since >= 30:
                        f.flush()
                        since = 0
                        if shutil.disk_usage(self.path).free < 32 * 1024**2:
                            raise OSError('disco abaixo da reserva: captura encerrada')
                    self.write_ns += time.perf_counter_ns() - t
                f.flush()
                os.fsync(f.fileno())
        except Exception as exc:
            self.error = str(exc)

    def close(self, summary):
        self.closed = True
        try:
            self.q.put(None, timeout=5)
        except queue.Full:
            self.error = self.error or 'telemetry close queue timeout'
        self.thread.join(10)
        if self.thread.is_alive():
            self.error = 'telemetry writer did not stop'
        summary.update(telemetry=dict(dropped=self.dropped, error=self.error,
                                     enqueue_ms=self.enqueue_ns / 1e6, write_ms=self.write_ns / 1e6))
        summary['execution_complete'] = summary['execution_complete'] and not self.error
        for name, content in [('summary.json', json.dumps(summary, ensure_ascii=False, indent=2)),
                              ('comparison.txt', 'E1_SUMMARY=' + json.dumps(summary, ensure_ascii=False))]:
            with (self.path / name).open('x', encoding='utf-8') as f:
                f.write(content + '\n')
        seal = {p.name: digest(p) for p in self.path.iterdir() if p.is_file()}
        name = 'COMPLETE.json' if summary['execution_complete'] else 'PARTIAL.json'
        with (self.path / name).open('x', encoding='utf-8') as f:
            json.dump(seal, f, indent=2)
        return summary
