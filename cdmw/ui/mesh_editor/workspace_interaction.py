"""WorkspaceInteractionMixin methods for the Mesh Editor workspace."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QSlider,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.mesh import (
    MeshCompareSummary,
    MeshEditSessionView,
    MeshExportValidationReport,
    MeshSkeletonSummary,
    MeshUvSummary,
    MeshWorkspaceSummary,
)
from cdmw.ui.mesh_editor.actions import (
    MESH_EDITOR_ACTIONS,
    NATIVE_EDITOR_SESSION_COMMANDS,
    MeshEditorAction,
    mesh_editor_actions_by_key,
)
from cdmw.ui.mesh_editor.icons import mesh_editor_action_icon
from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame
from cdmw.ui.native_preview_panel import NativePreviewPanel


_LEFT_TOOL_PAGES = (
    ("Tools", ("selection", "transform", "sculpt")),
    ("Edit", ("topology", "cleanup", "normals", "history")),
    ("UV", ("uv", "material")),
    ("Rig", ()),
)
_LEFT_CATEGORY_LABELS = {
    "selection": "Selection",
    "transform": "Transform",
    "sculpt": "Sculpt",
    "topology": "Topology",
    "cleanup": "Cleanup",
    "normals": "Normals",
    "uv": "UV",
    "material": "Material",
    "history": "History",
}

_SLOW_FRAME_MS = 1000.0 / 60.0
_MODE_ACTION_BY_TEXT = {"object": "mode_object", "edit": "mode_edit", "sculpt": "mode_sculpt"}
_SELECTION_ACTION_BY_TEXT = {"vertex": "select_vertex", "edge": "select_edge", "face": "select_face"}
_SKELETON_PANEL_BONE_LIMIT = 512
_SKELETON_PANEL_WEIGHT_LIMIT = 32


from cdmw.ui.mesh_editor.workspace_views import (
    MeshUvCanvas,
    _issue_location,
    _short_hash,
    _join_report_values,
    _rebuild_report_operation_names,
    _workspace_action_tooltip,
    _part_selection_summary_text,
    _part_selection_status_text,
    _part_detail_text,
    _clamped01,
    _selection_operation_from_modifiers,
    _constraint_bone_label,
    _constraint_candidate_token_text,
    _constraint_candidate_field_offset_text,
    _constraint_bone_match_counts_text,
    _constraint_counts_text,
    _constraint_delta_counts_text,
    _constraint_numeric_match_text,
    _constraint_nested_counts_text,
    _constraint_expression_evidence_text,
    _constraint_field_offset_text,
    _constraint_solver_readiness_text,
)

class _PartTreeWidget(QTreeWidget):
    blank_area_clicked = Signal()

    def mousePressEvent(self, event: object) -> None:  # type: ignore[override]
        position = event.position().toPoint()  # type: ignore[attr-defined]
        if event.button() == Qt.MouseButton.LeftButton and self.itemAt(position) is None:  # type: ignore[attr-defined]
            self.clearSelection()
            self.setCurrentItem(None)
            self.blank_area_clicked.emit()
            event.accept()  # type: ignore[attr-defined]
            return
        super().mousePressEvent(event)  # type: ignore[arg-type]


class WorkspaceInteractionMixin:
    def _build_status_strip(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorBottomStatusStrip")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.status_label = QLabel("No active edit session.", frame)
        self.status_label.setObjectName("MeshEditorStandaloneStatus")
        self.status_label.setWordWrap(True)
        self.part_status_label = QLabel("Parts: no mesh.", frame)
        self.part_status_label.setObjectName("MeshEditorPartStatusStrip")
        self.part_status_label.setWordWrap(True)
        self.log_list = QListWidget(frame)
        self.log_list.setObjectName("MeshEditorWorkspaceLog")
        self.log_list.setMaximumHeight(54)
        layout.addWidget(self.status_label)
        layout.addWidget(self.part_status_label)
        layout.addWidget(self.log_list)
        return frame

    def _combo(self, object_name: str, values: Iterable[str]) -> QComboBox:
        combo = QComboBox(self)
        combo.setObjectName(object_name)
        combo.addItems(tuple(values))
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        return combo

    def _tree(self, headers: Sequence[str], object_name: str) -> QTreeWidget:
        tree = QTreeWidget(self)
        tree.setObjectName(object_name)
        tree.setHeaderLabels(tuple(headers))
        tree.setRootIsDecorated(False)
        return tree

    def _part_tree(self, headers: Sequence[str], object_name: str) -> QTreeWidget:
        tree = _PartTreeWidget(self)
        tree.setObjectName(object_name)
        tree.setHeaderLabels(tuple(headers))
        tree.setRootIsDecorated(False)
        tree.blank_area_clicked.connect(lambda: self.part_selection_requested.emit(-1, "clear"))
        return tree

    def _configure_part_tree(self, tree: QTreeWidget) -> None:
        tree.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        tree.itemClicked.connect(self._part_tree_item_clicked)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(
            lambda position, current=tree: self._show_part_context_menu(current, position)
        )

    def _configure_part_item(self, item: QTreeWidgetItem, part_index: int, selected: bool) -> None:
        item.setData(0, Qt.ItemDataRole.UserRole, int(part_index))
        item.setSelected(bool(selected))
        item.setToolTip(0, "Click to toggle part selection. Right-click for part actions.")

    def _part_tree_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        part_index = self._part_index_from_item(item)
        if part_index >= 0:
            self.part_selection_requested.emit(part_index, "toggle")

    def show_part_context_menu_for_part(self, part_index: int, global_pos: object | None = None) -> None:
        try:
            normalized_index = int(part_index)
        except (TypeError, ValueError):
            normalized_index = -1
        if normalized_index < 0:
            return
        position = global_pos if global_pos is not None else self.mapToGlobal(self.rect().center())
        self._exec_part_context_menu(normalized_index, position, self)

    def _show_part_context_menu(self, tree: QTreeWidget, position: object) -> None:
        item = tree.itemAt(position)  # type: ignore[arg-type]
        part_index = self._part_index_from_item(item)
        if part_index < 0:
            return
        self._exec_part_context_menu(part_index, tree.viewport().mapToGlobal(position), tree)  # type: ignore[arg-type]

    def _exec_part_context_menu(self, part_index: int, global_pos: object, parent: QWidget) -> None:
        menu = QMenu(parent)
        actions = (
            ("Select Only", "select_only"),
            ("Toggle Selection", "toggle_selection"),
            ("Clone Part", "duplicate"),
            ("Delete Part", "delete"),
            ("Recalculate Normals", "recalculate_normals"),
            ("Flip Normals", "flip_normals"),
            ("Open Texture", "open_texture"),
        )
        action_by_command = {command: menu.addAction(label) for label, command in actions}
        chosen = menu.exec(global_pos)  # type: ignore[arg-type]
        for command, action in action_by_command.items():
            if chosen is action:
                self.part_context_action_requested.emit(command, part_index)
                return

    def _part_index_from_item(self, item: QTreeWidgetItem | None) -> int:
        if item is None:
            return -1
        try:
            return int(item.data(0, Qt.ItemDataRole.UserRole))
        except (TypeError, ValueError):
            return -1

    def _mode_changed(self, text: str) -> None:
        if self._updating_state:
            return
        action = mesh_editor_actions_by_key().get(_MODE_ACTION_BY_TEXT.get(str(text or "").strip().lower(), ""))
        if action is not None:
            self.action_requested.emit(action)

    def _compare_view_changed(self, text: str) -> None:
        mode = str(text or "Edited").strip().lower().replace(" ", "_")
        if mode not in {"edited", "source", "ghost"}:
            mode = "edited"
        self.compare_view_requested.emit(mode)

    def _uv_tree_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        try:
            uv_min, uv_max = item.data(0, Qt.ItemDataRole.UserRole)
        except (TypeError, ValueError):
            return
        self.uv_region_selected.emit(tuple(uv_min), tuple(uv_max), "replace")

    def _skeleton_tree_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        try:
            bone_index = int(item.data(0, Qt.ItemDataRole.UserRole))
        except (TypeError, ValueError):
            return
        if bone_index >= 0:
            self.skeleton_pose_requested.emit("select_bone", bone_index)

    def _sync_skeleton_pose_controls(self, summary: MeshSkeletonSummary | None) -> None:
        pose = summary.pose if summary is not None else None
        has_bones = bool(summary is not None and summary.bones)
        has_rig_summary = bool(summary is not None and (summary.skinned or summary.skeleton_linked or summary.bones))
        selected = int(pose.selected_bone_index if pose is not None else -1)
        for name in ("pose_preview_button", "preview_pose_button", "rig_pose_button"):
            pose_button = getattr(self, name, None)
            if pose_button is None:
                continue
            previous = pose_button.blockSignals(True)
            try:
                pose_button.setChecked(bool(pose is not None and pose.enabled))
            finally:
                pose_button.blockSignals(previous)
            pose_button.setEnabled(has_bones)
        for name in ("preview_skeleton_button", "rig_skeleton_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(has_rig_summary)
        for name in ("pose_rotate_x_button", "pose_rotate_y_button", "pose_rotate_z_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(has_bones and selected >= 0)
        has_selected_weights = bool(summary is not None and summary.selected_vertex_weights)
        has_selected_part = bool(summary is not None and any(part.selected for part in summary.parts))
        for name in ("weight_increase_button", "weight_decrease_button", "weight_normalize_button", "rig_weight_normalize_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(has_bones and selected >= 0 and has_selected_weights)
        for name in ("weight_transfer_button", "rig_weight_transfer_button"):
            transfer_button = getattr(self, name, None)
            if transfer_button is not None:
                transfer_button.setEnabled(has_bones and (has_selected_weights or has_selected_part))
        reset_button = getattr(self, "pose_reset_button", None)
        if reset_button is not None:
            reset_button.setEnabled(has_bones and bool(pose is not None and (pose.posed_bone_count or selected >= 0)))
        playback = summary.animation_playback if summary is not None else None
        playback_ready = bool(playback is not None and playback.ready)
        play_button = getattr(self, "animation_play_button", None)
        if play_button is not None:
            previous = play_button.blockSignals(True)
            try:
                play_button.setChecked(bool(playback is not None and playback.enabled))
            finally:
                play_button.blockSignals(previous)
            play_button.setEnabled(playback_ready)
        for name in ("animation_step_button", "animation_rewind_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(playback_ready)
        loop_button = getattr(self, "animation_loop_button", None)
        if loop_button is not None:
            previous = loop_button.blockSignals(True)
            try:
                loop_button.setChecked(bool(playback is not None and playback.loop))
            finally:
                loop_button.blockSignals(previous)
            loop_button.setEnabled(playback_ready)
        speed_combo = getattr(self, "animation_speed_combo", None)
        if speed_combo is not None:
            self._sync_animation_speed_combo(speed_combo, float(getattr(playback, "playback_speed", 1.0) if playback is not None else 1.0))
            speed_combo.setEnabled(playback_ready)
        scrub_slider = getattr(self, "animation_scrub_slider", None)
        if scrub_slider is not None:
            duration = float(getattr(playback, "duration_seconds", 0.0) if playback is not None else 0.0)
            time_seconds = float(getattr(playback, "time_seconds", 0.0) if playback is not None else 0.0)
            value = int(round(1000.0 * min(1.0, max(0.0, time_seconds / duration)))) if duration > 0.0 else 0
            previous = scrub_slider.blockSignals(True)
            try:
                scrub_slider.setValue(value)
            finally:
                scrub_slider.blockSignals(previous)
            scrub_slider.setEnabled(playback_ready and duration > 0.0)

    def _selection_changed(self, text: str) -> None:
        if self._updating_state:
            return
        action = mesh_editor_actions_by_key().get(_SELECTION_ACTION_BY_TEXT.get(str(text or "").strip().lower(), ""))
        if action is not None:
            self.action_requested.emit(action)

    def _sync_combo(self, combo: QComboBox, value: str) -> None:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return
        for index in range(combo.count()):
            if combo.itemText(index).strip().lower() == normalized:
                if combo.currentIndex() == index:
                    return
                self._updating_state = True
                try:
                    combo.setCurrentIndex(index)
                finally:
                    self._updating_state = False
                return

    def _animation_speed_changed(self, _index: int) -> None:
        if self._updating_state:
            return
        combo = getattr(self, "animation_speed_combo", None)
        if combo is None:
            return
        self.skeleton_pose_requested.emit("set_animation_speed", combo.currentData())

    def _animation_scrub_changed(self, value: int) -> None:
        if self._updating_state:
            return
        self.skeleton_pose_requested.emit("scrub_animation_fraction", max(0.0, min(1.0, float(value) / 1000.0)))

    def _sync_animation_speed_combo(self, combo: QComboBox, value: float) -> None:
        best_index = 0
        best_delta = float("inf")
        for index in range(combo.count()):
            try:
                current = float(combo.itemData(index))
            except (TypeError, ValueError, OverflowError):
                continue
            delta = abs(current - value)
            if delta < best_delta:
                best_index = index
                best_delta = delta
        previous = combo.blockSignals(True)
        try:
            combo.setCurrentIndex(best_index)
        finally:
            combo.blockSignals(previous)
