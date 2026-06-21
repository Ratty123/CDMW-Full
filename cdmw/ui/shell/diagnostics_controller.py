"""UI-thread diagnostics snapshot owner for the shell."""

from __future__ import annotations

import os
import ctypes
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    import shiboken6
except Exception:  # pragma: no cover - shipped with PySide6, defensive for test-only imports.
    shiboken6 = None


@dataclass(slots=True)
class CrashContextSnapshot:
    active_tab: str = ""
    active_archive: Path | None = None
    last_active_operation: str = ""
    worker_count: int = 0
    preview_backend: str = ""
    memory_summary: dict[str, Any] | None = None


class DiagnosticsController:
    def __init__(self, context: object | None = None) -> None:
        self.context = context
        self.snapshot = CrashContextSnapshot()


def d3d11_status_file_signature(stat: os.stat_result) -> tuple[int, int]:
    return (
        int(getattr(stat, "st_mtime_ns", int(float(getattr(stat, "st_mtime", 0.0) or 0.0) * 1_000_000_000))),
        int(getattr(stat, "st_size", 0) or 0),
    )


def d3d11_cache_event_user_label(event: object) -> str:
    normalized = str(event or "").strip().lower()
    if normalized in {"miss", "bypass", "new"}:
        return "new preview package"
    if normalized == "hit":
        return "cached preview package"
    if normalized == "material_dirty":
        return "material cache updated"
    if normalized == "cleared":
        return "preview package reset"
    return normalized or "preview package"


def start_heartbeat_timer(
    app: object,
    write_heartbeat: Callable[[], object],
    *,
    interval_ms: int = 5000,
    timer_factory: Callable[[object], object] | None = None,
) -> object:
    if timer_factory is None:
        from PySide6.QtCore import QTimer

        timer = QTimer(app)
    else:
        timer = timer_factory(app)
    timer.setInterval(max(1, int(interval_ms)))  # type: ignore[attr-defined]
    timer.timeout.connect(write_heartbeat)  # type: ignore[attr-defined]
    timer.start()  # type: ignore[attr-defined]
    return timer


class _ProcessMemoryCountersEx(ctypes.Structure):
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
        ("PrivateUsage", ctypes.c_size_t),
    ]


def windows_process_memory_snapshot(pid: int) -> dict[str, int]:
    if platform.system().lower() != "windows":
        return {}
    try:
        process_id = int(pid)
    except (TypeError, ValueError):
        return {}
    if process_id <= 0:
        return {}
    try:
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        process_query_limited_information = 0x1000
        process_vm_read = 0x0010
        kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ProcessMemoryCountersEx),
            ctypes.c_ulong,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        handle = kernel32.OpenProcess(
            process_query_limited_information | process_vm_read,
            False,
            process_id,
        )
        if not handle:
            return {}
        try:
            counters = _ProcessMemoryCountersEx()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return {}
            return {
                "pid": process_id,
                "working_set_bytes": int(counters.WorkingSetSize),
                "private_bytes": int(counters.PrivateUsage),
            }
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return {}


def qt_wrapper_is_valid(obj: object) -> bool:
    if obj is None:
        return False
    if shiboken6 is not None:
        try:
            return bool(shiboken6.isValid(obj))
        except Exception:
            return False
    try:
        obj.objectName()  # type: ignore[attr-defined]
        return True
    except RuntimeError:
        return False
    except Exception:
        return True


__all__ = [
    "CrashContextSnapshot",
    "DiagnosticsController",
    "d3d11_cache_event_user_label",
    "d3d11_status_file_signature",
    "qt_wrapper_is_valid",
    "start_heartbeat_timer",
    "windows_process_memory_snapshot",
]
