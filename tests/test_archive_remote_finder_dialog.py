from __future__ import annotations

import os
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QRect, QSettings, Signal, Qt
from PySide6.QtGui import QFont, QImage
from PySide6.QtWidgets import QAbstractSlider, QApplication, QPushButton, QScrollArea, QStyle, QStyleOptionViewItem, QWidget
from PySide6.QtTest import QTest

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
    assert weapon.text(0) == "Weapon" and weapon.text(1) == "85" and not weapon.isExpanded()
    assert all(not tree.topLevelItem(index).isExpanded() for index in range(tree.topLevelItemCount()))
    weapon.setExpanded(True)
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


@pytest.mark.parametrize("exit_method", ["close", "reject", "accept", "escape", "button"])
def test_finder_reopens_at_the_saved_category_page_item_and_scroll_positions(tmp_path, exit_method) -> None:
    _app()
    settings_path = str(tmp_path / "finder.cfg")
    window = _Window()
    window.settings = QSettings(settings_path, QSettings.IniFormat)
    dialog = RemoteArchiveFinderDialog(window)
    service = window.archive_catalogue_service
    facets = (ItemCatalogCategoryFacet("Weapon", "Sword", 216),
              *(ItemCatalogCategoryFacet("Weapon", f"Group {index}", 1) for index in range(45)),
              ItemCatalogCategoryFacet("Armor", "Head", 4),
              ItemCatalogCategoryFacet("Material", "Raw", 3))
    first_rows = tuple(_row(index) for index in range(1, 73))
    page_rows = tuple(replace(_row(index), description="\n".join(f"Detail {line}" for line in range(80)))
                      for index in range(73, 145))
    dialog.show()
    _drain()
    service.result_ready.emit("search-1", "search_item_catalog",
        ItemCatalogSearchResult("session-a", 216, 0, 72, first_rows, facets))
    _drain()
    weapon = dialog._category_tree.topLevelItem(1)
    armor = dialog._category_tree.topLevelItem(2)
    weapon.setExpanded(True)
    armor.setExpanded(True)
    dialog._category_tree.setCurrentItem(weapon.child(0))
    dialog._search_edit.setText("item")
    dialog._start_search()
    service.result_ready.emit("search-2", "search_item_catalog",
        ItemCatalogSearchResult("session-a", 216, 0, 72, first_rows, facets))
    dialog._next_button.click()
    service.result_ready.emit("search-3", "search_item_catalog",
        ItemCatalogSearchResult("session-a", 216, 72, 72, page_rows, facets))
    dialog._item_grid.setCurrentRow(42)
    _drain()
    scrollbars = (dialog._item_grid.verticalScrollBar(), dialog._category_tree.verticalScrollBar(),
                  dialog._detail_scroll.verticalScrollBar())
    for scrollbar in scrollbars:
        scrollbar.setValue(min(140, scrollbar.maximum()))
    expected_scroll = tuple(scrollbar.value() for scrollbar in scrollbars)
    assert all(value > 0 for value in expected_scroll)
    selected_id = dialog._selected_item_ids()[0]
    if exit_method == "escape":
        QTest.keyClick(dialog, Qt.Key_Escape)
    elif exit_method == "button":
        next(button for button in dialog.findChildren(QPushButton)
             if button.text() == "Close" and button.parentWidget() is dialog).click()
    else:
        getattr(dialog, exit_method)()
    assert dialog._closing
    window.settings.sync()

    reopened_window = _Window()
    reopened_window.settings = QSettings(settings_path, QSettings.IniFormat)
    reopened = RemoteArchiveFinderDialog(reopened_window)
    reopened.show()
    _drain()
    reopened_service = reopened_window.archive_catalogue_service
    request = reopened_service.searches[0]
    assert (request.query, request.category, request.group, request.page_start) == ("item", "Weapon", "Sword", 72)
    reopened_service.result_ready.emit("search-1", "search_item_catalog",
        ItemCatalogSearchResult("session-a", 216, 72, 72, page_rows, facets))
    _drain()
    assert reopened._selected_item_ids() == (selected_id,)
    assert reopened._detail_title.text() == f"Item {selected_id}"
    assert reopened._category_tree.currentItem().data(0, Qt.UserRole) == ("Weapon", "Sword")
    assert [reopened._category_tree.topLevelItem(index).isExpanded() for index in (1, 2, 3)] == [True, True, False]
    assert tuple(scrollbar.value() for scrollbar in (reopened._item_grid.verticalScrollBar(),
        reopened._category_tree.verticalScrollBar(), reopened._detail_scroll.verticalScrollBar())) == expected_scroll
    assert len(reopened_service.searches) == 1 and not reopened._search_timer.isActive()
    reopened.close()
    window.close()
    reopened_window.close()


