"""A small minidump of CDMW when it dies of a native fault (Windows).

``faulthandler`` writes every thread's Python stack to native_fault_current.log,
but on Windows it cannot read the C stack ("<cannot get C stack on this
system>"), and a crash inside Qt or PySide shows only "<no Python frame>". This
adds an unhandled-exception filter that writes a minidump next to that log, so
the crashing thread's C stack can be read with a debugger afterwards.

The dump holds every thread's stack, the loaded modules and thread information
(MiniDumpNormal with thread info and unloaded modules: a few megabytes, no heap).
It is written only when the process dies of an exception nothing handled, after
faulthandler (a vectored handler, so it runs first) has written its log. The
filter then hands the exception on unchanged, so the process still ends with its
own exit code (0xC0000005 for an access violation). Only the newest few dumps
are kept.

Set CDMW_NATIVE_CRASH_DUMP=0 to leave it off. The filter is Python code called
through ctypes, so it needs the GIL: everything it uses is prepared here, and
the call itself is a handful of Win32 calls.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

DUMP_PREFIX = "native-crash-"
DUMP_SUFFIX = ".dmp"
#: Dumps kept in the folder, this run's included.
KEEP_DUMPS = 3

# MiniDumpNormal | MiniDumpWithUnloadedModules | MiniDumpWithThreadInfo
DUMP_TYPE = 0x00000000 | 0x00000020 | 0x00001000
_EXCEPTION_CONTINUE_SEARCH = 0
_GENERIC_WRITE = 0x40000000
_CREATE_ALWAYS = 2
_FILE_ATTRIBUTE_NORMAL = 0x80

#: Kept for the life of the process: the filter, its callback object and what it uses.
_installed: dict[str, object] = {}


def native_crash_dumps(directory: Path) -> list[Path]:
    """The dumps in ``directory``, newest first."""

    try:
        found = [path for path in Path(directory).glob(f"{DUMP_PREFIX}*{DUMP_SUFFIX}") if path.is_file()]
    except OSError:
        return []
    return sorted(found, key=lambda path: (path.stat().st_mtime, path.name), reverse=True)


def prune_native_crash_dumps(directory: Path, *, keep: int = KEEP_DUMPS) -> list[Path]:
    removed = []
    for path in native_crash_dumps(directory)[max(0, int(keep)):]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            pass
    return removed


def native_crash_dump_path(directory: Path, *, now: float | None = None, pid: int | None = None) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() if now is None else now))
    return Path(directory) / f"{DUMP_PREFIX}{stamp}-{os.getpid() if pid is None else pid}{DUMP_SUFFIX}"


def install_native_crash_dump(directory: Path, *, keep: int = KEEP_DUMPS) -> Path | None:
    """Write a minidump into ``directory`` if the process dies of a native fault.

    Returns the path the dump would be written to, or None when it is not
    installed (not Windows, turned off, already installed, or the Win32 calls
    are missing)."""

    if sys.platform != "win32" or os.environ.get("CDMW_NATIVE_CRASH_DUMP", "1").strip() == "0":
        return None
    if "filter" in _installed:
        return None
    try:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        # The dump about to be written counts: keep room for it.
        prune_native_crash_dumps(directory, keep=max(0, int(keep) - 1))
        return _install(native_crash_dump_path(directory))
    except Exception:  # noqa: BLE001 - crash evidence must never stop the app starting
        return None


def _install(path: Path) -> Path:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32")
    dbghelp = ctypes.WinDLL("dbghelp")

    class MinidumpExceptionInformation(ctypes.Structure):
        _pack_ = 4  # dbghelp.h packs its structures to four bytes
        _fields_ = [("ThreadId", wintypes.DWORD), ("ExceptionPointers", ctypes.c_void_p),
                    ("ClientPointers", wintypes.BOOL)]

    filter_type = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)

    create_file = kernel32.CreateFileW
    create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    current_process = kernel32.GetCurrentProcess
    current_process.argtypes = []
    current_process.restype = wintypes.HANDLE
    current_thread_id = kernel32.GetCurrentThreadId
    current_thread_id.argtypes = []
    current_thread_id.restype = wintypes.DWORD
    set_filter = kernel32.SetUnhandledExceptionFilter
    set_filter.argtypes = [ctypes.c_void_p]
    set_filter.restype = ctypes.c_void_p
    write_dump = dbghelp.MiniDumpWriteDump
    write_dump.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.HANDLE, ctypes.c_int,
                           ctypes.POINTER(MinidumpExceptionInformation), ctypes.c_void_p, ctypes.c_void_p]
    write_dump.restype = wintypes.BOOL

    target = str(path)
    pid = os.getpid()
    information = MinidumpExceptionInformation()
    information_pointer = ctypes.pointer(information)
    invalid_handle = wintypes.HANDLE(-1).value
    state = {"previous": None, "written": False}

    def on_unhandled_exception(pointers):
        if not state["written"]:
            state["written"] = True  # once: a fault while writing must not loop
            handle = create_file(target, _GENERIC_WRITE, 0, None, _CREATE_ALWAYS, _FILE_ATTRIBUTE_NORMAL, None)
            if handle and handle != invalid_handle:
                information.ThreadId = current_thread_id()
                information.ExceptionPointers = pointers
                information.ClientPointers = False
                write_dump(current_process(), pid, handle, DUMP_TYPE, information_pointer, None, None)
                close_handle(handle)
        previous = state["previous"]
        if previous is not None:
            return previous(pointers)
        return _EXCEPTION_CONTINUE_SEARCH

    callback = filter_type(on_unhandled_exception)
    previous = set_filter(ctypes.cast(callback, ctypes.c_void_p))
    if previous:
        state["previous"] = filter_type(previous)
    _installed.update(filter=callback, function=on_unhandled_exception, information=information,
                      pointer=information_pointer, calls=(create_file, close_handle, current_process,
                                                          current_thread_id, write_dump, set_filter),
                      libraries=(kernel32, dbghelp), state=state, path=path)
    return path


__all__ = [
    "DUMP_TYPE",
    "install_native_crash_dump",
    "native_crash_dump_path",
    "native_crash_dumps",
    "prune_native_crash_dumps",
]
