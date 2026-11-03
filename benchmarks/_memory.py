"""Peak resident memory of the current process, in MB, on Linux, macOS and Windows.

Benchmark scripts need one number comparable across the project's three
platforms (ARCHITECTURE.md); the stdlib gives it two different ways, and
Windows has no ``resource`` module at all.
"""

import ctypes
import sys


def peak_rss_mb() -> float:
    """Peak resident/working set size of this process so far, in MB."""
    if sys.platform == "win32":
        return _peak_rss_mb_windows()
    import resource  # POSIX only

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KB, macOS reports bytes.
    return peak / 1024 if sys.platform == "linux" else peak / (1024 * 1024)


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _peak_rss_mb_windows() -> float:
    # GetCurrentProcess returns a pointer-sized pseudo handle; ctypes defaults
    # to a 32-bit int return and truncates it on 64-bit Windows otherwise.
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.windll.psapi  # type: ignore[attr-defined]
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    process = kernel32.GetCurrentProcess()
    ok = psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
    if not ok:
        raise ctypes.WinError()  # type: ignore[attr-defined]
    return counters.PeakWorkingSetSize / (1024 * 1024)
