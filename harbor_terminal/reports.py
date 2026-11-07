"""Local diagnostic reports. No network upload or credential collection."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.harbor-report-', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as output:
            json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write('\n'); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def resources():
    value = dict(threads=threading.active_count(), monotonic=time.monotonic())
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        class Memory(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ('peak_working_set','working_set',
                'peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        process = kernel.GetCurrentProcess()
        memory = Memory(); memory.cb = ctypes.sizeof(memory)
        query = ctypes.windll.psapi.GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        query.restype = wintypes.BOOL
        if query(process, ctypes.byref(memory), memory.cb): value['rss_bytes'] = memory.working_set
        count = wintypes.DWORD()
        kernel.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        if kernel.GetProcessHandleCount(process, ctypes.byref(count)): value['handles'] = count.value
    elif Path('/proc/self/statm').exists():
        value['rss_bytes'] = int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
        value['handles'] = len(list(Path('/proc/self/fd').iterdir()))
    return value
