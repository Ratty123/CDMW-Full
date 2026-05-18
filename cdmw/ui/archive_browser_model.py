from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import QAbstractItemModel, QItemSelectionModel, QModelIndex, QObject, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QTreeView

from cdmw.models import ArchiveEntry


ARCHIVE_BROWSER_COLUMNS = (
    "Name",
    "Exact Name",
    "Name Evidence",
    "Role / Type",
    "Size",
    "Comp",
    "Package",
    "State",
    "Path",
)


@dataclass(frozen=True)
class ArchiveBrowserRowPayload:
    columns: Tuple[str, ...]
    tooltips: Tuple[str, ...] = ()
    tooltip_provider: Optional[Callable[[], Tuple[str, ...]]] = field(default=None, compare=False, repr=False)

    def tooltip(self, column: int) -> str:
        tooltips = self.tooltips
        if not tooltips and self.tooltip_provider is not None:
            tooltips = self.tooltip_provider()
        return tooltips[column] if 0 <= column < len(tooltips) else ""


@dataclass
class ArchiveBrowserNode:
    kind: str
    value: object = None
    columns: Tuple[str, ...] = ()
    tooltips: Tuple[str, ...] = ()
    parent: Optional["ArchiveBrowserNode"] = None
    children: List["ArchiveBrowserNode"] = field(default_factory=list)
    entry_indexes: Tuple[int, ...] = ()
    fetched: bool = True
    direct_loaded: int = 0
    row_number: int = 0

    def child(self, row: int) -> Optional["ArchiveBrowserNode"]:
        return self.children[row] if 0 <= row < len(self.children) else None

    def childCount(self) -> int:
        return len(self.children)

    def row(self) -> int:
        return self.row_number

    def data(self, column: int, role: int = Qt.UserRole) -> object:
        if role == Qt.UserRole:
            return self.kind
        if role == Qt.UserRole + 1:
            return self.value
        if role == Qt.UserRole + 2:
            return self.fetched
        return None

    def text(self, column: int) -> str:
        return self.columns[column] if 0 <= column < len(self.columns) else ""

    def toolTip(self, column: int) -> str:
        return self.tooltips[column] if 0 <= column < len(self.tooltips) else ""

    def isSelected(self) -> bool:
        return False

    def setSelected(self, selected: bool) -> None:
        del selected


