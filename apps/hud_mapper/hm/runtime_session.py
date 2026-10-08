"""HM3/HM4 capture runtime. HM4 can normalize verified 16:9 pixels for frozen 1920x1080 readers."""
from __future__ import annotations
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import copy, hashlib, queue, threading, time
import json
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from .core import native_regions, valid_box
from .session import Session

READER_CACHE_MAX_MS = 750.0
CANONICAL_READER_SIZE = (1920, 1080)
ASPECT_16_9 = 16 / 9
ASPECT_TOLERANCE = 0.005
ASYNC_HP_MAX_AGE_MS = 2000.0
SHOP_CHANGE_MIN_BITS = 15
SHOP_CHANGE_MIN_GAP_MS = 500.0


def shop_text_signature(frame):
    """Sample only the fixed five shop name strips; no OCR or full-frame hash."""
    if (frame.width, frame.height) != CANONICAL_READER_SIZE:
        return None
    pixels = memoryview(frame.rgb)
    slots = []
    for slot in range(5):
        bits = bytearray()
        for y in range(1045, 1069, 2):
            for x in range(558 + 202 * slot, 711 + 202 * slot, 3):
                offset = (y * frame.width + x) * 3
                r, g, b = pixels[offset:offset + 3]
                bits.append(min(r, g, b) >= 130 and max(r, g, b) - min(r, g, b) <= 100)
        slots.append(bytes(bits))
    return tuple(slots)


def shop_read_due(source_ms, epoch, next_ms, signature, previous):
    """Read changed shop text promptly; refresh an unchanged shop at its normal cadence."""
    if previous is None or previous['epoch'] != epoch or source_ms < previous['source_ms']:
        return True
    if source_ms >= next_ms:
        return True
    if signature is None or previous['signature'] is None:
        return False
    if source_ms - previous['source_ms'] < SHOP_CHANGE_MIN_GAP_MS:
        return False
    return any(sum(a != b for a, b in zip(now, old)) >= SHOP_CHANGE_MIN_BITS
               for now, old in zip(signature, previous['signature']))


def hub_due(previous, frame, interval_ms):
    """Replay seeks/restarts must not wait for an old source-time deadline."""
    return (previous is None or previous['epoch'] != frame.epoch
            or frame.pts_ms < previous['source_ms']
            or frame.pts_ms - previous['source_ms'] >= interval_ms)


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


