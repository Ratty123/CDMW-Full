"""Preload three pages per Finder tab through the existing preview pipeline."""

from collections import deque
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from cdmw.domain.archives.character_catalogue import (
    BuildCharacterCatalogResult, CharacterCatalogSearchRequest, CharacterCatalogSearchResult,
)
from cdmw.ui.shell.close_controller import register_transient_worker_controller


class CharacterFinderWarmupController(QObject):
    def __init__(self, archive):
        super().__init__(archive)
        self._archive = archive
        self._service = archive.archive_catalogue_service
        self._session = None
        self._generation = 0
        self._request = None
        self._request_kind = None
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
        self._service.request_cancelled.connect(self._cancelled)
        self._service.worker_crashed.connect(self.invalidate)
        if hasattr(self._service, "session_published"):
            self._service.session_published.connect(self._handle_session_published)
        register_transient_worker_controller(archive.shell, self)

    def _handle_session_published(self, session):
        if self._closed or not isinstance(session, ArchiveSessionHandle):
            return
        bridge = getattr(self._archive, "archive_remote_bridge", None)
        controller = getattr(bridge, "controller", None)
        ui_generation = int(getattr(controller, "generation", self._generation) or self._generation)
        self.start(session, ui_generation=ui_generation)

    def start(self, session, *, ui_generation):
        if self._closed or not self._service.character_catalog_available:
            return
        if self._session == session:
            self._generation = max(self._generation, int(ui_generation))
            if self._summary is not None or self._request is not None or self._pages:
                if not self._paused and self._request is None and self._pages and not self._timer.isActive():
                    self._timer.start(0)
                return
        elif (
            self._session is not None
            and getattr(self._session, "fingerprint", None) == getattr(session, "fingerprint", None)
            and self._summary is not None
        ):
            # Recovered session with identical fingerprint: keep cached summary and rebind session id.
            self._session = session
            self._generation = max(self._generation, int(ui_generation))
            self._summary = replace(self._summary, session_id=session.session_id)
            self._searches = {
                replace(req, session_id=session.session_id): replace(res, session_id=session.session_id)
                for req, res in self._searches.items()
            }
            self._pages = deque(replace(req, session_id=session.session_id) for req in self._pages)
            if not self._paused and self._request is None and self._pages and not self._timer.isActive():
                self._timer.start(0)
            return
        self.invalidate()
        self._session, self._generation = session, int(ui_generation)
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
        self._timer.start(0)

    def cached_summary(self, session_id):
        return self._summary if self._session and self._session.session_id == session_id else None

    def cached_search(self, request):
        return self._searches.get(request)

    def cached_detail(self, key, session_id):
        if self._preview is not None and self._session is not None and self._session.session_id == session_id:
            return self._preview.cached_detail(key, session_id)
        return None

    def pause(self, client, *, cancel_active=False):
        if self._closed or client in self._clients:
            return
        self._clients.add(client)
        self._paused = True
        self._timer.stop()
        # Keep an in-flight out-of-process build_character_catalog alive across
        # brief UI activity and Finder dialog opens: it runs in the separate
        # archive worker behind a shared build gate without holding Python's
        # GIL, so cancelling it would discard progress and force a cold rebuild
        # when the dialog opens. Only invalidate()/shutdown() cancels builds.
        if cancel_active and self._request_kind != "build":
            self._cancel_request()
        if self._preview is not None:
            self._preview.pause_scheduling(cancel_active=cancel_active)

    def resume(self, client):
        self._clients.discard(client)
        if not self._closed and not self._clients:
            self._paused = False
            self._timer.start(0)

    def _cancel_request(self):
        request, self._request, self._request_kind = self._request, None, None
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

    def _warmup_allowed(self):
        gate = getattr(self._archive, "_archive_finder_warmup_allowed", None)
        if callable(gate):
            return bool(gate())
        return bool(self._archive._archive_browser_background_work_allowed())

    def _continue(self):
        if self._closed or self._paused or self._session is None or self._request is not None:
            return
        if self._preview is not None and self._preview._closed:
            if self._preview.busy:
                self._timer.start(40)
                return
            self._preview.deleteLater()
            self._preview = None
        if not self._warmup_allowed():
            if self._preview is not None:
                self._preview.pause_scheduling(cancel_active=True)
            self._timer.start(250)
            return
        if self._preview is not None:
            self._preview.resume_scheduling()
        if self._rendering:
            if not self._preview.page_complete:
                # The preview scheduler advances inside a page, independently
                # of page completion. Keep applying the application idle gate.
                self._timer.start(250)
                return
            self._pages.popleft()
            self._rendering = False
        if not self._pages:
            return
        try:
            if self._summary is None:
                self._request = self._service.build_character_catalog(
                    self._session.session_id, ui_generation=self._generation)
                self._request_kind = "build"
                return
            page = self._searches.get(self._pages[0])
            if page is None:
                self._request = self._service.search_character_catalog(
                    self._pages[0], ui_generation=self._generation)
                self._request_kind = "search"
                return
            if self._preview is None:
                from cdmw.ui.character_finder.preview_controller import CharacterFinderPreviewController

                self._preview = CharacterFinderPreviewController(self._service,
                    fingerprint=self._session.fingerprint,
                    cache_root=Path(self._archive._native_preview_package_cache_root()),
                    settings=self._archive._current_model_preview_render_settings(),
                    parent=self, max_lanes=2, background=True)
                self._preview.idle.connect(self._schedule)
            self._rendering = True
            self._preview.visible(page.rows, session_id=self._session.session_id, generation=self._generation)
            self._timer.start(250)
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
        self._request_kind = None
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

    def _cancelled(self, request, *_args):
        if request == self._request:
            self._request = None
            self._request_kind = None
            if not self._closed and not self._paused and self._pages:
                self._timer.start(250)

    def _failed(self, request, *_args):
        if request == self._request:
            self._request = None
            self._request_kind = None
            self._pages.clear()

    def iter_shutdown_workers(self):
        if self._preview is not None:
            yield from self._preview.iter_shutdown_workers()

    def request_shutdown(self):
        self._closed = True
        self.invalidate()
