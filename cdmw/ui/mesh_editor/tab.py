from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, is_dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Mapping, Optional, Sequence

from PySide6.QtCore import QPoint, QProcess, QSettings, QThread, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.mesh import (
    DEVELOPER_OVERRIDABLE_REBUILD_BLOCKERS,
    MeshEditCommand,
    MeshEditResult,
    MeshEditSelection,
    MeshEditSessionView,
)
from cdmw.models import ModelPreviewData, ModelPreviewRenderSettings, TextureEditorSourceBinding
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_dotnet_experiment import (
    MeshDotNetExperimentPackage,
    find_mesh_dotnet_experiment_editor,
    mesh_dotnet_experiment_command,
    mesh_dotnet_experiment_output_obj_path,
    write_mesh_dotnet_experiment_evaluation,
)
from cdmw.services.mesh_service import MeshService
from cdmw.ui.shell.settings_bridge import read_bool_setting
from cdmw.ui.mesh_editor.action_bar import MeshEditorActionBar
from cdmw.ui.mesh_editor.actions import NATIVE_EDITOR_SESSION_COMMANDS, mesh_editor_actions_by_key
from cdmw.ui.mesh_editor.controller import (
    MeshEditorActionExecution,
    MeshEditorController,
    MeshEditorNativeUpdate,
    apply_native_update_to_host,
)
from cdmw.ui.mesh_editor.native_preview_runtime import (
    _host_widget_hwnd,
    mesh_editor_native_preview_data,
    mesh_editor_native_preview_command,
    mesh_editor_write_prepared_native_preview_package,
    mesh_editor_write_native_preview_package,
)
from cdmw.ui.mesh_editor.native_preview_payloads import mesh_pose_to_native_preview
from cdmw.ui.mesh_editor.session import MeshEditorSessionRequest
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace
from cdmw.workers.mesh_editor_workers import (
    MeshEditCommandWorker,
    MeshEditablePackageExportWorker,
    MeshEditablePackageImportWorker,
    MeshDotNetExperimentOutputImportWorker,
    MeshDotNetExperimentPackageWorker,
    MeshFileSessionLoadWorker,
    MeshExportValidationWorker,
    MeshNativePreviewPackageWorker,
    MeshRebuildReportWorker,
    MeshTextureSourceResolveWorker,
)

_STANDALONE_NATIVE_TOOL_STATE: dict[str, tuple[str, str, str]] = {
    "transform_move": ("move", "selection", "edit"),
    "brush_grab": ("grab", "selection", "sculpt"),
    "brush_smooth": ("smooth", "selection", "sculpt"),
    "brush_inflate": ("inflate", "selection", "sculpt"),
    "brush_pinch": ("pinch", "selection", "sculpt"),
}
_LEGACY_SCREEN_CAMERA_FIELDS = frozenset(
    {"camera_world", "yaw_degrees", "pitch_degrees", "distance", "vertical_fov_degrees", "pan"}
)

try:  # pragma: no cover - import guard keeps source tests light.
    from cdmw.models import ArchiveEntry
except Exception:  # pragma: no cover
    ArchiveEntry = object  # type: ignore[assignment]

try:  # pragma: no cover
    from cdmw.modding.scene_importer import SceneImportResult
except Exception:  # pragma: no cover
    SceneImportResult = object  # type: ignore[assignment]


