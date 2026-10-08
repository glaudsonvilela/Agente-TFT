import io
import json
import os
import tempfile
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from hm.voice import VoiceCoach, speech_importance
from hm.voice_api import ElevenLabsSpeech, SpeechError
from hm.voice_validation import MockConnection, mock_client
from hm.pipeline_health import snapshot


class VoiceAPITests(unittest.TestCase):
    def test_request_is_text_only_pt_and_cache_reuses_wav(self):
        calls=[]
        class Connection(MockConnection):
            def request(self, method, path, body, headers):
                calls.append((method,path,json.loads(body),headers))
        client=ElevenLabsSpeech('private-key','selected-voice',connection_factory=Connection)
        wav=client.synthesize('Guarde os componentes.')
        self.assertEqual(client.synthesize('Guarde os componentes.'),wav)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][2],dict(text='Guarde os componentes.',model_id='eleven_flash_v2_5',language_code='pt'))
        self.assertEqual(calls[0][3]['xi-api-key'],'private-key')
        with wave.open(io.BytesIO(wav),'rb') as audio:
            self.assertEqual((audio.getnchannels(),audio.getsampwidth(),audio.getframerate()),(1,2,22050))
        for i in range(30):client.synthesize(str(i))
        self.assertLessEqual(len(client.cache),16)
        client.close();self.assertFalse(client.cache)

    def test_delivery_tags_require_an_expressive_model(self):
        calls=[]
        class Connection(MockConnection):
            def request(self,method,path,body,headers):
                calls.append(json.loads(body))
        flash=ElevenLabsSpeech('key','voice',connection_factory=Connection)
        flash.synthesize('Role uma vez.',tone='urgent')
        self.assertEqual(calls[-1]['text'],'Role uma vez.')
        expressive=ElevenLabsSpeech('key','voice',model_id='eleven_v4',connection_factory=Connection)
        expressive.synthesize('Role uma vez.',tone='urgent')
        self.assertEqual(calls[-1]['text'],'[urgent, focused] Role uma vez.')
        self.assertEqual(calls[-1]['model_id'],'eleven_v4')
        with self.assertRaises(SpeechError):expressive.synthesize('Teste',tone='[laughs]')

    def test_http_errors_redact_body_and_never_follow_redirects(self):
        for status in (301,401,403,404,429,500):
            class Connection(MockConnection):
                def getresponse(self):
                    self.status=status;return self
                def read1(self,size):
                    raise AssertionError('Error body must not be read')
            client=ElevenLabsSpeech('sensitive-key','voice',connection_factory=Connection)
            with self.assertRaises(SpeechError) as error:client.synthesize('Texto privado')
            self.assertNotIn('sensitive-key',str(error.exception))
            self.assertNotIn('Texto privado',str(error.exception))

    def test_invalid_pcm_and_oversized_payload(self):
        for payload in (b'',b'x',b'\0'*(2*1024*1024+2)):
            class Connection(MockConnection):
                def __init__(self,*args,**kwargs):
                    super().__init__(*args,**kwargs);self.data=io.BytesIO(payload)
            with self.assertRaises(SpeechError):
                ElevenLabsSpeech('key','voice',connection_factory=Connection).synthesize('Teste')

    def test_configuration_does_not_make_a_request(self):
        client=mock_client()
        client.synthesize=lambda text: self.fail('No automatic billed warmup')
        coach=VoiceCoach(client=client,load_settings=False)
        self.assertTrue(coach.ready)
        self.assertFalse(coach.enabled)
        coach.close()

    def test_repeated_economy_speech_yields_to_new_context(self):
        coach = VoiceCoach(load_settings=False)
        coach.enabled = True
        self.assertTrue(coach.say('Guarde um de ouro.', 0, family='economy'))
        self.assertFalse(coach.say('Guarde dois de ouro.', 0, family='economy'))
        self.assertEqual(coach.last_rejection, 'economy_speech_cooldown')
        self.assertTrue(coach.say('Veja o adversário.', 0, kind='scout',
                                  urgent_event=True))
        coach.close()

    def test_interest_reminder_stays_in_panel_without_speech(self):
        coach = VoiceCoach(load_settings=False)
        coach.enabled = True
        coach.set_context('specific-buy')
        tip = dict(actionable=True, action_type='hold_interest',
                   speech_text='Guarde um de ouro.', decision_key='interest',
                   frame_id=1, source_due_ns=time.monotonic_ns())
        self.assertIsNone(coach.observe_tip(tip, time.monotonic_ns()))
        self.assertEqual(coach.context_key, 'specific-buy')
        self.assertEqual(coach.queued_count, 0)
        coach.close()

    def test_three_nearby_tips_keep_the_most_important_action(self):
        coach = VoiceCoach(load_settings=False)
        coach.enabled = True
        now = time.monotonic_ns()
        tips = [
            dict(actionable=True, action_type='prepare_level', family='economy',
                 speech_text='Prepare o próximo nível.', decision_key='plan',
                 frame_id=1, source_due_ns=now),
            dict(actionable=True, action_type='roll', family='roll',
                 speech_text='Role agora.', decision_key='roll',
                 frame_id=2, source_due_ns=now),
            dict(actionable=True, action_type='buy_pair', family='buy',
                 speech_text='Compre o par.', decision_key='pair',
                 frame_id=3, source_due_ns=now),
        ]
        self.assertLess(speech_importance(tips[0]), speech_importance(tips[1]))
        self.assertTrue(coach.observe_tip(tips[0], now)['queued'])
        self.assertTrue(coach.observe_tip(tips[1], now)['queued'])
        result = coach.observe_tip(tips[2], now)
        self.assertFalse(result['queued'])
        self.assertEqual(result['reason'], 'lower_priority_recent_tip')
        self.assertEqual(coach.context_key, 'roll')
        self.assertEqual(coach.pending.get_nowait()[0], 'Role agora.')
        coach.close()

    def test_priority_window_avoids_synthesis_for_superseded_tip(self):
        client = mock_client()
        synthesized = []
        played = threading.Event()
        original = client.synthesize
        def synth(text, *, tone=None):
            synthesized.append(text)
            return original(text)
        client.synthesize = synth
        coach = VoiceCoach(client=client, playback=lambda wav: played.set(), load_settings=False)
        coach.set_enabled(True)
        self.assertTrue(coach.say('Prepare o nível.', 0, decision_key='plan',
                                  importance=55))
        self.assertTrue(coach.say('Role agora.', 0, decision_key='roll',
                                  importance=100))
        self.assertFalse(coach.say('Compre o par.', 0, decision_key='pair',
                                   importance=90))
        self.assertTrue(played.wait(2))
        self.assertEqual(synthesized, ['Role agora.'])
        coach.close(); coach.thread.join(1)

    def test_changed_voice_cancels_inflight_old_audio(self):
        entered=threading.Event();release=threading.Event();played=[]
        client=mock_client()
        def synth(text):
            entered.set();release.wait(2);return b'old voice'
        client.synthesize=synth
        coach=VoiceCoach(client=client,playback=played.append,load_settings=False)
        coach.set_enabled(True);coach.say('Teste',0,force=True)
        self.assertTrue(entered.wait(1))
        coach.configure(mock_client());release.set()
        time.sleep(.05);coach.close();coach.thread.join(1)
        self.assertFalse(played)

    def test_action_family_sets_audio_tone_without_changing_visible_tip(self):
        client=mock_client();calls=[];played=threading.Event()
        original=client.synthesize
        def synth(text,*,tone=None):
            calls.append((text,tone));return original(text)
        client.synthesize=synth
        coach=VoiceCoach(client=client,playback=lambda wav:played.set(),load_settings=False)
        coach.set_enabled(True)
        now=time.monotonic_ns()
        tip=dict(actionable=True,speech_text='Role uma vez.',family='roll',
                 decision_key='roll:one',frame_id=1,source_due_ns=now,
                 speech_max_age_ms=8000)
        self.assertTrue(coach.observe_tip(tip,now)['queued'])
        self.assertTrue(played.wait(1))
        self.assertEqual(calls,[('Role uma vez.','urgent')])
        self.assertEqual(tip['speech_text'],'Role uma vez.')
        coach.close();coach.thread.join(1)

    def test_confirmed_combat_commentary_is_spoken_without_action_feedback(self):
        client=mock_client();played=threading.Event();calls=[]
        original=client.synthesize
        def synth(text,*,tone=None):
            calls.append((text,tone));return original(text)
        client.synthesize=synth
        coach=VoiceCoach(client=client,playback=lambda wav:played.set(),load_settings=False)
        coach.set_enabled(True)
        now=time.monotonic_ns()
        tip=dict(actionable=False,speakable=True,kind='combat',
                 speech_text='Não foi dessa vez, hein.',voice_tone='thoughtful',
                 decision_key='combat-loss:1:2-6',frame_id=10,source_due_ns=now,
                 speech_max_age_ms=8000)
        self.assertTrue(coach.observe_tip(tip,now)['queued'])
        self.assertTrue(played.wait(1))
        self.assertEqual(calls,[('Não foi dessa vez, hein.','thoughtful')])
        coach.close();coach.thread.join(1)

    def test_highlight_callback_requires_successful_audio_playback(self):
        played=[];completed=threading.Event()
        coach=VoiceCoach(client=mock_client(),playback=lambda wav: None,load_settings=False)
        coach.on_played=lambda *args: (played.append(args),completed.set())
        coach.set_enabled(True)
        coach.say('Role agora.',0,force=True,decision_key='roll:one',kind='strategy',family='roll')
        self.assertTrue(completed.wait(1))
        self.assertEqual(played[0][1],'Role agora.')
        self.assertEqual(played[0][2]['decision_key'],'roll:one')
        self.assertEqual(played[0][2]['family'],'roll')
        self.assertLessEqual(played[0][3],played[0][4])
        coach.close();coach.thread.join(1)

        failed=[];error=threading.Event()
        def fail(_wav):
            error.set()
            raise RuntimeError('playback unavailable')
        coach=VoiceCoach(client=mock_client(),playback=fail,load_settings=False)
        coach.on_played=lambda *args: failed.append(args)
        coach.set_enabled(True)
        coach.say('Role agora.',0,force=True,decision_key='roll:two')
        self.assertTrue(error.wait(1))
        coach.close();coach.thread.join(1)
        self.assertFalse(failed)

    def test_spoken_action_is_not_repeated_after_intervening_phrase(self):
        played=[]
        coach=VoiceCoach(client=mock_client(),playback=lambda wav:played.append(wav),
                         load_settings=False)
        coach.set_enabled(True)
        self.assertTrue(coach.say('Compre Ornn.',0,force=True,decision_key='ornn'))
        until=time.monotonic()+2
        while len(played)<1 and time.monotonic()<until:time.sleep(.01)
        self.assertEqual(len(played),1)
        self.assertTrue(coach.say('Role agora.',0,force=True,decision_key='roll'))
        until=time.monotonic()+2
        while len(played)<2 and time.monotonic()<until:time.sleep(.01)
        self.assertEqual(len(played),2)
        self.assertFalse(coach.say('Compre Ornn.',0,decision_key='ornn'))
        self.assertEqual(coach.last_rejection,'decision_recently_spoken')
        coach.close();coach.thread.join(1)

    def test_combat_commentary_bypasses_only_the_speech_cooldown(self):
        coach=VoiceCoach(load_settings=False);coach.enabled=True
        now=time.monotonic_ns()
        coach.last_queued_ns=now
        tip=dict(actionable=False,speakable=True,kind='combat',
                 speech_text='Não foi dessa vez, hein.',decision_key='loss:one',
                 frame_id=1,source_due_ns=now,speech_max_age_ms=8000)
        self.assertTrue(coach.observe_tip(tip,now)['queued'])
        self.assertIsNone(coach.observe_tip(tip,now))

    def test_unchanged_visible_text_retries_after_stale_observation(self):
        coach=VoiceCoach(load_settings=False);coach.enabled=True
        now=time.monotonic_ns()
        tip=dict(actionable=True,speech_text='Suba para o nível quatro.',decision_key='level4',
                 frame_id=1,source_due_ns=now-3_000_000_000,speech_max_age_ms=4000)
        self.assertFalse(coach.observe_tip(tip,now)['queued'])
        tip.update(frame_id=2,source_due_ns=now)
        self.assertTrue(coach.observe_tip(tip,now)['queued'])
        self.assertIsNone(coach.observe_tip(tip,now))

    def test_api_failure_has_backoff_and_can_retry_same_tip_later(self):
        client=mock_client();failed=threading.Event()
        def fail(text):failed.set();raise SpeechError('Limite da API')
        client.synthesize=fail
        coach=VoiceCoach(client=client,playback=lambda wav:None,load_settings=False)
        coach.set_enabled(True);coach.say('Teste',0,force=True)
        failed.wait(1)
        until=time.monotonic()+1
        while coach.error is None and time.monotonic()<until:time.sleep(.01)
        self.assertFalse(coach.say('Teste',0,force=True))
        self.assertEqual(coach.last_rejection,'api_backoff')
        self.assertIsNone(coach.last_text)
        coach.retry_after_ns=0
        self.assertTrue(coach.say('Teste',0))
        coach.close();coach.thread.join(1)

    def test_pipeline_distinguishes_arrival_from_reader_and_accuracy(self):
        from types import SimpleNamespace
        source=SimpleNamespace(last_analysis_received_ns=10_000_000_000,last_preview_received_ns=10_000_000_000)
        counts=dict(source_frames=5,read_frames=0)
        result=snapshot(now_ns=11_000_000_000,source=source,reader_item=None,counts=counts)
        self.assertEqual(result['code'],'READER_NOT_RETURNING')
        result=snapshot(now_ns=11_000_000_000,source=source,reader_item=dict(ready_ns=10_000_000_000,record={}),counts=counts)
        self.assertEqual(result['code'],'DELIVERY_AND_READER_ACTIVE')
        self.assertFalse(result['confirms_ocr_accuracy'])
        source.last_analysis_received_ns=0
        self.assertEqual(snapshot(now_ns=11_000_000_000,source=source,reader_item=None,counts=counts)['code'],'ANALYSIS_FRAMES_STALLED')

    @unittest.skipUnless(os.name=='nt','Windows DPAPI required')
    def test_windows_credentials_encrypted_and_roundtrip(self):
        from hm.voice_settings import save,load,settings_path
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,LOCALAPPDATA=temp):
            save('secret-do-not-log','selected-voice')
            self.assertNotIn(b'secret-do-not-log',settings_path().read_bytes())
            self.assertEqual(load(),dict(api_key='secret-do-not-log',voice_id='selected-voice'))


class VoiceServiceTests(unittest.TestCase):
    def test_gateway_url_and_payload_do_not_expose_provider_key(self):
        from hm.voice_service import ServiceSpeech,service_address
        for url in ('http://example.com','https://user:pass@example.com','https://example.com/?token=secret'):
            with self.assertRaises(SpeechError):service_address(url)
        calls=[]
        class Connection(MockConnection):
            def __init__(self,host,port,timeout):super().__init__(host,timeout)
            def request(self,method,path,body,headers):calls.append((path,json.loads(body),headers))
        service=ServiceSpeech('https://voice.example.com','session-token',connection_factory=Connection)
        service.synthesize('Bem-vindo!')
        self.assertEqual(calls[0][0],'/v1/voice')
        self.assertEqual(calls[0][1],{'text':'Bem-vindo!'})
        self.assertNotIn('xi-api-key',calls[0][2])
        service.synthesize('Role uma vez.',tone='urgent')
        self.assertEqual(calls[1][1],{'text':'Role uma vez.','tone':'urgent'})

if __name__=='__main__':unittest.main()
