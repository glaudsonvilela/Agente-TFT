"""Headless WSL core: L3, OCR/HP and B4 over authenticated localhost TCP.

The Windows process owns capture and display. This process never opens a video
file or a screen capture API. It accepts only bounded, lossless analysis inputs.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import socketserver
import sys
import threading
import time
import traceback
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
os.environ["OMP_THREAD_LIMIT"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["AGENTE_TFT_RESIDENT_OCR"] = "required"
for path in (ROOT, ROOT / "apps/hud_mapper", ROOT / "apps/e1_replay"):
    sys.path.insert(0, str(path))

from hm45_protocol import ProtocolError, decode_rgb, recv_packet, send_packet

VERSION = "0.6.4"
MAX_CLIENTS = 6


class AnalysisCore:
    def __init__(self, root: Path = ROOT):
        from e1.protocol import NativeWorker
        from hm.core import sha
        from e1.model import MapObserver
        from hm.board_hub_live import BoardHubLive

        self.root = root
        self.model = MapObserver(root / "models/deployment-candidate.json")
        self.board = BoardHubLive(str(root / "configs"))
        (root / "runtime").mkdir(parents=True, exist_ok=True)
        self.reader_lock = threading.Lock()
        self.hp_lock = threading.Lock()
        self.model_lock = threading.Lock()
        self.hub_lock = threading.Lock()
        self.reader = None
        self.hp = None
        self.board_worker = None
        log_suffix = f"{os.getpid()}-{time.time_ns()}"
        try:
            self.reader = NativeWorker(str(root / "bin/agente-tft-e1-worker"), str(root / "configs"),
                                       "tesseract", log=root / f"runtime/reader-{log_suffix}.log")
            self.hp = NativeWorker(str(root / "bin/agente-tft-hm-hp"), str(root / "configs"),
                                   "tesseract", log=root / f"runtime/hp-{log_suffix}.log")
            from hm.board_worker import BoardWorker
            self.board_worker = BoardWorker(str(root / "bin/agente-tft-e1-worker"), str(root / "configs"),
                                             log=root / f"runtime/board-{log_suffix}.log")
        except Exception:
            self.close()
            raise
        if not self.reader.ready.get("ocr_available") or not self.hp.ready.get("ocr_available"):
            raise RuntimeError("OCR residente indisponível na VM.")
        self.ready = {
            "version": VERSION,
            "model_sha256": self.model.hash,
            "model_metadata_sha256": sha(root / "models/deployment-candidate.json"),
            "reader_binary_sha256": sha(root / "bin/agente-tft-e1-worker"),
            "hp_binary_sha256": sha(root / "bin/agente-tft-hm-hp"),
            "reader_ready": self.reader.ready,
            "hp_ready": self.hp.ready,
            "board_reference_sha256": self.board.manifest["reference_sha256"],
            "board_set_key": self.board.manifest["set_key"],
            "analysis_health_contract": "l3_ocr_b4_roi_v1",
            "capabilities": ["l3_small_rgb", "ocr_lossless_rgb", "hp_lossless_rgb", "b4_lossless_rgb", "board_independent_v1"],
        }

    def close(self):
        for worker in (self.reader, self.hp, self.board_worker):
            try:
                if worker:
                    worker.close()
            except Exception:
                pass

    def dispatch(self, header: dict, payload: bytes) -> dict:
        op = header.get("op")
        frame_id = header.get("frame_id")
        if op == "health":
            return self.ready
        if type(frame_id) is not int or frame_id < 0:
            raise ProtocolError("frame_id inválido.")
        width, height = header.get("width"), header.get("height")
        if type(width) is not int or type(height) is not int:
            raise ProtocolError("Dimensões ausentes.")
        if op == "model":
            if (len(payload) != 320 * 192 * 3 or header.get("codec") != "rgb8-small" or
                    not 0 < width <= 8192 or not 0 < height <= 8192):
                raise ProtocolError("Entrada L3 incompatível.")
            import numpy as np
            started = time.perf_counter_ns()
            array = np.frombuffer(payload, dtype=np.uint8).reshape(192, 320, 3)
            value = array.astype(np.float32).transpose(2, 0, 1)[None] / 255
            with self.model_lock:
                raw = self.model.session.run(["panels"], {"image": value})[0]
            elapsed = (time.perf_counter_ns() - started) / 1e6
            if raw.shape != (1, 2, 5) or not np.isfinite(raw).all():
                raise RuntimeError("L3 retornou saída inválida.")
            from hm.core import neural_regions
            return dict(status="real_diagnostic_only", sha256=self.model.hash,
                        raw=raw.tolist(), regions=neural_regions(raw, width, height),
                        inference_ms=elapsed, resize_ms=float(header.get("resize_ms") or 0.0),
                        frame_id=frame_id, model_scope=["bench_envelope", "shop_envelope"],
                        shadow_mode="diagnostic_only", ground_truth=False,
                        training_label_allowed=False, game_state_write_allowed=False,
                        reader_input_allowed=False, map_usable_by_readers=False,
                        model_trained=False, profile_promoted=False)
        if (width, height) != (1920, 1080):
            raise ProtocolError("OCR e B4 exigem frame canônico 1920×1080.")
        rgb = decode_rgb(header.get("codec"), payload, width, height)
        source_ms = header.get("source_ms")
        if type(source_ms) not in (int, float) or not 0 <= source_ms <= 10**9:
            raise ProtocolError("Tempo de origem inválido.")
        if op == "reader":
            request = dict(op="frame", id=frame_id, source_ms=round(source_ms), width=width,
                           height=height, bytes=len(rgb), include_shop=bool(header.get("include_shop", True)))
            with self.reader_lock:
                answer = self.reader.request(request, rgb, timeout=12)
        elif op == "hp":
            request = dict(op="frame", id=frame_id, source_ms=round(source_ms), width=width,
                           height=height, bytes=len(rgb), include_shop=False)
            with self.hp_lock:
                answer = self.hp.request(request, rgb, timeout=12)
        elif op == "reference":
            request = dict(op="reference", id=frame_id, source_ms=round(source_ms), width=width,
                           height=height, bytes=len(rgb))
            with self.reader_lock:
                answer = self.reader.request(request, rgb, timeout=12)
        elif op == "hub":
            frame = SimpleNamespace(id=frame_id, pts_ms=source_ms, width=width, height=height, rgb=rgb)
            with self.hub_lock:
                # Derive geometry from these pixels, independently of the OCR
                # connection; never trust a stale caller-supplied bar list.
                board_read = self.board_worker.observe(frame, header.get('calibrate_board') is True)
                answer = self.board.observe(frame, board_read)
        else:
            raise ProtocolError("Operação não reconhecida.")
        if op != "hub" and answer.get("id") != frame_id:
            raise RuntimeError("Resposta do worker pertence a outro frame.")
        return answer


class CoreTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, core: AnalysisCore, token: str):
        self.core = core
        self.token = token
        self.slots = threading.BoundedSemaphore(MAX_CLIENTS)
        super().__init__(("127.0.0.1", 0), CoreHandler)


class CoreHandler(socketserver.BaseRequestHandler):
    def handle(self):
        server: CoreTCPServer = self.server
        if not server.slots.acquire(blocking=False):
            return
        try:
            self.request.settimeout(20)
            hello, payload = recv_packet(self.request)
            if payload or hello.get("op") != "hello" or not secrets.compare_digest(
                    str(hello.get("token", "")), server.token):
                return
            send_packet(self.request, {"ok": True, "op": "hello", "ready": server.core.ready})
            # Worker connections are persistent and may legitimately remain idle
            # while a replay is paused. The 20 s deadline applies to handshake
            # only; closing an idle authenticated socket killed the next request.
            self.request.settimeout(None)
            while True:
                try:
                    header, payload = recv_packet(self.request)
                except EOFError:
                    break
                request_id = header.get("request_id")
                try:
                    if header.get("op") == "shutdown":
                        send_packet(self.request, {"ok": True, "request_id": request_id})
                        threading.Thread(target=server.shutdown, daemon=True).start()
                        break
                    started = time.perf_counter_ns()
                    result = server.core.dispatch(header, payload)
                    send_packet(self.request, {"ok": True, "request_id": request_id,
                                               "result": result,
                                               "core_ms": (time.perf_counter_ns() - started) / 1e6})
                except Exception as exc:
                    traceback.print_exc(file=sys.stderr)
                    send_packet(self.request, {"ok": False, "request_id": request_id,
                                               "error": str(exc)[:500]})
        finally:
            server.slots.release()


def serve(core: AnalysisCore, token: str, ready_file=None):
    with CoreTCPServer(core, token) as server:
        ready = {"ready": True, "host": "127.0.0.1", "port": server.server_address[1], **core.ready}
        if ready_file is None:
            print(json.dumps(ready, separators=(",", ":")), flush=True)
        else:
            ready_file.write(json.dumps(ready))
        server.serve_forever(poll_interval=0.1)


def self_test(root: Path, version: str) -> int:
    if version != VERSION:
        raise RuntimeError("Versão do núcleo incompatível.")
    core = AnalysisCore(root)
    token = secrets.token_hex(32)
    server = CoreTCPServer(core, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with socket.create_connection(server.server_address, timeout=20) as sock:
            sock.settimeout(30)
            send_packet(sock, {"op": "hello", "token": token})
            greeting, _ = recv_packet(sock)
            if not greeting.get("ok"):
                raise RuntimeError("Handshake IP local falhou.")
            def check(op: str, frame_id: int, rgb: bytes, width: int, height: int, codec: str):
                send_packet(sock, {"op": op, "request_id": frame_id, "frame_id": frame_id,
                                   "source_ms": 0, "width": width, "height": height,
                                   "codec": codec, "board_read": None}, rgb)
                result, _ = recv_packet(sock)
                if not result.get("ok") or result.get("request_id") != frame_id:
                    raise RuntimeError(f"Teste IP local {op} falhou: {result.get('error')}")
                return result["result"]
            model = check("model", 1, bytes(320*192*3), 1920, 1080, "rgb8-small")
            if model.get("sha256") != core.model.hash or len(model.get("regions") or []) != 2:
                raise RuntimeError("L3 não retornou regiões válidas.")
            from hm45_protocol import encode_rgb
            codec, rgb = encode_rgb(bytes(1920*1080*3), 1920, 1080)
            reader = check("reader", 2, rgb, 1920, 1080, codec)
            hp = check("hp", 3, rgb, 1920, 1080, codec)
            hub = check("hub", 4, rgb, 1920, 1080, codec)
            if reader.get("id") != 2 or hp.get("id") != 3 or "snapshot" not in hub:
                raise RuntimeError("OCR/HP/B4 não retornaram resultados válidos.")
            if not (hub['snapshot'].get('neural_items') or {}).get('active'):
                raise RuntimeError('Modelo neural de itens não carregou no núcleo.')
        print("AGENTETFT_CORE_HEALTH_OK", flush=True)
        return 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        core.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("serve", "self-test"))
    parser.add_argument("--version", default=VERSION)
    args = parser.parse_args()
    if args.mode == "self-test":
        return self_test(ROOT, args.version)
    token = sys.stdin.readline(256).strip()
    if len(token) != 64 or any(ch not in "0123456789abcdef" for ch in token):
        raise RuntimeError("Token de sessão inválido.")
    core = AnalysisCore(ROOT)
    try:
        serve(core, token)
    finally:
        core.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
