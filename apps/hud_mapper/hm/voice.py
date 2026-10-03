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

VOICE_NAMES = {"dii": "Dii (feminina, pt-BR)",
               "cadu": "Cadu (pt-BR)", "faber": "Faber (pt-BR)"}


def voice_assets() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    return base / "voices"


def available_voices(base: Path | None = None) -> dict[str, str]:
    base = base or voice_assets()
    return {key: label for key, label in VOICE_NAMES.items()
            if (base / key / "model.onnx").is_file()
            and (base / key / "tokens.txt").is_file()
            and (base / "espeak-ng-data").is_dir()}


def _load_engine(voice_id: str, base: Path):
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
    import sherpa_onnx
    import numpy as np
    if engine is None:
        engine = _load_engine(voice_id, base)
    generation = sherpa_onnx.GenerationConfig()
    generation.sid = 0
    generation.speed = 1.0
    audio = engine.generate(text, generation)
    samples = np.asarray(audio.samples)
    if samples.size == 0:
        raise RuntimeError("A voz local não gerou áudio.")
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(audio.sample_rate))
        wav.writeframes(pcm)
    return out.getvalue(), engine


class VoiceCoach:
    def __init__(self, base: Path | None = None):
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

    def set_voice(self, voice_id: str):
        if voice_id not in self.voices:
            raise ValueError("Voz local indisponível no instalador.")
        self.voice_id = voice_id
        self.last_text = None
        self.ready = False

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled and os.name == "nt" and self.voice_id and not self.closed)
        if enabled and not self.enabled:
            self.error = "Voz local indisponível neste computador ou pacote."
        if self.enabled and self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True, name="agente-tft-voice")
            self.thread.start()

    def say(self, text: str, source_age_ms: float, *, force: bool = False):
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
        self.pending.put_nowait((text, now, self.voice_id, force, source_age_ms))
        self.queued_count += 1
        return True

    def _run(self):
        engine = None
        loaded_voice = None
        while not self.closed:
            if self.enabled and (loaded_voice != self.voice_id or not self.ready):
                try:
                    engine = _load_engine(self.voice_id, self.base)
                    # Warm the synthesizer before the first time-sensitive readout.
                    _synthesize("Pronto.", self.voice_id, self.base, engine)
                    loaded_voice = self.voice_id
                    self.ready = True
                    self.error = None
                except Exception as exc:
                    self.error = f"Voz local: {exc}"
                    self.ready = False
                    self.enabled = False
                    continue
            try:
                text, queued_ns, voice_id, force, source_age_ms = self.pending.get(timeout=.2)
            except queue.Empty:
                continue
            if not self.enabled or voice_id != self.voice_id:
                continue
            if (time.monotonic_ns()-queued_ns)/1e6 + source_age_ms > 3000 and not force:
                self.stale_dropped_count += 1
                if self.last_text == text:
                    self.last_text = None
                continue
            try:
                started = time.monotonic_ns()
                wav, engine = _synthesize(text, voice_id, self.base, engine)
                self.last_generation_ms = (time.monotonic_ns()-started)/1e6
                if not self.enabled or voice_id != self.voice_id or self.closed:
                    continue
                if not force and (time.monotonic_ns()-queued_ns)/1e6 + source_age_ms > 3000:
                    self.stale_dropped_count += 1
                    if self.last_text == text:
                        self.last_text = None
                    continue
                import winsound
                winsound.PlaySound(wav, winsound.SND_MEMORY | winsound.SND_SYNC | winsound.SND_NODEFAULT)
                self.played_count += 1
                self.error = None
            except Exception as exc:
                self.error = f"Voz local: {exc}"
                self.ready = False
                self.enabled = False

    def close(self):
        self.closed = True
        self.enabled = False
        self.ready = False