class ArchiveBrowserModel(QAbstractItemModel):
    def __init__(
        self,
        parent: Optional[QObject] = None,
        *,
        row_provider: Optional[Callable[[int, bool], ArchiveBrowserRowPayload]] = None,
        category_provider: Optional[Callable[[ArchiveEntry], str]] = None,
        category_sort_key: Optional[Callable[[str], Tuple[int, str]]] = None,
        row_cache_limit: int = 12000,
    ):
        super().__init__(parent)
        self._root = ArchiveBrowserNode("root", fetched=True)
        self._entries: Sequence[ArchiveEntry] = ()
        self._mode = "flat"
        self._tree_child_folders: Mapping[Tuple[str, ...], Sequence[Tuple[str, Tuple[str, ...]]]] = {}
        self._tree_direct_files: Mapping[Tuple[str, ...], Sequence[int]] = {}
        self._tree_folder_entry_indexes: Mapping[Tuple[str, ...], Sequence[int]] = {}
        self._category_entry_indexes: Mapping[str, Sequence[int]] = {}
        self._row_provider = row_provider or self._default_row_payload
        self._category_provider = category_provider or (lambda _entry: "Other")
        self._category_sort_key = category_sort_key or (lambda value: (99, value))
        self._fetch_batch_size = 500
        self._row_cache: "OrderedDict[Tuple[int, bool], ArchiveBrowserRowPayload]" = OrderedDict()
        self._row_cache_limit = max(1, min(100_000, int(row_cache_limit or 12000)))
        self._flat_node_cache: Dict[int, ArchiveBrowserNode] = {}

    def clear(self) -> None:
        self.beginResetModel()
        self._root.children.clear()
        self._entries = ()
        self._row_cache.clear()
        self._flat_node_cache.clear()
        self.endResetModel()

    def set_archive_state(
        self,
        entries: Sequence[ArchiveEntry],
        *,
        mode: str,
        tree_child_folders: Mapping[Tuple[str, ...], Sequence[Tuple[str, Tuple[str, ...]]]] = {},
        tree_direct_files: Mapping[Tuple[str, ...], Sequence[int]] = {},
        tree_folder_entry_indexes: Mapping[Tuple[str, ...], Sequence[int]] = {},
        category_entry_indexes: Mapping[str, Sequence[int]] = {},
        fetch_batch_size: int = 500,
    ) -> None:
        self.beginResetModel()
        self._entries = entries
        self._mode = mode if mode in {"flat", "folders", "categories"} else "flat"
        self._tree_child_folders = tree_child_folders
        self._tree_direct_files = tree_direct_files
        self._tree_folder_entry_indexes = tree_folder_entry_indexes
        self._category_entry_indexes = category_entry_indexes
        self._fetch_batch_size = max(100, min(5000, int(fetch_batch_size or 500)))
        self._row_cache.clear()
        self._flat_node_cache.clear()
        self._root.children = self._build_top_level_nodes()
        self.endResetModel()

    def set_providers(
        self,
        *,
        row_provider: Optional[Callable[[int, bool], ArchiveBrowserRowPayload]] = None,
        category_provider: Optional[Callable[[ArchiveEntry], str]] = None,
        category_sort_key: Optional[Callable[[str], Tuple[int, str]]] = None,
    ) -> None:
        if row_provider is not None:
            self._row_provider = row_provider
        if category_provider is not None:
            self._category_provider = category_provider
        if category_sort_key is not None:
            self._category_sort_key = category_sort_key

    def _build_top_level_nodes(self) -> List[ArchiveBrowserNode]:
        if self._mode == "categories":
            nodes: List[ArchiveBrowserNode] = []
            for row_number, (category, indexes) in enumerate(
                sorted(self._category_entry_indexes.items(), key=lambda item: self._category_sort_key(str(item[0])))
            ):
                node = ArchiveBrowserNode(
                    "category",
                    str(category),
                    columns=(f"{category} ({len(indexes):,})", "-", "-", "Category", "-", "-", "-", "-", ""),
                    tooltips=(f"{category} assets in the current filtered view",),
                    parent=self._root,
                    entry_indexes=tuple(int(index) for index in indexes),
                    fetched=False,
                    row_number=row_number,
                )
                nodes.append(node)
            return nodes
        if self._mode == "folders":
            nodes: List[ArchiveBrowserNode] = []
            for _leaf, child_key in self._tree_child_folders.get((), ()):
                nodes.append(self._folder_node(child_key, self._root, row_number=len(nodes)))
            for index in self._tree_direct_files.get((), ()):
                nodes.append(self._file_node(index, self._root, show_full_path=False, row_number=len(nodes)))
            return nodes
        return []

    def _folder_node(self, folder_key: Tuple[str, ...], parent: ArchiveBrowserNode, *, row_number: int = 0) -> ArchiveBrowserNode:
        tooltip = "/".join(folder_key)
        return ArchiveBrowserNode(
            "folder",
            tuple(folder_key),
            columns=(folder_key[-1] if folder_key else "(root)", "-", "-", "Folder", "-", "-", "-", "-", tooltip),
            tooltips=(tooltip,),
            parent=parent,
            entry_indexes=tuple(int(index) for index in self._tree_folder_entry_indexes.get(folder_key, ())),
            fetched=False,
            row_number=row_number,
        )

    def _file_node(
        self,
        entry_index: int,
        parent: Optional[ArchiveBrowserNode],
        *,
        show_full_path: bool,
        row_number: int = 0,
    ) -> ArchiveBrowserNode:
        if parent is None:
            cached = self._flat_node_cache.get(int(entry_index))
            if cached is not None:
                return cached
            cached = ArchiveBrowserNode(
                "file",
                int(entry_index),
                parent=None,
                entry_indexes=(int(entry_index),),
                fetched=True,
                columns=(),
                tooltips=(),
                row_number=int(entry_index),
            )
            self._flat_node_cache[int(entry_index)] = cached
            return cached
        return ArchiveBrowserNode(
            "file",
            int(entry_index),
            parent=parent,
            entry_indexes=(int(entry_index),),
            fetched=True,
            columns=(),
            tooltips=(),
            row_number=row_number,
        )

    def _default_row_payload(self, entry_index: int, show_full_path: bool) -> ArchiveBrowserRowPayload:
        entry = self._entries[entry_index]
        parts = tuple(part for part in PurePosixPath(entry.path.replace("\\", "/")).parts if part)
        display_name = parts[-1] if parts else entry.basename
        folder = entry.path if show_full_path else "/".join(parts[:-1])
        columns = (
            display_name,
            "-",
            "-",
            str(entry.extension or "-"),
            str(getattr(entry, "orig_size", "") or "-"),
            str(getattr(entry, "compression_label", "") or "-"),
            str(getattr(entry, "package_label", "") or "-"),
            "-",
            folder,
        )
        return ArchiveBrowserRowPayload(columns=columns, tooltips=(entry.path,))

    def _payload_for_file(self, entry_index: int, *, show_full_path: bool) -> ArchiveBrowserRowPayload:
        key = (int(entry_index), bool(show_full_path))
        payload = self._row_cache.get(key)
        if payload is None:
            payload = self._row_provider(int(entry_index), bool(show_full_path))
            self._row_cache[key] = payload
            while len(self._row_cache) > self._row_cache_limit:
                self._row_cache.popitem(last=False)
        else:
            self._row_cache.move_to_end(key)
        return payload

    def _node_for_index(self, index: QModelIndex) -> Optional[ArchiveBrowserNode]:
        if not index.isValid():
            return self._root
        node = index.internalPointer()
        return node if isinstance(node, ArchiveBrowserNode) else None

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if row < 0 or column < 0 or column >= self.columnCount(parent):
            return QModelIndex()
        parent_node = self._node_for_index(parent)
        if parent_node is None:
            return QModelIndex()
        if self._mode == "flat" and parent_node is self._root:
            if row >= len(self._entries):
                return QModelIndex()
            return self.createIndex(row, column, self._file_node(row, None, show_full_path=True))
        child = parent_node.child(row)
        return self.createIndex(row, column, child) if child is not None else QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        node = self._node_for_index(index)
        if node is None or node.parent is None or node.parent is self._root:
            return QModelIndex()
        parent_node = node.parent
        return self.createIndex(parent_node.row(), 0, parent_node)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        parent_node = self._node_for_index(parent)
        if parent_node is None:
            return 0
        if self._mode == "flat" and parent_node is self._root:
            return len(self._entries)
        return parent_node.childCount()

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
        node = self._node_for_index(index)
        if node is None:
            return None
        column = index.column()
        if role == Qt.DisplayRole:
            if node.kind == "file" and isinstance(node.value, int):
                return self._payload_for_file(node.value, show_full_path=self._mode == "flat").columns[column]
            return node.text(column)
        if role == Qt.ToolTipRole:
            if node.kind == "file" and isinstance(node.value, int):
                payload = self._payload_for_file(node.value, show_full_path=self._mode == "flat")
                return payload.tooltip(column)
            return node.toolTip(column)
        if role in (Qt.UserRole, Qt.UserRole + 1, Qt.UserRole + 2):
            return node.data(column, role)
        return None

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        node = self._node_for_index(parent)
        if node is None:
            return False
        if self._mode == "flat" and node is self._root:
            return bool(self._entries)
        if node.kind == "folder":
            key = node.value if isinstance(node.value, tuple) else ()
            return bool(self._tree_child_folders.get(key) or self._tree_direct_files.get(key))
        if node.kind == "category":
            return bool(node.entry_indexes)
        return bool(node.children)

    def canFetchMore(self, parent: QModelIndex) -> bool:
        node = self._node_for_index(parent)
        if node is None or node.kind not in {"folder", "category"}:
            return False
        if node.kind == "category":
            return node.direct_loaded < len(node.entry_indexes)
        key = node.value if isinstance(node.value, tuple) else ()
        direct_files = self._tree_direct_files.get(key, ())
        return (not node.fetched) or node.direct_loaded < len(direct_files)

    def fetchMore(self, parent: QModelIndex) -> None:
        node = self._node_for_index(parent)
        if node is None or node.kind not in {"folder", "category"}:
            return
        new_nodes: List[ArchiveBrowserNode] = []
        if node.kind == "category":
            start = node.direct_loaded
            end = min(len(node.entry_indexes), start + self._fetch_batch_size)
            new_nodes = [
                self._file_node(index, node, show_full_path=True, row_number=start + offset)
                for offset, index in enumerate(node.entry_indexes[start:end])
            ]
            node.direct_loaded = end
            node.fetched = node.direct_loaded >= len(node.entry_indexes)
        else:
            key = node.value if isinstance(node.value, tuple) else ()
            if not node.fetched:
                for _leaf, child_key in self._tree_child_folders.get(key, ()):
                    new_nodes.append(self._folder_node(child_key, node, row_number=len(node.children) + len(new_nodes)))
                node.fetched = True
            direct_files = self._tree_direct_files.get(key, ())
            start = node.direct_loaded
            end = min(len(direct_files), start + self._fetch_batch_size)
            direct_row_base = len(node.children) + len(new_nodes)
            new_nodes.extend(
                self._file_node(index, node, show_full_path=False, row_number=direct_row_base + offset)
                for offset, index in enumerate(direct_files[start:end])
            )
            node.direct_loaded = end
        if not new_nodes:
            return
        insert_at = len(node.children)
        self.beginInsertRows(parent, insert_at, insert_at + len(new_nodes) - 1)
        node.children.extend(new_nodes)
        self.endInsertRows()

    def top_level_node(self, row: int) -> Optional[ArchiveBrowserNode]:
        if self._mode == "flat":
            return self._file_node(row, None, show_full_path=True) if 0 <= row < len(self._entries) else None
        return self._root.child(row)

    def node_from_index(self, index: QModelIndex) -> Optional[ArchiveBrowserNode]:
        node = self._node_for_index(index)
        return None if node is self._root else node

    def entry_indexes_for_node(self, node: Optional[ArchiveBrowserNode]) -> Tuple[int, ...]:
        if node is None:
            return ()
        if node.kind == "file" and isinstance(node.value, int):
            return (int(node.value),)
        return tuple(int(index) for index in node.entry_indexes)

    def find_index_for_entry(self, entry_index: int) -> QModelIndex:
        entry_index = int(entry_index)
        if not (0 <= entry_index < len(self._entries)):
            return QModelIndex()
        if self._mode == "flat":
            return self.index(entry_index, 0, QModelIndex())
        return QModelIndex()


