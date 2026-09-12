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
    idle = Signal()
    busy = False
    _thread = None
    _worker = None

    def __init__(self, *a, parent=None, **kw):
        super().__init__(parent)
        self.selected = []
        self.visible_rows = []

    def select(self, detail, generation): self.selected.append(detail)
    def visible(self, rows, **kw): self.visible_rows = rows
    def clear_page(self): pass
    def shutdown(self): pass


class Host(QWidget):
    package_applied = Signal(str, int)
    package_failed = Signal(str, int, str)

    def __init__(self, parent=None, **kw):
        super().__init__(parent)
        self.controller = self
        self.loaded = []

    def load_package(self, path, **kw):
        self.loaded.append(path)
        return True

    def reset_view(self): pass
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


def publish_rows(dialog, service, rows):
    service.result_ready.emit(dialog._requests["search"], "search_character_catalog",
        CharacterCatalogSearchResult("session-a", len(rows), 0, 72, tuple(rows), (), ()))


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


def test_related_unclassified_model_selects_its_explicit_filter(finder):
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(1)])
    unknown = row(2, role="unclassified")
    service.result_ready.emit(dialog._requests["detail"], "get_character_catalog_detail", detail(row(1), [unknown]))
    dialog._navigate(dialog._relations.item(0))
    dialog._search_timer.stop()
    dialog._search()
    request = service.calls[-1][1]
    assert request.role == "unclassified" and request.query == unknown.path


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
    bridge = ArchiveRemoteWindowBridge(window, display_v2=True, shadow=False)
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


def test_only_visible_cards_are_queued_and_late_thumbnails_are_ignored(finder, tmp_path):
    dialog, service, _ = finder
    publish_rows(dialog, service, [row(i) for i in range(72)])
    _APPLICATION.processEvents()
    dialog._visible()
    assert 0 < len(dialog._preview.visible_rows) < 72
    dialog._shutdown()
    dialog._thumbnail_ready("asset:1", CharacterRenderResult("cache", "package", str(tmp_path / "late.png"), "base_appearance", ()))
    assert "asset:1" not in dialog._thumbs


def test_archive_controls_wire_finder_in_classic_and_compact_layouts(monkeypatch):
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    from cdmw.ui.archive_browser.controls_panel import ArchiveControlsPanelMixin
    from cdmw.ui.archive_browser.asset_catalog_dialog import ArchiveAssetCatalogDialogMixin
    from cdmw.ui.archive_browser.command_strip import build_archive_command_strip
    from cdmw.constants import DEFAULT_UI_THEME

    class Window(ArchiveControlsPanelMixin, ArchiveAssetCatalogDialogMixin, QWidget):
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
    assert not button.isEnabled() and button.parentWidget() is window.archive_asset_catalog_button.parentWidget()
    button.setEnabled(True)
    button.click()
    assert len(messages) == 1 and "updated archive helper" in messages[0]
    root = QWidget(window)
    QVBoxLayout(root)
    build_archive_command_strip(window, root)
    strip = root._cdmw_compact_archive_command_strip
    assert strip.layout().indexOf(button) == strip.layout().indexOf(window.archive_asset_catalog_button) + 1
    button.click()
    assert len(messages) == 2
    window.deleteLater()
    _APPLICATION.processEvents()


def test_finder_cards_and_filters_translate_without_changing_ids(finder, tmp_path):
    from cdmw.ui.localization import UiLocalizer
    dialog, service, _ = finder
    localizer = UiLocalizer(language_dir=tmp_path / "languages", language_code="fr")
    localizer.register_root(dialog)
    publish_rows(dialog, service, [row(1, role="facial_detail", preview_status="unresolved_model")])
    localizer.apply_registered_roots()
    assert dialog._grid.item(0).data(feature.Qt.ItemDataRole.UserRole) == "asset:1"
    assert "Détail du visage" in dialog._grid.item(0).text()
    assert "Modèle non résolu" in dialog._grid.item(0).text()
    assert dialog._view.currentData() == "assets"
    dialog._thumbnail_ready("asset:1", CharacterRenderResult("cache", "package", "thumbnail.png", "textures_unavailable", ()))
    localizer.apply_registered_roots()
    assert "Textures indisponibles" in dialog._grid.item(0).text()
    localizer.load_language("en")
    localizer.apply_registered_roots()
    localizer.shutdown()
