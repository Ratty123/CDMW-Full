"""Focused regressions for Mission A (startup latency) and Mission B (Finder warmups)."""

from __future__ import annotations

import importlib
import os
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.app.events import AppEventBus
from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from cdmw.domain.archives.character_catalogue import (
    BuildCharacterCatalogResult,
    CharacterCatalogSearchResult,
)
from cdmw.domain.archives.item_catalogue import (
    BuildNameIndexResult,
    ItemCatalogSearchResult,
)
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.archive_browser.remote_finder_warmup import RemoteItemFinderWarmupController
from cdmw.ui.character_finder.warmup import CharacterFinderWarmupController
from cdmw.ui.shell.app_context import AppContext
from cdmw.ui.shell.app_window import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_lazy_workspace_mixins_match_real_classes_without_collisions() -> None:
    from cdmw.ui.archive_browser import workspace as archive_ws
    from cdmw.ui.shell import workbench as shell_wb
    from cdmw.ui.texture_workflow import workspace as texture_ws

    for module_obj, spec_name in (
        (archive_ws, "_LAZY_MIXIN_SPECS"),
        (texture_ws, "_LAZY_MIXIN_SPECS"),
        (shell_wb, "_LAZY_BRIDGE_SPECS"),
    ):
        specs = getattr(module_obj, spec_name)
        seen_attrs: dict[str, str] = {}
        for mod_name, cls_name, expected_attrs in specs:
            mixin_cls = getattr(importlib.import_module(mod_name), cls_name)
            actual_attrs = set()
            for base in mixin_cls.__mro__:
                if not base.__module__.startswith("cdmw."):
                    continue
                for attr_name in base.__dict__:
                    if not (attr_name.startswith("__") and attr_name.endswith("__")):
                        actual_attrs.add(attr_name)
            assert set(expected_attrs) <= actual_attrs, f"Stale lazy attr in {mod_name}.{cls_name}"
            # Every attribute, so the first one the app touches attaches the mixin; one left
            # out raises AttributeError if it is reached before a listed one.
            assert actual_attrs <= set(expected_attrs), (
                f"Lazy attrs missing from {mod_name}.{cls_name}: {sorted(actual_attrs - set(expected_attrs))}"
            )
            for attr_name in expected_attrs:
                assert attr_name not in seen_attrs, (
                    f"Duplicate lazy attr {attr_name}: {seen_attrs[attr_name]} vs {mod_name}.{cls_name}"
                )
                seen_attrs[attr_name] = f"{mod_name}.{cls_name}"


def test_lazy_workspace_binding_preserves_bound_method_semantics() -> None:
    from cdmw.ui.archive_browser.workspace import ArchiveBrowserWorkspace
    from cdmw.ui.shell.workbench import WorkbenchWindow
    from cdmw.ui.texture_workflow.workspace import TexturesWorkspace

    app = _app()
    window = WorkbenchWindow()
    window.archive = ArchiveBrowserWorkspace(window)
    window.textures = TexturesWorkspace(window)
    try:
        static_arch = window.archive._ui_compact_status_line
        assert callable(static_arch)
        assert not hasattr(static_arch, "__self__")
        bound_arch = window.archive._start_archive_preview_core_prewarm
        assert bound_arch.__self__ is window.archive
        bound_tex = window.textures.collect_config
        assert bound_tex.__self__ is window.textures
        bound_shell = window._mesh_editor_entry_key
        assert bound_shell.__self__ is window
        assert not hasattr(window.archive, "__definitely_missing_attr__")
        assert not hasattr(window.textures, "__definitely_missing_attr__")
        assert not hasattr(window, "__definitely_missing_attr__")
    finally:
        window.deleteLater()
        app.processEvents()


def test_windows_process_memory_snapshot_skips_platform_system_wmi() -> None:
    from cdmw.ui.shell import diagnostics_controller

    with patch("platform.system", side_effect=AssertionError("Must not call platform.system() / WMI")):
        snapshot = diagnostics_controller.windows_process_memory_snapshot(os.getpid())
    if sys.platform == "win32":
        assert snapshot["pid"] == os.getpid()
        assert snapshot["working_set_bytes"] > 0
    else:
        assert snapshot == {}


def test_lazy_module_symbols_resolve_and_honor_monkeypatch(monkeypatch) -> None:
    from cdmw.ui.archive_browser import hkx_document_actions
    from cdmw.ui.mesh_editor import replace_from_archive_dialog, replace_from_archive_flow
    from cdmw.ui.shell import about_controller, app_window, model_library_bridge

    assert callable(app_window.mesh_import_mode_availability)
    assert callable(model_library_bridge.import_scene_mesh_with_report)
    assert replace_from_archive_flow.ReplaceFromArchivePickerDialog is replace_from_archive_dialog.ReplaceFromArchivePickerDialog
    assert about_controller.AboutDialog is not None

    sentinel = object()
    monkeypatch.setattr(hkx_document_actions, "ensure_archive_preview_source", sentinel)
    assert hkx_document_actions._sym("ensure_archive_preview_source") is sentinel


