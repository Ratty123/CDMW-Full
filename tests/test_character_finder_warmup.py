from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from cdmw.domain.archives.character_catalogue import BuildCharacterCatalogResult, CharacterCatalogSearchResult
from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.character_finder import warmup as module
from cdmw.ui.shell.close_controller import iter_transient_shutdown_workers, request_transient_shutdowns
from tests.test_character_finder_dialog import Service, Preview, Host, row


_APP = None


class WarmService(Service):
    request_cancelled = Signal(str)


class WarmPreview(Preview):
    page_complete = True
    _closed = False
    busy = False

    def __init__(self, *args, max_lanes, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_lanes = max_lanes
        self.pages = []
        self.cleared = 0
        self.paused = False

    def visible(self, rows, **kwargs):
        self.pages.append(tuple(rows))
        self.page_complete = False

    def clear_page(self):
        self.cleared += 1
        self.page_complete = True

    def shutdown(self): self._closed = True
    def pause_scheduling(self): self.paused = True
    def resume_scheduling(self): self.paused = False

    def iter_shutdown_workers(self):
        if self.busy:
            yield "warmup", "retained-thread", "retained-worker"


@pytest.fixture
def warmup(monkeypatch, tmp_path):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    monkeypatch.setattr(module, "CharacterFinderPreviewController", WarmPreview)
    archive = QWidget()
    archive.shell = archive.archive = archive
    archive.settings = SimpleNamespace(value=lambda _key, default=None: default, setValue=lambda *_: None)
    archive.archive_catalogue_service = WarmService()
    archive._native_preview_package_cache_root = lambda: tmp_path
    archive._current_model_preview_render_settings = ModelPreviewRenderSettings
    archive._archive_browser_background_work_allowed = lambda: True
    owner = module.CharacterFinderWarmupController(archive)
    archive.archive_character_finder_warmup_controller = owner
    session = ArchiveSessionHandle("session-a", "C:/game", "fp", 10, 3, True)
    yield owner, archive, session
    owner.request_shutdown()
    archive.deleteLater()
    _APP.processEvents()


def publish(owner, archive, result):
    archive.archive_catalogue_service.result_ready.emit(owner._request, "fixture", result)
    owner._timer.stop()
    owner._continue()


def build_first_page(owner, archive, session):
    owner.start(session, ui_generation=4)
    owner._timer.stop()
    owner._continue()
    summary = BuildCharacterCatalogResult("session-a", True, 10, 1, 11, 11, 0, 0, ())
    publish(owner, archive, summary)
    page = CharacterCatalogSearchResult("session-a", 72, 0, 72, (row(1),), (), ())
    publish(owner, archive, page)
    return summary, page


def test_startup_preloads_both_pages_after_paint_and_caches_catalogue(warmup):
    owner, archive, session = warmup
    service = archive.archive_catalogue_service
    archive._archive_browser_background_work_allowed = lambda: False
    owner.start(session, ui_generation=4)
    owner._continue()
    assert not service.calls
    archive._archive_browser_background_work_allowed = lambda: True
    summary, page = build_first_page(owner, archive, session)
    preview = owner._preview
    assert preview.max_lanes == 2 and preview.pages == [page.rows]
    assert owner.cached_summary(session.session_id) is summary
    assert owner.cached_search(owner._pages[0]) is page
    assert service.calls[1][1].source_group == "humanoid"
    preview.page_complete = True
    owner._continue()
    assert service.calls[-1][1].tab == "faces" and service.calls[-1][1].role is None
    faces = replace(page, rows=(row(2, role="head"),))
    publish(owner, archive, faces)
    assert preview.pages == [page.rows, faces.rows]
    preview.page_complete = True
    owner._continue()
    owner.start(session, ui_generation=5)
    owner._continue()
    assert len(service.calls) == 3 and not owner._pages


def test_refresh_and_shutdown_retain_active_threads_and_reject_old_results(warmup):
    owner, archive, session = warmup
    _, page = build_first_page(owner, archive, session)
    old = owner._preview
    old.busy = True
    owner.start(replace(session, session_id="session-b", fingerprint="new"), ui_generation=5)
    owner._continue()
    assert old._closed and owner._preview is old
    assert list(iter_transient_shutdown_workers(archive))[0][1] == "retained-thread"
    assert owner.cached_summary("session-a") is None and not owner._searches
    old.busy = False
    owner._continue()
    late = owner._request
    request_transient_shutdowns(archive)
    archive.archive_catalogue_service.result_ready.emit(late, "search", page)
    assert owner._closed and not owner._searches
    assert late in archive.archive_catalogue_service.cancelled


def test_opening_uses_preloaded_catalogue_and_resumes_warmup_after_close(warmup, monkeypatch):
    from cdmw.ui.character_finder import dialog as feature
    owner, archive, session = warmup
    _, page = build_first_page(owner, archive, session)
    preview = owner._preview
    monkeypatch.setattr(feature, "CharacterFinderPreviewController", Preview)
    monkeypatch.setattr(feature, "RustPreviewHostFrame", Host)
    archive.archive_remote_bridge = SimpleNamespace(current_session=session,
        controller=SimpleNamespace(generation=4))
    dialog = feature.CharacterFinderDialog(archive)
    try:
        assert owner._paused and preview.paused and preview.cleared == 0
        dialog._build()
        assert dialog._preview.visible_rows == list(page.rows)
        kinds = [token.split("-")[0] for token, _, _ in archive.archive_catalogue_service.calls]
        assert kinds.count("build") == 1 and kinds.count("search") == 1
        dialog.close()
        dialog._release()
        assert not owner._paused and not preview.paused
    finally:
        if not dialog._closing:
            dialog.close()


def test_pause_cancels_pending_requests_and_resume_retries_same_page(warmup):
    owner, archive, session = warmup
    owner.start(session, ui_generation=4)
    owner._continue()
    request = owner._request
    owner.pause(archive)
    assert request in archive.archive_catalogue_service.cancelled
    archive.archive_catalogue_service.result_ready.emit(request, "build",
        BuildCharacterCatalogResult("session-a", True, 10, 1, 11, 11, 0, 0, ()))
    assert owner._summary is None
    owner.resume(archive)
    owner._continue()
    assert owner._request != request


def test_a_closing_dialog_cannot_resume_background_work_under_a_new_dialog(warmup):
    owner, archive, session = warmup
    owner.start(session, ui_generation=4)
    first, second = object(), object()
    owner.pause(first)
    owner.pause(second)
    owner.resume(first)
    owner.resume(first)  # Release callbacks can arrive more than once.
    owner._continue()
    assert owner._paused and not archive.archive_catalogue_service.calls
    owner.resume(second)
    owner._continue()
    assert not owner._paused and len(archive.archive_catalogue_service.calls) == 1


def test_actual_archive_publication_starts_warmup_and_rescan_invalidates_it(warmup):
    from cdmw.domain.archives.catalogue import ArchiveQueryHandle
    from cdmw.ui.archive_browser.model import ArchiveBrowserTreeView
    from cdmw.ui.archive_browser.remote_window_bridge import ArchiveRemoteWindowBridge
    from cdmw.services.archive_catalogue_service import ArchiveCatalogueService

    owner, archive, session = warmup
    service = archive.archive_catalogue_service
    # The real bridge uses these service signals even though this fixture never
    # loads game files or starts the external archive helper.
    class BridgeService(WarmService):
        batch_ready = Signal(str, str, object)
        compatibility_entry = staticmethod(ArchiveCatalogueService.compatibility_entry)
    service = BridgeService()
    archive.archive_catalogue_service = service
    archive.archive_tree = ArchiveBrowserTreeView(archive)
    archive.archive_remote_query_pending = False
    archive._current_archive_filter_signature = lambda: ()
    archive._capture_archive_filter_state = lambda: {}
    for method in ("_schedule_archive_tree_content_autofit", "_update_archive_filter_button_state",
                   "_set_archive_cache_health", "_set_archive_list_status", "_set_archive_warmup_overlay",
                   "_set_archive_load_progress", "set_status_message", "append_archive_log", "set_busy",
                   "_write_heartbeat", "_release_startup_splash", "_record_runtime_event",
                   "_rebuild_archive_structure_filter_controls"):
        setattr(archive, method, lambda *_args, **_kwargs: None)
    bridge = ArchiveRemoteWindowBridge(archive, display_v2=True, shadow=False)
    bridge._controller._current_session = session
    bridge._activate_tab_on_publish = False
    bridge.request_structure_children = lambda *_: None
    bridge._controller.open_archive = lambda *_args, **_kwargs: None
    bridge._handle_query_published(ArchiveQueryHandle(session.session_id, "query", 4, 10))
    assert owner._session == session and owner._timer.isActive()
    bridge.open_archive("C:/game", force_refresh=False, activate_tab=False)
    assert owner._session is None and not owner._timer.isActive()
