from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled


PROCESS_TERMINATION_GRACE_SECONDS = 1.0
PROCESS_DIAGNOSTIC_TAIL_CHARS = 64 * 1024
PROCESS_PROTOCOL_LINE_MAX_CHARS = 16 * 1024 * 1024


class ProcessTimeoutExpired(RuntimeError):
    def __init__(
        self,
        cmd: Sequence[str],
        timeout_seconds: float,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.cmd = tuple(str(part) for part in cmd)
        self.timeout_seconds = float(timeout_seconds)
        self.stdout = stdout
        self.stderr = stderr
        command_label = self.cmd[0] if self.cmd else "process"
        super().__init__(f"{command_label} timed out after {self.timeout_seconds:.0f}s")


def read_file_bytes_cancellable(
    path: Path | str,
    *,
    stop_event: Optional[threading.Event] = None,
    max_bytes: Optional[int] = None,
    chunk_size: int = 1024 * 1024,
) -> bytes:
    """Read a bounded file in cancellation-sized chunks."""

    source = Path(path)
    raise_if_cancelled(stop_event)
    size = source.stat().st_size
    if max_bytes is not None and size > max(0, int(max_bytes)):
        raise ValueError(f"File is too large ({size:,} bytes; maximum {int(max_bytes):,}).")
    chunks: List[bytes] = []
    total = 0
    with source.open("rb") as handle:
        while True:
            raise_if_cancelled(stop_event)
            chunk = handle.read(max(4096, int(chunk_size)))
            if not chunk:
                break
            total += len(chunk)
            if max_bytes is not None and total > max(0, int(max_bytes)):
                raise ValueError(f"File exceeds the {int(max_bytes):,}-byte limit.")
            chunks.append(chunk)
    raise_if_cancelled(stop_event)
    return b"".join(chunks)


def read_text_file_cancellable(
    path: Path | str,
    *,
    stop_event: Optional[threading.Event] = None,
    max_bytes: Optional[int] = None,
    encoding: str = "utf-8",
    errors: str = "strict",
) -> str:
    return read_file_bytes_cancellable(
        path,
        stop_event=stop_event,
        max_bytes=max_bytes,
    ).decode(encoding, errors=errors)


def hidden_subprocess_kwargs() -> Dict[str, object]:
    if os.name != "nt":
        return {}

    kwargs: Dict[str, object] = {}
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if creationflags:
        kwargs["creationflags"] = creationflags

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= int(getattr(subprocess, "STARTF_USESHOWWINDOW", 0))
    startupinfo.wShowWindow = int(getattr(subprocess, "SW_HIDE", 0))
    kwargs["startupinfo"] = startupinfo
    return kwargs


def hidden_process_group_kwargs() -> Dict[str, object]:
    """Return hidden-window flags plus an independently stoppable process group."""

    kwargs = hidden_subprocess_kwargs()
    if os.name == "nt":
        kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True
    return kwargs


class BoundedTextTail:
    """Thread-safe tail used while continuously draining helper diagnostics."""

    def __init__(self, max_chars: int = PROCESS_DIAGNOSTIC_TAIL_CHARS) -> None:
        self.max_chars = max(1, int(max_chars))
        self._lock = threading.Lock()
        self._text = ""

    def append(self, value: object) -> None:
        text = str(value or "")
        if not text:
            return
        with self._lock:
            self._text = (self._text + text)[-self.max_chars :]

    def text(self) -> str:
        with self._lock:
            return self._text


def start_bounded_text_stream_drain(
    stream: object,
    *,
    name: str,
    max_chars: int = PROCESS_DIAGNOSTIC_TAIL_CHARS,
) -> Tuple[threading.Thread, BoundedTextTail]:
    """Drain a text pipe continuously so a verbose helper cannot deadlock."""

    tail = BoundedTextTail(max_chars)

    def drain() -> None:
        read = getattr(stream, "read", None)
        if not callable(read):
            return
        while True:
            try:
                chunk = read(4096)
            except (OSError, ValueError):
                return
            if not chunk:
                return
            tail.append(chunk)

    thread = threading.Thread(target=drain, name=name, daemon=True)
    thread.start()
    return thread, tail


def read_bounded_text_line(stream: object, *, max_chars: int = PROCESS_PROTOCOL_LINE_MAX_CHARS) -> str:
    """Read one helper-protocol line without permitting an unbounded buffer."""

    limit = max(1, int(max_chars))
    readline = getattr(stream, "readline", None)
    if not callable(readline):
        raise OSError("helper stdout does not support line reads")
    try:
        value = readline(limit + 1)
    except TypeError:
        value = readline()
    text = str(value or "")
    if len(text) > limit:
        raise ValueError(f"helper protocol line exceeds {limit:,} characters")
    return text


def _windows_descendant_pids(root_pid: int) -> Tuple[int, ...]:
    if os.name != "nt":
        return ()
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
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
    process_first.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    process_first.restype = wintypes.BOOL
    process_next = kernel32.Process32NextW
    process_next.argtypes = (wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W))
    process_next.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    snapshot = create_snapshot(0x00000002, 0)
    if ctypes.cast(snapshot, ctypes.c_void_p).value == ctypes.c_void_p(-1).value:
        return ()
    children_by_parent: Dict[int, List[int]] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        if process_first(snapshot, ctypes.byref(entry)):
            while True:
                children_by_parent.setdefault(int(entry.th32ParentProcessID), []).append(int(entry.th32ProcessID))
                if not process_next(snapshot, ctypes.byref(entry)):
                    break
    finally:
        close_handle(snapshot)

    descendants: List[int] = []
    pending = list(children_by_parent.get(int(root_pid), ()))
    while pending:
        process_id = pending.pop(0)
        if process_id in descendants:
            continue
        descendants.append(process_id)
        pending.extend(children_by_parent.get(process_id, ()))
    return tuple(descendants)


