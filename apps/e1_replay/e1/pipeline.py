"""Bounded independent producer, one resident consumer, correlated UI acknowledgments."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import json, queue, threading, time, uuid
from .source import VideoSource, fixture_frames
from .protocol import NativeWorker
from .metrics import Journal, quantiles, digest


class Latest:
    def __init__(self):
        self.q = queue.Queue(maxsize=1)
    def put(self, x):
        old = None
        try:
            old = self.q.get_nowait()
        except queue.Empty:
            pass
        self.q.put_nowait(x)
        return old
    def get(self, timeout=.1):
        return self.q.get(timeout=timeout)
    def empty(self):
        return self.q.empty()


@dataclass(frozen=True)
class Options:
    worker: str
    configs: str
    output: str
    mode: str = 'fixtures'
    video: str | None = None
    tesseract: str = 'tesseract'
    ffmpeg: str = 'ffmpeg'
    ffprobe: str = 'ffprobe'
    controls: str | None = None
    board_reference: str | None = None
    model: str | None = None
    seconds: float = 30
    reader_hz: float = 2
    max_age_ms: float = 2000
    injected_wait_ms: float = 0

    def validate(self):
        if self.mode not in ('fixtures', 'replay'):
            raise ValueError('E1 suporta somente replay local encerrado ou fixtures.')
        if self.mode == 'replay' and not self.video:
            raise ValueError('Selecione o vídeo encerrado.')
        for value, low, high in [(self.seconds, 1, 600), (self.reader_hz, .2, 30),
                                  (self.max_age_ms, 50, 10000), (self.injected_wait_ms, 0, 3000)]:
            if not low <= value <= high:
                raise ValueError('Orçamento fora dos limites')


def explanation(response):
    d = response['decision']
    action = d['action']['type']
    if response['origin'] == 'observed_pixels':
        return 'AGUARDAR — fase, identidade e tabuleiro ainda não confirmados.', 'abstention'
    labels = {'hold_econ': 'PRESERVAR ECONOMIA', 'buy': 'COMPRAR', 'level': 'SUBIR DE NÍVEL',
              'roll': 'ROLAR', 'wait': 'AGUARDAR', 'sell': 'VENDER'}
    label = labels.get(action, action.upper())
    detail = next((e['detail'] for e in d.get('evidence', []) if e.get('detail')), '')
    return f'CENÁRIO CONTROLADO — {label}\n{detail}', 'abstention' if action == 'wait' else 'fixture_action'


class Session:
    def __init__(self, options, worker_factory=NativeWorker, source_factory=VideoSource):
        options.validate()
        self.options = options
        self.id = uuid.uuid4().hex
        self.cancelled = threading.Event()
        self.source_done = threading.Event()
        self.done = threading.Event()
        self.pending, self.preview, self.results = Latest(), Latest(), Latest()
        self.counts = Counter()
        self.traces = []
        self.error = None
        self.worker = self.source = None
        self.journal = Journal(options.output)
        self.factory, self.source_factory = worker_factory, source_factory
        self.start_ns = time.perf_counter_ns()
        self.lock = threading.RLock()
        self.capabilities = {}
        self.finished = False
        self._stop_started = False
        self.journal.emit(dict(event='session', session_id=self.id, options=options.__dict__,
                                clock='perf_counter_ns_same_python_process', source_mode=options.mode,
                                physical_display_latency_measured=False, official_game_connected=False))
        self.thread = threading.Thread(target=self._launch, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def emit(self, kind, **data):
        self.journal.emit(dict(event=kind, session_id=self.id, at_ns=time.perf_counter_ns(), **data))

    def _launch(self):
        consumer = None
        try:
            t = time.perf_counter_ns()
            self.worker = self.factory(self.options.worker, self.options.configs, self.options.tesseract,
                                       self.options.controls, Path(self.options.output)/'native-stderr.log')
            self.capabilities = dict(native_engine='real' if self.factory is NativeWorker else 'test_double', native_pid=self.worker.ready.get('pid'),
                                     native_startup_ms=(time.perf_counter_ns()-t)/1e6,
                                     hud_and_shop='real' if self.options.mode=='replay' and self.worker.ready['ocr_available'] else 'not_executed',
                                     controls_profile='explicit_custom' if self.options.controls else 'S3_frozen_not_S4',
                                     hud_profile='numeric_gray_v3_no_stage_recovery',
                                     board='not_connected', ui_map='not_connected', hp='not_connected',
                                     state_fusion='single_frame_partial_no_temporal_fusion', llm='not_connected',
                                     windows_screen_capture='not_connected', online_training='not_connected',
                                     body_ground_assignment='not_connected', strategic_accuracy=None)
            self.model = None
            if self.options.mode == 'replay' and self.options.model:
                from .model import MapObserver
                self.model = MapObserver(self.options.model)
                self.capabilities['ui_map'] = 'real_diagnostic_only'
                self.capabilities['model_sha256'] = self.model.hash
                self.capabilities['model_load_ms'] = self.model.load_ms
            if self.options.mode == 'replay' and self.options.board_reference:
                from PIL import Image
                p = Path(self.options.board_reference)
                with Image.open(p) as im:
                    im = im.convert('RGB'); w, h = im.size; rgb = im.tobytes()
                self.worker.request(dict(op='reference', id=0, source_ms=0, width=w, height=h, bytes=len(rgb)), rgb)
                self.capabilities['board'] = 'real_B1_proposals_not_units'
                self.capabilities['board_reference_sha256'] = digest(p)
            if self.options.mode == 'replay':
                self.source = self.source_factory(self.options.video, self.options.ffmpeg, self.options.ffprobe)
            self.capabilities['native_binary_sha256'] = digest(self.options.worker) if Path(self.options.worker).is_file() else None
            self.capabilities['configuration_hashes'] = {
                str(p.relative_to(Path(self.options.configs))): digest(p)
                for p in Path(self.options.configs).rglob('*.json') if p.is_file()
            }
            if self.options.controls:
                self.capabilities['custom_controls_sha256'] = digest(self.options.controls)
            self.emit('capabilities', values=self.capabilities)
            consumer = threading.Thread(target=self._consume, daemon=True)
            consumer.start()
            self._produce()
            self.source_done.set()
            consumer.join(28)
            if consumer.is_alive():
                raise TimeoutError('consumer did not finish within native deadline')
        except Exception as exc:
            self.error = self.error or str(exc)
            try:
                self.emit('failed', detail=self.error)
            except OSError:
                pass
            self.cancelled.set()
        finally:
            self.source_done.set()
            if self.source:
                self.source.close()
            if self.worker:
                self.worker.close()
            if consumer and consumer is not threading.current_thread():
                consumer.join(3)
                if consumer.is_alive():
                    self.error = self.error or 'consumer shutdown incomplete'
            self.done.set()

    def _produce(self):
        next_due = -1
        frames = self.source.frames(self.cancelled, self.options.seconds) if self.source else fixture_frames(self.cancelled, self.options.seconds)
        for f in frames:
            if self.cancelled.is_set():
                break
            self.counts['source_frames'] += 1
            self.emit('frame_released', frame_id=f.id, source_ms=f.pts_ms, due_ns=f.due_ns,
                      ready_ns=f.ready_ns, source_late_ms=(f.ready_ns-f.due_ns)/1e6,
                      rgb_bytes=len(f.rgb), time_basis='decoded_pts' if self.source else 'fixture_clock')
            if self.preview.put(f) is not None:
                self.counts['preview_coalesced'] += 1
            if f.due_ns < next_due:
                self.counts['reader_rate_skipped'] += 1
                continue
            next_due = f.due_ns + int(1e9 / self.options.reader_hz)
            previous = self.pending.put(f)
            if previous is not None:
                self.counts['reader_pending_superseded'] += 1
                self.emit('reader_superseded', old_frame_id=previous.id, replacement_frame_id=f.id)
            self.counts['reader_submitted'] += 1

    def _consume(self):
        try:
            while not self.cancelled.is_set():
                try:
                    f = self.pending.get()
                except queue.Empty:
                    if self.source_done.is_set():
                        return
                    continue
                started = time.perf_counter_ns()
                trace = dict(trace_id=f'{self.id}:{f.id}', frame_id=f.id, source_ms=f.pts_ms,
                             source_due_ns=f.due_ns, source_ready_ns=f.ready_ns, worker_start_ns=started,
                             queue_ms=(started-f.ready_ns)/1e6, source_late_ms=(f.ready_ns-f.due_ns)/1e6,
                             ui_apply_ns=None, ui_applied_latency_ms=None, physical_display_ms=None)
                model = self.model.observe(f) if self.model else None
                wait = self.options.injected_wait_ms
                if wait:
                    self.cancelled.wait(wait/1000)
                if self.cancelled.is_set():
                    self.counts['cancelled_inflight'] += 1
                    return
                h = dict(op='fixture' if self.options.mode=='fixtures' else 'frame', id=f.id,
                         source_ms=round(f.pts_ms), width=f.width, height=f.height, bytes=len(f.rgb), case=(f.id//4)%4)
                t = time.perf_counter_ns()
                answer = self.worker.request(h, f.rgb, timeout=12)
                native_roundtrip = (time.perf_counter_ns()-t)/1e6
                t = time.perf_counter_ns()
                text, kind = explanation(answer)
                explanation_ms = (time.perf_counter_ns()-t)/1e6
                ready = time.perf_counter_ns()
                age = (ready-f.due_ns)/1e6
                trace.update(origin=answer['origin'], result_kind=kind, native_roundtrip_ms=native_roundtrip,
                             explanation_ms=explanation_ms, model=model, native_spans=answer['spans'],
                             payload_bytes=len(f.rgb), native_ms=answer.get('native_ms'),
                             ipc_residual_ms=native_roundtrip-answer['native_ms'] if 'native_ms' in answer else None,
                             decision_ready_ns=ready, source_to_ready_ms=age, state_revision=answer['state']['revision'],
                             oldest_required_field_age_ms=age if kind=='fixture_action' else None,
                             injected_wait_ms=wait, injection_kind='explicit_sleep_not_inference' if wait else None,
                             expired_at_ready=age>self.options.max_age_ms,
                             opportunities_evaluated=len(answer['report']['all']))
                with self.lock:
                    self.traces.append(trace)
                self.counts['processed'] += 1
                self.counts[kind] += 1
                self.emit('decision_ready', trace=trace.copy(), observations=answer, text=text)
                result = dict(trace=trace, text=text, answer=answer)
                if self.results.put(result) is not None:
                    self.counts['ui_pending_superseded'] += 1
        except Exception as exc:
            self.error = self.error or str(exc)
            self.cancelled.set()
            try:
                self.emit('consumer_failed', error=str(exc))
            except OSError:
                pass
            if self.source:
                self.source.close()

    def acknowledge(self, result, ui_kind='tk_applied_not_physical_display'):
        now = time.perf_counter_ns()
        trace = result['trace']
        with self.lock:
            trace['ui_apply_ns'] = now
            trace['ui_applied_latency_ms'] = (now-trace['source_due_ns'])/1e6
            trace['ui_queue_ms'] = (now-trace['decision_ready_ns'])/1e6
            trace['expired_at_ui'] = trace['ui_applied_latency_ms'] > self.options.max_age_ms
            trace['ui_confirmation'] = ui_kind
        self.counts['ui_applied' if ui_kind.startswith('tk') else 'headless_sink_applied'] += 1
        if trace['expired_at_ui']:
            self.counts['ui_expired'] += 1
        self.emit('ui_applied_estimate' if ui_kind.startswith('tk') else 'headless_sink', trace=trace.copy())
        return trace

    def stop(self):
        self.cancelled.set()
        with self.lock:
            if self._stop_started:
                return
            self._stop_started = True
        def close_owned():
            for obj in (self.source, self.worker):
                if obj:
                    try:
                        obj.close()
                    except Exception as exc:
                        self.error = self.error or str(exc)
        threading.Thread(target=close_owned, daemon=True).start()

    def finish(self):
        if not self.done.is_set():
            raise RuntimeError('workers still running')
        if self.finished:
            raise RuntimeError('session already sealed')
        self.finished = True
        with self.lock:
            traces = list(self.traces)
        span_groups = {}
        for r in traces:
            for s in r['native_spans']:
                span_groups.setdefault(s['stage'], []).append(s['duration_ms'])
        ranked = sorted((dict(stage=k, **quantiles(v)) for k,v in span_groups.items()),
                        key=lambda d: d['p50_ms'] or 0, reverse=True)
        real_ui = [r for r in traces if str(r.get('ui_confirmation','')).startswith('tk')]
        summary = dict(schema_version=1, policy='e1_replay_lab_v1', session_id=self.id,
                       mode=self.options.mode, source_clock_independent_of_reader=True,
                       options=self.options.__dict__, counts=dict(self.counts),
                       capabilities=self.capabilities, execution_complete=self.error is None and not self.cancelled.is_set(),
                       cancelled=self.cancelled.is_set(), error=self.error,
                       elapsed_seconds=(time.perf_counter_ns()-self.start_ns)/1e9,
                       timings={k:quantiles([r.get(k) for r in traces]) for k in
                                ('source_late_ms','queue_ms','native_roundtrip_ms','source_to_ready_ms','explanation_ms')},
                       source_to_tk_apply=quantiles([r['ui_applied_latency_ms'] for r in real_ui]),
                       latency_by_result={kind: quantiles([r['source_to_ready_ms'] for r in traces if r['result_kind']==kind])
                                          for kind in sorted({r['result_kind'] for r in traces})},
                       ipc_residual=quantiles([r.get('ipc_residual_ms') for r in traces]),
                       model_resize=quantiles([r['model']['resize_ms'] for r in traces if r.get('model')]),
                       model_inference=quantiles([r['model']['inference_ms'] for r in traces if r.get('model')]),
                       stage_processing_rank_not_causal_attribution=ranked,
                       actionable_visual_tips=0, game_state_updated=False, profile_promoted=False,
                       physical_display_latency_measured=False, full_product_latency_established=False,
                       note='Fixtures exercise actual engine but not perception. Visual route abstains on missing phase/identity. No live capture.')
        return self.journal.close(summary)
