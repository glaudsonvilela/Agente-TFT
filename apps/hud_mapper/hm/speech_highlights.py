"""Save successful coach speech with nearby preview frames for a local montage.

The live path reuses JPEGs already encoded for the studio. All disk writes and
video encoding run outside capture, advice, and voice playback threads.
"""
from __future__ import annotations

from collections import deque
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading


class SpeechHighlightsRecorder:
    def __init__(self, session_dir, *, max_moments=240):
        self.root = Path(session_dir) / 'speech-highlights'
        self.root.mkdir(parents=True, exist_ok=False)
        self.max_moments = max_moments
        self.lock = threading.RLock()
        self.recent = deque(maxlen=180)
        self.active = []
        self.jobs = queue.Queue(maxsize=8)
        self.rows = []
        self.next_index = 0
        self.last_preview_ns = 0
        self.closed = False
        self.error = None
        self.writer = threading.Thread(target=self._writer, name='tft-speech-moment-writer', daemon=True)
        self.writer.start()

    def preview(self, jpeg, at_ns, source_ms):
        if not isinstance(jpeg, bytes) or len(jpeg) > 512_000:
            return
        with self.lock:
            if self.closed or at_ns-self.last_preview_ns < 100_000_000:
                return
            self.last_preview_ns = at_ns
            row = (int(at_ns), float(source_ms), jpeg)
            self.recent.append(row)
            while self.recent and at_ns-self.recent[0][0] > 20_000_000_000:
                self.recent.popleft()
            for moment in list(self.active):
                if moment['from_ns'] <= at_ns <= moment['until_ns']:
                    moment['frames'].append(row)
                if at_ns >= moment['until_ns']:
                    self._queue(moment)
                    self.active.remove(moment)

    def spoken(self, wav, text, metadata, started_ns, ended_ns):
        """Called only after playback succeeds; never waits for a disk write."""
        if not isinstance(wav, bytes) or not wav or not text:
            return
        with self.lock:
            if self.closed or self.next_index >= self.max_moments:
                return
            self.next_index += 1
            beginning = max(0, int(started_ns)-2_000_000_000)
            ending = int(ended_ns)+2_000_000_000
            moment = dict(index=self.next_index, text=str(text)[:500],
                          metadata=dict(metadata or {}), wav=wav,
                          speech_start_ns=int(started_ns), speech_end_ns=int(ended_ns),
                          from_ns=beginning, until_ns=ending,
                          frames=[row for row in self.recent if beginning <= row[0] <= ending])
            self.active.append(moment)

    def _queue(self, moment):
        try:
            self.jobs.put_nowait(moment)
        except queue.Full:
            self.error = 'speech_highlight_write_queue_full'

    def _writer(self):
        try:
            while True:
                moment = self.jobs.get()
                if moment is None:
                    break
                folder = self.root / 'clips' / f"{moment['index']:04d}"
                frames_dir = folder / 'frames'
                frames_dir.mkdir(parents=True)
                (folder / 'voice.wav').write_bytes(moment['wav'])
                frames = []
                for index, (at_ns, source_ms, jpeg) in enumerate(moment['frames']):
                    name = f'{index:05d}.jpg'
                    (frames_dir / name).write_bytes(jpeg)
                    frames.append(dict(image=f'frames/{name}',at_ns=at_ns,source_ms=source_ms))
                row = dict(index=moment['index'], text=moment['text'],
                           metadata=moment['metadata'], audio=f'clips/{moment["index"]:04d}/voice.wav',
                           frames=frames, speech_start_ns=moment['speech_start_ns'],
                           speech_end_ns=moment['speech_end_ns'],
                           ground_truth=False, selection='successful_playback')
                (folder / 'moment.json').write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n')
                self.rows.append(row)
        except Exception as exc:
            self.error = f'{type(exc).__name__}:{exc}'

    def seal(self):
        with self.lock:
            if self.closed:
                return self.root / 'manifest.json'
            self.closed = True
            for moment in self.active:
                self._queue(moment)
            self.active.clear()
        self.jobs.put(None, timeout=5)
        self.writer.join(30)
        if self.writer.is_alive():
            raise RuntimeError('speech highlight writer did not stop')
        if self.error:
            raise RuntimeError(self.error)
        manifest = dict(schema_version=1, role='successful_spoken_moments',
                        moments=sorted(self.rows,key=lambda row:row['index']),
                        montage='pending', clips=len(self.rows))
        path = self.root / 'manifest.json'
        path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        return path


def _seconds(at_ns, origin_ns):
    return max(0., (at_ns-origin_ns)/1e9)


