import tempfile
import unittest
import uuid
from pathlib import Path
from fastapi.testclient import TestClient
from companion_service.app import create_app
from hm.voice_validation import mock_client

class CompanionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'voice.sqlite3'
        self.client=TestClient(create_app(client=mock_client(),db_path=self.path,daily_characters=30))
    def tearDown(self):self.temp.cleanup()
    def session(self,identity=None):
        return self.client.post('/v1/session',json={'installation_id':identity or str(uuid.uuid4())}).json()['token']
    def test_requires_session_and_returns_only_audio(self):
        self.assertEqual(self.client.post('/v1/voice',json={'text':'Olá'}).status_code,401)
        token=self.session()
        response=self.client.post('/v1/voice',json={'text':'Olá'},headers={'Authorization':'Bearer '+token})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['content-type'],'audio/pcm')
        self.assertEqual(len(response.content),4410)
        self.assertFalse(self.client.get('/health').json()['riot_integration'])
    def test_budget_survives_restart_and_new_device(self):
        token=self.session()
        request=lambda t:self.client.post('/v1/voice',json={'text':'x'*20},headers={'Authorization':'Bearer '+t})
        self.assertEqual(request(token).status_code,200)
        self.client=TestClient(create_app(client=mock_client(),db_path=self.path,daily_characters=30))
        self.assertEqual(request(self.session()).status_code,429)
    def test_malformed_request_and_registration_limit(self):
        self.assertEqual(self.client.post('/v1/session',json={'installation_id':'bad'}).status_code,422)
        self.assertEqual(self.client.post('/v1/voice',json={'text':'x'*501}).status_code,422)
        for _ in range(20):self.session()
        self.assertEqual(self.client.post('/v1/session',json={'installation_id':str(uuid.uuid4())}).status_code,429)

    def test_profile_filter_and_cache_are_scoped_to_patch(self):
        import time
        class Provider:
            calls=0
            def fetch(self,nickname,region,**query):
                self.calls+=1
                return dict(nickname=nickname,region=region,source='authorized-test-fixture',fetched_at=time.time(),matches=[
                    dict(match_id='current',queue='ranked',placement=2,played_at=100,patch=query['patch'],set=query['set_key']),
                    dict(match_id='old',queue='ranked',placement=8,played_at=100,patch='old',set=query['set_key'])])
        provider=Provider()
        self.client=TestClient(create_app(client=mock_client(),db_path=self.path,history_provider=provider,
            active_release={'tft_patch':'18.3','set_key':'TFTSet18'}))
        token=self.session();headers={'Authorization':'Bearer '+token}
        query={'nickname':'Jogador#BR1','region':'BR'}
        first=self.client.post('/v1/player-summary',json=query,headers=headers).json()
        second=self.client.post('/v1/player-summary',json=query,headers=headers).json()
        self.assertEqual(first['statistics']['matches'],1)
        self.assertEqual(first['excluded_patch_records'],1)
        self.assertTrue(second['cache_hit']);self.assertEqual(provider.calls,1)
        self.client=TestClient(create_app(client=mock_client(),db_path=self.path,history_provider=provider,
            active_release={'tft_patch':'18.4','set_key':'TFTSet18'}))
        third=self.client.post('/v1/player-summary',json=query,headers=headers).json()
        self.assertFalse(third['cache_hit']);self.assertEqual(provider.calls,2)
