from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from cdmw.domain.archives.catalogue import (
    ArchiveChildNode,
    ArchiveChildrenResult,
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveEntryRole,
    ArchiveFacet,
    ArchivePage,
    ArchiveQueryHandle,
    ArchiveViewMode,
)
from cdmw.ui.archive_browser.remote_model import (
    REMOTE_ENTRY_DTO_ROLE,
    RemoteArchiveBrowserModel,
    RemoteChildrenFetch,
)
from cdmw.ui.archive_browser.model import ArchiveBrowserTreeView
from cdmw.models import ArchiveEntry


_APPLICATION: QApplication | None = None


def _app() -> QApplication:
    global _APPLICATION
    _APPLICATION = QApplication.instance() or QApplication([])
    return _APPLICATION


def _handle(*, query: str = "query-a", generation: int = 4, total: int = 2_000) -> ArchiveQueryHandle:
    return ArchiveQueryHandle("session-a", query, generation, total)


def _entry(entry_id: int, *, session: str = "session-a", path: str | None = None) -> ArchiveEntryDto:
    resolved_path = path or f"character/model/file_{entry_id}.pac"
    return ArchiveEntryDto(
        session_id=session,
        entry_id=entry_id,
        identity=ArchiveDurableIdentity(resolved_path.casefold(), "0009/0.pamt", 2, entry_id * 100),
        path=resolved_path,
        source_pamt="C:/game/0009/0.pamt",
        paz_file="C:/game/0009/2.paz",
        paz_index=2,
        offset=entry_id * 100,
        stored_size=1024,
        original_size=2048,
        flags=2,
        extension=".pac",
        package="0009/0.pamt",
        role=ArchiveEntryRole.MODEL,
        category="model_mesh_physics",
        is_previewable=True,
        exact_name=f"Exact {entry_id}",
        name_evidence="Exact localization",
        is_active_override=entry_id % 2 == 0,
    )


def _drain_events() -> None:
    app = _app()
    for _ in range(4):
        app.processEvents()


def test_flat_remote_model_exposes_total_without_full_list_and_requests_adjacent_pages() -> None:
    _app()
    model = RemoteArchiveBrowserModel(page_size=256, page_cache_limit=8)
    requests = []
    model.pageRequested.connect(requests.append)

    model.publish_query(_handle(total=1_674_732), view_mode=ArchiveViewMode.FLAT)

    assert model.rowCount() == 1_674_732
    assert model.cached_entry_count == 0
    assert model.data(model.index(700, 0), Qt.DisplayRole) == "Loading..."
    _drain_events()
    starts = {request.page_start for request in requests}
    assert {0, 256, 512, 768}.issubset(starts)
    assert model.cached_entry_count == 0


def test_remote_model_accepts_only_current_bounded_pages_and_repaints_rows() -> None:
    _app()
    model = RemoteArchiveBrowserModel(page_size=4, page_cache_limit=3)
    rejected: list[str] = []
    changed: list[tuple[int, int]] = []
    model.stalePayloadRejected.connect(rejected.append)
    model.dataChanged.connect(lambda first, last, _roles: changed.append((first.row(), last.row())))
    model.publish_query(_handle(total=12), view_mode=ArchiveViewMode.FLAT)
    current = ArchivePage("session-a", "query-a", 4, 12, 0, tuple(_entry(index) for index in range(4)))

    assert model.accept_page(current)
    index = model.index(0, 0)
    assert model.data(index, Qt.DisplayRole) == "file_0.pac"
    assert model.data(index, REMOTE_ENTRY_DTO_ROLE) == current.rows[0]
    assert changed == [(0, 3)]
    assert not model.accept_page(ArchivePage("session-a", "old-query", 4, 12, 0, current.rows))
    assert not model.accept_page(ArchivePage("session-a", "query-a", 4, 12, 1, current.rows))
    assert rejected == ["page", "page"]


def test_remote_page_cache_is_lru_bounded_below_ten_thousand_entries() -> None:
    _app()
    model = RemoteArchiveBrowserModel(page_size=512, page_cache_limit=99)
    total = 512 * 25
    model.publish_query(_handle(total=total), view_mode=ArchiveViewMode.FLAT)
    for start in range(0, total, 512):
        page = ArchivePage(
            "session-a",
            "query-a",
            4,
            total,
            start,
            tuple(_entry(start + offset) for offset in range(512)),
        )
        assert model.accept_page(page)

    assert model.cached_page_count == 19
    assert model.cached_entry_count == 19 * 512
    assert model.cached_entry_count < 10_000
    assert model.entry_for_index(model.index(0, 0)) is None
    assert model.entry_for_index(model.index(total - 1, 0)) is not None