class MeshEditorTab(QWidget):
    """Main mesh replacement/editing workspace host.

    The full Mesh Replacement Builder is mounted here for active sessions so the
    D3D11 preview, tabs, build preflight, and archive safety gates stay shared.
    """

    status_message_requested = Signal(str, bool)
    modify_original_requested = Signal(object)
    import_replacement_requested = Signal(object)
    import_preview_requested = Signal(object)
    preview_rebuilt_asset_requested = Signal(object, object)
    package_rebuilt_asset_requested = Signal(object, object)
    in_game_swap_requested = Signal(object)
    open_archive_target_requested = Signal(object)
    mesh_action_requested = Signal(object)
    open_texture_source_requested = Signal(str, object)

    def __init__(
        self,
        *,
        settings: QSettings,
        theme_key: str = "graphite",
        get_archive_texture_entries_by_normalized_path: Callable[[], Mapping[str, Sequence[ArchiveEntry]]] | None = None,
        get_archive_texture_entries_by_basename: Callable[[], Mapping[str, Sequence[ArchiveEntry]]] | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.theme_key = str(theme_key or "graphite")
        self.current_request: Optional[MeshEditorSessionRequest] = None
        self.current_archive_selection: Optional[ArchiveEntry] = None
        self.current_edit_mode = "object"
        self.current_selection_mode = "vertex"
        self.current_tool_action_key = ""
        self.current_selection_empty = True
        self.current_undo_count = 0
        self.current_redo_count = 0
        self.standalone_controller: MeshEditorController | None = None
        self.standalone_file_load_thread: QThread | None = None
        self.standalone_file_load_worker: MeshFileSessionLoadWorker | None = None
        self.standalone_file_load_target_entry: object | None = None
        self.standalone_file_load_source_skeleton: object | None = None
        self.standalone_file_load_request_id = 0
        self.standalone_texture_source_thread: QThread | None = None
        self.standalone_texture_source_worker: MeshTextureSourceResolveWorker | None = None
        self.standalone_texture_source_request_id = 0
        self.standalone_texture_source_target: object | None = None
        self.standalone_texture_source_controller: MeshEditorController | None = None
        self.get_archive_texture_entries_by_normalized_path = get_archive_texture_entries_by_normalized_path
        self.get_archive_texture_entries_by_basename = get_archive_texture_entries_by_basename
        self.standalone_native_host: object | None = None
        self.standalone_native_process: QProcess | None = None
        self.standalone_native_package_thread: QThread | None = None
        self.standalone_native_package_worker: MeshNativePreviewPackageWorker | None = None
        self.standalone_native_package_request_id = 0
        self.standalone_action_thread: QThread | None = None
        self.standalone_action_worker: MeshEditCommandWorker | None = None
        self.standalone_action_progress: QProgressDialog | None = None
        self.standalone_action_request_id = 0
        self.standalone_action_text = ""
        self.standalone_rebuild_report_thread: QThread | None = None
        self.standalone_rebuild_report_worker: MeshRebuildReportWorker | None = None
        self.standalone_rebuild_report_progress: QProgressDialog | None = None
        self.standalone_rebuild_report_request_id = 0
        self.standalone_validation_thread: QThread | None = None
        self.standalone_validation_worker: MeshExportValidationWorker | None = None
        self.standalone_validation_request_id = 0
        self.standalone_dotnet_package_thread: QThread | None = None
        self.standalone_dotnet_package_worker: MeshDotNetExperimentPackageWorker | None = None
        self.standalone_dotnet_package_request_id = 0
        self.standalone_dotnet_import_thread: QThread | None = None
        self.standalone_dotnet_import_worker: MeshDotNetExperimentOutputImportWorker | None = None
        self.standalone_dotnet_import_request_id = 0
        self.standalone_editable_export_thread: QThread | None = None
        self.standalone_editable_export_worker: MeshEditablePackageExportWorker | None = None
        self.standalone_editable_export_request_id = 0
        self.standalone_editable_import_thread: QThread | None = None
        self.standalone_editable_import_worker: MeshEditablePackageImportWorker | None = None
        self.standalone_editable_import_request_id = 0
        self.standalone_dotnet_editor_process: QProcess | None = None
        self.standalone_dotnet_experiment_package: MeshDotNetExperimentPackage | None = None
        self.standalone_dotnet_status_payload: dict[str, object] = {}
        self.standalone_dotnet_target_controller: MeshEditorController | None = None
        self.standalone_dotnet_target_embedded = False
        self.standalone_dotnet_embedded_state = "closed"
        self.standalone_dotnet_protocol_stdout = ""
        self.standalone_dotnet_protocol_events: list[dict[str, object]] = []
        self.embedded_dotnet_editor_button: QPushButton | None = None
        self.standalone_last_export_validation_report: object | None = None
        self.standalone_last_rebuild_report: object | None = None
        self.standalone_last_rebuilt_asset_path: Path | None = None
        self.standalone_last_action_result: MeshEditResult | None = None
        self.standalone_last_action_metrics: dict[str, float] = {}
        self.standalone_native_package_reset_view = True
        self.standalone_mesh_label = ""
        self.standalone_source_skeleton: object | None = None
        self.standalone_compare_mode = "edited"
        self.standalone_texture_preview_overrides: dict[int, str] = {}
        self.standalone_native_package_dir: Path | None = None
        self.standalone_native_status_file: Path | None = None
        self.standalone_native_package_has_reference = False
        self.standalone_native_package_pending_has_reference = False
        self.standalone_native_package_compare_mode = "edited"
        self.standalone_native_package_pending_compare_mode = "edited"
        self.standalone_native_status_signature: tuple[int, int] = (0, 0)
        self.standalone_native_status_payload_text = ""
        self.standalone_native_last_status_payload: dict[str, object] = {}
        self.standalone_native_part_picking_wanted = False
        self.standalone_native_part_picking_enabled = False
        self.standalone_native_mesh_edit_state_signature: tuple[object, ...] = ()
        self.standalone_native_mesh_edit_stroke_id = ""
        self.standalone_native_mesh_edit_stroke_changed = False
        self.embedded_workspace: MeshEditorWorkspace | None = None
        self._embedded_control_tabs: QTabWidget | None = None
        self._embedded_classic_builder: QWidget | None = None
        self.standalone_native_status_timer = QTimer(self)
        self.standalone_native_status_timer.setInterval(250)
        self.standalone_native_status_timer.timeout.connect(self._poll_standalone_native_preview_status)
        self.standalone_animation_timer = QTimer(self)
        self.standalone_animation_timer.setInterval(33)
        self.standalone_animation_timer.timeout.connect(self._tick_standalone_animation_playback)
        self.standalone_animation_last_tick = 0.0
        self._wired_standalone_native_host_ids: set[int] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.action_bar = MeshEditorActionBar(parent=self)
        self.action_bar.action_requested.connect(self._handle_action_requested)
        root.addWidget(self.action_bar)

        self.workspace_stack = QStackedWidget(self)
        self.workspace_stack.setObjectName("MeshEditorWorkspaceStack")
        self.empty_state = self._build_empty_state()
        self.standalone_workspace = self._build_standalone_workspace()
        self.embedded_builder_host = QFrame(self)
        self.embedded_builder_host.setObjectName("MeshEditorEmbeddedBuilderHost")
        self.embedded_builder_host.setFrameShape(QFrame.Shape.NoFrame)
        self.embedded_builder_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.embedded_builder_host_layout = QVBoxLayout(self.embedded_builder_host)
        self.embedded_builder_host_layout.setContentsMargins(0, 0, 0, 0)
        self.embedded_builder_host_layout.setSpacing(0)

        self.workspace_stack.addWidget(self.empty_state)
        self.workspace_stack.addWidget(self.standalone_workspace)
        self.workspace_stack.addWidget(self.embedded_builder_host)
        root.addWidget(self.workspace_stack, 1)

        self._sync_state()

    def _build_empty_state(self) -> QWidget:
        page = QFrame(self)
        page.setObjectName("MeshEditorEmptyState")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        header = QFrame(page)
        header.setObjectName("MeshEditorEmptyHeader")
        header_layout = QGridLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setHorizontalSpacing(8)
        header_layout.setVerticalSpacing(3)

        self.target_label = QLabel("Target: none")
        self.target_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.target_label.setWordWrap(True)
        self.session_label = QLabel("Mode: no active session")
        self.session_label.setObjectName("HintLabel")
        self.session_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.open_archive_button = QPushButton("Show Target In Archive")
        self.open_archive_button.setObjectName("MeshEditorShowTargetArchiveButton")
        self.open_archive_button.clicked.connect(self._emit_open_archive_target)

        header_layout.addWidget(self.target_label, 0, 0)
        header_layout.addWidget(self.session_label, 1, 0)
        header_layout.addWidget(self.open_archive_button, 0, 1, 2, 1)
        header_layout.setColumnStretch(0, 1)
        layout.addWidget(header)

        self.empty_status_label = QLabel("Select a supported archive mesh, then choose a workflow.")
        self.empty_status_label.setObjectName("MeshEditorEmptyStatus")
        self.empty_status_label.setWordWrap(True)
        layout.addWidget(self.empty_status_label)

        workflow_row = QHBoxLayout()
        workflow_row.setSpacing(8)
        self.modify_original_button = QPushButton("Modify Original")
        self.modify_original_button.setObjectName("MeshEditorModifyOriginalButton")
        self.import_replacement_button = QPushButton("Import Replacement")
        self.import_replacement_button.setObjectName("MeshEditorImportReplacementButton")
        self.import_preview_button = QPushButton("Import Preview")
        self.import_preview_button.setObjectName("MeshEditorImportPreviewButton")
        self.in_game_swap_button = QPushButton("In-Game Swap")
        self.in_game_swap_button.setObjectName("MeshEditorInGameSwapButton")
        self.modify_original_button.setToolTip("Create or reopen an editable clone workspace for the selected archive mesh.")
        self.import_replacement_button.setToolTip("Import OBJ, DAE, glTF, GLB, PAC, PAM, or PAMLOD as the replacement source.")
        self.import_preview_button.setToolTip("Run the same import path as preview-only, without writing output.")
        self.in_game_swap_button.setToolTip("Use another loaded archive mesh as the source for this target.")
        for button in (
            self.modify_original_button,
            self.import_replacement_button,
            self.import_preview_button,
            self.in_game_swap_button,
        ):
            button.setMinimumHeight(30)
            workflow_row.addWidget(button)
        workflow_row.addStretch(1)
        layout.addLayout(workflow_row)
        layout.addStretch(1)

        self.modify_original_button.clicked.connect(lambda _checked=False: self._emit_target(self.modify_original_requested))
        self.import_replacement_button.clicked.connect(lambda _checked=False: self._emit_target(self.import_replacement_requested))
        self.import_preview_button.clicked.connect(lambda _checked=False: self._emit_target(self.import_preview_requested))
        self.in_game_swap_button.clicked.connect(lambda _checked=False: self._emit_target(self.in_game_swap_requested))
        return page

    def _build_standalone_workspace(self) -> QWidget:
        page = MeshEditorWorkspace(theme_key=self.theme_key, parent=self)
        page.action_requested.connect(self._handle_action_requested)
        page.native_preview_requested.connect(self._start_standalone_native_preview_requested)
        page.export_editable_package_requested.connect(self._start_standalone_export_editable_package_requested)
        page.import_edited_package_requested.connect(self._start_standalone_import_edited_package_requested)
        page.open_editable_package_folder_requested.connect(self._open_standalone_editable_package_folder)
        page.dotnet_editor_requested.connect(self._start_standalone_dotnet_editor_requested)
        page.texture_edit_requested.connect(self.open_selected_texture_in_editor)
        page.compare_view_requested.connect(self._set_standalone_compare_mode)
        page.skeleton_pose_requested.connect(self._handle_skeleton_pose_request)
        page.part_selection_requested.connect(self._handle_part_selection)
        page.part_context_action_requested.connect(self._handle_part_context_action)
        page.uv_region_selected.connect(self._handle_uv_region_selection)
        page.uv_lasso_selected.connect(self._handle_uv_lasso_selection)
        page.validation_report_requested.connect(self._start_standalone_export_validation_requested)
        page.copy_validation_report_requested.connect(self._copy_standalone_validation_report_requested)
        page.rebuild_report_requested.connect(self._start_standalone_rebuild_report_requested)
        page.rebuild_asset_requested.connect(self._start_standalone_rebuild_asset_requested)
        page.preview_rebuilt_asset_requested.connect(self._preview_standalone_rebuilt_asset_requested)
        page.package_rebuilt_asset_requested.connect(self._package_standalone_rebuilt_asset_requested)
        page.save_rebuild_report_requested.connect(self._save_standalone_rebuild_report_requested)
        self.standalone_preview_stack = page.preview_stack
        self.standalone_native_host_frame = page.native_host_frame
        self.standalone_preview = page.preview
        self.standalone_native_host = page.native_host_frame
        self._wire_standalone_native_part_events(self.standalone_native_host)
        self.standalone_native_preview_button = page.native_preview_button
        self.standalone_run_validation_report_button = page.run_validation_report_button
        self.standalone_rebuild_asset_button = page.rebuild_asset_button
        self.standalone_preview_rebuilt_asset_button = page.preview_rebuilt_asset_button
        self.standalone_package_rebuilt_asset_button = page.package_rebuilt_asset_button
        self.standalone_export_editable_package_button = page.export_editable_package_button
        self.standalone_import_edited_package_button = page.import_edited_package_button
        self.standalone_open_editable_package_folder_button = page.open_editable_package_folder_button
        self.standalone_dotnet_editor_button = page.dotnet_editor_button
        self.standalone_status_label = page.status_label
        return page

    def set_theme(self, theme_key: str) -> None:
        self.theme_key = str(theme_key or self.theme_key)
        for widget in (
            self.action_bar,
            self.standalone_workspace,
            self.embedded_workspace,
            self.active_builder(),
        ):
            if widget is not None and hasattr(widget, "set_theme"):
                widget.set_theme(self.theme_key)
        self.update()

    def sync_ui_font(self, font: QFont, data_font: QFont | None = None) -> None:
        applied_font = QFont(font)
        dense_font = QFont(data_font or applied_font)
        for widget in (
            self,
            self.empty_state,
            self.target_label,
            self.session_label,
            self.empty_status_label,
            self.open_archive_button,
            self.modify_original_button,
            self.import_replacement_button,
            self.import_preview_button,
            self.in_game_swap_button,
        ):
            if widget.font().toString() != applied_font.toString():
                widget.setFont(applied_font)
        if hasattr(self.action_bar, "sync_ui_font"):
            self.action_bar.sync_ui_font(applied_font, dense_font)
        if hasattr(self.standalone_workspace, "sync_ui_font"):
            self.standalone_workspace.sync_ui_font(applied_font, dense_font)
        if self.embedded_workspace is not None and hasattr(self.embedded_workspace, "sync_ui_font"):
            self.embedded_workspace.sync_ui_font(applied_font, dense_font)
        builder = self.active_builder()
        if builder is not None:
            sync = getattr(builder, "sync_ui_font", None)
            if callable(sync):
                try:
                    sync(applied_font, dense_font)
                except TypeError:
                    sync(applied_font)

    def builder_host(self) -> QWidget:
        return self.embedded_builder_host

    def active_builder(self) -> Optional[QWidget]:
        item = self.embedded_builder_host_layout.itemAt(0)
        return item.widget() if item is not None else None

    def has_active_builder(self) -> bool:
        return self.active_builder() is not None

    def has_active_standalone_session(self) -> bool:
        return self.standalone_controller is not None and bool(self.standalone_controller.active_session_id)

    def iter_shutdown_workers(self) -> tuple[tuple[str, QThread | None, object | None], ...]:
        return (
            ("standalone_file_load", self.standalone_file_load_thread, self.standalone_file_load_worker),
            ("standalone_texture_source", self.standalone_texture_source_thread, self.standalone_texture_source_worker),
            ("standalone_native_package", self.standalone_native_package_thread, self.standalone_native_package_worker),
            ("standalone_mesh_action", self.standalone_action_thread, self.standalone_action_worker),
            ("standalone_validation", self.standalone_validation_thread, self.standalone_validation_worker),
            ("standalone_rebuild_report", self.standalone_rebuild_report_thread, self.standalone_rebuild_report_worker),
            ("standalone_dotnet_package", self.standalone_dotnet_package_thread, self.standalone_dotnet_package_worker),
            ("standalone_dotnet_import", self.standalone_dotnet_import_thread, self.standalone_dotnet_import_worker),
            ("standalone_editable_export", self.standalone_editable_export_thread, self.standalone_editable_export_worker),
            ("standalone_editable_import", self.standalone_editable_import_thread, self.standalone_editable_import_worker),
        )

    def request_shutdown(self) -> None:
        self.close_standalone_session()

    def mount_embedded_builder(self, builder: QWidget) -> None:
        self.close_standalone_session()
        while self.embedded_builder_host_layout.count():
            item = self.embedded_builder_host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not builder:
                widget.setParent(None)
                widget.deleteLater()
        self.embedded_builder_host_layout.addWidget(builder)
        self.workspace_stack.setCurrentWidget(self.embedded_builder_host)
        self._install_embedded_merged_mesh_editing(builder)
        self._wire_embedded_dotnet_button(builder)
        self._sync_state()

    def show_empty_state(self, message: str = "") -> None:
        self.close_standalone_session()
        self.embedded_workspace = None
        self._embedded_control_tabs = None
        self._embedded_classic_builder = None
        self.embedded_dotnet_editor_button = None
        self._set_embedded_dotnet_state("closed", active=False)
        while self.embedded_builder_host_layout.count():
            item = self.embedded_builder_host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        if message:
            self.empty_status_label.setText(message)
        self.workspace_stack.setCurrentWidget(self.empty_state)
        self.update_editor_session_state(None)

    def _install_embedded_merged_mesh_editing(self, builder: QWidget) -> None:
        control_tabs = builder.findChild(QTabWidget, "MeshAlignmentStickyWorkflowTabs")
        if control_tabs is None or bool(control_tabs.property("meshEditorMergedTabInstalled")):
            return
        classic_index = _mesh_editor_tab_index(control_tabs, "Mesh Editing")
        if classic_index < 0:
            return
        workspace = MeshEditorWorkspace(
            theme_key=self.theme_key,
            embedded_controls_only=True,
            object_name="MeshEditorEmbeddedMergedWorkspace",
            parent=control_tabs,
        )
        workspace.action_requested.connect(self._handle_action_requested)
        workspace.texture_edit_requested.connect(self._handle_embedded_open_texture)
        workspace.compare_view_requested.connect(self._handle_embedded_compare_mode)
        workspace.skeleton_pose_requested.connect(self._handle_embedded_skeleton_pose_request)
        workspace.part_selection_requested.connect(self._handle_embedded_part_selection)
        workspace.part_context_action_requested.connect(self._handle_embedded_part_context_action)
        workspace.uv_region_selected.connect(self._handle_embedded_uv_region_selection)
        workspace.uv_lasso_selected.connect(self._handle_embedded_uv_lasso_selection)
        advanced_index = control_tabs.addTab(workspace, "Advanced Mesh Data")
        if hasattr(control_tabs, "setTabVisible"):
            control_tabs.setTabVisible(classic_index, False)
            control_tabs.setTabVisible(advanced_index, False)
        control_tabs.setProperty("meshEditorMergedTabInstalled", True)
        self.embedded_workspace = workspace
        self._embedded_control_tabs = control_tabs
        self._embedded_classic_builder = builder
        setattr(builder, "_mesh_editor_embedded_merged_visible", lambda widget=workspace: control_tabs.currentWidget() is widget)
        setattr(builder, "_mesh_editor_embedded_native_part_selected", self._handle_embedded_native_part_selected)
        setattr(builder, "_mesh_editor_embedded_show_part_context_menu", self._show_embedded_part_context_menu)
        control_tabs.currentChanged.connect(lambda _index: self._refresh_embedded_workspace_from_builder())
        if control_tabs.currentIndex() == classic_index:
            for index in range(control_tabs.count()):
                is_visible = getattr(control_tabs, "isTabVisible", lambda _index: True)
                if index != classic_index and index != advanced_index and bool(is_visible(index)):
                    control_tabs.setCurrentIndex(index)
                    break
        self._refresh_embedded_workspace_from_builder()

    def _set_embedded_dotnet_state(self, state: str, *, active: bool = False) -> None:
        normalized_state = str(state or "closed").strip().lower() or "closed"
        self.standalone_dotnet_embedded_state = normalized_state
        builder = self.active_builder()
        if builder is not None:
            setattr(builder, "_mesh_editor_embedded_dotnet_state", normalized_state)
            setattr(builder, "_mesh_editor_embedded_dotnet_active", bool(active))

    def _wire_embedded_dotnet_button(self, builder: QWidget) -> None:
        dotnet_available = self._dotnet_editor_executable_path() is not None
        dotnet_enabled = dotnet_available and read_bool_setting(
            self.settings,
            "mesh_editor/use_embedded_dotnet_viewport",
            True,
        )
        setattr(builder, "_mesh_editor_embedded_start_dotnet", self._start_embedded_dotnet_editor_requested)
        setattr(builder, "_mesh_editor_embedded_stop_dotnet", self._request_embedded_dotnet_editor_close)
        setattr(builder, "_mesh_editor_dotnet_available", dotnet_available)
        setattr(builder, "_mesh_editor_use_embedded_dotnet_viewport", dotnet_enabled)
        self._set_embedded_dotnet_state("closed", active=False)
        button = builder.findChild(QPushButton, "MeshAlignmentDotNetExperimentButton")
        self.embedded_dotnet_editor_button = button
        if button is None:
            return
        if button.property("meshEditorDotNetConnectedTo") != id(self):
            button.clicked.connect(self._start_embedded_dotnet_editor_requested)
            button.setProperty("meshEditorDotNetConnectedTo", id(self))
        button.setVisible(False)
        if dotnet_enabled:
            button.setToolTip("Diagnostics-only .NET viewport restart; Edit Mesh starts .NET automatically when available.")
        else:
            button.setToolTip("Diagnostics-only .NET viewport launch; embedded .NET is unavailable or disabled by developer setting.")
        button.setEnabled(dotnet_available and not self._dotnet_task_active())

    def set_native_preview_host(self, host: object | None) -> None:
        self.standalone_native_host = host if host is not None else getattr(self, "standalone_native_host_frame", None)
        self._wire_standalone_native_part_events(self.standalone_native_host)
        if self.standalone_native_part_picking_wanted:
            self._request_standalone_native_part_picking(True, retries=2)
        self._sync_standalone_native_mesh_edit_state(force=True)

    def _wire_standalone_native_part_events(self, host: object | None) -> None:
        if host is None:
            return
        marker = id(host)
        if marker in self._wired_standalone_native_host_ids:
            return
        wired = False
        for signal_name, handler in (
            ("source_part_selected", self._handle_native_source_part_selected),
            ("source_part_context_requested", self._handle_native_source_part_context_requested),
            ("mesh_edit_stroke_started", self._handle_standalone_native_mesh_edit_stroke_started),
            ("mesh_edit_stroke_previewed", self._handle_standalone_native_mesh_edit_stroke_previewed),
            ("mesh_edit_stroke_finished", self._handle_standalone_native_mesh_edit_stroke_finished),
            ("mesh_edit_stroke_cancelled", self._handle_standalone_native_mesh_edit_stroke_cancelled),
            ("mesh_edit_selection_changed", self._handle_standalone_native_mesh_edit_selection_changed),
            ("native_event_received", self._handle_standalone_native_preview_event),
        ):
            signal = getattr(host, signal_name, None)
            connector = getattr(signal, "connect", None)
            if not callable(connector):
                continue
            try:
                connector(handler)
                wired = True
            except (RuntimeError, TypeError):
                pass
        if wired:
            self._wired_standalone_native_host_ids.add(marker)

    def _set_standalone_native_part_picking(self, enabled: bool) -> bool:
        setter = getattr(self.standalone_native_host, "set_source_part_picking", None)
        if not callable(setter):
            self.standalone_native_part_picking_enabled = False
            return False
        try:
            ok = bool(setter(bool(enabled)))
        except RuntimeError:
            self.standalone_native_part_picking_enabled = False
            return False
        self.standalone_native_part_picking_enabled = bool(ok and enabled)
        return ok

    def _request_standalone_native_part_picking(self, enabled: bool, *, retries: int = 0) -> bool:
        self.standalone_native_part_picking_wanted = bool(enabled)
        updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
        if not enabled:
            self._set_standalone_native_part_picking(False)
            if callable(updater):
                updater("Part pick: preview off", available=False)
            return False
        ok = self._set_standalone_native_part_picking(True)
        if ok:
            if callable(updater):
                updater("Part pick: ready", available=True)
            return True
        if callable(updater):
            updater("Part pick: unavailable, waiting for D3D11 host", available=False)
        if retries > 0:
            QTimer.singleShot(250, lambda remaining=int(retries) - 1: self._retry_standalone_native_part_picking(remaining))
        return False

    def _retry_standalone_native_part_picking(self, retries: int) -> None:
        if (
            self.standalone_native_part_picking_wanted
            and not self.standalone_native_part_picking_enabled
            and self.has_active_standalone_session()
        ):
            self._request_standalone_native_part_picking(True, retries=max(0, int(retries or 0)))

    def _sync_standalone_native_mesh_edit_state(self, *, force: bool = False) -> bool:
        host = self.standalone_native_host
        setter = getattr(host, "set_mesh_edit_state", None)
        if not callable(setter):
            self.standalone_native_mesh_edit_state_signature = ()
            return False
        tool_state = _STANDALONE_NATIVE_TOOL_STATE.get(str(self.current_tool_action_key or "").strip())
        controller = self.standalone_controller
        if controller is None or tool_state is None or not self._native_mesh_editor_available():
            signature = (False,)
            if not force and signature == self.standalone_native_mesh_edit_state_signature:
                return True
            self.standalone_native_mesh_edit_state_signature = signature
            try:
                return bool(setter(enabled=False))
            except (RuntimeError, TypeError):
                return False
        tool, target_mode, mode = tool_state
        try:
            view = controller.session_view()
            source_indices = tuple(int(index) for index in view.selection.source_indices)
            selection_empty = bool(view.selection.is_empty())
        except Exception:
            source_indices = ()
            selection_empty = True
        target = target_mode if not selection_empty else ("selection" if tool in {"move", "vertex"} else "brush")
        signature = (
            True,
            tool,
            target,
            mode,
            str(self.current_selection_mode or "vertex"),
            source_indices,
        )
        if not force and signature == self.standalone_native_mesh_edit_state_signature:
            return True
        self.standalone_native_mesh_edit_state_signature = signature
        try:
            return bool(
                setter(
                    enabled=True,
                    scope_mode="selection" if source_indices else "all",
                    source_submesh_indices=source_indices,
                    target_mode=target,
                    tool=tool,
                    radius_pixels=24.0,
                    strength=0.5,
                    falloff="smooth",
                    selection_mode=str(self.current_selection_mode or "vertex"),
                    smooth_iterations=3,
                )
            )
        except (RuntimeError, TypeError, ValueError):
            return False

    def _standalone_preview_mesh_snapshot(self) -> ParsedMesh:
        controller = self.standalone_controller
        if controller is None:
            raise RuntimeError("Mesh Editor has no standalone edit session.")
        mesh = controller.base_mesh(clone=True) if self.standalone_compare_mode == "source" else controller.pose_preview_mesh()
        if self.standalone_compare_mode != "source":
            self._apply_texture_preview_overrides(mesh)
        return mesh

    def _standalone_reference_mesh_snapshot(self) -> ParsedMesh | None:
        controller = self.standalone_controller
        if controller is None or self.standalone_compare_mode != "ghost":
            return None
        return controller.base_mesh(clone=True)

    def _standalone_pose_native_preview_context(
        self,
    ) -> tuple[ParsedMesh, object, Mapping[int, tuple[float, float, float]]] | None:
        controller = self.standalone_controller
        if (
            controller is None
            or self.standalone_compare_mode in {"source", "ghost"}
            or self.standalone_texture_preview_overrides
        ):
            return None
        return controller.pose_preview_native_context()

    def _apply_texture_preview_overrides(self, mesh: ParsedMesh) -> None:
        if not self.standalone_texture_preview_overrides:
            return
        submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
        for submesh_index, texture_path in tuple(self.standalone_texture_preview_overrides.items()):
            if 0 <= int(submesh_index) < len(submeshes):
                submeshes[int(submesh_index)].texture = str(texture_path)

    def write_standalone_native_preview_package(self, output_root: Path | None = None) -> Path:
        controller = self.standalone_controller
        if controller is None:
            raise RuntimeError("Mesh Editor has no standalone edit session.")
        display_mode = "original_only" if self.standalone_compare_mode == "source" else ("overlay" if self.standalone_compare_mode == "ghost" else "replacement_only")
        pose_native_context = self._standalone_pose_native_preview_context()
        if pose_native_context is not None:
            mesh, pose_skeleton, pose_rotations = pose_native_context
            reference_mesh = None
            prepared = mesh_pose_to_native_preview(
                mesh,
                skeleton=pose_skeleton,
                pose_rotations=pose_rotations,
            )
            package_dir = mesh_editor_write_prepared_native_preview_package(
                mesh,
                prepared,
                output_root=output_root,
                display_mode=display_mode,
                skeleton_overlay=controller.skeleton_overlay_data(),
                use_textures=True,
                high_quality_textures=True,
            )
        else:
            mesh = self._standalone_preview_mesh_snapshot()
            reference_mesh = self._standalone_reference_mesh_snapshot()
            package_dir = mesh_editor_write_native_preview_package(
                mesh,
                reference_mesh=reference_mesh,
                output_root=output_root,
                display_mode=display_mode,
                skeleton_overlay=controller.skeleton_overlay_data(),
                use_textures=True,
                high_quality_textures=True,
            )
        self.standalone_native_package_dir = package_dir
        self.standalone_native_status_file = package_dir / "host_status.json"
        self.standalone_native_package_has_reference = reference_mesh is not None
        self.standalone_native_package_pending_has_reference = reference_mesh is not None
        self.standalone_native_package_compare_mode = self.standalone_compare_mode
        self.standalone_native_package_pending_compare_mode = self.standalone_compare_mode
        return package_dir

    def load_standalone_native_preview_package(
        self,
        package_dir: Path | None = None,
        status_file: Path | None = None,
        *,
        reset_view: bool = True,
    ) -> bool:
        host = self.standalone_native_host
        loader = getattr(host, "load_package", None)
        if not callable(loader):
            return False
        selected_package = package_dir or self.standalone_native_package_dir
        if selected_package is None:
            return False
        package_path = Path(selected_package)
        status_path = Path(status_file or self.standalone_native_status_file or package_path / "host_status.json")
        ok = bool(loader(package_path, status_path, reset_view=bool(reset_view)))
        if ok:
            self.standalone_native_package_dir = package_path
            self.standalone_native_status_file = status_path
            self._reset_standalone_native_status_tracking()
            self.standalone_native_status_timer.start()
            if host is getattr(self, "standalone_native_host_frame", None):
                self.standalone_preview_stack.setCurrentWidget(self.standalone_native_host_frame)
            self._request_standalone_native_part_picking(True, retries=3)
            self._sync_standalone_native_mesh_edit_state(force=True)
            self.standalone_status_label.setText(f"Native D3D11 preview loading: {package_path}")
        return ok

    def _launch_standalone_native_preview_package(self, package_dir: Path, *, reset_view: bool = True) -> bool:
        package_dir = Path(package_dir)
        status_file = package_dir / "host_status.json"
        self.standalone_native_package_dir = package_dir
        self.standalone_native_status_file = status_file
        try:
            status_file.unlink(missing_ok=True)
        except OSError:
            pass
        if self._standalone_native_process_running():
            if self.load_standalone_native_preview_package(package_dir, status_file, reset_view=reset_view):
                return True
            self._stop_standalone_native_preview_process()
        host = self.standalone_native_host or getattr(self, "standalone_native_host_frame", None)
        try:
            program, arguments = mesh_editor_native_preview_command(package_dir, status_file, host_widget=host)
        except Exception as exc:
            self.standalone_status_label.setText(f"Native D3D11 preview unavailable: {exc}")
            self.status_message_requested.emit(f"Native D3D11 preview unavailable: {exc}", True)
            return False
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(arguments)
        try:
            process.setWorkingDirectory(str(Path(__file__).resolve().parents[3]))
        except Exception:
            pass
        process.setProcessChannelMode(QProcess.SeparateChannels)
        try:
            process.finished.connect(lambda *_args, target=process: self._handle_standalone_native_preview_finished(target))
            process.errorOccurred.connect(lambda _error, target=process: self._handle_standalone_native_preview_error(target))
        except (AttributeError, RuntimeError, TypeError):
            pass
        self.standalone_native_process = process
        if host is getattr(self, "standalone_native_host_frame", None):
            self.standalone_preview_stack.setCurrentWidget(self.standalone_native_host_frame)
        self.standalone_status_label.setText(f"Native D3D11 preview launching: {package_dir}")
        self._reset_standalone_native_status_tracking()
        self.standalone_native_status_timer.start()
        process.start()
        self._request_standalone_native_part_picking(True, retries=3)
        self._sync_standalone_native_mesh_edit_state(force=True)
        return True

    def start_standalone_native_preview(self, output_root: Path | None = None, *, reset_view: bool = True) -> bool:
        package_dir = self.write_standalone_native_preview_package(output_root=output_root)
        return self._launch_standalone_native_preview_package(package_dir, reset_view=reset_view)

    def start_standalone_native_preview_async(self, output_root: Path | None = None, *, reset_view: bool = True) -> bool:
        if self.standalone_native_package_thread is not None:
            self.status_message_requested.emit("Native D3D11 preview package is already preparing.", False)
            return False
        controller = self.standalone_controller
        if controller is None:
            self.standalone_status_label.setText("Native D3D11 preview unavailable: no active session.")
            self.status_message_requested.emit("Native D3D11 preview unavailable: no active session.", True)
            return False
        try:
            pose_native_context = self._standalone_pose_native_preview_context()
            if pose_native_context is not None:
                mesh_snapshot, pose_skeleton, pose_rotations = pose_native_context
                reference_snapshot = None

                def prepare_native_preview(mesh: ParsedMesh) -> object:
                    prepared = mesh_pose_to_native_preview(
                        mesh,
                        skeleton=pose_skeleton,
                        pose_rotations=pose_rotations,
                    )
                    return prepared

            else:
                # Snapshot safety still covers source/ghost/no-pose paths.
                mesh_snapshot = self._standalone_preview_mesh_snapshot()
                reference_snapshot = self._standalone_reference_mesh_snapshot()
                prepare_native_preview = lambda mesh, reference=reference_snapshot: mesh_editor_native_preview_data(mesh, reference_mesh=reference)
            skeleton_overlay = controller.skeleton_overlay_data()
        except Exception as exc:
            self.standalone_status_label.setText(f"Native D3D11 preview unavailable: {exc}")
            self.status_message_requested.emit(f"Native D3D11 preview unavailable: {exc}", True)
            return False
        self.standalone_native_package_request_id += 1
        request_id = self.standalone_native_package_request_id
        display_mode = "original_only" if self.standalone_compare_mode == "source" else ("overlay" if self.standalone_compare_mode == "ghost" else "replacement_only")
        worker = MeshNativePreviewPackageWorker(
            request_id,
            mesh_snapshot,
            ModelPreviewRenderSettings(use_textures_by_default=True, high_quality_by_default=True),
            prepare_native_preview=prepare_native_preview,
            output_root=output_root,
            model_preview_data=ModelPreviewData(path=str(mesh_snapshot.path or "mesh_editor.pac"), physics_overlay=skeleton_overlay),
            use_textures=True,
            high_quality_textures=True,
            backend="d3d11",
            display_mode=display_mode,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_standalone_native_package_ready)
        worker.error.connect(self._handle_standalone_native_package_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_native_package_worker(target_thread, target_worker))
        self.standalone_native_package_thread = thread
        self.standalone_native_package_worker = worker
        self.standalone_native_package_reset_view = bool(reset_view)
        self.standalone_native_package_pending_has_reference = reference_snapshot is not None
        self.standalone_native_package_pending_compare_mode = self.standalone_compare_mode
        self.standalone_status_label.setText("Preparing native D3D11 preview package...")
        thread.start(QThread.LowPriority)
        return True

    def _handle_standalone_native_package_ready(self, request_id: int, package_dir_object: object, elapsed_ms: float) -> None:
        try:
            package_dir = Path(package_dir_object)
        except TypeError:
            return
        if int(request_id) != int(self.standalone_native_package_request_id):
            shutil.rmtree(package_dir, ignore_errors=True)
            return
        if not self.has_active_standalone_session():
            shutil.rmtree(package_dir, ignore_errors=True)
            return
        if self._launch_standalone_native_preview_package(
            package_dir,
            reset_view=self.standalone_native_package_reset_view,
        ):
            self.standalone_native_package_has_reference = bool(self.standalone_native_package_pending_has_reference)
            self.standalone_native_package_compare_mode = self.standalone_native_package_pending_compare_mode
            self.status_message_requested.emit(f"Native D3D11 preview started after package build ({float(elapsed_ms):.1f} ms).", False)

    def _handle_standalone_native_package_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_native_package_request_id):
            return
        self.standalone_status_label.setText(f"Native D3D11 preview package failed: {message}")
        self.status_message_requested.emit(f"Native D3D11 preview package failed: {message}", True)

    def _cleanup_standalone_native_package_worker(
        self,
        thread: QThread,
        worker: MeshNativePreviewPackageWorker,
    ) -> None:
        if self.standalone_native_package_thread is thread:
            self.standalone_native_package_thread = None
        if self.standalone_native_package_worker is worker:
            self.standalone_native_package_worker = None

    def _cancel_standalone_native_package_worker(self) -> None:
        worker = self.standalone_native_package_worker
        thread = self.standalone_native_package_thread
        if worker is None and thread is None:
            return
        self.standalone_native_package_request_id += 1
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass

    def _standalone_editable_package_task_active(self) -> bool:
        return (
            self.standalone_editable_export_thread is not None
            or self.standalone_editable_export_worker is not None
            or self.standalone_editable_import_thread is not None
            or self.standalone_editable_import_worker is not None
        )

    def _open_standalone_editable_package_folder(self) -> bool:
        raw_dir = str(self.settings.value("mesh_editor/last_editable_package_dir", "") or "").strip()
        if not raw_dir:
            self.status_message_requested.emit("No editable mesh package folder has been exported yet.", True)
            return False
        package_dir = Path(raw_dir)
        if not package_dir.is_dir():
            self.status_message_requested.emit(f"Editable mesh package folder not found: {package_dir}", True)
            return False
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(package_dir.resolve()))):
            self.status_message_requested.emit(f"Could not open editable mesh package folder: {package_dir}", True)
            return False
        text = f"Opened editable mesh package folder: {package_dir}"
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, False)
        return True

    def _start_standalone_export_editable_package_requested(self) -> None:
        controller = self.standalone_controller
        if controller is None or not controller.active_session_id:
            self.status_message_requested.emit("Open a mesh session before exporting an editable package.", True)
            return
        if (
            self._standalone_action_worker_active()
            or self._standalone_validation_worker_active()
            or self._standalone_rebuild_report_worker_active()
            or self._standalone_editable_package_task_active()
        ):
            self.status_message_requested.emit("Wait for the current Mesh Editor task to finish, or cancel it first.", True)
            return
        start_dir = str(self.settings.value("mesh_editor/last_editable_package_dir", "") or "")
        raw_dir = QFileDialog.getExistingDirectory(self, "Export Editable Mesh Package", start_dir)
        if not raw_dir:
            return
        self._start_standalone_editable_package_export(Path(raw_dir))

    def _start_standalone_editable_package_export(self, output_dir: Path | str) -> bool:
        controller = self.standalone_controller
        if controller is None or not controller.active_session_id:
            self.status_message_requested.emit("Editable package export unavailable: no active session.", True)
            return False
        if self._standalone_editable_package_task_active():
            self.status_message_requested.emit("Editable package export/import is already running.", False)
            return False
        self.standalone_editable_export_request_id += 1
        request_id = self.standalone_editable_export_request_id
        worker = MeshEditablePackageExportWorker(request_id, controller.mesh_service, controller.active_session_id, output_dir)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_standalone_editable_package_exported)
        worker.error.connect(self._handle_standalone_editable_package_export_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_editable_package_export_worker(target_thread, target_worker))
        self.standalone_editable_export_thread = thread
        self.standalone_editable_export_worker = worker
        self.standalone_status_label.setText("Exporting editable mesh package...")
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        thread.start(QThread.LowPriority)
        return True

    def _handle_standalone_editable_package_exported(self, request_id: int, result: object, elapsed_ms: float) -> None:
        if int(request_id) != int(self.standalone_editable_export_request_id):
            return
        package_dir = Path(str(result.get("package_dir", ""))) if isinstance(result, Mapping) else Path()
        if package_dir:
            self.settings.setValue("mesh_editor/last_editable_package_dir", str(package_dir))
        text = f"Editable mesh package exported ({float(elapsed_ms):.1f} ms): {package_dir}"
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, False)

    def _handle_standalone_editable_package_export_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_editable_export_request_id):
            return
        text = f"Editable mesh package export failed: {message}"
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, True)

    def _cleanup_standalone_editable_package_export_worker(
        self,
        thread: QThread,
        worker: MeshEditablePackageExportWorker,
    ) -> None:
        if self.standalone_editable_export_thread is thread:
            self.standalone_editable_export_thread = None
        if self.standalone_editable_export_worker is worker:
            self.standalone_editable_export_worker = None
        self.update_editor_action_state(selection_empty=self.current_selection_empty)

    def _cancel_standalone_editable_package_export_worker(self) -> None:
        worker = self.standalone_editable_export_worker
        thread = self.standalone_editable_export_thread
        if worker is None and thread is None:
            return
        self.standalone_editable_export_request_id += 1
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass

    def _start_standalone_import_edited_package_requested(self) -> None:
        controller = self.standalone_controller
        if controller is None or not controller.active_session_id:
            self.status_message_requested.emit("Open a mesh session before importing an edited package.", True)
            return
        if (
            self._standalone_action_worker_active()
            or self._standalone_validation_worker_active()
            or self._standalone_rebuild_report_worker_active()
            or self._standalone_editable_package_task_active()
        ):
            self.status_message_requested.emit("Wait for the current Mesh Editor task to finish, or cancel it first.", True)
            return
        start_dir = str(self.settings.value("mesh_editor/last_editable_package_dir", "") or "")
        raw_dir = QFileDialog.getExistingDirectory(self, "Import Edited Mesh Package", start_dir)
        if not raw_dir:
            return
        self._start_standalone_edited_package_import(Path(raw_dir))

    def _start_standalone_edited_package_import(self, package_path: Path | str) -> bool:
        controller = self.standalone_controller
        if controller is None or not controller.active_session_id:
            self.status_message_requested.emit("Edited package import unavailable: no active session.", True)
            return False
        if self._standalone_editable_package_task_active():
            self.status_message_requested.emit("Editable package export/import is already running.", False)
            return False
        self.standalone_editable_import_request_id += 1
        request_id = self.standalone_editable_import_request_id
        worker = MeshEditablePackageImportWorker(request_id, controller.mesh_service, controller.active_session_id, package_path)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_standalone_edited_package_imported)
        worker.error.connect(self._handle_standalone_edited_package_import_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_edited_package_import_worker(target_thread, target_worker))
        self.standalone_editable_import_thread = thread
        self.standalone_editable_import_worker = worker
        self.standalone_status_label.setText("Importing edited mesh package...")
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        thread.start(QThread.LowPriority)
        return True

    def _handle_standalone_edited_package_imported(self, request_id: int, view: object, validation: object, elapsed_ms: float) -> None:
        if int(request_id) != int(self.standalone_editable_import_request_id):
            return
        if not isinstance(view, MeshEditSessionView):
            self.status_message_requested.emit("Edited package import returned an invalid session view.", True)
            return
        controller = self.standalone_controller
        if controller is None:
            return
        self.update_editor_session_state(view, active_selection_mode=controller.active_selection_mode)
        if self.standalone_compare_mode != "source":
            self._refresh_standalone_preview()
        blocker_count = len(tuple(getattr(validation, "blockers", ()) or ()))
        warning_count = len(tuple(getattr(validation, "warnings", ()) or ()))
        ok = bool(getattr(validation, "ok", False))
        text = (
            f"Edited mesh package imported and validated ({float(elapsed_ms):.1f} ms): "
            f"{'safe to rebuild' if ok else 'rebuild blocked'}"
            f" ({blocker_count} blockers, {warning_count} warnings)."
        )
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, not ok)

    def _handle_standalone_edited_package_import_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_editable_import_request_id):
            return
        text = f"Edited mesh package import failed: {message}"
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, True)

    def _cleanup_standalone_edited_package_import_worker(
        self,
        thread: QThread,
        worker: MeshEditablePackageImportWorker,
    ) -> None:
        if self.standalone_editable_import_thread is thread:
            self.standalone_editable_import_thread = None
        if self.standalone_editable_import_worker is worker:
            self.standalone_editable_import_worker = None
        self.update_editor_action_state(selection_empty=self.current_selection_empty)

    def _cancel_standalone_edited_package_import_worker(self) -> None:
        worker = self.standalone_editable_import_worker
        thread = self.standalone_editable_import_thread
        if worker is None and thread is None:
            return
        self.standalone_editable_import_request_id += 1
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass

    def _dotnet_editor_executable_path(self) -> Path | None:
        raw = str(self.settings.value("mesh_editor/dotnet_experiment_executable", "") or "").strip()
        if raw:
            return Path(raw).expanduser()
        return find_mesh_dotnet_experiment_editor()

    def _standalone_dotnet_package_worker_active(self) -> bool:
        return self.standalone_dotnet_package_thread is not None or self.standalone_dotnet_package_worker is not None

    def _dotnet_task_active(self) -> bool:
        return (
            self._standalone_dotnet_package_worker_active()
            or self._standalone_dotnet_import_worker_active()
            or self._standalone_dotnet_editor_process_running()
        )

    def _set_dotnet_status(self, message: str, *, error: bool = False) -> None:
        label = (
            getattr(self.embedded_workspace, "status_label", None)
            if self.standalone_dotnet_target_embedded and self.embedded_workspace is not None
            else self.standalone_status_label
        )
        if label is not None:
            label.setText(message)
        self.status_message_requested.emit(message, error)

    def _start_standalone_dotnet_editor_requested(self) -> None:
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Mesh .NET editor experiment unavailable: no active session.", True)
            return
        self._start_dotnet_editor_requested(controller, embedded=False)

    def _start_embedded_dotnet_editor_requested(self) -> None:
        controller = self._embedded_builder_controller()
        if controller is None:
            self.status_message_requested.emit("Mesh .NET editor experiment unavailable: no embedded edit session.", True)
            return
        self._start_dotnet_editor_requested(controller, embedded=True)

    def _start_dotnet_editor_requested(self, controller: MeshEditorController, *, embedded: bool) -> None:
        executable = self._dotnet_editor_executable_path()
        self.standalone_dotnet_target_embedded = bool(embedded)
        if executable is None or not executable.is_file():
            if embedded:
                self._set_embedded_dotnet_state("failed", active=False)
            message = (
                "Mesh .NET editor experiment is not configured. Set "
                "mesh_editor/dotnet_experiment_executable, CDMW_MESH_DOTNET_EXPERIMENT_EXE, or build the bundled helper."
            )
            self._set_dotnet_status(message, error=True)
            return
        if self._standalone_dotnet_package_worker_active():
            self._set_dotnet_status("Mesh .NET editor package is already preparing.")
            return
        if self._standalone_dotnet_editor_process_running():
            self._set_dotnet_status("Mesh .NET editor experiment is already running.")
            return
        session_id = controller.session_view().session_id
        self.standalone_dotnet_package_request_id += 1
        request_id = self.standalone_dotnet_package_request_id
        self.standalone_dotnet_target_controller = controller
        if embedded:
            self._set_embedded_dotnet_state("launching", active=False)
        worker = MeshDotNetExperimentPackageWorker(request_id, controller.mesh_service, session_id)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_standalone_dotnet_package_ready)
        worker.error.connect(self._handle_standalone_dotnet_package_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_dotnet_package_worker(target_thread, target_worker))
        self.standalone_dotnet_package_thread = thread
        self.standalone_dotnet_package_worker = worker
        self._set_dotnet_status("Preparing Mesh .NET editor experiment package...")
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        thread.start(QThread.LowPriority)

    def _handle_standalone_dotnet_package_ready(self, request_id: int, package_object: object, elapsed_ms: float) -> None:
        if int(request_id) != int(self.standalone_dotnet_package_request_id):
            return
        if not isinstance(package_object, MeshDotNetExperimentPackage):
            self._set_dotnet_status("Mesh .NET editor package worker returned an invalid package.", error=True)
            return
        if self._launch_standalone_dotnet_editor_package(package_object):
            self.status_message_requested.emit(
                f"Mesh .NET editor experiment package ready ({float(elapsed_ms):.1f} ms).",
                False,
            )

    def _handle_standalone_dotnet_package_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_dotnet_package_request_id):
            return
        text = f"Mesh .NET editor experiment package failed: {message}"
        if self.standalone_dotnet_target_embedded:
            self._set_embedded_dotnet_state("failed", active=False)
        self._set_dotnet_status(text, error=True)

    def _cleanup_standalone_dotnet_package_worker(
        self,
        thread: QThread,
        worker: MeshDotNetExperimentPackageWorker,
    ) -> None:
        if self.standalone_dotnet_package_thread is thread:
            self.standalone_dotnet_package_thread = None
        if self.standalone_dotnet_package_worker is worker:
            self.standalone_dotnet_package_worker = None
        self.update_editor_action_state(selection_empty=self.current_selection_empty)

    def _cancel_standalone_dotnet_package_worker(self) -> None:
        worker = self.standalone_dotnet_package_worker
        thread = self.standalone_dotnet_package_thread
        if worker is None and thread is None:
            return
        self.standalone_dotnet_package_request_id += 1
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass

    def _standalone_dotnet_import_worker_active(self) -> bool:
        return self.standalone_dotnet_import_thread is not None or self.standalone_dotnet_import_worker is not None

    def _start_standalone_dotnet_output_import(
        self,
        package: MeshDotNetExperimentPackage,
        status_payload: Mapping[str, object],
    ) -> bool:
        controller = self.standalone_dotnet_target_controller or self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Mesh .NET editor output import unavailable: no active session.", True)
            return False
        if self._standalone_dotnet_import_worker_active():
            self.status_message_requested.emit("Mesh .NET editor output import is already running.", False)
            return False
        self.standalone_dotnet_import_request_id += 1
        request_id = self.standalone_dotnet_import_request_id
        worker = MeshDotNetExperimentOutputImportWorker(
            request_id,
            controller.mesh_service,
            controller.session_view().session_id,
            package,
            status_payload,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_standalone_dotnet_output_imported)
        worker.error.connect(self._handle_standalone_dotnet_output_import_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_dotnet_import_worker(target_thread, target_worker))
        self.standalone_dotnet_import_thread = thread
        self.standalone_dotnet_import_worker = worker
        self._set_dotnet_status("Importing Mesh .NET editor output...")
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        thread.start(QThread.LowPriority)
        return True

    def _handle_standalone_dotnet_output_imported(
        self,
        request_id: int,
        view: object,
        validation: object,
        elapsed_ms: float,
    ) -> None:
        if int(request_id) != int(self.standalone_dotnet_import_request_id):
            return
        if not isinstance(view, MeshEditSessionView):
            self._set_dotnet_status("Mesh .NET editor output import returned an invalid session view.", error=True)
            return
        controller = self.standalone_dotnet_target_controller or self.standalone_controller
        if controller is None:
            return
        if self.standalone_dotnet_target_embedded:
            if not self._sync_embedded_dotnet_imported_mesh(controller):
                text = "Mesh .NET editor output imported, but embedded preview sync failed."
                self._set_dotnet_status(text, error=True)
                return
            if not self._finalize_embedded_dotnet_import("dotnet_output_import"):
                text = "Mesh .NET editor output imported, but textured preview rebuild sync failed."
                self._set_dotnet_status(text, error=True)
                return
            self._refresh_embedded_workspace_from_builder()
        else:
            self.update_editor_session_state(view, active_selection_mode=controller.active_selection_mode)
            if self.standalone_compare_mode != "source":
                if self._standalone_native_preview_update_active():
                    if self.standalone_native_package_thread is None:
                        self.start_standalone_native_preview_async(reset_view=False)
                else:
                    self._refresh_standalone_preview()
        blocker_count = len(tuple(getattr(validation, "blockers", ()) or ()))
        warning_count = len(tuple(getattr(validation, "warnings", ()) or ()))
        ok = bool(getattr(validation, "ok", False))
        evaluation_path = None
        package = self.standalone_dotnet_experiment_package
        if package is not None:
            try:
                evaluation_path = write_mesh_dotnet_experiment_evaluation(
                    package,
                    self.standalone_dotnet_status_payload,
                    validation_report=validation,
                )
            except Exception:
                evaluation_path = None
        text = (
            f"Mesh .NET editor output imported and validated ({float(elapsed_ms):.1f} ms): "
            f"{'safe to rebuild' if ok else 'rebuild blocked'}"
            f" ({blocker_count} blockers, {warning_count} warnings)."
        )
        if evaluation_path is not None:
            text += f" Evaluation: {evaluation_path}"
        self._set_dotnet_status(text, error=not ok)

    def _handle_standalone_dotnet_output_import_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_dotnet_import_request_id):
            return
        text = f"Mesh .NET editor output import failed: {message}"
        self._set_dotnet_status(text, error=True)

    def _cleanup_standalone_dotnet_import_worker(
        self,
        thread: QThread,
        worker: MeshDotNetExperimentOutputImportWorker,
    ) -> None:
        if self.standalone_dotnet_import_thread is thread:
            self.standalone_dotnet_import_thread = None
        if self.standalone_dotnet_import_worker is worker:
            self.standalone_dotnet_import_worker = None
        self.update_editor_action_state(selection_empty=self.current_selection_empty)

    def _sync_embedded_dotnet_imported_mesh(self, controller: MeshEditorController) -> bool:
        builder = self.active_builder()
        sync = getattr(builder, "_mesh_editor_embedded_replace_working_mesh", None) if builder is not None else None
        if not callable(sync):
            return False
        try:
            return bool(sync(controller.working_mesh(clone=True)))
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh .NET editor embedded sync failed: {exc}", True)
            return False

    def _finalize_embedded_dotnet_import(self, reason: str) -> bool:
        builder = self.active_builder()
        finalize = getattr(builder, "_mesh_editor_embedded_finalize_dotnet_import", None) if builder is not None else None
        if not callable(finalize):
            return True
        try:
            return bool(finalize(str(reason or "dotnet_import")))
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh .NET editor embedded preview finalize failed: {exc}", True)
            return False

    def _dotnet_target_controller(self) -> MeshEditorController | None:
        return self.standalone_dotnet_target_controller or self.standalone_controller

    def _connect_dotnet_protocol(self, process: QProcess) -> None:
        self.standalone_dotnet_protocol_stdout = ""
        self.standalone_dotnet_protocol_events = []
        try:
            process.readyReadStandardOutput.connect(
                lambda target=process: self._handle_dotnet_protocol_stdout_ready(target)
            )
            process.started.connect(self._send_dotnet_session_state)
        except (AttributeError, RuntimeError, TypeError):
            pass

    def _handle_dotnet_protocol_stdout_ready(self, process: QProcess) -> None:
        if self.standalone_dotnet_editor_process is not process:
            return
        try:
            raw = bytes(process.readAllStandardOutput())
        except (AttributeError, RuntimeError, TypeError):
            return
        if not raw:
            return
        self.standalone_dotnet_protocol_stdout += raw.decode("utf-8", "replace")
        while "\n" in self.standalone_dotnet_protocol_stdout:
            line, self.standalone_dotnet_protocol_stdout = self.standalone_dotnet_protocol_stdout.split("\n", 1)
            self._handle_dotnet_protocol_line(line.strip())

    def _handle_dotnet_protocol_line(self, line: str) -> bool:
        if not line:
            return False
        try:
            payload = json.loads(line)
        except ValueError:
            self._set_dotnet_status("Mesh .NET editor protocol ignored malformed JSON.", error=True)
            return False
        if not isinstance(payload, dict):
            self._set_dotnet_status("Mesh .NET editor protocol ignored non-object JSON.", error=True)
            return False
        return self._handle_dotnet_protocol_event(payload)

    def _handle_dotnet_protocol_event(self, payload: Mapping[str, object]) -> bool:
        event = str(payload.get("event", payload.get("type", "")) or "").strip().lower()
        if not event:
            self._set_dotnet_status("Mesh .NET editor protocol message had no event.", error=True)
            return False
        self.standalone_dotnet_protocol_events.append(dict(payload))
        if not self._dotnet_session_matches(payload):
            self._send_dotnet_command_result(
                str(payload.get("command", event) or event),
                ok=False,
                status="error",
                diagnostics=("Stale .NET mesh editor session id.",),
            )
            return False
        if event == "ready":
            if self.standalone_dotnet_target_embedded:
                self._set_embedded_dotnet_state("ready", active=True)
                self.update_editor_action_state(selection_empty=self.current_selection_empty)
            self._send_dotnet_session_state()
            return True
        if event == "metrics":
            metrics = payload.get("metrics", payload)
            if isinstance(metrics, Mapping):
                self.standalone_dotnet_status_payload["metrics"] = dict(metrics)
            return True
        if event == "select_request":
            return self._handle_dotnet_select_request(payload)
        if event in {"stroke_begin", "stroke_update", "stroke_end", "stroke_cancel"}:
            return self._handle_dotnet_stroke_event(payload, event.removeprefix("stroke_"))
        if event in {"command_request", "command_requested"}:
            return self._handle_dotnet_command_request(payload)
        if event == "save_request":
            return self._request_embedded_dotnet_editor_close()
        if event == "error":
            message = str(payload.get("message", "") or "Mesh .NET editor reported an error.")
            self._set_dotnet_status(message, error=True)
            return False
        return False

    def _dotnet_session_matches(self, payload: Mapping[str, object]) -> bool:
        raw_session = str(payload.get("session_id", "") or "").strip()
        if not raw_session:
            return True
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        try:
            return raw_session == str(controller.session_view().session_id)
        except Exception:
            return False

    def _send_dotnet_protocol_message(self, payload: Mapping[str, object]) -> bool:
        process = self.standalone_dotnet_editor_process
        if process is None:
            return False
        try:
            if process.state() == QProcess.NotRunning:
                return False
            data = (json.dumps(dict(payload), separators=(",", ":"), default=str) + "\n").encode("utf-8")
            process.write(data)
            return True
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False

    def _send_dotnet_session_state(self) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        try:
            view = controller.session_view()
        except Exception:
            return False
        actions = sorted(mesh_editor_actions_by_key().keys())
        selection = view.selection
        payload = {
            "event": "session_state",
            "session_id": view.session_id,
            "mode": view.mode,
            "revision": view.revision,
            "selection_mode": str(getattr(controller, "active_selection_mode", "") or self.current_selection_mode or "vertex"),
            "selection": self._dotnet_selection_payload(selection),
            "submesh_count": view.submesh_count,
            "vertex_count": view.vertex_count,
            "face_count": view.face_count,
            "undo_count": view.undo_count,
            "redo_count": view.redo_count,
            "actions": actions,
            "selection_depth_mode": "visible",
        }
        return self._send_dotnet_protocol_message(payload)

    @staticmethod
    def _dotnet_selection_payload(selection: MeshEditSelection) -> dict[str, object]:
        return {
            "vertices_by_submesh": selection.vertices_by_submesh,
            "edges_by_submesh": selection.edges_by_submesh,
            "faces_by_submesh": selection.faces_by_submesh,
            "source_indices": selection.source_indices,
            "empty": selection.is_empty(),
        }

    @classmethod
    def _dotnet_local_selection_payload_to_selection(cls, payload: Mapping[str, object]) -> MeshEditSelection:
        raw_selection = payload.get("local_selection")
        if not isinstance(raw_selection, Mapping):
            raw_selection = payload.get("selection")
        if not isinstance(raw_selection, Mapping):
            return MeshEditSelection()
        vertices = cls._dotnet_index_map(raw_selection.get("vertices_by_submesh"))
        faces = cls._dotnet_index_map(raw_selection.get("faces_by_submesh"))
        edges = cls._dotnet_edge_map(raw_selection.get("edges_by_submesh"))
        if not edges:
            edges = cls._dotnet_edge_descriptors(raw_selection.get("edge_descriptors"))
        sources = cls._dotnet_int_values(
            raw_selection.get("source_indices", raw_selection.get("sources", ()))
        )
        return MeshEditSelection.from_maps(
            vertices_by_submesh=vertices,
            edges_by_submesh=edges,
            faces_by_submesh=faces,
            source_indices=sources,
        )

    @classmethod
    def _dotnet_index_map(cls, value: object) -> dict[int, tuple[int, ...]]:
        result: dict[int, tuple[int, ...]] = {}
        for submesh, values in cls._dotnet_map_items(value):
            indices = tuple(sorted({index for index in cls._dotnet_int_values(values) if index >= 0}))
            if indices:
                result[submesh] = indices
        return result

    @classmethod
    def _dotnet_edge_map(cls, value: object) -> dict[int, tuple[tuple[int, int], ...]]:
        result: dict[int, tuple[tuple[int, int], ...]] = {}
        for submesh, raw_edges in cls._dotnet_map_items(value):
            pairs = cls._dotnet_edge_pairs(raw_edges)
            if pairs:
                result[submesh] = pairs
        return result

    @classmethod
    def _dotnet_edge_descriptors(cls, value: object) -> dict[int, tuple[tuple[int, int], ...]]:
        if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
            return {}
        try:
            items = tuple(value or ())  # type: ignore[arg-type]
        except TypeError:
            return {}
        result: dict[int, set[tuple[int, int]]] = {}
        for item in items:
            if not isinstance(item, Mapping):
                continue
            submesh = cls._standalone_native_payload_int(
                item.get("source_submesh_index", item.get("submesh_index", -1)),
                -1,
            )
            a = cls._standalone_native_payload_int(item.get("vertex_a"), -1)
            b = cls._standalone_native_payload_int(item.get("vertex_b"), -1)
            if submesh < 0 or a < 0 or b < 0 or a == b:
                continue
            pair = (a, b) if a <= b else (b, a)
            result.setdefault(submesh, set()).add(pair)
        return {submesh: tuple(sorted(pairs)) for submesh, pairs in sorted(result.items())}

    @classmethod
    def _dotnet_map_items(cls, value: object) -> tuple[tuple[int, object], ...]:
        pairs: list[tuple[int, object]] = []
        if isinstance(value, Mapping):
            iterable = value.items()
        elif not isinstance(value, (str, bytes)):
            try:
                iterable = tuple(value or ())  # type: ignore[arg-type]
            except TypeError:
                iterable = ()
        else:
            iterable = ()
        for item in iterable:
            if isinstance(value, Mapping):
                raw_key, raw_values = item
            else:
                if isinstance(item, Mapping):
                    raw_key = item.get("index", item.get("submesh", item.get("submesh_index", -1)))
                    raw_values = item.get("indices", item.get("values", item.get("edges", ())))
                else:
                    try:
                        item_values = tuple(item or ())  # type: ignore[arg-type]
                    except TypeError:
                        continue
                    if len(item_values) < 2:
                        continue
                    raw_key, raw_values = item_values[0], item_values[1]
            key = cls._standalone_native_payload_int(raw_key, -1)
            if key >= 0:
                pairs.append((key, raw_values))
        return tuple(pairs)

    @classmethod
    def _dotnet_int_values(cls, value: object) -> tuple[int, ...]:
        if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
            return ()
        try:
            raw_values = tuple(value or ())  # type: ignore[arg-type]
        except TypeError:
            return ()
        return tuple(cls._standalone_native_payload_int(raw, -1) for raw in raw_values)

    @classmethod
    def _dotnet_edge_pairs(cls, value: object) -> tuple[tuple[int, int], ...]:
        if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
            return ()
        try:
            raw_edges = tuple(value or ())  # type: ignore[arg-type]
        except TypeError:
            return ()
        edges: set[tuple[int, int]] = set()
        for raw_edge in raw_edges:
            if isinstance(raw_edge, Mapping):
                a = cls._standalone_native_payload_int(raw_edge.get("vertex_a"), -1)
                b = cls._standalone_native_payload_int(raw_edge.get("vertex_b"), -1)
            else:
                try:
                    pair_values = tuple(raw_edge or ())[:2]  # type: ignore[arg-type]
                except TypeError:
                    continue
                if len(pair_values) < 2:
                    continue
                a = cls._standalone_native_payload_int(pair_values[0], -1)
                b = cls._standalone_native_payload_int(pair_values[1], -1)
            if a >= 0 and b >= 0 and a != b:
                edges.add((a, b) if a <= b else (b, a))
        return tuple(sorted(edges))

    def _send_dotnet_command_result(
        self,
        command: str,
        *,
        ok: bool,
        status: str,
        revision: int | None = None,
        diagnostics: Sequence[object] = (),
    ) -> bool:
        payload: dict[str, object] = {
            "event": "command_result",
            "command": command,
            "ok": bool(ok),
            "status": status,
            "diagnostics": [str(item) for item in diagnostics],
        }
        if revision is not None:
            payload["revision"] = int(revision)
        return self._send_dotnet_protocol_message(payload)

    def _send_dotnet_native_update(
        self,
        update: MeshEditorNativeUpdate,
        *,
        result: MeshEditResult | None = None,
    ) -> None:
        controller = self._dotnet_target_controller()
        session_id = ""
        revision = None
        selection: MeshEditSelection | None = None
        if controller is not None:
            try:
                view = controller.session_view()
                session_id = view.session_id
                revision = view.revision
                selection = view.selection
            except Exception:
                pass
        base: dict[str, object] = {}
        if session_id:
            base["session_id"] = session_id
        if revision is not None:
            base["revision"] = int(revision)
        if update.refresh_selection:
            self._send_dotnet_protocol_message({
                **base,
                "event": "selection_update",
                "selection": self._dotnet_selection_payload(selection or MeshEditSelection()),
                "selection_groups": update.selection_groups,
            })
        if update.vertex_groups:
            self._send_dotnet_protocol_message({
                **base,
                "event": "preview_vertex_update",
                "vertex_groups": update.vertex_groups,
            })
        if update.triangle_groups or update.triangle_source_submesh_indices or update.replace_all_triangles:
            self._send_dotnet_protocol_message({
                **base,
                "event": "preview_triangle_update",
                "triangle_groups": update.triangle_groups,
                "triangle_source_submesh_indices": update.triangle_source_submesh_indices,
                "replace_all_triangles": update.replace_all_triangles,
                "material_override_groups": update.material_override_groups,
            })
        if result is not None:
            self._send_dotnet_command_result(
                result.action,
                ok=str(result.status or "").strip().lower() != "error",
                status=str(result.status or ""),
                revision=result.revision,
                diagnostics=result.diagnostics,
            )

    def _dotnet_screen_selection_payload(self, payload: Mapping[str, object]) -> dict[str, object]:
        screen_payload: dict[str, object] = {}
        raw_screen_brush = payload.get("screen_brush")
        raw_screen_region = payload.get("screen_region")
        if isinstance(raw_screen_brush, Mapping):
            screen_payload["screen_brush"] = self._native_screen_payload(raw_screen_brush)
        if isinstance(raw_screen_region, Mapping):
            screen_payload["screen_region"] = self._native_screen_payload(raw_screen_region)
        if "falloff" in payload:
            screen_payload["falloff"] = str(payload.get("falloff") or "smooth")
        if "target_mode" in payload:
            screen_payload["target_mode"] = str(payload.get("target_mode") or "vertex")
        depth_mode = str(payload.get("selection_depth_mode", "visible") or "visible").strip().lower()
        screen_payload["selection_depth_mode"] = "xray" if depth_mode == "xray" else "visible"
        return screen_payload

    def _apply_dotnet_result_update(
        self,
        controller: MeshEditorController,
        result: MeshEditResult,
        *,
        command_name: str = "",
    ) -> bool:
        try:
            update = controller.native_update_for_result(result)
        except Exception as exc:
            self._set_dotnet_status(f"Mesh .NET editor command failed: {exc}", error=True)
            self._send_dotnet_command_result(
                command_name or result.action,
                ok=False,
                status="error",
                diagnostics=(str(exc),),
            )
            return False
        if self.standalone_dotnet_target_embedded:
            self._apply_embedded_native_update(update)
            self._refresh_embedded_workspace_from_builder()
        elif (
            update.vertex_groups
            or update.triangle_groups
            or update.triangle_source_submesh_indices
            or update.selection_groups
            or update.refresh_selection
            or update.material_override_groups
            or update.replace_all_triangles
        ):
            self._apply_standalone_native_update(update)
            QTimer.singleShot(0, self._sync_state)
        self._send_dotnet_native_update(update, result=result)
        return str(result.status or "").strip().lower() != "error"

    def _handle_dotnet_select_request(self, payload: Mapping[str, object]) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        screen_payload = self._dotnet_screen_selection_payload(payload)
        if not any(key in screen_payload for key in ("screen_brush", "screen_region")):
            self._send_dotnet_command_result("select", ok=False, status="error", diagnostics=("Missing screen selection payload.",))
            return False
        operation = str(payload.get("operation", payload.get("selection_operation", "replace")) or "replace").strip().lower()
        try:
            result = controller.apply(
                "select",
                selection=MeshEditSelection(),
                operation=operation,
                _native_screen_selection_payload=screen_payload,
            )
        except Exception as exc:
            self._set_dotnet_status(f"Mesh .NET editor selection failed: {exc}", error=True)
            self._send_dotnet_command_result("select", ok=False, status="error", diagnostics=(str(exc),))
            return False
        return self._apply_dotnet_result_update(controller, result, command_name="select")

    def _handle_dotnet_stroke_event(self, payload: Mapping[str, object], phase: str) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        command = self._standalone_native_mesh_edit_stroke_command(payload, phase)
        if command is None:
            self._send_dotnet_command_result("stroke", ok=False, status="error", diagnostics=("Invalid stroke payload.",))
            return False
        blocked_command = "transform" if command.action == "transform" else "brush"
        if self._native_editor_action_blocked(blocked_command, embedded=self.standalone_dotnet_target_embedded):
            return False
        try:
            result = controller.apply(command.action, selection=command.selection, mode=command.mode, **dict(command.params))
        except Exception as exc:
            self._set_dotnet_status(f"Mesh .NET editor stroke failed: {exc}", error=True)
            self._send_dotnet_command_result(command.action, ok=False, status="error", diagnostics=(str(exc),))
            return False
        return self._apply_dotnet_result_update(controller, result, command_name=command.action)

    def _handle_dotnet_command_request(self, payload: Mapping[str, object]) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        command = str(payload.get("command", payload.get("action", "")) or "").strip().lower()
        command = command.replace("-", "_")
        if not command:
            self._send_dotnet_command_result("command", ok=False, status="error", diagnostics=("Missing command.",))
            return False
        if command in {"copy", "paste"}:
            self._send_dotnet_command_result(
                command,
                ok=False,
                status="disabled",
                diagnostics=("Mesh clipboard is disabled until metadata-preserving paste is proved; use Duplicate for same-selection copies.",),
            )
            return False
        local_selection = self._dotnet_local_selection_payload_to_selection(payload)
        action_selection = local_selection if not local_selection.is_empty() else None
        try:
            if command == "clear_selection":
                result = controller.select(operation="replace")
            elif command == "select_all":
                summary = controller.workspace_summary()
                result = controller.select(source_indices=tuple(part.index for part in summary.parts), operation="all")
            elif command in {"grow", "shrink", "invert"}:
                result = controller.apply("select", selection=local_selection, operation=command)
            else:
                action_key = command
                aliases = {
                    "delete_selection": "delete",
                    "subdivide_selection": "subdivide",
                    "refine": "refine_smooth",
                    "duplicate_selection": "duplicate",
                    "move": "transform_move",
                    "grab": "brush_grab",
                    "smooth": "brush_smooth",
                    "inflate": "brush_inflate",
                    "pinch": "brush_pinch",
                }
                action_key = aliases.get(action_key, action_key)
                params: dict[str, object] = {}
                if action_key == "transform_move":
                    if "delta" in payload:
                        params["delta"] = self._standalone_native_payload_vec3(payload.get("delta"))
                    elif "translate" in payload:
                        params["translate"] = self._standalone_native_payload_vec3(payload.get("translate"))
                    elif "step" in payload:
                        step = self._standalone_native_payload_float(payload.get("step"), 0.0)
                        axis = str(payload.get("axis", "x") or "x").strip().lower()
                        params["delta"] = (step if axis == "x" else 0.0, step if axis == "y" else 0.0, step if axis == "z" else 0.0)
                    if "axis" in payload:
                        params["axis"] = str(payload.get("axis") or "").strip().lower()
                result = controller.apply_editor_action(action_key, selection=action_selection, **params)
        except Exception as exc:
            self._set_dotnet_status(f"Mesh .NET editor command failed: {command}: {exc}", error=True)
            self._send_dotnet_command_result(command, ok=False, status="error", diagnostics=(str(exc),))
            return False
        return self._apply_dotnet_result_update(controller, result, command_name=command)

    def _dotnet_embedded_parent_hwnd(self) -> int:
        if not self.standalone_dotnet_target_embedded:
            return 0
        builder = self.active_builder()
        if isinstance(builder, QWidget):
            host = builder.findChild(QWidget, "AlignmentNativeD3D11PreviewHost")
            hwnd = _host_widget_hwnd(host)
            if hwnd > 0:
                return hwnd
            hwnd = _host_widget_hwnd(builder)
            if hwnd > 0:
                return hwnd
        hwnd = _host_widget_hwnd(self.standalone_native_host)
        return hwnd if hwnd > 0 else 0

    def _request_embedded_dotnet_editor_close(self) -> bool:
        if not self.standalone_dotnet_target_embedded or not self._standalone_dotnet_editor_process_running():
            return False
        process = self.standalone_dotnet_editor_process
        if process is None:
            return False
        self._set_embedded_dotnet_state("closing", active=False)
        self._send_dotnet_protocol_message({"event": "close_request"})
        package = self.standalone_dotnet_experiment_package
        if package is not None:
            try:
                (package.package_dir / "dotnet_close_requested.txt").write_text("close\n", encoding="utf-8")
                self._set_dotnet_status("Closing embedded Mesh .NET editor; importing output after it saves...")
                return True
            except OSError:
                pass
        try:
            process.terminate()
        except RuntimeError:
            return False
        self._set_dotnet_status("Closing embedded Mesh .NET editor; importing output after it saves...")
        return True

    def _cancel_standalone_dotnet_import_worker(self) -> None:
        worker = self.standalone_dotnet_import_worker
        thread = self.standalone_dotnet_import_thread
        if worker is None and thread is None:
            return
        self.standalone_dotnet_import_request_id += 1
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass

    def _launch_standalone_dotnet_editor_package(self, package: MeshDotNetExperimentPackage) -> bool:
        executable = self._dotnet_editor_executable_path()
        if executable is None or not executable.is_file():
            if self.standalone_dotnet_target_embedded:
                self._set_embedded_dotnet_state("failed", active=False)
            self._set_dotnet_status("Mesh .NET editor experiment executable is missing.", error=True)
            return False
        embedded_parent_hwnd = self._dotnet_embedded_parent_hwnd()
        if self.standalone_dotnet_target_embedded and embedded_parent_hwnd <= 0:
            self._set_embedded_dotnet_state("failed", active=False)
            self._set_dotnet_status("Mesh .NET embedded launch failed: no native parent window handle is available.", error=True)
            return False
        try:
            program, arguments = mesh_dotnet_experiment_command(
                executable,
                package,
                embedded_parent_hwnd=embedded_parent_hwnd,
            )
        except Exception as exc:
            if self.standalone_dotnet_target_embedded:
                self._set_embedded_dotnet_state("failed", active=False)
            self._set_dotnet_status(f"Mesh .NET editor experiment unavailable: {exc}", error=True)
            return False
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(arguments)
        process.setWorkingDirectory(str(package.package_dir))
        process.setProcessChannelMode(QProcess.SeparateChannels)
        try:
            self._connect_dotnet_protocol(process)
            process.finished.connect(lambda *_args, target=process, handoff=package: self._handle_standalone_dotnet_editor_finished(target, handoff))
            process.errorOccurred.connect(lambda _error, target=process: self._handle_standalone_dotnet_editor_error(target))
        except (AttributeError, RuntimeError, TypeError):
            pass
        self.standalone_dotnet_editor_process = process
        self.standalone_dotnet_experiment_package = package
        mode = "embedded" if embedded_parent_hwnd > 0 else "standalone"
        if self.standalone_dotnet_target_embedded:
            self._set_embedded_dotnet_state("launching", active=False)
        self._set_dotnet_status(f"Mesh .NET editor experiment launching {mode}: {package.package_dir}")
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        process.start()
        if not self._confirm_dotnet_process_started(process):
            return False
        return True

    def _confirm_dotnet_process_started(self, process: QProcess) -> bool:
        try:
            if not hasattr(process, "waitForStarted"):
                return self._standalone_dotnet_editor_process_running()
            if process.waitForStarted(1500):
                return True
        except RuntimeError as exc:
            self.standalone_dotnet_editor_process = None
            if self.standalone_dotnet_target_embedded:
                self._set_embedded_dotnet_state("failed", active=False)
            self._set_dotnet_status(f"Mesh .NET editor launch failed: {exc}", error=True)
            self.update_editor_action_state(selection_empty=self.current_selection_empty)
            return False
        detail = self._dotnet_process_diagnostics(process)
        self.standalone_dotnet_editor_process = None
        if self.standalone_dotnet_target_embedded:
            self._set_embedded_dotnet_state("failed", active=False)
        self._set_dotnet_status(f"Mesh .NET editor launch failed: {detail}", error=True)
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        try:
            process.deleteLater()
        except RuntimeError:
            pass
        return False

    def _dotnet_process_diagnostics(self, process: QProcess) -> str:
        pieces: list[str] = []
        try:
            error_text = str(process.errorString() or "").strip()
            if error_text:
                pieces.append(error_text)
        except RuntimeError:
            pass
        try:
            stderr = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
            if stderr:
                pieces.append(stderr[:800])
        except RuntimeError:
            pass
        try:
            stdout = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
            if stdout:
                pieces.append(stdout[:800])
        except RuntimeError:
            pass
        return " | ".join(pieces) if pieces else "process did not start and reported no diagnostics"

    def _standalone_dotnet_editor_process_running(self) -> bool:
        process = self.standalone_dotnet_editor_process
        if process is None:
            return False
        try:
            return process.state() != QProcess.NotRunning
        except RuntimeError:
            return False

    def _stop_standalone_dotnet_editor_process(self) -> None:
        process = self.standalone_dotnet_editor_process
        if self.standalone_dotnet_target_embedded:
            self._set_embedded_dotnet_state("closed", active=False)
        self.standalone_dotnet_editor_process = None
        if process is None:
            return
        try:
            running = process.state() != QProcess.NotRunning
        except RuntimeError:
            running = False
        if running:
            try:
                process.terminate()
                if not process.waitForFinished(1000):
                    process.kill()
                    process.waitForFinished(1000)
            except RuntimeError:
                pass
        try:
            process.deleteLater()
        except RuntimeError:
            pass

    def _handle_standalone_dotnet_editor_finished(
        self,
        process: QProcess,
        package: MeshDotNetExperimentPackage,
    ) -> None:
        if self.standalone_dotnet_editor_process is not process:
            return
        self.standalone_dotnet_editor_process = None
        if self.standalone_dotnet_target_embedded:
            self._set_embedded_dotnet_state("closed", active=False)
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        payload: dict[str, object] = {}
        if package.status_path.is_file():
            try:
                loaded = json.loads(package.status_path.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, dict):
                    payload = loaded
            except ValueError:
                payload = {"event": "error", "message": "status JSON could not be parsed"}
        self.standalone_dotnet_status_payload = dict(payload)
        try:
            evaluation_path = write_mesh_dotnet_experiment_evaluation(package, payload)
        except Exception:
            evaluation_path = None
        event = str(payload.get("event", "") or "closed").strip().lower()
        message = str(payload.get("message", "") or "").strip()
        if event == "error":
            text = f"Mesh .NET editor experiment error: {message or 'external editor reported an error.'}"
            if evaluation_path is not None:
                text += f" Evaluation: {evaluation_path}"
            self._set_dotnet_status(text, error=True)
            return
        output_obj = mesh_dotnet_experiment_output_obj_path(package, payload)
        if output_obj is not None and self._start_standalone_dotnet_output_import(package, payload):
            self.status_message_requested.emit(f"Mesh .NET editor experiment closed; importing {output_obj}.", False)
            return
        if self.standalone_dotnet_target_embedded:
            controller = self._dotnet_target_controller()
            if controller is not None and self._sync_embedded_dotnet_imported_mesh(controller):
                self._finalize_embedded_dotnet_import("dotnet_closed_without_output")
                self._refresh_embedded_workspace_from_builder()
        output_hint = str(payload.get("edited_package", "") or package.output_dir)
        text = f"Mesh .NET editor experiment closed. Output package: {output_hint}"
        if evaluation_path is not None:
            text += f" Evaluation: {evaluation_path}"
        self._set_dotnet_status(text)

    def _handle_standalone_dotnet_editor_error(self, process: QProcess) -> None:
        if self.standalone_dotnet_editor_process is not process:
            return
        detail = self._dotnet_process_diagnostics(process)
        text = f"Mesh .NET editor experiment process error: {detail}"
        if self.standalone_dotnet_target_embedded:
            self._set_embedded_dotnet_state("failed", active=False)
            controller = self._dotnet_target_controller()
            if controller is not None:
                self._sync_embedded_dotnet_imported_mesh(controller)
            self._finalize_embedded_dotnet_import("dotnet_process_error")
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        self._set_dotnet_status(text, error=True)

    def _standalone_action_worker_active(self) -> bool:
        return self.standalone_action_thread is not None or self.standalone_action_worker is not None

    def _start_standalone_action_worker(self, action: object, *, action_text: str) -> bool:
        controller = self.standalone_controller
        if controller is None:
            return False
        if self._standalone_action_worker_active():
            self.status_message_requested.emit("Wait for the current Mesh Editor action to finish, or cancel it first.", True)
            return True
        command = self._standalone_action_command(action, controller, action_text=action_text)
        if command is None:
            return False
        session_id = controller.session_view().session_id
        self.standalone_action_request_id += 1
        request_id = self.standalone_action_request_id
        worker = MeshEditCommandWorker(request_id, controller.mesh_service, session_id, command, action_text=action_text)
        thread = QThread(self)
        progress = QProgressDialog(f"Applying {action_text}...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Mesh Editor")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(250)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(self._cancel_standalone_action_worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(self._handle_standalone_action_progress)
        worker.completed.connect(self._handle_standalone_action_completed)
        worker.cancelled.connect(self._handle_standalone_action_cancelled)
        worker.error.connect(self._handle_standalone_action_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_action_worker(target_thread, target_worker))
        self.standalone_action_thread = thread
        self.standalone_action_worker = worker
        self.standalone_action_progress = progress
        self.standalone_action_text = str(action_text or "Mesh Editor action")
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        self.status_message_requested.emit(f"Applying {action_text} in the background...", False)
        thread.start(QThread.LowPriority)
        return True

    def _handle_standalone_action_progress(self, request_id: int, percent: int, message: str) -> None:
        if int(request_id) != int(self.standalone_action_request_id):
            return
        progress = self.standalone_action_progress
        if progress is not None:
            progress.setLabelText(str(message or "Applying Mesh Editor action..."))
            progress.setValue(max(0, min(100, int(percent or 0))))
        self.standalone_status_label.setText(str(message or "Applying Mesh Editor action..."))

    def _handle_standalone_action_completed(self, request_id: int, result: object) -> None:
        if int(request_id) != int(self.standalone_action_request_id):
            return
        controller = self.standalone_controller
        if controller is None:
            return
        update_started = time.perf_counter()
        native_update = controller.native_update_for_result(result)
        result = _mesh_edit_result_with_metric(
            result,
            "preview_delta_build_ms",
            (time.perf_counter() - update_started) * 1000.0,
        )
        execution = MeshEditorActionExecution(
            edit_result=result,
            native_update=native_update,
        )
        self._finish_standalone_action_execution(execution, action_text=self.standalone_action_text)

    def _handle_standalone_action_cancelled(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_action_request_id):
            return
        text = str(message or "Mesh Editor action cancelled.")
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, False)

    def _handle_standalone_action_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_action_request_id):
            return
        text = str(message or "Mesh Editor action failed.")
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, True)

    def _cleanup_standalone_action_worker(
        self,
        thread: QThread,
        worker: MeshEditCommandWorker,
    ) -> None:
        if self.standalone_action_thread is thread:
            self.standalone_action_thread = None
        if self.standalone_action_worker is worker:
            self.standalone_action_worker = None
            self.standalone_action_text = ""
        progress = self.standalone_action_progress
        if progress is not None:
            progress.close()
            progress.deleteLater()
            self.standalone_action_progress = None
        self.update_editor_action_state(selection_empty=self.current_selection_empty)

    def _cancel_standalone_action_worker(self) -> None:
        worker = self.standalone_action_worker
        thread = self.standalone_action_thread
        if worker is None and thread is None:
            return
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
            except RuntimeError:
                pass

    def _standalone_validation_worker_active(self) -> bool:
        return self.standalone_validation_thread is not None or self.standalone_validation_worker is not None

    def _start_standalone_export_validation_requested(self) -> None:
        controller = self.standalone_controller
        if controller is None or not controller.active_session_id:
            self.status_message_requested.emit("Open a mesh session before running validation.", True)
            return
        if (
            self._standalone_action_worker_active()
            or self._standalone_validation_worker_active()
            or self._standalone_rebuild_report_worker_active()
            or self._standalone_editable_package_task_active()
            or self._standalone_dotnet_package_worker_active()
            or self._standalone_dotnet_import_worker_active()
        ):
            self.status_message_requested.emit("Wait for the current Mesh Editor task to finish, or cancel it first.", True)
            return
        self.standalone_validation_request_id += 1
        request_id = self.standalone_validation_request_id
        worker = MeshExportValidationWorker(request_id, controller.mesh_service, controller.active_session_id)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_standalone_export_validation_completed)
        worker.error.connect(self._handle_standalone_export_validation_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_export_validation_worker(
                target_thread,
                target_worker,
            )
        )
        self.standalone_validation_thread = thread
        self.standalone_validation_worker = worker
        self.standalone_status_label.setText("Running validation...")
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        self.status_message_requested.emit("Running validation in the background...", False)
        thread.start(QThread.LowPriority)

    def _handle_standalone_export_validation_completed(self, request_id: int, report: object, elapsed_ms: float) -> None:
        if int(request_id) != int(self.standalone_validation_request_id):
            return
        self.standalone_last_export_validation_report = report
        self.standalone_workspace.update_export_validation(report)
        self.standalone_workspace._focus_right_panel("Checks")
        blocker_count = len(tuple(getattr(report, "blockers", ()) or ()))
        warning_count = len(tuple(getattr(report, "warnings", ()) or ()))
        ok = bool(getattr(report, "ok", False))
        text = (
            f"Validation finished ({float(elapsed_ms):.1f} ms): "
            f"{'safe to rebuild' if ok else 'rebuild blocked'} "
            f"({blocker_count} blockers, {warning_count} warnings)."
        )
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, not ok)

    def _handle_standalone_export_validation_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_validation_request_id):
            return
        text = f"Validation failed: {message}"
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, True)

    def _cleanup_standalone_export_validation_worker(
        self,
        thread: QThread,
        worker: MeshExportValidationWorker,
    ) -> None:
        if self.standalone_validation_thread is thread:
            self.standalone_validation_thread = None
        if self.standalone_validation_worker is worker:
            self.standalone_validation_worker = None
        self.update_editor_action_state(selection_empty=self.current_selection_empty)

    def _cancel_standalone_export_validation_worker(self) -> None:
        worker = self.standalone_validation_worker
        thread = self.standalone_validation_thread
        if worker is None and thread is None:
            return
        self.standalone_validation_request_id += 1
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass

    def _standalone_rebuild_report_worker_active(self) -> bool:
        return self.standalone_rebuild_report_thread is not None or self.standalone_rebuild_report_worker is not None

    def _start_standalone_rebuild_report_requested(
        self,
        *,
        output_path: Path | str = "",
        action_text: str = "rebuild report",
        developer_override: bool = False,
        developer_override_reason: str = "",
    ) -> None:
        controller = self.standalone_controller
        if controller is None or not controller.active_session_id:
            self.status_message_requested.emit(f"Open a mesh session before running {action_text}.", True)
            return
        if (
            self._standalone_action_worker_active()
            or self._standalone_validation_worker_active()
            or self._standalone_rebuild_report_worker_active()
        ):
            self.status_message_requested.emit("Wait for the current Mesh Editor task to finish, or cancel it first.", True)
            return
        output_path_text = str(output_path or "").strip()
        self.standalone_rebuild_report_request_id += 1
        request_id = self.standalone_rebuild_report_request_id
        worker = MeshRebuildReportWorker(
            request_id,
            controller.mesh_service,
            controller.active_session_id,
            action_text=action_text,
            output_path=output_path_text,
            developer_override=bool(developer_override and output_path_text),
            developer_override_reason=developer_override_reason,
        )
        thread = QThread(self)
        progress = QProgressDialog(f"Running {action_text}...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Mesh Editor")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(250)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(self._cancel_standalone_rebuild_report_worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(self._handle_standalone_rebuild_report_progress)
        worker.completed.connect(self._handle_standalone_rebuild_report_completed)
        worker.cancelled.connect(self._handle_standalone_rebuild_report_cancelled)
        worker.error.connect(self._handle_standalone_rebuild_report_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_rebuild_report_worker(
                target_thread,
                target_worker,
            )
        )
        self.standalone_rebuild_report_thread = thread
        self.standalone_rebuild_report_worker = worker
        self.standalone_rebuild_report_progress = progress
        self.standalone_last_rebuild_report = None
        self.standalone_last_rebuilt_asset_path = None
        self.standalone_workspace.update_rebuild_report(None)
        self._set_rebuild_report_button_enabled(False)
        self._set_rebuild_asset_button_enabled(False)
        self._set_save_rebuild_report_button_enabled(False)
        self.status_message_requested.emit(f"Running {action_text} in the background...", False)
        thread.start(QThread.LowPriority)

    def _start_standalone_rebuild_asset_requested(self) -> None:
        developer_override = self._standalone_developer_rebuild_override_allowed()
        if not (self._standalone_export_validation_ok() or developer_override):
            self.status_message_requested.emit("Run validation successfully before rebuilding a patched asset.", True)
            return
        default_name = f"{Path(self.standalone_mesh_label or 'mesh').stem or 'mesh'}_rebuilt.pac"
        start_dir = str(self.settings.value("mesh_editor/last_rebuild_asset_dir", "") or "").strip()
        default_path = str(Path(start_dir) / default_name) if start_dir else default_name
        target, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Rebuild Patched Mesh Asset",
            default_path,
            "Mesh assets (*.pac *.pam *.pamlod);;All files (*)",
        )
        if not target:
            return
        self.settings.setValue("mesh_editor/last_rebuild_asset_dir", str(Path(target).parent))
        kwargs: dict[str, object] = {"output_path": target, "action_text": "patched asset rebuild"}
        if developer_override:
            kwargs["developer_override"] = True
            kwargs["developer_override_reason"] = self._standalone_developer_rebuild_override_reason()
        self._start_standalone_rebuild_report_requested(**kwargs)

    def _handle_standalone_rebuild_report_progress(self, request_id: int, percent: int, message: str) -> None:
        if int(request_id) != int(self.standalone_rebuild_report_request_id):
            return
        progress = self.standalone_rebuild_report_progress
        if progress is not None:
            progress.setLabelText(str(message or "Running rebuild report..."))
            progress.setValue(max(0, min(100, int(percent or 0))))
        self.standalone_status_label.setText(str(message or "Running rebuild report..."))

    def _handle_standalone_rebuild_report_completed(self, request_id: int, report: object) -> None:
        if int(request_id) != int(self.standalone_rebuild_report_request_id):
            return
        self.standalone_last_rebuild_report = report
        self.standalone_workspace.update_rebuild_report(report)
        self.standalone_workspace._focus_right_panel("Rebuild")
        output_path = str(getattr(report, "output_path", "") or "").strip()
        self.standalone_last_rebuilt_asset_path = Path(output_path) if output_path else None
        text = f"Patched asset rebuilt: {output_path}" if output_path else "Rebuild report ready."
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, False)

    def _handle_standalone_rebuild_report_cancelled(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_rebuild_report_request_id):
            return
        text = str(message or "Rebuild report cancelled.")
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, False)

    def _handle_standalone_rebuild_report_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_rebuild_report_request_id):
            return
        text = str(message or "Rebuild report failed.")
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, True)

    def _standalone_rebuilt_asset_handoff_payload(self, *, action: str) -> tuple[ArchiveEntry, Path] | None:
        target = self._current_target_entry()
        if not isinstance(target, ArchiveEntry):
            self.status_message_requested.emit(
                f"Open Mesh Editor from an archive target before {action} a rebuilt asset.",
                True,
            )
            return None
        output_path = self.standalone_last_rebuilt_asset_path
        if output_path is None:
            raw_output = str(getattr(self.standalone_last_rebuild_report, "output_path", "") or "").strip()
            output_path = Path(raw_output) if raw_output else None
        if output_path is None or not output_path.is_file():
            self.status_message_requested.emit(f"Rebuild a patched asset before {action} it.", True)
            return None
        return target, output_path

    def _preview_standalone_rebuilt_asset_requested(self) -> None:
        payload = self._standalone_rebuilt_asset_handoff_payload(action="previewing")
        if payload is None:
            return
        target, output_path = payload
        self.preview_rebuilt_asset_requested.emit(target, output_path)

    def _package_standalone_rebuilt_asset_requested(self) -> None:
        payload = self._standalone_rebuilt_asset_handoff_payload(action="packaging")
        if payload is None:
            return
        target, output_path = payload
        self.package_rebuilt_asset_requested.emit(target, output_path)

    def _cleanup_standalone_rebuild_report_worker(
        self,
        thread: QThread,
        worker: MeshRebuildReportWorker,
    ) -> None:
        if self.standalone_rebuild_report_thread is thread:
            self.standalone_rebuild_report_thread = None
        if self.standalone_rebuild_report_worker is worker:
            self.standalone_rebuild_report_worker = None
        progress = self.standalone_rebuild_report_progress
        if progress is not None:
            progress.close()
            progress.deleteLater()
            self.standalone_rebuild_report_progress = None
        self._set_rebuild_report_button_enabled(self.has_active_standalone_session())
        self._set_rebuild_asset_button_enabled(self.has_active_standalone_session() and self._standalone_export_validation_ok())
        self._set_preview_rebuilt_asset_button_enabled(
            self.has_active_standalone_session() and self.standalone_last_rebuilt_asset_path is not None
        )
        self._set_package_rebuilt_asset_button_enabled(
            self.has_active_standalone_session() and self.standalone_last_rebuilt_asset_path is not None
        )

    def _cancel_standalone_rebuild_report_worker(self) -> None:
        worker = self.standalone_rebuild_report_worker
        thread = self.standalone_rebuild_report_thread
        if worker is None and thread is None:
            return
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
            except RuntimeError:
                pass

    def _set_rebuild_report_button_enabled(self, enabled: bool) -> None:
        button = getattr(self.standalone_workspace, "run_rebuild_report_button", None)
        if button is not None:
            button.setEnabled(bool(enabled))

    def _set_rebuild_asset_button_enabled(self, enabled: bool) -> None:
        button = getattr(self.standalone_workspace, "rebuild_asset_button", None)
        if button is not None:
            button.setEnabled(bool(enabled))

    def _set_preview_rebuilt_asset_button_enabled(self, enabled: bool) -> None:
        button = getattr(self.standalone_workspace, "preview_rebuilt_asset_button", None)
        if button is not None:
            button.setEnabled(bool(enabled))

    def _set_package_rebuilt_asset_button_enabled(self, enabled: bool) -> None:
        button = getattr(self.standalone_workspace, "package_rebuilt_asset_button", None)
        if button is not None:
            button.setEnabled(bool(enabled))

    def _standalone_export_validation_ok(self) -> bool:
        return bool(getattr(self.standalone_last_export_validation_report, "ok", False))

    def _standalone_rebuild_allowed(self) -> bool:
        return self._standalone_export_validation_ok() or self._standalone_developer_rebuild_override_allowed()

    def _standalone_developer_rebuild_override_enabled(self) -> bool:
        return read_bool_setting(self.settings, "mesh_editor/developer_mode", False) and read_bool_setting(
            self.settings,
            "mesh_editor/developer_rebuild_override",
            False,
        )

    def _standalone_developer_rebuild_override_reason(self) -> str:
        reason = str(self.settings.value("mesh_editor/developer_rebuild_override_reason", "") or "").strip()
        return reason or "Developer-mode unsafe rebuild override."

    def _standalone_developer_rebuild_override_allowed(self) -> bool:
        if not self._standalone_developer_rebuild_override_enabled():
            return False
        blockers = tuple(getattr(self.standalone_last_export_validation_report, "blockers", ()) or ())
        return bool(blockers) and all(
            str(getattr(issue, "code", "") or "").strip() in DEVELOPER_OVERRIDABLE_REBUILD_BLOCKERS
            for issue in blockers
        )

    def _set_save_rebuild_report_button_enabled(self, enabled: bool) -> None:
        button = getattr(self.standalone_workspace, "save_rebuild_report_button", None)
        if button is not None:
            button.setEnabled(bool(enabled))

    def _save_standalone_rebuild_report_requested(self) -> None:
        report = self.standalone_last_rebuild_report
        if report is None:
            self.status_message_requested.emit("Run a rebuild report before saving it.", True)
            return
        default_name = f"{Path(self.standalone_mesh_label or 'mesh').stem or 'mesh'}_rebuild_report.json"
        target, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Rebuild Report",
            default_name,
            "JSON files (*.json);;All files (*)",
        )
        if not target:
            return
        try:
            saved_path = self._save_standalone_rebuild_report(target)
        except Exception as exc:
            self.status_message_requested.emit(f"Rebuild report save failed: {exc}", True)
            return
        self.status_message_requested.emit(f"Rebuild report saved: {saved_path}", False)

    def _save_standalone_rebuild_report(self, path: Path | str) -> Path:
        report = self.standalone_last_rebuild_report
        if report is None:
            raise RuntimeError("no rebuild report is available")
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(_rebuild_report_json_payload(report), indent=2) + "\n", encoding="utf-8")
        return target

    def _start_standalone_native_preview_requested(self) -> None:
        if not self.has_active_standalone_session():
            self.status_message_requested.emit("Open a mesh session before starting native D3D11 preview.", True)
            return
        if self.start_standalone_native_preview_async():
            self.status_message_requested.emit("Native D3D11 preview package preparation started.", False)

    def open_mesh_session(
        self,
        mesh: ParsedMesh,
        *,
        target_entry: object | None = None,
        session_id: str = "",
        mode: str = "object",
        source_skeleton: object | None = None,
    ) -> MeshEditSessionView:
        if not isinstance(mesh, ParsedMesh):
            raise TypeError("mesh must be ParsedMesh")
        self.close_standalone_session()
        self.standalone_compare_mode = "edited"
        self.standalone_controller = MeshEditorController()
        self.standalone_source_skeleton = source_skeleton
        view = self.standalone_controller.open_mesh(
            mesh,
            session_id=str(session_id or "mesh-editor-standalone"),
            mode=str(mode or "object"),
        )
        self._show_standalone_session(view, mesh=mesh, target_entry=target_entry)
        return view

    def open_mesh_file_session(
        self,
        path: Path | str,
        *,
        target_entry: object | None = None,
        session_id: str = "",
        mode: str = "object",
        source_skeleton: object | None = None,
    ) -> MeshEditSessionView:
        source_path = Path(path)
        self.close_standalone_session()
        self.standalone_compare_mode = "edited"
        mesh_service = MeshService()
        mesh = mesh_service.load_mesh_file(source_path, run_roundtrip=True)
        self.standalone_controller = MeshEditorController(mesh_service=mesh_service)
        loaded_source_skeleton = source_skeleton
        try:
            view = self.standalone_controller.open_mesh(
                mesh,
                session_id=str(session_id or f"mesh-editor-file:{source_path.name}"),
                mode=str(mode or "object"),
            )
        except Exception:
            self.standalone_controller = None
            raise
        self.standalone_source_skeleton = loaded_source_skeleton
        if loaded_source_skeleton is not None:
            self.standalone_controller.attach_skeleton(
                loaded_source_skeleton,
                source_path=str(getattr(loaded_source_skeleton, "path", "") or source_path),
            )
        self._show_standalone_session(view, mesh=mesh, target_entry=target_entry)
        return view

    def open_mesh_file_session_async(
        self,
        path: Path | str,
        *,
        target_entry: object | None = None,
        session_id: str = "",
        mode: str = "object",
        source_skeleton: object | None = None,
    ) -> int:
        source_path = Path(path)
        self.close_standalone_session()
        self.standalone_file_load_request_id += 1
        request_id = self.standalone_file_load_request_id
        worker = MeshFileSessionLoadWorker(
            request_id,
            source_path,
            session_id=str(session_id or f"mesh-editor-file:{source_path.name}"),
            mode=str(mode or "object"),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.loaded.connect(self._handle_standalone_file_loaded)
        worker.error.connect(self._handle_standalone_file_load_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_file_loader(target_thread, target_worker))
        self.standalone_file_load_worker = worker
        self.standalone_file_load_thread = thread
        self.standalone_file_load_target_entry = target_entry
        self.standalone_file_load_source_skeleton = source_skeleton
        self.current_archive_selection = target_entry  # type: ignore[assignment]
        self.current_request = None
        self.standalone_mesh_label = str(source_path)
        self.workspace_stack.setCurrentWidget(self.standalone_workspace)
        self.standalone_status_label.setText(f"Loading Mesh Editor file: {source_path}")
        self.update_editor_session_state(None)
        thread.start(QThread.LowPriority)
        self.status_message_requested.emit(f"Mesh Editor loading standalone mesh: {source_path.name}", False)
        return request_id

    def _handle_standalone_file_loaded(self, request_id: int, mesh_service: MeshService, view: MeshEditSessionView, mesh: ParsedMesh) -> None:
        if int(request_id) != self.standalone_file_load_request_id:
            return
        self.standalone_controller = MeshEditorController(mesh_service=mesh_service)
        view = self.standalone_controller.attach_session(view.session_id)
        self.standalone_source_skeleton = self.standalone_file_load_source_skeleton
        if self.standalone_source_skeleton is not None:
            self.standalone_controller.attach_skeleton(
                self.standalone_source_skeleton,
                source_path=str(getattr(self.standalone_source_skeleton, "path", "") or ""),
            )
        self._show_standalone_session(view, mesh=mesh, target_entry=self.standalone_file_load_target_entry)

    def _handle_standalone_file_load_error(self, request_id: int, message: str) -> None:
        if int(request_id) != self.standalone_file_load_request_id:
            return
        self.standalone_controller = None
        self.standalone_status_label.setText(f"Mesh Editor file load failed: {message}")
        self.status_message_requested.emit(f"Mesh Editor file load failed: {message}", True)
        self.update_editor_session_state(None)

    def _cleanup_standalone_file_loader(self, thread: QThread, worker: MeshFileSessionLoadWorker) -> None:
        if self.standalone_file_load_thread is thread:
            self.standalone_file_load_thread = None
        if self.standalone_file_load_worker is worker:
            self.standalone_file_load_worker = None
            self.standalone_file_load_target_entry = None
            self.standalone_file_load_source_skeleton = None

    def _cancel_standalone_file_load(self) -> None:
        worker = self.standalone_file_load_worker
        thread = self.standalone_file_load_thread
        if worker is None and thread is None:
            return
        self.standalone_file_load_request_id += 1
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass

    def _show_standalone_session(
        self,
        view: MeshEditSessionView,
        *,
        mesh: ParsedMesh,
        target_entry: object | None = None,
    ) -> None:
        self.current_archive_selection = target_entry  # type: ignore[assignment]
        self.current_request = None
        self.standalone_mesh_label = str(mesh.path or "mesh").strip() or "mesh"
        self._sync_standalone_compare_combo()
        self.workspace_stack.setCurrentWidget(self.standalone_workspace)
        self._refresh_standalone_preview()
        self.update_editor_session_state(view, active_selection_mode=self.standalone_controller.active_selection_mode)
        self.status_message_requested.emit(f"Mesh Editor loaded standalone mesh: {Path(self.standalone_mesh_label).name}", False)

    def close_standalone_session(self) -> None:
        self.standalone_animation_timer.stop()
        self.standalone_animation_last_tick = 0.0
        self._cancel_standalone_file_load()
        self._cancel_standalone_texture_source_resolution()
        self._cancel_standalone_native_package_worker()
        self._cancel_standalone_action_worker()
        self._cancel_standalone_export_validation_worker()
        self._cancel_standalone_rebuild_report_worker()
        self._cancel_standalone_editable_package_export_worker()
        self._cancel_standalone_edited_package_import_worker()
        self._cancel_standalone_dotnet_package_worker()
        self._cancel_standalone_dotnet_import_worker()
        self._stop_standalone_native_preview_process()
        self._stop_standalone_dotnet_editor_process()
        if self.standalone_controller is not None:
            try:
                self.standalone_controller.close_active_session()
            except (KeyError, RuntimeError):
                pass
        self.standalone_controller = None
        self.standalone_mesh_label = ""
        self.standalone_source_skeleton = None
        self.standalone_last_rebuild_report = None
        self.standalone_last_rebuilt_asset_path = None
        self.standalone_file_load_source_skeleton = None
        self.standalone_compare_mode = "edited"
        self.standalone_texture_preview_overrides.clear()
        self.standalone_native_package_dir = None
        self.standalone_native_status_file = None
        self.standalone_native_package_has_reference = False
        self.standalone_native_package_pending_has_reference = False
        self.standalone_native_package_compare_mode = "edited"
        self.standalone_native_package_pending_compare_mode = "edited"
        self.standalone_dotnet_experiment_package = None
        self.standalone_dotnet_status_payload = {}
        self.standalone_dotnet_target_controller = None
        self.standalone_dotnet_target_embedded = False
        self._reset_standalone_native_status_tracking()
        self.standalone_native_status_timer.stop()
        self._request_standalone_native_part_picking(False)

    def _reset_standalone_native_status_tracking(self) -> None:
        self.standalone_native_status_signature = (0, 0)
        self.standalone_native_status_payload_text = ""
        self.standalone_native_last_status_payload = {}
        self._set_standalone_native_performance_status(None)

    def _poll_standalone_native_preview_status(self) -> None:
        status_file = self.standalone_native_status_file
        if status_file is None:
            return
        try:
            stat = Path(status_file).stat()
        except OSError:
            return
        signature = (int(getattr(stat, "st_mtime_ns", 0) or 0), int(getattr(stat, "st_size", 0) or 0))
        try:
            payload_text = Path(status_file).read_text(encoding="utf-8")
        except OSError as exc:
            self.standalone_status_label.setText(f"Native D3D11 status read failed: {exc}")
            return
        if signature == self.standalone_native_status_signature and payload_text == self.standalone_native_status_payload_text:
            return
        self.standalone_native_status_signature = signature
        self.standalone_native_status_payload_text = payload_text
        try:
            payload = json.loads(payload_text)
        except ValueError as exc:
            self.standalone_status_label.setText(f"Native D3D11 status parse failed: {exc}")
            return
        if not isinstance(payload, dict):
            return
        self.standalone_native_last_status_payload = dict(payload)
        self._set_standalone_native_performance_status(payload)
        event = str(payload.get("event", "") or "").strip().lower()
        if event == "loaded":
            batch_count = int(payload.get("batch_count", 0) or 0)
            vertex_count = int(payload.get("vertex_count", 0) or 0)
            self._request_standalone_native_part_picking(True, retries=2)
            self.standalone_status_label.setText(
                f"Native D3D11 preview loaded: {batch_count:,} batches, {vertex_count:,} vertices."
            )
            self.status_message_requested.emit("Native D3D11 preview loaded.", False)
        elif event == "loading":
            message = str(payload.get("message", "") or "Loading native D3D11 preview...")
            updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
            if callable(updater):
                updater("Part pick: loading D3D11 host", available=False)
            self.standalone_status_label.setText(message)
            self.status_message_requested.emit(f"Native D3D11 preview: {message}", False)
        elif event == "error":
            message = str(payload.get("message", "") or "Renderer error.")
            self._request_standalone_native_part_picking(False)
            updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
            if callable(updater):
                updater("Part pick: unavailable, D3D11 renderer error", available=False)
            self.standalone_status_label.setText(f"Native D3D11 preview error: {message}")
            self.status_message_requested.emit(f"Native D3D11 preview error: {message}", True)
        elif event == "closed":
            self._request_standalone_native_part_picking(False)
            self.standalone_status_label.setText("Native D3D11 preview closed.")
            self.status_message_requested.emit("Native D3D11 preview closed.", False)

    def _set_standalone_native_performance_status(self, payload: Mapping[str, object] | None) -> None:
        updater = getattr(self.standalone_workspace, "set_native_performance_status", None)
        if callable(updater):
            updater(payload)

    def _handle_standalone_native_preview_event(self, payload: object) -> bool:
        if isinstance(payload, Mapping) and self._has_standalone_native_performance_payload(payload):
            self._set_standalone_native_performance_status(payload)
        return True

    @staticmethod
    def _has_standalone_native_performance_payload(payload: Mapping[str, object]) -> bool:
        sources: list[Mapping[str, object]] = [payload]
        metrics = payload.get("metrics")
        if isinstance(metrics, Mapping):
            sources.insert(0, metrics)
        for source in sources:
            if any(
                source.get(key) not in (None, "")
                for key in (
                    "current_fps",
                    "average_fps",
                    "fps",
                    "frame_time_ms",
                    "frame_ms",
                    "last_frame_ms",
                    "first_frame_ms",
                    "gpu_upload_ms",
                    "gpu_upload_time_ms",
                    "geometry_upload_ms",
                )
            ):
                return True
        return False

    def _standalone_native_process_running(self) -> bool:
        process = self.standalone_native_process
        if process is None:
            return False
        try:
            return process.state() != QProcess.NotRunning
        except RuntimeError:
            return False

    def _stop_standalone_native_preview_process(self) -> None:
        process = self.standalone_native_process
        self.standalone_native_process = None
        if process is None:
            return
        try:
            running = process.state() != QProcess.NotRunning
        except RuntimeError:
            running = False
        if running:
            try:
                process.terminate()
                if not process.waitForFinished(1000):
                    process.kill()
                    process.waitForFinished(1000)
            except RuntimeError:
                pass
        try:
            process.deleteLater()
        except RuntimeError:
            pass

    def _archive_texture_indexes(self) -> tuple[Mapping[str, Sequence[ArchiveEntry]], Mapping[str, Sequence[ArchiveEntry]]]:
        path_provider = self.get_archive_texture_entries_by_normalized_path
        basename_provider = self.get_archive_texture_entries_by_basename
        try:
            path_index = path_provider() if callable(path_provider) else {}
        except Exception:
            path_index = {}
        try:
            basename_index = basename_provider() if callable(basename_provider) else {}
        except Exception:
            basename_index = {}
        return path_index or {}, basename_index or {}

    def _start_archive_texture_source_resolution(
        self,
        target: object,
        *,
        controller: MeshEditorController | None = None,
    ) -> bool:
        if self.standalone_texture_source_thread is not None:
            self.status_message_requested.emit("Mesh Editor texture source is already resolving.", False)
            return True
        target_entry = self.current_archive_selection
        if not isinstance(target_entry, ArchiveEntry):
            return False
        path_index, basename_index = self._archive_texture_indexes()
        if not path_index and not basename_index:
            return False
        self.standalone_texture_source_request_id += 1
        request_id = self.standalone_texture_source_request_id
        worker = MeshTextureSourceResolveWorker(
            request_id,
            str(getattr(target, "texture", "") or ""),
            target_entry=target_entry,
            entries_by_normalized_path=path_index,
            entries_by_basename=basename_index,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.resolved.connect(self._handle_archive_texture_source_resolved)
        worker.error.connect(self._handle_archive_texture_source_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_archive_texture_source_worker(target_thread, target_worker))
        self.standalone_texture_source_thread = thread
        self.standalone_texture_source_worker = worker
        self.standalone_texture_source_target = target
        self.standalone_texture_source_controller = controller
        thread.start(QThread.LowPriority)
        self.status_message_requested.emit(f"Resolving Mesh Editor archive texture: {getattr(target, 'display_name', '') or getattr(target, 'texture', '')}", False)
        return True

    def _handle_archive_texture_source_resolved(self, request_id: int, result: object) -> None:
        if int(request_id) != int(self.standalone_texture_source_request_id):
            return
        target = self.standalone_texture_source_target
        source_path = getattr(result, "source_path", None)
        if target is None or source_path is None:
            self.status_message_requested.emit("Mesh Editor archive texture source resolved without a usable path.", True)
            return
        self._open_texture_target_source(
            target,
            Path(source_path),
            archive_path=str(getattr(result, "archive_path", "") or ""),
            controller=self.standalone_texture_source_controller,
        )
        message = str(getattr(result, "message", "") or "")
        self.status_message_requested.emit(message or f"Mesh Editor archive texture source ready: {Path(source_path).name}", False)

    def _handle_archive_texture_source_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_texture_source_request_id):
            return
        self.status_message_requested.emit(str(message or "Mesh Editor archive texture source could not be resolved."), True)

    def _cleanup_archive_texture_source_worker(
        self,
        thread: QThread,
        worker: MeshTextureSourceResolveWorker,
    ) -> None:
        if self.standalone_texture_source_thread is thread:
            self.standalone_texture_source_thread = None
        if self.standalone_texture_source_worker is worker:
            self.standalone_texture_source_worker = None
            self.standalone_texture_source_target = None
            self.standalone_texture_source_controller = None

    def _cancel_standalone_texture_source_resolution(self) -> None:
        worker = self.standalone_texture_source_worker
        thread = self.standalone_texture_source_thread
        if worker is None and thread is None:
            return
        self.standalone_texture_source_request_id += 1
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass

    def _handle_standalone_native_preview_finished(self, process: QProcess) -> None:
        if self.standalone_native_process is not process:
            return
        self._poll_standalone_native_preview_status()
        self.standalone_native_process = None
        self.standalone_native_status_timer.stop()
        self._request_standalone_native_part_picking(False)
        if self.has_active_standalone_session():
            last_event = str(self.standalone_native_last_status_payload.get("event", "") or "").strip().lower()
            if last_event not in {"error", "closed"}:
                message = "Native D3D11 preview stopped unexpectedly; preview is stale. Reload native preview to resync."
                self.standalone_status_label.setText(message)
                self.status_message_requested.emit(message, True)
                return
            self.standalone_preview_stack.setCurrentWidget(self.standalone_preview)

    def _handle_standalone_native_preview_error(self, process: QProcess) -> None:
        if self.standalone_native_process is not process:
            return
        self.standalone_status_label.setText("Native D3D11 preview process error.")
        self._set_standalone_native_performance_status(None)
        self._request_standalone_native_part_picking(False)
        updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
        if callable(updater):
            updater("Part pick: unavailable, D3D11 process error", available=False)

    def _entry_path(self, entry: object) -> str:
        return str(getattr(entry, "path", "") or getattr(entry, "name", "") or "").strip()

    def _entry_label(self, entry: object) -> str:
        return str(getattr(entry, "basename", "") or Path(self._entry_path(entry)).name or self._entry_path(entry) or "mesh").strip()

    def set_archive_selection(self, entry: Optional[ArchiveEntry]) -> None:
        self.current_archive_selection = entry
        if self.has_active_builder():
            self._sync_state()
            return
        if self.has_active_standalone_session():
            self._sync_state()
            return
        if (
            entry is not None
            and (
                self.current_request is None
                or (
                    self.current_request.source_path is None
                    and self.current_request.source_entry is None
                )
            )
        ):
            self.current_request = MeshEditorSessionRequest(target_entry=entry, mode="modify_original")
        self._sync_state()

    def open_session(self, request: MeshEditorSessionRequest) -> None:
        self.current_request = request
        self.current_archive_selection = request.target_entry
        self._sync_state()
        self.status_message_requested.emit(f"Mesh Editor loaded target: {self._entry_label(request.target_entry)}", False)

    def update_editor_action_state(
        self,
        *,
        mode: str = "",
        active_selection_mode: str = "",
        active_tool_key: str | None = None,
        selection_empty: bool | None = None,
        undo_count: int | None = None,
        redo_count: int | None = None,
    ) -> None:
        if mode:
            self.current_edit_mode = str(mode)
        if active_selection_mode:
            self.current_selection_mode = str(active_selection_mode)
        if active_tool_key is not None:
            self.current_tool_action_key = str(active_tool_key)
        if selection_empty is not None:
            self.current_selection_empty = bool(selection_empty)
        if undo_count is not None:
            self.current_undo_count = max(0, int(undo_count or 0))
        if redo_count is not None:
            self.current_redo_count = max(0, int(redo_count or 0))
        self._sync_state()
        self._sync_standalone_native_mesh_edit_state()

    def update_editor_session_state(
        self,
        view: MeshEditSessionView | None,
        *,
        active_selection_mode: str = "",
    ) -> None:
        summary = getattr(self.standalone_workspace, "update_session_summary", None)
        if callable(summary):
            summary(view, mesh_label=self.standalone_mesh_label)
        self._refresh_standalone_workspace_summary(view)
        self._refresh_standalone_uv_summary(view)
        self._refresh_standalone_skeleton_summary(view)
        self._refresh_standalone_compare_summary(view)
        self._refresh_standalone_export_validation(view)
        rebuild_updater = getattr(self.standalone_workspace, "update_rebuild_report", None)
        if callable(rebuild_updater):
            self.standalone_last_rebuild_report = None
            rebuild_updater(None)
        if view is None:
            self.update_editor_action_state(
                mode="object",
                active_selection_mode="vertex",
                selection_empty=True,
                undo_count=0,
                redo_count=0,
            )
            return
        self.update_editor_action_state(
            mode=str(view.mode or "object"),
            active_selection_mode=str(active_selection_mode or self.current_selection_mode or "vertex"),
            selection_empty=bool(view.selection.is_empty()),
            undo_count=int(view.undo_count or 0),
            redo_count=int(view.redo_count or 0),
        )

    def set_active_tool_state(self, *, mode: str = "", active_selection_mode: str = "", active_tool_key: str | None = None) -> None:
        self.update_editor_action_state(
            mode=mode,
            active_selection_mode=active_selection_mode,
            active_tool_key=active_tool_key,
        )

    def _refresh_standalone_export_validation(self, view: MeshEditSessionView | None) -> None:
        updater = getattr(self.standalone_workspace, "update_export_validation", None)
        if not callable(updater):
            return
        controller = self.standalone_controller
        if view is None or controller is None or controller.active_session_id != view.session_id:
            self.standalone_last_export_validation_report = None
            updater(None)
            return
        try:
            report = controller.export_validation_report()
            self.standalone_last_export_validation_report = report
            updater(report)
        except Exception:
            self.standalone_last_export_validation_report = None
            updater(None)

    def _copy_standalone_validation_report_requested(self) -> None:
        report = self.standalone_last_export_validation_report
        if report is None:
            self.status_message_requested.emit("Run validation before copying a validation report.", True)
            return
        payload = _validation_report_json_payload(report)
        QApplication.clipboard().setText(json.dumps(payload, indent=2, sort_keys=True))
        text = "Validation report copied to clipboard."
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, False)

    def _refresh_standalone_workspace_summary(self, view: MeshEditSessionView | None) -> None:
        updater = getattr(self.standalone_workspace, "update_workspace_summary", None)
        if not callable(updater):
            return
        controller = self.standalone_controller
        if view is None or controller is None or controller.active_session_id != view.session_id:
            updater(None)
            return
        try:
            updater(controller.workspace_summary())
        except Exception:
            updater(None)

    def _refresh_standalone_uv_summary(self, view: MeshEditSessionView | None) -> None:
        updater = getattr(self.standalone_workspace, "update_uv_summary", None)
        if not callable(updater):
            return
        controller = self.standalone_controller
        if view is None or controller is None or controller.active_session_id != view.session_id:
            updater(None)
            return
        try:
            updater(controller.uv_summary())
        except Exception:
            updater(None)

    def _refresh_standalone_skeleton_summary(self, view: MeshEditSessionView | None) -> None:
        updater = getattr(self.standalone_workspace, "update_skeleton_summary", None)
        if not callable(updater):
            return
        controller = self.standalone_controller
        if view is None or controller is None or controller.active_session_id != view.session_id:
            updater(None)
            return
        try:
            updater(controller.skeleton_summary())
        except Exception:
            updater(None)

    def _refresh_standalone_compare_summary(self, view: MeshEditSessionView | None) -> None:
        updater = getattr(self.standalone_workspace, "update_compare_summary", None)
        if not callable(updater):
            return
        controller = self.standalone_controller
        if view is None or controller is None or controller.active_session_id != view.session_id:
            updater(None)
            return
        try:
            updater(controller.compare_summary())
        except Exception:
            updater(None)

    def _current_target_entry(self) -> Optional[ArchiveEntry]:
        if self.current_request is not None:
            return self.current_request.target_entry
        return self.current_archive_selection

    def _native_mesh_editor_available(self) -> bool:
        try:
            return bool(native_mesh_core_available())
        except Exception:
            return False

    def _native_editor_action_blocked(self, command: str, *, embedded: bool = False) -> bool:
        normalized = str(command or "").strip().lower()
        if normalized not in NATIVE_EDITOR_SESSION_COMMANDS or self._native_mesh_editor_available():
            return False
        prefix = "Embedded Mesh Editor" if embedded else "Mesh Editor"
        message = f"{prefix} action unavailable: Native Mesh Editor C++ core is missing ({normalized})."
        if embedded:
            label = getattr(self.embedded_workspace, "status_label", None) if self.embedded_workspace is not None else None
        else:
            label = getattr(self, "standalone_status_label", None)
        if label is not None:
            label.setText(message)
        self.status_message_requested.emit(message, True)
        return True

    def _sync_state(self) -> None:
        target = self._current_target_entry()
        has_standalone = self.has_active_standalone_session()
        has_target = target is not None or has_standalone
        has_workflow_target = target is not None
        native_editor_available = self._native_mesh_editor_available()
        workflow_mode = str(getattr(self.current_request, "mode", "") or "modify_original")
        path_text = self._entry_path(target) if target is not None else self.standalone_mesh_label
        label_text = self._entry_label(target) if target is not None else Path(self.standalone_mesh_label).name or "none"
        self.target_label.setText(f"Target: {path_text or label_text}")
        self.session_label.setText(
            f"Mode: {'standalone' if has_standalone else workflow_mode.replace('_', ' ')} | Edit: {self.current_edit_mode}"
            if has_target
            else "Mode: no active session"
        )
        self.empty_status_label.setText(
            "Ready: choose Modify Original, Import Replacement, Import Preview, or In-Game Swap. "
            "The full Mesh Replacement Builder opens here; archive writes still require explicit build/export confirmation."
            if has_target
            else "No mesh target loaded. Select a .pac, .pam, or .pamlod in Archive Browser, then Open in Mesh Editor."
        )
        for button in (
            self.open_archive_button,
            self.modify_original_button,
            self.import_replacement_button,
            self.import_preview_button,
            self.in_game_swap_button,
        ):
            button.setEnabled(has_workflow_target)
        self.standalone_native_preview_button.setEnabled(has_standalone)
        self.action_bar.setVisible(False)
        task_active = (
            self._standalone_action_worker_active()
            or self._standalone_validation_worker_active()
            or self._standalone_rebuild_report_worker_active()
            or self._standalone_editable_package_task_active()
            or self._standalone_dotnet_package_worker_active()
            or self._standalone_dotnet_import_worker_active()
            or self._standalone_dotnet_editor_process_running()
        )
        self.action_bar.setEnabled(not task_active)
        self.action_bar.update_action_state(
            has_target=has_target,
            selection_empty=self.current_selection_empty,
            mode=self.current_edit_mode,
            active_selection_mode=self.current_selection_mode,
            active_tool_key=self.current_tool_action_key,
            undo_count=self.current_undo_count,
            redo_count=self.current_redo_count,
            native_editor_available=native_editor_available,
        )
        workspace_state = getattr(self.standalone_workspace, "update_action_state", None)
        if callable(workspace_state):
            workspace_state(
                has_target=has_target,
                selection_empty=self.current_selection_empty,
                mode=self.current_edit_mode,
                active_selection_mode=self.current_selection_mode,
                undo_count=self.current_undo_count,
                redo_count=self.current_redo_count,
                native_editor_available=native_editor_available,
            )
        dotnet_button = getattr(self, "standalone_dotnet_editor_button", None)
        if dotnet_button is not None:
            dotnet_button.setEnabled(has_standalone and not task_active)
        embedded_dotnet_button = getattr(self, "embedded_dotnet_editor_button", None)
        if embedded_dotnet_button is not None:
            embedded_dotnet_button.setEnabled(self.workspace_stack.currentWidget() is self.embedded_builder_host and not task_active)
        for button_name in (
            "standalone_run_validation_report_button",
            "standalone_rebuild_asset_button",
            "standalone_preview_rebuilt_asset_button",
            "standalone_package_rebuilt_asset_button",
            "standalone_export_editable_package_button",
            "standalone_import_edited_package_button",
            "standalone_open_editable_package_folder_button",
        ):
            button = getattr(self, button_name, None)
            if button is not None:
                enabled = has_standalone and not task_active
                if button_name == "standalone_rebuild_asset_button":
                    enabled = enabled and self._standalone_rebuild_allowed()
                elif button_name in {"standalone_preview_rebuilt_asset_button", "standalone_package_rebuilt_asset_button"}:
                    enabled = enabled and self.standalone_last_rebuilt_asset_path is not None
                button.setEnabled(enabled)
        self._set_rebuild_report_button_enabled(has_standalone and not task_active)
        self._set_rebuild_asset_button_enabled(has_standalone and not task_active and self._standalone_rebuild_allowed())

    def _handle_action_requested(self, action: object) -> None:
        if self.has_active_standalone_session():
            self._run_standalone_action(action)
            return
        self.mesh_action_requested.emit(action)

    def _embedded_builder_controller(self) -> MeshEditorController | None:
        builder = self.active_builder()
        getter = getattr(builder, "_mesh_editor_embedded_controller", None) if builder is not None else None
        if not callable(getter):
            return None
        try:
            controller = getter()
        except Exception:
            return None
        return controller if isinstance(controller, MeshEditorController) else None

    def _refresh_embedded_workspace_from_builder(self) -> None:
        workspace = self.embedded_workspace
        if workspace is None:
            return
        controller = self._embedded_builder_controller()
        view: MeshEditSessionView | None = None
        if controller is not None:
            try:
                view = controller.session_view()
            except Exception:
                view = None
        if controller is None or view is None:
            if hasattr(workspace, "status_label"):
                workspace.status_label.setText("No active edit session.")
            workspace.update_session_summary(None)
            workspace.update_workspace_summary(None)
            workspace.update_uv_summary(None)
            workspace.update_skeleton_summary(None)
            workspace.update_compare_summary(None)
            workspace.update_export_validation(None)
            workspace.update_rebuild_report(None)
            workspace.update_action_state(has_target=False)
            return
        native_editor_available = self._native_mesh_editor_available()
        if hasattr(workspace, "status_label"):
            if native_editor_available:
                workspace.status_label.setText(
                    f"Mesh editing ready | Mode: {str(view.mode or 'edit').title()} | "
                    f"Revision {view.revision} | Undo {view.undo_count} | Redo {view.redo_count}"
                )
            else:
                workspace.status_label.setText("Native Mesh Editor unavailable: C++ mesh core missing.")
        workspace.update_session_summary(view, mesh_label=self._entry_label(self._current_target_entry()))
        for method_name, updater_name in (
            ("workspace_summary", "update_workspace_summary"),
            ("uv_summary", "update_uv_summary"),
            ("skeleton_summary", "update_skeleton_summary"),
            ("compare_summary", "update_compare_summary"),
            ("export_validation_report", "update_export_validation"),
        ):
            updater = getattr(workspace, updater_name, None)
            method = getattr(controller, method_name, None)
            if callable(updater) and callable(method):
                try:
                    updater(method())
                except Exception:
                    updater(None)
        workspace.update_rebuild_report(None)
        workspace.update_action_state(
            has_target=True,
            selection_empty=bool(view.selection.is_empty()),
            mode=str(view.mode or "edit"),
            active_selection_mode=str(getattr(controller, "active_selection_mode", "") or self.current_selection_mode or "vertex"),
            undo_count=int(view.undo_count or 0),
            redo_count=int(view.redo_count or 0),
            native_editor_available=native_editor_available,
        )

    def _apply_embedded_native_update(self, update: MeshEditorNativeUpdate) -> bool:
        builder = self.active_builder()
        sender = getattr(builder, "_mesh_editor_embedded_apply_native_update", None) if builder is not None else None
        if callable(sender):
            try:
                return bool(sender(update))
            except Exception:
                return False
        return False

    def _handle_embedded_part_selection(self, part_index: int, operation: str = "toggle") -> bool:
        controller = self._embedded_builder_controller()
        if controller is None:
            self.status_message_requested.emit("Embedded Mesh Editor part tools are not ready yet.", True)
            return False
        normalized_operation = str(operation or "toggle").strip().lower()
        try:
            if normalized_operation == "clear":
                result = controller.select(source_indices=(), operation="replace")
            elif normalized_operation == "select_all":
                summary = controller.workspace_summary()
                result = controller.select(source_indices=tuple(part.index for part in summary.parts), operation="replace")
            elif normalized_operation == "invert":
                summary = controller.workspace_summary()
                selected_sources = set(controller.session_view().selection.source_indices)
                result = controller.select(
                    source_indices=tuple(part.index for part in summary.parts if part.index not in selected_sources),
                    operation="replace",
                )
            else:
                result = controller.select(source_indices=(int(part_index),), operation=normalized_operation)
            update = controller.native_update_for_result(result)
        except Exception as exc:
            self.status_message_requested.emit(f"Embedded Mesh Editor part selection failed: {exc}", True)
            return False
        self._apply_embedded_native_update(update)
        self._refresh_embedded_workspace_from_builder()
        selected_names = ", ".join(part.name for part in controller.workspace_summary().parts if part.selected)
        self.status_message_requested.emit(
            f"Embedded Mesh Editor selected {len(controller.session_view().selection.source_indices)} part(s){': ' + selected_names if selected_names else ''}.",
            False,
        )
        return True

    def _embedded_selection_for_part_context(
        self,
        controller: MeshEditorController,
        part_index: int,
    ) -> MeshEditSelection | None:
        try:
            clicked_index = int(part_index)
        except (TypeError, ValueError):
            clicked_index = -1
        if clicked_index < 0:
            return None
        selected_sources = set(controller.session_view().selection.source_indices)
        if clicked_index not in selected_sources:
            result = controller.select(source_indices=(clicked_index,), operation="replace")
            self._apply_embedded_native_update(controller.native_update_for_result(result))
            selected_sources = {clicked_index}
            self._refresh_embedded_workspace_from_builder()
        return MeshEditSelection.from_maps(source_indices=selected_sources)

    def _handle_embedded_part_context_action(self, action_key: str, part_index: int) -> bool:
        normalized = str(action_key or "").strip().lower()
        if normalized == "select_only":
            return self._handle_embedded_part_selection(part_index, "replace")
        if normalized == "toggle_selection":
            return self._handle_embedded_part_selection(part_index, "toggle")
        if self._native_editor_action_blocked(normalized, embedded=True):
            return False
        controller = self._embedded_builder_controller()
        if controller is None:
            self.status_message_requested.emit("Embedded Mesh Editor part tools are not ready yet.", True)
            return False
        selection = self._embedded_selection_for_part_context(controller, part_index)
        if selection is None:
            return False
        if normalized == "open_texture":
            return self._open_selected_texture_in_editor_for_controller(controller)
        runner = getattr(self.active_builder(), "_mesh_editor_embedded_run_part_action", None)
        if not callable(runner):
            self.status_message_requested.emit(f"Embedded Mesh Editor part action is unavailable: {normalized}.", True)
            return False
        try:
            ok = bool(runner(normalized, tuple(selection.source_indices)))
        except Exception as exc:
            self.status_message_requested.emit(f"Embedded Mesh Editor part action failed: {normalized}: {exc}", True)
            return False
        self._refresh_embedded_workspace_from_builder()
        return ok

    def _handle_embedded_open_texture(self) -> bool:
        controller = self._embedded_builder_controller()
        if controller is None:
            self.status_message_requested.emit("Embedded Mesh Editor part tools are not ready yet.", True)
            return False
        return self._open_selected_texture_in_editor_for_controller(controller)

    def _handle_embedded_compare_mode(self, mode: str) -> None:
        self.status_message_requested.emit(f"Embedded Mesh Editor compare mode selected: {str(mode or 'edited')}.", False)

    def _handle_embedded_skeleton_pose_request(self, command: str, payload: object) -> bool:
        normalized = str(command or "").strip().lower()
        if normalized != "select_bone":
            self.status_message_requested.emit("Embedded rig view supports bone selection; pose and weight authoring stay standalone.", False)
            return False
        controller = self._embedded_builder_controller()
        if controller is None:
            self.status_message_requested.emit("Embedded Mesh Editor rig tools are not ready yet.", True)
            return False
        try:
            summary = controller.select_bone(int(payload))  # type: ignore[arg-type]
        except Exception as exc:
            self.status_message_requested.emit(f"Embedded Mesh Editor bone selection failed: {exc}", True)
            return False
        setter = getattr(self.active_builder(), "_mesh_editor_embedded_set_skeleton_bone", None)
        if callable(setter):
            try:
                setter(summary.pose.selected_bone_index)
            except Exception:
                pass
        self._refresh_embedded_workspace_from_builder()
        selected = summary.pose.selected_bone_name or "bone"
        self.status_message_requested.emit(f"Embedded Mesh Editor selected bone {summary.pose.selected_bone_index}: {selected}.", False)
        return True

    def _handle_embedded_uv_region_selection(self, uv_min: tuple, uv_max: tuple, operation: str) -> bool:
        controller = self._embedded_builder_controller()
        if controller is None:
            return False
        try:
            result = controller.select_uv_region(uv_min, uv_max, operation=operation)
        except Exception as exc:
            self.status_message_requested.emit(f"Embedded Mesh Editor UV selection failed: {exc}", True)
            return False
        if not result.ok:
            diagnostic = "; ".join(str(item) for item in tuple(result.diagnostics or ()) if str(item).strip())
            self.status_message_requested.emit(
                f"Embedded Mesh Editor UV selection failed{': ' + diagnostic if diagnostic else ''}.",
                True,
            )
            return False
        self._apply_embedded_native_update(controller.native_update_for_result(result))
        self._refresh_embedded_workspace_from_builder()
        return True

    def _handle_embedded_uv_lasso_selection(self, points: tuple, operation: str) -> bool:
        controller = self._embedded_builder_controller()
        if controller is None:
            return False
        try:
            result = controller.select_uv_lasso(points, operation=operation)
        except Exception as exc:
            self.status_message_requested.emit(f"Embedded Mesh Editor UV lasso failed: {exc}", True)
            return False
        if not result.ok:
            diagnostic = "; ".join(str(item) for item in tuple(result.diagnostics or ()) if str(item).strip())
            self.status_message_requested.emit(
                f"Embedded Mesh Editor UV lasso failed{': ' + diagnostic if diagnostic else ''}.",
                True,
            )
            return False
        self._apply_embedded_native_update(controller.native_update_for_result(result))
        self._refresh_embedded_workspace_from_builder()
        return True

    def _handle_embedded_native_part_selected(self, part_index: int) -> bool:
        return self._handle_embedded_part_selection(part_index, "toggle")

    def _show_embedded_part_context_menu(self, part_index: int, global_pos: object | None = None) -> bool:
        controller = self._embedded_builder_controller()
        workspace = self.embedded_workspace
        if controller is None or workspace is None:
            return False
        if self._embedded_selection_for_part_context(controller, part_index) is None:
            return False
        QTimer.singleShot(0, lambda index=int(part_index), position=global_pos: workspace.show_part_context_menu_for_part(index, position))
        return True

    def _handle_skeleton_pose_request(self, command: str, payload: object) -> bool:
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before editing skeleton preview.", True)
            return False
        normalized = str(command or "").strip().lower()
        try:
            if normalized == "set_pose_preview":
                controller.set_pose_preview(bool(payload))
            elif normalized == "select_bone":
                controller.select_bone(int(payload))  # type: ignore[arg-type]
            elif normalized == "rotate_selected_bone":
                controller.rotate_selected_bone(payload)  # type: ignore[arg-type]
            elif normalized == "reset_pose":
                controller.reset_pose()
            elif normalized == "set_animation_playback":
                summary = controller.set_animation_playback(bool(payload))
                if summary.animation_playback.enabled:
                    self.standalone_animation_last_tick = time.monotonic()
                    self.standalone_animation_timer.start()
                else:
                    self.standalone_animation_timer.stop()
            elif normalized == "set_animation_loop":
                controller.set_animation_loop(bool(payload))
            elif normalized == "set_animation_speed":
                controller.set_animation_speed(payload)
            elif normalized == "seek_animation":
                controller.seek_animation(payload)
                self.standalone_animation_last_tick = time.monotonic()
            elif normalized == "scrub_animation_fraction":
                controller.scrub_animation_fraction(payload)
                self.standalone_animation_last_tick = time.monotonic()
            elif normalized == "step_animation_frame":
                controller.step_animation_frame(payload)
                self.standalone_animation_last_tick = time.monotonic()
            elif normalized == "step_animation":
                controller.step_animation(payload)
                self.standalone_animation_last_tick = time.monotonic()
            elif normalized == "adjust_selected_vertex_bone_weight":
                controller.adjust_selected_vertex_bone_weight(payload)
            elif normalized == "normalize_selected_vertex_weights":
                controller.normalize_selected_vertex_weights()
            elif normalized == "transfer_selected_vertex_weights_from_source":
                controller.transfer_selected_vertex_weights_from_source(source_skeleton=self.standalone_source_skeleton)
            else:
                return False
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor skeleton preview failed: {exc}", True)
            return False
        self.update_editor_session_state(controller.session_view(), active_selection_mode=controller.active_selection_mode)
        if self.standalone_compare_mode != "source":
            if self._standalone_native_preview_update_active():
                if self.standalone_native_package_thread is None:
                    self.start_standalone_native_preview_async(reset_view=False)
            else:
                self._refresh_standalone_preview()
        self.status_message_requested.emit("Mesh Editor skeleton preview updated.", False)
        return True

    def _tick_standalone_animation_playback(self) -> None:
        controller = self.standalone_controller
        if controller is None:
            self.standalone_animation_timer.stop()
            return
        now = time.monotonic()
        previous = self.standalone_animation_last_tick or now
        self.standalone_animation_last_tick = now
        delta = max(0.0, min(0.25, now - previous))
        try:
            summary = controller.step_animation(delta)
        except Exception as exc:
            self.standalone_animation_timer.stop()
            self.status_message_requested.emit(f"Mesh Editor animation playback failed: {exc}", True)
            return
        if not summary.animation_playback.enabled:
            self.standalone_animation_timer.stop()
        self.update_editor_session_state(controller.session_view(), active_selection_mode=controller.active_selection_mode)
        if self.standalone_compare_mode != "source":
            if self._standalone_native_preview_update_active():
                if self.standalone_native_package_thread is None:
                    self.start_standalone_native_preview_async(reset_view=False)
            else:
                self._refresh_standalone_preview()

    def _handle_uv_region_selection(self, uv_min: object, uv_max: object, operation: str = "replace") -> bool:
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before selecting UVs.", True)
            return False
        try:
            result = controller.select_uv_region(uv_min, uv_max, operation=operation)  # type: ignore[arg-type]
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor UV selection failed: {exc}", True)
            return False
        if not result.ok:
            diagnostic = "; ".join(str(item) for item in tuple(result.diagnostics or ()) if str(item).strip())
            self.status_message_requested.emit(
                f"Mesh Editor UV selection failed{': ' + diagnostic if diagnostic else ''}.",
                True,
            )
            return False
        update = controller.native_update_for_result(result)
        view = controller.session_view()
        self.update_editor_session_state(view, active_selection_mode=controller.active_selection_mode)
        self._apply_standalone_native_update(update)
        if view.selection.is_empty():
            self.status_message_requested.emit("Mesh Editor UV region selection is empty.", False)
        else:
            self.status_message_requested.emit("Mesh Editor UV region selected.", False)
        return True

    def _handle_uv_lasso_selection(self, points: object, operation: str = "replace") -> bool:
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before selecting UVs.", True)
            return False
        try:
            result = controller.select_uv_lasso(points, operation=operation)  # type: ignore[arg-type]
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor UV lasso selection failed: {exc}", True)
            return False
        if not result.ok:
            diagnostic = "; ".join(str(item) for item in tuple(result.diagnostics or ()) if str(item).strip())
            self.status_message_requested.emit(
                f"Mesh Editor UV lasso selection failed{': ' + diagnostic if diagnostic else ''}.",
                True,
            )
            return False
        update = controller.native_update_for_result(result)
        view = controller.session_view()
        self.update_editor_session_state(view, active_selection_mode=controller.active_selection_mode)
        self._apply_standalone_native_update(update)
        if view.selection.is_empty():
            self.status_message_requested.emit("Mesh Editor UV lasso selection is empty.", False)
        else:
            self.status_message_requested.emit("Mesh Editor UV lasso selected.", False)
        return True

    def _handle_native_source_part_selected(self, part_index: int) -> bool:
        try:
            normalized_index = int(part_index)
        except (TypeError, ValueError):
            normalized_index = -1
        if normalized_index < 0:
            return False
        return self._handle_part_selection(normalized_index, "toggle")

    def _handle_native_source_part_context_requested(self, part_index: int, x: int, y: int) -> bool:
        controller = self.standalone_controller
        if controller is None:
            return False
        try:
            normalized_index = int(part_index)
        except (TypeError, ValueError):
            normalized_index = -1
        if normalized_index < 0:
            return False
        if self._selection_for_part_context(controller, normalized_index) is None:
            return False
        global_pos = self._standalone_native_global_pos(x, y)
        QTimer.singleShot(
            0,
            lambda index=normalized_index, position=global_pos: self.standalone_workspace.show_part_context_menu_for_part(
                index,
                position,
            ),
        )
        return True

    def _standalone_native_global_pos(self, x: int, y: int) -> object | None:
        host = self.standalone_native_host
        cursor = getattr(host, "cursor", None)
        if callable(cursor):
            try:
                return cursor().pos()
            except RuntimeError:
                pass
        mapper = getattr(host, "mapToGlobal", None)
        if callable(mapper):
            try:
                return mapper(QPoint(int(x), int(y)))
            except (RuntimeError, TypeError, ValueError):
                pass
        return None

    def _handle_standalone_native_mesh_edit_stroke_started(self, payload: object) -> bool:
        return self._apply_standalone_native_mesh_edit_stroke(payload, "begin")

    def _handle_standalone_native_mesh_edit_stroke_previewed(self, payload: object) -> bool:
        return self._apply_standalone_native_mesh_edit_stroke(payload, "update")

    def _handle_standalone_native_mesh_edit_stroke_finished(self, payload: object) -> bool:
        return self._apply_standalone_native_mesh_edit_stroke(payload, "end")

    def _handle_standalone_native_mesh_edit_stroke_cancelled(self, payload: object) -> bool:
        return self._apply_standalone_native_mesh_edit_stroke(payload, "cancel")

    def _handle_standalone_native_mesh_edit_selection_changed(self, payload: object) -> bool:
        controller = self.standalone_controller
        if controller is None or not isinstance(payload, Mapping):
            return False
        raw_screen_brush = payload.get("screen_brush")
        raw_screen_region = payload.get("screen_region")
        if not isinstance(raw_screen_brush, Mapping) and not isinstance(raw_screen_region, Mapping):
            return False
        if self._native_editor_action_blocked("select"):
            return False
        operation = str(payload.get("operation", payload.get("selection_operation", "replace")) or "replace").strip().lower()
        context_request = bool(payload.get("context_request"))
        screen_payload: dict[str, object] = {}
        if isinstance(raw_screen_brush, Mapping):
            screen_payload["screen_brush"] = self._native_screen_payload(raw_screen_brush)
        if isinstance(raw_screen_region, Mapping):
            screen_payload["screen_region"] = self._native_screen_payload(raw_screen_region)
        if "falloff" in payload:
            screen_payload["falloff"] = str(payload.get("falloff") or "smooth")
        if "target_mode" in payload:
            screen_payload["target_mode"] = str(payload.get("target_mode") or "vertex")
        if "selection_depth_mode" in payload:
            screen_payload["selection_depth_mode"] = str(payload.get("selection_depth_mode") or "visible")
        try:
            result = controller.apply(
                "select",
                selection=MeshEditSelection(),
                operation=operation,
                _native_screen_selection_payload=screen_payload,
            )
            native_update = controller.native_update_for_result(result)
        except Exception as exc:
            self.standalone_status_label.setText(f"Native D3D11 mesh selection failed: {exc}")
            self.status_message_requested.emit(f"Native D3D11 mesh selection failed: {exc}", True)
            return False
        if not result.ok:
            diagnostic = "; ".join(str(item) for item in tuple(result.diagnostics or ()) if str(item).strip())
            self.standalone_status_label.setText(f"Native D3D11 mesh selection failed{': ' + diagnostic if diagnostic else ''}.")
            return False
        self.standalone_last_action_result = result
        self.standalone_last_action_metrics = {
            str(key): float(value) for key, value in dict(result.metrics).items()
        }
        if not self._apply_standalone_native_update(native_update):
            return False
        if context_request:
            if float(dict(result.metrics).get("editor_select_source_pick_count", 0.0) or 0.0) <= 0.0:
                self.standalone_status_label.setText("Native D3D11 mesh context hit no source part.")
                return False
            view = controller.session_view()
            source_indices = tuple(int(index) for index in view.selection.source_indices)
            if not source_indices:
                self.standalone_status_label.setText("Native D3D11 mesh context hit no source part.")
                return False
            try:
                context_x = int(payload.get("context_x", 0) or 0)
                context_y = int(payload.get("context_y", 0) or 0)
            except (TypeError, ValueError):
                context_x = 0
                context_y = 0
            global_pos = self._standalone_native_global_pos(context_x, context_y)
            QTimer.singleShot(
                0,
                lambda index=source_indices[0], position=global_pos: self.standalone_workspace.show_part_context_menu_for_part(
                    index,
                    position,
                ),
            )
            self.standalone_status_label.setText("Native D3D11 mesh context opened.")
            return True
        self.standalone_status_label.setText("Native D3D11 mesh selection updated.")
        return True

    def _apply_standalone_native_mesh_edit_stroke(self, payload: object, phase: str) -> bool:
        controller = self.standalone_controller
        if controller is None or not isinstance(payload, Mapping):
            return False
        if self._native_editor_action_blocked("transform" if str(payload.get("tool") or "").strip().lower() in {"move", "vertex"} else "brush"):
            return False
        command = self._standalone_native_mesh_edit_stroke_command(payload, phase)
        if command is None:
            return False
        stroke_id = str(command.params.get("stroke_id") or "")
        if phase == "begin":
            if self.standalone_native_mesh_edit_stroke_id and self.standalone_native_mesh_edit_stroke_id != stroke_id:
                return False
        elif stroke_id and self.standalone_native_mesh_edit_stroke_id and self.standalone_native_mesh_edit_stroke_id != stroke_id:
            return False
        try:
            result = controller.apply(command.action, selection=command.selection, mode=command.mode, **dict(command.params))
            native_update = controller.native_update_for_result(result)
        except Exception as exc:
            self.standalone_status_label.setText(f"Native D3D11 mesh edit stroke failed: {exc}")
            self.status_message_requested.emit(f"Native D3D11 mesh edit stroke failed: {exc}", True)
            if phase in {"end", "cancel"}:
                self.standalone_native_mesh_edit_stroke_id = ""
                self.standalone_native_mesh_edit_stroke_changed = False
            return False
        if stroke_id and phase == "begin":
            self.standalone_native_mesh_edit_stroke_id = stroke_id
            self.standalone_native_mesh_edit_stroke_changed = False
        has_native_delta = result.ok and (
            result.affected_submesh_indices
            or result.changed_vertices_by_submesh
            or result.topology_changed
            or native_update.vertex_groups
            or native_update.triangle_groups
            or native_update.material_override_groups
        )
        stroke_changed = bool(self.standalone_native_mesh_edit_stroke_changed or has_native_delta)
        if has_native_delta:
            self.standalone_native_mesh_edit_stroke_changed = True
        if phase in {"end", "cancel"}:
            self.standalone_native_mesh_edit_stroke_id = ""
            self.standalone_native_mesh_edit_stroke_changed = False
        if str(result.status or "").strip().lower() in {"ok", "noop"}:
            self.standalone_last_action_result = result
            self.standalone_last_action_metrics = {
                str(key): float(value) for key, value in dict(result.metrics).items()
            }
        if has_native_delta:
            if not self._apply_standalone_native_update(native_update):
                return False
            if phase != "update":
                if phase == "end" and stroke_changed:
                    self.current_selection_mode = controller.active_selection_mode
                    self.current_undo_count += 1
                    self.current_redo_count = 0
                    QTimer.singleShot(0, self._sync_state)
                self.standalone_status_label.setText(f"Native D3D11 mesh edit stroke {phase}.")
            else:
                self.standalone_status_label.setText("Native D3D11 mesh edit stroke updating.")
        elif phase in {"end", "cancel"}:
            if phase == "end" and stroke_changed:
                self.current_selection_mode = controller.active_selection_mode
                self.current_undo_count += 1
                self.current_redo_count = 0
                QTimer.singleShot(0, self._sync_state)
            self.standalone_status_label.setText(f"Native D3D11 mesh edit stroke {phase}.")
        return True

    def _standalone_native_mesh_edit_stroke_command(self, payload: Mapping[object, object], phase: str) -> MeshEditCommand | None:
        normalized_phase = str(phase or "").strip().lower()
        if normalized_phase not in {"begin", "update", "end", "cancel"}:
            return None
        stroke_id = str(payload.get("stroke_id") or "").strip()
        if not stroke_id:
            return None
        tool = str(payload.get("tool") or "").strip().lower()
        raw_groups_for_reuse = payload.get("groups")
        try:
            has_groups_for_reuse = bool(tuple(raw_groups_for_reuse or ())) and not isinstance(raw_groups_for_reuse, (Mapping, str, bytes))  # type: ignore[arg-type]
        except TypeError:
            has_groups_for_reuse = False
        reuse_resident_selection = (
            normalized_phase == "update"
            and (
                tool in {"move", "vertex", "grab"}
                or (
                    tool in {"smooth", "inflate", "pinch"}
                    and isinstance(payload.get("screen_brush"), Mapping)
                    and not has_groups_for_reuse
                )
            )
            and bool(stroke_id)
            and stroke_id == self.standalone_native_mesh_edit_stroke_id
        )
        params: dict[str, object] = {
            "stroke_phase": normalized_phase,
            "stroke_id": stroke_id,
        }
        if tool in {"move", "vertex"}:
            raw_screen_drag = payload.get("screen_drag")
            if not isinstance(raw_screen_drag, Mapping):
                if normalized_phase in {"end", "cancel"}:
                    return MeshEditCommand("transform", params=params, mode="edit", label="D3D11 stroke")
                return None
            params["screen_drag"] = MeshEditorTab._native_screen_payload(raw_screen_drag)
            if not reuse_resident_selection:
                raw_screen_brush = payload.get("screen_brush")
                if isinstance(raw_screen_brush, Mapping):
                    screen_payload: dict[str, object] = {"screen_brush": MeshEditorTab._native_screen_payload(raw_screen_brush)}
                    if "target_mode" in payload:
                        screen_payload["target_mode"] = str(payload.get("target_mode") or "vertex")
                    if "selection_depth_mode" in payload:
                        screen_payload["selection_depth_mode"] = str(payload.get("selection_depth_mode") or "visible")
                    if "falloff" in payload:
                        screen_payload["falloff"] = str(payload.get("falloff") or "smooth")
                    params["_native_screen_selection_payload"] = screen_payload
                else:
                    native_selection = self._standalone_native_payload_selection(payload)
                    if native_selection:
                        params["_native_selection_payload"] = native_selection
            return MeshEditCommand("transform", params=params, mode="edit", label="D3D11 stroke")
        if tool not in {"grab", "smooth", "inflate", "pinch"}:
            return None
        params["tool"] = tool
        raw_center = payload.get("center")
        if raw_center is not None:
            params["center"] = raw_center if isinstance(raw_center, Mapping) else self._standalone_native_payload_vec3(raw_center)
        raw_screen_drag = payload.get("screen_drag")
        if isinstance(raw_screen_drag, Mapping):
            params["screen_drag"] = MeshEditorTab._native_screen_payload(raw_screen_drag)
        if "radius" in payload:
            params["radius"] = self._standalone_native_payload_float(payload.get("radius"), 1.0)
        raw_screen_radius = payload.get("screen_radius")
        if isinstance(raw_screen_radius, Mapping):
            params["screen_radius"] = MeshEditorTab._native_screen_payload(raw_screen_radius)
        raw_screen_brush = payload.get("screen_brush")
        if isinstance(raw_screen_brush, Mapping):
            params["screen_brush"] = MeshEditorTab._native_screen_payload(raw_screen_brush)
        if "target_mode" in payload:
            params["target_mode"] = str(payload.get("target_mode") or "vertex")
        if "selection_depth_mode" in payload:
            params["selection_depth_mode"] = str(payload.get("selection_depth_mode") or "visible")
        if "strength" in payload:
            params["strength"] = self._standalone_native_payload_float(payload.get("strength"), 0.5)
        if "amount" in payload:
            params["amount"] = self._standalone_native_payload_float(payload.get("amount"), 0.0)
        if "falloff" in payload:
            params["falloff"] = str(payload.get("falloff") or "smooth")
        if "smooth_iterations" in payload:
            params["iterations"] = self._standalone_native_payload_int(payload.get("smooth_iterations"), 3)
        if "invert" in payload:
            params["invert"] = bool(payload.get("invert"))
        if not reuse_resident_selection and not (isinstance(raw_screen_brush, Mapping) and not has_groups_for_reuse):
            native_selection = self._standalone_native_payload_selection(payload)
            if native_selection:
                params["_native_selection_payload"] = native_selection
        return MeshEditCommand("brush", params=params, mode="sculpt", label="D3D11 stroke")

    @staticmethod
    def _native_screen_payload(payload: Mapping[object, object]) -> dict[object, object]:
        return {key: value for key, value in payload.items() if str(key) not in _LEGACY_SCREEN_CAMERA_FIELDS}

    @classmethod
    def _standalone_native_payload_selection(cls, payload: Mapping[object, object]) -> dict[str, object]:
        raw_groups = payload.get("groups")
        if isinstance(raw_groups, Mapping) or isinstance(raw_groups, (str, bytes)):
            return {}
        try:
            groups = tuple(raw_groups or ())  # type: ignore[arg-type]
        except TypeError:
            return {}
        vertices_by_submesh: list[dict[str, object]] = []
        faces_by_submesh: list[dict[str, object]] = []
        for raw_group in groups:
            if not isinstance(raw_group, Mapping):
                continue
            submesh_index = cls._standalone_native_payload_int(
                raw_group.get("source_submesh_index", raw_group.get("index", raw_group.get("submesh_index"))),
                -1,
            )
            if submesh_index < 0:
                continue
            vertex_payload = cls._standalone_native_group_indices(
                raw_group,
                values_key="source_vertex_indices",
                binary_key="source_vertex_indices_binary",
                weights_key="source_vertex_weights",
                weights_binary_key="source_vertex_weights_binary",
                start_key="source_vertex_start",
                count_key="source_vertex_count",
            )
            if vertex_payload:
                vertices_by_submesh.append({"index": submesh_index, **vertex_payload})
            face_payload = cls._standalone_native_group_indices(
                raw_group,
                values_key="source_face_indices",
                binary_key="source_face_indices_binary",
                start_key="source_face_start",
                count_key="source_face_count",
            )
            if face_payload:
                faces_by_submesh.append({"index": submesh_index, **face_payload})
        result: dict[str, object] = {}
        if vertices_by_submesh:
            result["vertices_by_submesh"] = vertices_by_submesh
        if faces_by_submesh:
            result["faces_by_submesh"] = faces_by_submesh
        return result

    @classmethod
    def _standalone_native_group_indices(
        cls,
        group: Mapping[object, object],
        *,
        values_key: str,
        binary_key: str,
        start_key: str,
        count_key: str,
        weights_key: str = "",
        weights_binary_key: str = "",
    ) -> dict[str, object]:
        binary = group.get(binary_key)
        weight_payload: dict[str, object] = {}
        weights_binary = group.get(weights_binary_key) if weights_binary_key else None
        if isinstance(weights_binary, Mapping):
            weight_payload["weights_binary"] = dict(weights_binary)
        elif weights_key:
            raw_weights = group.get(weights_key)
            if not isinstance(raw_weights, Mapping) and not isinstance(raw_weights, (str, bytes)):
                try:
                    weights = tuple(raw_weights or ())  # type: ignore[arg-type]
                except TypeError:
                    weights = ()
                if weights:
                    weight_payload["weights"] = weights
        if isinstance(binary, Mapping):
            return {"indices_binary": dict(binary), **weight_payload}
        start = cls._standalone_native_payload_int(group.get(start_key), -1)
        count = cls._standalone_native_payload_int(group.get(count_key), 0)
        if start >= 0 and count > 0:
            return {"start": start, "count": count, **weight_payload}
        raw_values = group.get(values_key)
        if isinstance(raw_values, Mapping) or isinstance(raw_values, (str, bytes)):
            return {}
        try:
            values = tuple(raw_values or ())  # type: ignore[arg-type]
        except TypeError:
            return {}
        indices = sorted({cls._standalone_native_payload_int(value, -1) for value in values})
        indices = [index for index in indices if index >= 0]
        return {"indices": indices, **weight_payload} if indices else {}

    @staticmethod
    def _standalone_native_payload_vec3(value: object) -> tuple[float, float, float]:
        if isinstance(value, Mapping):
            raw_values = (value.get("x", 0.0), value.get("y", 0.0), value.get("z", 0.0))
        else:
            try:
                raw_values = tuple(value or ())[:3]  # type: ignore[arg-type]
            except TypeError:
                raw_values = ()
        result: list[float] = []
        for raw in tuple(raw_values)[:3]:
            try:
                result.append(float(raw))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                result.append(0.0)
        while len(result) < 3:
            result.append(0.0)
        return result[0], result[1], result[2]

    @staticmethod
    def _standalone_native_payload_float(value: object, fallback: float = 0.0) -> float:
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return float(fallback)

    @staticmethod
    def _standalone_native_payload_int(value: object, fallback: int = 0) -> int:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError, OverflowError):
            return int(fallback)

    def _handle_part_selection(self, part_index: int, operation: str = "toggle") -> bool:
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before selecting parts.", True)
            return False
        normalized_operation = str(operation or "toggle").strip().lower()
        try:
            if normalized_operation == "clear":
                result = controller.select(source_indices=(), operation="replace")
            elif normalized_operation == "select_all":
                summary = controller.workspace_summary()
                result = controller.select(source_indices=tuple(part.index for part in summary.parts), operation="replace")
            elif normalized_operation == "invert":
                summary = controller.workspace_summary()
                selected_sources = set(controller.session_view().selection.source_indices)
                result = controller.select(
                    source_indices=tuple(part.index for part in summary.parts if part.index not in selected_sources),
                    operation="replace",
                )
            else:
                result = controller.select(
                    source_indices=(int(part_index),),
                    operation=normalized_operation,
                )
            update = controller.native_update_for_result(result)
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor part selection failed: {exc}", True)
            return False
        view = controller.session_view()
        self.update_editor_session_state(view, active_selection_mode=controller.active_selection_mode)
        self._apply_standalone_native_update(update)
        summary = controller.workspace_summary()
        selected_names = ", ".join(part.name for part in summary.parts if part.selected)
        self.status_message_requested.emit(
            f"Mesh Editor selected {len(view.selection.source_indices)} part(s){': ' + selected_names if selected_names else ''}.",
            False,
        )
        return True

    def _handle_part_context_action(self, action_key: str, part_index: int) -> bool:
        normalized = str(action_key or "").strip().lower()
        if normalized == "select_only":
            return self._handle_part_selection(part_index, "replace")
        if normalized == "toggle_selection":
            return self._handle_part_selection(part_index, "toggle")
        if self._native_editor_action_blocked(normalized):
            return False
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before editing parts.", True)
            return False
        selection = self._selection_for_part_context(controller, part_index)
        if selection is None:
            return False
        if normalized == "open_texture":
            return self.open_selected_texture_in_editor()
        if normalized not in {"delete", "duplicate", "recalculate_normals", "flip_normals"}:
            return False
        params = {"delete_parts": True} if normalized == "delete" else {}
        try:
            execution = controller.run_editor_action(normalized, selection=selection, mode="edit", **params)
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor part action failed: {normalized}: {exc}", True)
            return False
        self.update_editor_session_state(controller.session_view(), active_selection_mode=controller.active_selection_mode)
        if execution.edit_result.ok:
            self._apply_standalone_native_update(execution.native_update)
            self._update_standalone_status()
            self.status_message_requested.emit(f"Mesh Editor part action applied: {normalized}.", False)
            return True
        diagnostic = "; ".join(str(item) for item in tuple(execution.edit_result.diagnostics or ()) if str(item).strip())
        self.status_message_requested.emit(
            f"Mesh Editor part action made no changes: {normalized}{': ' + diagnostic if diagnostic else ''}.",
            False,
        )
        return False

    def _selection_for_part_context(
        self,
        controller: MeshEditorController,
        part_index: int,
    ) -> MeshEditSelection | None:
        try:
            clicked_index = int(part_index)
        except (TypeError, ValueError):
            clicked_index = -1
        if clicked_index < 0:
            return None
        selected_sources = set(controller.session_view().selection.source_indices)
        if clicked_index not in selected_sources:
            result = controller.select(source_indices=(clicked_index,), operation="replace")
            self.update_editor_session_state(
                controller.session_view(),
                active_selection_mode=controller.active_selection_mode,
            )
            self._apply_standalone_native_update(controller.native_update_for_result(result))
            selected_sources = {clicked_index}
        return MeshEditSelection.from_maps(source_indices=selected_sources)

    def _run_standalone_action(self, action: object) -> bool:
        controller = self.standalone_controller
        if controller is None:
            return False
        if self._standalone_action_worker_active():
            self.status_message_requested.emit("Wait for the current Mesh Editor action to finish, or cancel it first.", True)
            return True
        if self._standalone_rebuild_report_worker_active():
            self.status_message_requested.emit("Wait for the current rebuild report to finish, or cancel it first.", True)
            return True
        text = str(getattr(action, "text", "") or getattr(action, "key", "") or "action")
        key = str(getattr(action, "key", "") or "").strip()
        if key in _STANDALONE_NATIVE_TOOL_STATE:
            self.set_active_tool_state(
                mode=str(getattr(action, "mode", "") or ""),
                active_tool_key=key,
            )
        if self._native_editor_action_blocked(str(getattr(action, "command", "") or "")):
            return True
        if self._should_run_standalone_action_worker(action, controller):
            return self._start_standalone_action_worker(action, action_text=text)
        try:
            execution = controller.run_editor_action(action)
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor action failed: {text}: {exc}", True)
            return False
        return self._finish_standalone_action_execution(execution, action_text=text)

    def _finish_standalone_action_execution(self, execution: object, *, action_text: str = "") -> bool:
        controller = self.standalone_controller
        if controller is None:
            return False
        self.update_editor_session_state(controller.session_view(), active_selection_mode=controller.active_selection_mode)
        edit_result = getattr(execution, "edit_result", None)
        native_update = getattr(execution, "native_update", MeshEditorNativeUpdate())
        text = str(action_text or getattr(edit_result, "action", "") or "action")
        if bool(getattr(edit_result, "ok", False)):
            native_host_was_available = self.standalone_native_host is not None
            native_update_has_payload = _native_update_has_payload(native_update)
            preview_started = time.perf_counter()
            preview_updated = self._apply_standalone_native_update(native_update)
            preview_elapsed_ms = (time.perf_counter() - preview_started) * 1000.0
            if native_host_was_available:
                metric_name = "d3d11_update_ms" if preview_updated else "d3d11_update_failed_ms"
            elif native_update_has_payload:
                metric_name = "native_preview_unavailable_ms"
            else:
                metric_name = "native_preview_noop_ms"
            edit_result = _mesh_edit_result_with_metric(edit_result, metric_name, preview_elapsed_ms)
            if isinstance(edit_result, MeshEditResult):
                self.standalone_last_action_result = edit_result
                self.standalone_last_action_metrics = {str(key): float(value) for key, value in dict(edit_result.metrics).items()}
            if native_update_has_payload and not preview_updated:
                return False
            self._update_standalone_status()
            self.status_message_requested.emit(f"Mesh Editor action applied: {text}.", False)
            return True
        diagnostic = "; ".join(str(item) for item in tuple(getattr(edit_result, "diagnostics", ()) or ()) if str(item).strip())
        self.status_message_requested.emit(
            f"Mesh Editor action made no changes: {text}{': ' + diagnostic if diagnostic else ''}.",
            False,
        )
        return False

    def _should_run_standalone_action_worker(self, action: object, controller: MeshEditorController) -> bool:
        if not self._standalone_action_can_run_in_background(action):
            return False
        if bool(getattr(action, "requires_selection", False)):
            try:
                return not controller.session_view().selection.is_empty()
            except Exception:
                return False
        return True

    def _standalone_action_can_run_in_background(self, action: object) -> bool:
        command = str(getattr(action, "command", "") or "").strip().lower()
        return bool(command and command not in {"set_mode", "select"})

    def _standalone_action_command(
        self,
        action: object,
        controller: MeshEditorController,
        *,
        action_text: str = "",
    ) -> MeshEditCommand | None:
        command = str(getattr(action, "command", "") or "").strip().lower()
        if not command or command in {"set_mode", "select"}:
            return None
        params = self._action_params(action)
        mode = str(getattr(action, "mode", "") or "").strip() or None
        return MeshEditCommand(
            action=command,
            selection=None,
            params=params,
            mode=mode,
            label=str(action_text or getattr(action, "text", "") or getattr(action, "key", "") or command),
        )

    @staticmethod
    def _action_params(action: object) -> dict[str, object]:
        try:
            return dict(tuple(getattr(action, "params", ()) or ()))
        except (TypeError, ValueError):
            return {}

    def _apply_standalone_native_update(self, update: MeshEditorNativeUpdate) -> bool:
        host = self.standalone_native_host
        if host is not None:
            if apply_native_update_to_host(host, update):
                if host is getattr(self, "standalone_native_host_frame", None):
                    self.standalone_preview_stack.setCurrentWidget(self.standalone_native_host_frame)
                return True
        if _native_update_has_payload(update) or self._standalone_native_preview_update_active():
            message = "Native D3D11 preview update failed; preview is stale. Reload native preview to resync."
            self.standalone_status_label.setText(message)
            self.status_message_requested.emit(message, True)
            return False
        return True

    def _standalone_native_preview_update_active(self) -> bool:
        return (
            self.standalone_preview_stack.currentWidget() is getattr(self, "standalone_native_host_frame", None)
            or self._standalone_native_process_running()
            or self.standalone_native_package_thread is not None
        )

    def _refresh_standalone_preview(self) -> None:
        controller = self.standalone_controller
        if controller is None:
            self.standalone_preview_stack.setCurrentWidget(self.standalone_preview)
            self.standalone_preview.clear_model("No active edit session.")
            self.standalone_status_label.setText("No active edit session.")
            return
        if self.standalone_compare_mode != "source" and controller.native_editor_mesh_dirty():
            message = "Native D3D11 preview required; Python preview rebuild is disabled while C++ mesh state is dirty."
            self.standalone_preview_stack.setCurrentWidget(self.standalone_preview)
            self.standalone_preview.clear_model(message)
            self.standalone_status_label.setText(message)
            return
        self.standalone_preview_stack.setCurrentWidget(self.standalone_preview)
        prepared = controller.source_preview_data() if self.standalone_compare_mode == "source" else controller.native_preview_data()
        model = SimpleNamespace(meshes=tuple(getattr(prepared, "batches", ()) or ()), vertex_count=getattr(prepared, "vertex_count", 0))
        self.standalone_preview.set_prepared_model(model, prepared)
        view = controller.session_view()
        self._set_standalone_status(view)

    def _set_standalone_compare_mode(self, mode: str) -> None:
        normalized = str(mode or "edited").strip().lower()
        if normalized not in {"edited", "source", "ghost"}:
            normalized = "edited"
        self.standalone_compare_mode = normalized
        if not self.has_active_standalone_session():
            return
        if normalized == "source":
            host = self.standalone_native_host
            setter = getattr(host, "set_display_mode", None)
            package_can_show_source = self.standalone_native_package_has_reference or self.standalone_native_package_compare_mode == "source"
            if (
                callable(setter)
                and package_can_show_source
                and self.standalone_preview_stack.currentWidget() is self.standalone_native_host_frame
                and setter("original_only")
            ):
                self.standalone_status_label.setText("Native D3D11 compare view: source.")
                return
            if self._standalone_native_preview_update_active():
                if self.standalone_native_package_thread is None and self.start_standalone_native_preview_async(reset_view=False):
                    self.standalone_status_label.setText("Preparing native D3D11 source compare preview...")
                else:
                    self.standalone_status_label.setText("Native D3D11 source compare preview pending.")
                return
            self._refresh_standalone_preview()
            return
        if normalized == "ghost" and self._standalone_native_preview_update_active() and not self.standalone_native_package_has_reference:
            if self.standalone_native_package_thread is None and self.start_standalone_native_preview_async(reset_view=False):
                self.standalone_status_label.setText("Preparing native D3D11 ghost compare preview...")
            else:
                self.standalone_status_label.setText("Native D3D11 ghost compare preview pending.")
            return
        host = self.standalone_native_host
        setter = getattr(host, "set_display_mode", None)
        if callable(setter) and self.standalone_preview_stack.currentWidget() is self.standalone_native_host_frame:
            display_mode = "overlay" if normalized == "ghost" else "replacement_only"
            if setter(display_mode):
                self.standalone_status_label.setText(f"Native D3D11 compare view: {normalized}.")
                return
            if self._standalone_native_preview_update_active():
                message = "Native D3D11 compare view update failed; preview is stale. Reload native preview to resync."
                self.standalone_status_label.setText(message)
                self.status_message_requested.emit(message, True)
                return
        self._refresh_standalone_preview()

    def _update_standalone_status(self) -> None:
        if self.standalone_controller is None:
            return
        self._set_standalone_status(self.standalone_controller.session_view())

    def _set_standalone_status(self, view: MeshEditSessionView) -> None:
        if not self._native_mesh_editor_available():
            self.standalone_status_label.setText(
                "Native Mesh Editor unavailable: C++ mesh core missing. "
                f"Mesh edit tools disabled. Session: {view.session_id} | Mode: {view.mode}"
            )
            return
        self.standalone_status_label.setText(
            f"Session: {view.session_id} | Mode: {view.mode} | Revision: {view.revision} | Undo: {view.undo_count} | Redo: {view.redo_count}"
        )

    def _sync_standalone_compare_combo(self) -> None:
        combo = getattr(self.standalone_workspace, "compare_mode_combo", None)
        if combo is None:
            return
        previous = combo.blockSignals(True)
        try:
            combo.setCurrentText("Edited")
        finally:
            combo.blockSignals(previous)

    def open_selected_texture_in_editor(self) -> bool:
        return self._open_selected_texture_in_editor_for_controller(
            self.standalone_controller,
            missing_controller_message="Open a standalone Mesh Editor session before opening a texture.",
        )

    def _open_selected_texture_in_editor_for_controller(
        self,
        controller: MeshEditorController | None,
        *,
        missing_controller_message: str = "Open a Mesh Editor session before opening a texture.",
    ) -> bool:
        if controller is None:
            self.status_message_requested.emit(missing_controller_message, True)
            return False
        target = controller.texture_edit_target()
        if target is None:
            self.status_message_requested.emit("Selected mesh part has no texture to open.", True)
            return False
        source_path = Path(target.texture).expanduser()
        if not source_path.exists():
            if self._start_archive_texture_source_resolution(target, controller=controller):
                return True
            self.status_message_requested.emit(f"Selected Mesh Editor texture is not a local file yet: {target.texture}", True)
            return False
        self._open_texture_target_source(target, source_path.resolve(), controller=controller)
        return True

    def _open_texture_target_source(
        self,
        target: object,
        source_path: Path,
        *,
        archive_path: str = "",
        controller: MeshEditorController | None = None,
    ) -> None:
        controller = controller or self.standalone_controller
        if controller is None:
            return
        resolved = Path(source_path).expanduser().resolve()
        texture = str(getattr(target, "texture", "") or "")
        binding = TextureEditorSourceBinding(
            launch_origin="mesh_editor",
            display_name=str(getattr(target, "display_name", "") or resolved.name),
            source_path=str(resolved),
            source_identity_path=f"{controller.active_session_id}:{getattr(target, 'submesh_index', -1)}:{texture}",
            relative_path=archive_path or texture,
            archive_relative_path=archive_path or texture,
            original_dds_path=str(resolved) if resolved.suffix.lower() == ".dds" else "",
            texture_type="mesh_material",
            semantic_subtype=str(getattr(target, "material", "") or getattr(target, "source_texture_set_key", "") or "unknown"),
        )
        self.open_texture_source_requested.emit(str(resolved), binding)
        self.status_message_requested.emit(f"Opening Mesh Editor texture in Texture Editor: {resolved.name}", False)

    def apply_texture_editor_dds_preview(self, dds_path_text: str, binding: object) -> bool:
        controller = self.standalone_controller
        if controller is None or not isinstance(binding, TextureEditorSourceBinding):
            return False
        if str(binding.launch_origin or "") != "mesh_editor" or str(binding.texture_type or "") != "mesh_material":
            return False
        session_id, submesh_index = _mesh_editor_texture_binding_target(binding.source_identity_path)
        if session_id and session_id != controller.active_session_id:
            return False
        if submesh_index < 0:
            return False
        try:
            dds_path = Path(dds_path_text).expanduser()
        except OSError:
            self.status_message_requested.emit(f"Mesh Editor texture preview path is invalid: {dds_path_text}", True)
            return False
        if not dds_path.is_file():
            self.status_message_requested.emit(f"Mesh Editor texture preview DDS not found: {dds_path}", True)
            return False
        resolved = dds_path.resolve()
        self.standalone_texture_preview_overrides[int(submesh_index)] = str(resolved)
        refresh_started = self.start_standalone_native_preview_async(reset_view=False)
        if refresh_started:
            self.status_message_requested.emit(f"Refreshing Mesh Editor D3D11 texture preview: {resolved.name}", False)
        else:
            self.status_message_requested.emit(f"Mesh Editor texture preview staged: {resolved.name}", False)
        return True

    def _emit_target(self, signal: Signal) -> None:
        target = self._current_target_entry()
        if target is None:
            self.status_message_requested.emit("Select a supported archive mesh first.", True)
            return
        signal.emit(target)

    def _emit_open_archive_target(self) -> None:
        target = self._current_target_entry()
        if target is None:
            return
        self.open_archive_target_requested.emit(target)