def test_settings_tab_is_lazy_at_startup_and_builds_cleanly_on_first_access(tmp_path) -> None:
    app = _app()
    settings = create_settings(settings_file_path=tmp_path / "startup.cfg")
    context = AppContext(
        settings=settings,
        services=ServiceContainer.create_default(settings=settings),
        event_bus=AppEventBus(),
    )
    with patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}):
        window = MainWindow(app_context=context)
    try:
        assert window.settings_tab.widget_if_created() is None
        assert window.textures.setup_section.parent() is window._deferred_settings_sections_holder
        assert window.archive.archive_locations_section.parent() is window._deferred_settings_sections_holder

        # Accessing any SettingsTab attribute transparently builds and wires it.
        group = window.settings_tab.archive_ignored_folders_group
        created = window.settings_tab.widget_if_created()
        assert created is not None
        assert group is created.archive_ignored_folders_group
        assert window._deferred_settings_sections_holder is None
        assert window.archive.archive_locations_section.parentWidget() is not None
    finally:
        window._finalize_close()
        window.deleteLater()
        app.processEvents()


def test_idle_module_preimport_loads_qt_free_modules_and_honors_stop(tmp_path) -> None:
    app = _app()
    settings = create_settings(settings_file_path=tmp_path / "idle.cfg")
    context = AppContext(
        settings=settings,
        services=ServiceContainer.create_default(settings=settings),
        event_bus=AppEventBus(),
    )
    with patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}):
        window = MainWindow(app_context=context)
    try:
        window._idle_preimport_stop_event = threading.Event()
        thread = window._start_idle_module_preimport(modules=("json", "math"))
        assert thread is not None
        thread.join(timeout=2.0)
        assert not thread.is_alive()

        # Once stop is requested, no new thread is started.
        window._stop_idle_module_preimport()
        assert window._start_idle_module_preimport(modules=("json",)) is None
    finally:
        window._finalize_close()
        window.deleteLater()
        app.processEvents()


class _FakeCatalogueService(QObject):
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)
    session_published = Signal(object)
    worker_crashed = Signal(str)
    operation_delayed = Signal(str, str, float)
    character_catalog_available = True

    def __init__(self) -> None:
        super().__init__()
        self.name_builds: list[tuple[str, int]] = []
        self.item_searches: list[object] = []
        self.character_builds: list[tuple[str, int]] = []
        self.character_searches: list[object] = []
        self.cancelled: list[str] = []

    def build_name_index(self, session_id: str, *, ui_generation: int) -> str:
        self.name_builds.append((session_id, ui_generation))
        return f"name-build-{len(self.name_builds)}"

    def search_item_catalog(self, request: object, *, ui_generation: int) -> str:
        self.item_searches.append(request)
        return f"item-search-{len(self.item_searches)}"

    def build_character_catalog(self, session_id: str, *, ui_generation: int) -> str:
        self.character_builds.append((session_id, ui_generation))
        return f"char-build-{len(self.character_builds)}"

    def search_character_catalog(self, request: object, *, ui_generation: int) -> str:
        self.character_searches.append(request)
        return f"char-search-{len(self.character_searches)}"

    def cancel(self, request_id: str) -> bool:
        self.cancelled.append(request_id)
        return True


