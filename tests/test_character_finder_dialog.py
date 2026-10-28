from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget, QSplitter, QVBoxLayout
from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from cdmw.domain.archives.character_catalogue import (
    BuildCharacterCatalogResult, CharacterCatalogRow, CharacterCatalogSearchResult,
    CharacterCatalogDetailResult, CharacterCatalogScopeResult,
)
from cdmw.domain.character_finder import CharacterRenderResult
from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.character_finder import dialog as feature

_APPLICATION = None


class Service(QObject):
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    progress = Signal(str, object)
    session_published = Signal(object)
    worker_crashed = Signal(str)
    character_catalog_available = True

    def __init__(self):
        super().__init__()
        self.calls = []
        self.cancelled = []

    def _call(self, kind, request, **kw):
        token = f"{kind}-{len(self.calls)}"
        self.calls.append((token, request, kw))
        return token

    def build_character_catalog(self, request, **kw): return self._call("build", request, **kw)
    def search_character_catalog(self, request, **kw): return self._call("search", request, **kw)
    def get_character_catalog_detail(self, request, **kw): return self._call("detail", request, **kw)
    def scope_character_catalog(self, request, **kw): return self._call("scope", request, **kw)
    def cancel(self, token): self.cancelled.append(token)


class Preview(QObject):
    package_ready = Signal(str, object)
    thumbnail_ready = Signal(str, object)
    failed = Signal(str, str)
    progress = Signal(str, str, int, int)
    idle = Signal()
    busy = False
    page_complete = False
    _thread = None
    _worker = None

    def __init__(self, *a, parent=None, **kw):
        super().__init__(parent)
        self.selected = []
        self.visible_rows = []
        self.prefetch_rows = []
        self.cleared = 0

    def select(self, detail, generation): self.selected.append(detail)
    def cached_detail(self, key, session_id): return None
    def visible(self, rows, **kw): self.visible_rows = rows
    def prefetch(self, rows, **kw): self.prefetch_rows = rows
    def clear_page(self):
        self.cleared += 1
        self.visible_rows = []
        self.prefetch_rows = []
    def shutdown(self): pass
    def iter_shutdown_workers(self): return iter(())


class Host(QWidget):
    package_applied = Signal(str, int)
    package_failed = Signal(str, int, str)

    def __init__(self, parent=None, **kw):
        super().__init__(parent)
        self.controller = self
        self.loaded = []
        self.canonical_views = 0
        self.hidden_parts = []

    def load_package(self, path, **kw):
        self.loaded.append(path)
        return True

    def reset_view(self): pass
    def set_hidden_source_submeshes(self, indices): self.hidden_parts.append(tuple(indices))
    def request_canonical_view(self): self.canonical_views += 1
    def shutdown(self): pass


def row(i=1, **kw):
    return replace(CharacterCatalogRow(f"asset:{i}", "assets", "body", f"Body {i}", f"body_{i}",
        f"character/model/body_{i}.pac", "1_pc", "1_phm", "resolved", "base_appearance", 1, 0, "Installed model."), **kw)


def detail(selected, related=()):
    return CharacterCatalogDetailResult("session-a", selected, (), (), (), (), tuple(related), (), 0, len(related), 0, False, "", selected.key)


@pytest.fixture
def finder(monkeypatch, tmp_path):
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    monkeypatch.setattr(feature, "CharacterFinderPreviewController", Preview)
    monkeypatch.setattr(feature, "RustPreviewHostFrame", Host)
    window = QWidget()
    window.archive = window.shell = window
    window.archive_catalogue_service = Service()
    scopes = []
    window.archive_remote_bridge = SimpleNamespace(current_session=ArchiveSessionHandle("session-a", "C:/game", "fp", 10, 3, True),
        controller=SimpleNamespace(generation=4), apply_entry_id_scope=lambda ids, **kw: scopes.append((ids, kw)) or True)
    window._native_preview_package_cache_root = lambda: tmp_path
    window._current_model_preview_render_settings = ModelPreviewRenderSettings
    dialog = feature.CharacterFinderDialog(window)
    dialog.show()
    _APPLICATION.processEvents()
    service = window.archive_catalogue_service
    service.result_ready.emit(dialog._requests["build"], "build_character_catalog", BuildCharacterCatalogResult("session-a", True, 10, 1, 11, 11, 0, 0, ()))
    yield dialog, service, scopes
    if not dialog._closing:
        dialog.close()
    _APPLICATION.processEvents()
    window.deleteLater()


def publish_rows(dialog, service, rows, *, total=None, page_start=0):
    service.result_ready.emit(dialog._requests["search"], "search_character_catalog",
        CharacterCatalogSearchResult("session-a", len(rows) if total is None else total, page_start, 72, tuple(rows), (), ()))


