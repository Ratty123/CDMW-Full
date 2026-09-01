"""Best-effort background prewarm task for the resident Rust preview host."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from cdmw.services.mesh_rust_preview_package import build_rust_preview_prewarm_package


class _DotNetPreviewPrewarmSignals(QObject):
    completed = Signal(object)


class DotNetPreviewPrewarmTask(QRunnable):
    def __init__(self, cache_root: Path, executable: Path | None = None) -> None:
        super().__init__()
        self.cache_root = Path(cache_root)
        self.executable = Path(executable) if executable else None
        self.signals = _DotNetPreviewPrewarmSignals()

    def run(self) -> None:
        """Contain all errors because the global pool may outlive the owning host."""

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
