"""The readiness watchdog of the resident .NET/Vortice session.

A fixed deadline from launch to ``ready`` killed healthy helpers on a loaded
machine, and the host then relaunched them into the same deadline, forever.
The helper reports ``startup_progress`` at every startup phase; each report
re-arms the deadline within a per-launch cap. Split from ``dotnet_session`` to
keep that module inside the owned-file line cap.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

_READY_TIMEOUT_MS = 10_000
# A helper that keeps reporting startup progress is building, not hung. Each
# report re-arms the readiness watchdog, up to this much wall time per launch,
# so a loaded machine gets a slow open instead of a restart loop.
_READY_PROGRESS_CAP_MS = 90_000


class DotNetPreviewSessionReadyWatchdogMixin:
    """Expects ``_ready_timer`` (single-shot QTimer), ``_ready_watchdog_started``,
    ``_ready_watchdog_extensions`` and ``_last_event`` on the controller."""

    def _arm_ready_watchdog(self) -> None:
        """Start the readiness deadline and open a fresh progress budget."""

        self._ready_watchdog_started = time.monotonic()
        self._ready_watchdog_extensions = 0
        self._ready_timer.start(_READY_TIMEOUT_MS)

    def _extend_ready_watchdog_for_progress(self, payload: Mapping[str, object]) -> bool:
        """Re-arm the readiness deadline because the helper reported progress.

        The helper's startup marks arrive while its UI thread is inside the
        form constructor, where nothing else can prove it is alive. A helper
        that is still building is given the full deadline again from the last
        report, but never more than ``_READY_PROGRESS_CAP_MS`` per launch in
        total: a genuinely stuck helper still fails, just later.
        """

        if not self._ready_timer.isActive():
            return False
        elapsed_ms = (time.monotonic() - self._ready_watchdog_started) * 1000.0
        if elapsed_ms + _READY_TIMEOUT_MS > _READY_PROGRESS_CAP_MS:
            return False
        self._ready_watchdog_extensions += 1
        self._ready_timer.start(_READY_TIMEOUT_MS)
        self._last_event = {
            "event": "ready_watchdog_extended",
            "phase": str(payload.get("phase", "") or ""),
            "helper_at_ms": payload.get("at_ms", 0),
            "elapsed_ms": round(elapsed_ms, 1),
            "extensions": self._ready_watchdog_extensions,
        }
        return True
