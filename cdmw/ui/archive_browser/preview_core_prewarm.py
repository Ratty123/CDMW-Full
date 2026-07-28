"""Background warm-up for the native preview-core service.

The first preview-core job against a package pays for that package's PAMT index
(about 550 ms of a ~590 ms cold job; later jobs in the same package run well under
100 ms). The index is published to the cache root, so paying it once off-thread
while the user is still browsing keeps it off their first click: measured against
the real archive, a cold first click goes from 593 ms to 151 ms.

The warm-up deliberately passes **no** dependency snapshot. A real preview carries
a complete bounded set from the archive worker, which short-circuits the lookup
before the cross-package scan and therefore only ever warms the one package the
selected entry lives in. Omitting it sends this job down the full ladder, so every
package's index gets published and the first click is warm wherever the user
lands. That costs about 3 s of background work and ends at roughly 100 MB private
bytes with the resident set trimmed to its 17-index bound -- clear of the
service's 512 MB recycle guard, which matters because a recycle would discard the
very warmth this job just paid for.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from cdmw.models import ArchiveEntry
from cdmw.ui.model_preview_native import ARCHIVE_MODEL_RENDERER_D3D11
from cdmw.workers.archive_preview_native import (
    NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS,
    native_preview_core_timeout_seconds,
)


# Only the first screenful is worth scanning: the row the user clicks first is
# almost always one of them, and in tree view the leading rows may be folders
# that carry no entry at all.
ARCHIVE_PREVIEW_CORE_PREWARM_SCAN_ROWS = 64


class _PreviewCorePrewarmSignals(QObject):
    completed = Signal(object)


class _ArchivePreviewCorePrewarmTask(QRunnable):
    """Run one throwaway preview job so the next real one lands on warm caches."""

    def __init__(
        self,
        entry: ArchiveEntry,
        *,
        cache_root: Path,
        package_root: Optional[Path],
        render_settings: object,
        stop_event: threading.Event,
    ) -> None:
        super().__init__()
        self.entry = entry
        self.cache_root = Path(cache_root)
        self.package_root = Path(package_root) if package_root else None
        self.render_settings = render_settings
        self.stop_event = stop_event
        self.signals = _PreviewCorePrewarmSignals()

    def run(self) -> None:  # pragma: no cover - exercised through the window
        # Imported here so a session that never previews does not pay for the
        # rendering package at import time.
        from cdmw.services.preview_rendering_service import run_native_preview_core_preview_job

        result: dict[str, object] = {"status": "skipped", "error": ""}
        output_root: Optional[Path] = None
        try:
            output_root = Path(tempfile.mkdtemp(prefix="cdmw_preview_core_prewarm_"))
            attempt = run_native_preview_core_preview_job(
                self.entry,
                cache_root=self.cache_root,
                render_settings=self.render_settings,
                package_root=self.package_root,
                output_root=output_root,
                timeout_seconds=native_preview_core_timeout_seconds(self.render_settings),
                stop_event=self.stop_event,
            )
            result["status"] = str(getattr(attempt, "status", "") or "")
            result["fallback_reason"] = str(getattr(attempt, "fallback_reason", "") or "")
            result["elapsed_ms"] = round(float(getattr(attempt, "elapsed_ms", 0.0) or 0.0), 1)
        except Exception as exc:  # A warm-up must never surface as a failure.
            result["status"] = "error"
            result["error"] = str(exc)
        finally:
            # The warm-up wants the caches, not the package: a durable entry here
            # would be keyed off render settings the user has not chosen yet.
            if output_root is not None:
                shutil.rmtree(output_root, ignore_errors=True)
        self.signals.completed.emit(result)


class ArchivePreviewCorePrewarmMixin:
    """Own the one-shot preview-core warm-up on the archive browser window."""

    def _archive_preview_core_prewarm_entry(self) -> Optional[ArchiveEntry]:
        """The first model row on screen, whose package the first click will need."""

        tree = getattr(self, "archive_tree", None)
        remote_bridge = getattr(self, "archive_remote_bridge", None)
        if remote_bridge is not None and bool(getattr(remote_bridge, "displays_v2", False)):
            model = tree.model() if tree is not None else None
            resolve = getattr(remote_bridge, "compatibility_entry_for_index", None)
            if model is None or not callable(resolve):
                return None
            rows = min(int(model.rowCount()), ARCHIVE_PREVIEW_CORE_PREWARM_SCAN_ROWS)
            for row in range(rows):
                try:
                    entry = resolve(model.index(row, 0))
                except Exception:
                    return None
                if _is_prewarmable(entry):
                    return entry
            return None
        entries = tuple(getattr(self, "archive_filtered_entries", ()) or ())
        for entry in entries[:ARCHIVE_PREVIEW_CORE_PREWARM_SCAN_ROWS]:
            if _is_prewarmable(entry):
                return entry
        return None

    def _archive_preview_core_prewarm_allowed(self) -> bool:
        if self._shutting_down or self._startup_benchmark_enabled():
            return False
        if bool(getattr(self, "archive_preview_core_prewarm_done", False)):
            return False
        if getattr(self, "archive_preview_core_prewarm_task", None) is not None:
            return False
        # A session that has already previewed has warmed itself, and a warm-up
        # dispatched now would sit in front of the user's next job on the
        # service's single job lock.
        if int(getattr(self, "archive_preview_request_id", 0) or 0) > 0:
            return False
        if getattr(self, "archive_preview_thread", None) is not None:
            return False
        return self._archive_model_renderer_backend() == ARCHIVE_MODEL_RENDERER_D3D11

    def _start_archive_preview_core_prewarm(self) -> bool:
        if not self._archive_preview_core_prewarm_allowed():
            return False
        entry = self._archive_preview_core_prewarm_entry()
        if entry is None:
            return False
        try:
            cache_root = self._native_preview_core_cache_root()
        except (AttributeError, OSError, ValueError):
            return False
        if cache_root is None:
            return False
        package_root_text = str(self.archive_package_root_edit.text() or "").strip()
        self.archive_preview_core_prewarm_done = True
        stop_event = threading.Event()
        self.archive_preview_core_prewarm_stop_event = stop_event
        task = _ArchivePreviewCorePrewarmTask(
            entry,
            cache_root=Path(cache_root),
            package_root=Path(package_root_text).expanduser() if package_root_text else None,
            render_settings=self._current_model_preview_render_settings(),
            stop_event=stop_event,
        )
        task.signals.completed.connect(self._finish_archive_preview_core_prewarm)
        self.archive_preview_core_prewarm_task = task
        self._record_runtime_event(
            "archive_preview_core_prewarm_started",
            path=str(getattr(entry, "path", "") or ""),
        )
        QThreadPool.globalInstance().start(task)
        return True

    def _cancel_archive_preview_core_prewarm(self) -> None:
        """Release the warm-up's hold on the preview-core service.

        The service serialises jobs behind one lock, so a warm-up still running at
        close would block the service shutdown for the rest of its job.
        """

        self.archive_preview_core_prewarm_done = True
        stop_event = getattr(self, "archive_preview_core_prewarm_stop_event", None)
        if stop_event is not None:
            stop_event.set()

    def _finish_archive_preview_core_prewarm(self, result: object) -> None:
        self.archive_preview_core_prewarm_task = None
        self.archive_preview_core_prewarm_stop_event = None
        if self._shutting_down or not isinstance(result, dict):
            return
        self.append_archive_log(
            "Archive Browser activation timing | cause=preview_core_prewarm"
            f" | status={result.get('status', '')} | elapsed={result.get('elapsed_ms', 0)}ms",
            verbose=True,
        )
        self._record_runtime_event(
            "archive_preview_core_prewarm_finished",
            status=str(result.get("status", "")),
            elapsed_ms=result.get("elapsed_ms", 0),
            error=str(result.get("error", "")),
        )


def _is_prewarmable(entry: object) -> bool:
    if entry is None:
        return False
    extension = str(getattr(entry, "extension", "") or "").strip().lower()
    return extension in NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS


__all__ = [
    "ARCHIVE_PREVIEW_CORE_PREWARM_SCAN_ROWS",
    "ArchivePreviewCorePrewarmMixin",
]
