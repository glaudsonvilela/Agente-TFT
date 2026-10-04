"""Recorded pixels -> native OCR -> decision -> normal voice queue/process.

The audio sink writes a WAV for inspection. It does not claim a speaker or
physical display measurement; no text is supplied directly to the voice.
"""
from __future__ import annotations
import hashlib
import io
import json
import os
from pathlib import Path
import threading
import time
import wave
from PIL import Image
from e1.protocol import NativeWorker
from .replay_decision import ReplayDecisionEngine
from .replay_coach import coach_prompt
from .voice import VoiceCoach


def run(fixture: Path, output: Path, paths: dict, voices: Path | None = None,
        voice_id: str = 'supertonic-f1') -> dict:
    manifest = json.loads((fixture/'manifest.json').read_text())
    output.mkdir(parents=True, exist_ok=False)
    audio_done = threading.Event()
    audio_report = {}
    def receive_audio(wav):
        with wave.open(io.BytesIO(wav),'rb') as audio:
            audio_report.update(frames=audio.getnframes(), rate=audio.getframerate())
        if not audio_report['frames']:
            raise ValueError('Decision produced empty audio')
        (output/'decision.wav').write_bytes(wav)
        audio_done.set()
    voice = VoiceCoach(voices, playback=receive_audio)
    voice.set_voice(voice_id)
    # Offline harness uses the same queue/thread/process, with a file audio sink.
    voice.enabled = True
    voice.thread = threading.Thread(target=voice._run, daemon=True)
    voice.thread.start()
    worker = None
    try:
        deadline = time.monotonic()+75
        while not voice.ready:
            if voice.error:
                raise RuntimeError(voice.error)
            if time.monotonic()>deadline:
                raise TimeoutError('Voice warmup timed out')
            time.sleep(.05)
        worker = NativeWorker(paths['worker'], paths['configs'], paths.get('tesseract','tesseract'),
                              env={**os.environ,'AGENTE_TFT_RESIDENT_OCR':'auto'})
        engine = ReplayDecisionEngine(paths['configs'])
        reads = []
        for frame in manifest['frames']:
            image_path=fixture/frame['image']
            if hashlib.sha256(image_path.read_bytes()).hexdigest()!=frame['sha256']:
                raise ValueError('Replay fixture changed')
            started=time.monotonic_ns()
            with Image.open(image_path) as source:
                image=source.convert('RGB');pixels=image.tobytes()
            answer=worker.request(dict(op='frame',id=frame['id'],source_ms=frame['source_ms'],
                width=image.width,height=image.height,bytes=len(pixels),include_shop=True),pixels)
            evaluated=engine.evaluate(answer)
            tip=coach_prompt(evaluated)
            age=(time.monotonic_ns()-started)/1e6
            voice.set_context(tip.get('decision_key') if tip.get('actionable') else None)
            queued=False
            if tip.get('actionable'):
                expected=manifest['expected_action'];actual=evaluated['decision']['action']
                if any(actual.get(k)!=v for k,v in expected.items()):
                    raise ValueError('Unexpected decision on recorded pixels')
                queued=voice.say(tip['speech_text'],age,decision_key=tip['decision_key'],
                                 max_age_ms=tip['speech_max_age_ms'],source_frame_id=frame['id'],
                                 source_ms=frame['source_ms'])
            reads.append(dict(frame_id=frame['id'],hud=answer['hud'],decision=evaluated['decision'],
                              tip=tip,read_to_decision_ms=age,voice_queued=queued))
        if not any(row['voice_queued'] for row in reads):
            raise RuntimeError('Recorded pixels produced no actionable spoken decision')
        if not audio_done.wait(15):
            raise RuntimeError('Decision audio did not arrive within validity: '+str(voice.error))
        report=dict(complete=True,source=manifest['source'],frames=reads,voice_id=voice.voice_id,
                    voice_process_separate=True,voice_process_memory=voice.engine_process.memory,
                    events=list(voice.events),audio=audio_report,
                    physical_audio_measured=False,full_match_accuracy_measured=False,
                    policy_kind='explicit_economy_heuristic_not_neural_combat_strategy')
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return report
    finally:
        voice.close()
        if worker:
            worker.close()