def test_underwear_toggle_updates_the_loaded_preview_without_preparation_and_follows_page_selection(finder):
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(1), row(2)])
    assert not dialog._show_underwear.isEnabled()
    first = CharacterRenderResult("render-1", "package-1", "image", "base_appearance", (),
        underwear_submesh_indices=(3, 7))
    dialog._preview.package_ready.emit("asset:1", first)
    dialog._host.package_applied.emit(first.package_path, 4)
    assert dialog._show_underwear.isEnabled() and dialog._show_underwear.isChecked()
    calls, selected = len(service.calls), len(dialog._preview.selected)
    dialog._show_underwear.setChecked(False)
    assert dialog._host.hidden_parts[-1] == (3, 7)
    assert len(service.calls) == calls and len(dialog._preview.selected) == selected
    assert dialog._host.loaded == [first.package_path]
    dialog._grid.setCurrentItem(dialog._items["asset:2"])
    second = replace(first, key="render-2", package_path="package-2", underwear_submesh_indices=(5,))
    dialog._preview.package_ready.emit("asset:2", second)
    dialog._host.package_applied.emit(first.package_path, 4)  # Stale completion keeps the last shown model's controls.
    assert dialog._underwear_parts == (3, 7)
    dialog._host.package_applied.emit(second.package_path, 4)
    assert dialog._host.hidden_parts[-1] == (5,)
    dialog._show_underwear.setChecked(True)
    assert dialog._host.hidden_parts[-1] == ()


def test_failed_cards_show_the_error_state_and_successful_retry_restores_the_caption(finder, tmp_path):
    from PySide6.QtGui import QImage
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(1)])
    dialog._preview.failed.emit("asset:1", "Access to the path is denied.")
    assert "Preview unavailable" in dialog._items["asset:1"].text()
    assert "Access to the path" in dialog._preview_status.text()
    image = tmp_path / "ready.png"
    QImage(4, 4, QImage.Format.Format_RGB32).save(str(image))
    dialog._preview.thumbnail_ready.emit("asset:1", CharacterRenderResult("ready", "package", str(image), "base_appearance", ()))
    assert "Preview unavailable" not in dialog._items["asset:1"].text()


def test_loading_stages_counts_animation_and_host_completion_are_independent(finder, tmp_path):
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(1), row(2)])
    assert "2 queued" in dialog._loading_summary.text()
    assert "Queued" in dialog._items["asset:1"].text()
    assert not dialog._preview_busy.isHidden()
    service.result_ready.emit(dialog._requests["detail"], "detail", detail(row(1)))
    assert dialog._preview_status.text() == "Preparing preview…"

    dialog._preview.progress.emit("asset:1", "preparing_files", 3, 8)
    dialog._preview.progress.emit("asset:2", "rendering_thumbnail", 0, 0)
    assert "Preparing model files… · 3/8" in dialog._items["asset:1"].text()
    assert "3/8" in dialog._preview_status.text()
    assert "2 loading" in dialog._loading_summary.text()
    assert dialog._loading_timer.isActive()
    # Exercise the real delegate through an offscreen widget render.
    assert not dialog._grid.grab().isNull()

    preview = CharacterRenderResult("render", "package", "", "base_appearance", ())
    dialog._preview.package_ready.emit("asset:1", preview)
    dialog._preview.progress.emit("asset:1", "rendering_thumbnail", 0, 0)
    assert dialog._preview_status.text() == "Opening interactive preview…"
    assert not dialog._preview_busy.isHidden()
    dialog._host.package_applied.emit(preview.package_path, 4)
    assert dialog._preview_busy.isHidden()
    assert dialog._preview_status.text() == "Base appearance"
    assert dialog._loading_timer.isActive()  # Thumbnail capture still runs.

    image = tmp_path / "thumb.png"
    from PySide6.QtGui import QPixmap
    pixels = QPixmap(8, 8)
    pixels.fill()
    assert pixels.save(str(image))
    dialog._preview.thumbnail_ready.emit("asset:1", replace(preview, thumbnail_path=str(image)))
    dialog._preview.failed.emit("asset:2", "fixture failure")
    assert dialog._page_progress.value() == 2
    assert "1/2 ready" in dialog._loading_summary.text() and "1 unavailable" in dialog._loading_summary.text()
    assert not dialog._loading_timer.isActive()
    dialog._preview.progress.emit("asset:2", "retrying", 0, 0)
    assert "Retrying preview…" in dialog._items["asset:2"].text()
    assert "0 unavailable" in dialog._loading_summary.text() and dialog._loading_timer.isActive()
    dialog._preview.thumbnail_ready.emit("asset:2", replace(preview, thumbnail_path=str(image)))
    assert "2/2 ready" in dialog._loading_summary.text()
    assert "fixture failure" not in dialog._items["asset:2"].toolTip()
    assert not dialog._loading_timer.isActive()
    dialog._host.package_failed.emit(preview.package_path, 4, "fixture host failure")
    assert "2/2 ready" in dialog._loading_summary.text()  # Existing images remain usable.


def test_obsolete_loading_events_cannot_restart_indicators_after_search_or_close(finder):
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(1)])
    dialog._preview.progress.emit("asset:1", "finding_files", 0, 0)
    dialog._search_edit.setText("another body")
    dialog._preview.progress.emit("asset:1", "preparing_files", 2, 4)
    assert dialog._loading_summary.text() == ""
    assert dialog._preview_busy.isHidden() and not dialog._loading_timer.isActive()
    dialog._search()
    publish_rows(dialog, service, [row(2)])
    before = dialog._loading_summary.text()
    dialog._preview.progress.emit("asset:1", "rendering_thumbnail", 0, 0)
    assert dialog._loading_summary.text() == before
    dialog._preview.progress.emit("asset:2", "preparing_geometry", 0, 0)
    dialog.close()
    dialog._preview.progress.emit("asset:2", "saving_preview", 0, 0)
    assert not dialog._loading_timer.isActive() and dialog._preview_busy.isHidden()


