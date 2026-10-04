"""Bounded, persistent PCM cache. Text and credentials are never stored as metadata."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time

MAX_AUDIO = 2 * 1024 * 1024


class AudioCache:
    def __init__(self, path, *, max_bytes=64 * 1024 * 1024, max_entries=512,
                 ttl_seconds=30 * 86400):
        self.path = str(path)
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('PRAGMA auto_vacuum=INCREMENTAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS audio(
                    key TEXT PRIMARY KEY, pcm BLOB NOT NULL, checksum TEXT NOT NULL,
                    created REAL NOT NULL, used REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS audio_used ON audio(used);
                CREATE TABLE IF NOT EXISTS savings(
                    id INTEGER PRIMARY KEY CHECK(id=1), hits INTEGER, characters INTEGER);
                INSERT OR IGNORE INTO savings VALUES(1,0,0);
            ''')
            self._prune(db)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def key(identity, text):
        # Exact text preserves punctuation, numbers and pronunciation cues.
        raw = json.dumps([identity, text], ensure_ascii=False, sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()

    def _prune(self, db, incoming=0, extra_entries=0):
        db.execute('DELETE FROM audio WHERE created<?', (time.time()-self.ttl_seconds,))
        count, size = db.execute('SELECT count(*),coalesce(sum(length(pcm)),0) FROM audio').fetchone()
        while count and (count+extra_entries > self.max_entries or size+incoming > self.max_bytes):
            key, length = db.execute('SELECT key,length(pcm) FROM audio ORDER BY used,key LIMIT 1').fetchone()
            db.execute('DELETE FROM audio WHERE key=?', (key,))
            count -= 1
            size -= length

    def get(self, key):
        with self.db() as db:
            row = db.execute('SELECT pcm,checksum,created FROM audio WHERE key=?', (key,)).fetchone()
            if row is None:
                return None
            pcm, checksum, created = row
            if (created < time.time()-self.ttl_seconds or not pcm or len(pcm)%2
                    or len(pcm)>MAX_AUDIO or hashlib.sha256(pcm).hexdigest()!=checksum):
                db.execute('DELETE FROM audio WHERE key=?', (key,))
                return None
            db.execute('UPDATE audio SET used=? WHERE key=?', (time.time(), key))
            return pcm

    def put(self, key, pcm):
        if not pcm or len(pcm)%2 or len(pcm)>min(MAX_AUDIO,self.max_bytes) or self.max_entries<1:
            return False
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM audio WHERE key=?', (key,))
            self._prune(db, incoming=len(pcm), extra_entries=1)
            now = time.time()
            db.execute('INSERT INTO audio VALUES(?,?,?,?,?)',
                       (key, pcm, hashlib.sha256(pcm).hexdigest(), now, now))
        with self.db() as db:
            db.execute('PRAGMA incremental_vacuum(256)')
        return True

    def record_hit(self, characters):
        with self.db() as db:
            db.execute('UPDATE savings SET hits=hits+1,characters=characters+? WHERE id=1', (characters,))

    def stats(self):
        with self.db() as db:
            count, size = db.execute('SELECT count(*),coalesce(sum(length(pcm)),0) FROM audio').fetchone()
            hits, characters = db.execute('SELECT hits,characters FROM savings WHERE id=1').fetchone()
        return dict(entries=count, audio_bytes=size, max_audio_bytes=self.max_bytes,
                    hits=hits, characters_reused=characters)
