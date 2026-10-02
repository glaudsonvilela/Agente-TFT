"""Consented resident Rust capture, with original QPC time and bounded RGB delivery.

No SnippingTool, capture subprocess per screenshot, game-memory access or input
control. Only the owned native child communicates with WGC/D3D11.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import ctypes, json, os, queue, re, struct, subprocess, threading, time

MAX_PAYLOAD = 128 * 1024**2


def capture_target(uri):
    match = re.fullmatch(r'capture://(monitor|window)/([0-9a-fA-F]{1,16})', str(uri))
    if not match or int(match[2], 16) == 0:
        raise ValueError('Fonte de captura inválida; selecione monitor/janela novamente.')
    return match[1], match[2].lower()


def native_path(configs):
    root = Path(configs).parent
    name = 'agente-tft-hm-capture.exe' if os.name == 'nt' else 'agente-tft-hm-capture'
    candidates = (root/'bin'/name, root/'tools/hm-capture-native/target/release'/name)
    return next((p for p in candidates if p.is_file()), candidates[0])


def list_targets(configs):
    if os.name != 'nt':
        raise RuntimeError('Captura nativa disponível somente no Windows.')
    binary = native_path(configs)
    result = subprocess.run([str(binary), 'list'], capture_output=True, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace')[-2000:])
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or len(rows) > 1024:
        raise ValueError('Lista de fontes inválida.')
    for row in rows:
        capture_target(f"capture://{row['kind']}/{row['id']}")
        if len(row['bounds']) != 4:
            raise ValueError('Geometria da fonte inválida.')
    return rows


def target_signature(target):
    # Handles alone can be reused. Recheck kind, PID and visible label on start.
    return tuple(target.get(k) for k in ('kind', 'id', 'pid', 'label', 'device'))


def read_exact(stream, count):
    if not 0 <= count <= MAX_PAYLOAD:
        raise ValueError('Orçamento IPC excedido.')
    out = bytearray()
    while len(out) < count:
        data = stream.read(count-len(out))
        if not data:
            raise EOFError('Captura terminou com pacote incompleto.')
        out.extend(data)
    return bytes(out)


def read_packet(stream):
    n = struct.unpack('<I', read_exact(stream, 4))[0]
    if not 0 < n <= 65536:
        raise ValueError('Cabeçalho IPC fora dos limites.')
    header = json.loads(read_exact(stream, n))
    size = header.get('bytes')
    if type(size) is not int or not 0 <= size <= MAX_PAYLOAD:
        raise ValueError('Tamanho de frame inválido.')
    if header.get('type') == 'frame':
        w, h = header.get('width'), header.get('height')
        if type(w) is not int or type(h) is not int or not (0 < w <= 8192 and 0 < h <= 8192):
            raise ValueError('Dimensões físicas inválidas.')
        if size != w*h*3 or header.get('stride_bytes') != w*3 or header.get('pixel_format') != 'RGB8':
            raise ValueError('Formato ou stride incompatível; não completar pixels.')
        if type(header.get('capture_ns')) is not int or header['capture_ns'] <= 0:
            raise ValueError('Timestamp nativo ausente.')
    elif size:
        raise ValueError('Payload inesperado para evento de controle.')
    return header, read_exact(stream, size)


class ClockBridge:
    """Bracket QPC against Python perf_counter, recording conversion uncertainty."""
    def __init__(self):
        if os.name != 'nt':
            raise RuntimeError('Relógio de captura requer Windows.')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        qpc, qpf = kernel.QueryPerformanceCounter, kernel.QueryPerformanceFrequency
        for function in (qpc, qpf):
            function.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
            function.restype = ctypes.c_int
        freq = ctypes.c_longlong()
        if not qpf(ctypes.byref(freq)) or freq.value <= 0:
            raise OSError('QPC indisponível.')
        candidates = []
        for _ in range(7):
            tick = ctypes.c_longlong(); before = time.perf_counter_ns()
            if not qpc(ctypes.byref(tick)):
                raise OSError('Falha ao ler QPC.')
            after = time.perf_counter_ns()
            native_ns = tick.value * 1_000_000_000 // freq.value
            candidates.append((after-before, (before+after)//2-native_ns))
        width, self.offset_ns = min(candidates)
        self.frequency = freq.value
        self.uncertainty_ns = (width+1)//2 + 100  # WGC timestamps are in 100 ns units.

    def convert(self, capture_ns):
        return int(capture_ns) + self.offset_ns

    def metadata(self):
        return dict(qpc_frequency=self.frequency, offset_ns=self.offset_ns,
                    uncertainty_ns=self.uncertainty_ns, method='bracketed_QPC_to_perf_counter_v1')


@dataclass(frozen=True)
class CapturedFrame:
    id: int
    pts_ms: float
    due_ns: int
    ready_ns: int
    width: int
    height: int
    rgb: bytes
    epoch: int
    capture: dict


class CaptureSource:
    def __init__(self, uri, configs, seconds, hz, *, consent=False, expected=None, log=None):
        if consent is not True:
            raise ValueError('Captura requer confirmação explícita da fonte.')
        if os.name != 'nt':
            raise RuntimeError('Captura nativa requer Windows; sem backend alternativo.')
        kind, identity = capture_target(uri)
        rows = list_targets(configs)
        current = next((x for x in rows if x['kind'] == kind and x['id'] == identity), None)
        if current is None:
            raise ValueError('Fonte selecionada não está disponível.')
        if expected is not None and target_signature(current) != target_signature(expected):
            raise ValueError('Identidade da fonte mudou; confirme a seleção novamente.')
        self.bridge = ClockBridge()
        from e1.protocol import spawn
        self.stop = threading.Event(); self.lock = threading.Lock(); self.closed = False
        self.pending = queue.Queue(maxsize=1); self.ready = None; self.end = None; self.error = None
        self.source_replaced = 0; self.control_events = []; self.log_tail = []
        self.binary = native_path(configs)
        self.proc = spawn([self.binary, 'stream', '--kind', kind, '--id', identity,
                           '--seconds', str(seconds), '--hz', str(hz), '--consent'],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        self.target = current; self.log = Path(log) if log else None
        self.reader_done = threading.Event(); self.ready_event = threading.Event()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.stderr = threading.Thread(target=self._stderr, daemon=True)
        self.reader.start(); self.stderr.start()
        if not self.ready_event.wait(18) or self.error or not self.ready:
            self.close()
            raise RuntimeError(self.error or 'Capturador não iniciou dentro do prazo.')
        if target_signature(self.ready['target']) != target_signature(current):
            self.close(); raise ValueError('Capturador retornou outra fonte.')
        if self.ready.get('qpc_frequency') != self.bridge.frequency:
            self.close(); raise ValueError('Relógios incompatíveis.')

    def _stderr(self):
        out = self.log.open('x', encoding='utf-8') if self.log else None
        try:
            for raw in iter(self.proc.stderr.readline, b''):
                text = raw.decode('utf-8', errors='replace')[-2000:]
                self.log_tail = (self.log_tail + [text])[-20:]
                if out:
                    out.write(text); out.flush()
        finally:
            if out:out.close()

    def _read(self):
        try:
            last_id = last_time = None
            while not self.stop.is_set():
                header, pixels = read_packet(self.proc.stdout)
                kind = header.get('type')
                if kind == 'ready':
                    if self.ready is not None:raise ValueError('Ready duplicado.')
                    self.ready = header; self.ready_event.set()
                elif kind == 'error':
                    raise RuntimeError(header.get('error', 'Erro nativo.'))
                elif kind == 'frame':
                    if self.ready is None:raise ValueError('Frame anterior ao ready.')
                    if last_id is not None and (header['frame_id'] <= last_id or header['capture_ns'] < last_time):
                        raise ValueError('Identidade/tempo da captura retrocedeu.')
                    last_id, last_time = header['frame_id'], header['capture_ns']
                    ready_ns = time.perf_counter_ns()
                    try:self.pending.get_nowait(); self.source_replaced += 1
                    except queue.Empty:pass
                    self.pending.put_nowait((header, pixels, ready_ns))
                elif kind == 'geometry_changed':
                    if len(self.control_events) >= 256:raise ValueError('Mudanças de geometria excederam o limite.')
                    self.control_events.append(header)
                elif kind == 'end':
                    self.end = header; break
                else:raise ValueError('Evento de captura não reconhecido.')
        except Exception as exc:
            if not self.stop.is_set():self.error = str(exc)
        finally:
            self.ready_event.set(); self.reader_done.set()

    def frames(self, cancelled, max_seconds=300):
        first = None
        while not cancelled.is_set():
            try:header, pixels, ready_ns = self.pending.get(timeout=.1)
            except queue.Empty:
                if self.error:raise RuntimeError(self.error)
                if self.reader_done.is_set():break
                continue
            if first is None:first = header['capture_ns']
            due = self.bridge.convert(header['capture_ns'])
            if due > ready_ns + self.bridge.uncertainty_ns + 1_000_000:
                raise ValueError('Frame com horário futuro incompatível com QPC.')
            record = dict(header, bridge=self.bridge.metadata(), source_queue_replaced=self.source_replaced,
                          rgb_received_ns=ready_ns, capture_to_rgb_ready_ms=(ready_ns-due)/1e6)
            yield CapturedFrame(header['frame_id'], (header['capture_ns']-first)/1e6, due, ready_ns,
                                header['width'], header['height'], pixels, header['geometry_segment'], record)
        if self.error and not cancelled.is_set():raise RuntimeError(self.error)
        if not cancelled.is_set() and (not self.end or not self.end.get('execution_complete')):
            raise RuntimeError('Sessão nativa incompleta.')

    def close(self):
        with self.lock:
            if self.closed:return
            self.closed = True; self.stop.set()
            try:
                if self.proc.poll() is None:
                    self.proc.stdin.write(b'stop\n'); self.proc.stdin.flush()
                    self.proc.wait(timeout=3)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                from e1.protocol import terminate
                terminate(self.proc)
            for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                try:stream.close()
                except (OSError, ValueError):pass
            if self.reader is not threading.current_thread():self.reader.join(2)
            if self.stderr is not threading.current_thread():self.stderr.join(2)
