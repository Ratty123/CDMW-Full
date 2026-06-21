from __future__ import annotations

import ctypes
import os
from pathlib import Path
import tempfile
import time
from typing import Optional


APP_SINGLE_INSTANCE_MUTEX_NAME = "Local\\CrimsonDesertModWorkbench.SingleInstance"

_single_instance_mutex_handle: Optional[int] = None
_single_instance_lock_handle: Optional[object] = None


def acquire_single_instance_guard() -> bool:
    global _single_instance_mutex_handle, _single_instance_lock_handle
    if os.name != "nt":
        return True
    mutex_acquired = False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool

        handle = kernel32.CreateMutexW(None, True, APP_SINGLE_INSTANCE_MUTEX_NAME)
        if handle:
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(handle)
                return False
            _single_instance_mutex_handle = int(handle)
            mutex_acquired = True
    except Exception:
        pass
    try:
        import msvcrt

        lock_dir = Path(tempfile.gettempdir()) / "CrimsonDesertModWorkbench"
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_path = lock_dir / "single_instance.lock"
        lock_path.touch(exist_ok=True)
        lock_handle = lock_path.open("r+b")
        try:
            lock_handle.seek(0, os.SEEK_END)
            if lock_handle.tell() <= 0:
                lock_handle.write(b"\0")
                lock_handle.flush()
            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            lock_handle.close()
            if mutex_acquired:
                release_single_instance_guard()
            return False
        _single_instance_lock_handle = lock_handle
        try:
            lock_handle.seek(0)
            lock_handle.truncate()
            lock_handle.write(f"{os.getpid()}\n{time.time():.3f}\n".encode("ascii", "ignore"))
            lock_handle.flush()
        except Exception:
            pass
        return True
    except Exception:
        return bool(mutex_acquired)


def release_single_instance_guard() -> None:
    global _single_instance_mutex_handle, _single_instance_lock_handle
    lock_handle = _single_instance_lock_handle
    if lock_handle is not None:
        try:
            import msvcrt

            lock_handle.seek(0)
            msvcrt.locking(lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
        except Exception:
            pass
        try:
            lock_handle.close()
        except Exception:
            pass
        _single_instance_lock_handle = None
    handle = _single_instance_mutex_handle
    if not handle or os.name != "nt":
        _single_instance_mutex_handle = None
        return
    try:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        pass
    _single_instance_mutex_handle = None
