"""Real VM setup flow in the GitHub designer's local UI."""

from __future__ import annotations

from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import mimetypes
import os
import secrets
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from browser_shell import open_local_window
from hm45_setup_core import CoreInstaller, restart_windows, wait_wsl_after_restart, wsl_available


def design_root() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / "ui" / "tauri-design"


class SetupController:
    def __init__(self, app_exe: Path, *, resume=False, resume_headless=False):
        self.app_exe = app_exe
        self.resume = resume
        self.resume_headless = resume_headless
        self.lock = threading.RLock()
        self.closed = threading.Event()
        self.phase = "checking"
        self.error = ""
        self.messages: list[str] = []
        self.vm_ready = False
        self.preflight_done = False
        self.log_path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AgenteTFT-HM45" / "setup.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.installer = CoreInstaller(app_exe.parent / "core",
                                       Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AgenteTFT-Core",
                                       app_exe)
        self._start("install" if resume else "preflight")

    def _report(self, message: str) -> None:
        line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
        with self.lock:
            self.messages.append(message)
            self.messages = self.messages[-80:]
            with self.log_path.open("a", encoding="utf-8") as file:
                file.write(line + "\n")

    def _start(self, action: str, *, headless=False) -> None:
        self.phase = "checking" if action == "preflight" else "installing"
        self.error = ""

        def work():
            try:
                if action == "preflight":
                    self.installer.preflight(self._report)
                    self.preflight_done = True
                    result = "ready_to_install"
                else:
                    if not self.preflight_done:
                        self.installer.preflight(self._report)
                        self.preflight_done = True
                    if self.resume and not self.resume_headless:
                        wait_wsl_after_restart(self.installer.run, self._report)
                    if headless and not self.installer.use_headless_wsl(self._report):
                        result = "restart"
                    elif not wsl_available(self.installer.run) and not self.installer.enable_wsl(self._report):
                        result = "restart"
                    else:
                        result = self.installer.install(self._report)
            except Exception as exc:
                self._report("ERRO: " + str(exc))
                with self.lock:
                    self.error = str(exc)
                    self.phase = "error"
                return
            with self.lock:
                self.phase = result
                self.vm_ready = result == "ready"

        threading.Thread(target=work, daemon=True, name="hm45-setup-" + action).start()

    def state(self):
        with self.lock:
            return {"phase": self.phase, "error": self.error, "messages": list(self.messages),
                    "vm_ready": self.vm_ready, "log_path": str(self.log_path)}

    def install(self, headless=False):
        with self.lock:
            if self.phase not in ("ready_to_install", "error"):
                raise ValueError("A instalação não está pronta para começar.")
            if type(headless) is not bool:
                raise ValueError("Opção de WSL inválida.")
            self._start("install", headless=headless)
        return self.state()

    def retry(self):
        with self.lock:
            if self.phase != "error":
                raise ValueError("Não há etapa com erro para repetir.")
            self._start("preflight")
        return self.state()

    def restart(self):
        with self.lock:
            if self.phase != "restart":
                raise ValueError("Nenhum reinício pendente.")
        self._report("Reinício solicitado pelo usuário; retomada registrada.")
        restart_windows()
        return {"restarting": True}

    def launch(self):
        with self.lock:
            if not self.vm_ready:
                raise ValueError("A VM ainda não passou no teste de saúde.")
        handoff = self.log_path.parent / f"studio-handoff-{secrets.token_hex(8)}.txt"
        environment = os.environ.copy()
        environment["AGENTE_TFT_STUDIO_URL_FILE"] = str(handoff)
        process = subprocess.Popen([str(self.app_exe)], cwd=str(self.app_exe.parent),
                                   env=environment,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + 45
        try:
            while time.monotonic() < deadline:
                if handoff.is_file():
                    url = handoff.read_text(encoding="utf-8").strip()
                    address = urlsplit(url)
                    if (address.scheme == "http" and address.hostname == "127.0.0.1"
                            and address.port and address.query == "connected=1"
                            and address.fragment == "studio"):
                        break
                if process.poll() is not None:
                    raise RuntimeError("O aplicativo encerrou antes de abrir a interface. Veja o registro de inicialização.")
                time.sleep(.1)
            else:
                raise RuntimeError("O aplicativo não abriu a interface em 45 segundos. Veja o registro de inicialização.")
        finally:
            handoff.unlink(missing_ok=True)
        self._report("Agente TFT iniciado após verificação da VM.")
        self.closed.set()
        return {"launched": True, "url": url}

    def close(self):
        if self.state()["phase"] == "installing":
            raise ValueError("A instalação está em andamento. Aguarde a conclusão antes de fechar.")
        self.closed.set()
        return {"closed": True}


class SetupServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, controller: SetupController, root: Path):
        self.controller = controller
        self.root = root.resolve()
        self.token = secrets.token_urlsafe(24)
        self.last_api_at = time.monotonic()
        self.api_seen = False
        super().__init__(("127.0.0.1", 0), SetupHandler)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_port}/{self.token}/?installer=1&realInstaller=1#installer"


