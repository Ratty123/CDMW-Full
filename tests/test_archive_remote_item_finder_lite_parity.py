from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QListView, QWidget

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
    for _ in range(10):
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


class _Settings:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self.values = dict(values or {})

    def value(self, key: str, default: object = None) -> object:
        return self.values.get(key, default)

    def setValue(self, key: str, value: object) -> None:
        self.values[key] = value


class _Bridge:
    def __init__(self) -> None:
        self.current_session = ArchiveSessionHandle("session-a", "C:/Game", "fingerprint-a", 20, 3, True)
        self.controller = type("Controller", (), {"generation": 4})()
        self.scopes: list[tuple[tuple[int, ...], str]] = []

    def apply_entry_id_scope(self, entry_ids: object, *, label: str) -> bool:
        self.scopes.append((tuple(entry_ids), label))
        return True


class _Window(QWidget):
    def __init__(self, settings: _Settings | None = None) -> None:
        super().__init__()
        self.archive_catalogue_service = _Service()
        self.archive_remote_bridge = _Bridge()
        self.settings = settings or _Settings()


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
        (f"ui/icon/item_{item_id}.dds",),
        (f"Localized Item {item_id}",),
        ("metal", "cloth"),
        2,
        "model and localization link",
    )


def test_full_item_finder_matches_lite_card_detail_and_scope_flow() -> None:
    _app()
    settings = _Settings(
        {
            "ui/item_finder_search_text": "sword",
            "ui/item_finder_category": "Equipment",
            "ui/item_finder_group": "Weapon",
            "ui/item_finder_material_tag": "metal",
        }
    )
    window = _Window(settings)
    dialog = RemoteArchiveFinderDialog(window)
    _drain()

    request = window.archive_catalogue_service.searches[-1]
    assert request.query == "sword"
    assert (request.category, request.group, request.material_tag) == (None, None, "metal")
    result = ItemCatalogSearchResult(
        "session-a",
        1,
        0,
        72,
        (_row(7),),
        (ItemCatalogCategoryFacet("Weapon", "Sword", 1),),
        (ItemCatalogValueFacet("metal", 1),),
        True,
    )
    window.archive_catalogue_service.result_ready.emit("search-1", "search_item_catalog", result)
    _drain()

    assert dialog._item_grid.viewMode() == QListView.IconMode
    assert dialog._item_grid.count() == 1
    assert not dialog._item_grid.item(0).icon().isNull()
    assert window.archive_catalogue_service.icons[-1].item_ids == (7,)
    dialog._item_grid.setCurrentRow(0)
    _drain()
    assert "item_7" in dialog._detail_internal.text()
    assert "Localized Item 7" in dialog._detail_localized.text()
    assert "metal" in dialog._detail_materials.text()
    assert "equipment/weapon/item_7.pac" in dialog._detail_models.text()
    assert "ui/icon/item_7.dds" in dialog._detail_icons.text()
    assert dialog._exact_button.isEnabled()
    assert dialog._related_button.isEnabled()

    dialog._scope_selected(include_related=True)
    window.archive_catalogue_service.result_ready.emit(
        "scope-1",
        "scope_item_catalog",
        ItemCatalogScopeResult("session-a", (3, 8), 1, 1, False),
    )
    _drain()
    assert dialog.result() == QDialog.Accepted
    assert window.archive_remote_bridge.scopes == [((3, 8), "Item Finder: Item 7")]
    dialog.close()
    assert "ui/item_finder_geometry" in settings.values
    assert settings.values["ui/item_finder_search_text"] == "sword"
    assert settings.values["ui/item_finder_category"] == ""
    assert settings.values["ui/item_finder_group"] == ""


def test_new_search_cancels_icons_and_rejects_stale_conversion(tmp_path) -> None:
    _app()
    window = _Window()
    dialog = RemoteArchiveFinderDialog(window)
    _drain()
    window.archive_catalogue_service.result_ready.emit(
        "search-1",
        "search_item_catalog",
        ItemCatalogSearchResult("session-a", 1, 0, 72, (_row(3),), (), (), True),
    )
    _drain()
    assert window.archive_catalogue_service.icons[-1].item_ids == (3,)
    old_generation = dialog._icon_generation
    old_cache_key = dialog._item_grid.item(0).icon().cacheKey()

    icon_path = tmp_path / "late.png"
    pixmap = QPixmap(8, 8)
    pixmap.fill(Qt.red)
    assert pixmap.save(str(icon_path))
    dialog._start_search()
    assert "icons-1" in window.archive_catalogue_service.cancelled
    dialog._apply_icons((old_generation, {3: str(icon_path)}))
    assert dialog._item_grid.item(0).icon().cacheKey() == old_cache_key
    dialog.close()
    assert "search-2" in window.archive_catalogue_service.cancelled
