"""Offline, selectable Portuguese narration. Synthesis never runs on the UI thread."""
from __future__ import annotations

import io
import os
from pathlib import Path
import queue
import sys
import threading
import time
import wave
from collections import OrderedDict, deque


def _voice_process_main(connection, voice_id, base):
    """Models and ONNX arenas live outside the UI process and die with it."""
    try:
        engine = _load_engine(voice_id, Path(base))
        _synthesize('Pronto.', voice_id, Path(base), engine)
        connection.send({'ready': True, 'pid': os.getpid()})
        cache = OrderedDict()
        while True:
            text = connection.recv()
            if text is None:
                break
            cached = text in cache
            if not cached:
                wav, engine = _synthesize(text, voice_id, Path(base), engine)
                cache[text] = wav
                while len(cache) > 16 or sum(map(len, cache.values())) > 8*1024*1024:
                    cache.popitem(last=False)
            else:
                wav = cache[text]
                cache.move_to_end(text)
            from .process_memory import current_process_memory
            connection.send({'wav': wav, 'cache_hit': cached,
                             'process_memory': current_process_memory()})
    except (EOFError, BrokenPipeError):
        pass
    except Exception as exc:
        try:
            connection.send({'error': str(exc)})
        except (EOFError, BrokenPipeError, OSError):
            pass
    finally:
        connection.close()


class VoiceProcess:
    def __init__(self, voice_id, base):
        import multiprocessing
        context = multiprocessing.get_context('spawn')
        self.connection, child = context.Pipe()
        self.process = context.Process(target=_voice_process_main,
            args=(child, voice_id, str(base)), daemon=True, name='tft-voice')
        self.process.start()
        child.close()
        self.memory = None

    def receive(self, timeout):
        if not self.connection.poll(timeout):
            raise TimeoutError('A geração de voz excedeu o tempo limite.')
        result = self.connection.recv()
        if result.get('error'):
            raise RuntimeError(result['error'])
        return result

    def synthesize(self, text):
        self.connection.send(text)
        result = self.receive(30)
        self.memory = result.get('process_memory')
        return result['wav']

    def close(self):
        # Close also interrupts stuck inference; no growing orphan model set.
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=1)
        self.connection.close()

VOICE_NAMES = {"supertonic-f1": "F1 (feminina)",
               "dii": "Dii (feminina, pt-BR)",
               "cadu": "Cadu (pt-BR)", "faber": "Faber (pt-BR)"}
SUPERTONIC_FILES = ("onnx/duration_predictor.onnx", "onnx/text_encoder.onnx",
                    "onnx/vector_estimator.onnx", "onnx/vocoder.onnx",
                    "onnx/tts.json", "onnx/unicode_indexer.json",
                    "voice_styles/F1.json", "LICENSE")


def voice_assets() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    return base / "voices"


def available_voices(base: Path | None = None) -> dict[str, str]:
    base = base or voice_assets()
    found = {}
    if all((base / "supertonic-f1" / name).is_file() for name in SUPERTONIC_FILES):
        found["supertonic-f1"] = VOICE_NAMES["supertonic-f1"]
    for key in ("dii", "cadu", "faber"):
        if ((base / key / "model.onnx").is_file()
                and (base / key / "tokens.txt").is_file()
                and (base / "espeak-ng-data").is_dir()):
            found[key] = VOICE_NAMES[key]
    return found


def _load_engine(voice_id: str, base: Path):
    if voice_id == "supertonic-f1":
        from supertonic import TTS
        model = TTS(model_dir=str(base / voice_id), auto_download=False,
                    intra_op_num_threads=2)
        return model, model.get_voice_style("F1")
    import sherpa_onnx
    model = base / voice_id
    config = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
            model=str(model / "model.onnx"), tokens=str(model / "tokens.txt"),
            data_dir=str(base / "espeak-ng-data")),
        provider="cpu", num_threads=1))
    if not config.validate():
        raise RuntimeError("Modelo de voz local incompleto.")
    return sherpa_onnx.OfflineTts(config)


def _synthesize(text: str, voice_id: str, base: Path, engine=None):
    import numpy as np
    if engine is None:
        engine = _load_engine(voice_id, base)
    if voice_id == "supertonic-f1":
        model, style = engine
        samples, _ = model.synthesize(text, voice_style=style, lang="pt",
                                      total_steps=6)
        sample_rate = model.sample_rate
    else:
        import sherpa_onnx
        generation = sherpa_onnx.GenerationConfig()
        generation.sid = 0
        generation.speed = 1.0
        audio = engine.generate(text, generation)
        samples = audio.samples
        sample_rate = audio.sample_rate
    samples = np.asarray(samples).reshape(-1)
    if samples.size == 0:
        raise RuntimeError("A voz local não gerou áudio.")
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm)
    return out.getvalue(), engine


def _play_wav(wav: bytes):
    import winsound
    # PlaySound is synchronous unless SND_ASYNC is specified. Python's
    # winsound module does not expose SND_SYNC on supported Windows builds.
    winsound.PlaySound(wav, winsound.SND_MEMORY | winsound.SND_NODEFAULT)