def test_next_page_request_starts_immediately_and_is_promoted_without_requery(finder):
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(i) for i in range(72)], total=144)
    assert not dialog._preview.page_complete
    request = dialog._requests["prefetch"]
    assert service.calls[-1][1].page_start == 72
    assert service.calls[-1][1].source_group == "humanoid"
    assert dialog._next_button.isEnabled()
    before = dialog._status.text()
    dialog._progress(request, SimpleNamespace(current_item="background progress", completed=1, total=2))
    assert dialog._status.text() == before
    cleared = dialog._preview.cleared
    dialog._page(1)
    assert dialog._requests["search"] == request and request not in service.cancelled
    assert dialog._preview.cleared == cleared
    publish_rows(dialog, service, [row(i) for i in range(72, 144)], total=144, page_start=72)
    searches = sum(token.startswith("search-") for token, _, _ in service.calls)
    dialog._page(-1)
    assert sum(token.startswith("search-") for token, _, _ in service.calls) == searches
    assert dialog._preview.visible_rows[0].key == "asset:0"


def test_four_page_lookahead_rolls_forward_and_retains_a_useful_pending_request(finder):
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(i) for i in range(72)], total=720)
    for start in (72, 144, 216, 288):
        token = dialog._requests["prefetch"]
        assert dialog._prefetch_search.page_start == start
        assert "search" not in dialog._requests
        service.result_ready.emit(token, "search_character_catalog", CharacterCatalogSearchResult(
            "session-a", 720, start, 72, tuple(row(i) for i in range(start, start + 72)), (), ()))
    assert "prefetch" not in dialog._requests
    assert len(dialog._preview.prefetch_rows) == 288
    assert dialog._preview.visible_rows[0].key == "asset:0"
    dialog._page(1)
    assert dialog._preview.visible_rows[0].key == "asset:72"
    token = dialog._requests["prefetch"]
    assert dialog._prefetch_search.page_start == 360
    calls = len(service.calls)
    dialog._page(1)
    assert dialog._preview.visible_rows[0].key == "asset:144"
    assert dialog._requests["prefetch"] == token and token not in service.cancelled
    assert not any(request.startswith("search-") for request, _, _ in service.calls[calls:])
    service.result_ready.emit(token, "search_character_catalog", CharacterCatalogSearchResult(
        "session-a", 720, 360, 72, tuple(row(i) for i in range(360, 432)), (), ()))
    assert dialog._prefetch_search.page_start == 432
    assert len(dialog._search_cache) == 6  # More than the previous four-page cache.
    dialog._search_edit.setText("new filter")
    dialog._search_timer.stop()
    assert "prefetch" not in dialog._requests and not dialog._preview.prefetch_rows


def test_failed_lookahead_page_does_not_stop_later_pages_or_repeat_the_failed_request(finder):
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(i) for i in range(72)], total=720)
    first = dialog._requests["prefetch"]
    before = dialog._status.text()
    service.request_failed.emit(first, "fixture failure")
    assert dialog._prefetch_search.page_start == 144
    pending = dialog._requests["prefetch"]
    dialog._preview.idle.emit()
    assert dialog._requests["prefetch"] == pending
    assert dialog._status.text() == before and dialog._next_button.isEnabled()
    dialog._page(1)
    assert service.calls[-1][1].page_start == 72
    assert "search" in dialog._requests and pending in service.cancelled


def test_next_page_reuses_preloaded_rows_without_replacing_the_current_grid_early(finder):
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(i) for i in range(72)], total=144)
    dialog._preview.page_complete = True
    dialog._preview.idle.emit()
    future = tuple(row(i) for i in range(72, 144))
    service.result_ready.emit(dialog._requests["prefetch"], "search_character_catalog",
        CharacterCatalogSearchResult("session-a", 144, 72, 72, future, (), ()))
    assert dialog._preview.prefetch_rows == future
    assert dialog._preview.visible_rows[0].key == "asset:0"
    searches = sum(token.startswith("search-") for token, _, _ in service.calls)
    cleared = dialog._preview.cleared
    dialog._page(1)
    assert dialog._preview.visible_rows == list(future)
    assert dialog._preview.cleared == cleared
    assert sum(token.startswith("search-") for token, _, _ in service.calls) == searches


def test_obsolete_prefetch_is_cancelled_and_late_results_cannot_warm_a_new_filter(finder):
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(i) for i in range(72)], total=144)
    dialog._preview.page_complete = True
    dialog._preview.idle.emit()
    request = dialog._requests["prefetch"]
    dialog._search_edit.setText("other body")
    dialog._search_timer.stop()
    assert request in service.cancelled
    service.result_ready.emit(request, "search_character_catalog",
        CharacterCatalogSearchResult("session-a", 144, 72, 72, (row(99),), (), ()))
    assert not dialog._preview.prefetch_rows and len(dialog._search_cache) == 1
    dialog._preview.idle.emit()
    assert "prefetch" not in dialog._requests


def test_next_page_retries_a_failed_prefetch_without_disturbing_current_status(finder):
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(i) for i in range(72)], total=144)
    dialog._preview.page_complete = True
    dialog._preview.idle.emit()
    request = dialog._requests["prefetch"]
    before = dialog._status.text()
    service.request_failed.emit(request, "background fixture failure")
    assert dialog._status.text() == before and dialog._next_button.isEnabled()
    dialog._page(1)
    assert dialog._requests["search"] != request
    assert service.calls[-1][1].page_start == 72


