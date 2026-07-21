"""Remote, bounded Qt model for the standalone full archive catalogue."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Optional

from PySide6.QtCore import QAbstractItemModel, QModelIndex, QObject, Qt, QTimer, Signal

from cdmw.domain.archives.catalogue import (
    ArchiveChildNode,
    ArchiveChildrenResult,
    ArchiveDurableIdentity,
    ArchiveEntryDto,
    ArchiveFacet,
    ArchivePage,
    ArchiveQueryHandle,
    ArchiveViewMode,
    archive_durable_identity_key,
)
from cdmw.ui.archive_browser.model import ARCHIVE_BROWSER_COLUMNS, ArchiveBrowserRowPayload


REMOTE_ENTRY_DTO_ROLE = int(Qt.UserRole) + 10
REMOTE_ENTRY_ID_ROLE = int(Qt.UserRole) + 11
REMOTE_IDENTITY_ROLE = int(Qt.UserRole) + 12


@dataclass(frozen=True, slots=True)
class RemotePageFetch:
    session_id: str
    query_id: str
    generation: int
    page_start: int
    page_size: int


@dataclass(frozen=True, slots=True)
class RemoteChildrenFetch:
    session_id: str
    query_id: str
    generation: int
    node_key: str
    parent_path: str | None
    category: str | None
    offset: int
    limit: int


@dataclass(slots=True)
class RemoteArchiveBrowserNode:
    kind: str
    key: str
    label: str = ""
    path: str = ""
    entry: ArchiveEntryDto | None = None
    parent: Optional["RemoteArchiveBrowserNode"] = None
    children: list["RemoteArchiveBrowserNode"] = field(default_factory=list)
    match_count: int = 0
    fetched: bool = False
    loading: bool = False
    next_offset: int | None = 0
    category: str | None = None
    row_number: int = 0

    @property
    def value(self) -> object:
        if self.entry is not None:
            return self.entry.entry_id
        if self.kind == "category":
            return self.category or self.key
        return self.path or self.key

    def child(self, row: int) -> Optional["RemoteArchiveBrowserNode"]:
        return self.children[row] if 0 <= row < len(self.children) else None

    def childCount(self) -> int:
        return len(self.children)

    def row(self) -> int:
        return self.row_number

    def data(self, _column: int, role: int = Qt.UserRole) -> object:
        if role == Qt.UserRole:
            return self.kind
        if role == Qt.UserRole + 1:
            return self.value
        if role == Qt.UserRole + 2:
            return self.fetched
        if role == REMOTE_ENTRY_DTO_ROLE:
            return self.entry
        if role == REMOTE_ENTRY_ID_ROLE:
            return None if self.entry is None else self.entry.entry_id
        if role == REMOTE_IDENTITY_ROLE:
            return None if self.entry is None else self.entry.identity
        return None

    def text(self, column: int) -> str:
        if column == 0:
            count = f" ({self.match_count:,})" if self.match_count else ""
            return f"{self.label}{count}"
        if column == 3:
            return "Category" if self.kind == "category" else "Folder"
        if column == 8 and self.kind == "folder":
            return self.path
        return "-" if column in {1, 2, 4, 5, 6, 7} else ""

    def toolTip(self, column: int) -> str:
        return (self.path or self.key) if column in {0, 8} else ""

    def isSelected(self) -> bool:
        return False

    def setSelected(self, selected: bool) -> None:
        del selected


class RemoteArchiveBrowserModel(QAbstractItemModel):
    """Expose worker-backed pages without retaining a global entry sequence."""

    pageRequested = Signal(object)
    childrenRequested = Signal(object)
    stalePayloadRejected = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        page_size: int = 256,
        page_cache_limit: int = 24,
        child_page_size: int = 256,
    ) -> None:
        super().__init__(parent)
        self._page_size = max(1, min(512, int(page_size)))
        maximum_pages = max(3, 10_000 // self._page_size)
        self._page_cache_limit = max(3, min(maximum_pages, int(page_cache_limit)))
        self._child_page_size = max(1, min(512, int(child_page_size)))
        self._handle: ArchiveQueryHandle | None = None
        self._view_mode = ArchiveViewMode.FLAT
        self._pages: OrderedDict[int, tuple[ArchiveEntryDto, ...]] = OrderedDict()
        self._queued_pages: set[int] = set()
        self._inflight_pages: set[int] = set()
        self._page_dispatch_scheduled = False
        self._requests_suspended = False
        self._root = RemoteArchiveBrowserNode("root", "root", fetched=False)
        self._nodes_by_key: dict[str, RemoteArchiveBrowserNode] = {self._root.key: self._root}

    @property
    def query_handle(self) -> ArchiveQueryHandle | None:
        return self._handle

    @property
    def page_size(self) -> int:
        return self._page_size

    @property
    def child_page_size(self) -> int:
        return self._child_page_size

    @property
    def view_mode(self) -> ArchiveViewMode:
        return self._view_mode

    @property
    def cached_page_count(self) -> int:
        return len(self._pages)

    @property
    def cached_entry_count(self) -> int:
        return sum(len(rows) for rows in self._pages.values()) + self._tree_entry_count(self._root)

    @property
    def inflight_page_starts(self) -> tuple[int, ...]:
        return tuple(sorted(self._inflight_pages))

    def publish_query(
        self,
        handle: ArchiveQueryHandle,
        *,
        view_mode: ArchiveViewMode,
        prime: bool = True,
    ) -> None:
        self.beginResetModel()
        self._handle = handle
        self._view_mode = view_mode
        self._pages.clear()
        self._queued_pages.clear()
        self._inflight_pages.clear()
        self._root = RemoteArchiveBrowserNode("root", "root", match_count=handle.total_matches, fetched=False)
        self._nodes_by_key = {self._root.key: self._root}
        self._requests_suspended = False
        self.endResetModel()
        if prime and view_mode is ArchiveViewMode.FLAT:
            self.request_visible_rows(0, min(handle.total_matches - 1, self._page_size - 1))
        elif prime and view_mode is ArchiveViewMode.FOLDERS:
            self._queue_children(self._root)

    def suspend_requests(self, suspended: bool) -> None:
        self._requests_suspended = bool(suspended)

    def clear(self) -> None:
        self.beginResetModel()
        self._handle = None
        self._pages.clear()
        self._queued_pages.clear()
        self._inflight_pages.clear()
        self._requests_suspended = False
        self._root = RemoteArchiveBrowserNode("root", "root", fetched=True, next_offset=None)
        self._nodes_by_key = {self._root.key: self._root}
        self.endResetModel()

    def publish_categories(self, facets: tuple[ArchiveFacet, ...]) -> bool:
        if self._handle is None or self._view_mode not in {
            ArchiveViewMode.CATEGORIES,
            ArchiveViewMode.CATEGORIES_AND_FOLDERS,
        }:
            return False
        self.beginResetModel()
        self._root.children = []
        self._nodes_by_key = {self._root.key: self._root}
        for row, facet in enumerate(facets):
            key = f"category:{facet.key}"
            node = RemoteArchiveBrowserNode(
                "category",
                key,
                label=facet.label,
                parent=self._root,
                match_count=facet.count,
                category=facet.key,
                row_number=row,
            )
            self._root.children.append(node)
            self._nodes_by_key[key] = node
        self._root.fetched = True
        self._root.next_offset = None
        self.endResetModel()
        return True

    def request_visible_rows(self, first_row: int, last_row: int) -> None:
        handle = self._handle
        if (
            self._requests_suspended
            or handle is None
            or self._view_mode is not ArchiveViewMode.FLAT
            or handle.total_matches <= 0
        ):
            return
        first = max(0, min(int(first_row), handle.total_matches - 1))
        last = max(first, min(int(last_row), handle.total_matches - 1))
        first_page = self._page_start(first)
        last_page = self._page_start(last)
        starts = range(first_page, last_page + self._page_size, self._page_size)
        for start in starts:
            self._queue_page(start)
        self._queue_page(first_page - self._page_size)
        self._queue_page(last_page + self._page_size)

    def accept_page(self, page: ArchivePage) -> bool:
        handle = self._handle
        if handle is None or not self._matches_page(page, handle) or not self._valid_page_bounds(page):
            self.stalePayloadRejected.emit("page")
            return False
        start = int(page.page_start)
        self._queued_pages.discard(start)
        self._inflight_pages.discard(start)
        self._pages[start] = tuple(page.rows)
        self._pages.move_to_end(start)
        while len(self._pages) > self._page_cache_limit:
            self._pages.popitem(last=False)
        if page.rows:
            first = self.index(start, 0)
            last = self.index(start + len(page.rows) - 1, self.columnCount() - 1)
            self.dataChanged.emit(first, last, [])
        return True

    def reject_page(self, page_start: int) -> None:
        start = self._page_start(page_start)
        self._queued_pages.discard(start)
        self._inflight_pages.discard(start)

    def accept_children(self, fetch: RemoteChildrenFetch, result: ArchiveChildrenResult) -> bool:
        handle = self._handle
        node = self._nodes_by_key.get(fetch.node_key)
        if (
            handle is None
            or node is None
            or fetch.session_id != handle.session_id
            or fetch.query_id != handle.query_id
            or fetch.generation != handle.generation
            or result.session_id != handle.session_id
            or result.query_id != handle.query_id
            or result.offset != fetch.offset
        ):
            if node is not None:
                node.loading = False
            self.stalePayloadRejected.emit("children")
            return False
        node.loading = False
        new_nodes = self._make_child_nodes(node, result.children)
        if new_nodes:
            parent_index = QModelIndex() if node is self._root else self._index_for_node(node)
            first_row = len(node.children)
            self.beginInsertRows(parent_index, first_row, first_row + len(new_nodes) - 1)
            node.children.extend(new_nodes)
            self.endInsertRows()
        next_offset = result.next_offset
        if next_offset is not None and next_offset <= fetch.offset:
            next_offset = None
        node.next_offset = next_offset
        node.fetched = next_offset is None
        node.match_count = max(node.match_count, result.total_children)
        return True

    def reject_children(self, fetch: RemoteChildrenFetch) -> None:
        node = self._nodes_by_key.get(fetch.node_key)
        if node is not None:
            node.loading = False

    def entry_for_index(self, index: QModelIndex) -> ArchiveEntryDto | None:
        if not index.isValid():
            return None
        if self._view_mode is ArchiveViewMode.FLAT:
            return self._entry_at_row(index.row())
        node = self._node_for_index(index)
        return None if node is None else node.entry

    def find_cached_index_for_identity(self, identity: ArchiveDurableIdentity) -> QModelIndex:
        target = archive_durable_identity_key(identity)
        if self._view_mode is ArchiveViewMode.FLAT:
            for start, rows in self._pages.items():
                for offset, entry in enumerate(rows):
                    if archive_durable_identity_key(entry.identity) == target:
                        return self.index(start + offset, 0)
            return QModelIndex()
        for node in self._nodes_by_key.values():
            if node.entry is not None and archive_durable_identity_key(node.entry.identity) == target:
                return self._index_for_node(node)
        return QModelIndex()

    def find_index_for_entry_id(self, entry_id: int) -> QModelIndex:
        target = int(entry_id)
        if self._view_mode is ArchiveViewMode.FLAT:
            for start, rows in self._pages.items():
                for offset, entry in enumerate(rows):
                    if entry.entry_id == target:
                        return self.index(start + offset, 0)
            return QModelIndex()
        for node in self._nodes_by_key.values():
            if node.entry is not None and node.entry.entry_id == target:
                return self._index_for_node(node)
        return QModelIndex()

    def index_for_node(self, node: RemoteArchiveBrowserNode) -> QModelIndex:
        if self._view_mode is ArchiveViewMode.FLAT and node.entry is not None:
            return self.find_index_for_entry_id(node.entry.entry_id)
        return self._index_for_node(node)

    def index_for_query_row(self, row: int) -> QModelIndex:
        if self._view_mode is not ArchiveViewMode.FLAT or not 0 <= row < self.rowCount():
            return QModelIndex()
        self.request_visible_rows(row, row)
        return self.index(row, 0)

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if row < 0 or column < 0 or column >= self.columnCount(parent):
            return QModelIndex()
        if self._view_mode is ArchiveViewMode.FLAT:
            if parent.isValid() or row >= self.rowCount():
                return QModelIndex()
            return self.createIndex(row, column)
        parent_node = self._node_for_index(parent)
        child = None if parent_node is None else parent_node.child(row)
        return self.createIndex(row, column, child) if child is not None else QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if self._view_mode is ArchiveViewMode.FLAT:
            return QModelIndex()
        node = self._node_for_index(index)
        if node is None or node.parent is None or node.parent is self._root:
            return QModelIndex()
        return self.createIndex(node.parent.row(), 0, node.parent)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        handle = self._handle
        if handle is None:
            return 0
        if self._view_mode is ArchiveViewMode.FLAT:
            return 0 if parent.isValid() else handle.total_matches
        node = self._node_for_index(parent)
        return 0 if node is None else node.childCount()

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        del parent
        return len(ARCHIVE_BROWSER_COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> object:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole and 0 <= section < len(ARCHIVE_BROWSER_COLUMNS):
            return ARCHIVE_BROWSER_COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        if not index.isValid():
            return None
        entry = self.entry_for_index(index)
        if entry is None:
            if self._view_mode is ArchiveViewMode.FLAT:
                self.request_visible_rows(index.row(), index.row())
                if role == Qt.DisplayRole:
                    return "Loading..." if index.column() == 0 else ""
                if role == Qt.UserRole:
                    return "loading"
                if role == Qt.UserRole + 2:
                    return False
                return None
            node = self._node_for_index(index)
            if node is None:
                return None
            if role == Qt.DisplayRole:
                return node.text(index.column())
            if role == Qt.ToolTipRole:
                return node.toolTip(index.column())
            return node.data(index.column(), role)
        payload = _row_payload(entry, show_full_path=self._view_mode is ArchiveViewMode.FLAT)
        if role == Qt.DisplayRole:
            return payload.columns[index.column()]
        if role == Qt.ToolTipRole:
            return payload.tooltip(index.column())
        if role == Qt.UserRole:
            return "file"
        if role == Qt.UserRole + 1:
            return entry.entry_id
        if role == Qt.UserRole + 2:
            return True
        if role == REMOTE_ENTRY_DTO_ROLE:
            return entry
        if role == REMOTE_ENTRY_ID_ROLE:
            return entry.entry_id
        if role == REMOTE_IDENTITY_ROLE:
            return entry.identity
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:
        base = Qt.ItemIsEnabled
        if self.entry_for_index(index) is not None or self._view_mode is not ArchiveViewMode.FLAT:
            base |= Qt.ItemIsSelectable
        return base

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        if self._handle is None:
            return False
        if self._view_mode is ArchiveViewMode.FLAT:
            return not parent.isValid() and self._handle.total_matches > 0
        node = self._node_for_index(parent)
        if node is None or node.kind == "file":
            return False
        return bool(node.children or node.next_offset is not None or node.match_count)

    def canFetchMore(self, parent: QModelIndex) -> bool:
        if self._view_mode is ArchiveViewMode.FLAT:
            return False
        node = self._node_for_index(parent)
        return bool(node is not None and node.kind != "file" and not node.loading and node.next_offset is not None)

    def fetchMore(self, parent: QModelIndex) -> None:
        if self._view_mode is ArchiveViewMode.FLAT:
            return
        node = self._node_for_index(parent)
        if node is not None:
            self._queue_children(node)

    def top_level_node(self, row: int) -> RemoteArchiveBrowserNode | None:
        if self._view_mode is ArchiveViewMode.FLAT:
            entry = self._entry_at_row(row)
            return RemoteArchiveBrowserNode(
                "file" if entry is not None else "loading",
                f"row:{row}",
                entry=entry,
                fetched=entry is not None,
                next_offset=None,
                row_number=row,
            ) if 0 <= row < self.rowCount() else None
        return self._root.child(row)

    def node_from_index(self, index: QModelIndex) -> RemoteArchiveBrowserNode | None:
        if not index.isValid():
            return None
        if self._view_mode is ArchiveViewMode.FLAT:
            return self.top_level_node(index.row())
        node = self._node_for_index(index)
        return None if node is self._root else node

    def entry_ids_for_node(self, node: RemoteArchiveBrowserNode | None) -> tuple[int, ...]:
        if node is None or node.entry is None:
            return ()
        return (node.entry.entry_id,)

    def _page_start(self, row: int) -> int:
        return max(0, int(row) // self._page_size * self._page_size)

    def _queue_page(self, page_start: int) -> None:
        handle = self._handle
        if self._requests_suspended or handle is None or page_start < 0 or page_start >= handle.total_matches:
            return
        start = self._page_start(page_start)
        if start in self._pages:
            self._pages.move_to_end(start)
            return
        if start in self._queued_pages or start in self._inflight_pages:
            return
        self._queued_pages.add(start)
        if not self._page_dispatch_scheduled:
            self._page_dispatch_scheduled = True
            QTimer.singleShot(0, self._dispatch_queued_pages)

    def _dispatch_queued_pages(self) -> None:
        self._page_dispatch_scheduled = False
        handle = self._handle
        if self._requests_suspended or handle is None:
            self._queued_pages.clear()
            return
        for start in sorted(self._queued_pages):
            self._inflight_pages.add(start)
            self.pageRequested.emit(
                RemotePageFetch(handle.session_id, handle.query_id, handle.generation, start, self._page_size)
            )
        self._queued_pages.clear()

    def _queue_children(self, node: RemoteArchiveBrowserNode) -> None:
        handle = self._handle
        if self._requests_suspended or handle is None or node.loading or node.next_offset is None or node.kind == "file":
            return
        node.loading = True
        parent_path = node.path if node.kind == "folder" else None
        fetch = RemoteChildrenFetch(
            handle.session_id,
            handle.query_id,
            handle.generation,
            node.key,
            parent_path,
            node.category,
            node.next_offset,
            self._child_page_size,
        )
        QTimer.singleShot(0, lambda current=fetch: self._dispatch_children(current))

    def _dispatch_children(self, fetch: RemoteChildrenFetch) -> None:
        node = self._nodes_by_key.get(fetch.node_key)
        handle = self._handle
        if (
            self._requests_suspended
            or node is None
            or handle is None
            or fetch.session_id != handle.session_id
            or fetch.query_id != handle.query_id
            or fetch.generation != handle.generation
        ):
            if node is not None:
                node.loading = False
            return
        self.childrenRequested.emit(fetch)

    def _entry_at_row(self, row: int) -> ArchiveEntryDto | None:
        if row < 0:
            return None
        start = self._page_start(row)
        rows = self._pages.get(start)
        if rows is None:
            return None
        self._pages.move_to_end(start)
        offset = row - start
        return rows[offset] if 0 <= offset < len(rows) else None

    def _node_for_index(self, index: QModelIndex) -> RemoteArchiveBrowserNode | None:
        if not index.isValid():
            return self._root
        node = index.internalPointer()
        return node if isinstance(node, RemoteArchiveBrowserNode) else None

    def _index_for_node(self, node: RemoteArchiveBrowserNode) -> QModelIndex:
        if node is self._root or node.parent is None:
            return QModelIndex()
        parent_index = QModelIndex() if node.parent is self._root else self._index_for_node(node.parent)
        return self.index(node.row(), 0, parent_index)

    def _make_child_nodes(
        self,
        parent: RemoteArchiveBrowserNode,
        children: tuple[ArchiveChildNode, ...],
    ) -> list[RemoteArchiveBrowserNode]:
        nodes: list[RemoteArchiveBrowserNode] = []
        for child in children:
            node_key = f"{parent.key}|{child.key}"
            if node_key in self._nodes_by_key:
                continue
            kind = "folder" if child.is_folder else "file"
            node = RemoteArchiveBrowserNode(
                kind,
                node_key,
                label=child.label,
                path=child.key if child.is_folder else (child.entry.path if child.entry is not None else ""),
                entry=child.entry,
                parent=parent,
                match_count=child.match_count,
                fetched=not child.is_folder,
                next_offset=0 if child.is_folder else None,
                category=parent.category,
                row_number=len(parent.children) + len(nodes),
            )
            nodes.append(node)
            self._nodes_by_key[node_key] = node
        return nodes

    @staticmethod
    def _matches_page(page: ArchivePage, handle: ArchiveQueryHandle) -> bool:
        return (
            page.session_id == handle.session_id
            and page.query_id == handle.query_id
            and page.generation == handle.generation
            and page.total_matches == handle.total_matches
            and all(row.session_id == handle.session_id for row in page.rows)
        )

    def _valid_page_bounds(self, page: ArchivePage) -> bool:
        return (
            page.page_start >= 0
            and page.page_start % self._page_size == 0
            and len(page.rows) <= self._page_size
            and page.page_start + len(page.rows) <= page.total_matches
        )

    @staticmethod
    def _tree_entry_count(node: RemoteArchiveBrowserNode) -> int:
        return sum(
            (1 if child.entry is not None else 0) + RemoteArchiveBrowserModel._tree_entry_count(child)
            for child in node.children
        )


def _row_payload(entry: ArchiveEntryDto, *, show_full_path: bool) -> ArchiveBrowserRowPayload:
    path = entry.path.replace("\\", "/")
    parts = tuple(part for part in PurePosixPath(path).parts if part)
    display_name = parts[-1] if parts else path
    folder = path if show_full_path else "/".join(parts[:-1])
    compression = "Stored" if entry.stored_size == entry.original_size else f"Type {entry.flags & 0x0F}"
    role = _remote_type_display(entry)
    columns = (
        display_name,
        entry.exact_name or "-",
        entry.name_evidence or entry.known_name or "-",
        role,
        _format_bytes(entry.original_size),
        compression,
        entry.package or "-",
        entry.override_state or "-",
        folder,
    )
    size_tooltip = f"Original: {entry.original_size:,} bytes\nStored: {entry.stored_size:,} bytes"
    tooltips = (
        path,
        entry.exact_name,
        entry.name_evidence,
        f"Role: {entry.role.value}\nExtension: {entry.extension or '-'}",
        size_tooltip,
        compression,
        f"Package: {entry.package}\nPAMT: {entry.source_pamt}",
        entry.override_state,
        path,
    )
    return ArchiveBrowserRowPayload(columns=columns, tooltips=tooltips)


def _remote_type_display(entry: ArchiveEntryDto) -> str:
    canonical = str(entry.type_display or "").strip()
    if canonical:
        return canonical
    labels = {
        "model": "Mesh",
        "animation": "Animation",
        "physics": "Physics",
        "metadata": "Metadata",
        "video": "Video",
        "audio": "Audio",
        "user_interface": "UI",
        "impostor": "Impostor",
        "normal": "Normal",
        "material": "Material",
        "image": "Texture",
        "text": "Text",
        "other": "Unknown",
    }
    label = labels.get(entry.role.value, entry.role.value.replace("_", " ").title())
    return f"{label} {str(entry.extension or '').strip().lower()}".strip()


def _format_bytes(value: int) -> str:
    size = max(0, int(value))
    if size < 1024:
        return f"{size:,} B"
    amount = float(size)
    for suffix in ("KiB", "MiB", "GiB", "TiB"):
        amount /= 1024.0
        if amount < 1024.0 or suffix == "TiB":
            return f"{amount:.1f} {suffix}"
    return f"{size:,} B"


__all__ = [
    "REMOTE_ENTRY_DTO_ROLE",
    "REMOTE_ENTRY_ID_ROLE",
    "REMOTE_IDENTITY_ROLE",
    "RemoteArchiveBrowserModel",
    "RemoteArchiveBrowserNode",
    "RemoteChildrenFetch",
    "RemotePageFetch",
]
