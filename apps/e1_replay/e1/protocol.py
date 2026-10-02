"""Resident native IPC. Reader thread bounds responses; timeout kills owned tree."""
from __future__ import annotations
import json, os, queue, signal, subprocess, threading, time
from pathlib import Path


def spawn(args, **kwargs):
    opts = dict(kwargs)
    if os.name == 'nt':
        opts['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        opts['start_new_session'] = True
    return subprocess.Popen([str(x) for x in args], **opts)


def terminate(proc):
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=10, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


class NativeWorker:
    def __init__(self, binary, configs, tesseract='tesseract', controls=None, log=None):
        args = [binary, '--configs', configs, tesseract]
        if controls:
            args.append(controls)
        self.stderr = open(log, 'xb') if log else subprocess.DEVNULL
        self.proc = spawn(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=self.stderr, bufsize=0)
        self.answers = queue.Queue(maxsize=2)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()
        ready = self._answer(20)
        if not ready.get('ready') or ready.get('protocol') != 1:
            self.close()
            raise ValueError('native handshake failed')
        self.ready = ready

    def _read(self):
        try:
            while True:
                line = self.proc.stdout.readline(4 * 1024**2 + 1)
                if not line:
                    raise EOFError('native worker ended')
                if len(line) > 4 * 1024**2 or not line.endswith(b'\n'):
                    raise ValueError('native response budget')
                value = json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
                self.answers.put(value, timeout=5)
        except Exception as exc:
            try:
                self.answers.put(exc, timeout=1)
            except queue.Full:
                pass

    def _answer(self, timeout):
        try:
            value = self.answers.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise TimeoutError('native deadline exceeded; owned process tree stopped')
        if isinstance(value, Exception):
            self.close()
            raise value
        return value

    def request(self, header, payload=b'', timeout=12):
        if self.proc.poll() is not None:
            raise RuntimeError('native process unavailable')
        raw = json.dumps(header, allow_nan=False, separators=(',', ':')).encode() + b'\n'
        if len(raw) > 65536:
            raise ValueError('request header budget')
        # Writing is supervised too: a hung child must not deadlock the pipeline.
        failure = []
        def write():
            try:
                for buf in (raw, payload):
                    view = memoryview(buf)
                    while view:
                        n = self.proc.stdin.write(view)
                        if not n:
                            raise BrokenPipeError('native input closed')
                        view = view[n:]
            except Exception as exc:
                failure.append(exc)
        thread = threading.Thread(target=write, daemon=True)
        thread.start()
        start = time.monotonic()
        thread.join(timeout)
        if thread.is_alive():
            self.close()
            raise TimeoutError('native input write deadline')
        if failure:
            self.close()
            raise failure[0]
        value = self._answer(max(.01, timeout - (time.monotonic() - start)))
        if value.get('id') != header['id']:
            self.close()
            raise ValueError('native frame identity mismatch')
        return value

    def close(self):
        terminate(self.proc)
        for f in (self.proc.stdin, self.proc.stdout):
            if f:
                try:
                    f.close()
                except OSError:
                    pass
        if hasattr(self.stderr, 'close'):
            self.stderr.close()
