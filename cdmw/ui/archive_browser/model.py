from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Callable, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import QAbstractItemModel, QItemSelectionModel, QModelIndex, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QAbstractItemView, QTreeView

from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.remote_flat_view import RemoteArchiveFlatTableView


ARCHIVE_BROWSER_COLUMNS = (
    "Name",
    "Item Name",
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
        self._flat_loaded_count = 0
        self._row_cache: "OrderedDict[Tuple[int, bool], ArchiveBrowserRowPayload]" = OrderedDict()
        self._row_cache_limit = max(1, min(100_000, int(row_cache_limit or 12000)))

    def clear(self) -> None:
        self.beginResetModel()
        self._root.children.clear()
        self._entries = ()
        self._flat_loaded_count = 0
        self._row_cache.clear()
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
        self._flat_loaded_count = min(len(entries), self._fetch_batch_size) if self._mode == "flat" else 0
        self._row_cache.clear()
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

    def invalidate_rows(self, columns: Sequence[int] = ()) -> None:
        self._row_cache.clear()
        normalized_columns = tuple(
            column
            for column in sorted({int(column) for column in columns})
            if 0 <= column < self.columnCount()
        )
        first_column = normalized_columns[0] if normalized_columns else 0
        last_column = normalized_columns[-1] if normalized_columns else self.columnCount() - 1
        roles = [Qt.DisplayRole, Qt.ToolTipRole]

        if self._mode == "flat":
            row_count = self._flat_loaded_count
            if row_count > 0:
                self.dataChanged.emit(
                    self.index(0, first_column),
                    self.index(row_count - 1, last_column),
                    roles,
                )
            return

        def emit_children(parent_node: ArchiveBrowserNode, parent_index: QModelIndex) -> None:
            child_count = parent_node.childCount()
            if child_count <= 0:
                return
            self.dataChanged.emit(
                self.index(0, first_column, parent_index),
                self.index(child_count - 1, last_column, parent_index),
                roles,
            )
            for row, child in enumerate(parent_node.children):
                if child.childCount() > 0:
                    emit_children(child, self.index(row, 0, parent_index))

        emit_children(self._root, QModelIndex())

    def _build_top_level_nodes(self) -> List[ArchiveBrowserNode]:
        if self._mode == "categories":
            nodes: List[ArchiveBrowserNode] = []
            for row_number, (category, indexes) in enumerate(
                sorted(self._category_entry_indexes.items(), key=lambda item: self._category_sort_key(str(item[0])))
            ):
                node = ArchiveBrowserNode(
                    "category",
                    str(category),
                    columns=(f"{category} ({len(indexes):,})", "-", "Category", "-", "-", "-", "-", ""),
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
            columns=(folder_key[-1] if folder_key else "(root)", "-", "Folder", "-", "-", "-", "-", tooltip),
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
            return ArchiveBrowserNode(
                "file",
                int(entry_index),
                parent=None,
                entry_indexes=(int(entry_index),),
                fetched=True,
                columns=(),
                tooltips=(),
                row_number=int(entry_index),
            )
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
        if self._mode == "flat":
            row = int(index.row())
            return self._file_node(row, None, show_full_path=True) if 0 <= row < self._flat_loaded_count else None
        node = index.internalPointer()
        return node if isinstance(node, ArchiveBrowserNode) else None

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if row < 0 or column < 0 or column >= self.columnCount(parent):
            return QModelIndex()
        if self._mode == "flat":
            if parent.isValid() or row >= self._flat_loaded_count:
                return QModelIndex()
            return self.createIndex(row, column)
        parent_node = self._node_for_index(parent)
        if parent_node is None:
            return QModelIndex()
        child = parent_node.child(row)
        return self.createIndex(row, column, child) if child is not None else QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if self._mode == "flat":
            return QModelIndex()
        node = self._node_for_index(index)
        if node is None or node.parent is None or node.parent is self._root:
            return QModelIndex()
        parent_node = node.parent
        return self.createIndex(parent_node.row(), 0, parent_node)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if self._mode == "flat":
            return 0 if parent.isValid() else self._flat_loaded_count
        parent_node = self._node_for_index(parent)
        if parent_node is None:
            return 0
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
        if self._mode == "flat":
            entry_index = int(index.row())
            if not (0 <= entry_index < self._flat_loaded_count):
                return None
            if role == Qt.DisplayRole:
                return self._payload_for_file(entry_index, show_full_path=True).columns[index.column()]
            if role == Qt.ToolTipRole:
                return self._payload_for_file(entry_index, show_full_path=True).tooltip(index.column())
            if role == Qt.UserRole:
                return "file"
            if role == Qt.UserRole + 1:
                return entry_index
            if role == Qt.UserRole + 2:
                return True
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
        if self._mode == "flat":
            return not parent.isValid() and bool(self._entries)
        node = self._node_for_index(parent)
        if node is None:
            return False
        if node.kind == "folder":
            key = node.value if isinstance(node.value, tuple) else ()
            return bool(self._tree_child_folders.get(key) or self._tree_direct_files.get(key))
        if node.kind == "category":
            return bool(node.entry_indexes)
        return bool(node.children)

    def canFetchMore(self, parent: QModelIndex) -> bool:
        if self._mode == "flat":
            return not parent.isValid() and self._flat_loaded_count < len(self._entries)
        node = self._node_for_index(parent)
        if node is None:
            return False
        if node.kind not in {"folder", "category"}:
            return False
        if node.kind == "category":
            return node.direct_loaded < len(node.entry_indexes)
        key = node.value if isinstance(node.value, tuple) else ()
        direct_files = self._tree_direct_files.get(key, ())
        return (not node.fetched) or node.direct_loaded < len(direct_files)

    def fetchMore(self, parent: QModelIndex) -> None:
        if self._mode == "flat":
            if parent.isValid():
                return
            start = self._flat_loaded_count
            end = min(len(self._entries), start + self._fetch_batch_size)
            if end <= start:
                return
            self.beginInsertRows(QModelIndex(), start, end - 1)
            self._flat_loaded_count = end
            self.endInsertRows()
            return
        node = self._node_for_index(parent)
        if node is None:
            return
        if node.kind not in {"folder", "category"}:
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
            return self._file_node(row, None, show_full_path=True) if 0 <= row < self._flat_loaded_count else None
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
            if entry_index >= self._flat_loaded_count:
                return QModelIndex()
            return self.index(entry_index, 0, QModelIndex())
        return QModelIndex()


class _ArchiveBrowserHeaderItem:
    def text(self, column: int) -> str:
        return ARCHIVE_BROWSER_COLUMNS[column] if 0 <= column < len(ARCHIVE_BROWSER_COLUMNS) else ""


class _ArchiveBrowserFlatPlaceholderModel(QAbstractItemModel):
    """Keep the tree header alive while the flat table owns remote rows."""

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        del parent
        return 0

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        del parent
        return len(ARCHIVE_BROWSER_COLUMNS)

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        del row, column, parent
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        del index
        return QModelIndex()

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> object:
        del index, role
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> object:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole and 0 <= section < len(ARCHIVE_BROWSER_COLUMNS):
            return ARCHIVE_BROWSER_COLUMNS[section]
        return None


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
        self._flat_placeholder_model = _ArchiveBrowserFlatPlaceholderModel(self)
        self._active_archive_model: QAbstractItemModel = self._archive_model
        self._remote_archive_model: QAbstractItemModel | None = None
        self._flat_remote_active = False
        self._connected_selection_model: QItemSelectionModel | None = None
        super().setModel(self._archive_model)
        self._flat_table = RemoteArchiveFlatTableView(self.viewport())
        self._flat_table.hide()
        self.setUniformRowHeights(True)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setAnimated(False)
        self.setExpandsOnDoubleClick(True)
        self.expanded.connect(self._handle_expanded_index)
        self._flat_table.uiActivity.connect(self.uiActivity.emit)
        self._flat_table.customContextMenuRequested.connect(self.customContextMenuRequested.emit)
        self._flat_table.horizontalScrollBar().valueChanged.connect(self._sync_flat_header_offset)
        self.header().sectionResized.connect(self._sync_flat_section_width)
        self.header().sectionMoved.connect(lambda *_args: self._sync_flat_columns())
        self.header().geometriesChanged.connect(self._sync_flat_columns)
        self._connect_selection_model()

    def _connect_selection_model(self) -> None:
        selection_model = self.selectionModel()
        if selection_model is None or selection_model is self._connected_selection_model:
            return
        if self._connected_selection_model is not None:
            try:
                self._connected_selection_model.currentChanged.disconnect(self._emit_current_item_changed)
                self._connected_selection_model.selectionChanged.disconnect(self._emit_selection_changed)
            except (RuntimeError, TypeError):
                pass
        selection_model.currentChanged.connect(self._emit_current_item_changed)
        selection_model.selectionChanged.connect(self._emit_selection_changed)
        self._connected_selection_model = selection_model

    def setModel(self, model) -> None:  # type: ignore[override]
        if model not in {self._archive_model, self._remote_archive_model}:
            raise RuntimeError("ArchiveBrowserTreeView owns its archive models.")
        self._active_archive_model = model
        if model is self._archive_model:
            self._activate_tree_model(self._archive_model)
        elif self._remote_view_is_flat():
            self._activate_remote_flat_view()
        else:
            self._activate_tree_model(model)

    def archive_model(self) -> QAbstractItemModel:
        return self._active_archive_model

    def legacy_archive_model(self) -> ArchiveBrowserModel:
        return self._archive_model

    def use_remote_model(self, model: QAbstractItemModel) -> None:
        required = ("node_from_index", "top_level_node", "entry_for_index", "request_visible_rows")
        if any(not callable(getattr(model, name, None)) for name in required):
            raise TypeError("Remote archive model does not provide the browser model contract.")
        if model is not self._remote_archive_model:
            previous_model = self._remote_archive_model
            if previous_model is not None:
                previous_changing = getattr(previous_model, "viewModeChanging", None)
                if previous_changing is not None:
                    try:
                        previous_changing.disconnect(self._handle_remote_view_mode_changing)
                    except (RuntimeError, TypeError):
                        pass
                try:
                    previous_model.modelReset.disconnect(self._handle_remote_model_reset)
                except (RuntimeError, TypeError):
                    pass
            self._remote_archive_model = model
            self._flat_table.setModel(model)
            changing = getattr(model, "viewModeChanging", None)
            if changing is not None:
                changing.connect(self._handle_remote_view_mode_changing)
            model.modelReset.connect(self._handle_remote_model_reset)
        self.setModel(model)
        QTimer.singleShot(0, self._prefetch_visible_remote_rows)

    def use_legacy_model(self) -> None:
        self.setModel(self._archive_model)

    @staticmethod
    def _is_flat_view_mode(view_mode: object) -> bool:
        return str(getattr(view_mode, "value", view_mode) or "").strip().lower() == "flat"

    def _remote_view_is_flat(self) -> bool:
        return self._is_flat_view_mode(getattr(self._remote_archive_model, "view_mode", ""))

    def _handle_remote_view_mode_changing(self, view_mode: object) -> None:
        if not self.remote_model_active():
            return
        QTreeView.setModel(self, self._flat_placeholder_model)
        if self._is_flat_view_mode(view_mode):
            self._activate_remote_flat_view()
        else:
            self._flat_remote_active = False
            self._flat_table.hide()

    def _handle_remote_model_reset(self) -> None:
        if not self.remote_model_active():
            return
        if self._remote_view_is_flat():
            self._activate_remote_flat_view()
        elif self._remote_archive_model is not None:
            self._activate_tree_model(self._remote_archive_model)

    def _activate_remote_flat_view(self) -> None:
        if self._remote_archive_model is None:
            return
        if self._flat_table.model() is not self._remote_archive_model:
            self._flat_table.setModel(self._remote_archive_model)
        if QTreeView.model(self) is not self._flat_placeholder_model:
            QTreeView.setModel(self, self._flat_placeholder_model)
        self._flat_remote_active = True
        QTreeView.setHorizontalScrollBarPolicy(self, Qt.ScrollBarAlwaysOff)
        QTreeView.setVerticalScrollBarPolicy(self, Qt.ScrollBarAlwaysOff)
        self._sync_flat_columns()
        self._flat_table.setGeometry(self.viewport().rect())
        self._flat_table.show()
        self._flat_table.raise_()
        self.setFocusProxy(self._flat_table)
        self._connect_selection_model()

    def _activate_tree_model(self, model: QAbstractItemModel) -> None:
        self._flat_remote_active = False
        self._flat_table.hide()
        QTreeView.setHorizontalScrollBarPolicy(self, Qt.ScrollBarAsNeeded)
        QTreeView.setVerticalScrollBarPolicy(self, Qt.ScrollBarAsNeeded)
        if QTreeView.model(self) is not model:
            QTreeView.setModel(self, model)
        self.header().setOffset(self.horizontalScrollBar().value())
        self.setFocusProxy(None)
        self._connect_selection_model()

    @property
    def remote_flat_view_active(self) -> bool:
        return self._flat_remote_active

    def _sync_flat_section_width(self, logical_index: int, _old_size: int, new_size: int) -> None:
        model = self._flat_table.model()
        if model is not None and 0 <= logical_index < model.columnCount():
            self._flat_table.setColumnWidth(logical_index, new_size)

    def _sync_flat_columns(self) -> None:
        model = self._flat_table.model()
        if model is None:
            return
        outer_header = self.header()
        flat_header = self._flat_table.horizontalHeader()
        column_count = min(outer_header.count(), model.columnCount())
        for logical_index in range(column_count):
            self._flat_table.setColumnHidden(logical_index, self.isColumnHidden(logical_index))
            self._flat_table.setColumnWidth(logical_index, self.columnWidth(logical_index))
        for target_visual in range(column_count):
            logical_index = outer_header.logicalIndex(target_visual)
            current_visual = flat_header.visualIndex(logical_index)
            if current_visual >= 0 and current_visual != target_visual:
                flat_header.moveSection(current_visual, target_visual)
        self._sync_flat_header_offset(self._flat_table.horizontalScrollBar().value())

    def _sync_flat_header_offset(self, value: int) -> None:
        if self._flat_remote_active:
            self.header().setOffset(value)

    def selectionModel(self):  # type: ignore[override]
        flat_table = getattr(self, "_flat_table", None)
        if getattr(self, "_flat_remote_active", False) and flat_table is not None:
            return flat_table.selectionModel()
        return QTreeView.selectionModel(self)

    def currentIndex(self) -> QModelIndex:  # type: ignore[override]
        if getattr(self, "_flat_remote_active", False):
            return self._flat_table.currentIndex()
        return QTreeView.currentIndex(self)

    def setCurrentIndex(self, index: QModelIndex) -> None:  # type: ignore[override]
        if getattr(self, "_flat_remote_active", False):
            self._flat_table.setCurrentIndex(index)
            return
        QTreeView.setCurrentIndex(self, index)

    def clearSelection(self) -> None:  # type: ignore[override]
        if getattr(self, "_flat_remote_active", False):
            self._flat_table.clearSelection()
            return
        QTreeView.clearSelection(self)

    def scrollTo(
        self,
        index: QModelIndex,
        hint: QAbstractItemView.ScrollHint = QAbstractItemView.EnsureVisible,
    ) -> None:  # type: ignore[override]
        if getattr(self, "_flat_remote_active", False):
            self._flat_table.scrollTo(index, hint)
            return
        QTreeView.scrollTo(self, index, hint)

    def indexAt(self, point) -> QModelIndex:  # type: ignore[override]
        if getattr(self, "_flat_remote_active", False):
            return self._flat_table.indexAt(point)
        return QTreeView.indexAt(self, point)

    def setSelectionMode(self, mode: QAbstractItemView.SelectionMode) -> None:  # type: ignore[override]
        QTreeView.setSelectionMode(self, mode)
        flat_table = getattr(self, "_flat_table", None)
        if flat_table is not None:
            flat_table.setSelectionMode(mode)

    def setSelectionBehavior(self, behavior: QAbstractItemView.SelectionBehavior) -> None:  # type: ignore[override]
        QTreeView.setSelectionBehavior(self, behavior)
        flat_table = getattr(self, "_flat_table", None)
        if flat_table is not None:
            flat_table.setSelectionBehavior(behavior)

    def setAlternatingRowColors(self, enable: bool) -> None:  # type: ignore[override]
        QTreeView.setAlternatingRowColors(self, enable)
        flat_table = getattr(self, "_flat_table", None)
        if flat_table is not None:
            flat_table.setAlternatingRowColors(enable)

    def setContextMenuPolicy(self, policy: Qt.ContextMenuPolicy) -> None:  # type: ignore[override]
        QTreeView.setContextMenuPolicy(self, policy)
        flat_table = getattr(self, "_flat_table", None)
        if flat_table is not None:
            flat_table.setContextMenuPolicy(policy)

    def setColumnHidden(self, column: int, hide: bool) -> None:  # type: ignore[override]
        QTreeView.setColumnHidden(self, column, hide)
        flat_table = getattr(self, "_flat_table", None)
        if flat_table is not None:
            flat_table.setColumnHidden(column, hide)

    def setUpdatesEnabled(self, enable: bool) -> None:  # type: ignore[override]
        QTreeView.setUpdatesEnabled(self, enable)
        flat_table = getattr(self, "_flat_table", None)
        if flat_table is not None:
            flat_table.setUpdatesEnabled(enable)

    def remote_model_active(self) -> bool:
        return self._remote_archive_model is not None and self._active_archive_model is self._remote_archive_model

    def set_archive_providers(self, **kwargs) -> None:
        self._archive_model.set_providers(**kwargs)

    def set_archive_state(self, *args, **kwargs) -> None:
        self.use_legacy_model()
        self._archive_model.set_archive_state(*args, **kwargs)

    def invalidate_archive_rows(self, columns: Sequence[int] = ()) -> None:
        self._archive_model.invalidate_rows(columns)

    def compact_hidden_columns(self) -> None:
        header = self.header()
        if header is None:
            return
        visible_columns: List[int] = []
        hidden_columns: List[int] = []
        for visual_index in range(header.count()):
            logical_index = int(header.logicalIndex(visual_index))
            if logical_index < 0:
                continue
            if self.isColumnHidden(logical_index):
                hidden_columns.append(logical_index)
            else:
                visible_columns.append(logical_index)
        for target_visual, logical_index in enumerate(visible_columns + hidden_columns):
            current_visual = int(header.visualIndex(logical_index))
            if current_visual >= 0 and current_visual != target_visual:
                header.moveSection(current_visual, target_visual)
        self.doItemsLayout()
        header.update()
        self.viewport().update()

    def set_empty_state(self, title: str, detail: str = "") -> None:
        self.empty_title = title
        self.empty_detail = detail
        self.viewport().update()

    def setHeaderLabels(self, labels: Sequence[str]) -> None:
        del labels

    def headerItem(self) -> _ArchiveBrowserHeaderItem:
        return _ArchiveBrowserHeaderItem()

    def columnCount(self) -> int:
        return self._active_archive_model.columnCount()

    def topLevelItemCount(self) -> int:
        return self._active_archive_model.rowCount(QModelIndex())

    def topLevelItem(self, row: int) -> Optional[ArchiveBrowserNode]:
        provider = getattr(self._active_archive_model, "top_level_node", None)
        return provider(row) if callable(provider) else None

    def currentItem(self) -> Optional[ArchiveBrowserNode]:
        provider = getattr(self._active_archive_model, "node_from_index", None)
        return provider(self.currentIndex()) if callable(provider) else None

    def selectedItems(self) -> List[ArchiveBrowserNode]:
        selection_model = self.selectionModel()
        if selection_model is None:
            return []
        nodes: List[ArchiveBrowserNode] = []
        seen: set[Tuple[str, object]] = set()
        for index in selection_model.selectedRows(0):
            provider = getattr(self._active_archive_model, "node_from_index", None)
            node = provider(index) if callable(provider) else None
            if node is None:
                continue
            key = (node.kind, node.value)
            if key in seen:
                continue
            seen.add(key)
            nodes.append(node)
        return nodes

    def itemAt(self, position) -> Optional[ArchiveBrowserNode]:  # type: ignore[override]
        provider = getattr(self._active_archive_model, "node_from_index", None)
        return provider(self.indexAt(position)) if callable(provider) else None

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
        finder_name = "find_index_for_entry_id" if self.remote_model_active() else "find_index_for_entry"
        finder = getattr(self._active_archive_model, finder_name, None)
        provider = getattr(self._active_archive_model, "node_from_index", None)
        index = finder(entry_index) if callable(finder) else QModelIndex()
        return provider(index) if index.isValid() and callable(provider) else None

    def _index_for_node(self, item: ArchiveBrowserNode) -> QModelIndex:
        direct = getattr(self._active_archive_model, "index_for_node", None)
        if callable(direct):
            return direct(item)
        if item.kind == "file" and isinstance(item.value, int):
            finder = getattr(self._active_archive_model, "find_index_for_entry", None)
            index = finder(int(item.value)) if callable(finder) else QModelIndex()
            if index.isValid():
                return index
        if item.parent is None:
            return QModelIndex()
        parent_index = QModelIndex() if item.parent.kind == "root" else self._index_for_node(item.parent)
        return self._active_archive_model.index(item.row(), 0, parent_index)

    def _emit_current_item_changed(self, current: QModelIndex, previous: QModelIndex) -> None:
        provider = getattr(self._active_archive_model, "node_from_index", None)
        self.currentItemChanged.emit(
            provider(current) if callable(provider) else None,
            provider(previous) if callable(provider) else None,
        )

    def _emit_selection_changed(self, *_args) -> None:
        self.itemSelectionChanged.emit()

    def _handle_expanded_index(self, index: QModelIndex) -> None:
        self.uiActivity.emit()
        if self._active_archive_model.canFetchMore(index):
            self._active_archive_model.fetchMore(index)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        self.uiActivity.emit()
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.RightButton:
            self.uiActivity.emit()
            event.accept()
            return
        self.uiActivity.emit()
        super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        self.uiActivity.emit()
        super().resizeEvent(event)
        if self._flat_remote_active:
            self._flat_table.setGeometry(self.viewport().rect())
        self._prefetch_visible_remote_rows()

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # type: ignore[override]
        if dx or dy:
            self.uiActivity.emit()
        super().scrollContentsBy(dx, dy)
        self._prefetch_visible_remote_rows()

    def _prefetch_visible_remote_rows(self) -> None:
        if not self.remote_model_active():
            return
        requester = getattr(self._active_archive_model, "request_visible_rows", None)
        if not callable(requester):
            return
        first = self.indexAt(QPoint(0, 0))
        last = self.indexAt(QPoint(0, max(0, self.viewport().height() - 1)))
        if not first.isValid():
            return
        last_row = last.row() if last.isValid() else first.row()
        requester(first.row(), max(first.row(), last_row))
