"""The Scene panel (P5): files and parts of the model a 3D preview shows.

One group per source file with its parts underneath and a visibility tick per
part and per file. It is shown beside every 3D preview, not only Item Finder
sets. A prefab component that is not loaded yet (such as a sword's ``_in.pac``
scabbard) is listed as its own file, unticked; ticking it loads it.

A context menu on parts and files offers Isolate, Show all, Hide, Preview only
this file, Open in Mesh Editor and Open ticked parts in Mesh Editor. It is the
one place to show, hide and load parts: the Parts dropdown that used to sit above
Browse's preview was removed (2026-11-21).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath

import shiboken6
from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.layout_utils import scaled_px

#: The one label for opening the ticked files as one session (P5).
OPEN_TICKED_LABEL = "Open ticked parts in Mesh Editor"
_PREFAB_ROLE = Qt.UserRole + 1
#: The panel's width, remembered across previews and restarts.
WIDTH_KEY = "scene_panel/width"
DEFAULT_WIDTH = 320
MINIMUM_WIDTH = 200
ISOLATE_HINT = "Select a part or a file to isolate it."
ISOLATE_TIP = "Show only the selected part or file."


def part_number_label(local: int) -> str:
    """A part's place in its file, counted from 1 as a person counts."""

    return "part {number}".format(number=int(local) + 1)


