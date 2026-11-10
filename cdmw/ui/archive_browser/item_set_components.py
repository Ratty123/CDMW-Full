"""Source-file and part visibility for a resident worn-set preview."""
from __future__ import annotations

from pathlib import PurePosixPath
from collections.abc import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget


def _path_key(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().casefold()


class ItemSetComponentsWidget(QWidget):
    visibilityChanged = Signal(object)
    highlightRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.active = False
        self._updating = False
        self._scope: tuple[str, ...] = ()
        self._hidden_keys: set[tuple[str, int]] = set()
        self._keys: dict[int, tuple[str, int]] = {}
        self._parts: dict[int, QTreeWidgetItem] = {}
        self._groups: dict[str, QTreeWidgetItem] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Set components"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(150)
        layout.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        self.show_all_button = QPushButton("Show all")
        self.isolate_button = QPushButton("Isolate")
        self.isolate_button.setEnabled(False)
        buttons.addWidget(self.show_all_button)
        buttons.addWidget(self.isolate_button)
        layout.addLayout(buttons)
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
        self.tree.clear()
        self.hide()

    def set_parts(self, batches: list[object], paths: tuple[str, ...]) -> None:
        scope = tuple(_path_key(path) for path in paths)
        if scope != self._scope:
            self._hidden_keys.clear()
        self._scope = scope
        self._updating = True
        try:
            self.tree.clear()
            self._keys.clear()
            self._parts.clear()
            self._groups.clear()
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
                group = self._groups.get(path)
                if group is None:
                    group = QTreeWidgetItem(self.tree, [PurePosixPath(path).name])
                    group.setToolTip(0, path)
                    group.setFlags(group.flags() | Qt.ItemIsUserCheckable)
                    self._groups[path] = group
                label = str(identity.get("part_label") or "")
                if not label or label.casefold() == PurePosixPath(path).name:
                    label = str(batch.get("material_name") or local)
                part = QTreeWidgetItem(group, [label])
                part.setFlags(part.flags() | Qt.ItemIsUserCheckable)
                part.setData(0, Qt.UserRole, index)
                self._parts[index] = part
                self._keys[index] = (path, local)
                part.setCheckState(0, Qt.Unchecked if (path, local) in self._hidden_keys else Qt.Checked)
            self._hidden_keys.intersection_update(self._keys.values())
            self._sync_group_checks()
            self.tree.expandAll()
        finally:
            self._updating = False
        self.active = bool(self._parts)
        self.setVisible(self.active)

    @property
    def hidden_indices(self) -> tuple[int, ...]:
        return tuple(index for index, key in self._keys.items() if key in self._hidden_keys)

    def _sync_group_checks(self) -> None:
        for group in self._groups.values():
            checked = sum(group.child(i).checkState(0) == Qt.Checked for i in range(group.childCount()))
            group.setCheckState(0, Qt.Checked if checked == group.childCount()
                               else Qt.Unchecked if checked == 0 else Qt.PartiallyChecked)

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 0:
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
        if group is None:
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

    def _current_changed(self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None) -> None:
        if not self._updating:
            self.isolate_button.setEnabled(current is not None)
            self.highlightRequested.emit(self._indices_for(current))

    def _isolate(self) -> None:
        selected = set(self._indices_for(self.tree.currentItem()))
        if selected:
            self.set_hidden_indices(set(self._parts) - selected)
