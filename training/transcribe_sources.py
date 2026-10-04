"""Resume private, timestamped ASR in bounded chunks; transcripts are not action labels."""
from __future__ import annotations
import argparse
import atexit
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import signal
import tempfile
import time
import wave


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def atomic(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    os.replace(tmp, path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry', type=Path, required=True)
    p.add_argument('--media', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seconds', type=int, default=3600)
    p.add_argument('--threads', type=int, default=2)
    p.add_argument('--chunk-seconds', type=int, default=120)
    p.add_argument('--corpus-output', type=Path)
    p.add_argument('--online', type=Path)
    args = p.parse_args()
    if args.seconds <= 0 or not 1 <= args.threads <= 8 or not 30 <= args.chunk_seconds <= 300:
        p.error('invalid time/thread/chunk budget')
    args.output.mkdir(parents=True, exist_ok=True)
    lock = (args.output / '.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    from faster_whisper import WhisperModel
    import numpy as np
    model = WhisperModel(str(args.model), device='cpu', compute_type='int8',
                         cpu_threads=args.threads, local_files_only=True)
    sources = sorted(json.loads(args.registry.read_text())['sources'],key=lambda s:s.get('duration_seconds',float('inf')))
    from .source_corpus import TRANSCRIPTS, build
    analysis = args.media/'analysis'
    seals = {r['filename']:r for r in json.loads((analysis/'analysis-index.json').read_text())['transcripts']}
    started = time.monotonic()
    progress = dict(kind='authorized_video_asr', status='running', sources=[],
                    training_labels_ready=False, runtime_promoted=False,
                    model='faster-whisper-small', precision='int8', threads=args.threads)
    stop_requested = [False]
    signal.signal(signal.SIGTERM, lambda *_: stop_requested.__setitem__(0,True))
    def unfinished():
        if progress['status']=='running':
            progress['status']='interrupted_or_error'
            atomic(args.output/'progress.json',progress)
    atexit.register(unfinished)
    for source in sources:
        if 'source_file' in source:
            media = args.media / source['source_file']
        elif source.get('local_media') and source.get('source_sha256'):
            media = Path(source['local_media'])
        else: continue
        if digest(media) != source['source_sha256']: raise ValueError('media hash mismatch')
        directory = args.output / source['source_sha256'][:16]
        directory.mkdir(exist_ok=True)
        duration = source['duration_seconds']; done = 0.0
        record = dict(source_sha256=source['source_sha256'], url=source['url'],
                      total_seconds=duration, transcribed_seconds=0, complete=False)
        progress['sources'].append(record)
        atomic(args.output / 'progress.json', progress)
        previous_name = TRANSCRIPTS.get(source.get('source_file'))
        previous = seals.get(previous_name,{})
        if previous.get('scope') == 'full_guide':
            if digest(analysis/previous_name) != previous['sha256']: raise ValueError('existing ASR hash mismatch')
            record.update(transcribed_seconds=duration,complete=True,
                          provenance='reused_hash_verified_full_guide_asr')
            atomic(args.output / 'progress.json',progress)
            continue
        # Every chunk is atomic. A kill can only lose the current chunk.
        for start in range(0, int(duration) + 1, args.chunk_seconds):
            end = min(start + args.chunk_seconds, duration)
            output = directory / f'{start:06d}.json'
            if output.exists():
                old = json.loads(output.read_text())
                if old['source_sha256'] != source['source_sha256'] or old['start'] != start or old['end'] != end:
                    raise ValueError('incompatible existing chunk')
            else:
                if stop_requested[0] or time.monotonic() - started >= args.seconds or (args.output / 'STOP').exists():
                    progress['status'] = 'paused_at_chunk_boundary'
                    atomic(args.output / 'progress.json', progress)
                    print(json.dumps(progress), flush=True); return
                with tempfile.TemporaryDirectory(dir=args.output) as temporary:
                    wav = Path(temporary) / 'chunk.wav'
                    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-threads', '1',
                                    '-ss', str(start), '-i', str(media), '-t', str(end-start),
                                    '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(wav)], check=True)
                    with wave.open(str(wav), 'rb') as audio:
                        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2').astype(np.float32)/32768
                    segments, info = model.transcribe(samples, beam_size=3, vad_filter=True)
                    rows = [dict(start=start+s.start, end=min(end, start+s.end), text=s.text,
                                 average_log_probability=s.avg_logprob) for s in segments]
                    atomic(output, dict(source_sha256=source['source_sha256'], start=start,
                                        end=end, language=info.language, segments=rows,
                                        supervision='automatic_unreviewed_transcript'))
            done += end-start
            record.update(transcribed_seconds=done, complete=done >= duration-0.001)
            progress['elapsed_seconds'] = time.monotonic()-started
            atomic(args.output / 'progress.json', progress)
            if args.corpus_output and int(done) % (args.chunk_seconds*5) == 0:
                build(args.registry,analysis,args.output,args.corpus_output,args.online)
        print(json.dumps(record), flush=True)
    progress['status'] = 'complete'
    atomic(args.output / 'progress.json', progress)
    if args.corpus_output: build(args.registry,analysis,args.output,args.corpus_output,args.online)


if __name__ == '__main__': main()
