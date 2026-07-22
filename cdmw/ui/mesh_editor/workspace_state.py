"""WorkspaceStateMixin methods for the Mesh Editor workspace."""

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
from cdmw.ui.preview import DotNetPreviewHostFrame, DotNetPreviewProfile
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

class WorkspaceStateMixin:
    def button_for_key(self, key: str) -> QToolButton | None:
        return self._buttons_by_key.get(str(key or ""))

    def set_theme(self, theme_key: str) -> None:
        self._theme_key = str(theme_key or self._theme_key)
        preview = getattr(self, "preview", None)
        if preview is not None and hasattr(preview, "set_theme"):
            preview.set_theme(self._theme_key)
        for button in self.findChildren(QToolButton):
            icon_key = str(button.property("meshEditorIconKey") or "")
            if icon_key:
                button.setIcon(mesh_editor_action_icon(icon_key, self.palette()))
        self.update()

    def sync_ui_font(self, font: QFont, data_font: QFont | None = None) -> None:
        ui_font = QFont(font)
        dense_font = QFont(data_font or ui_font)
        self._set_widget_font(self, ui_font)
        for name in (
            "mode_combo",
            "selection_combo",
            "snap_combo",
            "pivot_combo",
            "orientation_combo",
            "left_tool_pages",
            "right_panels",
            "native_preview_button",
            "dotnet_editor_button",
            "native_part_pick_status_label",
            "native_performance_status_label",
            "preview_skeleton_button",
            "preview_pose_button",
            "run_rebuild_report_button",
            "rebuild_asset_button",
            "preview_rebuilt_asset_button",
            "package_rebuilt_asset_button",
            "save_rebuild_report_button",
            "pose_preview_button",
            "animation_speed_combo",
            "animation_scrub_slider",
            "part_selection_summary_label",
            "open_texture_button",
            "compare_mode_combo",
            "status_label",
            "part_status_label",
        ):
            self._set_widget_font(getattr(self, name, None), ui_font)
        for button in self._buttons_by_key.values():
            self._set_widget_font(button, ui_font)
        for widget in self._ui_font_widgets:
            self._set_widget_font(widget, ui_font)
        preview_host = getattr(self, "native_host_frame", None)
        self._set_widget_font(preview_host, ui_font)
        if preview_host is not None:
            for child in preview_host.findChildren(QWidget):
                self._set_widget_font(child, ui_font)
        for name in (
            "outliner",
            "properties_tree",
            "validator_tree",
            "rebuild_tree",
            "performance_tree",
            "history_list",
            "uv_tree",
            "skeleton_tree",
            "material_tree",
            "compare_tree",
            "log_list",
        ):
            widget = getattr(self, name, None)
            self._set_widget_font(widget, dense_font)
            header = widget.header() if isinstance(widget, QTreeWidget) else None
            self._set_widget_font(header, dense_font)
        log_list = getattr(self, "log_list", None)
        if log_list is not None:
            log_list.setMaximumHeight(max(54, log_list.fontMetrics().height() * 3 + 12))

    @staticmethod
    def _set_widget_font(widget: QWidget | None, font: QFont) -> None:
        if widget is not None and widget.font().toString() != font.toString():
            widget.setFont(font)

    def update_action_state(
        self,
        *,
        has_target: bool,
        selection_empty: bool = True,
        mode: str = "",
        active_selection_mode: str = "",
        undo_count: int = 0,
        redo_count: int = 0,
        native_editor_available: bool = True,
    ) -> None:
        self._has_editor_target = bool(has_target)
        self._native_editor_available = bool(native_editor_available)
        self.setEnabled(bool(has_target))
        self._sync_combo(self.mode_combo, str(mode or "object"))
        self._sync_combo(self.selection_combo, str(active_selection_mode or "vertex"))
        current_mode = str(mode or "").strip().lower()
        for action in self._actions_by_key.values():
            enabled = bool(has_target)
            if action.mode and action.category != "mode" and action.mode != current_mode:
                enabled = False
            if action.requires_selection and selection_empty:
                enabled = False
            if action.command == "undo" and int(undo_count or 0) <= 0:
                enabled = False
            if action.command == "redo" and int(redo_count or 0) <= 0:
                enabled = False
            if action.command in NATIVE_EDITOR_SESSION_COMMANDS and not native_editor_available:
                enabled = False
            for button in (self.button_for_key(action.key), self._uv_action_buttons.get(action.key)):
                if button is not None:
                    button.setEnabled(enabled)
        for name in ("uv_select_all_button", "uv_clear_selection_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(bool(has_target))
        rebuild_button = getattr(self, "run_rebuild_report_button", None)
        if rebuild_button is not None:
            rebuild_button.setEnabled(bool(has_target) and not self._embedded_controls_only)
        rebuild_asset_button = getattr(self, "rebuild_asset_button", None)
        if rebuild_asset_button is not None:
            rebuild_asset_button.setEnabled(
                bool(has_target) and self._export_validation_ok and not self._embedded_controls_only
            )
        dotnet_button = getattr(self, "dotnet_editor_button", None)
        if dotnet_button is not None:
            dotnet_button.setEnabled(bool(has_target) and not self._embedded_controls_only)
        for name in (
            "export_editable_package_button",
            "import_edited_package_button",
            "open_editable_package_folder_button",
        ):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(bool(has_target) and not self._embedded_controls_only)
        save_button = getattr(self, "save_rebuild_report_button", None)
        if save_button is not None:
            save_button.setEnabled(bool(has_target) and self._has_rebuild_report and not self._embedded_controls_only)
        preview_rebuilt_button = getattr(self, "preview_rebuilt_asset_button", None)
        if preview_rebuilt_button is not None:
            preview_rebuilt_button.setEnabled(
                bool(has_target) and self._has_rebuilt_asset_output and not self._embedded_controls_only
            )
        package_rebuilt_button = getattr(self, "package_rebuilt_asset_button", None)
        if package_rebuilt_button is not None:
            package_rebuilt_button.setEnabled(
                bool(has_target) and self._has_rebuilt_asset_output and not self._embedded_controls_only
            )
        copy_validation_button = getattr(self, "copy_validation_report_button", None)
        if copy_validation_button is not None:
            copy_validation_button.setEnabled(
                bool(has_target) and self._has_export_validation_report and not self._embedded_controls_only
            )
        run_validation_button = getattr(self, "run_validation_report_button", None)
        if run_validation_button is not None:
            run_validation_button.setEnabled(bool(has_target) and not self._embedded_controls_only)
        open_texture_button = getattr(self, "open_texture_button", None)
        if open_texture_button is not None:
            self._sync_part_controls()
        compare_combo = getattr(self, "compare_mode_combo", None)
        if compare_combo is not None:
            compare_combo.setEnabled(bool(has_target))

    def update_session_summary(self, view: MeshEditSessionView | None, *, mesh_label: str = "") -> None:
        if view is None:
            self.outliner.clear()
            self.outliner.addTopLevelItem(QTreeWidgetItem(("No mesh", "0", "")))
            self.properties_tree.clear()
            self.properties_tree.addTopLevelItem(QTreeWidgetItem(("Session", "none")))
            self.history_list.clear()
            self.history_list.addItem("No history")
            self.skeleton_tree.clear()
            self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("No skeleton", "")))
            return
        label = str(mesh_label or view.session_id or "mesh")
        self.outliner.clear()
        self.outliner.addTopLevelItem(QTreeWidgetItem((label, "", str(view.revision))))
        self.properties_tree.clear()
        for key, value in (
            ("Session", view.session_id),
            ("Mode", view.mode),
            ("Revision", view.revision),
            ("Undo", view.undo_count),
            ("Redo", view.redo_count),
        ):
            self.properties_tree.addTopLevelItem(QTreeWidgetItem((str(key), str(value))))
        self.history_list.clear()
        if view.history_entries:
            self.history_list.addItems(
                tuple(
                    f"{index + 1:02d}  {'[undone] ' if entry.state == 'undone' else ''}{entry.label}"
                    for index, entry in enumerate(view.history_entries)
                )
            )
            if view.history_cursor > 0:
                self.history_list.setCurrentRow(min(view.history_cursor - 1, self.history_list.count() - 1))
        else:
            self.history_list.addItem("No edit actions yet")

    def update_workspace_summary(self, summary: MeshWorkspaceSummary | None) -> None:
        self._workspace_summary = summary
        if summary is None:
            self.outliner.clear()
            self.outliner.addTopLevelItem(QTreeWidgetItem(("No mesh", "0", "")))
            self.material_tree.clear()
            self.material_tree.addTopLevelItem(QTreeWidgetItem(("No material", "", "")))
            self.uv_tree.clear()
            self.uv_tree.addTopLevelItem(QTreeWidgetItem(("No UV data", "")))
            self.uv_canvas.set_uv_summary(None)
            self.skeleton_tree.clear()
            self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("No skeleton", "")))
            self._sync_part_controls()
            return
        self.outliner.clear()
        self.material_tree.clear()
        self.uv_tree.clear()
        self.skeleton_tree.clear()
        for part in summary.parts:
            selected = "*" if part.selected else ""
            outliner_item = QTreeWidgetItem(
                (
                    f"{selected}{part.index}: {part.name}",
                    f"{part.face_count}",
                    f"{part.vertex_count} verts",
                )
            )
            self._configure_part_item(outliner_item, part.index, part.selected)
            self.outliner.addTopLevelItem(outliner_item)
            material_slot = str(part.material_slot_index) if part.material_slot_index >= 0 else ""
            texture_note = part.texture or "missing texture"
            if part.source_texture_set_key:
                texture_note = f"{texture_note} | set={part.source_texture_set_key}"
            material_item = QTreeWidgetItem(
                (
                    f"{selected}{part.index}: {part.material or 'missing material'}",
                    texture_note,
                    material_slot or part.material_slot_kind,
                )
            )
            self._configure_part_item(material_item, part.index, part.selected)
            self.material_tree.addTopLevelItem(material_item)
            self.uv_tree.addTopLevelItem(
                QTreeWidgetItem(
                    (
                        f"{part.index}: {part.name}",
                        f"UV {part.uv_coverage} | normal {part.normal_coverage} | tangent {part.tangent_coverage}",
                    )
                )
            )
            if part.has_skinning:
                self.skeleton_tree.addTopLevelItem(QTreeWidgetItem((f"{part.index}: {part.name}", "weighted part")))
        if not summary.parts:
            self.outliner.addTopLevelItem(QTreeWidgetItem(("No mesh", "0", "")))
        if self.skeleton_tree.topLevelItemCount() <= 0:
            self.skeleton_tree.addTopLevelItem(QTreeWidgetItem(("No skeleton", "")))
        self._sync_part_controls()

    def update_uv_summary(self, summary: MeshUvSummary | None) -> None:
        self._uv_summary = summary
        self.uv_canvas.set_uv_summary(summary)
        self.uv_tree.clear()
        self._sync_uv_summary_label(summary)
        workspace_summary = self._workspace_summary
        if workspace_summary is not None and not self._embedded_controls_only:
            for part in workspace_summary.parts:
                self.uv_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        (
                            f"{part.index}: {part.name}",
                            f"UV {part.uv_coverage} | normal {part.normal_coverage} | tangent {part.tangent_coverage}",
                        )
                    )
                )
        if summary is None:
            if self.uv_tree.topLevelItemCount() <= 0:
                self.uv_tree.addTopLevelItem(QTreeWidgetItem(("No UV data", "")))
            return
        if not summary.islands:
            self.uv_tree.addTopLevelItem(QTreeWidgetItem(("No UV islands", "0 connected islands")))
            return
        for island in summary.islands:
            selected = "*" if island.selected else ""
            texture = island.texture or "missing texture"
            item = QTreeWidgetItem(
                (
                    f"{selected}Island {island.index} | part {island.submesh_index}: {island.part_name}",
                    f"{island.vertex_count} verts | {island.face_count} faces | {island.bounds_text} | {texture}",
                )
            )
            item.setData(0, Qt.ItemDataRole.UserRole, (island.uv_min, island.uv_max))
            self.uv_tree.addTopLevelItem(item)

    def _sync_uv_summary_label(self, summary: MeshUvSummary | None) -> None:
        label = getattr(self, "uv_summary_label", None)
        if label is None:
            return
        if summary is None or not summary.islands:
            label.setText("UV: no islands selected")
            return
        textures = sorted({island.texture for island in summary.islands if island.texture})
        selected = int(summary.selected_island_count or 0)
        label.setText(
            f"UV: {summary.island_count} island(s) | {selected} selected | {', '.join(textures[:3]) or 'missing texture'}"
        )

    def append_log(self, message: str) -> None:
        text = str(message or "").strip()
        if text:
            self.log_list.addItem(text)
            self.log_list.scrollToBottom()