@pytest.mark.parametrize("publish_before_close", [False, True])
def test_closing_during_initial_restore_preserves_saved_state_and_ignores_late_results(tmp_path, publish_before_close) -> None:
    _app()
    window = _Window()
    window.settings = QSettings(str(tmp_path / "finder.cfg"), QSettings.IniFormat)
    saved = {"ui/item_finder_search_text": "saved",
             "ui/item_finder_category": "Weapon", "ui/item_finder_group": "Sword",
             "ui/item_finder_page_start": 72, "ui/item_finder_selected_item_id": 88,
             "ui/item_finder_expanded_categories": ["Weapon"],
             "ui/item_finder_scroll_value": 240, "ui/item_finder_category_scroll_value": 100,
             "ui/item_finder_detail_scroll_value": 60}
    for key, value in saved.items():
        window.settings.setValue(key, value)
    dialog = RemoteArchiveFinderDialog(window)
    _drain()
    service = window.archive_catalogue_service
    result = ItemCatalogSearchResult("session-a", 144, 72, 72, (_row(88),),
        (ItemCatalogCategoryFacet("Weapon", "Sword", 144),))
    if publish_before_close:
        service.result_ready.emit("search-1", "search_item_catalog", result)
    dialog.reject()
    service.result_ready.emit("search-1", "search_item_catalog", result)
    _drain()
    assert {key: window.settings.value(key) for key in saved} == saved
    assert dialog._tree.topLevelItemCount() == (1 if publish_before_close else 0)
    if publish_before_close:
        assert not service.cancelled
    else:
        assert "search-1" in service.cancelled
    assert not dialog._search_timer.isActive() and not dialog._visible_icon_timer.isActive()
    window.close()


def test_new_filter_before_loading_drops_the_previous_page_and_item_restore(tmp_path) -> None:
    _app()
    window = _Window()
    window.settings = QSettings(str(tmp_path / "finder.cfg"), QSettings.IniFormat)
    window.settings.setValue("ui/item_finder_page_start", 72)
    window.settings.setValue("ui/item_finder_selected_item_id", 88)
    window.settings.setValue("ui/item_finder_scroll_value", 240)
    dialog = RemoteArchiveFinderDialog(window)
    dialog._search_edit.setText("new search")
    dialog.reject()
    _drain()
    assert window.settings.value("ui/item_finder_search_text") == "new search"
    assert window.settings.value("ui/item_finder_page_start") == 0
    assert window.settings.value("ui/item_finder_selected_item_id") == 0
    assert window.settings.value("ui/item_finder_scroll_value") == 0
    assert not window.archive_catalogue_service.searches
    window.close()


def test_collapsing_the_selected_group_parent_stays_collapsed_on_reopen(tmp_path) -> None:
    _app()
    window = _Window()
    window.settings = QSettings(str(tmp_path / "finder.cfg"), QSettings.IniFormat)
    window.settings.setValue("ui/item_finder_category", "Weapon")
    window.settings.setValue("ui/item_finder_group", "Sword")
    window.settings.setValue("ui/item_finder_expanded_categories", ["Weapon"])
    result = ItemCatalogSearchResult("session-a", 1, 0, 72, (_row(1),),
        (ItemCatalogCategoryFacet("Weapon", "Sword", 1),))
    dialog = RemoteArchiveFinderDialog(window)
    _drain()
    service = window.archive_catalogue_service
    service.result_ready.emit("search-1", "search_item_catalog", result)
    _drain()
    weapon = dialog._category_tree.topLevelItem(1)
    assert weapon.isExpanded()
    weapon.setExpanded(False)
    saved_filter = dialog._selected_filters()
    dialog.reject()
    assert window.settings.value("ui/item_finder_expanded_categories") == []
    reopened = RemoteArchiveFinderDialog(window)
    _drain()
    service.result_ready.emit("search-2", "search_item_catalog", result)
    _drain()
    assert reopened._selected_filters() == saved_filter
    assert not reopened._category_tree.topLevelItem(1).isExpanded()
    reopened.close()
    window.close()


