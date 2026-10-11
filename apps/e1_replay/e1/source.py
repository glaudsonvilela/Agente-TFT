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


@dataclass(frozen=True)
class JPEGFrame:
    id: int
    pts_ms: float
    jpeg: bytes


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
    def __init__(self, path, ffmpeg='ffmpeg', ffprobe='ffprobe', fps=None,
                 preview_hz=None, preview_size=(960, 540)):
        self._close_lock = threading.Lock()
        self.closed = False
        self.path = local_video(path)
        self.w, self.h = probe(self.path, ffprobe)
        self.identity = (self.path.stat().st_size, self.path.stat().st_mtime_ns)
        if fps is not None and not 1 <= fps <= 60:
            raise ValueError('Replay FPS outside decoding budget')
        filters = f'fps={fps},format=rgb24,showinfo' if fps is not None else 'format=rgb24,showinfo'
        self.proc = spawn([ffmpeg, '-nostdin', '-v', 'info', '-threads', '2',
                           '-filter_threads', '1', '-protocol_whitelist', 'file', '-noautorotate', '-i', self.path,
                           '-map', '0:v:0', '-an', '-sn', '-dn', '-vf', filters,
                           '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.pts = queue.Queue(maxsize=64)
        self.stop = threading.Event()
        self.log_tail = []
        self.thread = threading.Thread(target=self._metadata, daemon=True)
        self.thread.start()
        self.preview_frames = None
        self.preview_received = 0
        self.preview_replaced = 0
        self.last_preview_received_ns = None
        self.preview_proc = None
        self.preview_thread = None
        self._preview_command = None
        if preview_hz is not None:
            if not 1 <= preview_hz <= 60:
                raise ValueError('Preview FPS outside decoding budget')
            preview_width, preview_height = preview_size
            if not 160 <= preview_width <= 1280 or not 90 <= preview_height <= 720:
                raise ValueError('Preview size outside decoding budget')
            self.preview_hz = preview_hz
            self.preview_frames = queue.Queue(maxsize=1)
            self._preview_command = [ffmpeg, '-nostdin', '-v', 'error', '-threads', '2',
                '-filter_threads', '1', '-protocol_whitelist', 'file', '-noautorotate',
                '-re', '-i', self.path, '-map', '0:v:0', '-an', '-sn', '-dn',
                '-vf', f'fps={preview_hz},scale={preview_width}:{preview_height}:flags=fast_bilinear',
                '-fps_mode', 'passthrough', '-q:v', '6', '-f', 'mjpeg', 'pipe:1']

    def _start_preview(self):
        # The analysis clock starts at its first decoded RGB frame. Starting
        # the independent MJPEG decoder here keeps source PTS in step with
        # analysis instead of letting the preview run ahead during setup.
        with self._close_lock:
            if self.closed or self.preview_proc is not None or self._preview_command is None:
                return
            self.preview_proc = spawn(self._preview_command,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
            self.preview_thread = threading.Thread(target=self._preview_jpegs, daemon=True)
            self.preview_thread.start()

    def _preview_jpegs(self):
        """Pass through native JPEGs; only the newest display frame is retained."""
        buffer = bytearray()
        index = 0
        try:
            while not self.stop.is_set():
                chunk = self.preview_proc.stdout.read(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
                while True:
                    start = buffer.find(b'\xff\xd8')
                    if start < 0:
                        buffer.clear()
                        break
                    end = buffer.find(b'\xff\xd9', start + 2)
                    if end < 0:
                        if start:
                            del buffer[:start]
                        break
                    jpeg = bytes(buffer[start:end + 2])
                    del buffer[:end + 2]
                    frame = JPEGFrame(index, index * 1000 / self.preview_hz, jpeg)
                    if self.preview_frames.full():
                        try:
                            self.preview_frames.get_nowait()
                            self.preview_replaced += 1
                        except queue.Empty:
                            pass
                    self.preview_frames.put_nowait(frame)
                    self.preview_received += 1
                    self.last_preview_received_ns = time.perf_counter_ns()
                    index += 1
                if len(buffer) > 4 * 1024 * 1024:
                    raise ValueError('Oversized MJPEG preview frame')
        except Exception as exc:
            self.log_tail.append('Preview: ' + str(exc))

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
                self._start_preview()
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
            if self.preview_proc is not None:
                terminate(self.preview_proc)
            for stream in (self.proc.stdout, self.proc.stderr):
                if stream:
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass
            if self.preview_proc is not None:
                for stream in (self.preview_proc.stdout, self.preview_proc.stderr):
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
