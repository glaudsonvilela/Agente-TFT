"""Closed local-file source. FFmpeg showinfo PTS, no fps filter, no screen/live URL."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json, math, queue, re, subprocess, threading, time
from .protocol import spawn, terminate

@dataclass(frozen=True)
class Frame:
    id: int
    pts_ms: float
    due_ns: int
    ready_ns: int
    width: int
    height: int
    rgb: bytes
    epoch: int = 0


def local_video(path):
    p = Path(path).expanduser()
    if p.is_symlink() or not p.is_file():
        raise ValueError('Selecione um arquivo local regular, já encerrado.')
    if p.suffix.lower() not in {'.mp4', '.mkv', '.mov', '.avi', '.webm'}:
        raise ValueError('Formato de vídeo local não suportado.')
    return p.resolve()


def probe(path, ffprobe):
    out = subprocess.run([str(ffprobe), '-v', 'error', '-protocol_whitelist', 'file',
                          '-select_streams', 'v:0', '-show_entries',
                          'stream=width,height,color_transfer:format=duration', '-of', 'json', str(path)],
                         capture_output=True, timeout=20, check=True,
                         **({'creationflags': subprocess.CREATE_NO_WINDOW} if __import__('os').name == 'nt' else {}))
    d = json.loads(out.stdout)
    stream = d['streams'][0]
    w, h = int(stream['width']), int(stream['height'])
    if not 1 <= w <= 3840 or not 1 <= h <= 2160:
        raise ValueError('Resolução excede 3840x2160.')
    if stream.get('color_transfer') in {'smpte2084', 'arib-std-b67'}:
        raise ValueError('HDR ainda não suportado; nenhuma conversão silenciosa para SDR.')
    return w, h


class VideoSource:
    def __init__(self, path, ffmpeg='ffmpeg', ffprobe='ffprobe'):
        self._close_lock = threading.Lock()
        self.closed = False
        self.path = local_video(path)
        self.w, self.h = probe(self.path, ffprobe)
        self.identity = (self.path.stat().st_size, self.path.stat().st_mtime_ns)
        self.proc = spawn([ffmpeg, '-nostdin', '-v', 'info', '-threads', '2',
                           '-filter_threads', '1', '-protocol_whitelist', 'file', '-noautorotate', '-i', self.path,
                           '-map', '0:v:0', '-an', '-sn', '-dn', '-vf', 'format=rgb24,showinfo',
                           '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.pts = queue.Queue(maxsize=64)
        self.stop = threading.Event()
        self.log_tail = []
        self.thread = threading.Thread(target=self._metadata, daemon=True)
        self.thread.start()

    def _metadata(self):
        try:
            for raw in iter(self.proc.stderr.readline, b''):
                line = raw.decode('utf-8', errors='replace')
                if len(self.log_tail) == 20:
                    self.log_tail.pop(0)
                self.log_tail.append(line[-1000:])
                m = re.search(r'\bn:\s*(\d+)\s+pts:\s*\S+\s+pts_time:([\-\d.eE+]+).*?\bs:(\d+)x(\d+)', line)
                if m:
                    record = (int(m[1]), float(m[2]) * 1000, int(m[3]), int(m[4]))
                    while not self.stop.is_set():
                        try:
                            self.pts.put(record, timeout=.1)
                            break
                        except queue.Full:
                            continue
        except Exception as exc:
            self.log_tail.append(str(exc))

    def frames(self, cancelled, max_seconds=30):
        first = last = None
        origin = None
        count = self.w * self.h * 3
        i = 0
        while not cancelled.is_set():
            chunks = bytearray()
            while len(chunks) < count:
                chunk = self.proc.stdout.read(count - len(chunks))
                if not chunk:
                    break
                chunks.extend(chunk)
            if not chunks:
                code = self.proc.wait(timeout=5)
                if code:
                    raise RuntimeError('FFmpeg falhou: ' + ''.join(self.log_tail)[-1500:])
                break
            if len(chunks) != count:
                raise ValueError('Frame RGB incompleto; não completar com zeros.')
            try:
                n, pts, w, h = self.pts.get(timeout=10)
            except queue.Empty:
                raise TimeoutError('PTS não recebido do decodificador')
            if n != i or (w, h) != (self.w, self.h) or not math.isfinite(pts) or pts < 0:
                raise ValueError('Identidade, geometria ou PTS de frame incompatível')
            if last is not None and pts < last:
                raise ValueError('PTS retrocede; nova época/reinício necessário')
            now = time.perf_counter_ns()
            if first is None:
                first, origin = pts, now
            relative = pts - first
            if relative > max_seconds * 1000:
                break
            due = origin + int(relative * 1_000_000)
            if cancelled.wait(max(0, (due - now) / 1e9)):
                break
            pixels = bytes(chunks)
            yield Frame(i, pts, due, time.perf_counter_ns(), self.w, self.h, pixels)
            last = pts
            i += 1
        if self.identity != (self.path.stat().st_size, self.path.stat().st_mtime_ns):
            raise ValueError('Arquivo de origem alterado durante a sessão')

    def close(self):
        with self._close_lock:
            if self.closed:
                return
            self.closed = True
            self.stop.set()
            terminate(self.proc)
            for stream in (self.proc.stdout, self.proc.stderr):
                if stream:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass


def fixture_frames(cancelled, max_seconds=12, fps=4):
    """Clocked fixture metadata; no fake video, screenshot or OCR produced."""
    origin = time.perf_counter_ns()
    for i in range(int(max_seconds * fps)):
        due = origin + int(i / fps * 1e9)
        if cancelled.wait(max(0, (due - time.perf_counter_ns()) / 1e9)):
            return
        yield Frame(i, i * 1000 / fps, due, time.perf_counter_ns(), 0, 0, b'')