class SetupHandler(BaseHTTPRequestHandler):
    API_METHODS = frozenset(("state", "install", "retry", "restart", "launch", "close"))

    def log_message(self, *_args):
        pass

    def _authorized(self) -> bool:
        server = self.server
        origin = self.headers.get("Origin")
        return self.headers.get("Host") == f"127.0.0.1:{server.server_port}" and origin in (
            None, f"http://127.0.0.1:{server.server_port}")

    def do_GET(self):
        server = self.server
        if not self._authorized():
            self.send_error(403)
            return
        prefix = f"/{server.token}/"
        path = unquote(urlsplit(self.path).path)
        if not path.startswith(prefix):
            self.send_error(404)
            return
        relative = path[len(prefix):] or "index.html"
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

    def do_POST(self):
        server = self.server
        prefix = f"/{server.token}/api/"
        path = urlsplit(self.path).path
        if not self._authorized() or not path.startswith(prefix):
            self.send_error(403)
            return
        method = path[len(prefix):]
        if method not in self.API_METHODS:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 4096 or self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json":
                raise ValueError("Requisição inválida.")
            args = json.loads(self.rfile.read(length)).get("args")
            if not isinstance(args, list) or len(args) > 1:
                raise ValueError("Argumentos inválidos.")
            result = getattr(server.controller, method)(*args)
            body = json.dumps({"ok": True, "result": result}).encode("utf-8")
            code = 200
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
            code = 400
        server.api_seen = True
        server.last_api_at = time.monotonic()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def run_setup(app_exe: Path, *, resume=False, resume_headless=False) -> int:
    root = design_root()
    if not (root / "installer-connected.js").is_file():
        raise RuntimeError("O layout do instalador está ausente do pacote.")
    controller = SetupController(app_exe, resume=resume, resume_headless=resume_headless)
    server = SetupServer(controller, root)
    threading.Thread(target=server.serve_forever, daemon=True, name="hm45-setup-web").start()
    try:
        handoff = os.environ.get("AGENTE_TFT_BOOTSTRAP_URL_FILE")
        if handoff:
            Path(handoff).write_text(server.url, encoding="utf-8")
        else:
            open_local_window(server.url, "setup-browser")
        while not controller.closed.wait(1):
            if (server.api_seen and controller.state()["phase"] not in ("checking", "installing")
                    and time.monotonic() - server.last_api_at > 1800):
                break
    finally:
        server.shutdown()
        server.server_close()
    return 0 if controller.vm_ready else 1


def package_contract(output: Path) -> dict:
    """Verify the packaged designer and authenticated setup bridge."""
    class ProbeController:
        def state(self):
            return {"phase": "checking"}
    root = design_root()
    server = SetupServer(ProbeController(), root)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urlopen(server.url, timeout=5) as response:
            page = response.read()
        with urlopen(server.url.split("?")[0] + "installer-connected.js", timeout=5) as response:
            bridge = response.read()
        request = Request(server.url.split("?")[0] + "api/state", data=b'{"args":[]}',
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            state = json.load(response)
        if (b"installer-connected.js" not in page or b"realInstaller" not in bridge or
                state != {"ok": True, "result": {"phase": "checking"}}):
            raise RuntimeError("O instalador visual não está conectado ao motor local.")
    finally:
        server.shutdown()
        server.server_close()
    report = {"designer_assets_served": True, "local_setup_api_responded": True,
              "clr_free_shell": True}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    return report
