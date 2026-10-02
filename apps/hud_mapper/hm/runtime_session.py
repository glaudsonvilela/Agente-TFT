"""HM3/HM4 capture runtime. HM4 can normalize verified 16:9 pixels for frozen 1920x1080 readers."""
from __future__ import annotations
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import copy, queue, time
from PIL import Image
from .core import native_regions, valid_box
from .session import Session

READER_CACHE_MAX_MS = 750.0
CANONICAL_READER_SIZE = (1920, 1080)
ASPECT_16_9 = 16 / 9
ASPECT_TOLERANCE = 0.005


def reader_plan(frame, allow_normalize=False):
    """Describe reader input without altering the captured source pixels."""
    if not isinstance(frame.rgb, bytes) or len(frame.rgb) != frame.width * frame.height * 3:
        raise ValueError('Invalid immutable RGB payload')
    source = [frame.width, frame.height]
    if (frame.width, frame.height) == CANONICAL_READER_SIZE:
        return dict(supported=True, normalized=False, source_size=source,
                    reader_size=list(CANONICAL_READER_SIZE), method='native_1920x1080',
                    aspect_error_pct=0.0, scale_x=1.0, scale_y=1.0)
    ratio = frame.width / frame.height
    error = abs(ratio - ASPECT_16_9) / ASPECT_16_9
    if not allow_normalize:
        return dict(supported=False, normalized=False, source_size=source,
                    reader_size=list(CANONICAL_READER_SIZE), method='exact_1920x1080_required',
                    aspect_error_pct=error * 100, reason='reader_requires_1920x1080')
    if error > ASPECT_TOLERANCE:
        return dict(supported=False, normalized=False, source_size=source,
                    reader_size=list(CANONICAL_READER_SIZE), method='reject_non_16_9',
                    aspect_error_pct=error * 100, reason='source_aspect_ratio_not_16_9')
    return dict(supported=True, normalized=True, source_size=source,
                reader_size=list(CANONICAL_READER_SIZE), method='RGB_LANCZOS_16_9_to_1920x1080_v1',
                aspect_error_pct=error * 100,
                scale_x=CANONICAL_READER_SIZE[0] / frame.width,
                scale_y=CANONICAL_READER_SIZE[1] / frame.height)


def materialize_reader_frame(frame, plan):
    """Return a derived reader frame; original immutable capture is retained separately."""
    if not plan.get('supported'):
        return None, 0.0
    if not plan.get('normalized'):
        return frame, 0.0
    started = time.perf_counter_ns()
    image = Image.frombytes('RGB', (frame.width, frame.height), frame.rgb)
    image = image.resize(CANONICAL_READER_SIZE, Image.Resampling.LANCZOS)
    out = replace(frame, width=CANONICAL_READER_SIZE[0], height=CANONICAL_READER_SIZE[1],
                  rgb=image.tobytes())
    return out, (time.perf_counter_ns() - started) / 1e6


def regions_to_source(regions, source_frame, plan):
    """Project only displayed/stored region geometry back to original capture coordinates."""
    if not plan.get('normalized'):
        return regions
    sx = source_frame.width / CANONICAL_READER_SIZE[0]
    sy = source_frame.height / CANONICAL_READER_SIZE[1]
    out = copy.deepcopy(regions)
    for reg in out:
        box = reg.get('box')
        if box and valid_box(box, *CANONICAL_READER_SIZE):
            reg['reader_box_1920x1080'] = list(box)
            reg['box'] = [box[0]*sx, box[1]*sy, box[2]*sx, box[3]*sy]
            reg['reader_geometry_transform'] = plan['method']
        points = reg.get('guide_points')
        if isinstance(points, list):
            for point in points:
                screen = point.get('screen') if isinstance(point, dict) else None
                if isinstance(screen, list) and len(screen) == 2:
                    point['reader_screen_1920x1080'] = list(screen)
                    point['screen'] = [screen[0]*sx, screen[1]*sy]
    return out


def reader_signature(frame, allow_any_resolution=False):
    """Retain one immutable SOURCE RGB object; cache never hashes guessed ROI footprints."""
    if not allow_any_resolution and (frame.width, frame.height) != CANONICAL_READER_SIZE:
        return None
    if not isinstance(frame.rgb, bytes) or len(frame.rgb) != frame.width * frame.height * 3:
        raise ValueError('Invalid immutable RGB payload')
    return frame.rgb


def reusable(last, pixels, frame):
    return bool(pixels is not None and last is not None and
                last['epoch'] == frame.epoch and
                last.get('size') == (frame.width, frame.height) and
                0 <= (frame.due_ns - last['due_ns']) / 1e6 <= READER_CACHE_MAX_MS and
                last['signature'] == pixels)