def _terminate_windows_pid(process_id: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    open_process.restype = wintypes.HANDLE
    terminate_process = kernel32.TerminateProcess
    terminate_process.argtypes = (wintypes.HANDLE, wintypes.UINT)
    terminate_process.restype = wintypes.BOOL
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    wait_for_single_object.restype = wintypes.DWORD
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL
    handle = open_process(0x0001 | 0x00100000, False, int(process_id))
    if not handle:
        return
    try:
        if terminate_process(handle, 1):
            wait_for_single_object(handle, 5000)
    finally:
        close_handle(handle)


def force_stop_windows_process_tree(root_pid: int, *, include_root: bool = True) -> None:
    """Force-stop a known Windows child tree; no-op on other platforms."""

    if os.name != "nt":
        return
    try:
        process_id = int(root_pid)
    except (TypeError, ValueError):
        return
    if process_id <= 0:
        return
    for descendant in reversed(_windows_descendant_pids(process_id)):
        _terminate_windows_pid(descendant)
    if include_root:
        _terminate_windows_pid(process_id)


def _request_process_tree_stop(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
    except (AttributeError, OSError, ValueError):
        terminate = getattr(proc, "terminate", None)
        if callable(terminate):
            try:
                terminate()
                return
            except OSError:
                pass
        kill = getattr(proc, "kill", None)
        if callable(kill):
            try:
                kill()
            except OSError:
                pass


def _force_stop_process_tree(proc: subprocess.Popen[str], known_descendants: Sequence[int]) -> None:
    if os.name == "nt":
        root_pid = int(getattr(proc, "pid", 0) or 0)
        descendants = tuple(
            dict.fromkeys((*known_descendants, *(_windows_descendant_pids(root_pid) if root_pid > 0 else ())))
        )
        for process_id in reversed(descendants):
            _terminate_windows_pid(process_id)
        try:
            proc.kill()
        except OSError:
            pass
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass


def finish_process_tree(
    proc: subprocess.Popen[str],
    *,
    grace_seconds: float = PROCESS_TERMINATION_GRACE_SECONDS,
    request_stop: bool = True,
) -> None:
    """Give a process tree bounded grace, then force-stop remaining processes."""

    try:
        root_pid = int(getattr(proc, "pid", 0) or 0)
    except (TypeError, ValueError):
        root_pid = 0
    known_descendants = _windows_descendant_pids(root_pid) if root_pid > 0 else ()
    if request_stop:
        _request_process_tree_stop(proc)
    wait = getattr(proc, "wait", None)
    if not callable(wait):
        return
    try:
        wait(timeout=max(0.0, float(grace_seconds)))
    except subprocess.TimeoutExpired:
        _force_stop_process_tree(proc, known_descendants)
        try:
            wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
    else:
        if known_descendants:
            _force_stop_process_tree(proc, known_descendants)


def run_process_with_cancellation(
    cmd: Sequence[str],
    stop_event: Optional[threading.Event] = None,
    env_overrides: Optional[Dict[str, Optional[str]]] = None,
    on_poll: Optional[Callable[[], None]] = None,
    on_cancel: Optional[Callable[[subprocess.Popen], None]] = None,
    timeout_seconds: Optional[float] = None,
    timeout_warning_interval_seconds: float = 30.0,
    on_timeout_warning: Optional[Callable[[float], None]] = None,
) -> Tuple[int, str, str]:
    env: Optional[Dict[str, str]] = None
    if env_overrides:
        env = dict(os.environ)
        for key, value in env_overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value

    popen_kwargs = hidden_process_group_kwargs()
    proc = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        **popen_kwargs,
    )

    start_time = time.monotonic()
    timeout_deadline = start_time + float(timeout_seconds) if timeout_seconds and timeout_seconds > 0 else None
    next_timeout_warning = (
        start_time + max(0.1, float(timeout_warning_interval_seconds))
        if timeout_deadline is not None and on_timeout_warning is not None
        else None
    )

    def terminate_process() -> Tuple[str, str]:
        known_descendants = _windows_descendant_pids(proc.pid)
        _request_process_tree_stop(proc)
        try:
            stdout_text, stderr_text = proc.communicate(timeout=PROCESS_TERMINATION_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            _force_stop_process_tree(proc, known_descendants)
            try:
                stdout_text, stderr_text = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
                stdout_text, stderr_text = proc.communicate()
        else:
            # A parent can exit while a detached child survives. Kill descendants
            # captured before the graceful stop even when the parent is already gone.
            if known_descendants:
                _force_stop_process_tree(proc, known_descendants)
        return stdout_text or "", stderr_text or ""

    try:
        while True:
            raise_if_cancelled(stop_event)
            if on_poll:
                on_poll()
            now = time.monotonic()
            if timeout_deadline is not None:
                if now >= timeout_deadline:
                    stdout, stderr = terminate_process()
                    raise ProcessTimeoutExpired(cmd, float(timeout_seconds or 0), stdout, stderr)
                if next_timeout_warning is not None and now >= next_timeout_warning:
                    try:
                        on_timeout_warning(max(0.0, now - start_time))
                    except Exception:
                        pass
                    next_timeout_warning = now + max(0.1, float(timeout_warning_interval_seconds))
            try:
                stdout, stderr = proc.communicate(timeout=0.2)
                if on_poll:
                    on_poll()
                return proc.returncode, stdout or "", stderr or ""
            except subprocess.TimeoutExpired:
                continue
    except RunCancelled:
        if on_cancel is not None:
            try:
                on_cancel(proc)
            except Exception:
                pass
        terminate_process()
        raise RunCancelled("Processing stopped by user.")


def split_log_lines(text: str) -> List[str]:
    return [line.rstrip() for line in text.replace("\r", "\n").split("\n") if line.strip()]


def sleep_with_cancellation(seconds: float, stop_event: Optional[threading.Event]) -> None:
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        raise_if_cancelled(stop_event)
        time.sleep(min(0.2, deadline - time.monotonic()))


def read_u32_le(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little", signed=False)

