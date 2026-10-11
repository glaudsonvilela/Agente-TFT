#!/usr/bin/env python3
"""One-job Akash upload and result endpoint; embedded in the SDL at build time."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import threading


ROOT = Path(os.environ.get("AKASH_WORKSPACE", "/workspace"))
ARCHIVES = {"core": "akash-core.tar.gz", "replays": "akash-replays.tar.gz"}
TOKEN = os.environ["AKASH_UPLOAD_TOKEN"]
EXPECTED = {"core": os.environ["AKASH_CORE_SHA256"], "replays": os.environ["AKASH_REPLAYS_SHA256"]}
LOCK = threading.Lock()
PROCESS: subprocess.Popen | None = None


def safe_extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as source:
        for member in source.getmembers():
            destination = (target / member.name).resolve()
            if not destination.is_relative_to(target.resolve()) or not member.isfile():
                raise ValueError("Unsafe bundle entry")
        source.extractall(target)


def start_if_ready() -> None:
    global PROCESS
    with LOCK:
        if PROCESS is not None or not all((ROOT / f"{name}.ready").exists() for name in ARCHIVES):
            return
        output = ROOT / "results"
        output.mkdir(exist_ok=True)
        log = (output / "training.log").open("wb")
        PROCESS = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "core/train.py"), "--root", str(ROOT / "core"), "--output", str(output)],
            stdout=log, stderr=subprocess.STDOUT, cwd=ROOT,
        )


class Handler(BaseHTTPRequestHandler):
    def authorized(self) -> bool:
        import hmac
        return hmac.compare_digest(self.headers.get("X-Upload-Token", ""), TOKEN)

    def respond(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self) -> None:
        if not self.authorized():
            return self.respond(403, b'{"error":"forbidden"}')
        name = self.path.strip("/")
        if name not in ARCHIVES:
            return self.respond(404, b'{"error":"unknown_archive"}')
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size <= 90_000_000:
            return self.respond(413, b'{"error":"invalid_size"}')
        target = ROOT / ARCHIVES[name]
        if (ROOT / f"{name}.ready").exists():
            return self.respond(409, b'{"error":"already_uploaded"}')
        digest = hashlib.sha256()
        remaining = size
        with target.open("wb") as output:
            while remaining:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    return self.respond(400, b'{"error":"short_upload"}')
                output.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
        if digest.hexdigest() != EXPECTED[name]:
            target.unlink(missing_ok=True)
            return self.respond(400, b'{"error":"checksum_mismatch"}')
        try:
            safe_extract(target, ROOT / name)
        except Exception as error:
            return self.respond(400, json.dumps({"error": str(error)}).encode())
        (ROOT / f"{name}.ready").touch()
        start_if_ready()
        return self.respond(200, json.dumps({"accepted": name, "sha256": digest.hexdigest()}).encode())

    def do_GET(self) -> None:
        if not self.authorized():
            return self.respond(403, b'{"error":"forbidden"}')
        if self.path == "/status":
            log = ROOT / "results/training.log"
            lines = log.read_text(errors="replace").splitlines()[-12:] if log.exists() else []
            state = {"core_uploaded": (ROOT / "core.ready").exists(),
                     "replays_uploaded": (ROOT / "replays.ready").exists(),
                     "running": PROCESS is not None and PROCESS.poll() is None,
                     "exit_code": None if PROCESS is None else PROCESS.poll(), "last_lines": lines}
            return self.respond(200, json.dumps(state, ensure_ascii=False).encode())
        allowed = {"report.json", "training.log", "champion-fusion-head.npz", "features.npz",
                   "diagnostic-best.pt", "diagnostic-source-disjoint.pt", "convnext-finetuned-experimental.pt"}
        name = self.path.removeprefix("/download/")
        if self.path.startswith("/download/") and name in allowed:
            file = ROOT / "results" / name
            if file.is_file():
                return self.respond(200, file.read_bytes(), "application/octet-stream")
        return self.respond(404, b'{"error":"not_found"}')


if __name__ == "__main__":
    port = int(os.environ.get("AKASH_RECEIVER_PORT", "8080"))
    print(f"Akash upload receiver ready on port {port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
