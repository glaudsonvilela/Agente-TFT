"""A1.4: durable laboratory profile registry. No runtime activation or training.

One SQLite transaction stores a snapshot and its audit event. Blockers are
append-only and keyed by reader content, not by a display name. This is a
single-user local-disk store, not an authenticated multi-tenant service.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

APP_ID = 0x54465452
SCHEMA = 1
MAX_BYTES = 8 * 1024 * 1024
MAX_REVIEWS = 2000
ZERO = '0' * 64


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def hash_value(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def token(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch('[a-z0-9_.-]{1,100}', value) is not None


def profile_key(identity: dict) -> str:
    require(set(identity) == {'reader', 'executable_sha256', 'config_sha256'}, 'invalid reader identity')
    require(token(identity['reader']) and all(hash_value(identity[k]) for k in
            ('executable_sha256', 'config_sha256')), 'invalid reader content hashes')
    return digest(identity)


def context_key(context: dict) -> str:
    require(set(context) == {'mode', 'subsystem', 'field', 'recording_sha256'}, 'invalid context')
    require(context['mode'] == 'offline_replay' and token(context['subsystem']) and token(context['field'])
            and hash_value(context['recording_sha256']), 'invalid replay context')
    return digest(context)


def empty_state() -> dict:
    return dict(schema_version=SCHEMA, profiles={}, contexts={}, reviews={})


def check_state(state: dict) -> None:
    require(set(state) == {'schema_version', 'profiles', 'contexts', 'reviews'}
            and state['schema_version'] == SCHEMA, 'unsupported snapshot schema')
    require(all(isinstance(state[k], dict) for k in ('profiles', 'contexts', 'reviews')), 'invalid snapshot maps')
    require(len(state['reviews']) <= MAX_REVIEWS, 'registry review budget exceeded')
    for key, p in state['profiles'].items():
        require(profile_key(p['identity']) == key and isinstance(p['blocks'], dict), 'profile identity changed')
        for reason, sources in p['blocks'].items():
            require(token(reason) and isinstance(sources, list) and sources == sorted(set(sources))
                    and all(s in state['reviews'] and state['reviews'][s]['candidate_key'] == key
                            and reason in state['reviews'][s]['blockers'] for s in sources), 'invalid blocker provenance')
    for key, binding in state['contexts'].items():
        require(context_key(binding['context']) == key and binding['baseline_key'] in state['profiles'],
                'invalid baseline reference binding')
    for key, review in state['reviews'].items():
        require(digest(review) == key and review['baseline_key'] in state['profiles']
                and review['candidate_key'] in state['profiles']
                and review['context_key'] in state['contexts'], 'review identity changed')


class Registry:
    """Content identities + sticky blockers + restart-safe baseline references.

    Importing evidence never selects a production profile. There is deliberately
    no approve/clear/activate API in this revision. Unknown readers fail closed.
    """
    def __init__(self, path: Path):
        path = Path(path).absolute()
        require(path.parent.is_dir() and not path.is_symlink(), 'registry parent missing or file is symlink')
        for suffix in ('-journal', '-wal', '-shm'):
            require(not Path(str(path) + suffix).is_symlink(), 'registry sidecar is symlink')
        self.path = path
        self.db = sqlite3.connect(str(path), timeout=5, isolation_level=None)
        try:
            self.db.execute('PRAGMA busy_timeout=5000')
            self.db.execute('PRAGMA synchronous=FULL')
            with self._transaction():
                app = self.db.execute('PRAGMA application_id').fetchone()[0]
                version = self.db.execute('PRAGMA user_version').fetchone()[0]
                names = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not names:
                    require(app == 0 and version == 0, 'unrecognized empty registry')
                    self.db.execute('CREATE TABLE snapshot (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, body TEXT NOT NULL, tip TEXT NOT NULL)')
                    self.db.execute('CREATE TABLE events (revision INTEGER PRIMARY KEY, body TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL)')
                    self.db.execute('INSERT INTO snapshot VALUES(1,0,?,?)', (canonical(empty_state()), ZERO))
                    self.db.execute(f'PRAGMA application_id={APP_ID}')
                    self.db.execute(f'PRAGMA user_version={SCHEMA}')
                else:
                    require(app == APP_ID and version == SCHEMA and names == {'snapshot', 'events'},
                            'not a compatible perception registry; no automatic reset')
                self._read()
        except BaseException:
            self.db.close()
            raise

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextmanager
    def _transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise

    def _read(self) -> tuple[int, dict, str]:
        row = self.db.execute('SELECT revision,body,tip FROM snapshot WHERE id=1').fetchone()
        require(row is not None and len(row[1].encode()) <= MAX_BYTES, 'missing/excessive registry snapshot')
        revision, body, tip = row
        state = json.loads(body)
        require(body == canonical(state), 'noncanonical registry snapshot')
        check_state(state)
        previous, last, final_state_hash = ZERO, 0, None
        rows = self.db.execute('SELECT revision,body,previous_hash,event_hash FROM events ORDER BY revision')
        for seq, text, prev, event_hash in rows:
            require(seq == last + 1 and seq <= MAX_REVIEWS, 'invalid event sequence')
            event = json.loads(text)
            require(text == canonical(event) and prev == previous and event['revision'] == seq,
                    'invalid event chain')
            require(digest(dict(previous_hash=prev, event=event)) == event_hash, 'event checksum mismatch')
            final_state_hash = event['snapshot_sha256']
            previous, last = event_hash, seq
        require(revision == last and tip == previous, 'snapshot/event revision mismatch')
        require((revision == 0 and state == empty_state()) or final_state_hash == digest(state),
                'snapshot checksum mismatch; no automatic reset')
        return revision, state, tip

    def _persist(self, revision: int, state: dict, tip: str, evidence_id: str) -> None:
        check_state(state)
        body = canonical(state)
        require(len(body.encode()) <= MAX_BYTES, 'registry snapshot exceeds budget')
        event = dict(revision=revision+1, kind='import_review', evidence_id=evidence_id,
                     snapshot_sha256=digest(state))
        event_hash = digest(dict(previous_hash=tip, event=event))
        self.db.execute('INSERT INTO events VALUES(?,?,?,?)',
                        (revision+1, canonical(event), tip, event_hash))
        self.db.execute('UPDATE snapshot SET revision=?,body=?,tip=? WHERE id=1',
                        (revision+1, body, event_hash))

    def import_review(self, context: dict, baseline: dict, candidate: dict, payload: dict,
                      blockers: list[str], expected_revision: int | None = None) -> dict:
        """Internal control-plane API: caller must verify evidence before import."""
        # Detach caller-owned objects before hashing or entering the transaction.
        context, baseline, candidate, payload, blockers = json.loads(canonical(
            [context, baseline, candidate, payload, blockers]))
        ck, bk, pk = context_key(context), profile_key(baseline), profile_key(candidate)
        require(bk != pk, 'baseline and candidate are identical')
        require(isinstance(payload, dict) and len(canonical(payload).encode()) <= 1024*1024, 'excessive review payload')
        require(isinstance(blockers, list) and len(blockers) <= 32 and all(token(r) for r in blockers), 'invalid blockers')
        require(expected_revision is None or type(expected_revision) is int and expected_revision >= 0,
                'invalid expected revision')
        review = dict(context_key=ck, baseline_key=bk, candidate_key=pk,
                      blockers=sorted(set(blockers)), evidence=payload)
        eid = digest(review)
        with self._transaction():
            rev, state, tip = self._read()
            if eid in state['reviews']:
                return self._receipt(state, rev, eid, pk, False)
            require(expected_revision is None or expected_revision == rev, 'stale registry revision; reload before retry')
            require(len(state['reviews']) < MAX_REVIEWS, 'review budget exceeded')
            for key, identity in ((bk, baseline), (pk, candidate)):
                if key in state['profiles']:
                    require(state['profiles'][key]['identity'] == identity, 'profile hash collision')
                else:
                    state['profiles'][key] = dict(identity=identity, blocks={})
            binding = state['contexts'].get(ck)
            require(binding is None or binding['baseline_key'] == bk, 'baseline reference replacement is not permitted')
            state['contexts'].setdefault(ck, dict(context=context, baseline_key=bk))
            state['reviews'][eid] = review
            for reason in review['blockers']:
                sources = state['profiles'][pk]['blocks'].setdefault(reason, [])
                sources.append(eid)
                sources.sort()
            self._persist(rev, state, tip, eid)
            return self._receipt(state, rev+1, eid, pk, True)

    @staticmethod
    def _receipt(state: dict, revision: int, eid: str, key: str, changed: bool) -> dict:
        return dict(revision=revision, changed=changed, evidence_id=eid, candidate_key=key,
                    candidate_state='quarantined' if state['profiles'][key]['blocks'] else 'shadow_only',
                    blocker_reasons=sorted(state['profiles'][key]['blocks']),
                    baseline_reference_retained=True, active_profile_written=False,
                    game_state_updated=False, model_trained=False)

    def inspect(self) -> dict:
        with self._transaction():
            revision, state, tip = self._read()
            return dict(revision=revision, snapshot=state, event_tip=tip)

    def permission(self, identity: dict) -> dict:
        key = profile_key(identity)
        state = self.inspect()['snapshot']
        p = state['profiles'].get(key)
        reasons = sorted(p['blocks']) if p else ['unregistered_reader']
        return dict(profile_key=key, shadow_evaluation_allowed=p is not None,
                    activation_allowed=False, reasons=reasons+['runtime_activation_not_implemented'],
                    status='unregistered' if p is None else 'quarantined' if p['blocks'] else 'shadow_only')