@pytest.mark.parametrize("cache_source", ["preview", "warmup"])
def test_selection_uses_prepared_details_without_another_catalogue_request(finder, cache_source):
    dialog, service, _ = finder
    selected = detail(row(1))
    lookup = lambda key, session: selected if (key, session) == (selected.row.key, selected.session_id) else None
    if cache_source == "preview":
        dialog._preview.cached_detail = lookup
    else:
        dialog._warmup = SimpleNamespace(cached_detail=lookup, resume=lambda *_: None)
    publish_rows(dialog, service, [selected.row])
    assert dialog._details is selected and dialog._preview.selected[-1] is selected
    assert not any(token.startswith("detail-") for token, _, _ in service.calls)


def test_revisited_and_shared_thumbnails_reuse_the_same_icon(finder, monkeypatch, tmp_path):
    dialog, service, _ = finder
    path = str(tmp_path / "thumbnail.png")
    pixmap = feature.QPixmap(16, 16)
    pixmap.fill(feature.Qt.GlobalColor.red)
    assert pixmap.save(path)
    original_icon = feature.QIcon
    icon_reads = []
    def icon(source):
        if isinstance(source, str):
            icon_reads.append(source)
        return original_icon(source)
    monkeypatch.setattr(feature, "QIcon", icon)
    rows = [row(1), row(2)]
    publish_rows(dialog, service, rows)
    result = CharacterRenderResult("shared", "package", path, "base_appearance", ())
    dialog._thumbnail_ready("asset:1", result)
    dialog._thumbnail_ready("asset:2", result)
    assert icon_reads == [path]
    first_icon = dialog._grid.item(0).icon().cacheKey()
    assert dialog._grid.item(1).icon().cacheKey() == first_icon
    dialog._populate(CharacterCatalogSearchResult("session-a", 2, 0, 72, tuple(rows), (), ()))
    assert icon_reads == [path]
    assert dialog._grid.item(0).icon().cacheKey() == first_icon
    # A preloaded card outside the current grid shares that icon too.
    dialog._thumbnail_ready("asset:3", result)
    assert icon_reads == [path]


def test_selection_rejects_old_details_and_old_previews(finder):
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(1), row(2)])
    old = dialog._requests["detail"]
    dialog._grid.setCurrentRow(1)
    assert old in service.cancelled
    service.result_ready.emit(old, "get_character_catalog_detail", detail(row(1)))
    assert dialog._details is None
    service.result_ready.emit(dialog._requests["detail"], "get_character_catalog_detail", detail(row(2)))
    assert dialog._details.row.key == "asset:2"
    result = CharacterRenderResult("cache", "C:/cache/package", "", "base_appearance", ())
    dialog._package_ready("asset:1", result)
    assert not dialog._host.loaded
    dialog._package_ready("asset:2", result)
    assert dialog._host.loaded == [result.package_path]
    dialog._package_applied(result.package_path, 1)
    assert dialog._shown_key == "asset:2"
    dialog._grid.setCurrentRow(0)
    dialog._preview_failed("asset:1", "Failed")
    assert "previous preview is still shown" in dialog._preview_status.text()
    assert dialog._host.loaded == [result.package_path]


def test_ownership_navigation_and_exact_scope(finder):
    dialog, service, scopes = finder
    publish_rows(dialog, service, [row(1)])
    appearance = row(2, view="appearances", key="appearance:2")
    service.result_ready.emit(dialog._requests["detail"], "get_character_catalog_detail", detail(row(1), [appearance]))
    dialog._navigate(dialog._relations.item(0))
    dialog._search_timer.stop()
    dialog._search()
    request = service.calls[-1][1]
    assert request.view == "appearances" and request.related_key == "asset:1" and request.query == appearance.path
    publish_rows(dialog, service, [appearance])
    service.result_ready.emit(dialog._requests["detail"], "get_character_catalog_detail", detail(appearance))
    dialog._scope(False)
    assert service.calls[-1][1].include_related is False
    service.result_ready.emit(dialog._requests["scope"], "scope_character_catalog", CharacterCatalogScopeResult("session-a", (3, 4), 2, 2, False))
    assert scopes[0][0] == (3, 4) and dialog._closing


def test_refresh_invalidates_requests_and_actions(finder):
    dialog, service, scopes = finder
    publish_rows(dialog, service, [row(1)])
    pending = dialog._requests["detail"]
    service.session_published.emit(ArchiveSessionHandle("session-b", "C:/game", "new", 10, 3, False))
    assert pending in service.cancelled and dialog._invalid
    assert not dialog._exact.isEnabled() and not dialog._next_button.isEnabled()
    service.result_ready.emit(pending, "get_character_catalog_detail", detail(row(1)))
    assert dialog._details is None and not scopes


@pytest.mark.parametrize("role", ["unclassified", "facial_detail", "hair", "beard"])
def test_related_component_selects_its_explicit_filter(finder, role):
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(1)])
    unknown = row(2, role=role, source_group="2_mon")
    service.result_ready.emit(dialog._requests["detail"], "get_character_catalog_detail", detail(row(1), [unknown]))
    dialog._navigate(dialog._relations.item(0))
    dialog._search_timer.stop()
    dialog._search()
    request = service.calls[-1][1]
    assert request.role == role and request.query == unknown.path
    assert request.source_group is None  # Explicit links can leave the humanoid default.


