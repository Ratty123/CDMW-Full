from __future__ import annotations

import time
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
    QApplication,
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
from cdmw.ui.mesh_editor.tab_shell_runtime import MeshEditorTabShellRuntimeMixin


class MeshEditorTabShellMixin(MeshEditorTabShellRuntimeMixin):

    def _initialize_texture_region_queue(self) -> None:
        self.standalone_texture_region_queue = ResidentTextureRegionUpdateQueue(
            self._send_dotnet_texture_region_message,
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
        self._wire_shared_dotnet_controller(self.standalone_native_host)
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
    def _wait_for_dotnet_export_updates(self, timeout_seconds: float) -> bool:
        timeout = max(0.0, float(timeout_seconds))
        started = time.monotonic()
        if not self.standalone_texture_region_queue.wait_idle(timeout):
            return False
        deadline = started + timeout
        while (
            self.standalone_dotnet_sent_material_resource_payload is not None
            or self.standalone_dotnet_sent_material_parameter_payload is not None
            or self._dotnet_material_compile_active()
            or self.standalone_dotnet_material_update_pending is not None
        ) and time.monotonic() < deadline:
            time.sleep(min(0.005, max(0.0, deadline - time.monotonic())))
        return bool(
            self.standalone_texture_region_queue.idle()
            and self.standalone_dotnet_sent_material_resource_payload is None
            and self.standalone_dotnet_sent_material_parameter_payload is None
            and not self._dotnet_material_compile_active()
            and self.standalone_dotnet_material_update_pending is None
        )
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
            ("standalone_mesh_action", self.standalone_action_thread, self.standalone_action_worker),
            ("standalone_validation", self.standalone_validation_thread, self.standalone_validation_worker),
            ("standalone_rebuild_report", self.standalone_rebuild_report_thread, self.standalone_rebuild_report_worker),
            ("standalone_report_write", self.standalone_report_write_thread, self.standalone_report_write_worker),
            ("standalone_dotnet_package", self.standalone_dotnet_package_thread, self.standalone_dotnet_package_worker),
            ("standalone_dotnet_material_update", self.standalone_dotnet_material_update_thread, self.standalone_dotnet_material_update_worker),
            ("standalone_dotnet_scene", self.standalone_dotnet_scene_thread, self.standalone_dotnet_scene_worker),
            ("standalone_dotnet_import", self.standalone_dotnet_import_thread, self.standalone_dotnet_import_worker),
            ("standalone_editable_export", self.standalone_editable_export_thread, self.standalone_editable_export_worker),
            ("standalone_editable_import", self.standalone_editable_import_thread, self.standalone_editable_import_worker),
        )
    def request_shutdown(self) -> None:
        self._cancel_dotnet_material_compile()
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
        self.set_native_preview_host(builder.findChild(QWidget, "AlignmentDotNetVorticePreviewHost"))
        self._install_embedded_merged_mesh_editing(builder)
        self._wire_embedded_dotnet_button(builder)
        self._sync_state()
        QTimer.singleShot(0, self._start_embedded_dotnet_preview_if_available)
    def show_empty_state(self, message: str = "") -> None:
        # Clear references owned by the embedded builder before teardown. Its
        # QDialog may already have processed deleteLater().
        self.embedded_dotnet_editor_button = None
        self.close_standalone_session()
        self.set_native_preview_host(getattr(self, "standalone_native_host_frame", None))
        self.embedded_workspace = None
        self._embedded_control_tabs = None
        self._embedded_classic_builder = None
        self._embedded_restore_control_widget = None
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
        workspace.viewport_display_requested.connect(self._handle_embedded_viewport_display_mode)
        workspace.skeleton_pose_requested.connect(self._handle_embedded_skeleton_pose_request)
        workspace.part_selection_requested.connect(self._handle_embedded_part_selection)
        workspace.part_context_action_requested.connect(self._handle_embedded_part_context_action)
        workspace.uv_region_selected.connect(self._handle_embedded_uv_region_selection)
        workspace.uv_lasso_selected.connect(self._handle_embedded_uv_lasso_selection)
        advanced_index = control_tabs.addTab(workspace, "Edit Mesh")
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
        setattr(builder, "_mesh_editor_embedded_set_controls_visible", self._set_embedded_edit_controls_visible)
        control_tabs.currentChanged.connect(lambda _index: self._refresh_embedded_workspace_from_builder())
        if control_tabs.currentIndex() == classic_index:
            for index in range(control_tabs.count()):
                is_visible = getattr(control_tabs, "isTabVisible", lambda _index: True)
                if index != classic_index and index != advanced_index and bool(is_visible(index)):
                    control_tabs.setCurrentIndex(index)
                    break
        self._refresh_embedded_workspace_from_builder()
    def _set_embedded_edit_controls_visible(self, visible: bool) -> None:
        tabs = self._embedded_control_tabs
        workspace = self.embedded_workspace
        if tabs is None or workspace is None:
            return
        workspace_index = tabs.indexOf(workspace)
        if workspace_index < 0:
            return
        if visible:
            if tabs.currentWidget() is not workspace:
                self._embedded_restore_control_widget = tabs.currentWidget()
            if hasattr(tabs, "setTabVisible"):
                tabs.setTabVisible(workspace_index, True)
            tabs.setCurrentWidget(workspace)
            return
        if tabs.currentWidget() is workspace:
            restore = self._embedded_restore_control_widget
            restore_index = tabs.indexOf(restore) if restore is not None else -1
            is_visible = getattr(tabs, "isTabVisible", lambda _index: True)
            if restore_index < 0 or not bool(is_visible(restore_index)):
                restore_index = next(
                    (
                        index
                        for index in range(tabs.count())
                        if index != workspace_index and bool(is_visible(index))
                    ),
                    -1,
                )
            if restore_index >= 0:
                tabs.setCurrentIndex(restore_index)
        if hasattr(tabs, "setTabVisible"):
            tabs.setTabVisible(workspace_index, False)
        self._embedded_restore_control_widget = None
    def _embedded_dotnet_runtime_diagnostics(self) -> dict[str, object]:
        builder = self.active_builder()
        package = self.standalone_dotnet_experiment_package
        process = self.standalone_dotnet_editor_process
        status = dict(self.standalone_dotnet_status_payload)
        renderer = status.get("renderer")
        renderer_status = dict(renderer) if isinstance(renderer, Mapping) else {}
        active = bool(
            builder is not None
            and getattr(builder, "_mesh_editor_embedded_dotnet_active", False)
        )
        return {
            "state": str(self.standalone_dotnet_embedded_state or "closed"),
            "active": active,
            "renderer_backend": str(
                renderer_status.get("backend")
                or ("d3d11_vortice_shader" if active else "")
            ),
            "process": {
                "attached": process is not None,
                "generation": int(self.standalone_dotnet_process_generation),
                "program": str(self.standalone_dotnet_last_program or ""),
                "working_directory": str(self.standalone_dotnet_last_working_directory or ""),
                "embedded_parent_hwnd": int(self.standalone_dotnet_last_parent_hwnd or 0),
            },
            "session": {
                "session_id": str(self.standalone_dotnet_lifecycle_session_id or ""),
                "package_dir": str(getattr(package, "package_dir", "") or ""),
                "status_path": str(getattr(package, "status_path", "") or ""),
                "capabilities": sorted(str(item) for item in self.standalone_dotnet_capabilities),
                "lifecycle_counts": dict(self.standalone_dotnet_lifecycle_counts),
            },
            "scene": {
                "desired": dict(self.standalone_dotnet_scene_desired),
                "generation": int(self.standalone_dotnet_scene_generation),
                "acknowledged_generation": int(self.standalone_dotnet_scene_acknowledged_generation),
                "pending": self.standalone_dotnet_scene_pending is not None,
                "acknowledged": dict(self.standalone_dotnet_scene_acknowledged or {}),
            },
            "presentation": {
                "desired": dict(self.standalone_dotnet_presentation_desired),
                "generation": int(self.standalone_dotnet_presentation_generation),
                "pending": self.standalone_dotnet_presentation_pending is not None,
                "acknowledged": dict(self.standalone_dotnet_presentation_acknowledged or {}),
                "pane_header_behavior": "focuses that pane's independent camera; does not hide the other side-by-side pane",
            },
            "materials": {
                "signature": str(self.standalone_dotnet_material_signature or ""),
                "generation": int(self.standalone_dotnet_material_generation),
                "applied_generation": int(self.standalone_dotnet_applied_material_generation),
                "completed_generation": int(self.standalone_dotnet_completed_material_generation),
            },
            "renderer": renderer_status,
            "host_status": status,
        }

    def _set_embedded_dotnet_state(self, state: str, *, active: bool = False) -> None:
        normalized_state = str(state or "closed").strip().lower() or "closed"
        self.standalone_dotnet_embedded_state = normalized_state
        builder = self.active_builder()
        if builder is not None:
            was_active = bool(getattr(builder, "_mesh_editor_embedded_dotnet_active", False))
            setattr(builder, "_mesh_editor_embedded_dotnet_state", normalized_state)
            setattr(builder, "_mesh_editor_embedded_dotnet_active", bool(active))
            if getattr(self, "embedded_workspace", None) is not None:
                self.embedded_workspace.viewport_display_combo.setEnabled(
                    normalized_state == "ready"
                    and bool(active)
                    and "viewport_display_modes_v1" in self.standalone_dotnet_capabilities
                )
            refresh_controls = getattr(builder, "_refresh_material_authority_live_control_states", None)
            if callable(refresh_controls):
                refresh_controls()
            replay_parameters = getattr(builder, "_replay_resident_material_authority_parameters", None)
            capability = getattr(builder, "_mesh_editor_embedded_resident_material_parameters_supported", False)
            parameter_updates_supported = bool(capability()) if callable(capability) else bool(capability)
            if normalized_state == "ready" and active and not was_active and parameter_updates_supported and callable(replay_parameters):
                replay_parameters()

    def _handle_embedded_builder_viewport_display_mode(self, mode: str) -> bool:
        return self._handle_embedded_viewport_display_mode(
            mode,
            use_presentation_state=True,
        )

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
        setattr(builder, "_mesh_editor_embedded_set_scene_state", self._send_dotnet_scene_state)
        setattr(
            builder,
            "_mesh_editor_embedded_set_presentation_state",
            self._send_dotnet_presentation_state,
        )
        setattr(
            builder,
            "_mesh_editor_embedded_request_viewport_display",
            self._handle_embedded_builder_viewport_display_mode,
        )
        setattr(
            builder,
            "_mesh_editor_embedded_runtime_diagnostics",
            self._embedded_dotnet_runtime_diagnostics,
        )
        setattr(builder, "_mesh_editor_embedded_send_native_update", self._send_embedded_dotnet_native_update)
        setattr(builder, "_mesh_editor_embedded_apply_material_parameters", self.apply_resident_material_parameters)
        setattr(builder, "_mesh_editor_embedded_apply_material_resources", self.apply_resident_material_resources)
        setattr(
            builder,
            "_mesh_editor_embedded_texture_request_failed",
            self._handle_embedded_texture_request_failed,
        )
        setattr(
            builder,
            "_mesh_editor_embedded_apply_clone_material_resources",
            self.apply_resident_clone_material_resources,
        )
        setattr(
            builder,
            "_mesh_editor_embedded_apply_reference_material_resources",
            self.apply_resident_reference_material_resources,
        )
        setattr(builder, "_mesh_editor_embedded_capture_icon", self.request_resident_dotnet_icon_capture)
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
        button.setEnabled(dotnet_available and not self._dotnet_task_active() and not self._standalone_dotnet_editor_process_running())

    def _start_embedded_dotnet_preview_if_available(self) -> None:
        if str(QApplication.platformName() or "").strip().lower() == "offscreen":
            return
        builder = self.active_builder()
        if builder is None:
            return
        if not bool(getattr(builder, "_mesh_editor_auto_dotnet_preview", False)):
            return
        if not bool(getattr(builder, "_mesh_editor_use_embedded_dotnet_viewport", False)):
            return
        if not bool(getattr(builder, "_mesh_editor_dotnet_available", False)):
            return
        if self._dotnet_task_active():
            return
        self._start_embedded_dotnet_editor_requested()
    def set_native_preview_host(self, host: object | None) -> None:
        self.standalone_native_host = host if host is not None else getattr(self, "standalone_native_host_frame", None)
        self._wire_shared_dotnet_controller(self.standalone_native_host)
        self._wire_standalone_native_part_events(self.standalone_native_host)
        if self.standalone_native_part_picking_wanted:
            self._request_standalone_native_part_picking(True, retries=2)
        self._sync_standalone_native_mesh_edit_state(force=True)

    def _active_shared_dotnet_controller(self) -> object | None:
        host = (
            self.standalone_native_host
            if self.standalone_dotnet_target_embedded
            else getattr(self, "standalone_native_host_frame", None)
        )
        return getattr(host, "controller", None)

    def _wire_shared_dotnet_controller(self, host: object | None) -> None:
        controller = getattr(host, "controller", None)
        if controller is None or id(controller) in self._wired_shared_dotnet_controller_ids:
            return
        controller.protocol_event.connect(
            lambda payload, target=controller: self._handle_shared_dotnet_protocol_event(target, payload)
        )
        controller.state_changed.connect(
            lambda state, message, target=controller: self._handle_shared_dotnet_state(target, state, message)
        )
        controller.package_applied.connect(
            lambda path, generation, target=controller: self._handle_shared_dotnet_package_applied(
                target, path, generation
            )
        )
        controller.package_failed.connect(
            lambda path, generation, message, target=controller: self._handle_shared_dotnet_package_failed(
                target, path, generation, message
            )
        )
        controller.set_authoring_rehydrator(
            lambda target=controller: self._rehydrate_shared_dotnet_controller(target)
        )
        self._wired_shared_dotnet_controller_ids.add(id(controller))

    def _sync_shared_dotnet_process_identity(self, controller: object) -> None:
        """Adopt the resident controller's process and count real launches.

        The shared controller owns the QProcess, so the tab never sees
        QProcess.started and cannot count a launch there. A process-generation
        increase is the launch. It has to be counted here because the
        controller's state and protocol signals arrive before any load path
        runs, which is what left the counters reading zero starts for a
        renderer that was demonstrably running.
        """

        process = getattr(controller, "process", None)
        generation = int(getattr(controller, "process_generation", 0) or 0)
        previous = int(getattr(self, "standalone_dotnet_process_generation", 0) or 0)
        self.standalone_dotnet_editor_process = process
        self.standalone_dotnet_process_generation = generation
        if generation <= previous or process is None:
            return
        starts = int(self.standalone_dotnet_lifecycle_counts.get("renderer_process_start_count", 0) or 0)
        self.standalone_dotnet_lifecycle_counts["renderer_process_start_count"] = starts + 1
        if starts > 0:
            self.standalone_dotnet_lifecycle_counts["process_restart_count"] += 1

    def _handle_shared_dotnet_protocol_event(self, controller: object, payload: object) -> None:
        if controller is not self._active_shared_dotnet_controller() or not isinstance(payload, Mapping):
            return
        self._sync_shared_dotnet_process_identity(controller)
        self.standalone_dotnet_capabilities.update(getattr(controller, "capabilities", ()) or ())
        event = str(payload.get("event", "") or "").strip().lower()
        if event in {
            "material_state_started",
            "material_state_applied",
            "material_state_failed",
            "viewport_display_request",
            "viewport_display_applied",
            "viewport_display_failed",
        }:
            self._record_mesh_dotnet_event(
                "mesh_dotnet_shared_protocol_event",
                helper_event=event,
                request_id=payload.get("request_id", 0),
                process_generation=payload.get("process_generation", 0),
                generation=payload.get("generation", 0),
                reason=payload.get("reason", ""),
                message=payload.get("message", ""),
                resource_count=payload.get("resource_count", 0),
                decoded_resources=payload.get("decoded_resources", 0),
                reused_resources=payload.get("reused_resources", 0),
                optional_resource_failure_count=len(
                    tuple(payload.get("optional_resource_failures", ()) or ())
                ),
            )
        self._handle_dotnet_protocol_event(payload)

    def _handle_shared_dotnet_state(self, controller: object, state: str, message: str) -> None:
        if controller is not self._active_shared_dotnet_controller():
            return
        self._sync_shared_dotnet_process_identity(controller)
        self._record_mesh_dotnet_event(
            "mesh_dotnet_shared_host_state",
            state=str(state or ""),
            message=str(message or ""),
            process_generation=self.standalone_dotnet_process_generation,
            package_generation=int(getattr(controller, "package_generation", 0) or 0),
            process_id=int(getattr(controller, "process_id", 0) or 0),
        )
        if str(state) == "ready":
            if self.standalone_dotnet_target_embedded:
                self._set_embedded_dotnet_state("ready", active=True)
            self._set_dotnet_status("Mesh Editor .NET/Vortice viewport ready.")
        elif str(state) == "error":
            if self.standalone_dotnet_target_embedded:
                self._set_embedded_dotnet_state("failed", active=False)
            self._set_dotnet_status(str(message or ".NET/Vortice viewport failed."), error=True)
        elif str(state) == "package_error":
            has_resident_scene = bool(getattr(controller, "applied_package_path", ""))
            if self.standalone_dotnet_target_embedded:
                self._set_embedded_dotnet_state(
                    "ready" if has_resident_scene else "failed",
                    active=has_resident_scene,
                )
            self._finish_pending_textured_view(success=False)
            self._set_dotnet_status(str(message or ".NET/Vortice package update failed."), error=True)

    def _handle_shared_dotnet_package_applied(
        self,
        controller: object,
        package_path: str,
        generation: int,
    ) -> None:
        del package_path
        if controller is not self._active_shared_dotnet_controller():
            return
        token = (
            int(getattr(controller, "process_generation", 0) or 0),
            int(generation or 0),
        )
        if token == self.standalone_dotnet_material_ready_flush_token:
            return
        self.standalone_dotnet_material_ready_flush_token = token
        QTimer.singleShot(0, self._flush_pending_dotnet_reference_material_resources)

    def _handle_shared_dotnet_package_failed(
        self,
        controller: object,
        package_path: str,
        generation: int,
        message: str,
    ) -> None:
        del package_path, generation
        if controller is not self._active_shared_dotnet_controller():
            return
        self._finish_pending_textured_view(success=False)
        self._set_dotnet_status(
            f"Mesh Editor package update failed; the resident scene was kept: {message}",
            error=True,
        )

    def _rehydrate_shared_dotnet_controller(self, controller: object) -> bool:
        if controller is not self._active_shared_dotnet_controller():
            return False
        self._sync_shared_dotnet_process_identity(controller)
        self.standalone_dotnet_capabilities.update(getattr(controller, "capabilities", ()) or ())
        sent = self._send_dotnet_session_state()
        self._send_dotnet_scene_state()
        self._send_dotnet_presentation_state()
        self._send_dotnet_cached_morph_state()
        return bool(sent)
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
            updater("Part pick: unavailable, waiting for .NET/Vortice host", available=False)
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