def _image_overlay(path, text):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new('RGBA',(1280,720),(0,0,0,0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((28,566,1252,704),radius=22,fill=(13,12,27,226),outline=(154,132,245,210),width=2)
    font_path = next((candidate for candidate in (
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('C:/Windows/Fonts/arial.ttf')) if candidate.is_file()), None)
    font = ImageFont.truetype(str(font_path),28) if font_path else ImageFont.load_default()
    label = 'AGENTE TFT · COACH'
    draw.text((54,582),label,font=font,fill=(174,150,255))
    words = text.split()
    lines=[];line=''
    for word in words:
        trial=(line+' '+word).strip()
        if draw.textlength(trial,font=font)>1130 and line:
            lines.append(line);line=word
        else: line=trial
    if line:lines.append(line)
    for i,row in enumerate(lines[:2]):
        draw.text((54,623+i*33),row,font=font,fill=(255,255,255))
    image.save(path)


def _ffmpeg_binary():
    if sys.platform != 'win32':
        return 'ffmpeg'
    bundled = Path(getattr(sys, '_MEIPASS', Path(sys.executable).resolve().parent)) / 'ffmpeg' / 'ffmpeg.exe'
    if not bundled.is_file():
        raise FileNotFoundError('Codificador de vídeo não incluído no aplicativo.')
    return str(bundled)


def _run_ffmpeg(cmd):
    subprocess.run(cmd, check=True, timeout=180,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def compile_highlights(session_dir, *, ffmpeg=None, max_clips=30):
    """Build one MP4 from saved moments; safe to rerun after a failed render."""
    root = Path(session_dir) / 'speech-highlights'
    ffmpeg = ffmpeg or _ffmpeg_binary()
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    scored = [row for row in manifest['moments']
              if row['metadata'].get('decision_key') and row['frames']]
    def priority(row):
        importance = row['metadata'].get('importance')
        if isinstance(importance, int):
            return importance
        family = row['metadata'].get('family')
        kind = row['metadata'].get('kind')
        return (5 if kind == 'combat' else
                4 if family in ('roll', 'positioning', 'equipment', 'item') else
                3 if family in ('composition', 'level', 'synergy', 'buy') else 2)
    selected = []
    seen_keys = set()
    economy_count = 0
    for row in sorted(scored, key=lambda row: (-priority(row), row['index'])):
        key = row['metadata']['decision_key']
        family = row['metadata'].get('family')
        if key in seen_keys or family == 'economy' and economy_count >= 2:
            continue
        seen_keys.add(key)
        economy_count += family == 'economy'
        selected.append(row)
        if len(selected) >= max_clips:
            break
    scored = sorted(selected, key=lambda row: row['index'])
    manifest['selected_moments'] = [row['index'] for row in scored]
    rendered=[]
    for row in scored:
        folder = root / 'clips' / f"{row['index']:04d}"
        frames = row['frames']
        if not frames:
            continue
        beginning = frames[0]['at_ns']
        duration = max(2., _seconds(frames[-1]['at_ns'], beginning)+.12,
                       _seconds(row['speech_end_ns'], beginning)+.5)
        ffconcat = folder / 'frames.ffconcat'
        lines=['ffconcat version 1.0']
        for i,frame in enumerate(frames):
            lines.append(f"file '{frame['image']}'")
            if i+1<len(frames):
                delta=_seconds(frames[i+1]['at_ns'],frame['at_ns'])
                lines.append(f'duration {max(.04,min(.6,delta)):.4f}')
        lines.append(f"file '{frames[-1]['image']}'")
        ffconcat.write_text('\n'.join(lines)+'\n')
        overlay=folder/'coach.png';_image_overlay(overlay,row['text'])
        audio_delay=round(_seconds(row['speech_start_ns'],beginning)*1000)
        target=folder/'moment.mp4'
        cmd=[ffmpeg,'-hide_banner','-loglevel','error','-y','-safe','0','-f','concat',
             '-i',str(ffconcat),'-i',str(folder/'voice.wav'),'-loop','1','-i',str(overlay),
             '-filter_complex',f'[0:v]fps=12,scale=1280:720,tpad=stop_mode=clone:stop_duration=30,format=yuv420p[base];'
                               f'[base][2:v]overlay=shortest=1[v];'
                               f'[1:a]adelay={audio_delay}:all=1,apad[a]',
             '-map','[v]','-map','[a]','-t',f'{duration:.3f}',
             '-c:v','libx264','-preset','veryfast','-crf','25','-pix_fmt','yuv420p',
             '-c:a','aac','-ac','2','-ar','44100','-b:a','128k','-movflags','+faststart',str(target)]
        _run_ffmpeg(cmd)
        rendered.append(target)
    if not rendered:
        manifest['montage']='no_coach_speech_with_preview'
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        return None
    concat=root/'montage.ffconcat'
    concat.write_text('ffconcat version 1.0\n'+''.join(
        f"file '{path.relative_to(root).as_posix()}'\n" for path in rendered))
    output=root/'melhores-momentos-agente-tft.mp4'
    _run_ffmpeg([ffmpeg,'-hide_banner','-loglevel','error','-y','-safe','0','-f','concat',
                 '-i',str(concat),'-c','copy',str(output)])
    manifest['montage']='complete';manifest['montage_file']=output.name
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return output