def test_default_filters_and_tab_switches_request_humanoids_and_heads(finder):
    dialog, service, _ = finder
    assert service.calls[-1][1].source_group == "humanoid"
    dialog._set_filter("role", "body")
    dialog._tabs.setCurrentIndex(1)
    dialog._search_timer.stop()
    dialog._search()
    request = service.calls[-1][1]
    assert request.tab == "faces" and request.role is None and request.source_group == "humanoid"
    assert dialog._filters["role"].currentText() == "Head"
    dialog._set_filter("source_group", "2_mon")
    dialog._set_filter("role", "hair")
    dialog._clear_filters()
    dialog._search_timer.stop()
    dialog._search()
    assert service.calls[-1][1].source_group == "humanoid" and service.calls[-1][1].role is None
    from PySide6.QtWidgets import QPushButton
    next(button for button in dialog.findChildren(QPushButton) if button.text() == "Reset view").click()
    assert dialog._host.canonical_views == 1


@pytest.mark.parametrize("saved, expected", [("", "humanoid"), ("all", ""), ("2_mon", "2_mon")])
def test_legacy_default_migrates_and_explicit_all_types_persists(finder, tmp_path, saved, expected):
    from PySide6.QtCore import QSettings
    dialog, _, _ = finder
    settings = QSettings(str(tmp_path / "finder.ini"), QSettings.Format.IniFormat)
    settings.setValue("ui/character_finder/source_group", saved)
    dialog._settings = settings
    dialog._restore()
    assert dialog._filters["source_group"].currentData() == expected
    dialog._set_filter("source_group", "")
    dialog._save()
    dialog._restore()
    assert dialog._filters["source_group"].currentData() == ""


@pytest.mark.parametrize("include_related", [False, True])
def test_scope_reaches_real_archive_bridge(finder, monkeypatch, include_related):
    from PySide6.QtWidgets import QLabel, QPushButton
    from cdmw.domain.archives.catalogue import ArchiveViewMode
    from cdmw.ui.archive_browser.remote_window_bridge import ArchiveRemoteWindowBridge
    from tests.test_archive_remote_window_bridge import _RemoteExportWindow

    dialog, service, _ = finder
    window = _RemoteExportWindow()
    window.archive_clear_asset_scope_button = QPushButton()
    window.archive_scope_banner_label = QLabel()
    bridge = ArchiveRemoteWindowBridge(window)
    bridge.controller._current_session = dialog._bridge.current_session
    queries = []
    monkeypatch.setattr(bridge, "_begin_pending", lambda *a, **kw: None)
    monkeypatch.setattr(bridge.controller, "apply_query", lambda query, **kw: queries.append(query) or 9)
    dialog._bridge.apply_entry_id_scope = bridge.apply_entry_id_scope
    publish_rows(dialog, service, [row(1)])
    service.result_ready.emit(dialog._requests["detail"], "get_character_catalog_detail", detail(row(1)))
    dialog._scope(include_related)
    assert service.calls[-1][1].include_related is include_related
    ids = (3, 4, 7) if include_related else (3,)
    service.result_ready.emit(dialog._requests["scope"], "scope_character_catalog",
                              CharacterCatalogScopeResult("session-a", ids, len(ids), len(ids), False))
    assert len(queries) == 1
    assert queries[0].session_id == "session-a" and queries[0].entry_ids == ids
    assert queries[0].view_mode is ArchiveViewMode.FLAT
    assert bridge._item_scope_entry_ids == ids and dialog._closing


def test_whole_page_is_queued_with_visible_cards_first_and_late_thumbnails_ignored(finder, tmp_path):
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(i) for i in range(72)])
    # Publication itself must enqueue the page; no scroll or timer is required.
    assert len(dialog._preview.visible_rows) == 72
    _APPLICATION.processEvents()
    dialog._visible()
    assert len(dialog._preview.visible_rows) == 72
    dialog._grid.scrollToBottom()
    _APPLICATION.processEvents()
    dialog._visible()
    assert dialog._preview.visible_rows[0].key != "asset:0"
    assert {r.key for r in dialog._preview.visible_rows} == {f"asset:{i}" for i in range(72)}
    dialog._shutdown()
    dialog._thumbnail_ready("asset:1", CharacterRenderResult("cache", "package", str(tmp_path / "late.png"), "base_appearance", ()))
    assert "asset:1" not in dialog._thumbs


