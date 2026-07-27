"""Terminate helper processes stranded by an earlier session's unclean exit.

The job object in :mod:`cdmw.services.process_job_service` prevents new strays,
but it cannot clean up what an older build already leaked, and it does not cover
a helper launched outside the job by a harness whose driver then died. Those
survivors are not harmless: a stranded renderer holds a D3D11 device, and a
stranded archive worker keeps a mapped cache file that this session then cannot
replace.

Reaping runs on a deliberately narrow rule, because identically named helpers
belong to other installations and to concurrently running sessions. A process is
reaped only when all of these hold:

* its image name is one this app owns, and
* its image lives under this installation's root, and
* its parent is gone -- either absent from the snapshot, or a recycled PID whose
  process started after the child did.

A live parent means somebody still owns the helper, so it is left alone.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path


OWNED_HELPER_BINARY_NAMES = frozenset(
    {
        "cdmw-mesh-dotnet-editor.exe",
        "cdmw-full-archive-worker.exe",
        "cdmw-mesh-core.exe",
        "cdmw-preview-core.exe",
        "cdmw-archive-accelerator.exe",
        "cd-texture-dx.exe",
        "cd-hkx.exe",
    }
)

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TH32CS_SNAPPROCESS = 0x00000002


def owned_installation_roots() -> tuple[Path, ...]:
    """Directories whose helper binaries belong to this installation."""

    roots: list[Path] = []
    meipass = str(getattr(sys, "_MEIPASS", "") or "")
    if meipass:
        roots.append(Path(meipass))
    if bool(getattr(sys, "frozen", False)):
        try:
            roots.append(Path(sys.executable).resolve().parent)
        except OSError:
            pass
    else:
        # Running from source: helpers live under the repository that this
        # module is part of, which is what keeps a sibling checkout's
        # identically named helper out of scope.
        roots.append(Path(__file__).resolve().parents[2])

    resolved: list[Path] = []
    for root in roots:
        try:
            candidate = root.resolve()
        except OSError:
            continue
        if candidate not in resolved:
            resolved.append(candidate)
    return tuple(resolved)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _snapshot_processes() -> tuple[tuple[int, int, str], ...]:
    """Every (pid, parent_pid, image_name) the current user can enumerate."""

    import ctypes
    from ctypes import wintypes

    class ProcessEntry32W(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        )

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_snapshot = kernel32.CreateToolhelp32Snapshot
    create_snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    create_snapshot.restype = wintypes.HANDLE
    process_first = kernel32.Process32FirstW
    process_first.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W))
    process_first.restype = wintypes.BOOL
    process_next = kernel32.Process32NextW
    process_next.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry32W))
    process_next.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    snapshot = create_snapshot(_TH32CS_SNAPPROCESS, 0)
    if ctypes.cast(snapshot, ctypes.c_void_p).value == ctypes.c_void_p(-1).value:
        return ()
    processes: list[tuple[int, int, str]] = []
    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(entry)
        if process_first(snapshot, ctypes.byref(entry)):
            while True:
                processes.append(
                    (
                        int(entry.th32ProcessID),
                        int(entry.th32ParentProcessID),
                        str(entry.szExeFile or ""),
                    )
                )
                if not process_next(snapshot, ctypes.byref(entry)):
                    break
    finally:
        close_handle(snapshot)
    return tuple(processes)


def _process_image_path_and_start(process_id: int) -> tuple[str, int]:
    """Full image path and creation time, or ``("", 0)`` when unreadable."""

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    query_image_name = kernel32.QueryFullProcessImageNameW
    query_image_name.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    query_image_name.restype = wintypes.BOOL
    get_process_times = kernel32.GetProcessTimes
    get_process_times.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    )
    get_process_times.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = open_process(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(process_id))
    if not handle:
        return "", 0
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        image_path = buffer.value if query_image_name(handle, 0, buffer, ctypes.byref(size)) else ""

        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        started = 0
        if get_process_times(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            started = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
        return str(image_path or ""), started
    finally:
        close_handle(handle)


def find_orphaned_helper_processes(
    *,
    helper_names: Iterable[str] = OWNED_HELPER_BINARY_NAMES,
    roots: Sequence[Path] | None = None,
) -> tuple[tuple[int, str], ...]:
    """Owned helper processes whose parent is gone, as ``(pid, image_path)``."""

    if os.name != "nt":
        return ()
    owned_roots = tuple(roots) if roots is not None else owned_installation_roots()
    if not owned_roots:
        return ()
    wanted = {str(name).casefold() for name in helper_names}

    try:
        processes = _snapshot_processes()
    except (AttributeError, OSError, ValueError):
        return ()
    if not processes:
        return ()

    live_pids = {pid for pid, _parent, _name in processes}
    current_pid = os.getpid()
    start_time_cache: dict[int, int] = {}

    def started_at(process_id: int) -> int:
        if process_id not in start_time_cache:
            try:
                start_time_cache[process_id] = _process_image_path_and_start(process_id)[1]
            except (AttributeError, OSError, ValueError):
                start_time_cache[process_id] = 0
        return start_time_cache[process_id]

    orphans: list[tuple[int, str]] = []
    for pid, parent_pid, name in processes:
        if pid == current_pid or pid <= 4:
            continue
        if name.casefold() not in wanted:
            continue
        try:
            image_path, started = _process_image_path_and_start(pid)
        except (AttributeError, OSError, ValueError):
            continue
        if not image_path:
            continue
        start_time_cache[pid] = started
        try:
            resolved_image = Path(image_path).resolve()
        except OSError:
            continue
        if not any(_path_is_within(resolved_image, root) for root in owned_roots):
            continue

        if parent_pid in live_pids:
            parent_started = started_at(parent_pid)
            # A parent that started after its child is a recycled PID, not the
            # real parent, so the child is orphaned after all. Unknown times
            # (0) are treated as a live parent, which errs toward leaving it be.
            if not (parent_started and started and parent_started > started):
                continue
        orphans.append((pid, str(resolved_image)))
    return tuple(orphans)


def reap_orphaned_helper_processes(
    *,
    helper_names: Iterable[str] = OWNED_HELPER_BINARY_NAMES,
    roots: Sequence[Path] | None = None,
) -> tuple[tuple[int, str], ...]:
    """Terminate this installation's parentless helpers; return what was reaped.

    Best effort by design: a helper this process cannot open is one it does not
    own, and failing startup over it would be worse than leaving it running.
    """

    from cdmw.services.process_control_service import force_stop_windows_process_tree

    orphans = find_orphaned_helper_processes(helper_names=helper_names, roots=roots)
    reaped: list[tuple[int, str]] = []
    for pid, image_path in orphans:
        try:
            force_stop_windows_process_tree(pid, include_root=True)
        except (OSError, ValueError):
            continue
        reaped.append((pid, image_path))
    return tuple(reaped)


__all__ = [
    "OWNED_HELPER_BINARY_NAMES",
    "find_orphaned_helper_processes",
    "owned_installation_roots",
    "reap_orphaned_helper_processes",
]
