"""A1.5 control plane: visibility-aware, bounded diagnostic work reservations.

No worker, OCR, profile activation, value correction or training. Source adapters
must verify frame provenance before calling assess; numeric predictions never
enter scheduling. A14 is consulted, not migrated or updated.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3

from training.perception_registry import Registry, canonical, context_key, digest, hash_value, profile_key, require

APP_ID = 0x54465443
MAX_ITEMS = 2000
MAX_BYTES = 8 * 1024 * 1024
READS = {'accepted', 'negative_display', 'ocr_uncertain', 'ocr_conflict',
         'badge_not_found', 'badge_ambiguous', 'search_budget_exceeded', 'read_error'}


@dataclass(frozen=True)
class CoordinatorPolicy:
    version: str = 'a15_diagnostic_coordinator_v1'
    block_samples: int = 8
    min_block_span_ms: int = 1000
    max_sample_gap_ms: int = 750
    bad_blocks: int = 3
    recover_blocks: int = 2
    max_unreadable_rate: float = .20
    cooldown_ms: int = 60_000
    budget_period_ms: int = 3_600_000
    max_intents_per_period: int = 3
    max_frames_per_period: int = 192
    max_outstanding: int = 1

    def validate(self) -> None:
        require(self.version == 'a15_diagnostic_coordinator_v1', 'unsupported policy version')
        for name, lo, hi in [('block_samples', 4, 32), ('min_block_span_ms', 250, 5000),
                            ('max_sample_gap_ms', 250, 1500), ('bad_blocks', 2, 8),
                            ('recover_blocks', 1, 8), ('cooldown_ms', 1000, 3_600_000),
                            ('budget_period_ms', 1000, 86_400_000), ('max_intents_per_period', 1, 100),
                            ('max_frames_per_period', 1, 10000), ('max_outstanding', 1, 8)]:
            n = getattr(self, name)
            require(type(n) is int and lo <= n <= hi, 'invalid coordinator policy: '+name)
        require(type(self.max_unreadable_rate) in (float, int)
                and 0 <= self.max_unreadable_rate < 1, 'invalid unreadable threshold')
        require(self.cooldown_ms <= self.budget_period_ms, 'cooldown exceeds budget period')


def validate_samples(samples: list[dict]) -> None:
    require(isinstance(samples, list) and 1 <= len(samples) <= 128, 'require 1..128 samples')
    last = -1
    for s in samples:
        require(isinstance(s, dict) and set(s) == {'timestamp_ms', 'image_sha256', 'status', 'marker'}, 'invalid sample schema')
        t = s['timestamp_ms']
        require(type(t) is int and last < t <= 86_400_000, 'duplicate/out-of-order sample time')
        require(hash_value(s['image_sha256']) and s['status'] in READS, 'invalid sample identity/status')
        marker = s['marker']
        require(marker in {'unique', 'missing', 'ambiguous', 'unknown'}, 'invalid marker state')
        required = {'badge_not_found':'missing', 'badge_ambiguous':'ambiguous',
                    'search_budget_exceeded':'unknown'}
        if s['status'] in required:
            require(marker == required[s['status']], 'marker/status contradiction')
        elif s['status'] != 'read_error':
            require(marker == 'unique', 'numeric read without unique marker')
        last = t


def scheduling_signal(samples: list[dict], policy: CoordinatorPolicy) -> dict:
    """Non-overlapping visible blocks, not overlapping drift votes or accuracy.

    A missing badge is UNRESOLVED visibility, not proven occlusion or UI drift.
    Identical recorded image hashes cannot advance a bad-block counter. Different
    full-frame hashes do not prove independent HP pixels. This is a scheduling
    signal from verified status records, not a fabricated A1.1 native snapshot.
    """
    policy.validate(); validate_samples(samples)
    block, seen, windows = [], set(), []
    bad, good, degraded, last = 0, 0, False, None
    state, repeated, gaps = 'warming_up', 0, 0
    for s in samples:
        at = s['timestamp_ms']
        if last is not None and at-last > policy.max_sample_gap_ms:
            block, bad, good, degraded, state = [], 0, 0, False, 'warming_up'
            gaps += 1
        last = at
        if s['status'] == 'read_error' or s['marker'] != 'unique':
            block, bad, good, degraded = [], 0, 0, False
            state = 'operational_error' if s['status'] == 'read_error' else 'visibility_unresolved'
            seen.add(s['image_sha256'])
            continue
        if s['image_sha256'] in seen:
            block, bad, good, degraded = [], 0, 0, False
            repeated += 1; state = 'repeated_image'
            continue
        seen.add(s['image_sha256']); block.append(s)
        if len(block) < policy.block_samples:
            if state not in {'healthy', 'degraded'}:
                state = 'warming_up'
            continue
        span = block[-1]['timestamp_ms']-block[0]['timestamp_ms']
        unreadable = sum(r['status'] not in {'accepted', 'negative_display'} for r in block)
        rate = unreadable/len(block)
        bad_block = span >= policy.min_block_span_ms and rate > policy.max_unreadable_rate
        if span < policy.min_block_span_ms:
            bad, good, degraded, state = 0, 0, False, 'warming_up'
        elif bad_block:
            bad += 1; good = 0
            degraded = degraded or bad >= policy.bad_blocks
            state = 'degraded' if degraded else 'suspect'
        else:
            good += 1; bad = 0
            if good >= policy.recover_blocks:
                degraded = False
            state = 'degraded' if degraded else 'healthy'
        windows.append(dict(first_ms=block[0]['timestamp_ms'], last_ms=block[-1]['timestamp_ms'],
                            samples=len(block), unreadable=unreadable, bad_block=bad_block, state=state))
        block = []
    return dict(state=state, samples=len(samples), evaluated_blocks=len(windows),
                consecutive_bad_blocks=bad, consecutive_good_blocks=good, pending_samples=len(block),
                repeated_unique_marker_images=repeated, gap_resets=gaps, blocks=windows,
                note='operational scheduling signal; missing marker cause unresolved; not accuracy')


class Coordinator:
    """Durable idempotent reservations; intentionally no dispatch/activation API.

    Separate local SQLite file; same transaction seals decision, clock and cost
    reservation. A future worker must recheck source hashes, registry and budget.
    finish_intent is an internal acknowledgement, not proof a worker ran.
    """
    def __init__(self, registry: Path, database: Path, policy: CoordinatorPolicy | None = None):
        self.policy = policy or CoordinatorPolicy(); self.policy.validate()
        registry, database = Path(registry).absolute(), Path(database).absolute()
        require(registry.is_file() and registry.stat().st_size > 0, 'A14 registry missing; register evidence first')
        require(database.parent.is_dir() and not database.is_symlink(), 'coordinator parent missing or symlink')
        require(database.resolve() != registry.resolve(), 'coordinator must not replace A14 registry')
        if database.exists():
            require(not database.samefile(registry), 'coordinator aliases A14 registry')
        for suffix in ('-journal', '-wal', '-shm'):
            require(not Path(str(database)+suffix).is_symlink(), 'coordinator sidecar is symlink')
        self.registry = Registry(registry)
        try:
            self.db = sqlite3.connect(str(database), timeout=5, isolation_level=None)
            self.db.execute('PRAGMA synchronous=FULL')
            with self.transaction():
                tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                app = self.db.execute('PRAGMA application_id').fetchone()[0]
                version = self.db.execute('PRAGMA user_version').fetchone()[0]
                if not tables:
                    require(app == 0 and version == 0, 'unrecognized empty coordinator')
                    self.db.execute('CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL, checksum TEXT NOT NULL)')
                    state = dict(schema_version=1, policy=asdict(self.policy), revision=0,
                                 last_clock_ms=0, decisions={}, intents={})
                    self.db.execute('INSERT INTO state VALUES(1,?,?)', (canonical(state), digest(state)))
                    self.db.execute(f'PRAGMA application_id={APP_ID}')
                    self.db.execute('PRAGMA user_version=1')
                require((not tables or tables == {'state'}) and
                        self.db.execute('PRAGMA application_id').fetchone()[0] == APP_ID and
                        self.db.execute('PRAGMA user_version').fetchone()[0] == 1,
                        'foreign/incompatible coordinator; no reset')
                self._read()
        except BaseException:
            if hasattr(self, 'db'): self.db.close()
            self.registry.close()
            raise

    def __enter__(self): return self
    def __exit__(self, *_): self.db.close(); self.registry.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise

    def _read(self) -> dict:
        row = self.db.execute('SELECT body,checksum FROM state WHERE id=1').fetchone()
        require(row is not None and len(row[0].encode()) <= MAX_BYTES, 'invalid coordinator snapshot size')
        state = json.loads(row[0])
        require(row[0] == canonical(state) and digest(state) == row[1], 'coordinator checksum mismatch')
        require(set(state) == {'schema_version','policy','revision','last_clock_ms','decisions','intents'}
                and state['schema_version'] == 1 and state['policy'] == asdict(self.policy), 'policy/schema changed; no silent reset')
        require(type(state['revision']) is int and state['revision'] >= 0 and
                type(state['last_clock_ms']) is int and state['last_clock_ms'] >= 0, 'invalid coordinator clock/revision')
        for name in ('decisions','intents'):
            require(isinstance(state[name], dict) and len(state[name]) <= MAX_ITEMS, 'coordinator item budget exceeded')
        for key, task in state['intents'].items():
            require(key in state['decisions'] and task['status'] in {'reserved','completed','failed'}, 'orphan/invalid intent')
        return state

    def _save(self, state: dict) -> None:
        body = canonical(state)
        require(len(body.encode()) <= MAX_BYTES, 'coordinator byte budget exceeded')
        self.db.execute('UPDATE state SET body=?,checksum=? WHERE id=1', (body, digest(state)))

    def inspect(self) -> dict:
        with self.transaction(): return self._read()

    def assess(self, context: dict, baseline: dict, candidate: dict, samples: list[dict],
               now_ms: int, completed_evidence_id: str | None = None) -> dict:
        """Internal verified-source API. No JSON task/command execution.

        completed_evidence_id must refer to this pair/context's A14 review. The
        HP5 adapter additionally verifies the exact report and manifests. Filenames,
        display names and wall time are deliberately absent from request identity.
        """
        context, baseline, candidate, samples = json.loads(canonical([context, baseline, candidate, samples]))
        ck, bk, pk = context_key(context), profile_key(baseline), profile_key(candidate)
        require(bk != pk, 'same baseline/candidate')
        require(type(now_ms) is int and 0 <= now_ms <= 9_000_000_000_000_000, 'invalid scheduling clock')
        signal = scheduling_signal(samples, self.policy)
        pair = digest(dict(context=ck, baseline=bk, candidate=pk))
        frames = [[r['timestamp_ms'],r['image_sha256']] for r in samples]
        key = digest(dict(pair=pair, frames=frames))
        input_hash = digest(samples)
        with self.transaction():
            state = self._read()
            require(now_ms >= state['last_clock_ms'], 'scheduling clock moved backwards; no budget reset')
            current = self.registry.inspect(); snapshot = current['snapshot']
            binding = snapshot['contexts'].get(ck)
            require(binding is not None and binding['baseline_key'] == bk, 'unregistered context or different baseline')
            profile = snapshot['profiles'].get(pk)
            blockers = sorted(profile['blocks']) if profile else ['unregistered_reader']
            if completed_evidence_id is not None:
                review = snapshot['reviews'].get(completed_evidence_id)
                require(review is not None and (review['context_key'],review['baseline_key'],review['candidate_key']) == (ck,bk,pk),
                        'completed evidence not registered for this pair/context')
            if key in state['decisions']:
                old = state['decisions'][key]
                require(old['input_hash'] == input_hash, 'same source frames changed status evidence')
                return dict(decision=old, changed=False, intent_created=False, decision_reused=True,
                            registry_revision=current['revision'], current_blockers=blockers,
                            activation_allowed=False, ledger_revision=state['revision'])
            require(len(state['decisions']) < MAX_ITEMS, 'coordinator decision budget exceeded')
            if completed_evidence_id is not None:
                action = 'skip_already_evaluated'
            elif profile is None:
                action = 'block_unregistered_candidate'
            elif signal['state'] == 'operational_error':
                action = 'diagnose_backend_not_calibration'
            elif signal['state'] == 'visibility_unresolved':
                action = 'wait_for_visibility'
            elif signal['state'] != 'degraded':
                action = 'observe_without_recalibration'
            elif blockers:
                action = 'block_automatic_retry_quarantined_candidate'
            else:
                action = self._reserve_check(state, ck, pair, frames, now_ms)
            decision = dict(request_id=key, input_hash=input_hash, pair_key=pair, context_key=ck,
                candidate_key=pk, source_frames=frames, signal=signal, action=action,
                completed_evidence_id=completed_evidence_id, registry_revision=current['revision'],
                registry_event_tip=current['event_tip'], candidate_blockers=blockers,
                shadow_permission_registered=profile is not None, activation_allowed=False,
                cost_frames=len(frames), worker_executed=False)
            state['decisions'][key] = decision
            reserved = action == 'reserve_shadow_intent'
            if reserved:
                state['intents'][key] = dict(context_key=ck, pair_key=pair, source_frames=frames,
                    reserved_at_ms=now_ms, frames=len(frames), status='reserved')
            state['last_clock_ms']=now_ms; state['revision']+=1
            self._save(state)
            return dict(decision=decision, changed=True, intent_created=reserved, decision_reused=False,
                        registry_revision=current['revision'], current_blockers=blockers,
                        activation_allowed=False, ledger_revision=state['revision'])

    def _reserve_check(self, state: dict, context: str, pair: str, frames: list, now: int) -> str:
        tasks = list(state['intents'].values())
        requested = {tuple(f) for f in frames}
        if any(t['pair_key'] == pair and requested.intersection(map(tuple,t['source_frames'])) for t in tasks):
            return 'skip_overlapping_reserved_evidence'
        scoped = [t for t in tasks if t['context_key'] == context]
        if sum(t['status']=='reserved' for t in scoped) >= self.policy.max_outstanding:
            return 'limit_outstanding_work'
        if any(t['pair_key']==pair and now-t['reserved_at_ms'] < self.policy.cooldown_ms for t in tasks):
            return 'cooldown'
        recent = [t for t in scoped if now-t['reserved_at_ms'] < self.policy.budget_period_ms]
        if len(recent) >= self.policy.max_intents_per_period:
            return 'limit_intent_budget'
        if sum(t['frames'] for t in recent)+len(frames) > self.policy.max_frames_per_period:
            return 'limit_frame_budget'
        return 'reserve_shadow_intent'

    def finish_intent(self, key: str, result: str, now_ms: int) -> bool:
        require(hash_value(key) and result in {'completed','failed'}, 'invalid intent acknowledgement')
        require(type(now_ms) is int and now_ms >= 0, 'invalid acknowledgement clock')
        with self.transaction():
            state = self._read(); require(now_ms >= state['last_clock_ms'], 'clock moved backwards')
            task = state['intents'].get(key); require(task is not None, 'unknown intent')
            if task['status'] != 'reserved':
                require(task['status'] == result, 'conflicting acknowledgement'); return False
            task['status']=result; task['finished_at_ms']=now_ms
            state['last_clock_ms']=now_ms; state['revision']+=1
            self._save(state); return True
