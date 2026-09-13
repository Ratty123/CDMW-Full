"""One render job at a time, with selected-preview priority and retained teardown."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from cdmw.domain.archives.character_catalogue import CharacterCatalogDetailRequest, CharacterCatalogDetailResult
from cdmw.domain.character_finder import CharacterRenderResult, character_preview_detail
from cdmw.ui.character_finder.preview_preparation import CharacterPreviewPreparation
from cdmw.workers.character_finder_workers import CharacterFinderRenderWorker, character_render_key, cached_character_render


class _CacheLookup(QObject):
    completed = Signal(int, object)
    finished = Signal()

    def __init__(self, token, root, key):
        super().__init__()
        self.token, self.root, self.key = token, root, key

    def stop(self):
        pass  # Bounded read of one small cache record; the owner rejects late results.

    @Slot()
    def run(self):
        try:
            self.completed.emit(self.token, cached_character_render(self.root, self.key))
        finally:
            self.finished.emit()


class CharacterFinderPreviewController(QObject):
    package_ready = Signal(str, object)
    thumbnail_ready = Signal(str, object)
    failed = Signal(str, str)
    idle = Signal()

    def __init__(self, service, *, fingerprint: str, cache_root: Path, settings, parent=None):
        super().__init__(parent)
        self._service = service
        self._fingerprint = fingerprint
        self._cache_root = cache_root
        self._settings = replace(settings, use_textures_by_default=True, ambient_strength=0.45,
            diffuse_light_scale=0.9, d3d11_light_azimuth_degrees=-35.0, d3d11_light_elevation_degrees=30.0)
        self._preparation = CharacterPreviewPreparation(service, self)
        self._preparation.ready.connect(self._prepared)
        self._preparation.failed.connect(self._preparation_failed)
        service.result_ready.connect(self._detail_ready)
        service.request_failed.connect(self._detail_failed)
        service.request_cancelled.connect(self._detail_cancelled)
        self._generation = 0
        self._token = 0
        self._session_id = ""
        self._selected = None
        self._selected_pending = False
        self._visible = {}
        self._done = set()
        self._request = None
        self._active_key = ""
        self._active_detail = None
        self._thread = None
        self._worker = None
        self._next = None
        self._closed = False
        self._kick_timer = QTimer(self)
        self._kick_timer.setSingleShot(True)
        self._kick_timer.timeout.connect(self._kick)

    @property
    def busy(self):
        return bool(self._active_key or self._thread)

    def clear_page(self):
        self._visible.clear()
        self._selected = None
        self._selected_pending = False
        self._cancel()

    def select(self, detail, generation):
        self._selected = detail
        self._selected_pending = True
        self._generation = generation
        self._session_id = detail.session_id
        self._cancel()
        self._kick_timer.start(0)

    def visible(self, rows, *, session_id, generation):
        self._visible = {row.key: row for row in rows if row.model_count and row.resolution != "ambiguous"}
        self._session_id, self._generation = session_id, generation
        if self._active_key and self._active_key not in self._visible and (
            self._selected is None or self._selected.row.key != self._active_key):
            self._cancel()
        self._kick_timer.start(0)

    def _cancel(self):
        self._token += 1
        self._next = None
        self._active_key = ""
        self._active_detail = None
        self._preparation.cancel()
        request, self._request = self._request, None
        if request:
            self._service.cancel(request)
        if self._worker is not None:
            self._worker.stop()

    def shutdown(self):
        self._closed = True
        self._kick_timer.stop()
        self._cancel()
        if self._thread is None:
            self.idle.emit()

    def _kick(self):
        if self._closed or self._thread is not None or self._active_key:
            return
        detail = None
        if self._selected_pending and self._selected is not None:
            detail = self._selected
            self._selected_pending = False
            key = detail.row.key
        else:
            key = next((key for key in self._visible if key not in self._done), "")
        if not key:
            self.idle.emit()
            return
        self._token = max(self._token + 1, self._generation)
        self._active_key = key
        if detail:
            self._check_cache(detail)
        else:
            try:
                self._request = self._service.get_character_catalog_detail(
                    CharacterCatalogDetailRequest(self._session_id, key), ui_generation=self._token)
            except Exception as error:
                self._fail(str(error))

    def _detail_ready(self, request, _operation, detail):
        if self._closed or request != self._request or not isinstance(detail, CharacterCatalogDetailResult):
            return
        self._request = None
        if detail.session_id == self._session_id and detail.row.key == self._active_key:
            self._check_cache(detail)

    def _detail_failed(self, request, error):
        if request == self._request:
            self._request = None
            self._fail(str(getattr(error, "message", error)))

    def _detail_cancelled(self, request):
        if request == self._request:
            self._request = None
            self._fail("Character preview preparation was cancelled.")

    def _check_cache(self, detail):
        detail = character_preview_detail(detail)
        self._active_detail = detail
        worker = _CacheLookup(self._token, self._cache_root, character_render_key(detail, self._fingerprint, self._settings))
        worker.completed.connect(self._cache_ready)
        self._start_thread(worker)

    def _cache_ready(self, token, result):
        if self._closed or token != self._token:
            return
        if isinstance(result, CharacterRenderResult):
            self._deliver_package(token, result)
            self._render_ready(token, result)
        else:
            self._next = "prepare"

    def _start_thread(self, worker):
        thread = QThread(self)
        self._thread, self._worker = thread, worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        thread.start()

    @Slot()
    def _thread_finished(self):
        thread = self.sender()
        if thread is not self._thread:
            return
        self._retire_thread(thread)

    def _retire_thread(self, thread):
        if not thread.wait(0):
            QTimer.singleShot(1, lambda: self._retire_thread(thread))
            return
        self._thread, self._worker = None, None
        thread.deleteLater()
        action, self._next = self._next, None
        if self._closed:
            self.idle.emit()
        elif action == "prepare" and self._active_detail is not None:
            self._preparation.start(self._active_detail, self._token)
        else:
            self._kick_timer.start(0)

    def _prepared(self, token, inputs):
        if self._closed or token != self._token or not self._active_key:
            return
        worker = CharacterFinderRenderWorker(token, inputs, cache_root=self._cache_root,
                                            fingerprint=self._fingerprint, settings=self._settings)
        worker.package_ready.connect(self._deliver_package)
        worker.completed.connect(self._render_ready)
        worker.failed.connect(self._preparation_failed)
        self._start_thread(worker)

    def _deliver_package(self, token, result):
        if self._closed or token != self._token:
            return
        if self._selected is not None and self._selected.row.key == self._active_key:
            self.package_ready.emit(self._active_key, result)

    def _render_ready(self, token, result):
        if self._closed or token != self._token:
            return
        key = self._active_key
        self._done.add(key)
        self._active_key = ""
        self._active_detail = None
        self.thumbnail_ready.emit(key, result)
        if self._thread is None:
            self._kick_timer.start(0)

    def _preparation_failed(self, token, message):
        if token == self._token and not self._closed:
            self._fail(message)

    def _fail(self, message):
        key = self._active_key
        self._done.add(key)
        self._active_key = ""
        self._active_detail = None
        self.failed.emit(key, message)
        if self._thread is None:
            self._kick_timer.start(0)