def test_archive_controls_wire_finder_in_classic_and_compact_layouts(monkeypatch):
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    import gc
    from cdmw.ui.archive_browser.controls_panel import ArchiveControlsPanelMixin
    from cdmw.ui.archive_browser.asset_catalog_dialog import ArchiveAssetCatalogDialogMixin
    from cdmw.ui.archive_browser.command_strip import build_archive_command_strip
    from cdmw.ui.archive_browser.edited_results import ArchiveEditedResultsMixin
    from cdmw.constants import DEFAULT_UI_THEME

    class Window(ArchiveControlsPanelMixin, ArchiveAssetCatalogDialogMixin, ArchiveEditedResultsMixin, QWidget):
        def _build_archive_location_controls(self): pass
        def _open_archive_extension_picker(self): pass
        def _canonicalize_archive_extension_filter_control(self): pass
        def _rebuild_archive_extension_filter_choices(self, *_): pass

    window = Window()
    window.archive = window
    window.shell = SimpleNamespace(_archive_controls_sidebar_bounds=lambda: (290, 360, 520),
                                   current_theme_key=DEFAULT_UI_THEME)
    window.textures = SimpleNamespace(_add_combo_choice=lambda combo, label, value: combo.addItem(label, value))
    window.archive_splitter = QSplitter(window)
    window.archive_catalogue_service = SimpleNamespace(character_catalog_available=False)
    messages = []
    monkeypatch.setattr(feature.QMessageBox, "information", lambda *args: messages.append(args[2]))
    window._build_archive_controls_panel(lambda *_: None)
    button = window.archive_character_finder_button
    assert button.text() == "Body && Face Finder" and button.shortcut().isEmpty()
    assert not button.isEnabled() and button.parentWidget() is window.archive_asset_catalog_button.parentWidget()
    button.setEnabled(True)
    button.click()
    assert len(messages) == 1 and "updated archive helper" in messages[0]
    root = QWidget(window)
    QVBoxLayout(root)
    automatic_gc = gc.isenabled()
    build_archive_command_strip(window, root)
    assert gc.isenabled() == automatic_gc
    gc.collect()
    strip = root._cdmw_compact_archive_command_strip
    assert strip.layout().indexOf(button) == strip.layout().indexOf(window.archive_asset_catalog_button) + 1
    button.click()
    assert len(messages) == 2
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QFrame
    filters_button = root._cdmw_compact_archive_more_filters_button
    filters_popup = filters_button.findChild(QFrame, "CompactArchiveFiltersMenu")
    assert filters_popup.windowType() == Qt.WindowType.Popup
    assert window.archive_filters_group.parentWidget() is filters_popup
    filters_button.click()
    _APPLICATION.processEvents()
    assert window.archive_filters_group.isVisible()
    window.archive_package_filter_edit.setText("0012")
    QTest.keyClick(window.archive_package_filter_edit, Qt.Key.Key_Escape)
    assert not filters_popup.isVisible()
    filters_button.click()
    _APPLICATION.processEvents()
    assert window.archive_package_filter_edit.text() == "0012"
    role_combo = window.archive_role_filter_combo
    role_combo.showPopup()
    _APPLICATION.processEvents()
    assert filters_popup.isVisible()
    QTest.keyClick(role_combo.view(), Qt.Key.Key_Escape)
    _APPLICATION.processEvents()
    assert not role_combo.view().isVisible()
    assert filters_popup.isVisible()
    filters_button.click()
    assert not filters_popup.isVisible()
    window.resize(1200, 800)
    window.show()
    filters_button.click()
    _APPLICATION.processEvents()
    QTest.mouseClick(window.windowHandle(), Qt.MouseButton.LeftButton, pos=window.rect().bottomRight())
    _APPLICATION.processEvents()
    assert not filters_popup.isVisible()
    window.deleteLater()
    _APPLICATION.processEvents()


def test_finder_cards_and_filters_translate_without_changing_ids(finder, tmp_path):
    from cdmw.ui.localization import UiLocalizer
    dialog, service, _ = finder
    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code="fr")
    localizer.register_root(dialog)
    publish_rows(dialog, service, [row(1, role="facial_detail", preview_status="unresolved_model", model_count=0), row(2)])
    localizer.apply_registered_roots()
    assert dialog._grid.item(0).data(feature.Qt.ItemDataRole.UserRole) == "asset:1"
    assert "Détail du visage" in dialog._grid.item(0).text()
    assert "Modèle non résolu" in dialog._grid.item(0).text()
    assert dialog._filters["source_group"].currentData() == "humanoid"
    assert "Humanoïdes" in dialog._filters["source_group"].currentText()
    assert dialog._view.currentData() == "assets"
    assert "En attente" in dialog._items["asset:2"].text()
    dialog._preview.progress.emit("asset:2", "preparing_files", 1, 3)
    localizer.apply_registered_roots()
    assert "Préparation des fichiers du modèle…" in dialog._items["asset:2"].text()
    assert "1/3" in dialog._items["asset:2"].text()
    dialog._thumbnail_ready("asset:2", CharacterRenderResult("cache", "package", "thumbnail.png", "textures_unavailable", ()))
    localizer.apply_registered_roots()
    assert "Textures indisponibles" in dialog._items["asset:2"].text()
    localizer.load_language("en")
    localizer.apply_registered_roots()
    localizer.shutdown()


class ExportPreparation(QObject):
    ready = Signal(int, object)
    failed = Signal(int, str)
    progress = Signal(int, str, int, int)
    instances = []

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.started = []
        self.cancelled = 0
        ExportPreparation.instances.append(self)

    def start(self, detail, token): self.started.append((detail, token))
    def cancel(self): self.cancelled += 1


def _export_selection(finder, monkeypatch, tmp_path):
    from cdmw.domain.archives.character_catalogue import CharacterCatalogComponent
    from cdmw.models import ArchiveEntry
    dialog, service, _ = finder
    ExportPreparation.instances.clear()
    monkeypatch.setattr("cdmw.ui.character_finder.preview_preparation.CharacterPreviewPreparation", ExportPreparation)
    monkeypatch.setattr(feature.QFileDialog, "getExistingDirectory", lambda *_args: str(tmp_path / "out"))
    # Kliff's alternate head: the default head's PAC bound through its own prefab.
    head = ArchiveEntry("character/model/1_pc/1_phm/head/head/cd_phm_00_head_00_0001_macduff.pac", Path("0.pamt"), Path("0.paz"), 0, 1, 1, 0, 0)
    prefab = ArchiveEntry("character/prefab/1_pc/01_phm/head/head/cd_phm_00_head_00_0008_macduff.prefabdata_xml", Path("0.pamt"), Path("0.paz"), 1, 1, 1, 0, 0)
    selected = row(1, role="head", key="appearance:1", view="appearances")
    component = CharacterCatalogComponent("head", "cd_phm_00_head_00_0008_macduff", (1,), (2,), 0.92, {}, "resolved")
    chosen = replace(detail(selected), models=(SimpleNamespace(entry_id=1, path=head.path),), components=(component,))
    publish_rows(dialog, service, [selected])
    service.result_ready.emit(dialog._requests["detail"], "get_character_catalog_detail", chosen)
    return dialog, chosen, head, prefab


