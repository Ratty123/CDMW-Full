"""Bounded parallel thumbnails, selected-preview priority and retained teardown."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import os
import threading
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from cdmw.domain.archives.character_catalogue import CharacterCatalogDetailRequest, CharacterCatalogDetailResult
from cdmw.domain.character_finder import CharacterRenderResult, character_preview_detail
from cdmw.ui.character_finder.preview_preparation import CharacterPreviewPreparation
from cdmw.workers.character_finder_workers import (
    CharacterFinderRenderWorker, character_render_key, cached_character_render,
    character_row_cache_root, cached_character_row, remember_character_thumbnail,
)


class _CacheLookup(QObject):
    completed = Signal(int, object)
    finished = Signal()

    def __init__(self, token, root, key, row_root, row_key):
        super().__init__()
        self.token, self.root, self.key = token, root, key
        self.row_root, self.row_key = row_root, row_key

    def stop(self):
        pass  # Bounded read of one small cache record; the owner rejects late results.

    @Slot()
    def run(self):
        try:
            result = cached_character_render(self.root, self.key)
            if result is not None:
                remember_character_thumbnail(self.row_root, self.row_key, result)
            self.completed.emit(self.token, result)
        finally:
            self.finished.emit()


class _PageCacheLookup(QObject):
    completed = Signal(int, object)
    finished = Signal()

    def __init__(self, token, root, row_root, keys):
        super().__init__()
        self.token, self.root, self.row_root, self.keys = token, root, row_root, tuple(keys)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    @Slot()
    def run(self):
        try:
            results = []
            for key in self.keys:
                if self._stop.is_set():
                    return
                result = cached_character_row(self.root, self.row_root, key)
                if result is not None:
                    results.append((key, result))
            self.completed.emit(self.token, results)
        finally:
            self.finished.emit()


class _CharacterPreviewLane(QObject):
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
        worker = _CacheLookup(self._token, self._cache_root, character_render_key(detail, self._fingerprint, self._settings),
            character_row_cache_root(self._cache_root, self._fingerprint, self._settings), detail.row.key)
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


class CharacterFinderPreviewController(QObject):
    package_ready = Signal(str, object)
    thumbnail_ready = Signal(str, object)
    failed = Signal(str, str)
    idle = Signal()

    def __init__(self, service, *, fingerprint, cache_root, settings, parent=None):
        super().__init__(parent)
        self._rows = {}
        self._done = set()
        self._assigned = {}
        self._selected_key = ""
        self._session_id = ""
        self._generation = 0
        self._closed = False
        self._cache_root = cache_root
        self._cache_thread = self._cache_worker = None
        self._cache_token = 0
        self._cache_page = None
        lane_count = min(8, max(2, (os.cpu_count() or 4) // 2))
        self._lanes = [_CharacterPreviewLane(service, fingerprint=fingerprint,
            cache_root=cache_root, settings=settings, parent=self) for _ in range(lane_count)]
        self._settings = self._lanes[0]._settings
        self._row_root = character_row_cache_root(cache_root, fingerprint, self._settings)
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setSingleShot(True)
        self._schedule_timer.timeout.connect(self._schedule)
        for lane in self._lanes:
            lane._done = self._done
            lane.package_ready.connect(self._package_ready)
            lane.thumbnail_ready.connect(self._thumbnail_ready)
            lane.failed.connect(self._failed)
            lane.idle.connect(self._lane_idle)

    @property
    def busy(self):
        return self._cache_thread is not None or any(lane.busy for lane in self._lanes)

    @property
    def _active_key(self):
        return next((lane._active_key for lane in self._lanes if lane._active_key), "")

    def iter_shutdown_workers(self):
        if self._cache_thread is not None:
            yield "character_finder_cache", self._cache_thread, self._cache_worker
        for index, lane in enumerate(self._lanes):
            if lane._thread is not None:
                yield f"character_finder_{index}", lane._thread, lane._worker

    def clear_page(self):
        self._schedule_timer.stop()
        self._rows.clear()
        self._assigned.clear()
        self._selected_key = ""
        self._cache_page = None
        self._cache_token += 1
        if self._cache_worker is not None:
            self._cache_worker.stop()
        for lane in self._lanes:
            lane.clear_page()

    def select(self, detail, generation):
        self._selected_key = detail.row.key
        self._session_id, self._generation = detail.session_id, generation
        # Reserve the first lane for the user's selection immediately; retain
        # obsolete workers until their real teardown before starting replacements.
        for lane in self._lanes:
            if lane is self._lanes[0] or self._assigned.get(lane) == detail.row.key:
                self._assigned.pop(lane, None)
                lane.clear_page()
        self._assigned[self._lanes[0]] = detail.row.key
        self._lanes[0].select(detail, generation)
        self._schedule_timer.start(0)

    def visible(self, rows, *, session_id, generation):
        # The caller orders on-screen cards first, followed by the remainder of
        # its bounded page. Scrolling reprioritizes queued work without restarting
        # jobs that still belong to this page.
        self._rows = {row.key: row for row in rows if row.model_count and row.resolution != "ambiguous"}
        self._session_id, self._generation = session_id, generation
        for lane, key in tuple(self._assigned.items()):
            if key not in self._rows and key != self._selected_key:
                self._assigned.pop(lane, None)
                lane.clear_page()
        self._schedule_timer.start(0)

    def _start_page_cache(self):
        self._cache_page = (self._session_id, self._generation, frozenset(self._rows))
        # A revisited page needs its images delivered again. The optional row
        # index may be absent or evicted even when this owner rendered it before.
        self._done.difference_update(self._rows)
        self._cache_token += 1
        worker = _PageCacheLookup(self._cache_token, self._cache_root, self._row_root, self._rows)
        thread = QThread(self)
        self._cache_thread, self._cache_worker = thread, worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._page_cache_ready)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._page_cache_finished)
        thread.start()

    @Slot(int, object)
    def _page_cache_ready(self, token, results):
        if self._closed or token != self._cache_token:
            return
        for key, result in results:
            if key in self._rows:
                self._done.add(key)
                self.thumbnail_ready.emit(key, result)

    @Slot()
    def _page_cache_finished(self):
        thread = self._cache_thread
        if thread is None:
            return
        if not thread.wait(0):
            QTimer.singleShot(1, self._page_cache_finished)
            return
        self._cache_thread = self._cache_worker = None
        thread.deleteLater()
        self._lane_idle()

    def _schedule(self):
        if self._closed or self._cache_thread is not None:
            return
        if self._rows and self._cache_page != (self._session_id, self._generation, frozenset(self._rows)):
            self._start_page_cache()
            return
        active = set(self._assigned.values())
        limit = len(self._lanes) if self._rows and all(row.role == "head" for row in self._rows.values()) else min(4, len(self._lanes))
        for lane in self._lanes[:limit]:
            if lane.busy or lane in self._assigned:
                continue
            key = next((key for key in self._rows if key not in self._done and key not in active), "")
            if not key:
                continue
            self._assigned[lane] = key
            active.add(key)
            lane.visible([self._rows[key]], session_id=self._session_id, generation=self._generation)

    def _package_ready(self, key, result):
        if not self._closed and key == self._selected_key:
            self.package_ready.emit(key, result)

    def _thumbnail_ready(self, key, result):
        self._assigned.pop(self.sender(), None)
        if not self._closed:
            self.thumbnail_ready.emit(key, result)
            self._schedule_timer.start(0)

    def _failed(self, key, message):
        self._assigned.pop(self.sender(), None)
        if not self._closed:
            self.failed.emit(key, message)
            self._schedule_timer.start(0)

    def _lane_idle(self):
        if not self._closed:
            self._schedule_timer.start(0)
        if not self.busy and not self._assigned:
            self.idle.emit()

    def shutdown(self):
        self._closed = True
        self._schedule_timer.stop()
        self._assigned.clear()
        self._cache_token += 1
        if self._cache_worker is not None:
            self._cache_worker.stop()
        for lane in self._lanes:
            lane.shutdown()
