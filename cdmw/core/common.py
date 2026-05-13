from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from cdmw.models import RunCancelled


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


def raise_if_cancelled(stop_event: Optional[threading.Event], message: str = "Processing stopped by user.") -> None:
    if stop_event and stop_event.is_set():
        raise RunCancelled(message)


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

    proc = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        **hidden_subprocess_kwargs(),
    )

    start_time = time.monotonic()
    timeout_deadline = start_time + float(timeout_seconds) if timeout_seconds and timeout_seconds > 0 else None
    next_timeout_warning = (
        start_time + max(0.1, float(timeout_warning_interval_seconds))
        if timeout_deadline is not None and on_timeout_warning is not None
        else None
    )

    def terminate_process() -> Tuple[str, str]:
        try:
            proc.terminate()
        except OSError:
            pass
        try:
            stdout_text, stderr_text = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
            stdout_text, stderr_text = proc.communicate()
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

