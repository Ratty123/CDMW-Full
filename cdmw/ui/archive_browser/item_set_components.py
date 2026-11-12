"""The Scene panel (P5): files and parts of the model a 3D preview shows.

One group per source file with its parts underneath and a visibility tick per
part and per file. It is shown beside every 3D preview, not only Item Finder
sets. A prefab component that is not loaded yet (such as a sword's ``_in.pac``
scabbard) is listed as its own file, unticked; ticking it loads it.

A context menu on parts and files offers Isolate, Show all, Hide, Preview only
this file, Open in Mesh Editor and Open ticked parts in Mesh Editor. The Parts
dropdown above the preview stays a shortcut to the same state.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

#: The one label for opening the ticked files as one session (P5).
OPEN_TICKED_LABEL = "Open ticked parts in Mesh Editor"
_PREFAB_ROLE = Qt.UserRole + 1


def _path_key(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().casefold()


class ItemSetComponentsWidget(QWidget):
    """The Scene panel; the historical name is kept for its callers."""

    visibilityChanged = Signal(object)
    highlightRequested = Signal(object)
    #: Open ticked parts in Mesh Editor (the button and the context menu).
    editSetRequested = Signal()
    #: (path, enabled): a prefab component file was ticked or unticked; loading it is the host's.
    prefabComponentToggled = Signal(str, bool)
    #: Open in Mesh Editor on one file, by its path.
    openFileRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ScenePanel")
        self.active = False
        self._updating = False
        self._scope: tuple[str, ...] = ()
        self._hidden_keys: set[tuple[str, int]] = set()
        self._keys: dict[int, tuple[str, int]] = {}
        self._parts: dict[int, QTreeWidgetItem] = {}
        self._groups: dict[str, QTreeWidgetItem] = {}
        #: Prefab component files listed but not loaded: path key -> group item.
        self._prefab_groups: dict[str, QTreeWidgetItem] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Scene"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(150)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        self.show_all_button = QPushButton("Show all")
        self.isolate_button = QPushButton("Isolate")
        self.isolate_button.setEnabled(False)
        buttons.addWidget(self.show_all_button)
        buttons.addWidget(self.isolate_button)
        layout.addLayout(buttons)
        self.edit_set_button = QPushButton(OPEN_TICKED_LABEL)
        self.edit_set_button.clicked.connect(self.editSetRequested.emit)
        layout.addWidget(self.edit_set_button)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.currentItemChanged.connect(self._current_changed)
        self.show_all_button.clicked.connect(lambda: self.set_hidden_indices(()))
        self.isolate_button.clicked.connect(self._isolate)
        self.hide()

    def reset(self) -> None:
        self.active = False
        self._scope = ()
        self._hidden_keys.clear()
        self._keys.clear()
        self._parts.clear()
        self._groups.clear()
        self._prefab_groups.clear()
        self.tree.clear()
        self.hide()

    def set_parts(self, batches: list[object], paths: tuple[str, ...] = (), *,
                  prefab_components: Iterable[tuple[str, str]] = ()) -> None:
        """Show the parts of ``batches``.

        ``paths`` limits the panel to those files (an Item Finder set); empty
        means every file the batches name. ``prefab_components`` lists (path,
        label) of components that can be loaded; one the batches do not hold
        yet is shown unticked.
        """

        loaded_paths = tuple(dict.fromkeys(
            _path_key(batch.get("editor_identity", {}).get("source_model_path"))
            for batch in batches
            if isinstance(batch, Mapping) and isinstance(batch.get("editor_identity"), Mapping)
        ))
        scope = tuple(_path_key(path) for path in paths) or tuple(path for path in loaded_paths if path)
        if scope != self._scope and not (set(scope) & set(self._scope)):
            self._hidden_keys.clear()
        self._scope = scope
        self._updating = True
        try:
            self.tree.clear()
            self._keys.clear()
            self._parts.clear()
            self._groups.clear()
            self._prefab_groups.clear()
            for batch in batches:
                if not isinstance(batch, Mapping):
                    continue
                identity = batch.get("editor_identity") or {}
                if not isinstance(identity, Mapping):
                    continue
                path = _path_key(identity.get("source_model_path") or (paths[0] if paths else ""))
                if path not in scope:
                    continue
                try:
                    index = int(identity.get("source_submesh_index", batch.get("index", -1)))
                    local = int(identity.get("source_local_submesh_index", index))
                except (TypeError, ValueError):
                    continue
                if index < 0 or index in self._parts:
                    continue
                group = self._group(path)
                label = str(identity.get("part_label") or "")
                if not label or label.casefold() == PurePosixPath(path).name:
                    label = str(batch.get("material_name") or local)
                part = QTreeWidgetItem(group, [label])
                part.setFlags(part.flags() | Qt.ItemIsUserCheckable)
                part.setData(0, Qt.UserRole, index)
                self._parts[index] = part
                self._keys[index] = (path, local)
                part.setCheckState(0, Qt.Unchecked if (path, local) in self._hidden_keys else Qt.Checked)
            for raw_path, label in prefab_components:
                path = _path_key(raw_path)
                if not path or path in self._groups:
                    continue
                # Listed, not loaded: ticking it asks the host to load it.
                group = self._group(path, label=str(label or PurePosixPath(path).name))
                group.setData(0, _PREFAB_ROLE, path)
                group.setToolTip(0, f"Tick to load this prefab component: {raw_path}")
                group.setCheckState(0, Qt.Unchecked)
                self._prefab_groups[path] = group
            self._hidden_keys.intersection_update(self._keys.values())
            self._sync_group_checks()
            self.tree.expandAll()
        finally:
            self._updating = False
        self.active = bool(self._parts)
        self.edit_set_button.setEnabled(bool(self._parts))
        self.setVisible(self.active)

    def _group(self, path: str, *, label: str = "") -> QTreeWidgetItem:
        group = self._groups.get(path)
        if group is None:
            group = QTreeWidgetItem(self.tree, [label or PurePosixPath(path).name])
            group.setToolTip(0, path)
            group.setFlags(group.flags() | Qt.ItemIsUserCheckable)
            self._groups[path] = group
        return group

    @property
    def hidden_indices(self) -> tuple[int, ...]:
        return tuple(index for index, key in self._keys.items() if key in self._hidden_keys)

    def ticked_files(self) -> tuple[tuple[str, tuple[int, ...]], ...]:
        """Each loaded file with at least one ticked part, and the local parts left unticked."""

        files: dict[str, tuple[list[int], list[int]]] = {}
        for index, (path, local) in self._keys.items():
            ticked, unticked = files.setdefault(path, ([], []))
            (unticked if (path, local) in self._hidden_keys else ticked).append(local)
        return tuple((path, tuple(sorted(unticked))) for path, (ticked, unticked) in files.items() if ticked)

    def _sync_group_checks(self) -> None:
        for path, group in self._groups.items():
            if path in self._prefab_groups:
                continue
            checked = sum(group.child(i).checkState(0) == Qt.Checked for i in range(group.childCount()))
            group.setCheckState(0, Qt.Checked if checked == group.childCount()
                               else Qt.Unchecked if checked == 0 else Qt.PartiallyChecked)

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 0:
            return
        prefab_path = item.data(0, _PREFAB_ROLE)
        if prefab_path:
            self.prefabComponentToggled.emit(str(prefab_path), item.checkState(0) == Qt.Checked)
            return
        self._updating = True
        try:
            if item.parent() is None:
                for i in range(item.childCount()):
                    item.child(i).setCheckState(0, item.checkState(0))
            self._hidden_keys = {self._keys[index] for index, part in self._parts.items()
                                 if part.checkState(0) != Qt.Checked}
            self._sync_group_checks()
        finally:
            self._updating = False
        self.visibilityChanged.emit(self.hidden_indices)

    def set_hidden_indices(self, indices: object) -> None:
        hidden = set(indices)
        self._updating = True
        try:
            self._hidden_keys = {key for index, key in self._keys.items() if index in hidden}
            for index, part in self._parts.items():
                part.setCheckState(0, Qt.Unchecked if index in hidden else Qt.Checked)
            self._sync_group_checks()
        finally:
            self._updating = False
        self.visibilityChanged.emit(self.hidden_indices)

    def set_group_visible(self, path: str, visible: bool) -> bool:
        group = self._groups.get(_path_key(path))
        if group is None or _path_key(path) in self._prefab_groups:
            return False
        indices = {index for index, key in self._keys.items() if key[0] == _path_key(path)}
        hidden = set(self.hidden_indices)
        if visible:
            hidden.difference_update(indices)
        else:
            hidden.update(indices)
        self.set_hidden_indices(hidden)
        return True

    def highlight_path(self, path: str) -> None:
        group = self._groups.get(_path_key(path))
        self.tree.setCurrentItem(group)
        if group is not None:
            self.tree.scrollToItem(group)
        self._current_changed(group, None)

    def _indices_for(self, item: QTreeWidgetItem | None) -> tuple[int, ...]:
        if item is None:
            return ()
        if item.parent() is not None:
            return (int(item.data(0, Qt.UserRole)),)
        return tuple(int(item.child(i).data(0, Qt.UserRole)) for i in range(item.childCount()))

    def _path_of(self, item: QTreeWidgetItem | None) -> str:
        while item is not None and item.parent() is not None:
            item = item.parent()
        return next((path for path, group in self._groups.items() if group is item), "")

    def _current_changed(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        if not self._updating:
            self.isolate_button.setEnabled(bool(self._indices_for(current)))
            self.highlightRequested.emit(self._indices_for(current))

    def _isolate(self) -> None:
        self.isolate_item(self.tree.currentItem())

    def isolate_item(self, item: QTreeWidgetItem | None) -> None:
        selected = set(self._indices_for(item))
        if selected:
            self.set_hidden_indices(set(self._parts) - selected)

    def hide_item(self, item: QTreeWidgetItem | None) -> None:
        self.set_hidden_indices(set(self.hidden_indices) | set(self._indices_for(item)))

    # ----- the context menu ---------------------------------------------------
    def context_actions(self, item: QTreeWidgetItem | None) -> list[tuple[str, object, bool]]:
        """(label, call, enabled) for the menu on ``item``; the menu and tests share it."""

        path = self._path_of(item)
        loaded = bool(self._indices_for(item))
        group = self._groups.get(path)
        return [
            ("Isolate", lambda: self.isolate_item(item), loaded),
            ("Show all", lambda: self.set_hidden_indices(()), bool(self._parts)),
            ("Hide", lambda: self.hide_item(item), loaded),
            ("Preview only this file", lambda: self.isolate_item(group), bool(group is not None and loaded)),
            ("Open in Mesh Editor", lambda: self.openFileRequested.emit(path), bool(path) and loaded),
            (OPEN_TICKED_LABEL, self.editSetRequested.emit, bool(self.ticked_files())),
        ]

    def _show_context_menu(self, position: QPoint) -> None:
        item = self.tree.itemAt(position)
        menu = QMenu(self)
        for label, call, enabled in self.context_actions(item):
            action = menu.addAction(label)
            action.setEnabled(enabled)
            action.triggered.connect(lambda _checked=False, run=call: run())
        menu.exec(self.tree.viewport().mapToGlobal(position))
        menu.deleteLater()


#: The panel's name since P5.
ScenePanel = ItemSetComponentsWidget

__all__ = ["ItemSetComponentsWidget", "OPEN_TICKED_LABEL", "ScenePanel"]
