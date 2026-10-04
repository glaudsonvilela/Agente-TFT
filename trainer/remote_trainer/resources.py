"""Lightweight cgroup and host resource readings for the local dashboard."""
from __future__ import annotations

from pathlib import Path
import time
from typing import Callable


class ResourceSampler:
    def __init__(self, *, cgroup: Path = Path('/sys/fs/cgroup'),
                 proc: Path = Path('/proc'), clock: Callable[[], float] = time.monotonic):
        self.cgroup = Path(cgroup)
        self.proc = Path(proc)
        self.clock = clock
        self._previous_container: tuple[float, int] | None = None
        self._previous_host: tuple[int, int] | None = None

    @staticmethod
    def _number(path: Path) -> int | None:
        try:
            return int(path.read_text().strip())
        except (OSError, ValueError):
            return None

    def sample(self) -> dict:
        now = self.clock()
        cpu_stat = {}
        try:
            for line in (self.cgroup / 'cpu.stat').read_text().splitlines():
                key, value = line.split(maxsplit=1)
                cpu_stat[key] = int(value)
        except (OSError, ValueError):
            pass
        usage = cpu_stat.get('usage_usec')
        cores_used = None
        if usage is not None:
            if self._previous_container is not None:
                previous_time, previous_usage = self._previous_container
                elapsed = now - previous_time
                if elapsed > 0 and usage >= previous_usage:
                    cores_used = round((usage - previous_usage) / (elapsed * 1_000_000), 3)
            self._previous_container = (now, usage)
        limit_cores = None
        try:
            quota, period = (self.cgroup / 'cpu.max').read_text().split()[:2]
            if quota != 'max' and int(period) > 0:
                limit_cores = round(int(quota) / int(period), 3)
        except (OSError, ValueError, IndexError):
            pass
        memory_used = self._number(self.cgroup / 'memory.current')
        memory_limit = self._number(self.cgroup / 'memory.max')
        mib = 1024 * 1024
        container = {
            'cpu_cores_used': cores_used,
            'cpu_limit_cores': limit_cores,
            'cpu_percent_of_limit': round(100 * cores_used / limit_cores, 1)
            if cores_used is not None and limit_cores else None,
            'memory_used_mib': round(memory_used / mib, 1) if memory_used is not None else None,
            'memory_limit_mib': round(memory_limit / mib, 1) if memory_limit is not None else None,
            'memory_percent_of_limit': round(100 * memory_used / memory_limit, 1)
            if memory_used is not None and memory_limit else None,
        }
        host_cpu = None
        try:
            fields = [int(value) for value in (self.proc / 'stat').read_text().splitlines()[0].split()[1:]]
            total = sum(fields)
            idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
            if self._previous_host is not None:
                previous_total, previous_idle = self._previous_host
                delta = total - previous_total
                if delta > 0 and idle >= previous_idle:
                    host_cpu = round(100 * (1 - (idle - previous_idle) / delta), 1)
            self._previous_host = (total, idle)
        except (OSError, ValueError, IndexError):
            pass
        memory = {}
        try:
            for line in (self.proc / 'meminfo').read_text().splitlines():
                key, value = line.split(':', 1)
                if key in {'MemTotal', 'MemAvailable'}:
                    memory[key] = int(value.strip().split()[0]) * 1024
        except (OSError, ValueError, IndexError):
            pass
        total = memory.get('MemTotal')
        available = memory.get('MemAvailable')
        host = {
            'cpu_percent': host_cpu,
            'memory_used_mib': round((total - available) / mib, 1)
            if total is not None and available is not None and total >= available else None,
            'memory_total_mib': round(total / mib, 1) if total is not None else None,
        }
        return {'container': container, 'host': host}
