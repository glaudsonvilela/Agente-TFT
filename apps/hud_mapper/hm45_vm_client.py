"""Windows supervisor and typed proxies for the WSL analysis core."""

from __future__ import annotations

from pathlib import Path
import json
import os
import queue
import secrets
import socket
import subprocess
import sys
import threading
import time

from hm45_protocol import encode_rgb, recv_packet, send_packet


class VMCore:
    def __init__(self, distro: str, log: Path, command: list[str] | None = None):
        if command is None and os.name != "nt":
            raise RuntimeError("A VM WSL 2 requer Windows.")
        self.token = secrets.token_hex(32)
        self.closed = False
        self.local = threading.local()
        self.connections: list[socket.socket] = []
        self.lock = threading.Lock()
        self.log = Path(log)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        cmd = command or ["wsl.exe", "--distribution", distro, "--exec", "python3",
                          "/opt/agente-tft/hm45_core_server.py", "serve"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, bufsize=0, creationflags=flags)
        lines: queue.Queue[str] = queue.Queue(maxsize=1)

        def read_ready():
            try:
                lines.put(self.proc.stdout.readline(65537).decode("utf-8", errors="replace"))
            except Exception:
                lines.put("")

        def read_errors():
            with self.log.open("a", encoding="utf-8") as file:
                for raw in iter(self.proc.stderr.readline, b""):
                    file.write(raw.decode("utf-8", errors="replace")[-2000:])
                    file.flush()

        threading.Thread(target=read_ready, daemon=True).start()
        threading.Thread(target=read_errors, daemon=True).start()
        try:
            self.proc.stdin.write((self.token + "\n").encode("ascii"))
            self.proc.stdin.flush()
            line = lines.get(timeout=120)
            if len(line) > 65536 or not line:
                raise RuntimeError("O serviço da VM não iniciou. Se surgiram janelas Remote Desktop/RemoteApp, "
                                   "abra 'Configurar VM do Agente TFT' e escolha 'VM sem WSLg'. "
                                   f"Log do núcleo: {self.log}")
            ready = json.loads(line)
            if not ready.get("ready") or ready.get("host") != "127.0.0.1" or not 0 < ready.get("port", 0) < 65536:
                raise RuntimeError("Handshake da VM incompatível.")
            self.port = ready["port"]
            self.ready = ready
            self._socket()  # Prove Windows -> WSL loopback before returning.
        except Exception:
            self.close()
            raise

    def _socket(self) -> socket.socket:
        sock = getattr(self.local, "socket", None)
        if sock is not None:
            return sock
        end = time.monotonic() + 10
        while True:
            try:
                sock = socket.create_connection(("127.0.0.1", self.port), timeout=10)
                break
            except OSError:
                if time.monotonic() >= end:
                    raise RuntimeError("A porta IP local da VM não respondeu.")
                time.sleep(0.1)
        sock.settimeout(30)
        send_packet(sock, {"op": "hello", "token": self.token})
        hello, _ = recv_packet(sock)
        if not hello.get("ok") or hello.get("ready", {}).get("version") != self.ready.get("version"):
            sock.close()
            raise RuntimeError("Autenticação ou versão do núcleo incompatível.")
        with self.lock:
            if self.closed:
                sock.close()
                raise RuntimeError("A VM já foi encerrada.")
            self.connections.append(sock)
        self.local.socket = sock
        self.local.sequence = 0
        return sock

    def request(self, op: str, frame_id: int, width: int = 0, height: int = 0,
                rgb: bytes = b"", **fields) -> tuple[dict, float]:
        if self.closed:
            raise RuntimeError("A VM já foi encerrada.")
        sock = self._socket()
        self.local.sequence += 1
        started = time.perf_counter_ns()
        codec, payload = (encode_rgb(rgb, width, height) if rgb else ("none", b""))
        encoded = time.perf_counter_ns()
        header = dict(op=op, request_id=self.local.sequence, frame_id=frame_id,
                      width=width, height=height, codec=codec, **fields)
        send_packet(sock, header, payload)
        response, _ = recv_packet(sock)
        if response.get("request_id") != self.local.sequence:
            raise RuntimeError("Resposta IP pertence a outra requisição.")
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error", "Falha no núcleo."))[:500])
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Resposta IP sem resultado estruturado.")
        result["vm_transport"] = dict(codec=codec,raw_bytes=len(rgb),wire_bytes=len(payload),
            encode_ms=(encoded-started)/1e6,roundtrip_ms=(time.perf_counter_ns()-encoded)/1e6,
            core_ms=float(response.get("core_ms") or 0.0))
        return result, float(response.get("core_ms") or 0.0)

    def model(self, frame_id: int, width: int, height: int, small_rgb: bytes,
              resize_ms: float) -> dict:
        sock = self._socket()
        self.local.sequence += 1
        started = time.perf_counter_ns()
        send_packet(sock, dict(op="model", request_id=self.local.sequence, frame_id=frame_id,
                               width=width, height=height, codec="rgb8-small",
                               resize_ms=resize_ms), small_rgb)
        response, _ = recv_packet(sock)
        if response.get("request_id") != self.local.sequence or not response.get("ok"):
            raise RuntimeError(str(response.get("error", "L3 sem resposta válida."))[:500])
        result = response["result"]
        result["vm_transport"] = dict(codec="rgb8-small",wire_bytes=len(small_rgb),
            roundtrip_ms=(time.perf_counter_ns()-started)/1e6,
            core_ms=float(response.get("core_ms") or 0.0))
        return result

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            connections = list(self.connections)
            self.connections.clear()
        if getattr(self, "port", None) and self.proc.poll() is None:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=1) as control:
                    control.settimeout(2)
                    send_packet(control, {"op": "hello", "token": self.token})
                    hello, _ = recv_packet(control)
                    if hello.get("ok"):
                        send_packet(control, {"op": "shutdown", "request_id": 0})
                        recv_packet(control)
            except (OSError, EOFError, ValueError):
                pass
        for sock in connections:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        if self.proc.poll() is None:
            try:
                self.proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                stream.close()
            except OSError:
                pass