class _ArchiveBrowserHeaderItem:
    def text(self, column: int) -> str:
        return ARCHIVE_BROWSER_COLUMNS[column] if 0 <= column < len(ARCHIVE_BROWSER_COLUMNS) else ""


class ArchiveBrowserTreeView(QTreeView):
    currentItemChanged = Signal(object, object)
    itemSelectionChanged = Signal()
    itemExpanded = Signal(object)
    uiActivity = Signal()

    def __init__(self, title: str = "", detail: str = "", parent: Optional[QObject] = None):
        super().__init__(parent)
        self.empty_title = title
        self.empty_detail = detail
        self._archive_model = ArchiveBrowserModel(self)
        super().setModel(self._archive_model)
        self.setUniformRowHeights(True)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setAnimated(False)
        self.setExpandsOnDoubleClick(True)
        self.expanded.connect(self._handle_expanded_index)
        self._connect_selection_model()

    def _connect_selection_model(self) -> None:
        selection_model = self.selectionModel()
        if selection_model is None:
            return
        selection_model.currentChanged.connect(self._emit_current_item_changed)
        selection_model.selectionChanged.connect(lambda *_args: self.itemSelectionChanged.emit())

    def setModel(self, model) -> None:  # type: ignore[override]
        if model is not self._archive_model:
            raise RuntimeError("ArchiveBrowserTreeView owns its virtual archive model.")
        super().setModel(model)
        self._connect_selection_model()

    def archive_model(self) -> ArchiveBrowserModel:
        return self._archive_model

    def set_archive_providers(self, **kwargs) -> None:
        self._archive_model.set_providers(**kwargs)

    def set_archive_state(self, *args, **kwargs) -> None:
        self._archive_model.set_archive_state(*args, **kwargs)

    def set_empty_state(self, title: str, detail: str = "") -> None:
        self.empty_title = title
        self.empty_detail = detail
        self.viewport().update()

    def setHeaderLabels(self, labels: Sequence[str]) -> None:
        del labels

    def headerItem(self) -> _ArchiveBrowserHeaderItem:
        return _ArchiveBrowserHeaderItem()

    def columnCount(self) -> int:
        return self._archive_model.columnCount()

    def topLevelItemCount(self) -> int:
        return self._archive_model.rowCount(QModelIndex())

    def topLevelItem(self, row: int) -> Optional[ArchiveBrowserNode]:
        return self._archive_model.top_level_node(row)

    def currentItem(self) -> Optional[ArchiveBrowserNode]:
        return self._archive_model.node_from_index(self.currentIndex())

    def selectedItems(self) -> List[ArchiveBrowserNode]:
        selection_model = self.selectionModel()
        if selection_model is None:
            return []
        nodes: List[ArchiveBrowserNode] = []
        seen: set[Tuple[str, object]] = set()
        for index in selection_model.selectedRows(0):
            node = self._archive_model.node_from_index(index)
            if node is None:
                continue
            key = (node.kind, node.value)
            if key in seen:
                continue
            seen.add(key)
            nodes.append(node)
        return nodes

    def itemAt(self, position) -> Optional[ArchiveBrowserNode]:  # type: ignore[override]
        return self._archive_model.node_from_index(self.indexAt(position))

    def setCurrentItem(self, item: Optional[ArchiveBrowserNode]) -> None:
        if item is None:
            self.clearSelection()
            return
        index = self._index_for_node(item)
        selection_model = self.selectionModel()
        if index.isValid() and selection_model is not None:
            self.setCurrentIndex(index)
            selection_model.select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)

    def scrollToItem(self, item: Optional[ArchiveBrowserNode], hint: QAbstractItemView.ScrollHint = QAbstractItemView.EnsureVisible) -> None:
        if item is None:
            return
        index = self._index_for_node(item)
        if index.isValid():
            self.scrollTo(index, hint)

    def find_item_for_entry(self, entry_index: int) -> Optional[ArchiveBrowserNode]:
        index = self._archive_model.find_index_for_entry(entry_index)
        return self._archive_model.node_from_index(index) if index.isValid() else None

    def clear(self) -> None:
        self._archive_model.clear()

    def addTopLevelItem(self, item) -> None:
        del item

    def addTopLevelItems(self, items) -> None:
        del items

    def takeTopLevelItem(self, row: int):
        del row
        return None

    def _index_for_node(self, item: ArchiveBrowserNode) -> QModelIndex:
        if item.kind == "file" and isinstance(item.value, int):
            index = self._archive_model.find_index_for_entry(int(item.value))
            if index.isValid():
                return index
        if item.parent is None:
            return QModelIndex()
        parent_index = QModelIndex() if item.parent.kind == "root" else self._index_for_node(item.parent)
        return self._archive_model.index(item.row(), 0, parent_index)

    def _emit_current_item_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        self.currentItemChanged.emit(
            self._archive_model.node_from_index(current),
            self._archive_model.node_from_index(previous),
        )

    def _handle_expanded_index(self, index: QModelIndex) -> None:
        self.uiActivity.emit()
        if self._archive_model.canFetchMore(index):
            self._archive_model.fetchMore(index)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        self.uiActivity.emit()
        super().wheelEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        self.uiActivity.emit()
        super().resizeEvent(event)

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # type: ignore[override]
        if dx or dy:
            self.uiActivity.emit()
        super().scrollContentsBy(dx, dy)