def test_changing_search_while_restore_is_queued_ignores_the_old_scroll_position(tmp_path) -> None:
    _app()
    window = _Window()
    window.settings = QSettings(str(tmp_path / "finder.cfg"), QSettings.IniFormat)
    window.settings.setValue("ui/item_finder_selected_item_id", 88)
    window.settings.setValue("ui/item_finder_scroll_value", 240)
    dialog = RemoteArchiveFinderDialog(window)
    dialog.show()
    _drain()
    service = window.archive_catalogue_service
    service.result_ready.emit("search-1", "search_item_catalog",
        ItemCatalogSearchResult("session-a", 1, 0, 72, (_row(88),), ()))
    dialog._search_edit.setText("different")
    dialog._start_search()
    service.result_ready.emit("search-2", "search_item_catalog",
        ItemCatalogSearchResult("session-a", 72, 0, 72, tuple(_row(index) for index in range(1, 73)), ()))
    _drain()
    assert dialog._selected_item_ids() == ()
    assert dialog._item_grid.verticalScrollBar().maximum() > 240
    assert dialog._item_grid.verticalScrollBar().value() == 0
    dialog.close()
    window.close()


@pytest.mark.parametrize("user_action", ["select", "scroll"])
def test_an_action_before_restore_finishes_is_saved_when_immediately_closed(tmp_path, user_action) -> None:
    _app()
    window = _Window()
    window.settings = QSettings(str(tmp_path / "finder.cfg"), QSettings.IniFormat)
    window.settings.setValue("ui/item_finder_selected_item_id", 88)
    window.settings.setValue("ui/item_finder_scroll_value", 240)
    dialog = RemoteArchiveFinderDialog(window)
    dialog.show()
    _drain()
    window.archive_catalogue_service.result_ready.emit("search-1", "search_item_catalog",
        ItemCatalogSearchResult("session-a", 72, 0, 72, tuple(_row(index) for index in range(88, 160)), ()))
    dialog._item_grid.doItemsLayout()
    scrollbar = dialog._item_grid.verticalScrollBar()
    if user_action == "select":
        dialog._item_grid.setCurrentRow(1)
    else:
        scrollbar.triggerAction(QAbstractSlider.SliderPageStepAdd)
        assert scrollbar.value() > 0
    selected_id, scroll_value = dialog._selected_item_ids()[0], scrollbar.value()
    dialog.reject()
    _drain()
    assert window.settings.value("ui/item_finder_selected_item_id") == selected_id
    assert window.settings.value("ui/item_finder_scroll_value") == scroll_value
    window.close()


def test_saved_page_past_the_current_results_returns_to_the_last_available_page(tmp_path) -> None:
    _app()
    window = _Window()
    window.settings = QSettings(str(tmp_path / "finder.cfg"), QSettings.IniFormat)
    window.settings.setValue("ui/item_finder_page_start", 216)
    window.settings.setValue("ui/item_finder_selected_item_id", 999)
    dialog = RemoteArchiveFinderDialog(window)
    _drain()
    service = window.archive_catalogue_service
    assert service.searches[0].page_start == 216
    service.result_ready.emit("search-1", "search_item_catalog",
        ItemCatalogSearchResult("session-a", 80, 216, 72, (), ()))
    assert service.searches[1].page_start == 72
    service.result_ready.emit("search-2", "search_item_catalog",
        ItemCatalogSearchResult("session-a", 80, 72, 72, (_row(79), _row(80)), ()))
    _drain()
    assert dialog._page_start == 72 and dialog._item_grid.count() == 2
    assert dialog._selected_item_ids() == ()
    assert not dialog._next_button.isEnabled() and dialog._previous_button.isEnabled()
    dialog.close()
    window.close()


