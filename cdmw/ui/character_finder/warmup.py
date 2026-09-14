"""Preload three pages per Finder tab through the existing preview pipeline."""

from collections import deque
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from cdmw.domain.archives.character_catalogue import (
    BuildCharacterCatalogResult, CharacterCatalogSearchRequest, CharacterCatalogSearchResult,
)
from cdmw.ui.character_finder.preview_controller import CharacterFinderPreviewController
from cdmw.ui.shell.close_controller import register_transient_worker_controller


class CharacterFinderWarmupController(QObject):
    def __init__(self, archive):
        super().__init__(archive)
        self._archive = archive
        self._service = archive.archive_catalogue_service
        self._session = None
        self._generation = 0
        self._request = None
        self._preview = None
        self._summary = None
        self._searches = {}
        self._pages = deque()
        self._rendering = False
        self._paused = False
        self._clients = set()
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._continue)
        self._service.result_ready.connect(self._result)
        self._service.request_failed.connect(self._failed)
        self._service.request_cancelled.connect(self._failed)
        self._service.worker_crashed.connect(self.invalidate)
        register_transient_worker_controller(archive.shell, self)

    def start(self, session, *, ui_generation):
        if self._closed or not self._service.character_catalog_available or self._session == session:
            return
        self.invalidate()
        self._session, self._generation = session, ui_generation
        settings = self._archive.shell.settings
        def saved(field, default=""):
            return str(settings.value("ui/character_finder/" + field, default) or "")
        tab = "faces" if saved("tab", "bodies") == "faces" else "bodies"
        source = saved("source_group")
        source = None if source == "all" else source or "humanoid"
        first = CharacterCatalogSearchRequest(session.session_id,
            view="appearances" if saved("view") == "appearances" else "assets", tab=tab,
            source_group=source, role=saved("role") or None,
            body_family=saved("body_family") or None, resolution=saved("resolution") or None)
        # Faces' empty component filter means separate heads in the catalogue.
        if tab == "faces" and first.role == "head":
            first = replace(first, role=None)
        self._pages.extend((first, replace(first, tab="bodies" if tab == "faces" else "faces", role=None)))
        self._timer.start(500)

    def cached_summary(self, session_id):
        return self._summary if self._session and self._session.session_id == session_id else None

    def cached_search(self, request):
        return self._searches.get(request)

    def cached_detail(self, key, session_id):
        if self._preview is not None and self._session is not None and self._session.session_id == session_id:
            return self._preview.cached_detail(key, session_id)
        return None

    def pause(self, client):
        self._clients.add(client)
        self._paused = True
        self._timer.stop()
        self._cancel_request()
        if self._preview is not None:
            self._preview.pause_scheduling()

    def resume(self, client):
        self._clients.discard(client)
        if not self._closed and not self._clients:
            self._paused = False
            if self._preview is not None:
                self._preview.resume_scheduling()
            self._timer.start(500)

    def _cancel_request(self):
        request, self._request = self._request, None
        if request is not None:
            self._service.cancel(request)

    def invalidate(self, *_args):
        self._timer.stop()
        self._cancel_request()
        self._session = None
        self._summary = None
        self._searches.clear()
        self._pages.clear()
        self._rendering = False
        self._paused = bool(self._clients)
        if self._preview is not None:
            # Keep the controller (and every native thread) until real teardown.
            self._preview.shutdown()

    def _continue(self):
        if self._closed or self._paused or self._session is None or self._request is not None:
            return
        if self._preview is not None and self._preview._closed:
            if self._preview.busy:
                self._timer.start(40)
                return
            self._preview.deleteLater()
            self._preview = None
        if not self._archive._archive_browser_background_work_allowed():
            self._timer.start(500)
            return
        if self._rendering:
            if not self._preview.page_complete:
                return
            self._pages.popleft()
            self._rendering = False
        if not self._pages:
            return
        try:
            if self._summary is None:
                self._request = self._service.build_character_catalog(
                    self._session.session_id, ui_generation=self._generation)
                return
            page = self._searches.get(self._pages[0])
            if page is None:
                self._request = self._service.search_character_catalog(
                    self._pages[0], ui_generation=self._generation)
                return
            if self._preview is None:
                self._preview = CharacterFinderPreviewController(self._service,
                    fingerprint=self._session.fingerprint,
                    cache_root=Path(self._archive._native_preview_package_cache_root()),
                    settings=self._archive._current_model_preview_render_settings(),
                    parent=self, max_lanes=2)
                self._preview.idle.connect(self._schedule)
            self._rendering = True
            self._preview.visible(page.rows, session_id=self._session.session_id, generation=self._generation)
        except Exception:
            # A failed optional warmup must leave normal Finder retries available.
            self._rendering = False
            self._pages.clear()

    def _schedule(self):
        if not self._closed and not self._paused:
            self._timer.start(0)

    def _result(self, request, _operation, result):
        if (self._closed or request != self._request or self._session is None
                or getattr(result, "session_id", None) != self._session.session_id):
            return
        self._request = None
        if isinstance(result, BuildCharacterCatalogResult):
            self._summary = result
        elif isinstance(result, CharacterCatalogSearchResult) and self._pages:
            request = self._pages[0]
            self._searches[request] = result
            next_start = request.page_start + 72
            if next_start < min(result.total_matches, 3 * 72):
                # Alternate tabs, keeping both landing pages ahead of their
                # following pages while warming enough for early navigation.
                self._pages.append(replace(request, page_start=next_start))
        else:
            self._pages.clear()
        self._schedule()

    def _failed(self, request, *_args):
        if request == self._request:
            self._request = None
            self._pages.clear()

    def iter_shutdown_workers(self):
        if self._preview is not None:
            yield from self._preview.iter_shutdown_workers()

    def request_shutdown(self):
        self._closed = True
        self.invalidate()
