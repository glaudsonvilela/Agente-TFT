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
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import urlopen
from urllib.request import Request

from .runtime_app import default_hm4_output_root, discover_model, runtime_paths, target_label
from .voice import VOICE_NARRATION_ENABLED
from .runtime_session import HM4RuntimeSession
from .session import Options


def design_root():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
    return root / "ui" / "tauri-design"


def encode_preview_jpeg(frame):
    """Downscale the display copy without touching full resolution inference input."""
    raw = frame.rgb
    channels = 4 if len(raw) == frame.width * frame.height * 4 else 3
    if len(raw) != frame.width * frame.height * channels:
        raise ValueError('Invalid preview frame size')
    scale = min(1.0, 960 / frame.width, 540 / frame.height)
    size = (round(frame.width * scale), round(frame.height * scale))
    try:
        import cv2
        import numpy as np
    except ImportError:
        from PIL import Image
        image = Image.frombytes('RGB', (frame.width, frame.height), raw,
                                'raw', 'BGRX' if channels == 4 else 'RGB')
        if image.size != size:
            image = image.resize(size, Image.Resampling.BILINEAR)
        out = BytesIO()
        image.save(out, 'JPEG', quality=65, optimize=False)
        return out.getvalue()
    pixels = np.frombuffer(raw, dtype=np.uint8).reshape(frame.height, frame.width, channels)
    if (frame.width, frame.height) != size:
        pixels = cv2.resize(pixels, size, interpolation=cv2.INTER_LINEAR)
    bgr = cv2.cvtColor(pixels, cv2.COLOR_BGRA2BGR if channels == 4 else cv2.COLOR_RGB2BGR)
    ok, jpeg = cv2.imencode('.jpg', bgr, [cv2.IMWRITE_JPEG_QUALITY, 65])
    if not ok:
        raise ValueError('Preview JPEG encoding failed')
    return jpeg.tobytes()


