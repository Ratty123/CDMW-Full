"""Shared session-only Character Context discovery, selection, and package owner."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal

from cdmw.domain.archives.catalogue import ArchivePage, ArchiveQuery, ArchiveQueryHandle, ArchiveViewMode
from cdmw.domain.archives.catalogue_operations import FetchPageRequest
from cdmw.domain.character_context import (
    CharacterContextDiscoveryRequest,
    CharacterContextDiscoveryResult,
    CharacterContextSelection,
    character_context_entry_key,
    default_character_context_selection,
    selected_character_context_components,
)
from cdmw.models import ArchiveEntry
from cdmw.workers.character_context_workers import (
    CharacterContextDiscoveryWorker,
    CharacterContextPackageRequest,
    CharacterContextPackageWorker,
)


_CATALOGUE_EXTENSIONS = (
    ".app_xml",
    ".pac",
    ".pam",
    ".pamlod",
    ".prefab",
    ".pappt",
    ".prefabdata_xml",
    ".pac_xml",
    ".pam_xml",
    ".pamlod_xml",
    ".pami",
    ".pab",
    ".pabc",
    ".pabv",
    ".pabgb",
    ".pabgh",
    ".pamt",
    ".hkx",
    ".hkt",
    ".dds",
)


class CharacterContextService(QObject):
    discovery_started = Signal(str, object)
    discovery_progress = Signal(str, int, int, str)
    discovery_ready = Signal(str, object)
    discovery_failed = Signal(str, str)
    selection_changed = Signal(str, object, object)
    package_started = Signal(str)
    package_ready = Signal(str, str, float)
    package_failed = Signal(str, str)

    def __init__(
        self,
        *,
        archive_catalogue_service: object | None = None,
        entries_provider: Callable[[], Sequence[ArchiveEntry]] | None = None,
        path_index_provider: Callable[[], Mapping[str, Sequence[ArchiveEntry]]] | None = None,
        basename_index_provider: Callable[[], Mapping[str, Sequence[ArchiveEntry]]] | None = None,
        archive_fingerprint_provider: Callable[[], str] | None = None,
        native_cache_root_provider: Callable[[], Path] | None = None,
        package_root_provider: Callable[[], Path | None] | None = None,
        render_settings_provider: Callable[[], object] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._catalogue = archive_catalogue_service
        self._entries_provider = entries_provider
        self._path_index_provider = path_index_provider
        self._basename_index_provider = basename_index_provider
        self._archive_fingerprint_provider = archive_fingerprint_provider
        self._native_cache_root_provider = native_cache_root_provider
        self._package_root_provider = package_root_provider
        self._render_settings_provider = render_settings_provider
        self._cache: dict[str, CharacterContextDiscoveryResult] = {}
        self._complete_source_keys: set[str] = set()
        self._selections: dict[str, CharacterContextSelection] = {}
        self._request_id = 0
        self._package_request_id = 0
        self._active_source_key = ""
        self._discovery_thread: QThread | None = None
        self._discovery_worker: CharacterContextDiscoveryWorker | None = None
        self._package_thread: QThread | None = None
        self._package_worker: CharacterContextPackageWorker | None = None
        self._discovery_operations: dict[QThread, CharacterContextDiscoveryWorker] = {}
        self._package_operations: dict[QThread, CharacterContextPackageWorker] = {}
        self._catalogue_request_ids: set[str] = set()
        self._catalogue_entries: list[ArchiveEntry] = []
        self._catalogue_source: ArchiveEntry | None = None
        self._catalogue_source_key = ""
        self._catalogue_query_id = ""
        self._catalogue_total = 0
        self._closed = False
        if archive_catalogue_service is not None:
            archive_catalogue_service.result_ready.connect(self._handle_catalogue_result)
            archive_catalogue_service.request_failed.connect(self._handle_catalogue_failure)
            archive_catalogue_service.request_cancelled.connect(self._handle_catalogue_cancelled)

    def archive_fingerprint(self) -> str:
        catalogue_session = getattr(self._catalogue, "current_session", None)
        remote_fingerprint = str(getattr(catalogue_session, "fingerprint", "") or "").strip()
        if remote_fingerprint:
            return remote_fingerprint
        if callable(self._archive_fingerprint_provider):
            try:
                return str(self._archive_fingerprint_provider() or "").strip()
            except Exception:
                return ""
        return ""

    def source_key(self, source_entry: ArchiveEntry) -> str:
        return f"{self.archive_fingerprint()}|{character_context_entry_key(source_entry)}"

    def cached_result(self, source_entry: ArchiveEntry) -> CharacterContextDiscoveryResult | None:
        return self._cache.get(self.source_key(source_entry))

    def selection(self, source_entry: ArchiveEntry) -> CharacterContextSelection:
        key = self.source_key(source_entry)
        result = self._cache.get(key)
        if result is None:
            return CharacterContextSelection()
        return self._selections.get(key, default_character_context_selection(result))

    def selected_native_components(self, source_entry: ArchiveEntry) -> tuple[object, ...]:
        key = self.source_key(source_entry)
        result = self._cache.get(key)
        if result is None:
            return ()
        selection = self._selections.get(key, default_character_context_selection(result))
        return selected_character_context_components(result, selection)

    def request_discovery(self, source_entry: ArchiveEntry) -> bool:
        if self._closed or not isinstance(source_entry, ArchiveEntry):
            return False
        source_key = self.source_key(source_entry)
        cached = self._cache.get(source_key)
        if cached is not None:
            QTimer.singleShot(0, lambda: self.discovery_ready.emit(source_key, cached))
            if source_key in self._complete_source_keys:
                return True
        self._cancel_discovery()
        self._request_id += 1
        self._active_source_key = source_key
        self.discovery_started.emit(source_key, source_entry)
        entries = tuple(self._entries_provider() or ()) if callable(self._entries_provider) else ()
        remote_session = getattr(self._catalogue, "current_session", None)
        remote_count = int(getattr(remote_session, "entry_count", 0) or 0)
        if remote_session is not None and (not entries or len(entries) < max(1, remote_count // 2)):
            return self._start_catalogue_discovery(source_entry, source_key)
        return self._start_discovery_worker(source_entry, source_key, entries)

    def cancel_pending_discovery(self, source_entry: ArchiveEntry) -> None:
        if self.source_key(source_entry) == self._active_source_key:
            self._cancel_discovery()

    def _start_catalogue_discovery(self, source_entry: ArchiveEntry, source_key: str) -> bool:
        session = getattr(self._catalogue, "current_session", None)
        create_query = getattr(self._catalogue, "create_query", None)
        if session is None or not callable(create_query):
            self.discovery_failed.emit(source_key, "Archive catalogue is unavailable for Character Context discovery.")
            return False
        self._catalogue_source = source_entry
        self._catalogue_source_key = source_key
        self._catalogue_entries = []
        self._catalogue_query_id = ""
        self._catalogue_total = 0
        generation = max(1, int(time.monotonic() * 1000.0))
        try:
            request_id = create_query(
                ArchiveQuery(
                    session_id=session.session_id,
                    extensions=_CATALOGUE_EXTENSIONS,
                    view_mode=ArchiveViewMode.FLAT,
                ),
                ui_generation=generation,
            )
        except Exception as exc:
            self.discovery_failed.emit(source_key, str(exc))
            return False
        self._catalogue_request_ids.add(str(request_id))
        self.discovery_progress.emit(source_key, 0, 1, "Loading appearance and model catalogue pages...")
        return True

    def _fetch_catalogue_page(self, page_start: int) -> None:
        fetch = getattr(self._catalogue, "fetch_page", None)
        if not callable(fetch) or not self._catalogue_query_id:
            self.discovery_failed.emit(self._catalogue_source_key, "Archive catalogue paging is unavailable.")
            return
        generation = max(1, int(time.monotonic() * 1000.0))
        request_id = fetch(
            FetchPageRequest(self._catalogue_query_id, page_start=page_start, page_size=512),
            ui_generation=generation,
        )
        self._catalogue_request_ids.add(str(request_id))

    def _handle_catalogue_result(self, request_id: str, _operation: str, payload: object) -> None:
        if request_id not in self._catalogue_request_ids or self._closed:
            return
        self._catalogue_request_ids.discard(request_id)
        if isinstance(payload, ArchiveQueryHandle):
            self._catalogue_query_id = payload.query_id
            self._catalogue_total = int(payload.total_matches)
            if self._catalogue_total <= 0:
                self._start_discovery_worker(self._catalogue_source, self._catalogue_source_key, ())
            else:
                self._fetch_catalogue_page(0)
            return
        if not isinstance(payload, ArchivePage):
            return
        compatibility_entry = getattr(self._catalogue, "compatibility_entry", None)
        if not callable(compatibility_entry):
            self.discovery_failed.emit(self._catalogue_source_key, "Archive catalogue rows cannot be prepared.")
            return
        self._catalogue_entries.extend(compatibility_entry(row) for row in payload.rows)
        loaded = int(payload.page_start) + len(payload.rows)
        self.discovery_progress.emit(
            self._catalogue_source_key,
            min(loaded, self._catalogue_total),
            max(1, self._catalogue_total),
            f"Loading Character Context catalogue: {min(loaded, self._catalogue_total):,}/{self._catalogue_total:,}",
        )
        if loaded < self._catalogue_total:
            self._fetch_catalogue_page(loaded)
            return
        source = self._catalogue_source
        source_key = self._catalogue_source_key
        entries = tuple(self._catalogue_entries)
        self._catalogue_entries = []
        if isinstance(source, ArchiveEntry):
            self._start_discovery_worker(source, source_key, entries)

    def _handle_catalogue_failure(self, request_id: str, error: object) -> None:
        if request_id not in self._catalogue_request_ids:
            return
        self._catalogue_request_ids.discard(request_id)
        self.discovery_failed.emit(self._catalogue_source_key, str(getattr(error, "message", error)))

    def _handle_catalogue_cancelled(self, request_id: str) -> None:
        self._catalogue_request_ids.discard(request_id)

    def _start_discovery_worker(
        self,
        source_entry: ArchiveEntry | None,
        source_key: str,
        entries: Sequence[ArchiveEntry],
    ) -> bool:
        if not isinstance(source_entry, ArchiveEntry) or source_key != self._active_source_key:
            return False
        path_index = self._path_index_provider() if callable(self._path_index_provider) else {}
        basename_index = self._basename_index_provider() if callable(self._basename_index_provider) else {}
        request = CharacterContextDiscoveryRequest(
            source_entry=source_entry,
            archive_entries=tuple(entries),
            path_index=path_index or {},
            basename_index=basename_index or {},
            archive_fingerprint=self.archive_fingerprint(),
            request_id=self._request_id,
        )
        worker = CharacterContextDiscoveryWorker(request)
        thread = QThread(self)
        thread.setObjectName("CharacterContextDiscoveryThread")
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(
            lambda current, total, detail, key=source_key: self.discovery_progress.emit(
                key, current, total, detail
            )
        )
        worker.authored_ready.connect(self._handle_discovery_authored_ready)
        worker.completed.connect(self._handle_discovery_ready)
        worker.error.connect(self._handle_discovery_error)
        worker.finished.connect(
            lambda target_worker=worker: self._finish_worker_thread(target_worker),
            Qt.DirectConnection,
        )
        thread.finished.connect(
            lambda target_thread=thread, target_worker=worker: self._cleanup_discovery_worker(
                target_thread, target_worker
            )
        )
        self._discovery_thread = thread
        self._discovery_worker = worker
        self._discovery_operations[thread] = worker
        thread.start(QThread.LowPriority)
        return True

    def _handle_discovery_authored_ready(self, result: object) -> None:
        self._publish_discovery_result(result, complete=False)

    def _handle_discovery_ready(self, result: object) -> None:
        self._publish_discovery_result(result, complete=True)

    def _publish_discovery_result(self, result: object, *, complete: bool) -> None:
        if not isinstance(result, CharacterContextDiscoveryResult):
            return
        if result.request_id != self._request_id or result.source_key != self._active_source_key:
            return
        previous = self._cache.get(result.source_key)
        self._cache[result.source_key] = result
        if complete:
            self._complete_source_keys.add(result.source_key)
        else:
            self._complete_source_keys.discard(result.source_key)
        selection = self._selections.setdefault(
            result.source_key,
            default_character_context_selection(result),
        )
        self.discovery_ready.emit(result.source_key, result)
        components = selected_character_context_components(result, selection)
        previous_components = (
            selected_character_context_components(previous, selection)
            if isinstance(previous, CharacterContextDiscoveryResult)
            else None
        )
        if previous_components != components:
            self.selection_changed.emit(result.source_key, selection, components)

    def _handle_discovery_error(self, request_id: int, message: str) -> None:
        if int(request_id) == self._request_id:
            self.discovery_failed.emit(self._active_source_key, str(message))

    def set_selection(
        self,
        source_entry: ArchiveEntry,
        selection: CharacterContextSelection,
    ) -> bool:
        key = self.source_key(source_entry)
        result = self._cache.get(key)
        if result is None:
            return False
        valid_appearances = {appearance.appearance_id for appearance in result.appearances}
        if selection.appearance_id and selection.appearance_id not in valid_appearances:
            return False
        normalized = CharacterContextSelection(
            appearance_id=selection.appearance_id or (result.appearances[0].appearance_id if result.appearances else ""),
            face_option_ids=tuple(dict.fromkeys(selection.face_option_ids)),
            hair_option_id=str(selection.hair_option_id or ""),
            body_option_id=str(selection.body_option_id or ""),
            gear_option_ids=tuple(dict.fromkeys(selection.gear_option_ids)),
        )
        if self._selections.get(key) == normalized:
            return False
        self._selections[key] = normalized
        self.selection_changed.emit(
            key,
            normalized,
            selected_character_context_components(result, normalized),
        )
        return True

    def select_appearance(self, source_entry: ArchiveEntry, appearance_id: str) -> bool:
        result = self.cached_result(source_entry)
        if result is None:
            return False
        return self.set_selection(
            source_entry,
            default_character_context_selection(result, appearance_id=appearance_id),
        )

    def reset_selection(self, source_entry: ArchiveEntry) -> bool:
        result = self.cached_result(source_entry)
        return bool(result is not None and self.set_selection(source_entry, default_character_context_selection(result)))

    def clear_selection(self, source_entry: ArchiveEntry) -> bool:
        current = self.selection(source_entry)
        return self.set_selection(
            source_entry,
            CharacterContextSelection(appearance_id=current.appearance_id),
        )

    def use_authored_hair_and_body(self, source_entry: ArchiveEntry) -> bool:
        result = self.cached_result(source_entry)
        if result is None:
            return False
        current = self.selection(source_entry)
        appearance = next(
            (item for item in result.appearances if item.appearance_id == current.appearance_id),
            result.appearances[0] if result.appearances else None,
        )
        if appearance is None:
            return False
        hair = next((option.option_id for option in appearance.options if option.slot == "hair"), "")
        body = next((option.option_id for option in appearance.options if option.slot == "body"), "")
        return self.set_selection(
            source_entry,
            replace(current, hair_option_id=hair, body_option_id=body),
        )

    def request_native_package(self, source_entry: ArchiveEntry) -> bool:
        key = self.source_key(source_entry)
        result = self._cache.get(key)
        if result is None:
            return False
        self._cancel_package()
        components = selected_character_context_components(result, self.selection(source_entry))
        self._package_request_id += 1
        if not components:
            QTimer.singleShot(0, lambda: self.package_ready.emit(key, "", 0.0))
            return True
        if not callable(self._native_cache_root_provider):
            self.package_failed.emit(key, "Character Context native cache is unavailable.")
            return False
        try:
            cache_root = Path(self._native_cache_root_provider())
            package_root = self._package_root_provider() if callable(self._package_root_provider) else None
            render_settings = self._render_settings_provider() if callable(self._render_settings_provider) else None
        except Exception as exc:
            self.package_failed.emit(key, str(exc))
            return False
        request = CharacterContextPackageRequest(
            request_id=self._package_request_id,
            source_entry=source_entry,
            components=components,
            source_dependency_entries=result.source_dependency_entries,
            source_dependencies_complete=result.source_dependencies_complete,
            archive_fingerprint=result.archive_fingerprint,
            cache_root=cache_root,
            package_root=Path(package_root) if package_root else None,
            render_settings=render_settings,
        )
        worker = CharacterContextPackageWorker(request)
        thread = QThread(self)
        thread.setObjectName("CharacterContextPackageThread")
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(
            lambda request_id, package_path, elapsed_ms, source_key=key: self._handle_package_ready(
                source_key, request_id, package_path, elapsed_ms
            )
        )
        worker.error.connect(
            lambda request_id, message, source_key=key: self._handle_package_error(
                source_key, request_id, message
            )
        )
        worker.finished.connect(
            lambda target_worker=worker: self._finish_worker_thread(target_worker),
            Qt.DirectConnection,
        )
        thread.finished.connect(
            lambda target_thread=thread, target_worker=worker: self._cleanup_package_worker(
                target_thread, target_worker
            )
        )
        self._package_thread = thread
        self._package_worker = worker
        self._package_operations[thread] = worker
        self.package_started.emit(key)
        thread.start(QThread.LowPriority)
        return True

    def _handle_package_ready(self, source_key: str, request_id: int, package_path: str, elapsed_ms: float) -> None:
        if int(request_id) == self._package_request_id and source_key == self._active_or_cached_key(source_key):
            self.package_ready.emit(source_key, package_path, float(elapsed_ms))

    def _handle_package_error(self, source_key: str, request_id: int, message: str) -> None:
        if int(request_id) == self._package_request_id:
            self.package_failed.emit(source_key, str(message))

    def _active_or_cached_key(self, source_key: str) -> str:
        return source_key if source_key in self._cache else ""

    def _finish_worker_thread(self, worker: QObject) -> None:
        current = QThread.currentThread()
        if worker.thread() is current:
            worker.moveToThread(self.thread())
        current.quit()

    def _cleanup_discovery_worker(self, thread: QThread, worker: CharacterContextDiscoveryWorker) -> None:
        if not thread.wait(0):
            QTimer.singleShot(0, lambda: self._cleanup_discovery_worker(thread, worker))
            return
        if self._discovery_thread is thread:
            self._discovery_thread = None
        if self._discovery_worker is worker:
            self._discovery_worker = None
        self._discovery_operations.pop(thread, None)
        worker.deleteLater()
        thread.deleteLater()

    def _cleanup_package_worker(self, thread: QThread, worker: CharacterContextPackageWorker) -> None:
        if not thread.wait(0):
            QTimer.singleShot(0, lambda: self._cleanup_package_worker(thread, worker))
            return
        if self._package_thread is thread:
            self._package_thread = None
        if self._package_worker is worker:
            self._package_worker = None
        self._package_operations.pop(thread, None)
        worker.deleteLater()
        thread.deleteLater()

    def _cancel_discovery(self) -> None:
        self._request_id += 1
        for worker in tuple(self._discovery_operations.values()):
            worker.stop()
        cancel = getattr(self._catalogue, "cancel", None)
        if callable(cancel):
            for request_id in tuple(self._catalogue_request_ids):
                try:
                    cancel(request_id)
                except Exception:
                    pass
        self._catalogue_request_ids.clear()

    def _cancel_package(self) -> None:
        self._package_request_id += 1
        for worker in tuple(self._package_operations.values()):
            worker.stop()

    def request_shutdown(self) -> None:
        self._closed = True
        self._cancel_discovery()
        self._cancel_package()

    def iter_shutdown_workers(self) -> tuple[tuple[str, QThread | None, QObject | None], ...]:
        workers: list[tuple[str, QThread | None, QObject | None]] = []
        workers.extend(
            ("character_context_discovery", thread, worker)
            for thread, worker in tuple(self._discovery_operations.items())
        )
        workers.extend(
            ("character_context_package", thread, worker)
            for thread, worker in tuple(self._package_operations.items())
        )
        return tuple(workers)


__all__ = ["CharacterContextService"]
