"""WorkspacePanelBuilderMixin methods for the Mesh Editor workspace."""

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

class WorkspacePanelBuilderMixin:
    def _build_right_panels(self) -> QTabWidget:
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
        self.update_session_summary(None)
        self.update_workspace_summary(None)
        self.update_uv_summary(None)
        self.update_export_validation(None)
        self.update_rebuild_report(None)
        self.set_native_performance_status(None)
        self.update_compare_summary(None)
        self.update_skeleton_summary(None)
        return tabs

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
        self.rebuild_asset_button = QToolButton(frame)
        self.rebuild_asset_button.setObjectName("MeshEditorRebuildPatchedAssetButton")
        self.rebuild_asset_button.setText("Rebuild")
        self.rebuild_asset_button.setAccessibleName("Rebuild patched asset")
        self.rebuild_asset_button.setToolTip("Write a validated rebuilt asset to a chosen file.")
        self.rebuild_asset_button.setProperty("meshEditorIconKey", "export")
        self.rebuild_asset_button.setIcon(mesh_editor_action_icon("export", self.palette()))
        self.rebuild_asset_button.setIconSize(QSize(18, 18))
        self.rebuild_asset_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.rebuild_asset_button.setEnabled(False)
        self.rebuild_asset_button.clicked.connect(self.rebuild_asset_requested.emit)
        self._ui_font_widgets.append(self.rebuild_asset_button)
        controls.addWidget(self.rebuild_asset_button)
        self.preview_rebuilt_asset_button = QToolButton(frame)
        self.preview_rebuilt_asset_button.setObjectName("MeshEditorPreviewRebuiltAssetButton")
        self.preview_rebuilt_asset_button.setText("Preview")
        self.preview_rebuilt_asset_button.setAccessibleName("Preview rebuilt asset")
        self.preview_rebuilt_asset_button.setToolTip("Preview the last rebuilt asset through the archive import preview flow.")
        self.preview_rebuilt_asset_button.setProperty("meshEditorIconKey", "select_face")
        self.preview_rebuilt_asset_button.setIcon(mesh_editor_action_icon("select_face", self.palette()))
        self.preview_rebuilt_asset_button.setIconSize(QSize(18, 18))
        self.preview_rebuilt_asset_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.preview_rebuilt_asset_button.setEnabled(False)
        self.preview_rebuilt_asset_button.clicked.connect(self.preview_rebuilt_asset_requested.emit)
        self._ui_font_widgets.append(self.preview_rebuilt_asset_button)
        controls.addWidget(self.preview_rebuilt_asset_button)
        self.package_rebuilt_asset_button = QToolButton(frame)
        self.package_rebuilt_asset_button.setObjectName("MeshEditorPackageRebuiltAssetButton")
        self.package_rebuilt_asset_button.setText("Package")
        self.package_rebuilt_asset_button.setAccessibleName("Package rebuilt asset")
        self.package_rebuilt_asset_button.setToolTip("Send the last rebuilt asset to the archive package or patch flow.")
        self.package_rebuilt_asset_button.setProperty("meshEditorIconKey", "export")
        self.package_rebuilt_asset_button.setIcon(mesh_editor_action_icon("export", self.palette()))
        self.package_rebuilt_asset_button.setIconSize(QSize(18, 18))
        self.package_rebuilt_asset_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.package_rebuilt_asset_button.setEnabled(False)
        self.package_rebuilt_asset_button.clicked.connect(self.package_rebuilt_asset_requested.emit)
        self._ui_font_widgets.append(self.package_rebuilt_asset_button)
        controls.addWidget(self.package_rebuilt_asset_button)
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
        self.open_texture_button = QToolButton(frame)
        self.open_texture_button.setObjectName("MeshEditorOpenTextureButton")
        self.open_texture_button.setText("Open Texture")
        self.open_texture_button.setAccessibleName("Open selected texture")
        self.open_texture_button.setToolTip("Open selected material texture in Texture Editor.")
        self.open_texture_button.setProperty("meshEditorIconKey", "material")
        self.open_texture_button.setIcon(mesh_editor_action_icon("material", self.palette()))
        self.open_texture_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.open_texture_button.setEnabled(False)
        self.open_texture_button.clicked.connect(self.texture_edit_requested.emit)
        for index, button in enumerate(
            (
                self.part_clone_button,
                self.part_delete_button,
                self.part_recalculate_normals_button,
                self.part_flip_normals_button,
                self.open_texture_button,
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
            ("open_texture_button", has_selection and has_selected_texture),
        ):
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(bool(enabled))
