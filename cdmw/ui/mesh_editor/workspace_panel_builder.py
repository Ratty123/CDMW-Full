"""WorkspacePanelBuilderMixin methods for the Mesh Editor workspace."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCheckBox,
    QDoubleSpinBox,
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
    MeshObjectTransformState,
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
_SELECTION_ACTION_BY_TEXT = {"brush": "select_parts", "rectangle": "select_parts", "lasso": "select_parts"}
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

class WorkspacePanelBuilderMixin:
    def _build_right_panels(self) -> QTabWidget:
        # Keyed on the English title the panel was added under, never on what the tab
        # currently draws: the localizer rewrites `Checks` to `Prueft`, and matching the
        # drawn text meant a finished validation or rebuild silently left the user on
        # whatever pane they were already looking at.
        self._right_panels_by_title: dict[str, QWidget] = {}
        tabs = QTabWidget(self)
        tabs.setObjectName("MeshEditorRightPanels")
        tabs.setUsesScrollButtons(True)
        tabs.setElideMode(Qt.ElideRight)
        tabs.tabBar().setExpanding(False)
        tabs.setMinimumWidth(300)
        tabs.setMaximumWidth(430)
        self.right_panels = tabs
        self.outliner = self._part_tree(("Part", "Faces", "Rev"), "MeshEditorOutlinerPanel")
        self._configure_part_tree(self.outliner)
        self.properties_tree = self._tree(("Property", "Value"), "MeshEditorPropertiesPanel")
        object_transform_panel = self._build_object_transform_panel()
        uv_panel = self._build_uv_panel()
        material_panel = self._build_material_panel()
        compare_panel = self._build_compare_panel()
        validation_panel = self._build_validation_panel()
        rebuild_panel = self._build_rebuild_panel()
        performance_panel = self._build_performance_panel()
        self.history_list = QListWidget(tabs)
        self.history_list.setObjectName("MeshEditorHistoryPanel")
        skeleton_panel = self._build_skeleton_panel()
        for widget, title in (
            (self.outliner, "Parts"),
            (self.properties_tree, "Details"),
            (object_transform_panel, "Object Transform"),
            (skeleton_panel, "Rig"),
            (uv_panel, "UV Map"),
            (material_panel, "Part Actions"),
            (compare_panel, "Review"),
            (validation_panel, "Checks"),
            (rebuild_panel, "Rebuild"),
            (performance_panel, "Performance"),
            (self.history_list, "History"),
        ):
            tabs.addTab(widget, title)
            self._right_panels_by_title[title.strip().lower()] = widget
        self.update_session_summary(None)
        self.update_workspace_panel_state(self._workspace_panel_state)
        self.update_uv_panel_state(self._uv_panel_state)
        self.update_export_validation_state(self._export_validation_panel_state)
        self.update_rebuild_report_state(self._rebuild_panel_state)
        self.set_native_performance_status(None)
        self.update_compare_panel_state(self._compare_panel_state)
        self.update_skeleton_panel_state(self._skeleton_panel_state)
        return tabs

    def _build_object_transform_panel(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorObjectTransformPanel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        hint = QLabel(
            "Moves every mesh part around the fixed source-bounds centre without changing selection.",
            frame,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        grid = QGridLayout()
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(4)
        for column, axis in enumerate(("X", "Y", "Z"), start=1):
            grid.addWidget(QLabel(axis, frame), 0, column)
        self.object_transform_spins: dict[str, tuple[QDoubleSpinBox, QDoubleSpinBox, QDoubleSpinBox]] = {}
        rows = (
            ("location", "Location", -100000.0, 100000.0, 0.01),
            ("rotation_degrees", "Rotation", -360000.0, 360000.0, 1.0),
            ("scale", "Scale", 0.0001, 10000.0, 0.01),
        )
        for row, (key, label, minimum, maximum, step) in enumerate(rows, start=1):
            grid.addWidget(QLabel(label, frame), row, 0)
            spins: list[QDoubleSpinBox] = []
            for axis in range(3):
                spin = QDoubleSpinBox(frame)
                spin.setObjectName(f"MeshEditorObject{key.title().replace('_', '')}{'XYZ'[axis]}Spin")
                spin.setDecimals(4)
                spin.setRange(minimum, maximum)
                spin.setSingleStep(step)
                spin.setKeyboardTracking(False)
                spin.editingFinished.connect(
                    lambda field=key, index=axis: self._commit_object_transform_spin(field, index)
                )
                grid.addWidget(spin, row, axis + 1)
                spins.append(spin)
            self.object_transform_spins[key] = tuple(spins)  # type: ignore[assignment]
        layout.addLayout(grid)

        scale_row = QHBoxLayout()
        self.object_transform_link_scale = QCheckBox("Linked XYZ scale", frame)
        self.object_transform_link_scale.setObjectName("MeshEditorObjectTransformLinkedScale")
        self.object_transform_link_scale.setChecked(True)
        scale_row.addWidget(self.object_transform_link_scale)
        scale_row.addStretch(1)
        layout.addLayout(scale_row)

        tilt_row = QGridLayout()
        for index, (text, axis, delta) in enumerate(
            (("Tilt X−", 0, -15.0), ("Tilt X+", 0, 15.0), ("Tilt Y−", 1, -15.0),
             ("Tilt Y+", 1, 15.0), ("Tilt Z−", 2, -15.0), ("Tilt Z+", 2, 15.0))
        ):
            button = QPushButton(text, frame)
            button.setObjectName(f"MeshEditorObjectTransformTilt{index}Button")
            button.clicked.connect(
                lambda _checked=False, target_axis=axis, amount=delta: self._tilt_object_transform(target_axis, amount)
            )
            tilt_row.addWidget(button, index // 2, index % 2)
        layout.addLayout(tilt_row)

        reset_row = QGridLayout()
        for index, (text, target) in enumerate(
            (("Reset Position", "location"), ("Reset Rotation", "rotation_degrees"),
             ("Reset Scale", "scale"), ("Reset All", "all"))
        ):
            button = QPushButton(text, frame)
            button.setObjectName(f"MeshEditorObjectTransformReset{target.title().replace('_', '')}Button")
            button.clicked.connect(
                lambda _checked=False, reset_target=target: self._reset_object_transform(reset_target)
            )
            reset_row.addWidget(button, index // 2, index % 2)
        layout.addLayout(reset_row)
        self.object_transform_pivot_label = QLabel("Pivot: —", frame)
        self.object_transform_pivot_label.setObjectName("MeshEditorObjectTransformPivot")
        layout.addWidget(self.object_transform_pivot_label)
        layout.addStretch(1)
        self._object_transform_control_update = False
        self.update_object_transform(MeshObjectTransformState())
        return frame

    def _object_transform_payload(self) -> dict[str, tuple[float, float, float]]:
        return {
            key: tuple(float(spin.value()) for spin in spins)
            for key, spins in self.object_transform_spins.items()
        }

    def _commit_object_transform_spin(self, field: str, axis: int) -> None:
        if self._object_transform_control_update or not self._has_editor_target:
            return
        if field == "scale" and self.object_transform_link_scale.isChecked():
            value = self.object_transform_spins[field][axis].value()
            self._object_transform_control_update = True
            try:
                for spin in self.object_transform_spins[field]:
                    spin.setValue(value)
            finally:
                self._object_transform_control_update = False
        self.object_transform_requested.emit(self._object_transform_payload())

    def _tilt_object_transform(self, axis: int, delta: float) -> None:
        if self._object_transform_control_update or not self._has_editor_target:
            return
        spin = self.object_transform_spins["rotation_degrees"][axis]
        spin.setValue(spin.value() + float(delta))
        self.object_transform_requested.emit(self._object_transform_payload())

    def _reset_object_transform(self, target: str) -> None:
        if self._object_transform_control_update or not self._has_editor_target:
            return
        self._object_transform_control_update = True
        try:
            targets = ("location", "rotation_degrees", "scale") if target == "all" else (target,)
            for key in targets:
                value = 1.0 if key == "scale" else 0.0
                for spin in self.object_transform_spins[key]:
                    spin.setValue(value)
        finally:
            self._object_transform_control_update = False
        self.object_transform_requested.emit(self._object_transform_payload())

    def update_object_transform(self, state: MeshObjectTransformState) -> None:
        self._object_transform_control_update = True
        try:
            for key in ("location", "rotation_degrees", "scale"):
                for spin, value in zip(self.object_transform_spins[key], getattr(state, key), strict=True):
                    spin.setValue(float(value))
            self.object_transform_pivot_label.setText(
                "Pivot: " + ", ".join(f"{float(value):.4f}" for value in state.pivot)
            )
        finally:
            self._object_transform_control_update = False

    def _build_performance_panel(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorPerformanceFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.performance_tree = self._tree(("Metric", "Value"), "MeshEditorPerformancePanel")
        layout.addWidget(self.performance_tree, 1)
        return frame

    def _build_validation_panel(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorValidationFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        controls = QHBoxLayout()
        controls.setSpacing(4)
        self.run_validation_report_button = QToolButton(frame)
        self.run_validation_report_button.setObjectName("MeshEditorRunValidationReportButton")
        self.run_validation_report_button.setText("Run")
        self.run_validation_report_button.setAccessibleName("Run validation")
        self.run_validation_report_button.setToolTip("Run export validation in the background.")
        self.run_validation_report_button.setProperty("meshEditorIconKey", "recalculate_normals")
        self.run_validation_report_button.setIcon(mesh_editor_action_icon("recalculate_normals", self.palette()))
        self.run_validation_report_button.setIconSize(QSize(18, 18))
        self.run_validation_report_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.run_validation_report_button.setEnabled(False)
        self.run_validation_report_button.clicked.connect(self.validation_report_requested.emit)
        self._ui_font_widgets.append(self.run_validation_report_button)
        controls.addWidget(self.run_validation_report_button)
        self.copy_validation_report_button = QToolButton(frame)
        self.copy_validation_report_button.setObjectName("MeshEditorCopyValidationReportButton")
        self.copy_validation_report_button.setText("Copy")
        self.copy_validation_report_button.setAccessibleName("Copy validation report")
        self.copy_validation_report_button.setToolTip("Copy the current validation report as JSON.")
        self.copy_validation_report_button.setProperty("meshEditorIconKey", "material_copy")
        self.copy_validation_report_button.setIcon(mesh_editor_action_icon("material_copy", self.palette()))
        self.copy_validation_report_button.setIconSize(QSize(18, 18))
        self.copy_validation_report_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.copy_validation_report_button.setEnabled(False)
        self.copy_validation_report_button.clicked.connect(self.copy_validation_report_requested.emit)
        self._ui_font_widgets.append(self.copy_validation_report_button)
        controls.addWidget(self.copy_validation_report_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.validator_tree = self._tree(("Severity", "Code", "Message"), "MeshEditorValidatorPanel")
        layout.addWidget(self.validator_tree, 1)
        return frame

    def _build_rebuild_panel(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorRebuildReportFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        controls = QHBoxLayout()
        controls.setSpacing(4)
        self.run_rebuild_report_button = QToolButton(frame)
        self.run_rebuild_report_button.setObjectName("MeshEditorRunRebuildReportButton")
        self.run_rebuild_report_button.setText("Run")
        self.run_rebuild_report_button.setAccessibleName("Run rebuild report")
        self.run_rebuild_report_button.setToolTip("Validate and run an in-memory rebuild report in the background.")
        self.run_rebuild_report_button.setProperty("meshEditorIconKey", "recalculate_normals")
        self.run_rebuild_report_button.setIcon(mesh_editor_action_icon("recalculate_normals", self.palette()))
        self.run_rebuild_report_button.setIconSize(QSize(18, 18))
        self.run_rebuild_report_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.run_rebuild_report_button.setEnabled(False)
        self.run_rebuild_report_button.clicked.connect(self.rebuild_report_requested.emit)
        self._ui_font_widgets.append(self.run_rebuild_report_button)
        controls.addWidget(self.run_rebuild_report_button)
        self.export_mesh_file_button = QToolButton(frame)
        self.export_mesh_file_button.setObjectName("MeshEditorExportMeshFileButton")
        self.export_mesh_file_button.setText("Export Mesh File")
        self.export_mesh_file_button.setAccessibleName("Export mesh file")
        self.export_mesh_file_button.setToolTip("Atomically write the validated rebuilt mesh and its report.")
        self.export_mesh_file_button.setProperty("meshEditorIconKey", "export")
        self.export_mesh_file_button.setIcon(mesh_editor_action_icon("export", self.palette()))
        self.export_mesh_file_button.setIconSize(QSize(18, 18))
        self.export_mesh_file_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.export_mesh_file_button.setEnabled(False)
        self.export_mesh_file_button.clicked.connect(self.export_mesh_file_requested.emit)
        self._ui_font_widgets.append(self.export_mesh_file_button)
        controls.addWidget(self.export_mesh_file_button)
        self.build_mod_button = QToolButton(frame)
        self.build_mod_button.setObjectName("MeshEditorBuildModButton")
        self.build_mod_button.setText("Build Mod")
        self.build_mod_button.setAccessibleName("Build mesh mod")
        self.build_mod_button.setToolTip("Build a loose mod folder or DMM archive-group overlay package.")
        self.build_mod_button.setProperty("meshEditorIconKey", "export")
        self.build_mod_button.setIcon(mesh_editor_action_icon("export", self.palette()))
        self.build_mod_button.setIconSize(QSize(18, 18))
        self.build_mod_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.build_mod_button.setEnabled(False)
        self.build_mod_button.clicked.connect(self.build_mod_requested.emit)
        self._ui_font_widgets.append(self.build_mod_button)
        controls.addWidget(self.build_mod_button)
        self.install_overlay_button = QToolButton(frame)
        self.install_overlay_button.setObjectName("MeshEditorInstallOverlayButton")
        self.install_overlay_button.setText("Install as Overlay")
        self.install_overlay_button.setAccessibleName("Install mesh as overlay")
        self.install_overlay_button.setToolTip("Prepare, confirm, back up, and mount this mesh through the workbench overlay.")
        self.install_overlay_button.setProperty("meshEditorIconKey", "export")
        self.install_overlay_button.setIcon(mesh_editor_action_icon("export", self.palette()))
        self.install_overlay_button.setIconSize(QSize(18, 18))
        self.install_overlay_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.install_overlay_button.setEnabled(False)
        self.install_overlay_button.clicked.connect(self.install_overlay_requested.emit)
        self._ui_font_widgets.append(self.install_overlay_button)
        controls.addWidget(self.install_overlay_button)
        self.restore_overlay_button = QToolButton(frame)
        self.restore_overlay_button.setObjectName("MeshEditorRestoreOverlayButton")
        self.restore_overlay_button.setText("Restore Last Overlay Install")
        self.restore_overlay_button.setAccessibleName("Restore last mesh overlay install")
        self.restore_overlay_button.setToolTip("Restore the backup named by the last Mesh Editor overlay receipt.")
        self.restore_overlay_button.setEnabled(False)
        self.restore_overlay_button.clicked.connect(self.restore_overlay_requested.emit)
        self._ui_font_widgets.append(self.restore_overlay_button)
        controls.addWidget(self.restore_overlay_button)
        self.save_rebuild_report_button = QToolButton(frame)
        self.save_rebuild_report_button.setObjectName("MeshEditorSaveRebuildReportButton")
        self.save_rebuild_report_button.setText("Save")
        self.save_rebuild_report_button.setAccessibleName("Save rebuild report")
        self.save_rebuild_report_button.setToolTip("Save the last generated rebuild report as JSON.")
        self.save_rebuild_report_button.setProperty("meshEditorIconKey", "material_copy")
        self.save_rebuild_report_button.setIcon(mesh_editor_action_icon("material_copy", self.palette()))
        self.save_rebuild_report_button.setIconSize(QSize(18, 18))
        self.save_rebuild_report_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.save_rebuild_report_button.setEnabled(False)
        self.save_rebuild_report_button.clicked.connect(self.save_rebuild_report_requested.emit)
        self._ui_font_widgets.append(self.save_rebuild_report_button)
        controls.addWidget(self.save_rebuild_report_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.rebuild_tree = self._tree(("Field", "Value"), "MeshEditorRebuildReportPanel")
        layout.addWidget(self.rebuild_tree, 1)
        return frame

    def _focus_right_panel(self, title: str) -> None:
        tabs = getattr(self, "right_panels", None)
        if tabs is None:
            return
        normalized = str(title or "").strip().lower()
        widget = getattr(self, "_right_panels_by_title", {}).get(normalized)
        if widget is not None:
            index = tabs.indexOf(widget)
            if index >= 0:
                tabs.setCurrentIndex(index)
                return
        for index in range(tabs.count()):
            if tabs.tabText(index).strip().lower() == normalized:
                tabs.setCurrentIndex(index)
                return

    def _request_skeleton_native_preview(self) -> None:
        self._focus_right_panel("Rig")
        self.native_preview_requested.emit()

    def _build_uv_panel(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorUVPanelFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.uv_summary_label = QLabel("UV: no mesh", frame)
        self.uv_summary_label.setObjectName("MeshEditorUVSummaryLabel")
        self.uv_summary_label.setWordWrap(True)
        self._ui_font_widgets.append(self.uv_summary_label)
        layout.addWidget(self.uv_summary_label)
        layout.addWidget(self._build_uv_action_panel(frame))
        self.uv_canvas = MeshUvCanvas(frame)
        self.uv_canvas.region_selected.connect(self.uv_region_selected.emit)
        self.uv_canvas.lasso_selected.connect(self.uv_lasso_selected.emit)
        layout.addWidget(self.uv_canvas, 2)
        self.uv_tree = self._tree(("UV", "Value"), "MeshEditorUVPanel")
        self.uv_tree.itemClicked.connect(self._uv_tree_item_clicked)
        layout.addWidget(self.uv_tree, 1)
        return frame

    def _build_uv_action_panel(self, parent: QWidget) -> QWidget:
        frame = QFrame(parent)
        frame.setObjectName("MeshEditorUVActionPanel")
        layout = QGridLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(4)
        layout.setVerticalSpacing(4)
        self.uv_select_all_button = self._uv_command_button(
            frame,
            "MeshEditorUVSelectAllButton",
            "Select All",
            "select_face",
            "Select all mesh parts for UV editing.",
            lambda _checked=False: self.part_selection_requested.emit(-1, "select_all"),
        )
        self.uv_clear_selection_button = self._uv_command_button(
            frame,
            "MeshEditorUVClearSelectionButton",
            "Clear",
            "delete",
            "Clear UV edit selection.",
            lambda _checked=False: self.part_selection_requested.emit(-1, "clear"),
        )
        buttons = [
            self.uv_select_all_button,
            self.uv_clear_selection_button,
            self._uv_action_button(frame, "uv_flip_u"),
            self._uv_action_button(frame, "uv_flip_v"),
            self._uv_action_button(frame, "uv_rotate_90", text="Rotate 90"),
            self._uv_action_button(frame, "uv_normalize"),
            self._uv_action_button(frame, "uv_pack"),
            self._uv_action_button(frame, "uv_align_u"),
            self._uv_action_button(frame, "uv_align_v"),
            self._uv_action_button(frame, "uv_planar_project", text="Planar"),
            self._uv_action_button(frame, "uv_box_project", text="Box"),
            self._uv_action_button(frame, "uv_cylindrical_project", text="Cylinder"),
            self._uv_action_button(frame, "uv_auto_unwrap", text="Auto UV"),
            self._uv_action_button(frame, "uv_snap_grid", text="Snap Grid"),
            self._uv_action_button(frame, "uv_snap_pixels", text="Snap Pixel"),
        ]
        columns = 3 if self._embedded_controls_only else 2
        for index, button in enumerate(buttons):
            layout.addWidget(button, index // columns, index % columns)
        for column in range(columns):
            layout.setColumnStretch(column, 1)
        return frame

    def _uv_action_button(self, parent: QWidget, action_key: str, *, text: str = "") -> QToolButton:
        action = self._actions_by_key[action_key]
        return self._uv_command_button(
            parent,
            f"MeshEditorUVAction_{action.key}",
            text or action.text,
            action.icon_key,
            _workspace_action_tooltip(action),
            lambda _checked=False, current=action: self.action_requested.emit(current),
            action_key=action.key,
        )

    def _uv_command_button(
        self,
        parent: QWidget,
        object_name: str,
        text: str,
        icon_key: str,
        tooltip: str,
        callback: object,
        *,
        action_key: str = "",
    ) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName(object_name)
        button.setText(text)
        button.setAccessibleName(text)
        button.setToolTip(tooltip)
        button.setProperty("meshEditorIconKey", icon_key)
        button.setIcon(mesh_editor_action_icon(icon_key, self.palette()))
        button.setIconSize(QSize(18, 18))
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setAutoRaise(True)
        button.setMinimumHeight(28)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setEnabled(False)
        button.clicked.connect(callback)  # type: ignore[arg-type]
        self._ui_font_widgets.append(button)
        if action_key:
            self._uv_action_buttons[action_key] = button
        return button

    def _build_skeleton_panel(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorSkeletonPanelFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        if self._embedded_controls_only:
            hint = QLabel("Rig view: click a bone row to select/highlight it. Pose and weight authoring stays in the standalone rig tools.", frame)
            hint.setObjectName("MeshEditorSkeletonReadOnlyLabel")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            self.skeleton_tree = self._tree(("Skeleton", "Value"), "MeshEditorSkeletonPanel")
            self.skeleton_tree.itemClicked.connect(self._skeleton_tree_item_clicked)
            layout.addWidget(self.skeleton_tree, 1)
            return frame
        controls_frame = QFrame(frame)
        controls_frame.setObjectName("MeshEditorSkeletonControlsFrame")
        controls = QGridLayout(controls_frame)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setHorizontalSpacing(6)
        controls.setVerticalSpacing(4)

        def add_group_label(row: int, text: str) -> None:
            label = QLabel(text, controls_frame)
            label.setObjectName(f"MeshEditorSkeleton{text.replace(' ', '')}Label")
            self._ui_font_widgets.append(label)
            controls.addWidget(label, row, 0)

        add_group_label(0, "Preview")
        self.pose_preview_button = self._skeleton_pose_button("MeshEditorPosePreviewButton", "Pose", "toggle", checkable=True)
        self.pose_preview_button.clicked.connect(
            lambda checked=False: self.skeleton_pose_requested.emit("set_pose_preview", bool(checked))
        )
        controls.addWidget(self.pose_preview_button, 0, 1)
        add_group_label(1, "Pose")
        pose_column = 1
        for object_name, attr_name, text, rotation in (
            ("MeshEditorPoseRotateXButton", "pose_rotate_x_button", "Rot X", (15.0, 0.0, 0.0)),
            ("MeshEditorPoseRotateYButton", "pose_rotate_y_button", "Rot Y", (0.0, 15.0, 0.0)),
            ("MeshEditorPoseRotateZButton", "pose_rotate_z_button", "Rot Z", (0.0, 0.0, 15.0)),
        ):
            button = self._skeleton_pose_button(object_name, text, "transform_rotate")
            setattr(self, attr_name, button)
            button.clicked.connect(
                lambda _checked=False, current=rotation: self.skeleton_pose_requested.emit("rotate_selected_bone", current)
            )
            controls.addWidget(button, 1, pose_column)
            pose_column += 1
        self.pose_reset_button = self._skeleton_pose_button("MeshEditorPoseResetButton", "Reset", "undo")
        self.pose_reset_button.clicked.connect(lambda _checked=False: self.skeleton_pose_requested.emit("reset_pose", None))
        controls.addWidget(self.pose_reset_button, 1, pose_column)
        add_group_label(2, "Animation")
        self.animation_play_button = self._skeleton_pose_button("MeshEditorAnimationPlayButton", "Play", "transform_rotate", checkable=True)
        self.animation_play_button.clicked.connect(
            lambda checked=False: self.skeleton_pose_requested.emit("set_animation_playback", bool(checked))
        )
        controls.addWidget(self.animation_play_button, 2, 1)
        self.animation_step_button = self._skeleton_pose_button("MeshEditorAnimationStepButton", "Step", "redo")
        self.animation_step_button.clicked.connect(lambda _checked=False: self.skeleton_pose_requested.emit("step_animation_frame", 1))
        controls.addWidget(self.animation_step_button, 2, 2)
        self.animation_rewind_button = self._skeleton_pose_button("MeshEditorAnimationRewindButton", "Rewind", "undo")
        self.animation_rewind_button.clicked.connect(lambda _checked=False: self.skeleton_pose_requested.emit("seek_animation", 0.0))
        controls.addWidget(self.animation_rewind_button, 2, 3)
        self.animation_loop_button = self._skeleton_pose_button("MeshEditorAnimationLoopButton", "Loop", "toggle", checkable=True)
        self.animation_loop_button.clicked.connect(
            lambda checked=False: self.skeleton_pose_requested.emit("set_animation_loop", bool(checked))
        )
        controls.addWidget(self.animation_loop_button, 2, 4)
        self.animation_speed_combo = QComboBox(frame)
        self.animation_speed_combo.setObjectName("MeshEditorAnimationSpeedCombo")
        for label, value in (("0.25x", 0.25), ("0.5x", 0.5), ("1x", 1.0), ("2x", 2.0), ("4x", 4.0)):
            self.animation_speed_combo.addItem(label, value)
        self.animation_speed_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.animation_speed_combo.currentIndexChanged.connect(self._animation_speed_changed)
        controls.addWidget(self.animation_speed_combo, 2, 5)
        self.animation_scrub_slider = QSlider(Qt.Orientation.Horizontal, frame)
        self.animation_scrub_slider.setObjectName("MeshEditorAnimationScrubSlider")
        self.animation_scrub_slider.setRange(0, 1000)
        self.animation_scrub_slider.setMinimumWidth(120)
        self.animation_scrub_slider.valueChanged.connect(self._animation_scrub_changed)
        controls.addWidget(self.animation_scrub_slider, 2, 6)
        controls.setColumnStretch(6, 1)
        add_group_label(3, "Weights")
        weight_column = 1
        for object_name, attr_name, text, command, payload in (
            ("MeshEditorWeightIncreaseButton", "weight_increase_button", "W+", "adjust_selected_vertex_bone_weight", 0.1),
            ("MeshEditorWeightDecreaseButton", "weight_decrease_button", "W-", "adjust_selected_vertex_bone_weight", -0.1),
            ("MeshEditorWeightNormalizeButton", "weight_normalize_button", "Norm W", "normalize_selected_vertex_weights", None),
            ("MeshEditorWeightTransferButton", "weight_transfer_button", "Transfer W", "transfer_selected_vertex_weights_from_source", None),
        ):
            button = self._skeleton_pose_button(object_name, text, "select_vertex")
            setattr(self, attr_name, button)
            button.clicked.connect(
                lambda _checked=False, current_command=command, current_payload=payload: self.skeleton_pose_requested.emit(
                    current_command,
                    current_payload,
                )
            )
            controls.addWidget(button, 3, weight_column)
            weight_column += 1
        controls.setColumnStretch(weight_column, 1)
        layout.addWidget(controls_frame)
        self.skeleton_tree = self._tree(("Skeleton", "Value"), "MeshEditorSkeletonPanel")
        self.skeleton_tree.itemClicked.connect(self._skeleton_tree_item_clicked)
        layout.addWidget(self.skeleton_tree, 1)
        return frame

    def _skeleton_pose_button(
        self,
        object_name: str,
        text: str,
        icon_key: str,
        *,
        checkable: bool = False,
    ) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName(object_name)
        button.setText(text)
        button.setAccessibleName(text)
        button.setProperty("meshEditorIconKey", icon_key)
        button.setIcon(mesh_editor_action_icon(icon_key, self.palette()))
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setAutoRaise(True)
        button.setCheckable(checkable)
        button.setEnabled(False)
        self._ui_font_widgets.append(button)
        return button

    def _build_material_panel(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorMaterialPanelFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.part_selection_summary_label = QLabel("Selected parts: no mesh.", frame)
        self.part_selection_summary_label.setObjectName("MeshEditorPartSelectionSummary")
        self.part_selection_summary_label.setWordWrap(True)
        layout.addWidget(self.part_selection_summary_label)

        selection_controls = QHBoxLayout()
        selection_controls.setContentsMargins(0, 0, 0, 0)
        selection_controls.setSpacing(4)
        self.part_select_all_button = self._part_control_button(
            frame,
            "MeshEditorPartSelectAllButton",
            "All",
            "select_face",
            "Select all mesh parts.",
            lambda _checked=False: self.part_selection_requested.emit(-1, "select_all"),
        )
        self.part_clear_selection_button = self._part_control_button(
            frame,
            "MeshEditorPartClearSelectionButton",
            "Clear",
            "delete",
            "Clear selected mesh parts.",
            lambda _checked=False: self.part_selection_requested.emit(-1, "clear"),
        )
        self.part_invert_selection_button = self._part_control_button(
            frame,
            "MeshEditorPartInvertSelectionButton",
            "Invert",
            "toggle",
            "Invert selected mesh parts.",
            lambda _checked=False: self.part_selection_requested.emit(-1, "invert"),
        )
        for button in (self.part_select_all_button, self.part_clear_selection_button, self.part_invert_selection_button):
            selection_controls.addWidget(button)
        selection_controls.addStretch(1)
        layout.addLayout(selection_controls)

        action_grid = QGridLayout()
        action_grid.setContentsMargins(0, 0, 0, 0)
        action_grid.setHorizontalSpacing(4)
        action_grid.setVerticalSpacing(4)
        self.part_clone_button = self._part_action_button(
            frame, "MeshEditorPartCloneButton", "Clone", "duplicate", "Clone selected part(s).", "duplicate"
        )
        self.part_delete_button = self._part_action_button(
            frame, "MeshEditorPartDeleteButton", "Delete", "delete", "Delete selected part(s).", "delete"
        )
        self.part_recalculate_normals_button = self._part_action_button(
            frame,
            "MeshEditorPartRecalculateNormalsButton",
            "Recalculate Normals",
            "recalculate_normals",
            "Recalculate normals for selected part(s).",
            "recalculate_normals",
        )
        self.part_flip_normals_button = self._part_action_button(
            frame,
            "MeshEditorPartFlipNormalsButton",
            "Flip Normals",
            "flip_normals",
            "Flip normals for selected part(s).",
            "flip_normals",
        )
        for index, button in enumerate(
            (
                self.part_clone_button,
                self.part_delete_button,
                self.part_recalculate_normals_button,
                self.part_flip_normals_button,
            )
        ):
            action_grid.addWidget(button, index // 2, index % 2)
        action_grid.setColumnStretch(1, 1)
        layout.addLayout(action_grid)
        self.material_tree = self._part_tree(("Material", "Texture", "Slot"), "MeshEditorMaterialPanel")
        self._configure_part_tree(self.material_tree)
        layout.addWidget(self.material_tree, 1)
        return frame

    def _part_control_button(
        self,
        parent: QWidget,
        object_name: str,
        text: str,
        icon_key: str,
        tooltip: str,
        callback: object,
    ) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName(object_name)
        button.setText(text)
        button.setAccessibleName(text)
        button.setToolTip(tooltip)
        button.setProperty("meshEditorIconKey", icon_key)
        button.setIcon(mesh_editor_action_icon(icon_key, self.palette()))
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setEnabled(False)
        button.clicked.connect(callback)  # type: ignore[arg-type]
        self._ui_font_widgets.append(button)
        return button

    def _part_action_button(
        self,
        parent: QWidget,
        object_name: str,
        text: str,
        icon_key: str,
        tooltip: str,
        command: str,
    ) -> QToolButton:
        return self._part_control_button(
            parent,
            object_name,
            text,
            icon_key,
            tooltip,
            lambda _checked=False, current=command: self._emit_selected_part_action(current),
        )

    def _emit_selected_part_action(self, command: str) -> None:
        part_index = self._first_selected_part_index()
        if part_index >= 0:
            self.part_context_action_requested.emit(str(command or ""), part_index)

    def _first_selected_part_index(self) -> int:
        summary = self._workspace_summary
        if summary is None:
            return -1
        for part in summary.parts:
            if part.selected:
                return int(part.index)
        return -1

    def _sync_part_controls(self) -> None:
        summary = self._workspace_summary
        parts = tuple(summary.parts if summary is not None else ())
        selected = tuple(part for part in parts if part.selected)
        part_count = len(parts)
        selected_count = len(selected)
        has_parts = bool(self._has_editor_target and summary is not None and part_count)
        has_selection = bool(has_parts and selected_count)
        has_selected_texture = any(str(part.texture or "").strip() for part in selected)
        native_part_actions_enabled = bool(self._native_editor_available)
        for label_name, value in (
            ("part_selection_summary_label", _part_selection_summary_text(summary)),
            ("part_status_label", _part_selection_status_text(summary)),
        ):
            label = getattr(self, label_name, None)
            if label is not None:
                label.setText(value)
                label.setProperty("selectedPartCount", selected_count)
        for name, enabled in (
            ("part_select_all_button", has_parts and selected_count < part_count),
            ("part_clear_selection_button", has_selection),
            ("part_invert_selection_button", has_parts),
            ("part_clone_button", has_selection and native_part_actions_enabled),
            ("part_delete_button", has_selection and native_part_actions_enabled),
            ("part_recalculate_normals_button", has_selection),
            ("part_flip_normals_button", has_selection),
        ):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(bool(enabled))