#: A loaded file row's part count.
_STATE_COLUMN = 1


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

    def __init__(self, parent: QWidget | None = None, *, opens_editor: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("ScenePanel")
        #: False beside a preview that cannot open the Mesh Editor: visibility actions only.
        self.opens_editor = bool(opens_editor)
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
        # Laid out as the app's other side panels: a section title, the list, then the actions.
        layout.setContentsMargins(scaled_px(6, self), scaled_px(4, self), 0, 0)
        layout.setSpacing(scaled_px(6, self))
        self.title_label = QLabel("Scene")
        self.title_label.setObjectName("FlatSectionTitle")
        layout.addWidget(self.title_label)
        self.tree = QTreeWidget()
        self.tree.setObjectName("ScenePanelTree")
        self.tree.setHeaderHidden(True)
        # The name, and a narrow column with a loaded file's part count.
        self.tree.setColumnCount(2)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        # Wide enough for a three-digit part count and the cell padding: never clipped.
        header.setSectionResizeMode(_STATE_COLUMN, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(_STATE_COLUMN, self.tree.fontMetrics().horizontalAdvance("0000") + scaled_px(16, self))
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(scaled_px(16, self))
        # The end of a part or file name tells similar ones apart, so cut the middle.
        self.tree.setTextElideMode(Qt.ElideMiddle)
        self.tree.setMinimumWidth(scaled_px(MINIMUM_WIDTH - 12, self))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        # Hovering a row highlights it in the view; a click selects it; clicking empty
        # space in the list or Esc clears it. Nothing is selected when a model is shown.
        self.tree.setMouseTracking(True)
        self.tree.itemEntered.connect(self._item_hovered)
        self.tree.viewport().installEventFilter(self)
        self.tree.installEventFilter(self)
        layout.addWidget(self.tree, 1)
        buttons = QHBoxLayout()
        buttons.setSpacing(scaled_px(6, self))
        self.show_all_button = QPushButton("Show all")
        self.isolate_button = QPushButton("Isolate")
        self.isolate_button.setEnabled(False)
        self.isolate_button.setToolTip(ISOLATE_HINT)
        buttons.addWidget(self.show_all_button)
        buttons.addWidget(self.isolate_button)
        layout.addLayout(buttons)
        self.edit_set_button = QPushButton(OPEN_TICKED_LABEL)
        self.edit_set_button.setObjectName("EditorPrimaryButton")
        self.edit_set_button.clicked.connect(self.editSetRequested.emit)
        layout.addWidget(self.edit_set_button)
        self.setMinimumWidth(scaled_px(MINIMUM_WIDTH, self))
        self.edit_set_button.setVisible(self.opens_editor)
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
                # The PAC submesh's own name, as the Mesh Editor's Parts list shows it;
                # part_label is the file's label (or the material) and is a fallback only.
                label = str(identity.get("part_name") or identity.get("part_label") or "")
                material = str(batch.get("material_name") or "")
                if not label or label.casefold() == PurePosixPath(path).name:
                    label = material or str(local)
                part = QTreeWidgetItem(group, [label])
                part.setFlags(part.flags() | Qt.ItemIsUserCheckable)
                part.setData(0, Qt.UserRole, index)
                part.setData(0, _LABEL_ROLE, (label, material, local))
                self._parts[index] = part
                self._keys[index] = (path, local)
                part.setCheckState(0, Qt.Unchecked if (path, local) in self._hidden_keys else Qt.Checked)
            for raw_path, label in prefab_components:
                path = _path_key(raw_path)
                if not path or path in self._groups:
                    continue
                # Listed, not loaded: ticking it asks the host to load it.
                group = self._group(path, label=str(label or PurePosixPath(path).stem))
                group.setData(0, _PREFAB_ROLE, path)
                group.setToolTip(0, f"Tick to load this prefab component: {raw_path}")
                group.setCheckState(0, Qt.Unchecked)
                self._prefab_groups[path] = group
            self._hidden_keys.intersection_update(self._keys.values())
            self._order_files_as_the_set(scope)
            self._label_rows()
            self._sync_group_checks()
            self.tree.expandAll()
        finally:
            self._updating = False
        self.active = bool(self._parts)
        self.edit_set_button.setEnabled(bool(self._parts))
        self.setVisible(self.active)

    def _order_files_as_the_set(self, scope: tuple[str, ...]) -> None:
        """Files in the set's own order, the order the Mesh Editor's Parts list uses
        (Fredric, 2026-11-16: the same parts in the same order in both lists); listed but
        not loaded prefab components stay after them."""

        if self.tree.topLevelItemCount() < 2:
            return
        order = {path: index for index, path in enumerate(scope)}
        path_of = {id(group): path for path, group in self._groups.items()}
        groups = [self.tree.takeTopLevelItem(0) for _ in range(self.tree.topLevelItemCount())]
        groups.sort(key=lambda group: (path_of.get(id(group), "") in self._prefab_groups,
                                       order.get(path_of.get(id(group), ""), len(order))))
        self.tree.addTopLevelItems(groups)

    def _group(self, path: str, *, label: str = "") -> QTreeWidgetItem:
        group = self._groups.get(path)
        if group is None:
            # The file's stem: the extension is the same for every file, the tooltip has the path.
            group = QTreeWidgetItem(self.tree, [label or PurePosixPath(path).stem])
            group.setToolTip(0, path)
            group.setFlags(group.flags() | Qt.ItemIsUserCheckable)
            # Files read as headings over their parts.
            font = group.font(0)
            font.setBold(True)
            group.setFont(0, font)
            self._groups[path] = group
        return group

    def _label_rows(self) -> None:
        """Name every row in full in its tooltip, count each file's parts, and tell
        parts apart that share a name (by material, else by their number)."""

        muted = self.palette().placeholderText()
        for path, group in self._groups.items():
            name = PurePosixPath(path).name
            group.setTextAlignment(_STATE_COLUMN, Qt.AlignRight | Qt.AlignVCenter)
            group.setForeground(_STATE_COLUMN, muted)
            if path in self._prefab_groups:
                # Listed, not loaded: muted, no count, its whole name (its tooltip says to tick it).
                font = group.font(0)
                font.setBold(False)
                group.setFont(0, font)
                group.setForeground(0, muted)
                self.tree.setFirstColumnSpanned(self.tree.indexOfTopLevelItem(group), self.tree.rootIndex(), True)
                continue
            group.setText(_STATE_COLUMN, str(group.childCount()))
            rows = [group.child(i) for i in range(group.childCount())]
            parent_index = self.tree.indexOfTopLevelItem(group)
            for row_number in range(len(rows)):
                # A part row has no state: its name takes the full width.
                self.tree.setFirstColumnSpanned(row_number, self.tree.model().index(parent_index, 0), True)
            names: dict[str, list[QTreeWidgetItem]] = {}
            for row in rows:
                label, _material, _local = row.data(0, _LABEL_ROLE)
                names.setdefault(label.casefold(), []).append(row)
            for same in names.values():
                materials = {row.data(0, _LABEL_ROLE)[1].casefold() for row in same}
                for row in same:
                    label, material, local = row.data(0, _LABEL_ROLE)
                    if len(same) > 1:
                        detail = (material if material and len(materials) == len(same)
                                  else part_number_label(local))
                        row.setText(0, f"{label} \u00b7 {detail}")
                    row.setToolTip(0, "\n".join(text for text in (label, material, name) if text))

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
        """Bring a file's row into view. It is not selected and nothing is highlighted in
        the 3D view: that waits for a hover or a click (Fredric, 2026-11-15)."""

        group = self._groups.get(_path_key(path))
        if group is not None:
            self.tree.scrollToItem(group)

    def clear_selection(self) -> None:
        """No part or file selected: the view shows no selection wire."""

        self.tree.setCurrentItem(None)
        self.tree.clearSelection()
        self._current_changed(None, None)

    def hover_part(self, index: int) -> None:
        """A part under the pointer in the 3D view (-1: none) is highlighted while hovered."""

        part = self._parts.get(int(index))
        if part is None:
            self._restore_highlight()
        elif not self._updating:
            self.highlightRequested.emit((int(index),))

    def select_part(self, index: int) -> None:
        """A part clicked in the 3D view is selected here too; -1 (empty space) clears."""

        part = self._parts.get(int(index))
        if part is None:
            self.clear_selection()
            return
        self.tree.setCurrentItem(part)
        self.tree.scrollToItem(part)

    def _item_hovered(self, item: QTreeWidgetItem) -> None:
        if not self._updating and self._indices_for(item):
            self.highlightRequested.emit(self._indices_for(item))

    def _restore_highlight(self) -> None:
        if not self._updating:
            current = self.tree.currentItem() if self.tree.selectedItems() else None
            self.highlightRequested.emit(self._indices_for(current))

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        kind = event.type()
        if watched is self.tree.viewport():
            if kind == QEvent.Type.Leave:
                self._restore_highlight()
            elif kind == QEvent.Type.MouseButtonPress and self.tree.itemAt(event.position().toPoint()) is None:
                self.clear_selection()
        elif watched is self.tree and kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.clear_selection()
            return True
        return False

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
            if current is not None and not current.isSelected():
                current = None  # a current row that is not selected highlights nothing
            selected = bool(self._indices_for(current))
            self.isolate_button.setEnabled(selected)
            self.isolate_button.setToolTip(ISOLATE_TIP if selected else ISOLATE_HINT)
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
        actions = [
            ("Isolate", lambda: self.isolate_item(item), loaded),
            ("Show all", lambda: self.set_hidden_indices(()), bool(self._parts)),
            ("Hide", lambda: self.hide_item(item), loaded),
            ("Preview only this file", lambda: self.isolate_item(group), bool(group is not None and loaded)),
        ]
        if self.opens_editor:
            actions += [
                ("Open in Mesh Editor", lambda: self.openFileRequested.emit(path), bool(path) and loaded),
                (OPEN_TICKED_LABEL, self.editSetRequested.emit, bool(self.ticked_files())),
            ]
        return actions

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
_LABEL_ROLE = Qt.UserRole + 2


def remember_scene_panel_width(splitter: QSplitter, panel: QWidget, settings: object | None = None) -> None:
    """Let ``splitter`` resize the panel and keep its width in the app's settings.

    One width for every preview's panel: dragging it in one place widens it everywhere
    it is shown next.
    """

    if settings is None:
        from cdmw.services.settings_service import app_settings

        settings = app_settings()
    index = splitter.indexOf(panel)
    if index < 0:
        return
    splitter.setChildrenCollapsible(False)
    splitter.setStretchFactor(index, 0)
    for other in range(splitter.count()):
        if other != index:
            splitter.setStretchFactor(other, 1)
    try:
        stored = int(settings.value(WIDTH_KEY, 0) or 0)
    except (TypeError, ValueError):
        stored = 0
    width = max(scaled_px(MINIMUM_WIDTH, panel), stored or scaled_px(DEFAULT_WIDTH, panel))
    panel.setProperty("_scene_panel_width", width)

    def apply() -> None:
        if not shiboken6.isValid(splitter) or not shiboken6.isValid(panel):
            return
        sizes = splitter.sizes()
        total = sum(sizes)
        if total <= width or index >= len(sizes):
            return
        rest = [size for i, size in enumerate(sizes) if i != index]
        share = (total - width) / max(1, sum(rest)) if sum(rest) else 0
        splitter.setSizes([width if i == index else max(1, int(size * share)) for i, size in enumerate(sizes)])

    def moved(*_args: object) -> None:
        if not shiboken6.isValid(splitter) or not shiboken6.isValid(panel):
            return
        sizes = splitter.sizes()
        if index < len(sizes) and sizes[index] > 0 and panel.isVisible():
            panel.setProperty("_scene_panel_width", sizes[index])
            settings.setValue(WIDTH_KEY, int(sizes[index]))

    splitter.splitterMoved.connect(moved)
    panel.installEventFilter(_ShowFilter(panel, apply))
    apply()


class _ShowFilter(QObject):
    """Applies the remembered width each time the panel is shown (it is hidden for one-part models)."""

    def __init__(self, panel: QWidget, apply) -> None:
        super().__init__(panel)
        self._apply = apply

    def eventFilter(self, _watched, event) -> bool:  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.Show:
            QTimer.singleShot(0, self, self._apply)
        return False


__all__ = [
    "ItemSetComponentsWidget",
    "OPEN_TICKED_LABEL",
    "ScenePanel",
    "remember_scene_panel_width",
]
