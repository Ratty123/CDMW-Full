"""Standalone Mesh Editor workspace layout."""

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


from cdmw.ui.mesh_editor.workspace_interaction import WorkspaceInteractionMixin
from cdmw.ui.mesh_editor.workspace_panel_builder import WorkspacePanelBuilderMixin
from cdmw.ui.mesh_editor.workspace_reports import WorkspaceReportMixin
from cdmw.ui.mesh_editor.workspace_shell_builder import WorkspaceShellBuilderMixin
from cdmw.ui.mesh_editor.workspace_skeleton_state import WorkspaceSkeletonStateMixin
from cdmw.ui.mesh_editor.workspace_state import WorkspaceStateMixin
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

class MeshEditorWorkspace(
    WorkspaceStateMixin,
    WorkspaceSkeletonStateMixin,
    WorkspaceShellBuilderMixin,
    WorkspacePanelBuilderMixin,
    WorkspaceReportMixin,
    WorkspaceInteractionMixin,
    QFrame,
):
    action_requested = Signal(object)
    native_preview_requested = Signal()
    export_editable_package_requested = Signal()
    import_edited_package_requested = Signal()
    open_editable_package_folder_requested = Signal()
    dotnet_editor_requested = Signal()
    texture_edit_requested = Signal()
    validation_report_requested = Signal()
    copy_validation_report_requested = Signal()
    compare_view_requested = Signal(str)
    skeleton_pose_requested = Signal(str, object)
    part_selection_requested = Signal(int, str)
    part_context_action_requested = Signal(str, int)
    uv_region_selected = Signal(tuple, tuple, str)
    uv_lasso_selected = Signal(tuple, str)
    rebuild_report_requested = Signal()
    rebuild_asset_requested = Signal()
    preview_rebuilt_asset_requested = Signal()
    package_rebuilt_asset_requested = Signal()
    save_rebuild_report_requested = Signal()

    def __init__(
        self,
        *,
        theme_key: str = "graphite",
        actions: Sequence[MeshEditorAction] = MESH_EDITOR_ACTIONS,
        embedded_controls_only: bool = False,
        object_name: str = "MeshEditorStandaloneWorkspace",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(str(object_name or "MeshEditorStandaloneWorkspace"))
        self._theme_key = str(theme_key or "graphite")
        self._actions_by_key = {action.key: action for action in actions}
        self._buttons_by_key: dict[str, QToolButton] = {}
        self._uv_action_buttons: dict[str, QToolButton] = {}
        self._ui_font_widgets: list[QWidget] = []
        self._updating_state = False
        self._has_editor_target = False
        self._native_editor_available = True
        self._workspace_summary: MeshWorkspaceSummary | None = None
        self._uv_summary: MeshUvSummary | None = None
        self._has_export_validation_report = False
        self._export_validation_ok = False
        self._has_rebuild_report = False
        self._has_rebuilt_asset_output = False
        self._embedded_controls_only = bool(embedded_controls_only)
        self._last_slow_frame_log_key: tuple[object, ...] | None = None

        root = QVBoxLayout(self)
        margin = 0 if embedded_controls_only else 6
        root.setContentsMargins(margin, margin, margin, margin)
        root.setSpacing(4)
        root.addWidget(self._build_top_bar())
        if embedded_controls_only:
            root.addWidget(self._build_right_panels(), 1)
            self.right_panels.setMinimumWidth(0)
            self.right_panels.setMaximumWidth(16777215)
            self.right_panels.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        else:
            root.addWidget(self._build_body(theme_key), 1)
        root.addWidget(self._build_status_strip())


__all__ = ["MeshEditorWorkspace"]
