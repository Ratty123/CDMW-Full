"""Mesh Editor action bar widgets."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QSizePolicy, QToolButton, QWidget

from cdmw.ui.mesh_editor.actions import MESH_EDITOR_ACTIONS, NATIVE_EDITOR_SESSION_COMMANDS, MeshEditorAction
from cdmw.ui.mesh_editor.icons import mesh_editor_action_icon


_CATEGORY_ORDER = ("mode", "selection", "transform", "sculpt", "topology", "cleanup", "normals", "uv", "material", "history")
_EXCLUSIVE_CATEGORIES = {"mode", "selection"}
_MODE_ACTION_BY_MODE = {"object": "mode_object", "edit": "mode_edit", "sculpt": "mode_sculpt"}
_SELECTION_ACTION_BY_MODE = {"vertex": "select_vertex", "edge": "select_edge", "face": "select_face"}
_TOOL_ACTION_KEYS = {"transform_move", "brush_grab", "brush_smooth", "brush_inflate", "brush_pinch"}
_BUTTON_LABELS = {
    "select_vertex": "Vertex",
    "select_edge": "Edge",
    "select_face": "Face",
    "transform_move": "Move",
    "transform_rotate": "Rotate",
    "transform_scale": "Scale",
    "brush_grab": "Grab",
    "brush_smooth": "Smooth",
    "brush_inflate": "Inflate",
    "brush_pinch": "Pinch",
    "subdivide": "Subdiv",
    "refine_smooth": "Refine",
    "duplicate": "Dupe",
    "loop_cut": "Loop Cut",
    "edge_split": "Edge Cut",
    "remove_doubles": "Doubles",
    "delete_loose_vertices": "Loose",
    "compact_orphans": "Compact",
    "fix_winding": "Winding",
    "fill_holes": "Holes",
    "recalculate_normals": "Recalc",
    "generate_tangents": "Tangents",
    "flip_normals": "Flip N",
    "sharpen_normals": "Sharp N",
    "soften_normals": "Soft N",
    "weighted_normals": "Weight N",
    "copy_normals": "Copy N",
    "uv_transform": "UV Move",
    "uv_rotate_90": "Rot UV",
    "uv_island_transform": "Island",
    "uv_normalize": "Norm UV",
    "uv_planar_project": "Planar",
    "uv_box_project": "Box UV",
    "uv_cylindrical_project": "Cyl UV",
    "uv_auto_unwrap": "Auto UV",
    "uv_snap_grid": "Grid",
    "uv_snap_pixels": "Pixel",
    "material_assign": "Assign",
    "material_copy": "Copy Mat",
}


class MeshEditorActionBar(QFrame):
    action_requested = Signal(object)

    def __init__(self, actions: Sequence[MeshEditorAction] = MESH_EDITOR_ACTIONS, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MeshEditorActionBar")
        self.setStyleSheet(
            "QFrame#MeshEditorActionBar QToolButton:checked {"
            " background-color: #1769aa;"
            " color: white;"
            " border: 1px solid #58a6ff;"
            "}"
        )
        self.buttons_by_key: dict[str, QToolButton] = {}
        self._actions_by_key = {action.key: action for action in actions}
        self._button_groups: list[QButtonGroup] = []
        self._selection_button_group: QButtonGroup | None = None
        self._tool_button_group = QButtonGroup(self)
        self._tool_button_group.setExclusive(True)
        self._button_groups.append(self._tool_button_group)

        root = QHBoxLayout(self)
        root.setContentsMargins(4, 2, 4, 2)
        root.setSpacing(4)
        for category in _CATEGORY_ORDER:
            category_actions = tuple(action for action in actions if action.category == category)
            if category_actions:
                root.addWidget(self._build_category(category, category_actions))
        root.addStretch(1)

    def button_for_key(self, key: str) -> QToolButton | None:
        return self.buttons_by_key.get(str(key or ""))

    def set_theme(self, _theme_key: str) -> None:
        for action in self._actions_by_key.values():
            button = self.button_for_key(action.key)
            if button is not None:
                button.setIcon(mesh_editor_action_icon(action.icon_key, self.palette()))

    def sync_ui_font(self, font: QFont, data_font: QFont | None = None) -> None:
        _ = data_font
        applied_font = QFont(font)
        if self.font().toString() != applied_font.toString():
            self.setFont(applied_font)
        for button in self.buttons_by_key.values():
            if button.font().toString() != applied_font.toString():
                button.setFont(applied_font)

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
        active_tool_key: str = "",
        undo_count: int = 0,
        redo_count: int = 0,
        native_editor_available: bool = True,
    ) -> None:
        self.setEnabled(bool(has_target))
        current_mode = str(mode or "").strip().lower()
        for action in self._actions_by_key.values():
            button = self.button_for_key(action.key)
            if button is None:
                continue
            enabled = bool(has_target)
            if action.command in {"brush", "select"}:
                if current_mode not in {"edit", "sculpt"}:
                    enabled = False
            elif not _action_mode_enabled(action, current_mode):
                enabled = False
            if action.requires_selection and selection_empty:
                enabled = False
            if action.command == "undo" and int(undo_count or 0) <= 0:
                enabled = False
            if action.command == "redo" and int(redo_count or 0) <= 0:
                enabled = False
            if action.command in NATIVE_EDITOR_SESSION_COMMANDS and not native_editor_available:
                enabled = False
            button.setEnabled(enabled)
        self.set_active_action(_MODE_ACTION_BY_MODE.get(str(mode or "").strip().lower(), ""))
        active_tool = str(active_tool_key or "").strip()
        if active_tool in _TOOL_ACTION_KEYS:
            self._clear_button_group(self._selection_button_group)
            self.set_active_action(active_tool)
        else:
            self._clear_button_group(self._tool_button_group)
            self.set_active_action(_SELECTION_ACTION_BY_MODE.get(str(active_selection_mode or "").strip().lower(), ""))

    def _build_category(self, category: str, actions: Sequence[MeshEditorAction]) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName(f"MeshEditorActionCategory_{category}")
        layout = QGridLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(2)
        layout.setVerticalSpacing(2)
        columns = max(1, min(4, len(actions)))
        button_group = QButtonGroup(frame) if category in _EXCLUSIVE_CATEGORIES else None
        if button_group is not None:
            button_group.setExclusive(True)
            self._button_groups.append(button_group)
            if category == "selection":
                self._selection_button_group = button_group
        for index, action in enumerate(actions):
            button = QToolButton(frame)
            button.setObjectName(f"MeshEditorAction_{action.key}")
            button.setText(_action_button_text(action))
            button.setAccessibleName(action.text)
            button.setIcon(mesh_editor_action_icon(action.icon_key, self.palette()))
            button.setIconSize(QSize(16, 16))
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setFixedSize(QSize(62, 42))
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
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
            if action.key in _TOOL_ACTION_KEYS:
                button.setCheckable(True)
                self._tool_button_group.addButton(button)
            button.clicked.connect(lambda _checked=False, current=action: self.action_requested.emit(current))
            self.buttons_by_key[action.key] = button
            layout.addWidget(button, index // columns, index % columns)
        return frame

    def _clear_button_group(self, button_group: QButtonGroup | None) -> None:
        if button_group is None:
            return
        was_exclusive = button_group.exclusive()
        button_group.setExclusive(False)
        for button in button_group.buttons():
            button.setChecked(False)
        button_group.setExclusive(was_exclusive)


def _action_mode_enabled(action: MeshEditorAction, current_mode: str) -> bool:
    required = str(action.mode or "").strip().lower()
    return not required or action.category == "mode" or required == current_mode


def _action_tooltip(action: MeshEditorAction) -> str:
    if not action.shortcut:
        return action.tooltip
    return f"{action.tooltip}\nShortcut: {action.shortcut}"


def _action_button_text(action: MeshEditorAction) -> str:
    return _BUTTON_LABELS.get(action.key, action.text)


__all__ = ["MeshEditorActionBar"]
