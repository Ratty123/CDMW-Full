from __future__ import annotations

import os
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from cdmw.domain.archives.item_catalogue import (
    ItemCatalogCategoryFacet,
    ItemCatalogRow,
    ItemCatalogScopeResult,
    ItemCatalogSearchResult,
)
from cdmw.ui.archive_browser.remote_finder_dialog import RemoteArchiveFinderDialog
from cdmw.domain.archives.catalogue_operations import ArchiveBackendError


_APPLICATION: QApplication | None = None


def _app() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def _drain() -> None:
    for _ in range(8):
        _app().processEvents()


class _Service(QObject):
    result_ready = Signal(str, str, object)
    request_failed = Signal(str, object)
    request_cancelled = Signal(str)
    progress = Signal(str, object)

    def __init__(self) -> None:
        super().__init__()
        self.searches: list[object] = []
        self.scopes: list[object] = []
        self.icons: list[object] = []
        self.cancelled: list[str] = []
        self.retried: list[str] = []

    def search_item_catalog(self, request: object, **_kwargs: object) -> str:
        self.searches.append(request)
        return f"search-{len(self.searches)}"

    def scope_item_catalog(self, request: object, **_kwargs: object) -> str:
        self.scopes.append(request)
        return f"scope-{len(self.scopes)}"

    def load_item_icons(self, request: object, **_kwargs: object) -> str:
        self.icons.append(request)
        return f"icons-{len(self.icons)}"

    def cancel(self, request_id: str) -> bool:
        self.cancelled.append(request_id)
        return True

    def retry_failed(self, request_id: str) -> str:
        self.retried.append(request_id)
        return "retry-" + request_id


class _Controller:
    generation = 4


class _Bridge:
    def __init__(self) -> None:
        self.current_session = ArchiveSessionHandle("session-a", "C:/Game", "fingerprint-a", 20, 3, True)
        self.controller = _Controller()
        self.scopes: list[tuple[tuple[int, ...], str, tuple[str, ...]]] = []

    def apply_entry_id_scope(
        self,
        entry_ids: object,
        *,
        label: str,
        preferred_prefab_stems: object = (),
    ) -> bool:
        self.scopes.append((tuple(entry_ids), label, tuple(preferred_prefab_stems)))
        return True


class _Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.shell = self
        self.archive = self
        self.textures = self
        self.archive_catalogue_service = _Service()
        self.archive_remote_bridge = _Bridge()


class _Warmup(QObject):
    iconsReady = Signal(str, object)
    iconsFailed = Signal(str, object)

    def __init__(self, result: ItemCatalogSearchResult, image: QImage) -> None:
        super().__init__()
        self.result = result
        self.image = image

    def cached_search(self, _request: object) -> ItemCatalogSearchResult:
        return self.result

    def cached_icons(self, _session_id: str, item_ids: object) -> dict[int, tuple[str, QImage]]:
        return {
            int(item_id): ("C:/cache/item.png", self.image)
            for item_id in item_ids
            if int(item_id) == 5
        }

    def prioritize_icons(self, _session_id: str, item_ids: object) -> tuple[int, ...]:
        return tuple(int(item_id) for item_id in item_ids)


def _row(item_id: int) -> ItemCatalogRow:
    return ItemCatalogRow(
        item_id,
        f"item_{item_id}",
        f"Item {item_id}",
        "Weapon",
        "Sword",
        "Recovered item/model naming",
        (f"equipment/weapon/item_{item_id}.pac",),
        (f"item_{item_id}",),
        (),
        (),
        1,
        "model link",
    )


def test_finder_scope_failure_keeps_typed_report_and_retries_the_scope_only() -> None:
    _app()
    window = _Window()
    dialog = RemoteArchiveFinderDialog(window)
    _drain()
    window.archive_catalogue_service.result_ready.emit("search-1", "search_item_catalog",
        ItemCatalogSearchResult("session-a", 1, 0, 72, (_row(12),), ()))
    dialog._tree.setCurrentRow(0)
    dialog._scope_selected(include_related=True)
    service = window.archive_catalogue_service
    service.request_failed.emit("scope-1", ArchiveBackendError("permission_denied", "Access denied", "Exact scope detail"))
    assert not dialog._failure_panel.isHidden()
    assert "permission_denied" in dialog._failure_panel.report and "Exact scope detail" in dialog._failure_panel.report
    dialog._failure_panel.copy_button.click()
    assert QApplication.clipboard().text() == dialog._failure_panel.report
    dialog._failure_panel.retry_button.click()
    assert service.retried == ["scope-1"] and len(service.searches) == 1
    assert dialog._scope_request_id == "retry-scope-1"
    service.result_ready.emit("retry-scope-1", "scope_item_catalog", ItemCatalogScopeResult("session-a", (), 0, 0, False))
    assert dialog._failure_panel.isHidden()
    dialog.close()


