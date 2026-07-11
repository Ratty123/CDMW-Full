"""Archive preview native-core worker and idle-shutdown helpers."""

from __future__ import annotations

import time
from typing import Optional

from cdmw.services.preview_rendering_service import shutdown_native_preview_core_service


class ArchivePreviewNativeCoreLifecycleMixin:
    """Lifecycle helpers for the shared native preview core service."""

    def _native_preview_core_worker_active(self) -> bool:
        for thread in (
            getattr(self, "archive_preview_thread", None),
            getattr(self, "archive_native_prefetch_thread", None),
        ):
            if thread is None:
                continue
            try:
                if thread.isRunning():
                    return True
            except RuntimeError:
                continue
        return False

    def _note_native_preview_core_activity(self) -> None:
        self.archive_preview_core_last_activity_at = time.monotonic()
        self.archive_preview_core_idle_shutdown_timer.stop()

    def _schedule_native_preview_core_idle_shutdown(self, delay_ms: Optional[int] = None) -> None:
        delay = self.archive_preview_core_idle_shutdown_ms if delay_ms is None else int(delay_ms)
        if delay <= 0 or self._shutting_down:
            return
        self.archive_preview_core_idle_shutdown_timer.start(delay)

    def _shutdown_idle_native_preview_core_service(self) -> None:
        if self._shutting_down:
            return
        if self._native_preview_core_worker_active():
            self._schedule_native_preview_core_idle_shutdown(delay_ms=30000)
            return
        idle_ms = max(0.0, (time.monotonic() - float(self.archive_preview_core_last_activity_at or 0.0)) * 1000.0)
        shutdown_native_preview_core_service()
        self.archive_preview_core_idle_shutdown_count += 1
        recorder = getattr(self, "_record_runtime_event", None)
        if callable(recorder):
            recorder(
                "native_preview_core_idle_shutdown",
                idle_ms=round(idle_ms, 1),
                shutdown_count=int(self.archive_preview_core_idle_shutdown_count),
            )
        self._record_archive_memory_audit("preview_core_idle_shutdown")
