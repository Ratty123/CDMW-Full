from __future__ import annotations

from typing import Mapping, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.shell.settings_bridge import read_bool_setting
from cdmw.ui.mesh_editor.dotnet_update_queue import DotNetRevisionUpdateQueue
from cdmw.ui.mesh_editor.resident_texture_update_queue import ResidentTextureRegionUpdateQueue
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace

_STANDALONE_NATIVE_TOOL_STATE: dict[str, tuple[str, str, str]] = {
    "transform_move": ("move", "selection", "edit"),
    "brush_grab": ("grab", "selection", "sculpt"),
    "brush_smooth": ("smooth", "selection", "sculpt"),
    "brush_inflate": ("inflate", "selection", "sculpt"),
    "brush_pinch": ("pinch", "selection", "sculpt"),
}

from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_support import _mesh_editor_tab_index


class MeshEditorTabShellMixin:
    def _initialize_runtime_state(
        self,
        *,
        get_archive_texture_entries_by_normalized_path: object,
        get_archive_texture_entries_by_basename: object,
    ) -> None:
        self.current_request: Optional[_tab.MeshEditorSessionRequest] = None
        self.current_archive_selection: Optional[_tab.ArchiveEntry] = None
        self.current_edit_mode = "object"
        self.current_selection_mode = "vertex"
        self.current_tool_action_key = ""
        self.current_selection_empty = True
        self.current_undo_count = 0
        self.current_redo_count = 0
        self.standalone_controller: _tab.MeshEditorController | None = None
        self.standalone_native_editor_available: bool | None = None
        self.standalone_file_load_thread: _tab.QThread | None = None
        self.standalone_file_load_worker: _tab.MeshFileSessionLoadWorker | None = None
        self.standalone_file_load_target_entry: object | None = None
        self.standalone_file_load_source_skeleton: object | None = None
        self.standalone_file_load_request_id = 0
        self.standalone_texture_source_thread: _tab.QThread | None = None
        self.standalone_texture_source_worker: _tab.MeshTextureSourceResolveWorker | None = None
        self.standalone_texture_source_request_id = 0
        self.standalone_texture_source_target: object | None = None
        self.standalone_texture_source_controller: _tab.MeshEditorController | None = None
        self.get_archive_texture_entries_by_normalized_path = get_archive_texture_entries_by_normalized_path
        self.get_archive_texture_entries_by_basename = get_archive_texture_entries_by_basename
        self.standalone_native_host: object | None = None
        self.standalone_native_process: _tab.QProcess | None = None
        self.standalone_native_stdout_tail = ""
        self.standalone_native_stderr_tail = ""
        self.standalone_native_package_thread: _tab.QThread | None = None
        self.standalone_native_package_worker: _tab.MeshNativePreviewPackageWorker | None = None
        self.standalone_native_package_request_id = 0
        self.standalone_action_thread: _tab.QThread | None = None
        self.standalone_action_worker: _tab.MeshEditCommandWorker | None = None
        self.standalone_action_progress: _tab.QProgressDialog | None = None
        self.standalone_action_request_id = 0
        self.standalone_action_text = ""
        self.standalone_action_controller: _tab.MeshEditorController | None = None
        self.standalone_action_dotnet_command = ""
        self.standalone_rebuild_report_thread: _tab.QThread | None = None
        self.standalone_rebuild_report_worker: _tab.MeshRebuildReportWorker | None = None
        self.standalone_rebuild_report_progress: _tab.QProgressDialog | None = None
        self.standalone_rebuild_report_request_id = 0
        self.standalone_report_write_thread: _tab.QThread | None = None
        self.standalone_report_write_worker: _tab.MeshReportWriteWorker | None = None
        self.standalone_report_write_request_id = 0
        self.standalone_validation_thread: _tab.QThread | None = None
        self.standalone_validation_worker: _tab.MeshExportValidationWorker | None = None
        self.standalone_validation_request_id = 0
        self.standalone_dotnet_package_thread: _tab.QThread | None = None
        self.standalone_dotnet_package_worker: _tab.MeshDotNetExperimentPackageWorker | None = None
        self.standalone_dotnet_package_request_id = 0
        self.standalone_dotnet_import_thread: _tab.QThread | None = None
        self.standalone_dotnet_import_worker: _tab.MeshDotNetExperimentOutputImportWorker | None = None
        self.standalone_dotnet_import_request_id = 0
        self.standalone_editable_export_thread: _tab.QThread | None = None
        self.standalone_editable_export_worker: _tab.MeshEditablePackageExportWorker | None = None
        self.standalone_editable_export_request_id = 0
        self.standalone_editable_import_thread: _tab.QThread | None = None
        self.standalone_editable_import_worker: _tab.MeshEditablePackageImportWorker | None = None
        self.standalone_editable_import_request_id = 0
        self.standalone_dotnet_editor_process: _tab.QProcess | None = None
        self.standalone_dotnet_experiment_package: _tab.MeshDotNetExperimentPackage | None = None
        self.standalone_dotnet_status_payload: dict[str, object] = {}
        self.standalone_dotnet_target_controller: _tab.MeshEditorController | None = None
        self.standalone_dotnet_target_embedded = False
        self.standalone_dotnet_embedded_state = "closed"
        self.standalone_dotnet_embedded_exit_finalized = False
        self.standalone_dotnet_exit_pending = False
        self.standalone_dotnet_deactivate_acknowledged = False
        self.standalone_dotnet_protocol_stdout = ""
        self.standalone_dotnet_protocol_events: list[dict[str, object]] = []
        self.standalone_dotnet_capabilities: set[str] = set()
        self.standalone_dotnet_material_generation = 0
        self.standalone_dotnet_applied_material_generation = 0
        self.standalone_dotnet_completed_material_generation = 0
        self.standalone_dotnet_material_signature = ""
        self.standalone_dotnet_lifecycle_session_id = ""
        self.standalone_dotnet_lifecycle_counts: dict[str, int] = {
            "initial_package_build_count": 0,
            "package_build_count": 0,
            "renderer_process_start_count": 0,
            "process_restart_count": 0,
            "full_reload_count": 0,
            "material_state_update_count": 0,
            "material_state_applied_count": 0,
            "material_state_failed_count": 0,
        }
        self._initialize_dotnet_material_parameter_state()
        self.standalone_dotnet_update_queue = DotNetRevisionUpdateQueue(self._send_dotnet_protocol_message)
        self._initialize_texture_region_queue()
        self.standalone_dotnet_update_ack_timer = QTimer(self)
        self.standalone_dotnet_update_ack_timer.setSingleShot(True)
        self.standalone_dotnet_update_ack_timer.timeout.connect(self._handle_dotnet_update_ack_timeout)
        self.standalone_dotnet_stdout_tail = ""
        self.standalone_dotnet_stderr_tail = ""
        self.standalone_dotnet_last_program = ""
        self.standalone_dotnet_ready_timer = QTimer(self)
        self.standalone_dotnet_ready_timer.setSingleShot(True)
        self.standalone_dotnet_ready_timer.timeout.connect(self._handle_dotnet_ready_timeout)
        self.standalone_dotnet_deactivate_timer = QTimer(self)
        self.standalone_dotnet_deactivate_timer.setSingleShot(True)
        self.standalone_dotnet_deactivate_timer.timeout.connect(self._handle_dotnet_deactivate_timeout)
        self.standalone_dotnet_last_arguments: list[str] = []
        self.standalone_dotnet_last_working_directory = ""
        self.standalone_dotnet_last_parent_hwnd = 0
        self.embedded_dotnet_editor_button: QPushButton | None = None
        self.standalone_last_export_validation_report: object | None = None
        self.standalone_last_rebuild_report: object | None = None
        self.standalone_last_rebuilt_asset_path: _tab.Path | None = None
        self.standalone_last_action_result: _tab.MeshEditResult | None = None
        self.standalone_last_action_metrics: dict[str, float] = {}
        self.standalone_native_package_reset_view = True
        self.standalone_mesh_label = ""
        self.standalone_source_skeleton: object | None = None
        self.standalone_compare_mode = "edited"
        self.standalone_texture_preview_overrides: dict[int, str] = {}
        self.standalone_native_package_dir: _tab.Path | None = None
        self.standalone_native_status_file: _tab.Path | None = None
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
        self.standalone_live_stroke_dispatcher: _tab.MeshLiveStrokeDispatcher | None = None
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

    def _initialize_texture_region_queue(self) -> None:
        self.standalone_texture_region_queue = ResidentTextureRegionUpdateQueue(
            self._send_dotnet_protocol_message,
            parent=self,
        )
        self.standalone_texture_region_queue.update_applied.connect(
            self._handle_texture_region_queue_applied
        )
        self.standalone_texture_region_queue.update_failed.connect(
            self._handle_texture_region_queue_failed
        )

    def _initialize_dotnet_material_parameter_state(self) -> None:
        self.standalone_dotnet_material_parameter_generation = 0
        self.standalone_dotnet_sent_material_parameter_generation = 0
        self.standalone_dotnet_applied_material_parameter_generation = 0
        self.standalone_dotnet_completed_material_parameter_generation = 0
        self.standalone_dotnet_material_parameter_revision = 0
        self.standalone_dotnet_material_parameter_session_id = ""
        self.standalone_dotnet_pending_material_parameter_payload: dict[str, object] | None = None
        self.standalone_dotnet_sent_material_parameter_payload: dict[str, object] | None = None
        self.standalone_dotnet_sent_material_resource_payload: dict[str, object] | None = None
        self.standalone_dotnet_lifecycle_counts.update({
            "material_parameter_update_count": 0,
            "material_parameter_applied_count": 0,
            "material_parameter_failed_count": 0,
        })
        self.standalone_dotnet_material_parameter_timer = QTimer(self)
        self.standalone_dotnet_material_parameter_timer.setSingleShot(True)
        self.standalone_dotnet_material_parameter_timer.timeout.connect(
            self._flush_dotnet_material_parameter_update
        )

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
    def _dotnet_resident_texture_region_updates_supported(self) -> bool:
        return "resident_texture_region_updates_v1" in self.standalone_dotnet_capabilities
    def _dotnet_resident_material_updates_supported(self) -> bool:
        return "resident_material_updates_v2" in self.standalone_dotnet_capabilities
    def _dotnet_resident_material_parameter_updates_supported(self) -> bool:
        return "resident_material_parameter_updates_v1" in self.standalone_dotnet_capabilities
    def _dotnet_texture_updates_idle(self) -> bool:
        return self.standalone_texture_region_queue.idle()
    def _handle_texture_region_queue_applied(self, payload: Mapping[str, object]) -> None:
        self.standalone_dotnet_lifecycle_counts["texture_region_applied_count"] = (
            int(self.standalone_dotnet_lifecycle_counts.get("texture_region_applied_count", 0)) + 1
        )
        self._record_mesh_dotnet_event(
            "mesh_dotnet_texture_region_applied",
            resource_id=str(payload.get("resource_id", "") or ""),
            generation=int(payload.get("generation", 0) or 0),
            texture_revision=int(payload.get("texture_revision", 0) or 0),
        )
    def _handle_texture_region_queue_failed(self, payload: Mapping[str, object]) -> None:
        self.standalone_dotnet_lifecycle_counts["texture_region_failed_count"] = (
            int(self.standalone_dotnet_lifecycle_counts.get("texture_region_failed_count", 0)) + 1
        )
        message = str(payload.get("message", payload.get("reason", "Texture region update failed.")) or "Texture region update failed.")
        self._set_dotnet_status(
            f"Mesh texture region update failed; keeping the last valid resource: {message}",
            error=True,
        )
    def iter_shutdown_workers(self) -> tuple[tuple[str, _tab.QThread | None, object | None], ...]:
        return (
            ("standalone_file_load", self.standalone_file_load_thread, self.standalone_file_load_worker),
            ("standalone_texture_source", self.standalone_texture_source_thread, self.standalone_texture_source_worker),
            ("standalone_native_package", self.standalone_native_package_thread, self.standalone_native_package_worker),
            ("standalone_mesh_action", self.standalone_action_thread, self.standalone_action_worker),
            ("standalone_validation", self.standalone_validation_thread, self.standalone_validation_worker),
            ("standalone_rebuild_report", self.standalone_rebuild_report_thread, self.standalone_rebuild_report_worker),
            ("standalone_report_write", self.standalone_report_write_thread, self.standalone_report_write_worker),
            ("standalone_dotnet_package", self.standalone_dotnet_package_thread, self.standalone_dotnet_package_worker),
            ("standalone_dotnet_import", self.standalone_dotnet_import_thread, self.standalone_dotnet_import_worker),
            ("standalone_editable_export", self.standalone_editable_export_thread, self.standalone_editable_export_worker),
            ("standalone_editable_import", self.standalone_editable_import_thread, self.standalone_editable_import_worker),
        )
    def request_shutdown(self) -> None:
        self.close_standalone_session()
        self.standalone_texture_region_queue.shutdown()
        dispatcher = self.standalone_live_stroke_dispatcher
        if dispatcher is not None:
            dispatcher.request_stop()
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
        setattr(builder, "_mesh_editor_embedded_set_part_selection", self._set_embedded_part_selection)
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
            was_active = bool(getattr(builder, "_mesh_editor_embedded_dotnet_active", False))
            setattr(builder, "_mesh_editor_embedded_dotnet_state", normalized_state)
            setattr(builder, "_mesh_editor_embedded_dotnet_active", bool(active))
            refresh_controls = getattr(builder, "_refresh_material_authority_live_control_states", None)
            if callable(refresh_controls):
                refresh_controls()
            replay_parameters = getattr(builder, "_replay_resident_material_authority_parameters", None)
            capability = getattr(builder, "_mesh_editor_embedded_resident_material_parameters_supported", False)
            parameter_updates_supported = bool(capability()) if callable(capability) else bool(capability)
            if normalized_state == "ready" and active and not was_active and parameter_updates_supported and callable(replay_parameters):
                replay_parameters()
    def _wire_embedded_dotnet_button(self, builder: QWidget) -> None:
        dotnet_executable = self._dotnet_editor_executable_path(log=False)
        dotnet_available = dotnet_executable is not None and dotnet_executable.is_file()
        dotnet_enabled = read_bool_setting(
            self.settings,
            "mesh_editor/use_embedded_dotnet_viewport",
            True,
        )
        setattr(builder, "_mesh_editor_embedded_start_dotnet", self._start_embedded_dotnet_editor_requested)
        setattr(builder, "_mesh_editor_embedded_stop_dotnet", self._request_embedded_dotnet_editor_close)
        setattr(builder, "_mesh_editor_embedded_send_native_update", self._send_embedded_dotnet_native_update)
        setattr(builder, "_mesh_editor_embedded_apply_material_parameters", self.apply_resident_material_parameters)
        setattr(builder, "_mesh_editor_embedded_apply_material_resources", self.apply_resident_material_resources)
        setattr(builder, "_mesh_editor_embedded_resident_material_resources_supported", self._dotnet_resident_material_updates_supported)
        setattr(builder, "_mesh_editor_embedded_resident_material_parameters_supported", self._dotnet_resident_material_parameter_updates_supported)
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
        except (AttributeError, RuntimeError, TypeError, ValueError):
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
    def _standalone_preview_mesh_snapshot(self) -> _tab.ParsedMesh:
        controller = self.standalone_controller
        if controller is None:
            raise RuntimeError("Mesh Editor has no standalone edit session.")
        mesh = controller.base_mesh(clone=True) if self.standalone_compare_mode == "source" else controller.pose_preview_mesh()
        if self.standalone_compare_mode != "source":
            self._apply_texture_preview_overrides(mesh)
        return mesh
    def _standalone_reference_mesh_snapshot(self) -> _tab.ParsedMesh | None:
        controller = self.standalone_controller
        if controller is None or self.standalone_compare_mode != "ghost":
            return None
        return controller.base_mesh(clone=True)
    def _standalone_pose_native_preview_context(
        self,
    ) -> tuple[_tab.ParsedMesh, object, Mapping[int, tuple[float, float, float]]] | None:
        controller = self.standalone_controller
        if (
            controller is None
            or self.standalone_compare_mode in {"source", "ghost"}
            or self.standalone_texture_preview_overrides
        ):
            return None
        return controller.pose_preview_native_context()
    def _apply_texture_preview_overrides(self, mesh: _tab.ParsedMesh) -> None:
        if not self.standalone_texture_preview_overrides:
            return
        submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
        for submesh_index, texture_path in tuple(self.standalone_texture_preview_overrides.items()):
            if 0 <= int(submesh_index) < len(submeshes):
                submeshes[int(submesh_index)].texture = str(texture_path)