def test_both_finder_warmups_start_on_session_published_even_when_archive_tab_is_not_active(tmp_path) -> None:
    app = _app()
    settings = create_settings(settings_file_path=tmp_path / "warmups.cfg")
    context = AppContext(
        settings=settings,
        services=ServiceContainer.create_default(settings=settings),
        event_bus=AppEventBus(),
    )
    with patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}):
        window = MainWindow(app_context=context)
    try:
        archive = window.archive
        # Simulate user sitting on Textures tab while MainWindow is visible.
        window.show()
        window._activate_tool_widget(window.textures)
        app.processEvents()
        archive.archive_browser_preload_state = "ready"
        archive.archive_browser_first_visible_paint_done = False
        archive.archive_browser_ready_at = time.perf_counter() - 1.0
        archive.archive_remote_query_pending = False
        archive._clear_archive_ui_activity()

        # Archive browser is hidden, so _archive_browser_background_work_allowed
        # is False, yet _archive_finder_warmup_allowed permits Finder warmups.
        assert not archive._archive_browser_background_work_allowed()
        assert archive._archive_finder_warmup_allowed()

        # Startup splash helper also recognises standalone sessions (empty archive_entries).
        assert window._archive_catalogue_loaded_for_first_paint()

        service = _FakeCatalogueService()
        archive_stub = QWidget(window)
        archive_stub.archive_catalogue_service = service
        archive_stub.archive_remote_bridge = SimpleNamespace(controller=SimpleNamespace(generation=3))
        archive_stub.shell = window
        archive_stub._archive_finder_warmup_allowed = archive._archive_finder_warmup_allowed
        archive_stub._archive_browser_background_work_allowed = archive._archive_browser_background_work_allowed
        item_warmup = RemoteItemFinderWarmupController(
            service,
            settings,
            background_allowed=archive._archive_browser_background_work_allowed,
            parent=archive,
        )
        char_warmup = CharacterFinderWarmupController(archive_stub)
        try:
            session = ArchiveSessionHandle("session-1", str(tmp_path), "fp-1", 42, 1, True)
            service.session_published.emit(session)
            item_warmup._continue_warmup()
            char_warmup._continue()

            assert service.name_builds == [("session-1", 0)]
            assert service.character_builds == [("session-1", 3)]
        finally:
            item_warmup.request_shutdown()
            char_warmup.request_shutdown()
    finally:
        window._finalize_close()
        window.deleteLater()
        app.processEvents()


