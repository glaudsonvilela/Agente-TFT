"""Bounded anonymous ElevenLabs proxy; provider key is never shipped to Windows.

Run behind HTTPS, single Uvicorn worker. SQLite reservations enforce a global
character budget even across restarts; failed requests consume the reservation.
"""
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid
import wave
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal
from hm.voice_api import ElevenLabsSpeech, SpeechError
from .audio_cache import AudioCache


class SessionRequest(BaseModel):
    installation_id: uuid.UUID


class VoiceRequest(BaseModel):
    text: str = Field(min_length=1,max_length=500)
    tone: Literal['thoughtful','confident','urgent'] | None = None


class ProfileRequest(BaseModel):
    nickname: str = Field(min_length=2,max_length=80)
    region: str = Field(pattern=r'^(BR|NA|LAN|LAS|EUW|EUNE|KR|JP|OCE|TR|RU|SEA|TW|VN)$')


class Budget:
    def __init__(self,path,daily_characters):
        self.path=str(path);self.daily_characters=daily_characters
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,device TEXT,expires REAL);
                CREATE TABLE IF NOT EXISTS registrations(ip TEXT,created REAL);
                CREATE TABLE IF NOT EXISTS usage(device TEXT,created REAL,characters INTEGER);
                CREATE TABLE IF NOT EXISTS profile_cache(key TEXT PRIMARY KEY,expires REAL,result TEXT);
                CREATE INDEX IF NOT EXISTS usage_time ON usage(created);
                CREATE INDEX IF NOT EXISTS registrations_time ON registrations(created);
            ''')
    @contextmanager
    def db(self):
        connection=sqlite3.connect(self.path,timeout=2)
        try:
            with connection:yield connection
        finally:connection.close()
    @staticmethod
    def digest(value):return hashlib.sha256(value.encode()).hexdigest()
    def session(self,device,ip):
        now=time.time();token=secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM sessions WHERE expires<?',(now,))
            db.execute('DELETE FROM registrations WHERE created<?',(now-3600,))
            db.execute('DELETE FROM usage WHERE created<?',(now-86400,))
            # Bounded state and registrations, independent of arbitrary device IDs.
            if db.execute('SELECT count(*) FROM sessions').fetchone()[0]>=10000:
                raise HTTPException(429,'Service session capacity reached')
            if db.execute('SELECT count(*) FROM registrations WHERE ip=?',(self.digest(ip),)).fetchone()[0]>=20:
                raise HTTPException(429,'Please retry later')
            db.execute('INSERT INTO registrations VALUES(?,?)',(self.digest(ip),now))
            db.execute('INSERT INTO sessions VALUES(?,?,?)',(self.digest(token),self.digest(device),now+86400))
        return token
    def reserve(self,token,characters):
        now=time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT device FROM sessions WHERE token=? AND expires>?',(self.digest(token),now)).fetchone()
            if row is None:raise HTTPException(401,'Session expired; reconnect voice')
            device=row[0]
            count=db.execute('SELECT count(*) FROM usage WHERE device=? AND created>?',(device,now-60)).fetchone()[0]
            daily=db.execute('SELECT count(*) FROM usage WHERE device=? AND created>?',(device,now-86400)).fetchone()[0]
            total=db.execute('SELECT coalesce(sum(characters),0) FROM usage WHERE created>?',(now-86400,)).fetchone()[0]
            if count>=6 or daily>=120 or (characters and total+characters>self.daily_characters):
                raise HTTPException(429,'Voice service budget reached')
            db.execute('INSERT INTO usage VALUES(?,?,?)',(device,now,characters))


def create_app(*,client=None,db_path=None,daily_characters=20000, history_provider=None, active_release=None):
    app=FastAPI(title='Agente TFT — voz',docs_url=None,redoc_url=None)
    budget=Budget(db_path or os.environ.get('TFT_VOICE_DB','data/voice.sqlite3'),daily_characters)
    audio_cache=AudioCache(Path(budget.path).with_name('voice-audio.sqlite3'))
    # One shared client/cache, no growing collection of provider engines or threads.
    lock=threading.Lock()
    history_lock=threading.Lock()
    if active_release is None:
        try:
            reference=Path(os.environ.get('TFT_ACTIVE_KNOWLEDGE',str(Path(__file__).resolve().parents[2]/'configs/catalog/active-knowledge-release-v1.json')))
            active_release=json.loads(reference.read_text())
        except (OSError,ValueError):active_release={}

    if client is None:
        key=os.environ.get('ELEVENLABS_API_KEY','');voice=os.environ.get('ELEVENLABS_VOICE_ID','')
        client=ElevenLabsSpeech(key,voice,model_id=os.environ.get('ELEVENLABS_MODEL_ID','eleven_flash_v2_5')) if key and voice else None

    @app.get('/health')
    def health():return dict(voice_configured=client is not None,provider='elevenlabs',
                            riot_integration=False,audio_cache=audio_cache.stats())

    @app.post('/v1/session')
    def session(body:SessionRequest,request:Request):
        if client is None and history_provider is None:raise HTTPException(503,'Companion service not configured')
        return dict(token=budget.session(str(body.installation_id),request.client.host if request.client else 'unknown'),expires_in=86400)

    @app.post('/v1/player-summary')
    def player_summary(body:ProfileRequest,authorization:str|None=Header(default=None)):
        if not authorization or not authorization.startswith('Bearer '):raise HTTPException(401,'Session required')
        # Read access validates the anonymous app session without consuming voice quota.
        with budget.db() as db:
            session=db.execute('SELECT 1 FROM sessions WHERE token=? AND expires>?',
                (budget.digest(authorization[7:]),time.time())).fetchone()
        if not session:raise HTTPException(401,'Session expired')
        if history_provider is None:
            return dict(status='external_history_unavailable',summary='Histórico externo ainda não conectado.',
                        statistics=None,neural_analysis_applied=False)
        patch=active_release.get('tft_patch');set_key=active_release.get('set_key')
        if not patch or not set_key:
            return dict(status='patch_unavailable',summary='Patch atual não configurado no servidor.',statistics=None,neural_analysis_applied=False)
        key=budget.digest(json.dumps([body.nickname,body.region,patch,set_key,'ranked-summary-v1']))
        if not history_lock.acquire(blocking=False):
            raise HTTPException(429,'History service busy')
        try:
            with budget.db() as db:
                cached=db.execute('SELECT result FROM profile_cache WHERE key=? AND expires>?',(key,time.time())).fetchone()
            if cached:return dict(json.loads(cached[0]),cache_hit=True)
            from .player_summary import summarize
            history=history_provider.fetch(body.nickname,body.region,patch=patch,set_key=set_key,limit=20)
            if history['nickname']!=body.nickname or history['region']!=body.region:
                raise ValueError('Identity mismatch')
            result=summarize(history['matches'],source=history['source'],fetched_at=history['fetched_at'],
                             current_patch=patch,current_set=set_key)
            with budget.db() as db:
                db.execute('DELETE FROM profile_cache WHERE expires<?',(time.time(),))
                if db.execute('SELECT count(*) FROM profile_cache').fetchone()[0]>=2000:
                    db.execute('DELETE FROM profile_cache WHERE key IN (SELECT key FROM profile_cache ORDER BY expires LIMIT 1)')
                db.execute('INSERT OR REPLACE INTO profile_cache VALUES(?,?,?)',
                           (key,min(time.time(),history['fetched_at'])+900,json.dumps(result)))
            return dict(result,cache_hit=False)
        except Exception:
            return dict(status='external_history_unavailable',summary='Não foi possível confirmar o histórico deste perfil.',
                        statistics=None,neural_analysis_applied=False)
        finally:history_lock.release()

    @app.post('/v1/voice')
    def voice(body:VoiceRequest,authorization:str|None=Header(default=None)):
        if client is None:raise HTTPException(503,'Voice service not configured')
        if not authorization or not authorization.startswith('Bearer '):raise HTTPException(401,'Session required')
        if not lock.acquire(blocking=False):raise HTTPException(429,'Voice service busy')
        try:
            # Tone belongs in the cache identity even when the current model
            # ignores tags, so changing models cannot reuse the wrong delivery.
            key=audio_cache.key(client.cache_identity(),json.dumps([body.text,body.tone],ensure_ascii=False))
            pcm=audio_cache.get(key)
            cached=pcm is not None
            # Cache hits still require a valid session and count toward rate limits.
            budget.reserve(authorization[7:],0 if cached else len(client.request_text(body.text,body.tone)))
            if cached:
                audio_cache.record_hit(len(body.text))
            else:
                wav=(client.synthesize(body.text,tone=body.tone) if body.tone
                     else client.synthesize(body.text))
                with wave.open(io.BytesIO(wav),'rb') as audio:
                    if (audio.getnchannels(),audio.getsampwidth(),audio.getframerate())!=(1,2,22050):
                        raise SpeechError('Unsupported audio')
                    pcm=audio.readframes(audio.getnframes())
                if not pcm or len(pcm)%2:raise SpeechError('Incomplete audio')
                audio_cache.put(key,pcm)
            return Response(pcm,media_type='audio/pcm',headers={
                'Cache-Control':'no-store','X-TFT-Voice-Cache':'hit' if cached else 'miss'})
        except SpeechError:
            raise HTTPException(502,'Voice provider unavailable') from None
        except sqlite3.Error:
            # Avoid repeated provider spending if persistent storage is unavailable.
            raise HTTPException(503,'Voice cache storage unavailable') from None
        finally:lock.release()
    return app


if __name__=='__main__':
    import uvicorn
    uvicorn.run(create_app(daily_characters=int(os.environ.get('TFT_DAILY_VOICE_CHARACTERS','20000'))),
                host='127.0.0.1',port=8802,workers=1,proxy_headers=False)