def _wait_for_export(dialog, shown, timeout=5.0):
    """The export runs on a worker thread; a fixed number of event spins can end before it does."""
    import time
    deadline = time.monotonic() + timeout
    while not (dialog._export_thread is None and shown) and time.monotonic() < deadline:
        _APPLICATION.processEvents()
        time.sleep(0.005)


def test_export_fbx_gives_each_model_its_components_prefab(finder, monkeypatch, tmp_path):
    from cdmw.domain.archives.mesh_contracts import MeshExportResult
    from cdmw.domain.character_finder import CharacterPreviewInputs
    dialog, chosen, head, prefab = _export_selection(finder, monkeypatch, tmp_path)
    exported, shown = [], []

    def export(entry, output_dir, export_format, **kwargs):
        exported.append((entry, Path(output_dir), export_format, kwargs["authored_descriptor"]))
        return MeshExportResult([Path(output_dir) / "head.fbx"], [
            f"Appearance prefab: {prefab.path}", "Vertices: 3",
            "Applied character skeleton variation cd_phm_macduff_head_0008.pabc (207/207 records matched the PAB)."])

    monkeypatch.setattr("cdmw.core.archive_mesh_export.export_archive_mesh", export)
    monkeypatch.setattr(feature.QMessageBox, "information", lambda _parent, _title, text: shown.append(text))
    assert dialog._export.isEnabled()
    dialog._export.click()
    preparation = ExportPreparation.instances[-1]
    assert preparation.started[0][1] == dialog._export_token and not dialog._export.isEnabled()
    preparation.ready.emit(dialog._export_token, CharacterPreviewInputs(chosen, {1: head, 2: prefab}, (head, prefab), True))
    _wait_for_export(dialog, shown)
    assert exported == [(head, tmp_path / "out", "fbx", prefab)]
    assert "Exported 1 of 1 models" in shown[0] and "cd_phm_macduff_head_0008.pabc" in shown[0]
    assert "Vertices" not in shown[0] and dialog._export.isEnabled()


def test_export_fbx_refuses_a_bounded_selection_and_stale_preparation(finder, monkeypatch, tmp_path):
    from cdmw.domain.character_finder import CharacterPreviewInputs
    dialog, chosen, head, prefab = _export_selection(finder, monkeypatch, tmp_path)
    monkeypatch.setattr("cdmw.core.archive_mesh_export.export_archive_mesh", lambda *_a, **_k: pytest.fail("exported"))
    dialog._export.click()
    preparation = ExportPreparation.instances[-1]
    # A late result of an earlier preparation must not consume the current one.
    preparation.ready.emit(dialog._export_token - 1, CharacterPreviewInputs(chosen, {1: head}, (head,), True))
    assert dialog._export_thread is None and dialog._export_pending is not None
    preparation.ready.emit(dialog._export_token, CharacterPreviewInputs(chosen, {1: head, 2: prefab}, (head, prefab), False))
    assert dialog._export_thread is None and "complete file set" in dialog._status.text()
    assert dialog._export.isEnabled()
    dialog._export.click()
    dialog.close()
    assert preparation.cancelled >= 1 and dialog._export_pending is None


class LookPreparation(QObject):
    ready = Signal(int, object, object)
    failed = Signal(int, str)
    progress = Signal(int, str)
    instances = []

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.started = []
        self.cancelled = 0
        LookPreparation.instances.append(self)

    def start(self, session_id, look, token): self.started.append((session_id, look, token))
    def cancel(self): self.cancelled += 1


def _creator_folder(tmp_path, version="9.1.16 1138693 281B6192"):
    folder = tmp_path / "CharacterCreator"
    folder.mkdir(exist_ok=True)
    (folder / "data.version").write_text(version, encoding="utf-8")
    (folder / "menu.txt").write_text(
        "mesh 1 201 phm 1 - cd_phm_00_head_00_0008_macduff 201 202\n"
        "base 0 0 x cd_phm_00_nude_01_0002_macduff 1.02571 cd_phm_00_head_00_0001_macduff 0.92 cd_phm_00_hair_00_0022_player\n",
        encoding="utf-8")
    (folder / "profile.txt").write_text("mesh 1 201\n", encoding="utf-8")
    return folder


def test_kliff_look_action_needs_the_character_creator_folder(finder, tmp_path):
    dialog, _service, _ = finder
    assert dialog._creator_folder is None and not dialog._kliff_look.isEnabled()
    dialog._creator_folder = _creator_folder(tmp_path)
    dialog._buttons()
    assert dialog._kliff_look.isEnabled()


