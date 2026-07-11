"""Bounded, nonblocking process IO helpers for Mesh Editor child tools."""

from __future__ import annotations

from PySide6.QtCore import QProcess, QTimer

from cdmw.services.process_control_service import force_stop_windows_process_tree


DOTNET_PROTOCOL_BUFFER_LIMIT = 1024 * 1024
DOTNET_PROTOCOL_LINE_LIMIT = 256 * 1024
DOTNET_PROTOCOL_EVENT_LIMIT = 256
PROCESS_STREAM_TAIL_LIMIT = 64 * 1024


def append_bounded_text(current: str, value: object, *, max_chars: int = PROCESS_STREAM_TAIL_LIMIT) -> str:
    text = current + str(value or "")
    return text[-max(1, int(max_chars)) :]


def qprocess_is_running(process: object) -> bool:
    try:
        not_running = getattr(process, "NotRunning", QProcess.NotRunning)
        return process.state() != not_running  # type: ignore[attr-defined]
    except (AttributeError, RuntimeError):
        return False


def stop_qprocess_async(process: object, *, grace_ms: int = 1000) -> None:
    """Request graceful stop and force-kill later without blocking Qt's thread."""

    deleted = False
    try:
        process_id = int(process.processId())  # type: ignore[attr-defined]
    except (AttributeError, RuntimeError, TypeError, ValueError):
        process_id = 0

    def delete_when_stopped(*_args: object) -> None:
        nonlocal deleted
        if deleted or qprocess_is_running(process):
            return
        deleted = True
        try:
            process.deleteLater()  # type: ignore[attr-defined]
        except (AttributeError, RuntimeError):
            pass

    finished = getattr(process, "finished", None)
    connect = getattr(finished, "connect", None)
    if callable(connect):
        try:
            connect(delete_when_stopped)
        except (RuntimeError, TypeError):
            pass
    if not qprocess_is_running(process):
        delete_when_stopped()
        return
    try:
        process.terminate()  # type: ignore[attr-defined]
    except (AttributeError, RuntimeError):
        pass
    if not qprocess_is_running(process):
        delete_when_stopped()
        return

    def force_after_grace() -> None:
        if not qprocess_is_running(process):
            delete_when_stopped()
            return
        force_stop_windows_process_tree(process_id, include_root=False)
        try:
            process.kill()  # type: ignore[attr-defined]
        except (AttributeError, RuntimeError):
            pass
        QTimer.singleShot(0, delete_when_stopped)

    QTimer.singleShot(max(0, int(grace_ms)), force_after_grace)


__all__ = [
    "DOTNET_PROTOCOL_BUFFER_LIMIT",
    "DOTNET_PROTOCOL_EVENT_LIMIT",
    "DOTNET_PROTOCOL_LINE_LIMIT",
    "PROCESS_STREAM_TAIL_LIMIT",
    "append_bounded_text",
    "qprocess_is_running",
    "stop_qprocess_async",
]