def _native_update_has_payload(update: object) -> bool:
    if not isinstance(update, MeshEditorNativeUpdate):
        return False
    return bool(
        update.vertex_groups
        or update.triangle_groups
        or update.triangle_source_submesh_indices
        or update.selection_groups
        or update.refresh_selection
        or update.material_override_groups
        or update.replace_all_triangles
    )


def _mesh_edit_result_with_metric(result: object, key: str, elapsed_ms: float) -> object:
    if not isinstance(result, MeshEditResult):
        return result
    metrics: dict[str, float] = {}
    for raw_key, raw_value in dict(result.metrics or {}).items():
        try:
            metrics[str(raw_key)] = float(raw_value)
        except (TypeError, ValueError, OverflowError):
            continue
    metrics[str(key)] = max(0.0, float(elapsed_ms))
    return replace(result, metrics=metrics)


def _rebuild_report_json_payload(report: object) -> dict[str, object]:
    if is_dataclass(report):
        payload = asdict(report)
    elif isinstance(report, Mapping):
        payload = dict(report)
    else:
        payload = {
            key: getattr(report, key)
            for key in (
                "mesh_format",
                "source_asset_hash",
                "rebuilt_asset_hash",
                "source_size",
                "rebuilt_size",
                "parse_confidence",
                "validation_status",
                "byte_identical",
                "changed_byte_ranges",
                "edited_lods",
                "edited_submeshes",
                "changed_channels",
                "recomputed_fields",
                "warnings",
                "developer_overrides",
                "edit_operations",
                "output_path",
            )
            if hasattr(report, key)
        }
    payload["changed_range_count"] = int(
        getattr(report, "changed_range_count", len(tuple(payload.get("changed_byte_ranges", ()) or ()))) or 0
    )
    return {str(key): _json_safe_report_value(value) for key, value in payload.items()}