class VoiceCoach:
    def __init__(self, base: Path | None = None, *, isolated: bool = True, playback=None):
        self.base = base or voice_assets()
        self.voices = available_voices(self.base)
        self.voice_id = next(iter(self.voices), None)
        self.enabled = False
        self.closed = False
        self.pending = queue.Queue(maxsize=1)
        self.last_text = None
        self.last_queued_ns = 0
        self.thread = None
        self.error = None
        self.last_generation_ms = None
        self.queued_count = 0
        self.played_count = 0
        self.stale_dropped_count = 0
        self.ready = False
        self.fallback_from = None
        self.isolated = isolated
        self.engine_process = None
        self.context_key = None
        self.events = deque(maxlen=64)
        self.playback = playback

    def set_context(self, decision_key):
        self.context_key = decision_key

    def _valid(self, queued_ns, source_age_ms, max_age_ms, decision_key, force):
        return (self.enabled and not self.closed and
                (force or ((time.monotonic_ns()-queued_ns)/1e6 + source_age_ms <= max_age_ms
                           and (decision_key is None or self.context_key == decision_key))))

    def _event(self, event, decision_key, queued_ns, source_age_ms, **extra):
        self.events.append(dict(event=event, decision_key=decision_key,
            source_age_ms=(time.monotonic_ns()-queued_ns)/1e6+source_age_ms, **extra))

    def set_voice(self, voice_id: str):
        if voice_id not in self.voices:
            raise ValueError("Voz local indisponível no instalador.")
        self.voice_id = voice_id
        self.last_text = None
        self.ready = False
        self.fallback_from = None

    def _handle_failure(self, voice_id: str, exc: Exception):
        if voice_id == "supertonic-f1" and "dii" in self.voices:
            self.voice_id = "dii"
            self.fallback_from = voice_id
            self.last_text = None
            self.ready = False
            self.error = f"F1 falhou; Dii ativada: {exc}"
        else:
            self.error = f"Voz local: {exc}"
            self.ready = False
            self.enabled = False

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled and os.name == "nt" and self.voice_id and not self.closed)
        if enabled and not self.enabled:
            self.error = "Voz local indisponível neste computador ou pacote."
        if self.enabled and self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True, name="agente-tft-voice")
            self.thread.start()

    def say(self, text: str, source_age_ms: float, *, force: bool = False,
            decision_key: str | None = None, max_age_ms: float = 3000):
        now = time.monotonic_ns()
        if (not self.enabled or not text or (source_age_ms > 2000 and not force)
                or (text == self.last_text and not force)
                or (now-self.last_queued_ns < 8_000_000_000 and not force)):
            return False
        self.last_text = text
        self.last_queued_ns = now
        try:
            self.pending.get_nowait()
        except queue.Empty:
            pass
        self.pending.put_nowait((text, now, self.voice_id, force, source_age_ms,
                                 decision_key, min(8000, max(0, max_age_ms))))
        self.queued_count += 1
        return True

    def _run(self):
        engine = None
        loaded_voice = None
        while not self.closed:
            if self.enabled and (loaded_voice != self.voice_id or not self.ready):
                selected_voice = self.voice_id
                try:
                    if self.engine_process:
                        self.engine_process.close()
                        self.engine_process = None
                    engine = None
                    if self.isolated:
                        self.engine_process = VoiceProcess(selected_voice, self.base)
                        self.engine_process.receive(60)
                        selected_engine = self.engine_process
                    else:
                        selected_engine = _load_engine(selected_voice, self.base)
                        _synthesize("Pronto.", selected_voice, self.base, selected_engine)
                    if selected_voice != self.voice_id or not self.enabled:
                        continue
                    engine = selected_engine
                    loaded_voice = selected_voice
                    self.ready = True
                    self.error = None
                except Exception as exc:
                    if self.engine_process:
                        self.engine_process.close()
                        self.engine_process = None
                    if selected_voice == self.voice_id:
                        self._handle_failure(selected_voice, exc)
                    continue
            try:
                text, queued_ns, voice_id, force, source_age_ms, decision_key, max_age_ms = self.pending.get(timeout=.2)
            except queue.Empty:
                continue
            if not self.enabled or voice_id != self.voice_id:
                continue
            if not self._valid(queued_ns, source_age_ms, max_age_ms, decision_key, force):
                self.stale_dropped_count += 1
                self._event('voice_cancelled_before_synthesis', decision_key, queued_ns, source_age_ms)
                if self.last_text == text:
                    self.last_text = None
                continue
            try:
                started = time.monotonic_ns()
                if self.isolated:
                    wav = engine.synthesize(text)
                else:
                    wav, engine = _synthesize(text, voice_id, self.base, engine)
                self.last_generation_ms = (time.monotonic_ns()-started)/1e6
                if not self.enabled or voice_id != self.voice_id or self.closed:
                    continue
                if not self._valid(queued_ns, source_age_ms, max_age_ms, decision_key, force):
                    self.stale_dropped_count += 1
                    self._event('voice_cancelled_after_synthesis', decision_key, queued_ns, source_age_ms,
                                generation_ms=self.last_generation_ms)
                    if self.last_text == text:
                        self.last_text = None
                    continue
                self._event('voice_play_started', decision_key, queued_ns, source_age_ms,
                            generation_ms=self.last_generation_ms, physical_audio_measured=False)
                (self.playback or _play_wav)(wav)
                self.played_count += 1
                self.error = None
            except Exception as exc:
                if self.engine_process:
                    self.engine_process.close()
                    self.engine_process = None
                if voice_id == self.voice_id:
                    self._handle_failure(voice_id, exc)

    def close(self):
        self.closed = True
        self.enabled = False
        self.ready = False
        if self.engine_process:
            self.engine_process.close()
            self.engine_process = None
