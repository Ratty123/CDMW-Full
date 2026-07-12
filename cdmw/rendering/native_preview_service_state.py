"""Nonblocking state probes for the shared native preview service."""

from __future__ import annotations

from cdmw.rendering import native_preview_core as _core


def native_preview_core_service_process_id() -> int:
    """Return the live shared-service PID without waiting for an active job."""
    if not _core._native_preview_core_service_lock.acquire(blocking=False):
        return 0
    try:
        service = _core._native_preview_core_service
        if service is None or not service._lock.acquire(blocking=False):
            return 0
        try:
            process = service._process
            if process is None or process.poll() is not None:
                return 0
            try:
                return int(getattr(process, "pid", 0) or 0)
            except (AttributeError, TypeError, ValueError):
                return 0
        finally:
            service._lock.release()
    finally:
        _core._native_preview_core_service_lock.release()


__all__ = ["native_preview_core_service_process_id"]