def test_kliff_look_refuses_an_unknown_character_creator_version(finder, monkeypatch, tmp_path):
    dialog, _service, _ = finder
    LookPreparation.instances.clear()
    monkeypatch.setattr("cdmw.ui.character_finder.creator_look.KliffLookPreparation", LookPreparation)
    monkeypatch.setattr(feature.QFileDialog, "getExistingDirectory", lambda *_args: pytest.fail("asked for a folder"))
    warnings = []
    monkeypatch.setattr(feature.QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text))
    dialog._creator_folder = _creator_folder(tmp_path, "9.2.0 1 2")
    dialog._buttons()
    dialog._kliff_look.click()
    assert "Character Creator 9.2.0 is not supported yet" in warnings[0] and "9.1.16" in warnings[0]
    assert not LookPreparation.instances and dialog._export_pending is None


def test_kliff_look_exports_each_part_through_its_own_prefab(finder, monkeypatch, tmp_path):
    from cdmw.domain.archives.catalogue import ArchiveDurableIdentity, ArchiveEntryDto, ArchiveEntryRole
    from cdmw.domain.archives.mesh_contracts import MeshExportResult
    from cdmw.domain.character_creator import CharacterCreatorResolvedPart, kliff_look_detail
    from cdmw.domain.character_finder import CharacterPreviewInputs
    from cdmw.models import ArchiveEntry
    dialog, _service, _ = finder
    LookPreparation.instances.clear()
    ExportPreparation.instances.clear()
    monkeypatch.setattr("cdmw.ui.character_finder.creator_look.KliffLookPreparation", LookPreparation)
    monkeypatch.setattr("cdmw.ui.character_finder.preview_preparation.CharacterPreviewPreparation", ExportPreparation)
    monkeypatch.setattr(feature.QFileDialog, "getExistingDirectory", lambda *_args: str(tmp_path / "out"))
    shown, exported = [], []
    monkeypatch.setattr(feature.QMessageBox, "information", lambda _parent, _title, text: shown.append(text))
    dialog._creator_folder = _creator_folder(tmp_path)
    dialog._buttons()
    dialog._kliff_look.click()
    look_preparation = LookPreparation.instances[-1]
    session_id, look, token = look_preparation.started[0]
    assert session_id == "session-a" and token == dialog._export_token
    assert [part.prefab for part in look.parts] == [
        "cd_phm_00_nude_01_0002_macduff", "cd_phm_00_head_00_0008_macduff", "cd_phm_00_hair_00_0022_player"]
    assert not dialog._kliff_look.isEnabled() and not dialog._export.isEnabled()

    def dto(entry_id, path):
        return ArchiveEntryDto("session-a", entry_id, ArchiveDurableIdentity(path, "0.pamt", 0, entry_id), path,
            "0.pamt", "0.paz", 0, entry_id, 1, 1, 0, "." + path.rsplit(".", 1)[-1], "0009", ArchiveEntryRole.MODEL, "model", True)

    head_pac = "character/model/1_pc/1_phm/head/head/cd_phm_00_head_00_0001_macduff.pac"
    descriptor_path = "character/prefab/1_pc/01_phm/head/head/cd_phm_00_head_00_0008_macduff.prefabdata_xml"
    hair_pac = "character/model/1_pc/1_phm/head/hair/cd_phm_00_hair_00_0022_player.pac"
    head_part, hair_part = look.parts[1], look.parts[2]
    detail = kliff_look_detail("session-a", (
        CharacterCreatorResolvedPart(head_part, dto(1, "a/cd_phm_00_head_00_0008_macduff.prefab"),
                                     dto(2, descriptor_path), (dto(4, head_pac),), ()),
        CharacterCreatorResolvedPart(hair_part, dto(3, "a/cd_phm_00_hair_00_0022_player.prefab"), None,
                                     (dto(7, hair_pac),), ()),
    ))
    look_preparation.ready.emit(token, detail, ("cd_phm_00_nude_01_0002_macduff.prefab is not in the loaded archives; that part is skipped.",))
    export_preparation = ExportPreparation.instances[-1]
    assert export_preparation.started == [(detail, token)]

    def entry(path, offset):
        return ArchiveEntry(path, Path("0.pamt"), Path("0.paz"), offset, 1, 1, 0, 0)

    head, descriptor, hair = entry(head_pac, 4), entry(descriptor_path, 2), entry(hair_pac, 7)

    def export(entry, output_dir, export_format, **kwargs):
        exported.append((entry.path, kwargs["authored_descriptor"]))
        return MeshExportResult([Path(output_dir) / (Path(entry.path).stem + ".fbx")], [
            *((f"Appearance prefab: {descriptor_path}",) if kwargs["authored_descriptor"] is not None else ()),
            "Vertices: 3"])

    monkeypatch.setattr("cdmw.core.archive_mesh_export.export_archive_mesh", export)
    export_preparation.ready.emit(token, CharacterPreviewInputs(detail, {4: head, 2: descriptor, 7: hair},
                                                                (head, descriptor, hair), True))
    _wait_for_export(dialog, shown)
    assert exported == [(head_pac, descriptor), (hair_pac, None)]
    text = shown[0]
    assert "Exported 2 of 2 models" in text
    assert "<b>Head</b>: cd_phm_00_head_00_0008_macduff<br>FBX written for cd_phm_00_head_00_0001_macduff.pac" in text
    assert f"Appearance prefab: {descriptor_path}" in text and "Vertices" not in text
    assert "<b>Hair</b>: cd_phm_00_hair_00_0022_player" in text
    assert "Head scale 0.92; not applied to the FBX files." in text and "cd_phm_00_nude_01_0002_macduff.prefab is not in the loaded archives" in text
    assert dialog._look_export is None and dialog._kliff_look.isEnabled()
