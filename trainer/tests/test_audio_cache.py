import sqlite3
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from companion_service.app import create_app
from companion_service.audio_cache import AudioCache
from hm.voice_api import SpeechError
from hm.voice_validation import mock_client


class AudioCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name)/'voice.sqlite3'

    def tearDown(self):
        self.temp.cleanup()

    def session(self, app):
        token = app.post('/v1/session', json={'installation_id':str(uuid.uuid4())}).json()['token']
        return {'Authorization':'Bearer '+token}

    def say(self, app, headers, text='Olá'):
        return app.post('/v1/voice', json={'text':text}, headers=headers)

    def test_restart_and_another_device_reuse_audio_with_exhausted_budget(self):
        speech = mock_client()
        app = TestClient(create_app(client=speech, db_path=self.db, daily_characters=3))
        first = self.say(app,self.session(app))
        self.assertEqual(first.status_code,200)
        self.assertEqual(first.headers['x-tft-voice-cache'],'miss')
        restarted = mock_client()
        with patch.object(restarted,'synthesize',side_effect=AssertionError('Must not call provider')):
            app = TestClient(create_app(client=restarted,db_path=self.db,daily_characters=3))
            headers = self.session(app)
            second = self.say(app,headers)
            self.assertEqual(second.status_code,200)
            self.assertEqual(second.content,first.content)
            self.assertEqual(second.headers['x-tft-voice-cache'],'hit')
            self.assertEqual(self.say(app,headers,'Novo texto').status_code,429)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT sum(characters) FROM usage').fetchone()[0],3)
        stats = app.get('/health').json()['audio_cache']
        self.assertEqual((stats['entries'],stats['hits'],stats['characters_reused']),(1,1,3))

    def test_cached_audio_still_requires_session_and_rate_limits(self):
        app = TestClient(create_app(client=mock_client(),db_path=self.db))
        headers = self.session(app)
        self.assertEqual(self.say(app,headers).status_code,200)
        self.assertEqual(self.say(app,{}).status_code,401)
        self.assertEqual(self.say(app,{'Authorization':'Bearer invalid'}).status_code,401)
        for _ in range(5):
            self.assertEqual(self.say(app,headers).status_code,200)
        self.assertEqual(self.say(app,headers).status_code,429)
        self.assertEqual(app.get('/health').json()['audio_cache']['hits'],5)

    def test_new_voice_and_model_do_not_reuse_old_audio(self):
        first = mock_client()
        app = TestClient(create_app(client=first,db_path=self.db))
        self.say(app,self.session(app))
        changed = mock_client()
        changed.voice_id = 'other-voice'
        with patch.object(changed,'synthesize',wraps=changed.synthesize) as synthesis:
            app = TestClient(create_app(client=changed,db_path=self.db))
            self.assertEqual(self.say(app,self.session(app)).headers['x-tft-voice-cache'],'miss')
            self.assertEqual(synthesis.call_count,1)
        with patch('hm.voice_api.MODEL','new-model'):
            app = TestClient(create_app(client=mock_client(),db_path=self.db))
            self.assertEqual(self.say(app,self.session(app)).headers['x-tft-voice-cache'],'miss')

    def test_failed_provider_is_not_cached(self):
        speech = mock_client()
        with patch.object(speech,'synthesize',side_effect=SpeechError('Provider unavailable')):
            app = TestClient(create_app(client=speech,db_path=self.db))
            self.assertEqual(self.say(app,self.session(app)).status_code,502)
            self.assertEqual(app.get('/health').json()['audio_cache']['entries'],0)
        app = TestClient(create_app(client=mock_client(),db_path=self.db))
        self.assertEqual(self.say(app,self.session(app)).headers['x-tft-voice-cache'],'miss')

    def test_bounds_eviction_corruption_and_expiry(self):
        cache = AudioCache(self.db,max_bytes=8,max_entries=2,ttl_seconds=30)
        cache.put('a',b'aa');cache.put('b',b'bbbb')
        cache.get('a')
        cache.put('c',b'cccc')
        self.assertIsNone(cache.get('b'))
        self.assertEqual(cache.get('a'),b'aa')
        self.assertLessEqual(cache.stats()['audio_bytes'],8)
        self.assertFalse(cache.put('huge',b'x'*10))
        self.assertFalse(cache.put('invalid',b'x'))
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE audio SET pcm=? WHERE key='a'",(b'zz',))
            db.execute("UPDATE audio SET created=? WHERE key='c'",(time.time()-31,))
        self.assertIsNone(cache.get('a'))
        self.assertIsNone(cache.get('c'))

    def test_exact_text_and_full_identity_determine_cache_key(self):
        identity = mock_client().cache_identity()
        key = AudioCache.key(identity,'Suba para o nível quatro.')
        self.assertNotEqual(key,AudioCache.key(identity,'Suba para o nível cinco.'))
        for field in ('voice_id','model','language','output_format','revision'):
            self.assertNotEqual(key,AudioCache.key(dict(identity,**{field:'changed'}),'Suba para o nível quatro.'))

    def test_cache_storage_failure_does_not_spend_provider_credits(self):
        speech = mock_client()
        app = TestClient(create_app(client=speech,db_path=self.db))
        with patch('companion_service.app.AudioCache.get',side_effect=sqlite3.OperationalError('storage error')):
            with patch.object(speech,'synthesize',side_effect=AssertionError('Must not call provider')):
                self.assertEqual(self.say(app,self.session(app)).status_code,503)
