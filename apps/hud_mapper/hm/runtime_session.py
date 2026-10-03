"""HM3/HM4 capture runtime. HM4 can normalize verified 16:9 pixels for frozen 1920x1080 readers."""
from __future__ import annotations
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import copy, hashlib, queue, threading, time
from PIL import Image
from .core import native_regions, valid_box
from .session import Session

READER_CACHE_MAX_MS = 750.0
CANONICAL_READER_SIZE = (1920, 1080)
ASPECT_16_9 = 16 / 9
ASPECT_TOLERANCE = 0.005
ASYNC_HP_MAX_AGE_MS = 2000.0


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


def async_hp_delivery(frame, latest, max_age_ms=ASYNC_HP_MAX_AGE_MS):
    """Choose only causal, same-geometry HP evidence; never relabel stale output as fresh."""
    pending = dict(status='async_pending', signed_hp=None, hp=None)
    if not latest:
        return pending, dict(mode='async_pending', fresh=False, age_ms=None)
    if latest.get('epoch') != frame.epoch or latest.get('due_ns', frame.due_ns + 1) > frame.due_ns:
        return pending, dict(mode='async_pending', fresh=False, age_ms=None,
                             source_frame_id=latest.get('frame_id'))
    age = max(0.0, (frame.due_ns - latest['due_ns']) / 1e6)
    meta = dict(mode='async_latest_causal', fresh=age <= max_age_ms, age_ms=age,
                source_frame_id=latest.get('frame_id'), source_ms=latest.get('source_ms'),
                ready_ns=latest.get('ready_ns'))
    source_hp = copy.deepcopy((latest.get('response') or {}).get('hp') or pending)
    if age > max_age_ms:
        return dict(status='async_stale', signed_hp=None, hp=None,
                    last_observation=source_hp), {**meta, 'mode':'async_stale', 'fresh':False}
    return source_hp, meta


