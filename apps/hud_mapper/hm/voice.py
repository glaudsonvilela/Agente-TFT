"""Bounded ElevenLabs narration on a worker thread; no local TTS models."""
from __future__ import annotations
import os
import queue
import subprocess
import threading
import time
from collections import deque
from .voice_api import ElevenLabsSpeech, SpeechError


def _play_wav(wav: bytes):
    import winsound
    # PlaySound is synchronous unless SND_ASYNC is specified. Python's
    # winsound module does not expose SND_SYNC on supported Windows builds.
    winsound.PlaySound(wav, winsound.SND_MEMORY | winsound.SND_NODEFAULT)


def linux_play_wav(wav: bytes):
    """Play a server-generated WAV in the Ubuntu laboratory, without local TTS."""
    process = subprocess.run(['ffplay', '-nodisp', '-autoexit', '-loglevel', 'error',
                              '-i', 'pipe:0'], input=wav, stdout=subprocess.DEVNULL,
                             stderr=subprocess.PIPE, timeout=12)
    if process.returncode:
        raise RuntimeError(process.stderr.decode('utf-8', 'replace')[-500:])


def speech_importance(tip: dict) -> int:
    """Rank delivery urgency, not the truth or quality of a game decision."""
    action = tip.get('action_type')
    if action == 'hold_interest':
        return 0
    priorities = {
        'roll': 100, 'equip': 95, 'buy_pair': 90, 'buy': 88,
        'buy_synergy': 85, 'trait_shop_review': 82, 'buy_xp': 80, 'position': 78,
        'composition': 75, 'rebuild_after_level': 70,
        'prepare_level': 55, 'hold_econ': 20,
    }
    if action in priorities:
        return priorities[action]
    if tip.get('kind') == 'combat':
        return 72 if tip.get('voice_tone') == 'urgent' else 45
    return {'roll': 90, 'buy': 80, 'synergy': 75, 'economy': 20}.get(
        tip.get('family'), 50)


