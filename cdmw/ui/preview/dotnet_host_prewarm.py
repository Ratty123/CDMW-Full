"""Best-effort background prewarm task for the resident Rust preview host.

The hidden spare helper that dialogs used to adopt is gone (P4 V6): a dialog's
preview is a window of Browse's helper process (P4 V5).
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from cdmw.services.mesh_rust_preview_package import build_rust_preview_prewarm_package
from cdmw.workers.runnable_signals import application_owned, release


class _DotNetPreviewPrewarmSignals(QObject):
    completed = Signal(object)


class DotNetPreviewPrewarmTask(QRunnable):
    def __init__(self, cache_root: Path, executable: Path | None = None) -> None:
        super().__init__()
        self.cache_root = Path(cache_root)
        self.executable = Path(executable) if executable else None
        # Owned by the application, deleted on the GUI thread (REPORT-crash, item 1).
        self.signals = application_owned(_DotNetPreviewPrewarmSignals)

    def run(self) -> None:
        """Contain all errors because the global pool may outlive the owning host."""

        try:
            self._run()
        finally:
            release(self.signals)

    def _run(self) -> None:
        started_at = time.perf_counter()
        try:
            package = build_rust_preview_prewarm_package(self.cache_root)
            result = {
                "package": package,
                "package_ms": (time.perf_counter() - started_at) * 1000.0,
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001 - prewarm is best-effort
            result = {
                "package": None,
                "package_ms": (time.perf_counter() - started_at) * 1000.0,
                "error": str(exc),
            }
        try:
            self.signals.completed.emit(result)
        except RuntimeError:
            return


__all__ = ["DotNetPreviewPrewarmTask"]