class RuntimeSession(Session):
    policy_name = 'hud_mapper_hm3_runtime'
    primary_objective = 'live_HUD_mapping_geometry_telemetry_and_training_material'
    normalize_reader_input = False
    shop_interval_ms = 0.0
    separate_hp_loop = False
    hp_hz = 1.0
    hp_max_delivery_ms = ASYNC_HP_MAX_AGE_MS

    def __init__(self, options):
        if not str(options.video).startswith('capture://'):
            raise ValueError('HM3 Runtime aceita somente monitor/janela; não vídeo.')
        super().__init__(options)
        self._last_native = None
        self._next_shop_ms = 0.0
        self._latest_hp = None


    def _hp_loop(self):
        try:
            while not self.cancel.is_set():
                try:
                    frame = self.hp_pending.get()
                except queue.Empty:
                    if self.producer_done.is_set():
                        break
                    continue
                start = time.perf_counter_ns()
                plan = reader_plan(frame, allow_normalize=self.normalize_reader_input)
                executed = False
                if not plan.get('supported'):
                    response = dict(id=frame.id, source_ms=round(frame.pts_ms),
                                    hp=dict(status='resolution_incompatible', signed_hp=None, hp=None),
                                    native_ms=0.0)
                else:
                    executed = True
                    reader_frame, normalize_ms = materialize_reader_frame(frame, plan)
                    request = dict(op='frame', id=frame.id, source_ms=round(frame.pts_ms),
                                   width=reader_frame.width, height=reader_frame.height,
                                   bytes=len(reader_frame.rgb), include_shop=False)
                    response = self.hp_worker.request(request, reader_frame.rgb, timeout=12)
                    response['reader_normalize_ms'] = normalize_ms
                    if response.get('id') != frame.id:
                        raise ValueError('Resposta HP pertence a outro frame')
                end = time.perf_counter_ns()
                latest = dict(frame_id=frame.id, source_ms=frame.pts_ms, due_ns=frame.due_ns,
                              epoch=frame.epoch, ready_ns=end, response=response,
                              input_transform=plan)
                with self.lock:
                    self._latest_hp = latest
                    self.traces.append(dict(kind='hp', frame_id=frame.id,
                                            source_due_ns=frame.due_ns, ready_ns=end,
                                            queue_ms=(start-frame.ready_ns)/1e6,
                                            total_ms=(end-frame.due_ns)/1e6,
                                            native_ms=float(response.get('native_ms') or 0.0),
                                            native_executed=executed,input_transform=plan))
                self.counts['hp_results'] += 1
                if executed:
                    self.counts['hp_native_runs'] += 1
        except Exception as exc:
            self.error = str(exc)
            self.stop()

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
                           not self.separate_hp_loop and
                           not (getattr(self, 'board_reference_requested', None) and self.board_reference_requested.is_set()) and
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
                    if (self.options.board_hub_enabled and self.board_reference_requested.is_set()):
                        try:
                            reply = self.worker.request(dict(op='reference', id=frame.id,
                                source_ms=round(frame.pts_ms), width=reader_frame.width,
                                height=reader_frame.height, bytes=len(reader_frame.rgb)),
                                reader_frame.rgb, timeout=12)
                            if not reply.get('reference_ready'):
                                raise ValueError('B1 reference was not accepted')
                            self.versions['board_reference_sha256'] = hashlib.sha256(reader_frame.rgb).hexdigest()
                            self.versions['board_reference_frame_id'] = frame.id
                            self.versions['board_reference_status'] = 'manual_replay_frame'
                        except Exception as exc:
                            self.versions['board_reference_status'] = 'failed'
                            self.versions['board_reference_error'] = str(exc)
                        finally:
                            self.board_reference_requested.clear()
                    executed = True
                    self.counts['reader_native_runs'] += 1
                    include_shop = (self.shop_interval_ms <= 0 or frame.pts_ms >= self._next_shop_ms)
                    request = dict(op='frame', id=frame.id, source_ms=round(frame.pts_ms),
                                   width=reader_frame.width, height=reader_frame.height,
                                   bytes=len(reader_frame.rgb), include_shop=include_shop)
                    if self.separate_hp_loop:
                        answer = self.worker.request(request, reader_frame.rgb, timeout=12)
                        if answer.get('id') != frame.id:
                            raise ValueError('Resposta pertence a outro frame')
                        with self.lock:
                            latest_hp = copy.deepcopy(self._latest_hp)
                        hp_value, hp_meta = async_hp_delivery(frame, latest_hp, self.hp_max_delivery_ms)
                        answer['hp'] = hp_value
                        answer['hp_delivery'] = hp_meta
                        answer['spans'].append(dict(stage='hp_async_delivery',
                            start_ms=(time.perf_counter_ns()-start)/1e6, duration_ms=0.0,
                            source_frame_id=hp_meta.get('source_frame_id'), age_ms=hp_meta.get('age_ms'),
                            fresh=hp_meta.get('fresh',False)))
                    else:
                        # HM3 compatibility: preserve same-frame HP by overlapping independent workers.
                        hp_start = time.perf_counter_ns()
                        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='hm3-hp') as pool:
                            hp_future = pool.submit(self.hp_worker.request, request, reader_frame.rgb, 12)
                            answer = self.worker.request(request, reader_frame.rgb, timeout=12)
                            hp = hp_future.result(timeout=13)
                        if answer.get('id') != frame.id or hp.get('id') != frame.id:
                            raise ValueError('Resposta pertence a outro frame')
                        answer['hp'] = hp['hp']
                        answer['spans'].append(dict(stage='hp_baseline',
                            start_ms=(hp_start - start) / 1e6, duration_ms=hp['native_ms']))
                    if include_shop and self.shop_interval_ms > 0:
                        self._next_shop_ms = frame.pts_ms + self.shop_interval_ms
                    if plan.get('normalized'):
                        answer['spans'].insert(0, dict(stage='reader_normalize_16_9',
                            start_ms=compare_ms, duration_ms=normalize_ms))
                    answer['reader_input_transform'] = plan
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
                if self.options.replay_review:
                    from .replay_coach import economy_prompt
                    tip = economy_prompt(answer)
                    tip.update(frame_id=frame.id, source_ms=frame.pts_ms,
                               source_due_ns=frame.due_ns, ready_ns=end,
                               input_kind='previously_recorded_video_on_screen',
                               ground_truth=False, game_state_updated=False)
                    if tip['text'] != getattr(self, '_last_replay_tip', None) or frame.pts_ms >= getattr(self, '_next_tip_ms', 0):
                        self._last_replay_tip = tip['text']
                        self._next_tip_ms = frame.pts_ms + 5000
                        self.store.emit('replay-tips', tip)
                        self.latest_replay_tip = tip
                        self.counts['replay_tips'] += 1
                if self.options.board_hub_enabled and plan.get('supported') and not hit:
                    next_hub = getattr(self, '_next_hub_ms', -1)
                    if frame.pts_ms >= next_hub:
                        self._next_hub_ms = frame.pts_ms + 5000
                        self.hub_pending.put((frame, reader_frame, answer.get('board'), plan))
        except Exception as exc:
            self.error = str(exc)
            self.stop()