class VoiceCoach:
    def __init__(self, *, playback=None, client=None, load_settings=True):
        self.voices = {}
        self.voice_id = None
        self.client = None
        self.enabled = self.closed = self.ready = False
        self.pending = queue.Queue(maxsize=1)
        self.last_text = self.thread = self.error = self.last_generation_ms = None
        self.last_queued_ns = self.queued_count = self.played_count = self.stale_dropped_count = 0
        self.last_economy_ns = 0
        self.last_importance = 0
        self.fallback_from = self.engine_process = None
        self.isolated = False
        self.context_key = self.last_tip_attempt = self.last_rejection = None
        self.events = deque(maxlen=64)
        self.playback = playback
        self.on_played = None
        self.generation = 0
        self.retry_after_ns = 0
        if client is not None:
            self.configure(client)
        elif load_settings and os.environ.get("AGENTE_TFT_DEVELOPER_VOICE") == "1":
            try:
                from .voice_settings import load
                settings = load()
                if settings:
                    self.configure(ElevenLabsSpeech(**settings))
            except Exception:
                self.error = "Não foi possível abrir a configuração protegida da voz. Configure novamente."

    def configure(self, client):
        old = self.client
        self.generation += 1
        self.client = client
        self.voice_id = client.voice_id
        self.voices = {self.voice_id: "ElevenLabs · voz configurada"}
        self.ready = True  # Credentials configured; not proof of a successful API call.
        self.error = self.last_text = self.last_tip_attempt = None
        self.last_queued_ns = self.last_economy_ns = self.retry_after_ns = 0
        self.last_importance = 0
        if old:
            old.close()

    def set_context(self, decision_key):
        self.context_key = decision_key

    def observe_tip(self, tip, now_ns):
        """Try once per fresh observation, independent of whether UI text changed."""
        speakable = bool(tip and (tip.get('actionable') or tip.get('speakable')))
        # Keep recurring interest reminders on screen; they are not a coach's
        # substitute for a decision based on the board or a fresh shop.
        if tip and tip.get('action_type') == 'hold_interest':
            return None
        if not speakable or not tip.get('speech_text') or not self.enabled:return None
        token=(tip.get('frame_id'),tip.get('source_due_ns'),tip.get('decision_key'),self.voice_id,self.ready)
        if token==self.last_tip_attempt:return None
        self.last_tip_attempt=token
        age=max(0.,(now_ns-tip['source_due_ns'])/1e6)
        family=tip.get('family')
        tone=tip.get('voice_tone') or ('urgent' if family=='roll' else
                                      'thoughtful' if family=='economy' else 'confident')
        queued=self.say(tip['speech_text'],age,decision_key=tip.get('decision_key'),tone=tone,
                        urgent_event=tip.get('kind') == 'combat',
                        importance=speech_importance(tip),
                        max_age_ms=tip.get('speech_max_age_ms',3000),
                        source_frame_id=tip['frame_id'],source_ms=tip.get('source_ms'),
                        kind=tip.get('kind'),family=family)
        result=dict(event='voice_tip_attempt',frame_id=tip['frame_id'],decision_key=tip.get('decision_key'),
                    source_age_ms=age,queued=queued,reason=self.last_rejection)
        self.events.append(result)
        return result

    def _forget_cancelled(self,text,queued_ns):
        if self.last_text==text and self.last_queued_ns==queued_ns:
            self.last_text=None
            self.last_queued_ns=0
            self.last_importance=0

    def _valid(self, queued_ns, source_age_ms, max_age_ms, decision_key, force):
        return (self.enabled and not self.closed and
                (force or ((time.monotonic_ns()-queued_ns)/1e6 + source_age_ms <= max_age_ms
                           and (decision_key is None or self.context_key == decision_key))))

    def _event(self, event, decision_key, queued_ns, source_age_ms, **extra):
        self.events.append(dict(event=event, decision_key=decision_key,
            source_age_ms=(time.monotonic_ns()-queued_ns)/1e6+source_age_ms, **extra))

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled and (os.name == "nt" or self.playback) and self.client and not self.closed)
        if enabled and not self.enabled:
            self.error = "O serviço de voz ainda não está conectado."
        if not self.enabled:
            self.generation += 1
            self.last_text = self.last_tip_attempt = None
            self.last_queued_ns = 0
            self.last_importance = 0
            while True:
                try: self.pending.get_nowait()
                except queue.Empty: break
        if self.enabled and self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True, name="agente-tft-voice-api")
            self.thread.start()

    def say(self, text: str, source_age_ms: float, *, force: bool = False,
            decision_key: str | None = None, max_age_ms: float = 3000,
            source_frame_id: int | None = None, source_ms: float | None = None,
            tone: str | None = None, urgent_event: bool = False,
            kind: str | None = None, family: str | None = None,
            importance: int = 50):
        now = time.monotonic_ns()
        self.last_rejection=None
        if not self.enabled:self.last_rejection='voice_disabled'
        elif not text:self.last_rejection='empty_text'
        elif now<self.retry_after_ns:self.last_rejection='api_backoff'
        elif source_age_ms>2000 and not force:self.last_rejection='source_too_old'
        elif text==self.last_text and not force:self.last_rejection='already_queued_or_spoken'
        elif (now-self.last_queued_ns<8_000_000_000 and not force
                and importance<self.last_importance):
            self.last_rejection='lower_priority_recent_tip'
        elif (family=='economy' and self.last_economy_ns
                and now-self.last_economy_ns<25_000_000_000 and not force):
            self.last_rejection='economy_speech_cooldown'
        elif (now-self.last_queued_ns<8_000_000_000 and not force
                and not urgent_event and importance<=self.last_importance):
            self.last_rejection='speech_cooldown'
        if self.last_rejection:return False
        self.last_text = text
        self.last_queued_ns = now
        self.last_importance = importance
        self.set_context(decision_key)
        if family == 'economy':
            self.last_economy_ns = now
        try:
            self.pending.get_nowait()
        except queue.Empty:
            pass
        self.pending.put_nowait((text, now, self.voice_id, force, source_age_ms,
                                 decision_key, min(8000, max(0, max_age_ms)),
                                 dict(frame_id=source_frame_id,source_ms=source_ms,voice_id=self.voice_id,
                                      voice_tone=tone,kind=kind,family=family,
                                      importance=importance),self.generation,tone))
        self.queued_count += 1
        return True

    def _run(self):
        while not self.closed:
            try:
                text, queued_ns, voice_id, force, source_age_ms, decision_key, max_age_ms, metadata, generation, tone = self.pending.get(timeout=.2)
            except queue.Empty:
                continue
            # Let tips from the same observation burst compete before a paid
            # synthesis request. A later, more important tip replaces this one.
            if not force:
                time.sleep(.25)
                try:
                    replacement = self.pending.get_nowait()
                except queue.Empty:
                    pass
                else:
                    self.stale_dropped_count += 1
                    self._event('voice_superseded_before_synthesis', decision_key,
                                queued_ns, source_age_ms, **metadata)
                    (text, queued_ns, voice_id, force, source_age_ms, decision_key,
                     max_age_ms, metadata, generation, tone) = replacement
            client = self.client
            if generation != self.generation or client is None:
                continue
            if not self._valid(queued_ns, source_age_ms, max_age_ms, decision_key, force):
                self.stale_dropped_count += 1
                self._event('voice_cancelled_before_synthesis', decision_key, queued_ns, source_age_ms, **metadata)
                self._forget_cancelled(text, queued_ns)
                continue
            try:
                started = time.monotonic_ns()
                wav = client.synthesize(text,tone=tone) if tone else client.synthesize(text)
                self.last_generation_ms = (time.monotonic_ns()-started)/1e6
                if generation != self.generation:
                    continue
                if not self._valid(queued_ns, source_age_ms, max_age_ms, decision_key, force):
                    self.stale_dropped_count += 1
                    self._event('voice_cancelled_after_synthesis', decision_key, queued_ns, source_age_ms,
                                generation_ms=self.last_generation_ms, **metadata)
                    self._forget_cancelled(text, queued_ns)
                    continue
                self._event('voice_play_started', decision_key, queued_ns, source_age_ms,
                            generation_ms=self.last_generation_ms, physical_audio_measured=False, **metadata)
                play_started_ns = time.monotonic_ns()
                (self.playback or _play_wav)(wav)
                play_ended_ns = time.monotonic_ns()
                self.played_count += 1
                self.error = None
                self._event('voice_play_completed', decision_key, queued_ns, source_age_ms,
                            physical_audio_measured=False, **metadata)
                if self.on_played:
                    try:
                        self.on_played(wav,text,dict(metadata,decision_key=decision_key),
                                       play_started_ns,play_ended_ns)
                    except Exception:
                        # Recording failures cannot interrupt spoken coaching.
                        pass
            except Exception as exc:
                if generation == self.generation:
                    self.error = str(exc) if isinstance(exc, SpeechError) else "Não foi possível reproduzir o áudio."
                    # A transient network timeout should not silence the
                    # coach for half a round. Quota/auth failures still back off.
                    long_backoff = any(word in self.error.lower() for word in
                                       ('limite', 'créditos', 'chave', 'acesso'))
                    self.retry_after_ns = time.monotonic_ns() + (
                        30_000_000_000 if long_backoff else 8_000_000_000)
                    self._forget_cancelled(text, queued_ns)
                    self._event('voice_error', decision_key, queued_ns, source_age_ms, error=self.error, **metadata)

    def close(self):
        self.closed = True
        self.enabled = self.ready = False
        self.generation += 1
        if self.client:
            self.client.close()
