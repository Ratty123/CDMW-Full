"""WorkspaceShellBuilderMixin methods for the Mesh Editor workspace."""

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

class WorkspaceShellBuilderMixin:
    def _build_top_bar(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorTopModeBar")
        layout = QGridLayout(frame) if self._embedded_controls_only else QHBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.mode_combo = self._combo("MeshEditorModeCombo", ("Object", "Edit", "Sculpt"))
        self.selection_combo = self._combo("MeshEditorSelectionCombo", ("Vertex", "Edge", "Face"))
        self.snap_combo = self._combo("MeshEditorSnapModeCombo", ("Off", "Grid", "Vertex", "Pixel"))
        self.pivot_combo = self._combo("MeshEditorPivotCombo", ("Median", "Center", "Cursor", "Individual"))
        self.orientation_combo = self._combo("MeshEditorOrientationCombo", ("Global", "Local", "Normal", "View"))
        self.viewport_display_combo = self._combo(
            "MeshEditorViewportDisplayCombo",
            ("Textured", "Faces", "Wire", "Vertices", "Wire + Vertices", "X-Ray"),
        )
        self.viewport_display_combo.setToolTip(
            "Change the resident .NET viewport without reloading geometry or textures."
        )
        controls = [
            ("Mode", self.mode_combo),
            ("Select", self.selection_combo),
            ("Snap", self.snap_combo),
            ("Pivot", self.pivot_combo),
            ("Orient", self.orientation_combo),
        ]
        if self._embedded_controls_only:
            controls.append(("View", self.viewport_display_combo))
        for index, (label_text, widget) in enumerate(controls):
            label = QLabel(label_text, frame)
            label.setObjectName(f"{widget.objectName()}Label")
            self._ui_font_widgets.append(label)
            if self._embedded_controls_only:
                widget.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                widget.setMinimumContentsLength(6)
                widget.setMinimumWidth(72)
                widget.setMaximumWidth(118)
                row = index // 3
                column = (index % 3) * 2
                layout.addWidget(label, row, column)
                layout.addWidget(widget, row, column + 1)
            else:
                layout.addWidget(label)
                layout.addWidget(widget)
        if not self._embedded_controls_only:
            layout.addStretch(1)
        self.mode_combo.currentTextChanged.connect(self._mode_changed)
        self.selection_combo.currentTextChanged.connect(self._selection_changed)
        if self._embedded_controls_only:
            self.viewport_display_combo.currentTextChanged.connect(
                lambda text: self.viewport_display_requested.emit(
                    {
                        "Textured": "textured",
                        "Faces": "untextured_faces",
                        "Wire": "wire",
                        "Vertices": "vertices",
                        "Wire + Vertices": "wire_vertices",
                        "X-Ray": "xray",
                    }.get(str(text), "textured")
                )
            )
            self.viewport_display_combo.setEnabled(False)
        else:
            self.viewport_display_combo.setVisible(False)
        return frame

    def _build_body(self, theme_key: str) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setObjectName("MeshEditorWorkspaceBody")
        splitter.addWidget(self._build_left_palette())
        splitter.addWidget(self._build_preview_area(theme_key))
        splitter.addWidget(self._build_right_panels())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes((190, 900, 340))
        return splitter

    def _build_left_palette(self) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorLeftToolPalette")
        frame.setMinimumWidth(168)
        frame.setMaximumWidth(230)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.left_tool_pages = QTabWidget(frame)
        self.left_tool_pages.setObjectName("MeshEditorLeftToolPages")
        self.left_tool_pages.setTabPosition(QTabWidget.TabPosition.North)
        for title, categories in _LEFT_TOOL_PAGES:
            page = self._build_left_tool_page(title, categories)
            self.left_tool_pages.addTab(page, title)
        layout.addWidget(self.left_tool_pages, 1)
        return frame

    def _build_left_tool_page(self, title: str, categories: Sequence[str]) -> QWidget:
        page = QFrame(self)
        page.setObjectName(f"MeshEditorLeftToolPage_{title.replace(' ', '')}")
        layout = QGridLayout(page)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setHorizontalSpacing(4)
        layout.setVerticalSpacing(4)
        row = 0
        if str(title).strip().lower() == "rig":
            row = self._add_rig_palette_controls(page, layout, row)
        for category in categories:
            category_actions = tuple(action for action in self._actions_by_key.values() if action.category == category)
            if not category_actions:
                continue
            label = QLabel(_LEFT_CATEGORY_LABELS.get(category, category.title()), page)
            label.setObjectName(f"MeshEditorToolCategory_{category}")
            self._ui_font_widgets.append(label)
            layout.addWidget(label, row, 0, 1, 3)
            row += 1
            for index, action in enumerate(category_actions):
                button = self._workspace_action_button(page, action)
                layout.addWidget(button, row + index // 3, index % 3)
            row += (len(category_actions) + 2) // 3
        layout.setRowStretch(row, 1)
        return page

    def _workspace_action_button(self, parent: QWidget, action: MeshEditorAction) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName(f"MeshEditorWorkspaceAction_{action.key}")
        button.setText(action.text)
        button.setAccessibleName(action.text)
        button.setIcon(mesh_editor_action_icon(action.icon_key, self.palette()))
        button.setIconSize(QSize(18, 18))
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setToolTip(_workspace_action_tooltip(action))
        button.setProperty("meshEditorActionKey", action.key)
        button.setProperty("meshEditorIconKey", action.icon_key)
        button.setAutoRaise(True)
        button.setFixedSize(42, 36)
        button.clicked.connect(lambda _checked=False, current=action: self.action_requested.emit(current))
        self._buttons_by_key[action.key] = button
        return button

    def _add_rig_palette_controls(self, parent: QWidget, layout: QGridLayout, row: int) -> int:
        label = QLabel("Character Preview", parent)
        label.setObjectName("MeshEditorToolCategory_rig")
        self._ui_font_widgets.append(label)
        layout.addWidget(label, row, 0, 1, 3)
        row += 1
        self.rig_skeleton_button = self._rig_palette_button(
            parent,
            "MeshEditorRigSkeletonButton",
            "Skeleton",
            "select_edge",
            "Open the Skeleton panel.",
        )
        self.rig_skeleton_button.clicked.connect(lambda _checked=False: self._focus_right_panel("Rig"))
        layout.addWidget(self.rig_skeleton_button, row, 0)
        self.rig_pose_button = self._rig_palette_button(
            parent,
            "MeshEditorRigPosePreviewButton",
            "Pose",
            "transform_rotate",
            "Toggle skinned pose preview.",
            checkable=True,
        )
        self.rig_pose_button.clicked.connect(
            lambda checked=False: self.skeleton_pose_requested.emit("set_pose_preview", bool(checked))
        )
        layout.addWidget(self.rig_pose_button, row, 1)
        self.rig_weight_transfer_button = self._rig_palette_button(
            parent,
            "MeshEditorRigWeightTransferButton",
            "Transfer W",
            "select_vertex",
            "Transfer selected vertex weights from the source mesh.",
        )
        self.rig_weight_transfer_button.clicked.connect(
            lambda _checked=False: self.skeleton_pose_requested.emit("transfer_selected_vertex_weights_from_source", None)
        )
        layout.addWidget(self.rig_weight_transfer_button, row, 2)
        row += 1
        self.rig_weight_normalize_button = self._rig_palette_button(
            parent,
            "MeshEditorRigWeightNormalizeButton",
            "Norm W",
            "select_vertex",
            "Normalize selected vertex weights.",
        )
        self.rig_weight_normalize_button.clicked.connect(
            lambda _checked=False: self.skeleton_pose_requested.emit("normalize_selected_vertex_weights", None)
        )
        layout.addWidget(self.rig_weight_normalize_button, row, 0)
        return row + 1

    def _rig_palette_button(
        self,
        parent: QWidget,
        object_name: str,
        text: str,
        icon_key: str,
        tooltip: str,
        *,
        checkable: bool = False,
    ) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName(object_name)
        button.setText(text)
        button.setAccessibleName(text)
        button.setToolTip(tooltip)
        button.setProperty("meshEditorIconKey", icon_key)
        button.setIcon(mesh_editor_action_icon(icon_key, self.palette()))
        button.setIconSize(QSize(18, 18))
        button.setToolButtonStyle(Qt.ToolButtonIconOnly)
        button.setAutoRaise(True)
        button.setCheckable(checkable)
        button.setEnabled(False)
        button.setFixedSize(42, 36)
        self._ui_font_widgets.append(button)
        return button

    def _build_preview_area(self, theme_key: str) -> QWidget:
        frame = QFrame(self)
        frame.setObjectName("MeshEditorCentralPreview")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.preview_stack = QStackedWidget(frame)
        self.preview_stack.setObjectName("MeshEditorStandalonePreviewStack")
        self.native_host_frame = DotNetPreviewHostFrame(
            frame,
            profile=DotNetPreviewProfile.AUTHORING,
        )
        self.native_host_frame.setObjectName("MeshEditorStandaloneDotNetVorticeHost")
        # Retained off-stack as a data/settings compatibility adapter.  The
        # resident Vortice host is the only visible model-preview widget.
        self.preview = NativePreviewPanel("Mesh Editor preview.", theme_key=theme_key)
        self.preview.setObjectName("MeshEditorStandalonePreviewCompatibilityAdapter")
        self.preview.setParent(frame)
        self.preview.setVisible(False)
        self.preview_stack.addWidget(self.native_host_frame)
        self.preview_stack.setCurrentWidget(self.native_host_frame)
        layout.addWidget(self.preview_stack, 1)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        self.native_preview_button = QPushButton(".NET/Vortice", frame)
        self.native_preview_button.setObjectName("MeshEditorStandaloneNativePreviewButton")
        self.native_preview_button.setToolTip("Reload the resident .NET/Vortice preview.")
        self.native_preview_button.setMinimumHeight(28)
        self.native_preview_button.setVisible(False)
        self.native_preview_button.setEnabled(False)
        self.native_preview_button.clicked.connect(self.native_preview_requested.emit)
        self.export_editable_package_button = QPushButton("Export", frame)
        self.export_editable_package_button.setObjectName("MeshEditorExportEditablePackageButton")
        self.export_editable_package_button.setToolTip("Export the current mesh as an editable package with sidecar metadata.")
        self.export_editable_package_button.setMinimumHeight(28)
        self.export_editable_package_button.setEnabled(False)
        self.export_editable_package_button.clicked.connect(self.export_editable_package_requested.emit)
        controls.addWidget(self.export_editable_package_button)
        self.import_edited_package_button = QPushButton("Import", frame)
        self.import_edited_package_button.setObjectName("MeshEditorImportEditedPackageButton")
        self.import_edited_package_button.setToolTip("Import an edited mesh package and run validation before rebuild.")
        self.import_edited_package_button.setMinimumHeight(28)
        self.import_edited_package_button.setEnabled(False)
        self.import_edited_package_button.clicked.connect(self.import_edited_package_requested.emit)
        controls.addWidget(self.import_edited_package_button)
        self.open_editable_package_folder_button = QPushButton("Open", frame)
        self.open_editable_package_folder_button.setObjectName("MeshEditorOpenEditablePackageFolderButton")
        self.open_editable_package_folder_button.setToolTip("Open the last editable mesh package folder.")
        self.open_editable_package_folder_button.setMinimumHeight(28)
        self.open_editable_package_folder_button.setEnabled(False)
        self.open_editable_package_folder_button.clicked.connect(self.open_editable_package_folder_requested.emit)
        controls.addWidget(self.open_editable_package_folder_button)
        self.dotnet_editor_button = QPushButton(".NET", frame)
        self.dotnet_editor_button.setObjectName("MeshEditorDotNetExperimentButton")
        self.dotnet_editor_button.setToolTip("Export the current Mesh Editor package and open it in the configured .NET editor experiment.")
        self.dotnet_editor_button.setMinimumHeight(28)
        self.dotnet_editor_button.setEnabled(False)
        self.dotnet_editor_button.clicked.connect(self.dotnet_editor_requested.emit)
        controls.addWidget(self.dotnet_editor_button)
        self.native_performance_status_label = QLabel("FPS: -- | Frame: -- ms", frame)
        self.native_performance_status_label.setObjectName("MeshEditorNativePerformanceStatus")
        self.native_performance_status_label.setAccessibleName(".NET/Vortice preview performance")
        self.native_performance_status_label.setToolTip(".NET/Vortice preview FPS and frame timing.")
        self.native_performance_status_label.setMinimumWidth(180)
        self.native_performance_status_label.setProperty("nativePerformanceAvailable", False)
        controls.addWidget(self.native_performance_status_label)
        self.native_part_pick_status_label = QLabel("Part pick: preview off", frame)
        self.native_part_pick_status_label.setObjectName("MeshEditorNativePartPickStatus")
        self.native_part_pick_status_label.setProperty("nativePartPickingAvailable", False)
        controls.addWidget(self.native_part_pick_status_label)
        self.preview_skeleton_button = QToolButton(frame)
        self.preview_skeleton_button.setObjectName("MeshEditorPreviewSkeletonButton")
        self.preview_skeleton_button.setText("Skeleton")
        self.preview_skeleton_button.setAccessibleName("Show skeleton preview")
        self.preview_skeleton_button.setToolTip("Open Skeleton panel and refresh the .NET/Vortice skeleton overlay metadata.")
        self.preview_skeleton_button.setProperty("meshEditorIconKey", "select_edge")
        self.preview_skeleton_button.setIcon(mesh_editor_action_icon("select_edge", self.palette()))
        self.preview_skeleton_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.preview_skeleton_button.setEnabled(False)
        self.preview_skeleton_button.clicked.connect(self._request_skeleton_native_preview)
        controls.addWidget(self.preview_skeleton_button)
        self.preview_pose_button = QToolButton(frame)
        self.preview_pose_button.setObjectName("MeshEditorPreviewPoseButton")
        self.preview_pose_button.setText("Pose")
        self.preview_pose_button.setAccessibleName("Toggle pose preview")
        self.preview_pose_button.setToolTip("Toggle skinned pose preview deformation.")
        self.preview_pose_button.setProperty("meshEditorIconKey", "transform_rotate")
        self.preview_pose_button.setIcon(mesh_editor_action_icon("transform_rotate", self.palette()))
        self.preview_pose_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.preview_pose_button.setCheckable(True)
        self.preview_pose_button.setEnabled(False)
        self.preview_pose_button.clicked.connect(
            lambda checked=False: self.skeleton_pose_requested.emit("set_pose_preview", bool(checked))
        )
        controls.addWidget(self.preview_pose_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        return frame
