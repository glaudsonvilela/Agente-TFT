"""Explicit X11 monitor capture for the Ubuntu replay laboratory.

This is a screen source: the video stays in the user's player. The bounded
queue retains only the newest frame, exactly as the Windows capture does.
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time

from .capture_source import CapturedFrame, capture_target, target_signature
from .dataset import Latest


MONITOR = re.compile(r'^\s*(\d+):\s+\S+\s+(\d+)/\d+x(\d+)/\d+([+-]\d+)([+-]\d+)\s+(\S+)\s*$')


def list_x11_targets():
    if not os.environ.get('DISPLAY'):
        raise RuntimeError('Sessão X11 indisponível; entre no Ubuntu com Xorg para este MVP.')
    result = subprocess.run(['xrandr', '--listmonitors'], capture_output=True, text=True,
                            timeout=5, check=True)
    rows = []
    for line in result.stdout.splitlines()[1:]:
        match = MONITOR.match(line)
        if not match:
            continue
        number, width, height, x, y, name = match.groups()
        x, y, width, height = map(int, (x, y, width, height))
        if width <= 0 or height <= 0:
            continue
        rows.append(dict(kind='monitor', id=format(int(number)+1, 'x'),
                         pid=None, label=name, device=name, adapter='X11',
                         bounds=[x, y, x+width, y+height], candidate_tft=False))
    if not rows:
        raise RuntimeError('Nenhum monitor X11 disponível.')
    return rows


class LinuxX11CaptureSource:
    def __init__(self, uri, configs, seconds, hz, *, consent=False, expected=None,
                 log=None, preview_hz=None, preview_size=None):
        if consent is not True:
            raise ValueError('Confirme a captura do monitor.')
        kind, identity = capture_target(uri)
        if kind != 'monitor':
            raise ValueError('O MVP Ubuntu captura apenas monitores X11.')
        target = next((row for row in list_x11_targets() if row['id'] == identity), None)
        if target is None or (expected is not None and
                              target_signature(target) != target_signature(expected)):
            raise ValueError('O monitor selecionado mudou; selecione novamente.')
        x, y, right, bottom = target['bounds']
        width, height = right-x, bottom-y
        self.target = target
        self.ready = dict(target=target, backend='ffmpeg_x11grab', width=width, height=height)
        self.end = None
        self.error = None
        self.source_replaced = 0
        self.preview_received = 0
        self.clock_anomalies = 0
        self.control_events = []
        self.last_preview_received_ns = None
        self.preview_frames = Latest() if preview_hz else None
        self.pending = queue.Queue(maxsize=1)
        self.stop = threading.Event()
        self.reader_done = threading.Event()
        self.closed = False
        self.lock = threading.Lock()
        self.log_tail = []
        self.frame_bytes = width*height*3
        self.capture_epoch_ns = time.perf_counter_ns()
        # On four-core desktops, leave CPU room for the player and the UI.
        desktop_cap = 15 if (os.cpu_count() or 1) <= 4 else 20
        self.frame_rate = min(4 if self.preview_frames else desktop_cap,
                              max(4 if self.preview_frames else 2, int(round(hz))))
        source = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
                   '-f', 'x11grab', '-draw_mouse', '0', '-video_size', f'{width}x{height}',
                   '-framerate']
        command = source + [str(self.frame_rate), '-i', f'{os.environ["DISPLAY"]}+{x},{y}',
                            '-an', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1']
        self.proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, bufsize=0)
        self.preview_proc = None
        self.preview_reader = None
        self.preview_stderr = None
        if self.preview_frames is not None:
            target_width, target_height = preview_size or (960, 540)
            scale = min(1.0, target_width / width, target_height / height)
            self.preview_width = max(1, round(width * scale))
            self.preview_height = max(1, round(height * scale))
            self.preview_frame_bytes = self.preview_width * self.preview_height * 3
            self.preview_rate = min(desktop_cap, max(2, int(round(preview_hz))))
            preview_command = source + [str(self.preview_rate), '-i',
                f'{os.environ["DISPLAY"]}+{x},{y}', '-an', '-filter_threads', '1',
                '-vf', f'scale={self.preview_width}:{self.preview_height}:flags=fast_bilinear',
                '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1']
            try:
                self.preview_proc = subprocess.Popen(preview_command,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            except Exception:
                self.proc.terminate()
                self.proc.wait(timeout=2)
                self.proc.stdout.close()
                self.proc.stderr.close()
                raise
            self.preview_reader = threading.Thread(target=self._read_preview, daemon=True,
                                                   name='tft-x11-preview')
            self.preview_stderr = threading.Thread(target=self._stderr,
                args=(self.preview_proc,), daemon=True, name='tft-x11-preview-stderr')
        self.reader = threading.Thread(target=self._read, daemon=True,
                                       name='tft-x11-capture')
        self.stderr = threading.Thread(target=self._stderr, args=(self.proc,), daemon=True,
                                       name='tft-x11-stderr')
        self.reader.start()
        self.stderr.start()
        if self.preview_reader:
            self.preview_reader.start()
            self.preview_stderr.start()

    def _stderr(self, proc):
        for raw in iter(proc.stderr.readline, b''):
            self.log_tail = (self.log_tail + [raw.decode('utf-8', 'replace')[-1000:]])[-20:]

    @staticmethod
    def _read_exact(proc, size):
        pixels = bytearray(size)
        view = memoryview(pixels)
        offset = 0
        while offset < size:
            received = proc.stdout.readinto(view[offset:])
            if not received:
                return None
            offset += received
        return bytes(pixels)

    def _read(self):
        index = 0
        try:
            while not self.stop.is_set():
                pixels = self._read_exact(self.proc, self.frame_bytes)
                if pixels is None:
                    break
                now = time.perf_counter_ns()
                frame = CapturedFrame(index, (now-self.capture_epoch_ns)/1e6, now, now,
                                      self.ready['width'], self.ready['height'], pixels, 0,
                                      dict(backend='ffmpeg_x11grab', capture_ns=now,
                                           frame_id=index, target=self.target['device']))
                try:
                    self.pending.get_nowait()
                    self.source_replaced += 1
                except queue.Empty:
                    pass
                self.pending.put_nowait(frame)
                index += 1
            if not self.stop.is_set() and self.proc.poll() not in (0, None):
                self.error = ''.join(self.log_tail)[-1200:] or 'Captura X11 encerrada.'
        except Exception as exc:
            if not self.stop.is_set():
                self.error = str(exc)
        finally:
            self.reader_done.set()

    def _read_preview(self):
        index = 0
        try:
            while not self.stop.is_set():
                pixels = self._read_exact(self.preview_proc, self.preview_frame_bytes)
                if pixels is None:
                    break
                now = time.perf_counter_ns()
                frame = CapturedFrame(index, (now-self.capture_epoch_ns)/1e6, now, now,
                                      self.preview_width, self.preview_height, pixels, 0,
                                      dict(backend='ffmpeg_x11grab_scaled_preview', capture_ns=now,
                                           frame_id=index, target=self.target['device']))
                self.preview_frames.put(frame)
                self.preview_received += 1
                self.last_preview_received_ns = now
                index += 1
            if not self.stop.is_set():
                self.error = ''.join(self.log_tail)[-1200:] or 'Prévia X11 encerrada.'
        except Exception as exc:
            if not self.stop.is_set():
                self.error = str(exc)

    def frames(self, cancelled, max_seconds=300):
        first = None
        reached_duration = False
        while not cancelled.is_set():
            try:
                frame = self.pending.get(timeout=.1)
            except queue.Empty:
                if self.error:
                    raise RuntimeError(self.error)
                if self.reader_done.is_set():
                    break
                continue
            if first is None:
                first = frame.due_ns
            pts_ms = (frame.due_ns-first)/1e6
            if pts_ms > max_seconds*1000:
                reached_duration = True
                break
            yield CapturedFrame(frame.id, frame.pts_ms, frame.due_ns, frame.ready_ns,
                                frame.width, frame.height, frame.rgb, frame.epoch,
                                frame.capture)
        if self.error and not cancelled.is_set():
            raise RuntimeError(self.error)
        if not cancelled.is_set() and not reached_duration:
            raise RuntimeError('A captura X11 terminou antes do prazo; verifique o monitor e o vídeo.')

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.stop.set()
            for proc in (self.proc, self.preview_proc):
                if proc is None:
                    continue
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                proc.stdout.close()
                proc.stderr.close()
            for thread in (self.reader, self.stderr, self.preview_reader,
                           self.preview_stderr):
                if thread is not None and thread is not threading.current_thread():
                    thread.join(2)
