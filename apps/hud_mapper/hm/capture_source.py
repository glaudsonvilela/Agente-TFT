"""Consented resident Rust capture, with original QPC time and bounded RGB delivery.

No SnippingTool, capture subprocess per screenshot, game-memory access or input
control. Only the owned native child communicates with WGC/D3D11.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import ctypes, json, os, queue, re, struct, subprocess, threading, time
from .dataset import Latest

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
    if header.get('type') in ('frame', 'preview'):
        w, h = header.get('width'), header.get('height')
        if type(w) is not int or type(h) is not int or not (0 < w <= 8192 and 0 < h <= 8192):
            raise ValueError('Dimensões físicas inválidas.')
        if size != w*h*3 or header.get('stride_bytes') != w*3 or header.get('pixel_format') != 'RGB8':
            raise ValueError('Formato ou stride incompatível; não completar pixels.')
        if type(header.get('capture_ns')) is not int or header['capture_ns'] <= 0:
            raise ValueError('Timestamp nativo ausente.')
        if header.get('type') == 'preview':
            source_w, source_h = header.get('source_width'), header.get('source_height')
            if (type(source_w) is not int or type(source_h) is not int or
                    not w <= source_w <= 8192 or not h <= source_h <= 8192 or w > 1280 or h > 720):
                raise ValueError('Geometria da prévia nativa inválida.')
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


def frame_clock(header, bridge, ready_ns, previous_compositor_ns=None):
    """Do not treat compositor timestamps as the application's receive clock.

    WGC time is retained verbatim, including anomalies. Scheduling uses the QPC
    acquired by our Rust worker before GPU readback, not a repaired WGC value.
    Application latencies therefore start at acquisition, NOT monitor scanout.
    """
    frequency = header.get('qpc_frequency')
    acquired, sent = header.get('qpc_acquired_ticks'), header.get('qpc_sent_ticks')
    if type(frequency) is not int or frequency != bridge.frequency:
        raise ValueError('Frequência nativa QPC incompatível.')
    if type(acquired) is not int or type(sent) is not int or not 0 < acquired <= sent:
        raise ValueError('Ordem dos timestamps de aquisição inválida.')
    acquired_ns = acquired * 1_000_000_000 // frequency
    sent_ns = sent * 1_000_000_000 // frequency
    acquire_due = bridge.convert(acquired_ns)
    if bridge.convert(sent_ns) > ready_ns + bridge.uncertainty_ns + 1_000_000:
        raise ValueError('Ponte QPC/recepção incompatível; não fabricar horários.')
    compositor_ns = header['capture_ns']
    compositor_due = bridge.convert(compositor_ns)
    regressed = previous_compositor_ns is not None and compositor_ns < previous_compositor_ns
    status = ('compositor_time_regressed' if regressed else
              'compositor_after_native_send' if compositor_ns > sent_ns + 100 else
              'ordering_consistent_not_physical_display_verified')
    consistent = status == 'ordering_consistent_not_physical_display_verified'
    return acquire_due, dict(
        source_time_basis='native_QPC_acquisition_before_readback',
        native_acquired_ns=acquired_ns, compositor_ns=compositor_ns,
        compositor_time_status=status, compositor_timestamp_regressed=regressed,
        compositor_to_rgb_ready_raw_ms=(ready_ns-compositor_due)/1e6,
        compositor_to_rgb_ready_ms=(ready_ns-compositor_due)/1e6 if consistent else None,
        native_acquire_to_rgb_ready_ms=(ready_ns-acquire_due)/1e6,
        original_timestamp_modified=False, physical_display_time_verified=False)


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
    def __init__(self, uri, configs, seconds, hz, *, consent=False, expected=None, log=None, preview_hz=None):
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
        self.pending = queue.Queue(maxsize=1); self.preview_frames = Latest() if preview_hz else None
        self.ready = None; self.end = None; self.error = None
        self.preview_received = 0
        self.source_replaced = 0; self.control_events = []; self.log_tail = []
        self.clock_anomalies = 0
        self.binary = native_path(configs)
        command = [self.binary, 'stream', '--kind', kind, '--id', identity,
                   '--seconds', str(seconds), '--hz', str(hz), '--consent']
        if preview_hz is not None:
            command += ['--preview-hz', str(preview_hz)]
        self.proc = spawn(command,
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
            last_id = {'frame': None, 'preview': None}
            first_preview_acquired = last_preview_compositor = None
            while not self.stop.is_set():
                header, pixels = read_packet(self.proc.stdout)
                kind = header.get('type')
                if kind == 'ready':
                    if self.ready is not None:raise ValueError('Ready duplicado.')
                    self.ready = header; self.ready_event.set()
                elif kind == 'error':
                    raise RuntimeError(header.get('error', 'Erro nativo.'))
                elif kind in ('frame', 'preview'):
                    if self.ready is None:raise ValueError('Frame anterior ao ready.')
                    if type(header.get('frame_id')) is not int or (last_id[kind] is not None and header['frame_id'] <= last_id[kind]):
                        raise ValueError('Identidade da captura retrocedeu.')
                    last_id[kind] = header['frame_id']
                    ready_ns = time.perf_counter_ns()
                    if kind == 'preview':
                        if self.preview_frames is None:raise ValueError('Prévia nativa inesperada.')
                        due, timing = frame_clock(header, self.bridge, ready_ns, last_preview_compositor)
                        acquired = timing['native_acquired_ns']
                        if first_preview_acquired is None:first_preview_acquired = acquired
                        last_preview_compositor = header['capture_ns']
                        capture = dict(header, bridge=self.bridge.metadata(), rgb_received_ns=ready_ns, timing=timing)
                        self.preview_frames.put(CapturedFrame(header['frame_id'],
                            (acquired-first_preview_acquired)/1e6, due, ready_ns,
                            header['width'], header['height'], pixels, header['geometry_segment'], capture))
                        self.preview_received += 1
                    else:
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
        first_acquired = last_acquired = last_compositor = None
        while not cancelled.is_set():
            try:header, pixels, ready_ns = self.pending.get(timeout=.1)
            except queue.Empty:
                if self.error:raise RuntimeError(self.error)
                if self.reader_done.is_set():break
                continue
            due, timing = frame_clock(header, self.bridge, ready_ns, last_compositor)
            acquired_ns = timing['native_acquired_ns']
            if last_acquired is not None and acquired_ns < last_acquired:
                raise ValueError('Relógio de aquisição retrocedeu.')
            if first_acquired is None:first_acquired = acquired_ns
            last_acquired = acquired_ns; last_compositor = header['capture_ns']
            if timing['compositor_to_rgb_ready_ms'] is None:self.clock_anomalies += 1
            record = dict(header, bridge=self.bridge.metadata(), source_queue_replaced=self.source_replaced,
                          rgb_received_ns=ready_ns, timing=timing)
            yield CapturedFrame(header['frame_id'], (acquired_ns-first_acquired)/1e6, due, ready_ns,
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