class RemoteNativeWorker:
    def __init__(self, core: VMCore, kind: str):
        if kind not in ("reader", "hp"):
            raise ValueError("Tipo de worker remoto inválido.")
        self.core = core
        self.kind = kind
        self.ready = core.ready[kind + "_ready"]

    def request(self, header: dict, payload: bytes = b"", timeout: int = 12) -> dict:
        del timeout  # The connection has its own bounded socket deadline.
        op = "reference" if header.get("op") == "reference" else self.kind
        result, network_core_ms = self.core.request(op, header["id"], header["width"], header["height"],
                                                     payload, source_ms=header.get("source_ms", 0),
                                                     include_shop=header.get("include_shop", True))
        result["vm_core_ms"] = network_core_ms
        return result

    def close(self):
        pass  # The owner Session closes the shared VMCore after all consumers stop.


class RemoteObserver:
    def __init__(self, core: VMCore, metadata: str):
        from hm.core import load_json, sha
        self.core = core
        self.path = Path(metadata)
        info = load_json(self.path, 65536)
        if info.get("schema_version") != 2 or info.get("coordinate_format") != "normalized_tlbr":
            raise ValueError("Metadados L3 incompatíveis.")
        self.meta_hash = sha(self.path)
        self.hash = sha(self.path.parent / "candidate-model.onnx")
        if (self.meta_hash != core.ready.get("model_metadata_sha256") or
                self.hash != core.ready.get("model_sha256")):
            raise ValueError("Modelo L3 da VM não corresponde ao pacote Windows.")
        self.load_ms = 0.0

    def observe(self, frame):
        from PIL import Image
        start = time.perf_counter_ns()
        small = Image.frombytes("RGB", (frame.width, frame.height), frame.rgb).resize(
            (320, 192), Image.Resampling.BILINEAR)
        payload = small.tobytes()
        resize_ms = (time.perf_counter_ns() - start) / 1e6
        result = self.core.model(frame.id, frame.width, frame.height, payload, resize_ms)
        if result.get("frame_id") != frame.id or result.get("sha256") != self.hash:
            raise RuntimeError("Resultado L3 desalinhado ou modelo inesperado.")
        return result

    def verify(self):
        from hm.core import sha
        if sha(self.path) != self.meta_hash or sha(self.path.parent / "candidate-model.onnx") != self.hash:
            raise ValueError("Modelo L3 alterado durante a sessão.")


class RemoteBoardHub:
    def __init__(self, core: VMCore):
        self.core = core
        if 'board_independent_v1' not in core.ready.get('capabilities', []):
            raise ValueError('VM core needs updating for independent board capture')
        self.manifest = {"reference_sha256": core.ready["board_reference_sha256"],
                         "set_key": core.ready["board_set_key"]}

    def observe(self, canonical_frame, board_read=None, calibrate=False):
        result, _ = self.core.request("hub", canonical_frame.id, canonical_frame.width,
                                      canonical_frame.height, canonical_frame.rgb,
                                      source_ms=canonical_frame.pts_ms, calibrate_board=calibrate)
        if "snapshot" not in result or "regions" not in result:
            raise RuntimeError("HUB da VM sem observação estruturada.")
        return result