def terminal_hp_observation(hp):
    """Terminal HP is a fail-closed live-match end signal, never a replay signal."""
    if not isinstance(hp, dict):
        return False
    status = str(hp.get('status') or '').lower()
    signed_hp = hp.get('signed_hp')
    value = hp.get('hp')
    return (
        (status == 'accepted' and value == 0)
        or (status == 'negative_display' and isinstance(signed_hp, int) and signed_hp < 0)
    )


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
        self._last_shop_read = None
        self._latest_hp = None

    def _publish_coach(self, tip, frame, ready_ns):
        if tip is None:return
        tip = dict(tip, frame_id=frame.id, source_ms=frame.pts_ms,
                   source_due_ns=frame.due_ns, ready_ns=ready_ns, epoch=frame.epoch,
                   input_kind=('previously_recorded_video_on_screen' if self.options.replay_review
                               else 'live_match_on_screen'),
                   data_patch=getattr(getattr(self, 'decision_engine', None), 'patch', None),
                   data_patch_basis=('reported_replay_patch' if self.options.replay_review
                                     else 'bundled_catalog_patch_lab'),
                   ground_truth=False, game_state_updated=False)
        with self.lock:
            previous = self.latest_replay_tip
            recent_action = (previous and (previous.get('actionable') or previous.get('speakable'))
                and previous.get('epoch') == frame.epoch
                and 0 <= frame.pts_ms - previous.get('source_ms', -1) < 5000)
            recent_combat = (previous and previous.get('kind') == 'combat'
                and previous.get('epoch') == frame.epoch
                and 0 <= frame.pts_ms - previous.get('source_ms', -1) < 3000)
            if tip.get('speakable') or (tip.get('actionable') and not recent_combat) or not recent_action:
                self.latest_replay_tip=tip
            if (tip['text']==getattr(self,'_last_replay_tip',None)
                    and frame.pts_ms<getattr(self,'_next_tip_ms',0)):
                return
            self._last_replay_tip=tip['text']
            self._next_tip_ms=frame.pts_ms+5000
            self.counts['coach_updates']+=1
            if tip.get('actionable'):self.counts['replay_tips']+=1
        self.store.emit('replay-tips',tip)


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
                hp_observation = response.get('hp') or {}
                terminal_hp = terminal_hp_observation(hp_observation)
                if self.options.replay_review:
                    # A recorded replay can contain terminal HP in its middle/end;
                    # replay analysis must never stop or trigger live learning.
                    self._terminal_hp_confirmations = 0
                    self._terminal_hp_first_source_ms = None
                elif terminal_hp:
                    if self._terminal_hp_confirmations == 0:
                        self._terminal_hp_first_source_ms = frame.pts_ms
                    self._terminal_hp_confirmations += 1
                else:
                    self._terminal_hp_confirmations = 0
                    self._terminal_hp_first_source_ms = None
                if (
                    not self.options.replay_review
                    and self._terminal_hp_confirmations >= 2
                    and self._terminal_hp_first_source_ms is not None
                    and frame.pts_ms - self._terminal_hp_first_source_ms >= 500
                ):
                    self.counts['match_end_hp_confirmed'] += 1
                    self.request_match_end('terminal_hp_confirmed')
                with self.lock:
                    self._latest_hp = latest
                    self.traces.append(dict(kind='hp', frame_id=frame.id,
                                            source_due_ns=frame.due_ns, ready_ns=end,
                                            queue_ms=(start-frame.ready_ns)/1e6,
                                            total_ms=(end-frame.due_ns)/1e6,
                                            native_ms=float(response.get('native_ms') or 0.0),
                                            native_executed=executed,input_transform=plan,
                                            vm_transport=response.get('vm_transport')))
                self.counts['hp_results'] += 1
                if executed:
                    self.counts['hp_native_runs'] += 1
        except Exception as exc:
            self.error = str(exc)
            self.stop()

    def _native_loop(self):
        next_save = next_log = -1
        interval = 30000 if self.options.vm_core else max(2000, self.options.seconds * 1000 / max(1, self.options.max_samples // 4))
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
                cache_enabled=not self.separate_hp_loop and not self.options.board_reference
                pixels = (reader_signature(frame, allow_any_resolution=bool(plan.get('supported') and self.normalize_reader_input))
                          if cache_enabled else None)
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
                    executed = True
                    self.counts['reader_native_runs'] += 1
                    shop_signature = (shop_text_signature(reader_frame)
                                      if self.shop_interval_ms > 0 else None)
                    include_shop = (self.shop_interval_ms <= 0 or shop_read_due(
                        frame.pts_ms, frame.epoch, self._next_shop_ms,
                        shop_signature, self._last_shop_read))
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
                        self._last_shop_read = dict(epoch=frame.epoch,
                            source_ms=frame.pts_ms, signature=shop_signature)
                    if plan.get('normalized'):
                        answer['spans'].insert(0, dict(stage='reader_normalize_16_9',
                            start_ms=compare_ms, duration_ms=normalize_ms))
                    answer['reader_input_transform'] = plan
                    decision_engine = getattr(self, 'decision_engine', None)
                    if decision_engine and answer.get('origin') == 'observed_pixels':
                        with self.lock:
                            strategy_entry = copy.deepcopy(getattr(self, '_latest_strategy_state', None))
                            visual_entry = copy.deepcopy(getattr(self, '_latest_visual_candidates', None))
                        strategy_state = None
                        if strategy_entry and strategy_entry['epoch'] == frame.epoch:
                            strategy_state = strategy_entry['state']
                            strategy_state['age_ms'] = max(
                                frame.pts_ms - strategy_entry['source_ms'],
                                (time.perf_counter_ns() - strategy_entry['due_ns']) / 1e6)
                            if frame.pts_ms < strategy_entry['source_ms']:
                                strategy_state = None
                        visual_candidates = None
                        if visual_entry and visual_entry['epoch'] == frame.epoch:
                            age_ms = max(frame.pts_ms - visual_entry['source_ms'],
                                (time.perf_counter_ns() - visual_entry['due_ns']) / 1e6)
                            if frame.pts_ms >= visual_entry['source_ms'] and age_ms <= 3500:
                                visual_candidates = visual_entry['candidates']
                                visual_candidates['age_ms'] = age_ms
                        answer = decision_engine.evaluate(answer, strategy_state=strategy_state,
                                                          visual_candidates=visual_candidates)
                        if not self.options.replay_review:
                            answer['catalog_binding']['basis'] = 'bundled_catalog_patch_lab'
                            answer['decision']['patch_basis'] = 'bundled_catalog_patch_lab'
                        self.counts['catalog_bound_offers'] += answer['catalog_binding']['bound_offers']
                        self.latest_decision_reason = (answer['decision'].get('economy') or {}).get('code') or answer['decision']['evidence'][0]['code']
                        if answer['decision']['action']['type'] == 'wait':
                            self.counts['decision_abstentions'] += 1
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
                observed_fields = {row.get('field') for row in answer.get('hud') or []
                    if row.get('status') == 'single_frame_observation'
                    and row.get('value') is not None
                    and isinstance(row.get('confidence'), (int, float))
                    and row['confidence'] >= .85}
                if answer.get('origin') != 'observed_pixels' or 'stage' not in observed_fields:
                    self.versions['screen_mode'] = 'no_gameplay_hud'
                elif 'gold' not in observed_fields:
                    self.versions['screen_mode'] = 'stage_without_economy'
                else:
                    self.versions['screen_mode'] = 'gameplay_hud'
                if 'stage' in observed_fields:
                    stage_rows = [row for row in answer.get('hud') or []
                                  if row.get('field') == 'stage' and row.get('status') == 'single_frame_observation'
                                  and row.get('value') is not None and row.get('confidence', 0) >= .85]
                    if len(stage_rows) == 1:
                        with self.lock:
                            self._latest_native_stage = (str(stage_rows[0]['value']), frame.epoch, frame.pts_ms)
                if getattr(self, 'ubuntu_mvp_diagnostics', False):
                    with self.lock:
                        self.latest_hud_diagnostic = {
                            'frame_id': frame.id,
                            'age_source_ms': frame.pts_ms,
                            'origin': answer.get('origin'),
                            'fields': [{k: row.get(k) for k in ('field', 'status', 'value', 'confidence')}
                                       for row in answer.get('hud') or []
                                       if row.get('field') in ('stage', 'gold', 'level', 'xp')],
                            'decision_reason': self.latest_decision_reason,
                        }
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
                                            spans=spans,vm_transport=answer.get('vm_transport')))
                save = frame.pts_ms >= next_save
                if save:
                    next_save = frame.pts_ms + interval
                if save or frame.pts_ms >= next_log:
                    next_log = frame.pts_ms + (5000 if self.options.vm_core else 0)
                    self.store.emit('roi-observations', record, frame, save)
                self.native_results.put(dict(frame=frame, record=record, ready_ns=end))
                self.counts['read_frames'] += 1
                if getattr(self, 'decision_engine', None):
                    from .replay_coach import coach_prompt
                    self._publish_coach(coach_prompt(answer),frame,end)
                tracker = getattr(self, 'combat_events', None)
                if tracker is not None:
                    outcome = tracker.update(answer, epoch=frame.epoch, source_ms=frame.pts_ms)
                    if outcome:
                        opponents = getattr(self, 'opponent_tracker', None)
                        linked = (opponents.register_loss(outcome, epoch=frame.epoch,
                                                          source_ms=frame.pts_ms)
                                  if opponents else None)
                        if linked:
                            outcome['opponent_candidate'] = linked
                        self.store.emit('combat-events', dict(outcome, frame_id=frame.id,
                                                               epoch=frame.epoch))
                        self.counts['combat_loss_observations'] += 1
                        self._publish_coach(dict(status='combat_commentary',
                            kind='combat', actionable=False, speakable=True,
                            speech_text=outcome['text'], text=outcome['text'],
                            decision_key=f'combat-loss:{frame.epoch}:{outcome["stage"]}',
                            speech_max_age_ms=8000, voice_tone='thoughtful',
                            basis=outcome['basis'], training_label=False), frame, end)
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
        self.ubuntu_mvp_diagnostics = __import__('os').environ.get('AGENTE_TFT_UBUNTU_MVP') == '1'
        self.latest_hud_diagnostic = None
        from .combat_events import CombatEvents
        self.combat_events = CombatEvents()
        from .opponent_tracking import OpponentTracker
        self.opponent_tracker = OpponentTracker()
        self._latest_native_stage = None
        self.shadow_learning_recorder = None
        self.shadow_learning_sealed = None
        self.shadow_learning_error = None
        from .learning_capture import ShadowLearningRecorder
        self.shadow_learning_recorder = ShadowLearningRecorder(
            options.output,
            interval_ms=5000.0 if options.replay_review else 2000.0,
            max_frames=3600,
            max_bytes=2 * 1024**3,
            jpeg_quality=88,
        )
        profile = json.loads((Path(options.configs) / 'ui/board-hub-live-v1.json').read_text())
        self.hub_interval_ms = profile['sample_interval_ms']
        if type(self.hub_interval_ms) is not int or not 1000 <= self.hub_interval_ms < 2000:
            raise ValueError('Board cadence must fit the 2000 ms strategic freshness budget')
        self.board_reference_requested = threading.Event()
        self._terminal_hp_confirmations = 0
        self._terminal_hp_first_source_ms = None
        self.latest_replay_tip = None
        self.latest_decision_reason = None
        self._latest_strategy_state = None
        self._latest_visual_candidates = None
        self.decision_engine = None
        if options.board_hub_enabled:
            from .replay_decision import ReplayDecisionEngine
            preference_root = (Path(options.output).parent if Path(options.output).parent.name == 'sessions'
                               else Path(options.output))
            self.decision_engine = ReplayDecisionEngine(options.configs,
                preference_path=preference_root / 'coach-preferences.json')
            self.versions['replay_decision_policy'] = 'verified_third_copy_v1'
            self.versions['resource_engine'] = 'resource_budget_v1'
            self.versions['resource_engine_identity'] = self.decision_engine.resource_engine.identity
            self.versions['resource_engine_learned_policy'] = False
            self.versions['strategic_coach_scope'] = self.decision_engine.strategic_coach.catalog['scope']
            self.versions['strategic_ranker_loaded'] = self.decision_engine.strategic_coach.model is not None
            self.versions['strategic_vision_state'] = 'pending_verified_observer'
            self.versions['partial_state_advice'] = 'experimental_with_explicit_feedback'
            self.versions['replay_catalog_set'] = self.decision_engine.set_key
            self.versions['replay_catalog_version'] = self.decision_engine.catalog_version
            self.versions['decision_patch_basis'] = ('reported_replay_patch' if options.replay_review
                                                     else 'bundled_catalog_patch_lab')

    def feedback_tip(self, helpful: bool, decision_key: str | None = None) -> bool:
        """Player feedback changes only advice priorities, never visual labels."""
        if type(helpful) is not bool or not self.decision_engine:
            return False
        with self.lock:
            tip = copy.deepcopy(self.latest_replay_tip)
        if (not tip or tip.get('policy') != 'partial_state_live_v1'
                or (decision_key is not None and decision_key != tip.get('decision_key'))):
            return False
        accepted = self.decision_engine.live_advice.rate(
            tip.get('decision_key'), tip.get('family'), helpful)
        if accepted:
            self.store.emit('telemetry', dict(event='coach_player_feedback',
                frame_id=tip['frame_id'], source_ms=tip['source_ms'],
                decision_key=tip['decision_key'], family=tip['family'],
                helpful=helpful, source='explicit_player_feedback',
                visual_training_label=False, neural_weights_updated=False))
            self.counts['coach_feedback'] += 1
        return accepted

    def _source_frame_observed(self, frame):
        recorder = self.shadow_learning_recorder
        if recorder is not None:
            recorder.submit(frame)

    def finish(self):
        recorder = self.shadow_learning_recorder
        if recorder is not None and self.shadow_learning_sealed is None and self.shadow_learning_error is None:
            try:
                self.shadow_learning_sealed = recorder.close(
                    session_id=self.id,
                    source={**self.source_info,
                            'input_kind': ('recorded_replay_on_screen' if self.options.replay_review
                                           else 'live_match_on_screen')},
                    runtime_model_sha256=self.versions.get('unit_neural_model_sha256')
                        or self.versions.get('model_sha256'),
                )
                self.versions['shadow_learning_capture'] = self.shadow_learning_sealed
            except Exception as exc:
                # Learning capture failure must never invalidate the gameplay/session evidence.
                self.shadow_learning_error = str(exc)
                self.versions['shadow_learning_capture_error'] = self.shadow_learning_error
        result = super().finish()
        result['shadow_learning_capture'] = self.shadow_learning_sealed
        result['shadow_learning_capture_error'] = self.shadow_learning_error
        result['active_model_changed_during_session'] = False
        result['post_session_learning_eligible'] = bool(
            result.get('execution_complete')
            and self.shadow_learning_sealed
            and self.shadow_learning_sealed.get('ready_for_post_session_learning')
        )
        return result

    def request_board_reference(self):
        if not self.options.board_hub_enabled or self.done.is_set():
            raise ValueError('Inicie a revisão de replay antes de calibrar o tabuleiro')
        self.board_reference_requested.set()

    def submit_hub_frame(self, frame):
        if hub_due(getattr(self, '_last_hub_submission', None), frame, self.hub_interval_ms):
            self._last_hub_submission = dict(epoch=frame.epoch, source_ms=frame.pts_ms)
            self.hub_pending.put(frame)
            self.counts['hub_submitted'] += 1

    def _hub_loop(self):
        board_worker = None
        try:
            from .replay_coach import inventory_prompt
            from .model_update import active_bundle_for_model
            neural_bundle = active_bundle_for_model(self.options.model)
            overlays = (neural_bundle / 'configs/catalog' if neural_bundle else None)
            has_active_overlay = bool(overlays and any(
                (overlays / name).is_file() for name in
                ('active-unit-head-v1.json', 'active-unit-gallery-v1.json',
                 'active-unit-identity-v1.json', 'active-item-neural-v1.json')))
            use_remote_board = bool(self.core and not has_active_overlay)
            self.versions['board_hub_execution'] = ('wsl_core' if use_remote_board
                                                    else 'windows_local_approved_overlay' if has_active_overlay
                                                    else 'windows_local')
            if use_remote_board:
                from hm45_vm_client import RemoteBoardHub
                observer = RemoteBoardHub(self.core)
            else:
                from .board_hub_live import BoardHubLive
                from .board_worker import BoardWorker
                observer = BoardHubLive(self.options.configs, neural_root=neural_bundle)
                board_worker = BoardWorker(self.options.worker, self.options.configs,
                                           log=Path(self.options.output) / 'board-stderr.log',
                                           tesseract=self.options.tesseract)
            self.versions['board_hub_reference_sha256'] = observer.manifest['reference_sha256']
            self.versions['board_hub_set_key'] = observer.manifest['set_key']
            self.versions['board_hub_mode'] = ('replay_screen_candidate_only' if self.options.replay_review
                                               else 'live_screen_candidate_only')
            self.versions['board_hub_interval_ms'] = self.hub_interval_ms
            self.versions['board_reference_status'] = 'not_calibrated'
            if self.options.board_reference:
                with Image.open(self.options.board_reference) as reference:
                    reference = reference.convert('RGB')
                    reference_frame = SimpleNamespace(id=0, pts_ms=0, width=reference.width,
                        height=reference.height, rgb=reference.tobytes())
                if use_remote_board:
                    observer.observe(reference_frame, calibrate=True)
                else:
                    board_worker.observe(reference_frame, calibrate=True)
            while not self.cancel.is_set():
                try:
                    frame = self.hub_pending.get()
                except queue.Empty:
                    if self.producer_done.is_set():
                        break
                    continue
                started = time.perf_counter_ns()
                if (started - frame.due_ns) / 1e6 > 2000:
                    with self.lock:
                        self._latest_strategy_state = None
                        self._latest_visual_candidates = None
                    self.counts['hub_stale_input_dropped'] += 1
                    continue
                plan = reader_plan(frame, self.normalize_reader_input)
                reader_frame, normalize_ms = materialize_reader_frame(frame, plan)
                if reader_frame is None:
                    with self.lock:
                        self._latest_strategy_state = None
                        self._latest_visual_candidates = None
                    self.counts['hub_resolution_skipped'] += 1
                    continue
                calibrate = self.board_reference_requested.is_set()
                if calibrate:
                    self.board_reference_requested.clear()
                try:
                    if use_remote_board:
                        observed = observer.observe(reader_frame, calibrate=calibrate)
                    else:
                        board_read = board_worker.observe(reader_frame, calibrate)
                        observed = observer.observe(reader_frame, board_read, source_frame=frame)
                except (ValueError, RuntimeError) as exc:
                    if not calibrate:
                        raise
                    self.versions['board_reference_status'] = 'failed'
                    self.versions['board_reference_error'] = str(exc)
                    with self.lock:
                        self._latest_strategy_state = None
                        self._latest_visual_candidates = None
                    continue
                if calibrate:
                    self.versions['board_reference_sha256'] = hashlib.sha256(reader_frame.rgb).hexdigest()
                    self.versions['board_reference_frame_id'] = frame.id
                # The present observer does not produce this contract. Keep the
                # explicit boundary for a future calibrated identity observer;
                # candidate icons are never converted into verified units here.
                with self.lock:
                    state = observed['snapshot'].get('verified_state')
                    self._latest_strategy_state = (dict(state=copy.deepcopy(state), epoch=frame.epoch,
                        source_ms=frame.pts_ms, due_ns=frame.due_ns) if state else None)
                    candidates = observed['snapshot'].get('temporal_candidates')
                    self._latest_visual_candidates = (dict(candidates=copy.deepcopy(candidates),
                        epoch=frame.epoch, source_ms=frame.pts_ms, due_ns=frame.due_ns)
                        if candidates else None)
                self.versions['board_reference_status']=observed['snapshot'].get('board_reference_status')
                neural_items=observed['snapshot'].get('neural_items') or {}
                with self.lock:
                    stage_read = self._latest_native_stage
                stage_for_opponents = (stage_read[0] if stage_read and stage_read[1] == frame.epoch
                                       and stage_read[2] <= frame.pts_ms else None)
                opponent_state = self.opponent_tracker.update(
                    observed['snapshot'].get('opponent_panel_observation'),
                    epoch=frame.epoch, source_ms=frame.pts_ms, stage=stage_for_opponents)
                observed['snapshot']['opponents'] = opponent_state
                self.versions['opponent_tracking'] = opponent_state
                opponent_panel = observed['snapshot'].get('opponent_panel_observation')
                if isinstance(opponent_panel, dict) and opponent_panel.get('status') == 'raw_ocr':
                    self.store.emit('opponent-crop-observations', dict(
                        source_frame_id=opponent_panel.get('frame_id'),
                        source_ms=opponent_panel.get('source_ms'),
                        geometry_segment=frame.epoch,
                        crop_regions={
                            'scoreboard':[1690,170,175,635],
                            'hp_strip':[1830,180,26,605],
                            'enemy_name':[1215,77,95,22],
                            'self_overlay':[80,9,160,20],
                        },
                        screen_read=opponent_panel,
                        reconciled_candidates=opponent_state,
                        ground_truth=False, training_label=None,
                        model_prediction_used_as_label=False,
                        purpose='post_session_ocr_review'))
                self.versions['item_neural_active']=neural_items.get('active',False)
                self.versions['item_neural_model_sha256']=neural_items.get('model_sha256')
                visual_items = observed['snapshot'].get('item_visual_native') or {}
                self.versions['item_visual_native_active'] = visual_items.get('active', False)
                self.versions['item_visual_native_error'] = visual_items.get('error')
                neural_units = observed['snapshot'].get('neural_units') or {}
                self.versions['unit_neural_active'] = neural_units.get('active', False)
                self.versions['unit_neural_model_sha256'] = neural_units.get('model_sha256')
                self.versions['visual_readiness'] = observed['snapshot'].get('visual_readiness')
                self.versions['temporal_candidates'] = observed['snapshot'].get('temporal_candidates')
                end = time.perf_counter_ns()
                regions = regions_to_source(observed['regions'], frame, plan)
                record = dict(frame_id=frame.id, source_ms=frame.pts_ms, regions=regions,
                              snapshot=observed['snapshot'], image_size=[frame.width, frame.height],
                              reader_input_transform=plan, ground_truth=False,
                              source_to_hub_ms=(end-frame.due_ns)/1e6,
                              hub_processing_ms=(end-started)/1e6,
                              hub_normalize_ms=normalize_ms,
                              scheduling='independent_of_hud_ocr_latest_frame',
                              board_reference_status=self.versions.get('board_reference_status'),
                              game_state_updated=False)
                with self.lock:
                    for reg in regions:
                        self.coverage[(reg['id'], reg['status'])] += 1
                    self.traces.append(dict(kind='hub', frame_id=frame.id,
                        source_due_ns=frame.due_ns, ready_ns=end,
                        total_ms=record['source_to_hub_ms'],
                        processing_ms=record['hub_processing_ms'],
                        vm_transport=observed.get('vm_transport')))
                self.store.emit('board-hub-observations', record)
                self.hub_results.put(dict(frame=frame, record=record, ready_ns=end))
                self.counts['hub_results'] += 1
                self._publish_coach(inventory_prompt(observed['snapshot']),frame,end)
        except Exception as exc:
            self.error = str(exc)
            self.stop()
        finally:
            if board_worker:
                board_worker.close()