def test_new_finder_search_invalidates_failed_retry_and_late_errors() -> None:
    _app()
    window = _Window()
    dialog = RemoteArchiveFinderDialog(window)
    _drain()
    service = window.archive_catalogue_service
    service.request_failed.emit("search-1", ArchiveBackendError("invalid_archive", "Invalid input"))
    dialog._search_edit.setText("new search")
    dialog._start_search()
    assert "search-1" in service.cancelled and dialog._failed_request is None
    assert dialog._failure_panel.isHidden()
    service.request_failed.emit("search-1", ArchiveBackendError("unknown", "late"))
    assert dialog._failure_panel.isHidden()
    dialog.close()


def test_selecting_an_item_shows_its_equip_slot_and_description() -> None:
    _app()
    window = _Window()
    dialog = RemoteArchiveFinderDialog(window)
    _drain()
    armour = replace(
        _row(11),
        display_name="Abyssal Dragon Armor",
        equip_type="DragonArmor",
        description="A dragon armor that can be equipped on Blackstar.",
    )
    window.archive_catalogue_service.result_ready.emit(
        "search-1",
        "search_item_catalog",
        ItemCatalogSearchResult("session-a", 1, 0, 72, (armour,), ()),
    )
    _drain()
    dialog._tree.topLevelItem(0).setSelected(True)
    _drain()

    assert "DragonArmor" in dialog._detail_stats.text()
    assert dialog._detail_description.text() == "A dragon armor that can be equipped on Blackstar."
    dialog.close()


def test_an_item_with_no_equip_slot_says_so_rather_than_showing_nothing() -> None:
    _app()
    window = _Window()
    dialog = RemoteArchiveFinderDialog(window)
    _drain()
    window.archive_catalogue_service.result_ready.emit(
        "search-1",
        "search_item_catalog",
        ItemCatalogSearchResult("session-a", 1, 0, 72, (_row(12),), ()),
    )
    _drain()
    dialog._tree.topLevelItem(0).setSelected(True)
    _drain()

    assert "equip slot" in dialog._detail_stats.text().lower()
    assert dialog._detail_description.text() == "None"
    dialog.close()


def test_full_item_finder_loads_immediately_and_pages_server_side() -> None:
    _app()
    window = _Window()
    dialog = RemoteArchiveFinderDialog(window)
    assert dialog.windowTitle() == "Item Finder"
    assert not hasattr(dialog, "_material_only")
    # Material classification was never consistent enough to filter or sort on.
    assert not hasattr(dialog, "_material_combo")
    assert not hasattr(dialog, "_detail_materials")
    assert not hasattr(dialog, "_all_button")
    assert dialog._status.text() == "Loading catalogue..."
    _drain()
    assert len(window.archive_catalogue_service.searches) == 1
    request = window.archive_catalogue_service.searches[-1]
    assert request.page_size == 72

    result = ItemCatalogSearchResult(
        "session-a",
        80,
        0,
        72,
        (_row(1), _row(2)),
        (ItemCatalogCategoryFacet("Weapon", "Sword", 80),),
    )
    window.archive_catalogue_service.result_ready.emit("search-1", "search_item_catalog", result)
    _drain()
    assert dialog._tree.topLevelItemCount() == 2
    assert dialog._next_button.isEnabled()
    assert "of 80" in dialog._status.text()
    dialog.close()


def test_full_item_finder_uses_startup_page_and_icon_cache_without_first_open_requests() -> None:
    _app()
    window = _Window()
    row = replace(_row(5), icon_paths=("ui/icon/item_5.dds",))
    result = ItemCatalogSearchResult("session-a", 1, 0, 72, (row,), ())
    image = QImage(16, 16, QImage.Format_ARGB32)
    image.fill(0xFFFF0000)
    window.archive_item_finder_warmup_controller = _Warmup(result, image)

    dialog = RemoteArchiveFinderDialog(window)
    _drain()

    assert window.archive_catalogue_service.searches == []
    assert window.archive_catalogue_service.icons == []
    assert dialog._item_grid.count() == 1
    assert not dialog._item_grid.item(0).icon().isNull()
    assert "of 1" in dialog._status.text()
    dialog.close()

