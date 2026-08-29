from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPushButton, QTabWidget, QWidget

from cdmw.domain.mesh import MeshPanelSnapshot
from cdmw.services.mesh_edit_session_state import MeshEditSessionMachine
from cdmw.services.mesh_material_publication import MaterialPublicationCoordinator
from cdmw.ui.mesh_editor.dotnet_update_queue import DotNetRevisionUpdateQueue
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace


class MeshEditorTabShellRuntimeMixin:
    def _initialize_runtime_state(
        self,
        *,
        get_archive_texture_entries_by_normalized_path: object,
        get_archive_texture_entries_by_basename: object,
        get_archive_sidecar_entries_by_texture_path: object,
        get_archive_sidecar_entries_by_texture_basename: object,
        ensure_archive_texture_indexes: object = None,
    ) -> None:
        self._initialize_mesh_editor_ui_state()
        self.current_request: Optional[_tab.MeshEditorSessionRequest] = None
        self.current_archive_selection: Optional[_tab.ArchiveEntry] = None
        self.current_edit_mode = "object"
        self.current_selection_mode = "brush"
        self.current_element_type = "vertex"
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
        self.archive_session_load_thread: _tab.QThread | None = None
        self.archive_session_load_worker: _tab.MeshArchiveSessionLoadWorker | None = None
        self.archive_session_load_request_id = 0
        self.archive_session_load_entry: _tab.ArchiveEntry | None = None
        self.archive_session_load_material_model: object | None = None
        self.standalone_archive_material_preview_model: object | None = None
        self.archive_material_context_companion_entry: _tab.ArchiveEntry | None = None
        self.archive_material_context_package_path = ""
        self.archive_material_context_package_lease: object | None = None
        self.archive_material_context_thread: _tab.QThread | None = None
        self.archive_material_context_worker: _tab.MeshArchiveMaterialContextWorker | None = None
        self.archive_material_context_request_id = 0
        self.archive_material_context_pending = False
        # The shell's deferred texture-lookup build, and the wait state used
        # while material context resolution holds for it. See
        # _wait_for_archive_texture_indexes for why resolving without the
        # lookup is worse than waiting.
        self.ensure_archive_texture_indexes = ensure_archive_texture_indexes
        self.archive_texture_index_wait_entry: _tab.ArchiveEntry | None = None
        self.archive_texture_index_wait_attempts = 0
        self.archive_texture_index_wait_timer = QTimer(self)
        self.archive_texture_index_wait_timer.setSingleShot(True)
        self.archive_texture_index_wait_timer.timeout.connect(
            self._retry_archive_material_context_after_index_wait
        )
        self.get_archive_texture_entries_by_normalized_path = get_archive_texture_entries_by_normalized_path
        self.get_archive_texture_entries_by_basename = get_archive_texture_entries_by_basename
        self.get_archive_sidecar_entries_by_texture_path = get_archive_sidecar_entries_by_texture_path
        self.get_archive_sidecar_entries_by_texture_basename = get_archive_sidecar_entries_by_texture_basename
        self.standalone_native_host: object | None = None
        self.standalone_native_process: _tab.QProcess | None = None
        self.standalone_native_stdout_tail = ""
        self.standalone_native_stderr_tail = ""
        self.standalone_action_thread: _tab.QThread | None = None
        self.standalone_action_worker: _tab.MeshEditCommandWorker | None = None
        self.standalone_action_progress: _tab.QProgressDialog | None = None
        self.standalone_action_request_id = 0
        self.standalone_action_finished_request_id = 0  # see _handle_standalone_action_progress
        # Which Edit Mesh session the in-flight command belongs to. The request
        # id alone only says "newest command"; it cannot tell that the session
        # the command was issued against has since been finished, cancelled, or
        # lost to a renderer restart.
        self.standalone_action_edit_session_generation = -1
        self.standalone_action_text = ""
        self.standalone_action_controller: _tab.MeshEditorController | None = None
        self.standalone_action_dotnet_command = ""
        self.standalone_action_dotnet_request_payload: dict[str, object] | None = None
        self.standalone_rebuild_report_thread: _tab.QThread | None = None
        self.standalone_rebuild_report_worker: _tab.MeshRebuildReportWorker | None = None
        self.standalone_rebuild_report_progress: _tab.QProgressDialog | None = None
        self.standalone_rebuild_report_request_id = 0
        self.standalone_output_thread: _tab.QThread | None = None
        self.standalone_output_worker: object | None = None
        self.standalone_output_progress: object | None = None
        self.standalone_output_request_id = 0
        self.standalone_output_kind = ""
        self.standalone_pending_overlay_apply: tuple[object, object] | None = None
        self.standalone_report_write_thread: _tab.QThread | None = None
        self.standalone_report_write_worker: _tab.MeshReportWriteWorker | None = None
        self.standalone_report_write_request_id = 0
        self.standalone_validation_thread: _tab.QThread | None = None
        self.standalone_validation_worker: _tab.MeshExportValidationWorker | None = None
        self.standalone_validation_request_id = 0
        self._initialize_dotnet_runtime_state()
        self._initialize_runtime_objects()

    def _initialize_dotnet_runtime_state(self) -> None:
        """The resident .NET helper's protocol, scene, material, and lifecycle state."""
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
        # A camera rides exactly the publish that follows its own command and is
        # then dropped, so a later republish of unrelated presentation state
        # cannot move the viewport.
        self.standalone_dotnet_presentation_camera_pending = False
        self.standalone_dotnet_presentation_acknowledged: dict[str, object] | None = None
        # The presentation content the helper is known to be holding. A publish
        # whose content matches this one would re-apply what is already on
        # screen, so it is skipped; see _publish_dotnet_presentation_state.
        self.standalone_dotnet_presentation_published_content: dict[str, object] | None = None
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
        # Where the Edit Mesh session is, as one explicit state rather than a
        # reading of worker timing, pending dictionaries, and status text.
        self.standalone_dotnet_edit_session = MeshEditSessionMachine()
        # A Finish Edit Mesh refused for "busy" retries itself when the worker
        # drains, instead of requiring the reader to click the button again.
        self.standalone_dotnet_finish_retry_pending = False
        self.standalone_dotnet_finish_scene_pending: dict[str, object] | None = None
        self.standalone_dotnet_protocol_stdout = ""
        self.standalone_dotnet_protocol_events: list[dict[str, object]] = []
        self.standalone_dotnet_capabilities: set[str] = set()
        self.standalone_dotnet_material_generation = 0
        self.standalone_dotnet_applied_material_generation = 0
        self.standalone_dotnet_completed_material_generation = 0
        self.standalone_dotnet_material_signature = ""
        self.standalone_dotnet_material_role_by_generation: dict[
            int, str | tuple[str, ...]
        ] = {}
        self.standalone_dotnet_material_input_signature_by_generation: dict[int, str] = {}
        self.standalone_dotnet_material_generation_by_role: dict[str, int] = {}
        self.standalone_dotnet_completed_material_generation_by_role: dict[str, int] = {}
        self.standalone_dotnet_applied_material_generation_by_role: dict[str, int] = {}
        self.standalone_dotnet_texture_resources_ready_by_role: dict[str, bool] = {}
        self.standalone_dotnet_material_signature_by_role: dict[str, str] = {}
        self.standalone_dotnet_material_input_signature_by_role: dict[str, str] = {}
        self.standalone_dotnet_material_error_by_role: dict[str, str] = {}
        self.standalone_dotnet_pending_textured_view = False
        self.standalone_dotnet_pending_textured_view_mode = "textured"
        self.standalone_dotnet_pending_textured_view_uses_presentation = False
        self.standalone_dotnet_pending_textured_view_extensions = 0
        self.standalone_dotnet_deferred_textured_view_mode = ""
        self.standalone_dotnet_deferred_textured_view_uses_presentation = False
        self.standalone_dotnet_pending_textured_view_timer = QTimer(self)
        self.standalone_dotnet_pending_textured_view_timer.setSingleShot(True)
        self.standalone_dotnet_pending_textured_view_timer.timeout.connect(
            self._handle_pending_textured_view_timeout
        )
        self.standalone_dotnet_material_package_token = (0, 0)
        self.standalone_dotnet_material_ready_flush_token = (0, 0)
        self.standalone_dotnet_pending_clone_material_model: object | None = None
        self.standalone_dotnet_pending_reference_material_model: object | None = None
        self.standalone_dotnet_pending_imported_material_publish: bool = False
        self.standalone_dotnet_pending_paired_material_model: object | None = None
        self.standalone_dotnet_pending_paired_material_upgrade: object | None = None
        self.standalone_dotnet_material_update_thread: _tab.QThread | None = None
        self.standalone_dotnet_material_update_worker: _tab.MeshDotNetMaterialUpdateWorker | None = None
        # Which publication is compiling, which are waiting, and which were
        # displaced. This replaced a single latest-wins pending slot that could
        # only remember one waiting request and dropped the rest silently.
        self.standalone_dotnet_material_publications = MaterialPublicationCoordinator()
        self.standalone_dotnet_material_update_active_resources: tuple[dict[str, object], ...] = ()
        self.standalone_dotnet_material_update_cancelled = False
        self.standalone_dotnet_capture_request_id = 0
        self.standalone_dotnet_viewport_display_request_id = 0
        self.standalone_dotnet_capture_callbacks: dict[int, tuple[object, object, object]] = {}
        self.standalone_dotnet_provenance_verified = False
        self.standalone_dotnet_lifecycle_session_id = ""
        self.standalone_dotnet_process_generation = 0
        self.standalone_dotnet_pending_mutation_commits: dict[int, dict[str, object]] = {}
        self.standalone_dotnet_recovery_failure_reported = False
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

    def _initialize_runtime_objects(self) -> None:
        self._initialize_dotnet_material_parameter_state()
        self.standalone_dotnet_update_queue = DotNetRevisionUpdateQueue(self._send_dotnet_protocol_message)
        self.standalone_dotnet_update_ack_timer = QTimer(self)
        self.standalone_dotnet_update_ack_timer.setSingleShot(True)
        self.standalone_dotnet_update_ack_timer.timeout.connect(self._handle_dotnet_update_ack_timeout)
        self.standalone_dotnet_update_ack_start_timer = QTimer(self)
        self.standalone_dotnet_update_ack_start_timer.setSingleShot(True)
        self.standalone_dotnet_update_ack_start_timer.timeout.connect(
            lambda: self._sync_dotnet_update_ack_timer()
        )
        self.standalone_dotnet_stdout_tail = ""
        self.standalone_dotnet_stderr_tail = ""
        self.standalone_dotnet_last_program = ""
        self.standalone_dotnet_ready_timer = QTimer(self)
        self.standalone_dotnet_ready_timer.setSingleShot(True)
        self.standalone_dotnet_ready_timer.timeout.connect(self._handle_dotnet_ready_timeout)
        self.standalone_dotnet_deactivate_timer = QTimer(self)
        self.standalone_dotnet_deactivate_timer.setSingleShot(True)
        self.standalone_dotnet_deactivate_timer.timeout.connect(self._handle_dotnet_deactivate_timeout)
        self.standalone_dotnet_finish_scene_timer = QTimer(self)
        self.standalone_dotnet_finish_scene_timer.setSingleShot(True)
        self.standalone_dotnet_finish_scene_timer.timeout.connect(
            self._handle_dotnet_finish_scene_timeout
        )
        self.standalone_dotnet_last_arguments: list[str] = []
        self.standalone_dotnet_last_working_directory = ""
        self.standalone_dotnet_last_parent_hwnd = 0
        self.embedded_dotnet_editor_button: QPushButton | None = None
        self.standalone_last_export_validation_report: object | None = None
        self.standalone_export_validation_revision: int | None = None
        self.standalone_validation_started_revision: int | None = None
        self.standalone_validation_started_session_id = ""
        self.standalone_validation_started_generation = 0
        self.standalone_last_rebuild_report: object | None = None
        # The session revision the rebuild report describes. Only a geometry command
        # bumps `session.revision`, so this is what tells a stale report from one that
        # is merely being looked at from a different selection.
        self.standalone_rebuild_report_revision: int | None = None
        self.standalone_rebuild_started_session_id = ""
        self.standalone_rebuild_started_revision: int | None = None
        self.standalone_rebuild_started_generation = 0
        self.standalone_workspace_panel_state: MeshPanelSnapshot[object] = MeshPanelSnapshot.unavailable()
        self.standalone_uv_panel_state: MeshPanelSnapshot[object] = MeshPanelSnapshot.unavailable()
        self.standalone_skeleton_panel_state: MeshPanelSnapshot[object] = MeshPanelSnapshot.unavailable()
        self.standalone_compare_panel_state: MeshPanelSnapshot[object] = MeshPanelSnapshot.unavailable()
        self.standalone_validation_panel_state: MeshPanelSnapshot[object] = MeshPanelSnapshot.unavailable()
        self.standalone_rebuild_panel_state: MeshPanelSnapshot[object] = MeshPanelSnapshot.unavailable()
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
        self.standalone_native_selection_stroke_id = ""
        self.standalone_pending_dotnet_topology_request: dict[str, object] | None = None
        self.standalone_pending_dotnet_live_stroke_outcome: object | None = None
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