@pytest.mark.parametrize(
    ("width", "height", "font_size", "density"),
    [(940, 640, 10, "compact"), (1240, 800, 10, "compact"), (1960, 1160, 10, "compact"),
     (940, 640, 15, "compact"), (1240, 800, 15, "comfortable")],
)
def test_finder_layout_keeps_text_and_actions_visible(width, height, font_size, density) -> None:
    from cdmw.ui.themes import build_app_palette, build_app_stylesheet
    from tests.qt_font_metrics_support import ensure_default_ui_font_available

    app = _app()
    if not ensure_default_ui_font_available():
        pytest.skip("The application font is required for text geometry checks")
    original_font, original_palette, original_stylesheet = app.font(), app.palette(), app.styleSheet()
    app.setFont(QFont("Segoe UI", font_size))
    app.setPalette(build_app_palette("graphite"))
    app.setStyleSheet(build_app_stylesheet("graphite", density_key=density))
    window = _Window()
    window.open_new_item_studio = lambda _item_id: None
    dialog = RemoteArchiveFinderDialog(window)
    try:
        _drain()
        names = ("Ancient Shield", "Artisan's Ornamented Shield", "Ancient Ceremonial Shield of the Guardians")
        rows = tuple(replace(_row(index + 1), display_name=names[index % len(names)], group="Shield",
            internal_name="IT_Shield_0001_Golden_Ceremonial_Variant_<literal>",
            pac_files=("character/equipment/shield/ceremonial_guardians_shield_0001.pac",),
            description="A shield carried by the royal guard, with an ornate polished surface.")
            for index in range(72))
        facets = tuple(ItemCatalogCategoryFacet(category, group, 76) for category, group in (
            ("Weapon", "Shield"), ("Weapon", "Axe / Mace / Hammer"), ("Weapon", "Polearm / Spear"),
            ("Progression / Reward", "Artifact"), ("Quest / Document", "Book / Diary"),
            ("Quest / Document", "Map / Treasure"), ("Tool", "Throwable / Utility"),
            ("Tool", "Backpack / Pack")))
        window.archive_catalogue_service.result_ready.emit("search-1", "search_item_catalog",
            ItemCatalogSearchResult("session-a", 76, 0, 72, rows, facets))
        dialog.resize(width, height)
        dialog.show()
        _drain()
        assert dialog.width() == width
        assert dialog._detail_content.isHidden()
        assert dialog._detail_category.isHidden() and dialog._detail_summary.isHidden()
        assert dialog._item_splitter.sizes()[2] <= 330

        for button in (dialog._exact_button, dialog._related_button, dialog._clone_button):
            assert button.width() >= button.sizeHint().width()
            assert button.parentWidget().rect().contains(button.geometry())
        buttons = (dialog._exact_button, dialog._related_button, dialog._clone_button)
        assert all(not first.geometry().intersects(second.geometry())
                   for index, first in enumerate(buttons) for second in buttons[index + 1:])

        tree = dialog._category_tree
        tree.expandAll()
        _drain()
        for top_index in range(tree.topLevelItemCount()):
            parent = tree.topLevelItem(top_index)
            for item in (parent, *(parent.child(index) for index in range(parent.childCount()))):
                for column in (0, 1):
                    index = tree.indexFromItem(item, column)
                    option = QStyleOptionViewItem()
                    option.initFrom(tree)
                    tree.itemDelegate().initStyleOption(option, index)
                    option.rect = tree.visualRect(index)
                    text_rect = tree.style().subElementRect(QStyle.SE_ItemViewItemText, option, tree)
                    needed = tree.fontMetrics().boundingRect(
                        QRect(0, 0, text_rect.width(), 10000), Qt.TextWordWrap, item.text(column)).height()
                    assert text_rect.height() >= needed, item.text(column)

        grid = dialog._item_grid
        first_row = [grid.visualItemRect(grid.item(index)) for index in range(grid.count())]
        top = first_row[0].y()
        used_width = max(rect.right() + 1 for rect in first_row if rect.y() == top)
        assert grid.viewport().width() - used_width <= 20
        for item_index in range(3):
            item = grid.item(item_index)
            option = QStyleOptionViewItem()
            option.initFrom(grid)
            grid.itemDelegate().initStyleOption(option, grid.indexFromItem(item))
            option.decorationPosition = QStyleOptionViewItem.Top
            option.decorationSize = grid.iconSize()
            option.rect = grid.visualItemRect(item)
            text_rect = grid.style().subElementRect(QStyle.SE_ItemViewItemText, option, grid)
            needed = grid.fontMetrics().boundingRect(
                QRect(0, 0, text_rect.width(), 10000), Qt.TextWordWrap, item.text()).height()
            assert text_rect.height() >= needed, item.text()

        grid.setCurrentRow(0)
        _drain()
        assert not dialog._detail_content.isHidden()
        scroll = dialog._item_splitter.widget(2).findChild(QScrollArea)
        assert scroll.horizontalScrollBar().maximum() == 0
        for name in ("_detail_title", "_detail_internal", "_detail_category", "_detail_summary",
                     "_detail_evidence", "_detail_category_evidence", "_detail_stats",
                     "_detail_description", "_detail_localized", "_detail_models", "_detail_icons"):
            field = getattr(dialog, name)
            assert field.document().size().height() <= field.height(), name
            assert field.horizontalScrollBar().maximum() == 0, name
        expected = rows[0].internal_name + " (ID 1)"
        assert dialog._detail_internal.text() == expected
        dialog._detail_internal.selectAll()
        dialog._detail_internal.copy()
        assert app.clipboard().text() == expected
    finally:
        dialog.close()
        window.close()
        dialog.deleteLater()
        window.deleteLater()
        app.setFont(original_font)
        app.setPalette(original_palette)
        app.setStyleSheet(original_stylesheet)
        _drain()


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
        assert dialog._detail_title.text() == localizer.translate("Select an item") != "Select an item"
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