def test_full_finder_search_is_latest_wins_and_scope_uses_entry_ids() -> None:
    _app()
    window = _Window()
    dialog = RemoteArchiveFinderDialog(window)
    _drain()
    dialog._start_search()
    assert window.archive_catalogue_service.cancelled == ["search-1"]
    window.archive_catalogue_service.result_ready.emit(
        "search-2",
        "search_item_catalog",
        ItemCatalogSearchResult("session-a", 1, 0, 72, (_row(7),), ()),
    )
    _drain()
    dialog._tree.topLevelItem(0).setSelected(True)
    dialog._scope_selected(include_related=True)
    assert window.archive_catalogue_service.scopes[-1].item_ids == (7,)
    window.archive_catalogue_service.result_ready.emit(
        "scope-1",
        "scope_item_catalog",
        ItemCatalogScopeResult("session-a", (3, 8), 1, 1, False),
    )
    _drain()
    assert window.archive_remote_bridge.scopes == [
        ((3, 8), "Item Finder: Item 7", ("item_7",))
    ]
    dialog.close()


def test_full_finder_double_click_uses_exact_item_scope_for_preview() -> None:
    _app()
    window = _Window()
    dialog = RemoteArchiveFinderDialog(window)
    _drain()
    window.archive_catalogue_service.result_ready.emit(
        "search-1",
        "search_item_catalog",
        ItemCatalogSearchResult("session-a", 1, 0, 72, (_row(9),), ()),
    )
    _drain()
    item = dialog._tree.topLevelItem(0)
    dialog._tree.setCurrentItem(item)
    item.setSelected(True)

    dialog._tree.itemDoubleClicked.emit(item)

    assert window.archive_catalogue_service.scopes[-1].item_ids == (9,)
    assert not window.archive_catalogue_service.scopes[-1].include_related
    dialog.close()


def test_clear_drops_the_saved_filter_before_it_searches_again() -> None:
    """Clear used to reset the controls and search with the old filter anyway.

    The saved category/group live in `_preferred_*` until the first facet
    response replaces them with a category-list selection. `_selected_filters` prefers
    them, so pressing Clear before the facets arrived showed "All" in every control
    over results that were still restricted by the filter the dialog opened with.
    """

    _app()
    window = _Window()
    dialog = RemoteArchiveFinderDialog(window)
    _drain()
    dialog._preferred_category = "Weapon"
    dialog._preferred_group = "Sword"

    assert dialog._selected_filters() == ("Weapon", "Sword")

    dialog._clear_filters()
    _drain()

    assert dialog._selected_filters() == (None, None)
    assert window.archive_catalogue_service.searches[-1].category is None
    assert window.archive_catalogue_service.searches[-1].group is None
    dialog.close()


def test_category_list_is_on_the_left_and_filters_categories_or_groups() -> None:
    _app()
    window = _Window()
    dialog = RemoteArchiveFinderDialog(window)
    _drain()
    service = window.archive_catalogue_service
    categories = (ItemCatalogCategoryFacet("Weapon", "Sword", 80),
                  ItemCatalogCategoryFacet("Weapon", "Shield", 5),
                  ItemCatalogCategoryFacet("Armor", "Head", 4))
    service.result_ready.emit("search-1", "search_item_catalog",
        ItemCatalogSearchResult("session-a", 89, 0, 72, (_row(9),), categories))
    dialog.resize(940, 640)
    dialog.show()
    _drain()
    tree = dialog._category_tree
    panel = dialog._item_splitter.widget(0)
    browse_panel = dialog._item_splitter.widget(1)
    detail_panel = dialog._item_splitter.widget(2)
    assert panel.objectName() == "ItemFinderCategoryPanel" and panel.isAncestorOf(tree)
    assert browse_panel.objectName() == "ItemFinderBrowsePanel" and browse_panel.isAncestorOf(dialog._item_grid)
    assert detail_panel.objectName() == "ItemFinderDetailPanel"
    assert panel.width() >= 230 and panel.x() < browse_panel.x() < detail_panel.x()
    assert tree.textElideMode() == Qt.ElideNone
    assert tree.topLevelItem(0).text(1) == "89"
    weapon = tree.topLevelItem(1)
    assert weapon.text(0) == "Weapon" and weapon.text(1) == "85" and weapon.isExpanded()
    shield = weapon.child(1)
    assert shield.text(0) == "Shield" and shield.text(1) == "5"
    assert shield.toolTip(0) == "Weapon / Shield"
    dialog._page_start = 72
    tree.setCurrentItem(shield)
    assert dialog._search_timer.isActive() and dialog._page_start == 0
    dialog._search_timer.stop()
    dialog._start_search()
    assert (service.searches[-1].category, service.searches[-1].group) == ("Weapon", "Shield")
    assert service.searches[-1].page_start == 0
    tree.setCurrentItem(weapon)
    dialog._search_timer.stop()
    dialog._start_search()
    assert (service.searches[-1].category, service.searches[-1].group) == ("Weapon", None)
    dialog._clear_filters()
    assert dialog._selected_filters() == (None, None)
    assert service.searches[-1].category is None and service.searches[-1].group is None
    dialog.close()