def _validation_report_json_payload(report: object) -> dict[str, object]:
    if is_dataclass(report):
        payload = asdict(report)
    elif isinstance(report, Mapping):
        payload = dict(report)
    else:
        payload = {
            key: getattr(report, key)
            for key in (
                "mesh_format",
                "submesh_count",
                "vertex_count",
                "face_count",
                "issues",
                "parse_confidence",
                "source_asset_hash",
                "no_op_roundtrip_status",
                "no_op_byte_identical",
                "no_op_unexpected_differences",
            )
            if hasattr(report, key)
        }
    blockers = tuple(getattr(report, "blockers", ()) or ())
    warnings = tuple(getattr(report, "warnings", ()) or ())
    payload["ok"] = bool(getattr(report, "ok", not blockers))
    payload["blocker_count"] = len(blockers)
    payload["warning_count"] = len(warnings)
    result = {str(key): _json_safe_report_value(value) for key, value in payload.items()}
    issues = result.get("issues")
    if isinstance(issues, list):
        for issue in issues:
            if isinstance(issue, dict) and "severity" in issue:
                issue["severity"] = _public_validation_severity(issue.get("severity"))
                issue.setdefault("can_continue", issue["severity"] not in {"error", "fatal"})
                issue.setdefault("expected", None)
                issue.setdefault("actual", None)
                issue.setdefault("lod_index", -1)
                issue.setdefault("submesh_index", -1)
    return result


def _public_validation_severity(severity: object) -> str:
    raw = str(severity or "").strip().lower()
    if raw == "blocker":
        return "error"
    return raw if raw in {"info", "warning", "error", "fatal"} else "error"


def _json_safe_report_value(value: object) -> object:
    if is_dataclass(value):
        return _json_safe_report_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_safe_report_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe_report_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _mesh_editor_texture_binding_target(value: object) -> tuple[str, int]:
    parts = str(value or "").split(":", 2)
    if len(parts) < 2:
        return "", -1
    try:
        submesh_index = int(parts[1])
    except (TypeError, ValueError):
        submesh_index = -1
    return str(parts[0] or ""), submesh_index


def _mesh_editor_tab_index(tabs: QTabWidget, title: str) -> int:
    normalized = str(title or "").strip().lower()
    for index in range(tabs.count()):
        if tabs.tabText(index).strip().lower() == normalized:
            return index
    return -1