def test_character_finder_warmup_preserves_inflight_build_across_pause_and_handles_cancel(tmp_path) -> None:
    app = _app()
    settings = create_settings(settings_file_path=tmp_path / "char-warmup.cfg")
    service = _FakeCatalogueService()

    class _Shell(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.settings = settings
            self.shell = self

    shell = _Shell()
    archive = QWidget(shell)
    archive.shell = shell
    archive.archive_catalogue_service = service
    archive.archive_remote_bridge = SimpleNamespace(controller=SimpleNamespace(generation=1))
    archive._archive_finder_warmup_allowed = lambda: True
    archive._archive_browser_background_work_allowed = lambda: True

    warmup = CharacterFinderWarmupController(archive)
    try:
        session = ArchiveSessionHandle("session-a", str(tmp_path), "fp-a", 10, 1, True)
        warmup.start(session, ui_generation=1)
        warmup._continue()
        assert service.character_builds == [("session-a", 1)]
        assert warmup._request == "char-build-1"

        # Brief UI activity pause or dialog opening must NOT abort out-of-process build_character_catalog.
        dialog_client = object()
        warmup.pause(dialog_client, cancel_active=False)
        warmup.pause(archive, cancel_active=True)
        assert service.cancelled == []
        assert warmup._request == "char-build-1"

        # Result arriving while paused caches summary without starting searches or previews.
        summary = BuildCharacterCatalogResult("session-a", True, 5, 2, 7, 7, 0, 0, ())
        service.result_ready.emit("char-build-1", "build_character_catalog", summary)
        assert warmup.cached_summary("session-a") == summary
        assert service.character_searches == []

        # Resuming continues to search; cancelling a search keeps _pages intact for retry.
        warmup.resume(archive)
        warmup.resume(dialog_client)
        warmup._continue()
        assert len(service.character_searches) == 1
        search_req_id = warmup._request
        service.request_cancelled.emit(search_req_id)
        assert warmup._request is None
        assert len(warmup._pages) >= 1

        # Same-session start advances ui_generation; same-fingerprint recovery preserves summary.
        warmup.start(session, ui_generation=5)
        assert warmup._generation == 5
        recovered = ArchiveSessionHandle("session-b", str(tmp_path), "fp-a", 10, 1, True)
        warmup.start(recovered, ui_generation=6)
        assert warmup.cached_summary("session-b").session_id == "session-b"

        # Invalidate cancels any active request unconditionally.
        warmup._continue()
        active_req = warmup._request
        assert active_req is not None
        warmup.invalidate()
        assert active_req in service.cancelled
    finally:
        warmup.request_shutdown()
        shell.deleteLater()
        app.processEvents()


def test_remote_item_finder_warmup_restarts_after_failure_on_new_start(tmp_path) -> None:
    app = _app()
    settings = create_settings(settings_file_path=tmp_path / "item-warmup.cfg")
    service = _FakeCatalogueService()
    warmup = RemoteItemFinderWarmupController(service, settings, background_allowed=lambda: True)
    try:
        session = ArchiveSessionHandle("session-x", str(tmp_path), "fp-x", 10, 1, True)
        warmup.start(session, ui_generation=1)
        warmup._continue_warmup()
        assert service.name_builds == [("session-x", 1)]
        service.request_failed.emit("name-build-1", RuntimeError("transient"))
        assert warmup._state == "failed"

        # Re-starting on the same session recovers from failed state.
        warmup.start(session, ui_generation=2)
        warmup._continue_warmup()
        assert service.name_builds == [("session-x", 1), ("session-x", 2)]
        service.result_ready.emit(
            "name-build-2",
            "build_name_index",
            BuildNameIndexResult("session-x", True, True, 10, 5, 15),
        )
        warmup._continue_warmup()
        assert len(service.item_searches) == 1
        result = ItemCatalogSearchResult("session-x", 1, 0, 72, (), ())
        service.result_ready.emit("item-search-1", "search_item_catalog", result)
        assert warmup.cached_search(service.item_searches[0]) == result
    finally:
        warmup.request_shutdown()
        app.processEvents()


def test_remote_item_finder_warmup_keeps_the_name_build_across_ui_activity(tmp_path) -> None:
    app = _app()
    settings = create_settings(settings_file_path=tmp_path / "item-warmup-pause.cfg")
    service = _FakeCatalogueService()
    allowed = [True]
    warmup = RemoteItemFinderWarmupController(service, settings, background_allowed=lambda: allowed[0])
    names_ready: list[str] = []
    warmup.itemNamesReady.connect(names_ready.append)
    try:
        session = ArchiveSessionHandle("session-p", str(tmp_path), "fp-p", 10, 1, True)
        warmup.start(session, ui_generation=1)
        warmup._continue_warmup()
        assert service.name_builds == [("session-p", 1)]

        # Scrolling, a settings save or a Mesh Editor hold pauses background work.
        # The worker-side name build must survive it rather than start over.
        allowed[0] = False
        warmup.pause_background()
        warmup.pause_background()
        assert service.cancelled == []
        warmup._continue_warmup()
        assert service.name_builds == [("session-p", 1)]

        # The result lands while still paused: names are announced at once, while
        # the Finder's own searches wait for the UI to go idle.
        service.result_ready.emit(
            "name-build-1",
            "build_name_index",
            BuildNameIndexResult("session-p", True, False, 10, 5, 15),
        )
        assert names_ready == ["session-p"]
        warmup._continue_warmup()
        assert service.item_searches == []

        allowed[0] = True
        warmup.resume_background()
        warmup._continue_warmup()
        assert len(service.item_searches) == 1
        assert names_ready == ["session-p"]

        # Invalidating (a new root, shutdown) still cancels a build in flight.
        warmup.start(ArchiveSessionHandle("session-q", str(tmp_path), "fp-q", 10, 1, True), ui_generation=2)
        warmup._continue_warmup()
        assert service.name_builds[-1] == ("session-q", 2)
        warmup.invalidate()
        assert "name-build-2" in service.cancelled
    finally:
        warmup.request_shutdown()
        app.processEvents()


def test_remote_item_finder_name_build_starts_after_bounded_wait_for_idle(tmp_path, monkeypatch) -> None:
    from cdmw.ui.archive_browser import remote_finder_warmup

    app = _app()
    settings = create_settings(settings_file_path=tmp_path / "item-warmup-patience.cfg")
    service = _FakeCatalogueService()
    clock = [100.0]
    monkeypatch.setattr(remote_finder_warmup.time, "monotonic", lambda: clock[0])
    warmup = RemoteItemFinderWarmupController(service, settings, background_allowed=lambda: False)
    try:
        warmup.start(ArchiveSessionHandle("session-w", str(tmp_path), "fp-w", 10, 1, True), ui_generation=1)
        warmup._continue_warmup()
        clock[0] += 9.0
        warmup._continue_warmup()
        assert service.name_builds == []
        # Someone scrolling non-stop never gives an idle moment; names still come.
        clock[0] += 1.5
        warmup._continue_warmup()
        assert service.name_builds == [("session-w", 1)]
    finally:
        warmup.request_shutdown()
        app.processEvents()


@pytest.mark.parametrize("language", ["en", "es", "de"])
def test_builtin_documentation_builds_through_the_lazy_dispatcher(language) -> None:
    """Help > Documentation without a browser builds every topic from the window's mixin."""

    from cdmw.ui.shell.about_documentation import AboutDocumentationMixin

    class _Window(AboutDocumentationMixin):
        settings_file_path = "CrimsonDesertModWorkbench.ini"
        archive = SimpleNamespace(archive_cache_root="archive_cache")

        def _build_about_intro_html(self) -> str:
            return "<p>intro</p>"

    # The window's class may not have the English topic helpers; the dispatcher adds them.
    assert not hasattr(_Window, "_build_start_sections")

    _title, _intro, sections = _Window()._build_about_document_for_language(language)
    assert sections and all(section.get("title") for section in sections)