@pytest.mark.parametrize(
    ("saved_sizes", "expected_sizes"),
    [([700, 330], [246, 454, 330]), ([700, 330, 280], [280, 700, 330])],
)
def test_saved_category_and_pane_widths_restore_into_the_category_list(saved_sizes, expected_sizes) -> None:
    from cdmw.services.settings_service import create_settings
    import tempfile
    from pathlib import Path

    _app()
    with tempfile.TemporaryDirectory() as directory:
        window = _Window()
        window.settings = create_settings(settings_file_path=Path(directory) / "finder.cfg")
        window.settings.setValue("ui/item_finder_category", "Weapon")
        window.settings.setValue("ui/item_finder_group", "Shield")
        window.settings.setValue("ui/item_finder_splitter_sizes", saved_sizes)
        dialog = RemoteArchiveFinderDialog(window)
        _drain()
        service = window.archive_catalogue_service
        assert (service.searches[0].category, service.searches[0].group) == ("Weapon", "Shield")
        assert dialog._restored_splitter_sizes() == expected_sizes
        service.result_ready.emit("search-1", "search_item_catalog",
            ItemCatalogSearchResult("session-a", 5, 0, 72, (),
                (ItemCatalogCategoryFacet("Weapon", "Sword", 80), ItemCatalogCategoryFacet("Weapon", "Shield", 5))))
        assert dialog._selected_filters() == ("Weapon", "Shield")
        assert dialog._category_tree.currentItem().text(0) == "Shield"
        assert len(service.searches) == 1 and not dialog._search_timer.isActive()
        pane_sizes = dialog._item_splitter.sizes()
        dialog.close()
        sizes = window.settings.value("ui/item_finder_splitter_sizes")
        assert sizes == [pane_sizes[1], pane_sizes[2], pane_sizes[0]]
        reopened = RemoteArchiveFinderDialog(window)
        assert reopened._restored_splitter_sizes() == pane_sizes
        assert reopened._selected_filters() == ("Weapon", "Shield")
        reopened.close()


def test_late_category_rows_are_localized_without_changing_the_backend_filter(tmp_path) -> None:
    from cdmw.ui.localization import UiLocalizer

    app = _app()
    window = _Window()
    localizer = UiLocalizer(language_dir=tmp_path, language_code="de")
    window.ui_localizer = localizer
    localizer.activate_runtime_tracking(window, application=app)
    dialog = RemoteArchiveFinderDialog(window)
    try:
        _drain()
        window.archive_catalogue_service.result_ready.emit("search-1", "search_item_catalog",
            ItemCatalogSearchResult("session-a", 5, 0, 72, (),
                (ItemCatalogCategoryFacet("Weapon", "Shield", 5),)))
        _drain()
        tree = dialog._category_tree
        assert tree.headerItem().text(0) == localizer.translate("Category") != "Category"
        assert tree.topLevelItem(0).text(0) == localizer.translate("All categories") != "All categories"
        shield = tree.topLevelItem(1).child(0)
        assert shield.text(0) == localizer.translate("Shield") != "Shield"
        assert shield.text(1) == "5"
        tree.setCurrentItem(shield)
        dialog._search_timer.stop()
        dialog._start_search()
        request = window.archive_catalogue_service.searches[-1]
        assert (request.category, request.group) == ("Weapon", "Shield")
    finally:
        dialog.close()
        localizer.shutdown()
        window.deleteLater()
        _drain()
