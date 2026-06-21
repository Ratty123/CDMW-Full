"""Background workers for the Text Search feature."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.core.text_search import (
    TextSearchResult,
    load_text_search_preview,
    normalize_text_search_extensions,
    search_archive_text_entries,
    search_loose_text_files,
)
from cdmw.models import ArchiveEntry, RunCancelled


class TextSearchWorker(QObject):
    log_message = Signal(str)
    progress_changed = Signal(int, int, str)
    completed = Signal(object)
    cancelled = Signal(str)
    error = Signal(str)
    finished = Signal()

    def __init__(
        self,
        *,
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
        self.source_kind = source_kind
        self.query = query
        self.extension_text = extension_text
        self.path_filter = path_filter
        self.case_sensitive = case_sensitive
        self.regex_enabled = regex_enabled
        self.archive_entries = archive_entries if isinstance(archive_entries, list) else list(archive_entries)
        self.loose_root = loose_root
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            extension_filters = normalize_text_search_extensions(self.extension_text)
            if self.source_kind == "archive":
                results, stats = search_archive_text_entries(
                    self.archive_entries,
                    self.query,
                    extension_filters=extension_filters,
                    path_filter=self.path_filter,
                    regex=self.regex_enabled,
                    case_sensitive=self.case_sensitive,
                    on_progress=self.progress_changed.emit,
                    on_log=self.log_message.emit,
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
                    on_progress=self.progress_changed.emit,
                    on_log=self.log_message.emit,
                    stop_event=self.stop_event,
                )
            self.completed.emit(
                {
                    "results": results,
                    "stats": stats,
                    "source_kind": self.source_kind,
                }
            )
        except RunCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            self.error.emit(str(exc))
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
    ) -> None:
        super().__init__()
        self.request_id = request_id
        self.result = result
        self.query = query
        self.regex_enabled = regex_enabled
        self.case_sensitive = case_sensitive
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
    "TextSearchPreviewWorker",
    "TextSearchWorker",
    "shutdown_thread",
]
