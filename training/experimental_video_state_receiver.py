"""Authenticated, resumable Akash receiver for the video-state experiment.

All uploaded chunks, extracted 1080p frames, checkpoints, and deadline state
live beneath the mounted /workspace volume. Restarting the container restarts
the supervisor; it never resets the clock or overwrites weights silently.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import threading


ROOT = Path(os.environ.get("TFT_WORKSPACE", "/workspace"))
TOKEN = os.environ["TFT_UPLOAD_TOKEN"]
PARTS = json.loads(os.environ["TFT_PART_SHA256_JSON"])
BUNDLE_SHA = os.environ["TFT_BUNDLE_SHA256"]
MAX_PART = 24_000_000
LOCK = threading.Lock()
PROCESS: subprocess.Popen | None = None


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def part_path(index: int) -> Path:
    return ROOT / "parts" / f"part-{index:04d}"


def safe_extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r") as source:
        for member in source:
            name = Path(member.name)
            destination = (target / name).resolve()
            if name.is_absolute() or not destination.is_relative_to(target.resolve()):
                raise ValueError("unsafe archive path")
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise ValueError("archive contains a non-regular file")
            destination.parent.mkdir(parents=True, exist_ok=True)
            item = source.extractfile(member)
            if item is None:
                raise ValueError("missing archive data")
            with destination.open("wb") as output:
                while block := item.read(1024 * 1024):
                    output.write(block)


def assemble_if_ready() -> None:
    if (ROOT / "input.ready").exists():
        return
    if not all(part_path(i).is_file() and digest_file(part_path(i)) == sha
               for i, sha in enumerate(PARTS)):
        return
    bundle = ROOT / "bundle.tar"
    with bundle.open("wb") as output:
        for i in range(len(PARTS)):
            with part_path(i).open("rb") as item:
                while block := item.read(1024 * 1024):
                    output.write(block)
    if digest_file(bundle) != BUNDLE_SHA:
        bundle.unlink(missing_ok=True)
        raise ValueError("bundle digest mismatch")
    safe_extract(bundle, ROOT / "input")
    if not (ROOT / "input/state-index.json").is_file():
        raise ValueError("missing state index")
    (ROOT / "input.ready").touch()
    bundle.unlink(missing_ok=True)


def start_if_ready() -> None:
    global PROCESS
    with LOCK:
        if PROCESS is not None and PROCESS.poll() is None:
            return
        assemble_if_ready()
        if not (ROOT / "input.ready").exists() or (ROOT / "results/complete.flag").exists():
            return
        output = ROOT / "results"
        output.mkdir(exist_ok=True)
        log = (output / "supervisor.log").open("ab")
        env = {**os.environ, "PYTHONPATH": str(ROOT / "input/code")}
        PROCESS = subprocess.Popen([
            sys.executable, "-u", "-m", "training.experimental_video_state_supervisor",
            "--index", str(ROOT / "input/state-index.json"),
            "--frames", str(ROOT / "input/frames"),
            "--branches", str(ROOT / "input/economy-branches.json"),
            "--workdir", str(output), "--persistent-root", str(ROOT),
            "--seconds", "36000"], env=env, cwd=ROOT, stdout=log,
            stderr=subprocess.STDOUT)
        log.close()


class Handler(BaseHTTPRequestHandler):
    def authenticated(self) -> bool:
        return hmac.compare_digest(self.headers.get("X-Upload-Token", ""), TOKEN)

    def respond(self, status: int, payload: dict | bytes,
                content_type: str = "application/json") -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self) -> None:
        if not self.authenticated():
            return self.respond(403, {"error": "forbidden"})
        if not self.path.startswith("/part/"):
            return self.respond(404, {"error": "not_found"})
        try:
            index = int(self.path.removeprefix("/part/"))
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.respond(400, {"error": "invalid_part"})
        if not 0 <= index < len(PARTS) or not 0 < size <= MAX_PART:
            return self.respond(413, {"error": "invalid_size_or_index"})
        target = part_path(index)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and digest_file(target) == PARTS[index]:
            try:
                start_if_ready()
            except Exception as error:
                return self.respond(500, {"error": f"assemble_failed: {error}"})
            return self.respond(200, {"accepted": index, "already_present": True})
        temporary = target.with_suffix(".tmp")
        remaining = size
        digest = hashlib.sha256()
        with temporary.open("wb") as output:
            while remaining:
                block = self.rfile.read(min(1024 * 1024, remaining))
                if not block:
                    temporary.unlink(missing_ok=True)
                    return self.respond(400, {"error": "short_upload"})
                output.write(block)
                digest.update(block)
                remaining -= len(block)
        if digest.hexdigest() != PARTS[index]:
            temporary.unlink(missing_ok=True)
            return self.respond(400, {"error": "checksum_mismatch"})
        os.replace(temporary, target)
        try:
            start_if_ready()
        except Exception as error:
            return self.respond(500, {"error": f"assemble_failed: {error}"})
        return self.respond(200, {"accepted": index})

    def do_GET(self) -> None:
        if not self.authenticated():
            return self.respond(403, {"error": "forbidden"})
        if self.path == "/status":
            report = ROOT / "results/report.json"
            job = ROOT / "results/job.json"
            files = ("report.json", "training.log", "supervisor.log",
                     "experimental-state-checkpoint.pt", "experimental-state-best.pt")
            return self.respond(200, {
                "parts_received": sum(part_path(i).is_file() for i in range(len(PARTS))),
                "parts_required": len(PARTS),
                "input_ready": (ROOT / "input.ready").exists(),
                "running": PROCESS is not None and PROCESS.poll() is None,
                "exit_code": None if PROCESS is None else PROCESS.poll(),
                "complete": (ROOT / "results/complete.flag").exists(),
                "files_available": [name for name in files
                                    if (ROOT / "results" / name).is_file()],
                "job": json.loads(job.read_text()) if job.is_file() else None,
                "report": json.loads(report.read_text()) if report.is_file() else None})
        name = self.path.removeprefix("/download/")
        allowed = {"report.json", "training.log", "supervisor.log",
                   "experimental-state-checkpoint.pt", "experimental-state-best.pt",
                   "checkpoint.json", "job.json"}
        if self.path.startswith("/download/") and name in allowed:
            file = ROOT / "results" / name
            if file.is_file():
                return self.respond(200, file.read_bytes(), "application/octet-stream")
        return self.respond(404, {"error": "not_found"})


if __name__ == "__main__":
    if not os.path.ismount(ROOT.resolve()):
        raise SystemExit("/workspace must be a mounted persistent volume")
    ROOT.mkdir(parents=True, exist_ok=True)
    start_if_ready()
    port = int(os.environ.get("TFT_RECEIVER_PORT", "8080"))
    print(f"Experimental video-state receiver ready on port {port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
