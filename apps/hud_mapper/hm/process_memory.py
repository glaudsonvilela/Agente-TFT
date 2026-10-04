"""Working set telemetry for the Windows HUD process, sampled outside the frame path."""
from __future__ import annotations

import os


def current_process_memory() -> dict[str, int] | None:
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCountersEx(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("page_fault_count", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "peak_working_set_size", "working_set_size", "quota_peak_paged_pool_usage",
                "quota_paged_pool_usage", "quota_peak_non_paged_pool_usage",
                "quota_non_paged_pool_usage", "pagefile_usage", "peak_pagefile_usage",
                "private_usage")]

    counters = ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return None
    return {"working_set_bytes": counters.working_set_size,
            "private_bytes": counters.private_usage}
