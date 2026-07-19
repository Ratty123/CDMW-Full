"""Background workers for the Text Search feature."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.services.text_search_service import (
    TextSearchResult,
    export_text_search_results,
    load_text_search_preview,
    normalize_text_search_extensions,
    search_archive_text_entries,
    search_loose_text_files,
)
from cdmw.models import ArchiveEntry, RunCancelled


class TextSearchWorker(QObject):
    log_message = Signal(int, str)
    progress_changed = Signal(int, int, int, str)
    completed = Signal(int, object)
    cancelled = Signal(int, str)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        *,
        request_id: int,
        source_kind: str,
        query: str,
        extension_text: str,
        path_filter: str,
        case_sensitive: bool,
        regex_enabled: bool,
        archive_entries: Sequence[ArchiveEntry],
        loose_root: Optional[Path],
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.source_kind = source_kind
        self.query = query
        self.extension_text = extension_text
        self.path_filter = path_filter
        self.case_sensitive = case_sensitive
        self.regex_enabled = regex_enabled
        self.archive_entries_source = archive_entries
        self.loose_root = loose_root
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            emitted_logs = 0

            def emit_log(message: str) -> None:
                nonlocal emitted_logs
                if emitted_logs < 250:
                    self.log_message.emit(self.request_id, message)
                elif emitted_logs == 250:
                    self.log_message.emit(
                        self.request_id,
                        "Additional text-search log messages were suppressed.",
                    )
                emitted_logs += 1

            extension_filters = normalize_text_search_extensions(self.extension_text)
            if self.source_kind == "archive":
                archive_entries = tuple(self.archive_entries_source)
                results, stats = search_archive_text_entries(
                    archive_entries,
                    self.query,
                    extension_filters=extension_filters,
                    path_filter=self.path_filter,
                    regex=self.regex_enabled,
                    case_sensitive=self.case_sensitive,
                    on_progress=lambda current, total, detail: self.progress_changed.emit(
                        self.request_id, current, total, detail
                    ),
                    on_log=emit_log,
                    stop_event=self.stop_event,
                )
            else:
                if self.loose_root is None:
                    raise ValueError("Select a loose root folder before searching loose files.")
                results, stats = search_loose_text_files(
                    self.loose_root,
                    self.query,
                    extension_filters=extension_filters,
                    path_filter=self.path_filter,
                    regex=self.regex_enabled,
                    case_sensitive=self.case_sensitive,
                    on_progress=lambda current, total, detail: self.progress_changed.emit(
                        self.request_id, current, total, detail
                    ),
                    on_log=emit_log,
                    stop_event=self.stop_event,
                )
            self.completed.emit(
                self.request_id,
                {
                    "results": results,
                    "stats": stats,
                    "source_kind": self.source_kind,
                }
            )
        except RunCancelled as exc:
            self.cancelled.emit(self.request_id, str(exc))
        except Exception as exc:
            self.error.emit(self.request_id, str(exc))
        finally:
            self.finished.emit()


class TextSearchPreviewWorker(QObject):
    completed = Signal(int, object)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        *,
        request_id: int,
        result: TextSearchResult,
        query: str,
        regex_enabled: bool,
        case_sensitive: bool,
        prepared_archive_path: Path | None = None,
        prepared_archive_note: str = "",
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.result = result
        self.query = query
        self.regex_enabled = regex_enabled
        self.case_sensitive = case_sensitive
        self.prepared_archive_path = prepared_archive_path
        self.prepared_archive_note = prepared_archive_note
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            if self.stop_event.is_set():
                return
            preview = load_text_search_preview(
                self.result,
                self.query,
                regex=self.regex_enabled,
                case_sensitive=self.case_sensitive,
                prepared_archive_path=self.prepared_archive_path,
                prepared_archive_note=self.prepared_archive_note,
                stop_event=self.stop_event,
            )
            if self.stop_event.is_set():
                return
            self.completed.emit(self.request_id, preview)
        except Exception as exc:
            if not self.stop_event.is_set():
                self.error.emit(self.request_id, str(exc))
        finally:
            self.finished.emit()


class TextSearchExportWorker(QObject):
    log_message = Signal(int, str)
    progress_changed = Signal(int, int, int, str)
    completed = Signal(int, object, str)
    cancelled = Signal(int, str)
    error = Signal(int, str)
    finished = Signal()

    def __init__(
        self,
        *,
        request_id: int,
        results: Sequence[TextSearchResult],
        output_root: Path,
        label: str,
    ) -> None:
        super().__init__()
        self.request_id = int(request_id)
        self.results_source = results
        self.output_root = Path(output_root)
        self.label = str(label)
        self.stop_event = threading.Event()
        self._processed = 0
        self._failure_logs = 0

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            results = tuple(self.results_source)
            total = len(results)
            progress_step = max(1, total // 200)

            def handle_log(message: str) -> None:
                self._processed += 1
                is_failure = "] FAIL " in message
                if is_failure:
                    self._failure_logs += 1
                if (
                    self._processed == 1
                    or self._processed == total
                    or self._processed % progress_step == 0
                    or (is_failure and self._failure_logs <= 50)
                ):
                    self.log_message.emit(self.request_id, message)
                    self.progress_changed.emit(
                        self.request_id,
                        self._processed,
                        total,
                        f"Exporting text matches... {self._processed:,} / {total:,}",
                    )

            stats = export_text_search_results(
                results,
                self.output_root,
                on_log=handle_log,
                stop_event=self.stop_event,
            )
            self.completed.emit(self.request_id, stats, self.label)
        except RunCancelled as exc:
            self.cancelled.emit(self.request_id, str(exc))
        except Exception as exc:
            self.error.emit(self.request_id, str(exc))
        finally:
            self.finished.emit()


def shutdown_thread(thread: Optional[object], *, grace_ms: int = 2000, force_ms: int = 2000) -> None:
    del grace_ms, force_ms
    if thread is None:
        return
    try:
        thread.requestInterruption()
    except Exception:
        pass
    thread.quit()


__all__ = [
    "TextSearchExportWorker",
    "TextSearchPreviewWorker",
    "TextSearchWorker",
    "shutdown_thread",
]
