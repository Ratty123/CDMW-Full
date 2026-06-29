"""Mesh Editor action bar widgets."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QToolButton, QWidget

from cdmw.ui.mesh_editor.actions import MESH_EDITOR_ACTIONS, MeshEditorAction
from cdmw.ui.mesh_editor.icons import mesh_editor_action_icon


_CATEGORY_ORDER = ("mode", "selection", "transform", "sculpt", "topology", "normals", "uv", "material", "history")
_EXCLUSIVE_CATEGORIES = {"mode", "selection"}
_MODE_ACTION_BY_MODE = {"object": "mode_object", "edit": "mode_edit", "sculpt": "mode_sculpt"}
_SELECTION_ACTION_BY_MODE = {"vertex": "select_vertex", "edge": "select_edge", "face": "select_face"}


class MeshEditorActionBar(QFrame):
    action_requested = Signal(object)

    def __init__(self, actions: Sequence[MeshEditorAction] = MESH_EDITOR_ACTIONS, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MeshEditorActionBar")
        self.buttons_by_key: dict[str, QToolButton] = {}
        self._actions_by_key = {action.key: action for action in actions}
        self._button_groups: list[QButtonGroup] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(6)
        for category in _CATEGORY_ORDER:
            category_actions = tuple(action for action in actions if action.category == category)
            if category_actions:
                root.addWidget(self._build_category(category, category_actions))
        root.addStretch(1)

    def button_for_key(self, key: str) -> QToolButton | None:
        return self.buttons_by_key.get(str(key or ""))

    def set_active_action(self, key: str) -> None:
        button = self.button_for_key(key)
        if button is not None and button.isCheckable():
            button.setChecked(True)

    def update_action_state(
        self,
        *,
        has_target: bool,
        selection_empty: bool = True,
        mode: str = "",
        active_selection_mode: str = "",
        undo_count: int = 0,
        redo_count: int = 0,
    ) -> None:
        self.setEnabled(bool(has_target))
        current_mode = str(mode or "").strip().lower()
        for action in self._actions_by_key.values():
            button = self.button_for_key(action.key)
            if button is None:
                continue
            enabled = bool(has_target)
            if not _action_mode_enabled(action, current_mode):
                enabled = False
            if action.requires_selection and selection_empty:
                enabled = False
            if action.command == "undo" and int(undo_count or 0) <= 0:
                enabled = False
            if action.command == "redo" and int(redo_count or 0) <= 0:
                enabled = False
            button.setEnabled(enabled)
        self.set_active_action(_MODE_ACTION_BY_MODE.get(str(mode or "").strip().lower(), ""))
        self.set_active_action(_SELECTION_ACTION_BY_MODE.get(str(active_selection_mode or "").strip().lower(), ""))

    def _build_category(self, category: str, actions: Sequence[MeshEditorAction]) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName(f"MeshEditorActionCategory_{category}")
        layout = QGridLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(2)
        layout.setVerticalSpacing(2)
        columns = 3 if category == "topology" else max(1, min(4, len(actions)))
        button_group = QButtonGroup(frame) if category in _EXCLUSIVE_CATEGORIES else None
        if button_group is not None:
            button_group.setExclusive(True)
            self._button_groups.append(button_group)
        for index, action in enumerate(actions):
            button = QToolButton(frame)
            button.setObjectName(f"MeshEditorAction_{action.key}")
            button.setText(action.text)
            button.setAccessibleName(action.text)
            button.setIcon(mesh_editor_action_icon(action.icon_key, self.palette()))
            button.setIconSize(QSize(18, 18))
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setToolTip(_action_tooltip(action))
            button.setProperty("meshEditorActionKey", action.key)
            button.setProperty("meshEditorCommand", action.command)
            button.setProperty("meshEditorCategory", action.category)
            button.setProperty("meshEditorMode", action.mode)
            button.setProperty("meshEditorSelectionMode", action.selection_mode)
            button.setProperty("meshEditorIconKey", action.icon_key)
            button.setProperty("meshEditorShortcut", action.shortcut)
            button.setProperty("meshEditorRequiresSelection", action.requires_selection)
            if action.shortcut:
                button.setShortcut(QKeySequence(action.shortcut))
            button.setAutoRaise(True)
            button.setCheckable(category in _EXCLUSIVE_CATEGORIES)
            if button_group is not None:
                button_group.addButton(button)
            button.clicked.connect(lambda _checked=False, current=action: self.action_requested.emit(current))
            self.buttons_by_key[action.key] = button
            layout.addWidget(button, index // columns, index % columns)
        return frame


def _action_mode_enabled(action: MeshEditorAction, current_mode: str) -> bool:
    required = str(action.mode or "").strip().lower()
    return not required or action.category == "mode" or required == current_mode


def _action_tooltip(action: MeshEditorAction) -> str:
    if not action.shortcut:
        return action.tooltip
    return f"{action.tooltip}\nShortcut: {action.shortcut}"


__all__ = ["MeshEditorActionBar"]
