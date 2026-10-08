"""Local browser studio for the GitHub design, backed by the HM4 runtime.

The UI and the frame stream are intentionally separate. Only the latest
preview frame may be encoded; analysis and voice never wait for a browser.
"""
from __future__ import annotations

from datetime import datetime
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
import json
import mimetypes
import os
import queue
import secrets
import sys
import threading
import time
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen
from urllib.request import Request

from .runtime_app import default_hm4_output_root, discover_model, runtime_paths, target_label
from .runtime_session import HM4RuntimeSession
from .session import Options


def design_root():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    return root / "ui" / "tauri-design"


class StudioController:
    def __init__(self):
        self.lock = threading.RLock()
        self.session = None
        self.last_result = None
        self.last_error = None
        self.last_tip_key = None
        self.history = deque(maxlen=100)
        self.preview_jpeg = None
        self.preview_sequence = 0
        self.preview_times = deque(maxlen=90)
        self.preview_encode_ms = deque(maxlen=90)
        self.preview_condition = threading.Condition()
        self.closed = threading.Event()
        self.voice = None
        from .player_profile import load as load_profile
        self.profile = load_profile()
        from .model_update import ModelUpdater
        self.model_updater = ModelUpdater(is_idle=lambda: self.session is None or self.session.finished)
        threading.Thread(target=self._resume_learning, daemon=True,
                         name="studio-resume-learning").start()
        self._connect_voice_async()
        self.pump = threading.Thread(target=self._pump, daemon=True, name="studio-state-pump")
        self.preview_pump = threading.Thread(target=self._preview_pump, daemon=True,
                                             name="studio-preview-encode")
        self.pump.start()
        self.preview_pump.start()

    def _resume_learning(self):
        try:
            from .post_session_learning import resume_pending_post_session_uploads
            resume_pending_post_session_uploads(default_hm4_output_root())
        except Exception:
            pass

    def _connect_voice_async(self):
        def connect():
            from .voice import VoiceCoach
            from .voice_service import connect as connect_service
            voice = VoiceCoach(load_settings=False)
            try:
                voice.configure(connect_service())
                voice.set_enabled(True)
                if not self.profile:
                    from .player_profile import WELCOME
                    voice.say(WELCOME, 0, force=True)
            except Exception:
                voice.error = "Serviço de voz indisponível."
            self.voice = voice
        threading.Thread(target=connect, daemon=True, name="studio-voice-connect").start()

    def list_sources(self):
        from .capture_source import list_targets
        return [{"kind": t["kind"], "id": t["id"], "label": target_label(t),
                 "candidate_tft": bool(t.get("candidate_tft"))}
                for t in list_targets(runtime_paths()["configs"])]

    def start_session(self, kind, identity, replay_review=False, consent=False):
        from .capture_source import list_targets
        if consent is not True:
            raise ValueError("Confirme a captura da fonte selecionada.")
        with self.lock:
            if self.session and not self.session.finished:
                raise ValueError("Encerre a sessão atual antes de iniciar outra.")
            paths = runtime_paths()
            selected = next((t for t in list_targets(paths["configs"])
                             if t["kind"] == kind and t["id"] == identity), None)
            if selected is None:
                raise ValueError("Fonte indisponível; selecione novamente.")
            # A remote model refresh must never block the first captured frame.
            # The signed package includes a baseline model; an updated model
            # is picked up on a later idle session by discover_model().
            model = discover_model()
            if not model:
                raise RuntimeError("Modelo visual local ausente do pacote; repare a instalação.")
            vm_core = (Path(sys.executable).resolve().parent / "core" / "core-package.json").is_file()
            output = str(Path(default_hm4_output_root()) /
                         ("hm4-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")))
            self.last_error = self.last_result = self.last_tip_key = None
            self.history.clear()
            self.preview_jpeg = None
            self.session = HM4RuntimeSession(Options(
                **paths, video=f"capture://{kind}/{identity}", output=output,
                model=model, dataset_only=False, seconds=7200,
                map_hz=4, reader_hz=1, sample_hz=.2 if vm_core else 1,
                scenario="studio-live-lab" if not replay_review else "studio-replay-review",
                replay_review=bool(replay_review), board_hub_enabled=True,
                vm_core=vm_core, native_preview=True, preview_hz=30,
                preview_width=1280, preview_height=720,
                max_samples=90 if vm_core else 600,
                max_bytes=384 * 1024**2 if vm_core else 1024**3,
                capture_consent=True, capture_expected=selected)).start()
            return {"session_id": self.session.id, "output": output}

    def stop_session(self):
        with self.lock:
            if self.session and not self.session.done.is_set():
                self.session.request_stop()
        return {"stopping": True}

    def set_voice(self, enabled):
        if self.voice:
            self.voice.set_enabled(bool(enabled))
        return {"enabled": bool(self.voice and self.voice.enabled)}

    def rate_tip(self, decision_key, helpful):
        """Accept explicit feedback for the currently visible provisional tip."""
        if (not isinstance(decision_key, str) or len(decision_key) > 100
                or type(helpful) is not bool):
            return {"accepted": False}
        with self.lock:
            session = self.session
        return {"accepted": bool(session and session.feedback_tip(
            helpful, decision_key=decision_key))}

    def save_profile(self, nickname, region):
        from .player_profile import save
        self.profile = save(nickname, region)
        return self.profile

    def state(self):
        with self.lock:
            session = self.session
            if session is None:
                return {"phase": "idle", "tip": None, "error": self.last_error,
                        "voice": self._voice_state(), "result": self.last_result,
                        "profile": self.profile,
                        "model_update": self.model_updater.last_result,
                        "history": list(self.history)}
            tip = session.latest_replay_tip
            safe_tip = None
            if tip:
                safe_tip = {k: tip.get(k) for k in
                            ("text", "status", "actionable", "frame_id", "source_ms",
                             "source_due_ns", "data_patch", "data_patch_basis", "basis",
                            "strategy_basis", "recommendations", "decision_key",
                            "policy", "family")}
                if safe_tip["source_due_ns"]:
                    safe_tip["age_ms"] = max(0, (time.perf_counter_ns() - safe_tip["source_due_ns"]) / 1e6)
                safe_tip.pop("source_due_ns", None)
            return {"phase": "finished" if session.finished else session.phase,
                    "session_id": session.id, "replay_review": session.options.replay_review,
                    "visual_model_loaded": bool(session.versions.get("neural_enabled")),
                    "strategic_model_loaded": bool(session.versions.get("strategic_ranker_loaded")),
                    "visual_readiness": session.versions.get("visual_readiness"),
                    "temporal_candidates": session.versions.get("temporal_candidates"),
                    "board_execution": session.versions.get("board_hub_execution"),
                    "unit_model_active": bool(session.versions.get("unit_neural_active")),
                    "item_model_active": bool(session.versions.get("item_neural_active")),
                    "data_patch": getattr(session.decision_engine, "patch", None),
                    "screen_mode": session.versions.get("screen_mode"),
                    "tip": safe_tip, "error": session.error or self.last_error,
                    "counts": {k: session.counts[k] for k in
                               ("source_frames", "preview_frames", "reader_native_runs",
                                "hub_results", "coach_updates", "replay_tips")},
                    "preview_sequence": self.preview_sequence,
                    "preview_encoded_fps": sum(t >= time.monotonic() - 1 for t in self.preview_times),
                    "preview_encode_last_ms": self.preview_encode_ms[-1] if self.preview_encode_ms else None,
                    "voice": self._voice_state(), "result": self.last_result,
                    "profile": self.profile,
                    "model_update": self.model_updater.last_result,
                    "history": list(self.history)}

    def _voice_state(self):
        v = self.voice
        return {"ready": bool(v and v.ready), "enabled": bool(v and v.enabled),
                "played": v.played_count if v else 0, "error": v.error if v else None}

    def _pump(self):
        next_model_check = 0.0
        while not self.closed.wait(.01):
            with self.lock:
                session = self.session
            if time.monotonic() >= next_model_check:
                next_model_check = time.monotonic() + 300
                if session is None or session.finished:
                    try:
                        self.model_updater.activate_pending_if_idle()
                        self.model_updater.check_async()
                    except Exception:
                        pass
            if session is None or session.finished:
                continue
            tip = session.latest_replay_tip
            if tip and tip.get("actionable"):
                tip_key = (tip.get("decision_key"), tip.get("text"))
                with self.lock:
                    if tip_key != self.last_tip_key:
                        self.last_tip_key = tip_key
                        self.history.appendleft({
                            "source_ms": tip.get("source_ms"), "text": tip.get("text"),
                            "data_patch": tip.get("data_patch"),
                            "basis": tip.get("basis") or [],
                            "recommendations": tip.get("recommendations") or [],
                        })
            if tip and self.voice:
                self.voice.observe_tip(tip, time.perf_counter_ns())
                while self.voice.events:
                    session.store.emit("telemetry", self.voice.events.popleft())
            if session.done.is_set():
                self._finalize(session)

    def _preview_pump(self):
        """Encode the latest frame off the advice/voice delivery thread.

        The capture queue has capacity one. Slow JPEG encoding therefore drops
        old preview frames instead of delaying a new decision or spoken tip.
        """
        next_jpeg = 0.0
        while not self.closed.wait(.01):
            with self.lock:
                session = self.session
            if session is None or session.finished or time.monotonic() < next_jpeg:
                continue
            try:
                frame = session.preview.get(0)
            except queue.Empty:
                continue
            next_jpeg = time.monotonic() + 1/30
            try:
                encode_start = time.perf_counter_ns()
                from PIL import Image
                raw = "BGRX" if len(frame.rgb) == frame.width * frame.height * 4 else "RGB"
                image = Image.frombytes("RGB", (frame.width, frame.height), frame.rgb, "raw", raw)
                out = BytesIO()
                image.save(out, "JPEG", quality=72, optimize=False)
                encoded = out.getvalue()
                with self.lock:
                    if self.session is not session or session.finished:
                        continue
                with self.preview_condition:
                    self.preview_jpeg = encoded
                    self.preview_sequence += 1
                    self.preview_times.append(time.monotonic())
                    self.preview_encode_ms.append((time.perf_counter_ns()-encode_start)/1e6)
                    self.preview_condition.notify_all()
            except Exception as exc:
                self.last_error = f"Prévia: {exc}"

    def _finalize(self, session):
        with self.lock:
            if self.session is not session or session.finished or not session.done.is_set():
                return
            try:
                self.last_result = session.finish()
                if self.last_result.get("post_session_learning_eligible") and not session.options.replay_review:
                    from .post_session_learning import launch_post_session_learning
                    self.last_result["post_session_learning_job"] = launch_post_session_learning(session.options.output)
                self.model_updater.activate_pending_if_idle()
                self.model_updater.check_async()
            except Exception as exc:
                self.last_error = str(exc)

    def close(self):
        self.stop_session()
        session = self.session
        if session and not session.finished:
            # A reader can use its 12-second request deadline and the session
            # still gives workers up to 30 seconds to join before sealing.
            if not session.done.wait(40):
                session.stop()
                session.done.wait(5)
            if not session.done.is_set():
                self.last_error = "A sessão não encerrou no prazo; preserve a pasta parcial para diagnóstico."
            self._finalize(session)
        self.closed.set()
        with self.preview_condition:
            self.preview_condition.notify_all()
        if self.voice:
            self.voice.close()


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, controller, root):
        self.controller = controller
        self.root = Path(root).resolve()
        self.token = secrets.token_urlsafe(24)
        self.last_api_at = time.monotonic()
        self.api_seen = False
        super().__init__(("127.0.0.1", 0), StudioHandler)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}/{self.token}/?connected=1#studio"


