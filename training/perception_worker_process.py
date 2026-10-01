"""A1.6 POSIX subprocess supervisor. Internal helper, not a command service.

Parent keeps stdin open. EOF (including parent death) cancels the process group.
The inherited coordinator lock remains held until the helper has cleaned up.
"""
from __future__ import annotations
import os
from pathlib import Path
import resource
import select
import signal
import subprocess
import sys
import time


def kill_group(proc: subprocess.Popen) -> None:
    try: os.killpg(proc.pid,signal.SIGKILL)
    except ProcessLookupError: pass
    proc.wait()


def supervise(command: list[str], timeout: float, parent_fd: int=0) -> int:
    # Caps each output file, including descendants' inherited log descriptors.
    resource.setrlimit(resource.RLIMIT_FSIZE,(32*1024*1024,32*1024*1024))
    deadline=time.monotonic()+timeout
    proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,start_new_session=True,close_fds=True)
    try:
        while True:
            code=proc.poll()
            if code is not None:
                kill_group(proc)  # Reap any descendants left in its process group.
                return code if 0<=code<=125 else 125
            remaining=deadline-time.monotonic()
            if remaining<=0: return 124
            ready,_,_=select.select([parent_fd],[],[],min(.1,remaining))
            if ready and not os.read(parent_fd,1): return 125
    finally:
        kill_group(proc)


def execute_native(probe: Path, manifest: Path, image_root: Path, profile: Path,
                   output: Path, folder: Path, lock_fd: int, timeout: int=120) -> None:
    # Positional arguments only, fixed executable interface, no shell/task-supplied code.
    command=[sys.executable,'-m','training.perception_worker_process',str(timeout),
             str(probe),str(manifest),str(image_root),str(profile),str(output)]
    env=os.environ.copy();env['OMP_THREAD_LIMIT']='1'
    with (folder/'events.jsonl').open('xb') as stdout, (folder/'native.stderr').open('xb') as stderr:
        proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,
            start_new_session=True,pass_fds=(lock_fd,),env=env)
        try:
            code=proc.wait(timeout=timeout+10)
            if code: raise RuntimeError(f'native supervisor exited {code}; see native.stderr')
        finally:
            proc.stdin.close()
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill();proc.wait()


def main() -> None:
    # The public worker constructs this argument vector. Never read an executable
    # path or shell command from the work-source JSON.
    args=sys.argv[1:]
    if len(args)!=6: raise SystemExit('internal supervisor requires timeout and five native arguments')
    timeout=int(args[0])
    if not 1<=timeout<=120: raise SystemExit('invalid native timeout')
    raise SystemExit(supervise(args[1:],timeout))


if __name__=='__main__': main()