class HM4RuntimeSession(RuntimeSession):
    """HM4 automatic shell with reversible 16:9 reader normalization."""
    policy_name = 'hud_mapper_hm4_auto'
    primary_objective = 'live_HUD_capture_geometry_telemetry_with_automatic_model_discovery'
    normalize_reader_input = True
    shop_interval_ms = 2000.0
    separate_hp_loop = True
    hp_hz = 1.0
    hp_max_delivery_ms = 2000.0
    native_worker_env = {"AGENTE_TFT_RESIDENT_OCR":"auto"}

    def __init__(self, options):
        super().__init__(options)
        self.board_reference_requested = threading.Event()
        self.latest_replay_tip = None

    def request_board_reference(self):
        if not self.options.board_hub_enabled or self.done.is_set():
            raise ValueError('Inicie a revisão de replay antes de calibrar o tabuleiro')
        self.board_reference_requested.set()

    def _hub_loop(self):
        try:
            from .board_hub_live import BoardHubLive
            from .replay_coach import inventory_prompt
            observer = BoardHubLive(self.options.configs)
            self.versions['board_hub_reference_sha256'] = observer.manifest['reference_sha256']
            self.versions['board_hub_set_key'] = observer.manifest['set_key']
            self.versions['board_hub_mode'] = 'replay_screen_candidate_only'
            self.versions['board_reference_status'] = 'not_calibrated'
            while not self.cancel.is_set():
                try:
                    frame, reader_frame, board_read, plan = self.hub_pending.get()
                except queue.Empty:
                    if self.producer_done.is_set():
                        break
                    continue
                started = time.perf_counter_ns()
                observed = observer.observe(reader_frame, board_read)
                end = time.perf_counter_ns()
                regions = regions_to_source(observed['regions'], frame, plan)
                record = dict(frame_id=frame.id, source_ms=frame.pts_ms, regions=regions,
                              snapshot=observed['snapshot'], image_size=[frame.width, frame.height],
                              reader_input_transform=plan, ground_truth=False,
                              source_to_hub_ms=(end-frame.due_ns)/1e6,
                              hub_processing_ms=(end-started)/1e6,
                              board_reference_status=self.versions.get('board_reference_status'),
                              game_state_updated=False)
                with self.lock:
                    for reg in regions:
                        self.coverage[(reg['id'], reg['status'])] += 1
                    self.traces.append(dict(kind='hub', frame_id=frame.id,
                        source_due_ns=frame.due_ns, ready_ns=end,
                        total_ms=record['source_to_hub_ms'],
                        processing_ms=record['hub_processing_ms']))
                self.store.emit('board-hub-observations', record)
                self.hub_results.put(dict(frame=frame, record=record, ready_ns=end))
                self.counts['hub_results'] += 1
                tip = inventory_prompt(observed['snapshot'])
                if tip is not None:
                    tip.update(frame_id=frame.id, source_ms=frame.pts_ms,
                               source_due_ns=frame.due_ns, ready_ns=end,
                               input_kind='previously_recorded_video_on_screen',
                               ground_truth=False, game_state_updated=False)
                    self.store.emit('replay-tips', tip)
                    self.latest_replay_tip = tip
                    self.counts['replay_tips'] += 1
        except Exception as exc:
            self.error = str(exc)
            self.stop()