class StudioHandler(BaseHTTPRequestHandler):
    API_METHODS = frozenset(("state", "list_sources", "start_session", "stop_session",
                             "set_voice", "rate_tip", "save_profile"))

    def log_message(self, *_args):
        pass

    def do_POST(self):
        server = self.server
        origin = self.headers.get("Origin")
        authority = f"127.0.0.1:{server.server_port}"
        base = f"http://{authority}"
        path = urlsplit(self.path).path
        prefix = f"/{server.token}/api/"
        if (self.headers.get("Host") != authority or origin not in (None, base)
                or not path.startswith(prefix)):
            self.send_error(403)
            return
        method = path[len(prefix):]
        if method not in self.API_METHODS:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 16384 or self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                raise ValueError("Requisição inválida.")
            payload = json.loads(self.rfile.read(length))
            args = payload.get("args")
            if not isinstance(args, list) or len(args) > 5:
                raise ValueError("Argumentos inválidos.")
            result = getattr(server.controller, method)(*args)
            body = json.dumps({"ok": True, "result": result}).encode("utf-8")
            code = 200
        except (ValueError, TypeError, KeyError) as exc:
            body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
            code = 400
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
            code = 500
        server.last_api_at = time.monotonic()
        server.api_seen = True
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        server = self.server
        if self.headers.get("Host") not in (f"127.0.0.1:{server.server_port}",):
            self.send_error(403)
            return
        prefix = "/" + server.token + "/"
        path = unquote(urlsplit(self.path).path)
        if not path.startswith(prefix):
            self.send_error(404)
            return
        relative = path[len(prefix):] or "index.html"
        if relative == "preview.mjpg":
            self._preview()
            return
        file = (server.root / relative).resolve()
        if not file.is_relative_to(server.root) or not file.is_file():
            self.send_error(404)
            return
        data = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(file)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _preview(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        sequence = 0
        try:
            while not self.server.controller.closed.is_set():
                with self.server.controller.preview_condition:
                    self.server.controller.preview_condition.wait_for(
                        lambda: self.server.controller.preview_sequence != sequence
                        or self.server.controller.closed.is_set(), timeout=2)
                    sequence = self.server.controller.preview_sequence
                    jpeg = self.server.controller.preview_jpeg
                if not jpeg:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " +
                                 str(len(jpeg)).encode("ascii") + b"\r\n\r\n" + jpeg + b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def package_contract(output):
    """Exercise the bundled studio and local API without opening a GUI."""
    root = design_root()
    class ProbeController:
        def state(self):
            return {"phase": "idle"}
    server = StudioServer(ProbeController(), root)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with urlopen(server.url, timeout=5) as response:
            page = response.read()
        with urlopen(server.url.split("?")[0] + "connected.js", timeout=5) as response:
            bridge = response.read()
        if b"AGENTE TFT" not in page or b"connectedCoach" not in bridge:
            raise RuntimeError("O layout conectado não foi incluído no pacote.")
        request = Request(server.url.split("?")[0] + "api/state", data=b'{"args":[]}',
                          headers={"Content-Type": "application/json", "Origin":
                                   f"http://127.0.0.1:{server.server_port}"})
        with urlopen(request, timeout=5) as response:
            api_result = json.load(response)
        if api_result != {"ok": True, "result": {"phase": "idle"}}:
            raise RuntimeError("A ponte local da interface não respondeu.")
    finally:
        server.shutdown()
        server.server_close()
    capture_present = None
    targets_enumerated = None
    target_count = None
    baseline_model_present = None
    if os.name == "nt":
        from .capture_source import native_path, list_targets
        configs = runtime_paths()["configs"]
        baseline = Path(configs).parent / "models" / "deployment-candidate.json"
        baseline_model_present = baseline.is_file() and (baseline.parent / "candidate-model.onnx").is_file()
        if not baseline_model_present:
            raise RuntimeError("O modelo visual local não está no pacote Windows.")
        capture_present = native_path(configs).is_file()
        if not capture_present:
            raise RuntimeError("O capturador Rust não está no pacote Windows.")
        targets = list_targets(configs)
        targets_enumerated = True
        target_count = len(targets)
    report = {"studio_assets_served": True, "local_api_responded": True,
              "clr_free_shell": True, "native_capture_present": capture_present,
              "targets_enumerated": targets_enumerated, "target_count": target_count,
              "baseline_model_present": baseline_model_present}
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    return report


def run_studio(*, browser=False):
    root = design_root()
    if not (root / "index.html").is_file():
        raise RuntimeError("Interface do GitHub ausente no pacote.")
    controller = StudioController()
    server = StudioServer(controller, root)
    worker = threading.Thread(target=server.serve_forever, daemon=True, name="studio-local-web")
    worker.start()
    try:
        from browser_shell import open_local_window
        open_local_window(server.url, "studio-browser")
        while not controller.closed.wait(1):
            # Browser timers can be suspended while the replay player is in
            # front. Never end an active capture merely because UI polling
            # paused; let its own duration/stop contract finish the session.
            active = controller.session is not None and not controller.session.finished
            if server.api_seen and not active and time.monotonic() - server.last_api_at > 600:
                break
    finally:
        controller.close()
        server.shutdown()
        server.server_close()
    return 0
