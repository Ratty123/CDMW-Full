from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPushButton, QTabWidget, QWidget

from cdmw.ui.mesh_editor.dotnet_update_queue import DotNetRevisionUpdateQueue
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace


class MeshEditorTabShellRuntimeMixin:
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
        self.standalone_action_thread: _tab.QThread | None = None
        self.standalone_action_worker: _tab.MeshEditCommandWorker | None = None
        self.standalone_action_progress: _tab.QProgressDialog | None = None
        self.standalone_action_request_id = 0
        self.standalone_action_text = ""
        self.standalone_action_controller: _tab.MeshEditorController | None = None
        self.standalone_action_dotnet_command = ""
        self.standalone_action_dotnet_request_payload: dict[str, object] | None = None
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
        self.standalone_dotnet_scene_thread: _tab.QThread | None = None
        self.standalone_dotnet_scene_worker: _tab.MeshDotNetSceneFrameWorker | None = None
        self.standalone_dotnet_scene_request_id = 0
        self.standalone_dotnet_scene_generation = 0
        self.standalone_dotnet_scene_acknowledged_generation = 0
        self.standalone_dotnet_scene_pending: dict[str, object] | None = None
        self.standalone_dotnet_scene_acknowledged: dict[str, object] | None = None
        self.standalone_dotnet_scene_candidate: object | None = None
        self.standalone_dotnet_scene_frame: object | None = None
        self.standalone_dotnet_scene_queued: dict[str, object] | None = None
        self.standalone_dotnet_scene_desired: dict[str, object] = {
            "comparison_mode": "replacement_only",
            "interaction_mode": "placement",
            "gizmo_tool": "move",
        }
        self.standalone_dotnet_presentation_request_id = 0
        self.standalone_dotnet_presentation_generation = 0
        self.standalone_dotnet_camera_command_generation = 0
        self.standalone_dotnet_presentation_pending: dict[str, object] | None = None
        self.standalone_dotnet_presentation_queued = False
        self.standalone_dotnet_presentation_desired: dict[str, object] = {}
        self.standalone_dotnet_presentation_acknowledged: dict[str, object] | None = None
        self.standalone_dotnet_texture_region_request_id = 0
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
        self.standalone_dotnet_pending_textured_view = False
        self.standalone_dotnet_pending_textured_view_mode = "textured"
        self.standalone_dotnet_pending_textured_view_uses_presentation = False
        self.standalone_dotnet_material_ready_flush_token = (0, 0)
        self.standalone_dotnet_pending_clone_material_model: object | None = None
        self.standalone_dotnet_pending_reference_material_model: object | None = None
        self.standalone_dotnet_material_update_thread: _tab.QThread | None = None
        self.standalone_dotnet_material_update_worker: _tab.MeshDotNetMaterialUpdateWorker | None = None
        self.standalone_dotnet_material_update_pending: tuple[object, tuple[dict[str, object], ...]] | None = None
        self.standalone_dotnet_material_update_active_resources: tuple[dict[str, object], ...] = ()
        self.standalone_dotnet_material_update_cancelled = False
        self.standalone_dotnet_capture_request_id = 0
        self.standalone_dotnet_viewport_display_request_id = 0
        self.standalone_dotnet_capture_callbacks: dict[int, tuple[object, object, object]] = {}
        self.standalone_dotnet_provenance_verified = False
        self.standalone_dotnet_lifecycle_session_id = ""
        self.standalone_dotnet_process_generation = 0
        self.standalone_dotnet_morph_change_id = ""
        self.standalone_dotnet_morph_sent_state_revision = -1
        self.standalone_dotnet_morph_ack_state_revision = -1
        self.standalone_dotnet_morph_sent_change_id = ""
        self.standalone_dotnet_morph_sent_request_id = 0
        self.standalone_dotnet_lifecycle_counts: dict[str, int] = {
            "initial_package_build_count": 0,
            "package_build_count": 0,
            "renderer_process_start_count": 0,
            "process_restart_count": 0,
            "full_reload_count": 0,
            "material_state_update_count": 0,
            "material_state_applied_count": 0,
            "material_state_failed_count": 0,
            "material_state_deduplicated_count": 0,
            "material_compile_start_count": 0,
            "material_compile_completed_count": 0,
            "material_compile_failed_count": 0,
            "material_compile_replaced_count": 0,
            "material_compile_stale_count": 0,
        }
        self._initialize_runtime_objects()

    def _initialize_runtime_objects(self) -> None:
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
        self._embedded_restore_control_widget: QWidget | None = None
        self.standalone_native_status_timer = QTimer(self)
        self.standalone_native_status_timer.setInterval(250)
        self.standalone_native_status_timer.timeout.connect(self._poll_standalone_native_preview_status)
        self.standalone_animation_timer = QTimer(self)
        self.standalone_animation_timer.setInterval(33)
        self.standalone_animation_timer.timeout.connect(self._tick_standalone_animation_playback)
        self.standalone_animation_last_tick = 0.0
        self._wired_standalone_native_host_ids: set[int] = set()
        self._wired_shared_dotnet_controller_ids: set[int] = set()
