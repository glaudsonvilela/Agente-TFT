"""HM3 capture runtime. Reuse only byte-identical complete frames within a short lease."""
from __future__ import annotations
import copy, queue, time
from .core import native_regions
from .session import Session

READER_CACHE_MAX_MS = 750.0


def reader_signature(frame, registry=None):
    """Retain one immutable RGB object, without hashing/copying or guessed reader footprints.

    All pixels matter until every reader's search/eligibility footprint is formalized.
    Python bytes equality compares the complete buffer, not a probabilistic digest.
    """
    if (frame.width, frame.height) != (1920, 1080):
        return None
    if not isinstance(frame.rgb, bytes) or len(frame.rgb) != frame.width * frame.height * 3:
        raise ValueError('Invalid immutable RGB payload')
    return frame.rgb


def reusable(last, pixels, frame):
    return bool(pixels is not None and last is not None and
                last['epoch'] == frame.epoch and
                0 <= (frame.due_ns - last['due_ns']) / 1e6 <= READER_CACHE_MAX_MS and
                last['signature'] == pixels)


class RuntimeSession(Session):
    policy_name = 'hud_mapper_hm3_runtime'
    primary_objective = 'live_HUD_mapping_geometry_telemetry_and_training_material'

    def __init__(self, options):
        if not str(options.video).startswith('capture://'):
            raise ValueError('HM3 Runtime aceita somente monitor/janela; não vídeo.')
        super().__init__(options)
        self._last_native = None

    def _native_loop(self):
        next_save = -1
        interval = max(2000, self.options.seconds * 1000 / max(1, self.options.max_samples // 4))
        try:
            while not self.cancel.is_set():
                try:
                    frame = self.native_pending.get()
                except queue.Empty:
                    if self.producer_done.is_set():
                        break
                    continue
                start = time.perf_counter_ns()
                pixels = reader_signature(frame)
                # B1 reuse remains disabled conservatively; no change to its temporal assumptions.
                hit = not self.options.board_reference and reusable(self._last_native, pixels, frame)
                compare_ms = (time.perf_counter_ns() - start) / 1e6
                executed = False
                if (frame.width, frame.height) != (1920, 1080):
                    self._last_native = None
                    self.counts['reader_resolution_skipped'] += 1
                    regions = self.registry.fixed(frame.width, frame.height)
                    for reg in regions:
                        if reg['id'] == 'player.hp':
                            reg['status'] = 'resolution_incompatible'
                    answer = dict(id=frame.id, origin='resolution_gate', spans=[], hud=[], shop=None, controls=None, hp=None)
                elif hit:
                    self.counts['reader_exact_cache_hits'] += 1
                    previous = self._last_native
                    age = (frame.due_ns - previous['due_ns']) / 1e6
                    regions = copy.deepcopy(previous['regions'])
                    for reg in regions:
                        reg.update(cached_from_frame_id=previous['frame_id'], cache_age_ms=age,
                                   evidence_mode='cached_identical_full_rgb_not_new_OCR')
                    answer = copy.deepcopy(previous['answer'])
                    # Keep original IDs and timings within the evidence, never relabel them as new work.
                    answer['cache_delivery'] = dict(delivered_frame_id=frame.id, source_frame_id=previous['frame_id'], age_ms=age)
                    spans = [dict(stage='reader_exact_cache', start_ms=0.0, duration_ms=compare_ms)]
                else:
                    executed = True
                    self.counts['reader_native_runs'] += 1
                    request = dict(op='frame', id=frame.id, source_ms=round(frame.pts_ms),
                                   width=frame.width, height=frame.height, bytes=len(frame.rgb))
                    answer = self.worker.request(request, frame.rgb, timeout=12)
                    hp_start = time.perf_counter_ns()
                    hp = self.hp_worker.request(request, frame.rgb, timeout=12)
                    if answer.get('id') != frame.id or hp.get('id') != frame.id:
                        raise ValueError('Resposta pertence a outro frame')
                    answer['hp'] = hp['hp']
                    answer['spans'].append(dict(stage='hp_baseline', start_ms=(hp_start - start) / 1e6, duration_ms=hp['native_ms']))
                    regions = native_regions(answer, self.registry, frame.width, frame.height)
                    if pixels is not None:
                        self._last_native = dict(signature=pixels, epoch=frame.epoch, due_ns=frame.due_ns, frame_id=frame.id,
                                                 answer=copy.deepcopy(answer), regions=copy.deepcopy(regions))
                end = time.perf_counter_ns()
                if not hit:
                    spans = answer.get('spans', [])
                record = dict(frame_id=frame.id, source_ms=frame.pts_ms, regions=regions, answer=answer,
                              queue_ms=(start - frame.ready_ns) / 1e6, source_to_reader_ms=(end - frame.due_ns) / 1e6,
                              reader_elapsed_ms=(end - start) / 1e6, reader_signature_ms=compare_ms,
                              reader_cache_exact_hit=hit, cache_policy='full_immutable_RGB_equality_750ms',
                              native_executed=executed, image_size=[frame.width, frame.height], ground_truth=False)
                with self.lock:
                    for reg in regions:
                        self.coverage[(reg['id'], reg['status'])] += 1
                    self.traces.append(dict(kind='reader', frame_id=frame.id, source_due_ns=frame.due_ns,
                                            ready_ns=end, queue_ms=record['queue_ms'], total_ms=record['source_to_reader_ms'],
                                            reader_elapsed_ms=record['reader_elapsed_ms'], signature_ms=compare_ms,
                                            cache_exact_hit=hit, native_executed=executed, spans=spans))
                save = frame.pts_ms >= next_save
                if save:
                    next_save = frame.pts_ms + interval
                self.store.emit('roi-observations', record, frame, save)
                self.native_results.put(dict(frame=frame, record=record, ready_ns=end))
                self.counts['read_frames'] += 1
        except Exception as exc:
            self.error = str(exc)
            self.stop()