class RuntimeSession(Session):
    policy_name = 'hud_mapper_hm3_runtime'
    primary_objective = 'live_HUD_mapping_geometry_telemetry_and_training_material'
    normalize_reader_input = False
    shop_interval_ms = 0.0

    def __init__(self, options):
        if not str(options.video).startswith('capture://'):
            raise ValueError('HM3 Runtime aceita somente monitor/janela; não vídeo.')
        super().__init__(options)
        self._last_native = None
        self._next_shop_ms = 0.0

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
                plan = reader_plan(frame, allow_normalize=self.normalize_reader_input)
                pixels = reader_signature(frame, allow_any_resolution=bool(plan.get('supported') and self.normalize_reader_input))
                hit = bool(plan.get('supported') and not self.options.board_reference and
                           reusable(self._last_native, pixels, frame))
                compare_ms = (time.perf_counter_ns() - start) / 1e6
                executed = False
                normalize_ms = 0.0

                if not plan.get('supported'):
                    self._last_native = None
                    self.counts['reader_resolution_skipped'] += 1
                    regions = self.registry.fixed(frame.width, frame.height)
                    for reg in regions:
                        if reg['id'] == 'player.hp':
                            reg['status'] = 'resolution_incompatible'
                    answer = dict(id=frame.id, origin='resolution_gate', spans=[], hud=[], shop=None,
                                  controls=None, hp=None, reader_input_transform=plan)
                elif hit:
                    self.counts['reader_exact_cache_hits'] += 1
                    previous = self._last_native
                    age = (frame.due_ns - previous['due_ns']) / 1e6
                    regions = copy.deepcopy(previous['regions'])
                    for reg in regions:
                        reg.update(cached_from_frame_id=previous['frame_id'], cache_age_ms=age,
                                   evidence_mode='cached_identical_full_source_rgb_not_new_OCR')
                    answer = copy.deepcopy(previous['answer'])
                    answer['cache_delivery'] = dict(delivered_frame_id=frame.id,
                                                    source_frame_id=previous['frame_id'], age_ms=age)
                    spans = [dict(stage='reader_exact_cache', start_ms=0.0, duration_ms=compare_ms)]
                else:
                    reader_frame, normalize_ms = materialize_reader_frame(frame, plan)
                    if reader_frame is None:
                        raise ValueError('Reader plan marked supported but produced no input frame')
                    if plan.get('normalized'):
                        self.counts['reader_normalized_runs'] += 1
                    executed = True
                    self.counts['reader_native_runs'] += 1
                    include_shop = (self.shop_interval_ms <= 0 or frame.pts_ms >= self._next_shop_ms)
                    request = dict(op='frame', id=frame.id, source_ms=round(frame.pts_ms),
                                   width=reader_frame.width, height=reader_frame.height,
                                   bytes=len(reader_frame.rgb), include_shop=include_shop)
                    # Independent processes: overlap HP with the main HUD/shop worker.
                    hp_start = time.perf_counter_ns()
                    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='hm4-hp') as pool:
                        hp_future = pool.submit(self.hp_worker.request, request, reader_frame.rgb, 12)
                        answer = self.worker.request(request, reader_frame.rgb, timeout=12)
                        hp = hp_future.result(timeout=13)
                    if include_shop and self.shop_interval_ms > 0:
                        self._next_shop_ms = frame.pts_ms + self.shop_interval_ms
                    if plan.get('normalized'):
                        answer['spans'].insert(0, dict(stage='reader_normalize_16_9',
                            start_ms=compare_ms, duration_ms=normalize_ms))
                    if answer.get('id') != frame.id or hp.get('id') != frame.id:
                        raise ValueError('Resposta pertence a outro frame')
                    answer['hp'] = hp['hp']
                    answer['reader_input_transform'] = plan
                    answer['spans'].append(dict(stage='hp_baseline',
                        start_ms=(hp_start - start) / 1e6, duration_ms=hp['native_ms']))
                    canonical_regions = native_regions(answer, self.registry,
                                                       reader_frame.width, reader_frame.height)
                    regions = regions_to_source(canonical_regions, frame, plan)
                    if pixels is not None:
                        self._last_native = dict(signature=pixels, epoch=frame.epoch,
                            size=(frame.width, frame.height), due_ns=frame.due_ns, frame_id=frame.id,
                            answer=copy.deepcopy(answer), regions=copy.deepcopy(regions))
                end = time.perf_counter_ns()
                if not hit:
                    spans = answer.get('spans', [])
                record = dict(frame_id=frame.id, source_ms=frame.pts_ms, regions=regions, answer=answer,
                              queue_ms=(start - frame.ready_ns) / 1e6,
                              source_to_reader_ms=(end - frame.due_ns) / 1e6,
                              reader_elapsed_ms=(end - start) / 1e6,
                              reader_signature_ms=compare_ms, reader_normalize_ms=normalize_ms,
                              reader_input_transform=plan,
                              reader_cache_exact_hit=hit,
                              cache_policy='full_immutable_source_RGB_equality_750ms',
                              native_executed=executed,
                              image_size=[frame.width, frame.height], ground_truth=False)
                with self.lock:
                    for reg in regions:
                        self.coverage[(reg['id'], reg['status'])] += 1
                    self.traces.append(dict(kind='reader', frame_id=frame.id,
                                            source_due_ns=frame.due_ns, ready_ns=end,
                                            queue_ms=record['queue_ms'],
                                            total_ms=record['source_to_reader_ms'],
                                            reader_elapsed_ms=record['reader_elapsed_ms'],
                                            signature_ms=compare_ms, normalize_ms=normalize_ms,
                                            input_transform=plan,
                                            cache_exact_hit=hit, native_executed=executed,
                                            spans=spans))
                save = frame.pts_ms >= next_save
                if save:
                    next_save = frame.pts_ms + interval
                self.store.emit('roi-observations', record, frame, save)
                self.native_results.put(dict(frame=frame, record=record, ready_ns=end))
                self.counts['read_frames'] += 1
        except Exception as exc:
            self.error = str(exc)
            self.stop()


class HM4RuntimeSession(RuntimeSession):
    """HM4 automatic shell with reversible 16:9 reader normalization."""
    policy_name = 'hud_mapper_hm4_auto'
    primary_objective = 'live_HUD_capture_geometry_telemetry_with_automatic_model_discovery'
    normalize_reader_input = True
    shop_interval_ms = 2000.0