class StudioController:
    def __init__(self):
        self.lock = threading.RLock()
        self.session = None
        self.source_label = None
        self.last_result = None
        self.last_error = None
        self.last_tip_key = None
        self.history = deque(maxlen=100)
        self.preview_jpeg = None
        self.preview_source_ms = None
        self.preview_sequence = 0
        self.preview_source_ms = None
        self.preview_epoch = None
        self.preview_times = deque(maxlen=90)
        self.preview_encode_ms = deque(maxlen=90)
        self.browser_preview = None
        self.next_preview_telemetry = 0.0
        self.preview_condition = threading.Condition()
        self.closed = threading.Event()
        self.voice = None
        self.highlight_recorder = None
        self.highlight_result = None
        from .player_profile import load as load_profile
        self.profile = load_profile()
        from .model_update import ModelUpdater
        self.model_updater = ModelUpdater(is_idle=lambda: self.session is None or self.session.finished)
        threading.Thread(target=self._resume_learning, daemon=True,
                         name="studio-resume-learning").start()
        if VOICE_NARRATION_ENABLED:
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
        if os.environ.get('AGENTE_TFT_DISABLE_VOICE') == '1':
            return
        def connect():
            from .voice import VoiceCoach
            from .voice_service import connect as connect_service
            playback = None
            if os.name != 'nt' and os.environ.get('AGENTE_TFT_UBUNTU_MVP') == '1':
                from .voice import linux_play_wav
                playback = linux_play_wav
            voice = VoiceCoach(playback=playback, load_settings=False)
            voice.on_played = self._record_spoken
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
        replay = os.environ.get('AGENTE_TFT_REPLAY_VIDEO')
        if replay and os.name != 'nt':
            path = Path(replay)
            return ([{'kind': 'video', 'id': 'local_replay',
                      'label': f'Replay local · {path.name}', 'candidate_tft': True}]
                    if path.is_file() else [])
        from .capture_source import list_targets
        return [{"kind": t["kind"], "id": t["id"], "label": target_label(t),
                 "candidate_tft": bool(t.get("candidate_tft"))}
                for t in list_targets(runtime_paths()["configs"])]

    def start_session(self, kind, identity, replay_review=False, consent=False):
        if consent is not True:
            raise ValueError("Confirme a captura da fonte selecionada.")
        with self.lock:
            if self.session and not self.session.finished:
                raise ValueError("Encerre a sessão atual antes de iniciar outra.")
            paths = runtime_paths()
            replay = os.environ.get('AGENTE_TFT_REPLAY_VIDEO')
            local_replay = bool(os.name != 'nt' and replay and
                                kind == 'video' and identity == 'local_replay')
            if local_replay:
                selected = {'kind': 'video', 'id': 'local_replay',
                            'label': f'Replay local · {Path(replay).name}'} if Path(replay).is_file() else None
            else:
                from .capture_source import list_targets
                selected = next((t for t in list_targets(paths["configs"])
                                 if t["kind"] == kind and t["id"] == identity), None)
            if selected is None:
                raise ValueError("Fonte indisponível; selecione novamente.")
            self.source_label = selected.get('label') or str(identity)
            # A remote model refresh must never block the first captured frame.
            # The signed package includes a baseline model; an updated model
            # is picked up on a later idle session by discover_model().
            model = discover_model()
            if not model:
                raise RuntimeError("Modelo visual local ausente do pacote; repare a instalação.")
            vm_core = (Path(sys.executable).resolve().parent / "core" / "core-package.json").is_file()
            preview_hz = (int(os.environ.get('AGENTE_TFT_REPLAY_PREVIEW_HZ', '22'))
                          if local_replay else 22)
            output = str(Path(default_hm4_output_root()) /
                         ("hm4-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")))
            self.last_error = self.last_result = self.last_tip_key = None
            self.highlight_recorder = None
            self.highlight_result = None
            self.history.clear()
            self.preview_jpeg = None
            self.preview_source_ms = None
            with self.preview_condition:
                self.preview_times.clear()
                self.preview_encode_ms.clear()
            self.browser_preview = None
            self.next_preview_telemetry = 0.0
            self.session = HM4RuntimeSession(Options(
                **({**paths, 'ffmpeg': 'ffmpeg', 'ffprobe': 'ffprobe'} if local_replay else paths),
                video=str(Path(replay).resolve()) if local_replay else f"capture://{kind}/{identity}", output=output,
                model=model, dataset_only=False, seconds=7200,
                map_hz=4, reader_hz=1, sample_hz=.2 if vm_core else 1,
                scenario="studio-live-lab" if not replay_review else "studio-replay-review",
                replay_review=bool(replay_review), board_hub_enabled=True,
                vm_core=vm_core and not local_replay, native_preview=True, preview_hz=preview_hz,
                preview_width=960, preview_height=540,
                max_samples=90 if vm_core else 600,
                max_bytes=384 * 1024**2 if vm_core else 1024**3,
                capture_consent=True, capture_expected=selected)).start()
            if VOICE_NARRATION_ENABLED:
                try:
                    from .speech_highlights import SpeechHighlightsRecorder
                    self.highlight_recorder = SpeechHighlightsRecorder(output)
                    self.highlight_result = {"status": "recording", "clips": 0}
                except Exception as exc:
                    self.highlight_result = {"status": "error", "error": str(exc)}
            else:
                self.highlight_result = {"status": "paused", "clips": 0}
            return {"session_id": self.session.id, "output": output}

    def _record_spoken(self, wav, text, metadata, started_ns, ended_ns):
        recorder = getattr(self, 'highlight_recorder', None)
        if recorder is not None:
            recorder.spoken(wav, text, metadata, started_ns, ended_ns)

    def _highlight_state(self):
        result = getattr(self, 'highlight_result', None)
        recorder = getattr(self, 'highlight_recorder', None)
        if result is None:
            return None
        return dict(result, clips=(len(recorder.rows) if recorder else result.get('clips', 0)))

    def highlight_video(self):
        result = getattr(self, 'highlight_result', None) or {}
        if result.get('status') != 'complete':
            return None
        path = Path(result['path'])
        return path if path.is_file() else None

    def stop_session(self):
        with self.lock:
            if self.session and not self.session.done.is_set():
                self.session.request_stop()
        return {"stopping": True}

    def set_voice(self, enabled):
        if not VOICE_NARRATION_ENABLED:
            return {"enabled": False, "paused": True}
        if self.voice:
            self.voice.set_enabled(bool(enabled))
        return {"enabled": bool(self.voice and self.voice.enabled)}

    def report_preview_metrics(self, fps, longest_gap_ms):
        """Receive display cadence from the local browser, separate from JPEG cadence."""
        if (not isinstance(fps, (int, float)) or isinstance(fps, bool) or
                not isinstance(longest_gap_ms, (int, float)) or isinstance(longest_gap_ms, bool) or
                not 0 <= fps <= 60 or not 0 <= longest_gap_ms <= 5000):
            raise ValueError("Métrica de prévia inválida.")
        with self.lock:
            self.browser_preview = {"fps": round(fps, 1),
                                    "longest_gap_ms": round(longest_gap_ms, 1),
                                    "at_monotonic": time.monotonic()}
        return {"accepted": True}

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
                        "highlights": self._highlight_state(),
                        "profile": self.profile,
                        "model_update": self.model_updater.last_result,
                        "history": list(self.history)}
            tip = session.latest_replay_tip
            safe_tip = None
            if tip:
                safe_tip = {k: tip.get(k) for k in
                            ("text", "status", "actionable", "speakable", "kind", "action_type", "frame_id", "source_ms",
                             "source_due_ns", "data_patch", "data_patch_basis", "basis",
                            "strategy_basis", "recommendations", "decision_key",
                            "policy", "family")}
                if safe_tip["source_due_ns"]:
                    safe_tip["age_ms"] = max(0, (time.perf_counter_ns() - safe_tip["source_due_ns"]) / 1e6)
                safe_tip.pop("source_due_ns", None)
            with self.preview_condition:
                preview_fps = sum(t >= time.monotonic() - 1 for t in self.preview_times)
                preview_encode_ms = self.preview_encode_ms[-1] if self.preview_encode_ms else None
            browser = self.browser_preview
            browser_preview = ({"fps": browser["fps"], "longest_gap_ms": browser["longest_gap_ms"]}
                               if browser and time.monotonic() - browser["at_monotonic"] < 5 else None)
            return {"phase": "finished" if session.finished else session.phase,
                    "session_id": session.id, "source_label": self.source_label,
                    "replay_review": session.options.replay_review,
                    "visual_model_loaded": bool(session.versions.get("neural_enabled")),
                    "strategic_model_loaded": bool(session.versions.get("strategic_ranker_loaded")),
                    "visual_readiness": session.versions.get("visual_readiness"),
                    "opponents": session.versions.get("opponent_tracking"),
                    "temporal_candidates": session.versions.get("temporal_candidates"),
                    "board_execution": session.versions.get("board_hub_execution"),
                    "unit_model_active": bool(session.versions.get("unit_neural_active")),
                    "item_model_active": bool(session.versions.get("item_neural_active")),
                    "yolo_overlay": session.versions.get("yolo_overlay"),
                    "data_patch": getattr(session.decision_engine, "patch", None),
                    "screen_mode": session.versions.get("screen_mode"),
                    "decision_status": getattr(session, "latest_decision_status", None),
                    "decision_reason": getattr(session, "latest_decision_reason", None),
                    "tip": safe_tip, "error": session.error or self.last_error,
                    "counts": {k: session.counts[k] for k in
                               ("source_frames", "preview_frames", "reader_native_runs",
                                "hub_results", "coach_updates", "replay_tips")},
                    "preview_sequence": self.preview_sequence,
                    "preview_encoded_fps": preview_fps,
                    "preview_encode_last_ms": preview_encode_ms,
                    "browser_preview": browser_preview,
                    "voice": self._voice_state(), "result": self.last_result,
                    "highlights": self._highlight_state(),
                    "profile": self.profile,
                    "model_update": self.model_updater.last_result,
                    "history": list(self.history)}

    def fast_diagnostic(self):
        with self.lock:
            session = self.session
            return getattr(session, 'latest_fast_diagnostic', None) if session else None

    def _voice_state(self):
        v = self.voice
        return {"ready": bool(v and v.ready), "enabled": bool(v and v.enabled),
                "played": v.played_count if v else 0, "error": v.error if v else None,
                "paused": not VOICE_NARRATION_ENABLED}

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
            if tip and (tip.get("actionable") or tip.get("kind") == "combat"):
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
        fast_backend = None
        if os.environ.get('AGENTE_TFT_UBUNTU_MVP') == '1':
            try:
                import cv2
                import numpy as np
                cv2.setNumThreads(1)
                fast_backend = (cv2, np)
            except ImportError:
                pass
        next_jpeg = 0.0
        while not self.closed.is_set():
            with self.lock:
                session = self.session
            if session is None or session.finished:
                next_jpeg = 0.0
                self.closed.wait(.05)
                continue
            remaining = next_jpeg - time.monotonic()
            if remaining > 0:
                self.closed.wait(remaining)
                continue
            try:
                frame = session.preview.get(.03)
            except queue.Empty:
                continue
            preview_hz = getattr(getattr(session, 'options', None), 'preview_hz', 22)
            next_jpeg = time.monotonic() + 1/preview_hz
            try:
                encode_start = time.perf_counter_ns()
                encoded = encode_preview_jpeg(frame)
                with self.lock:
                    if self.session is not session or session.finished:
                        continue
                    with self.preview_condition:
                        self.preview_jpeg = encoded
                        self.preview_source_ms = getattr(frame, 'pts_ms', None)
                        self.preview_sequence += 1
                        now = time.monotonic()
                        self.preview_times.append(now)
                        self.preview_encode_ms.append((time.perf_counter_ns()-encode_start)/1e6)
                        self.preview_condition.notify_all()
                        if now >= self.next_preview_telemetry:
                            self.next_preview_telemetry = now + 5
                            recent = sorted(self.preview_encode_ms)
                            source = getattr(session, "source", None)
                            event = {"event": "studio_preview_pipeline",
                                     "preview_encoded_fps": sum(t >= now - 1 for t in self.preview_times),
                                     "preview_encode_p95_ms": recent[int((len(recent)-1)*.95)],
                                     "native_preview_received": getattr(source, "preview_received", None),
                                     "native_preview_queue_replaced": getattr(
                                         getattr(source, "preview_frames", None), "replaced", None),
                                     "preview_source_age_ms": (
                                         (time.perf_counter_ns()-source.last_preview_received_ns)/1e6
                                         if source and getattr(source, 'last_preview_received_ns', None) else None)}
                        else:
                            event = None
                if event and getattr(session, "store", None):
                    session.store.emit("telemetry", event)
                recorder = getattr(self, 'highlight_recorder', None)
                if recorder is not None:
                    recorder.preview(encoded, time.monotonic_ns(),
                                     getattr(frame, 'pts_ms', 0) or 0)
            except Exception as exc:
                self.last_error = f"Prévia: {exc}"

    def _finalize(self, session):
        with self.lock:
            if self.session is not session or session.finished or not session.done.is_set():
                return
            try:
                self.last_result = session.finish()
                recorder = getattr(self, 'highlight_recorder', None)
                if recorder is not None:
                    self.highlight_result = {"status": "rendering", "clips": len(recorder.rows)}
                    threading.Thread(target=self._render_highlights,
                        args=(session.options.output, recorder), daemon=False,
                        name="tft-highlight-render").start()
                if self.last_result.get("post_session_learning_eligible") and not session.options.replay_review:
                    from .post_session_learning import launch_post_session_learning
                    self.last_result["post_session_learning_job"] = launch_post_session_learning(session.options.output)
                self.model_updater.activate_pending_if_idle()
                self.model_updater.check_async()
            except Exception as exc:
                self.last_error = str(exc)

    def _render_highlights(self, output, recorder):
        try:
            from .speech_highlights import compile_highlights
            recorder.seal()
            video = compile_highlights(output)
            self.highlight_result = ({"status": "complete", "path": str(video),
                                      "clips": len(recorder.rows)} if video else
                                     {"status": "no_spoken_tips", "clips": len(recorder.rows)})
        except Exception as exc:
            self.highlight_result = {"status": "error", "error": str(exc),
                                     "clips": len(recorder.rows)}

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
                             "set_voice", "rate_tip", "save_profile", "report_preview_metrics"))

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
        if relative == "frame.jpg":
            self._frame()
            return
        if relative == "preview.mjpg":
            self._preview()
            return
        if relative == "highlights.mp4":
            video = getattr(server.controller, 'highlight_video', lambda: None)()
            if video is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(video.stat().st_size))
            self.send_header("Content-Disposition", 'attachment; filename="melhores-momentos-agente-tft.mp4"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                with video.open('rb') as stream:
                    while chunk := stream.read(256 * 1024):
                        self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
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

    def _frame(self):
        """Return one fresh frame so the browser can release each decoded image."""
        try:
            raw = parse_qs(urlsplit(self.path).query).get("after", ["0"])
            if len(raw) != 1:
                raise ValueError
            after = int(raw[0])
            if not 0 <= after <= 2**63 - 1:
                raise ValueError
        except ValueError:
            self.send_error(400, "Invalid frame sequence")
            return
        controller = self.server.controller
        with controller.preview_condition:
            fresh = controller.preview_condition.wait_for(
                lambda: ((controller.preview_sequence > after and controller.preview_jpeg is not None)
                         or controller.closed.is_set()), timeout=2)
            sequence = controller.preview_sequence
            jpeg = controller.preview_jpeg
            source_ms = getattr(controller, 'preview_source_ms', None)
        if not fresh or controller.closed.is_set() or jpeg is None:
            self.send_response(204)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpeg)))
        self.send_header("X-Frame-Sequence", str(sequence))
        if source_ms is not None:
            self.send_header("X-Frame-Source-Ms", str(source_ms))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(jpeg)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _preview(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        sequence = 0
        try:
            while not self.server.controller.closed.is_set():
                with self.server.controller.preview_condition:
                    fresh = self.server.controller.preview_condition.wait_for(
                        lambda: self.server.controller.preview_sequence != sequence
                        or self.server.controller.closed.is_set(), timeout=2)
                    if not fresh or self.server.controller.closed.is_set():
                        continue
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
    if os.name == "nt" and getattr(sys, "frozen", False):
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
        handoff = os.environ.get("AGENTE_TFT_STUDIO_URL_FILE")
        if handoff:
            Path(handoff).write_text(server.url, encoding="utf-8")
            if os.environ.get('AGENTE_TFT_UBUNTU_MVP') == '1':
                open_local_window(server.url, "studio-browser")
        else:
            open_local_window(server.url, "studio-browser")
        if os.environ.get('AGENTE_TFT_UBUNTU_MVP') == '1':
            print('Interface do MVP: ' + server.url, flush=True)
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