def test_folder_children_are_requested_and_continuation_pages_append_lazily() -> None:
    _app()
    model = RemoteArchiveBrowserModel(child_page_size=2)
    requests: list[RemoteChildrenFetch] = []
    model.childrenRequested.connect(requests.append)
    model.publish_query(_handle(total=20), view_mode=ArchiveViewMode.FOLDERS)
    _drain_events()
    assert len(requests) == 1
    root_fetch = requests.pop()
    assert root_fetch.node_key == "root"
    assert root_fetch.offset == 0
    first_result = ArchiveChildrenResult(
        "session-a",
        "query-a",
        (
            ArchiveChildNode("character", "character", True, 19),
            ArchiveChildNode("entry:19", "root.txt", False, 1, _entry(19, path="root.txt")),
        ),
        True,
        offset=0,
        total_children=3,
        next_offset=2,
    )
    assert model.accept_children(root_fetch, first_result)
    assert model.rowCount() == 2
    assert model.data(model.index(0, 0), Qt.DisplayRole) == "character (19)"
    assert model.data(model.index(1, 0), Qt.DisplayRole) == "root.txt"
    assert model.canFetchMore(QModelIndex())

    model.fetchMore(QModelIndex())
    _drain_events()
    continuation = requests.pop()
    assert continuation.offset == 2
    assert model.accept_children(
        continuation,
        ArchiveChildrenResult(
            "session-a",
            "query-a",
            (ArchiveChildNode("texture", "texture", True, 1),),
            False,
            offset=2,
            total_children=3,
            next_offset=None,
        ),
    )
    assert model.rowCount() == 3
    assert not model.canFetchMore(QModelIndex())

    folder_index = model.index(0, 0)
    model.fetchMore(folder_index)
    _drain_events()
    folder_fetch = requests.pop()
    assert folder_fetch.parent_path == "character"
    assert folder_fetch.offset == 0


def test_category_facets_are_nodes_and_stale_child_results_are_rejected() -> None:
    _app()
    model = RemoteArchiveBrowserModel(child_page_size=32)
    requests: list[RemoteChildrenFetch] = []
    rejected: list[str] = []
    model.childrenRequested.connect(requests.append)
    model.stalePayloadRejected.connect(rejected.append)
    model.publish_query(_handle(total=9), view_mode=ArchiveViewMode.CATEGORIES)
    assert model.publish_categories((ArchiveFacet("model", "Models", 9),))
    category = model.index(0, 0)
    assert model.data(category, Qt.DisplayRole) == "Models (9)"
    model.fetchMore(category)
    _drain_events()
    fetch = requests.pop()
    assert fetch.category == "model"
    stale = ArchiveChildrenResult("session-a", "old-query", (), False)
    assert not model.accept_children(fetch, stale)
    assert rejected == ["children"]


def test_durable_identity_can_restore_a_cached_flat_selection() -> None:
    _app()
    model = RemoteArchiveBrowserModel(page_size=4)
    model.publish_query(_handle(total=4), view_mode=ArchiveViewMode.FLAT)
    rows = tuple(_entry(index) for index in range(4))
    assert model.accept_page(ArchivePage("session-a", "query-a", 4, 4, 0, rows))

    restored = model.find_cached_index_for_identity(rows[2].identity)

    assert restored.isValid()
    assert restored.row() == 2
    assert model.entry_for_index(restored) == rows[2]


def test_archive_tree_view_switches_between_owned_remote_and_legacy_models() -> None:
    _app()
    view = ArchiveBrowserTreeView()
    remote = RemoteArchiveBrowserModel(page_size=4, parent=view)
    rows = tuple(_entry(index) for index in range(4))
    remote.publish_query(_handle(total=4), view_mode=ArchiveViewMode.FLAT, prime=False)
    assert remote.accept_page(ArchivePage("session-a", "query-a", 4, 4, 0, rows))

    view.use_remote_model(remote)

    assert view.remote_model_active()
    assert view.archive_model() is remote
    assert view.topLevelItemCount() == 4
    item = view.find_item_for_entry(2)
    assert item is not None and item.entry == rows[2]
    view.setCurrentItem(item)
    assert view.currentItem() is not None and view.currentItem().entry == rows[2]

    legacy_entry = ArchiveEntry(
        path="legacy/file.pac",
        pamt_path=Path("legacy/0.pamt"),
        paz_file=Path("legacy/0.paz"),
        offset=1,
        comp_size=2,
        orig_size=3,
        flags=0,
        paz_index=0,
    )
    view.set_archive_state([legacy_entry], mode="flat", fetch_batch_size=100)
    assert not view.remote_model_active()
    assert view.archive_model() is view.legacy_archive_model()
    assert view.topLevelItemCount() == 1
