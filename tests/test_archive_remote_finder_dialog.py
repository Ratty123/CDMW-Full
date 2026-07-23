from __future__ import annotations

import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from cdmw.domain.archives.item_catalogue import (
    ItemCatalogCategoryFacet,
    ItemCatalogRow,
    ItemCatalogScopeResult,
    ItemCatalogSearchResult,
    ItemCatalogValueFacet,
)
from cdmw.ui.archive_browser.remote_finder_dialog import RemoteArchiveFinderDialog


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


class _Controller:
    generation = 4


class _Bridge:
    def __init__(self) -> None:
        self.current_session = ArchiveSessionHandle("session-a", "C:/Game", "fingerprint-a", 20, 3, True)
        self.controller = _Controller()
        self.scopes: list[tuple[tuple[int, ...], str]] = []

    def apply_entry_id_scope(self, entry_ids: object, *, label: str) -> bool:
        self.scopes.append((tuple(entry_ids), label))
        return True


class _Window(QWidget):
    def __init__(self) -> None:
        super().__init__()
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


def _row(item_id: int, *, materials: tuple[str, ...] = ()) -> ItemCatalogRow:
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
        materials,
        1,
        "model link",
    )


def test_full_item_finder_loads_immediately_and_pages_server_side() -> None:
    _app()
    window = _Window()
    dialog = RemoteArchiveFinderDialog(window)
    assert dialog.windowTitle() == "Item Finder"
    assert not hasattr(dialog, "_material_only")
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
        (_row(1, materials=("metal",)), _row(2)),
        (ItemCatalogCategoryFacet("Weapon", "Sword", 80),),
        (ItemCatalogValueFacet("metal", 1),),
        True,
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
    result = ItemCatalogSearchResult("session-a", 1, 0, 72, (row,), (), (), False)
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
        ItemCatalogSearchResult("session-a", 1, 0, 72, (_row(7),), (), (), False),
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
    assert window.archive_remote_bridge.scopes == [((3, 8), "Item Finder: Item 7")]
    dialog.close()
