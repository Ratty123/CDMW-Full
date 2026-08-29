"""Widget projection helpers for the authoritative Mesh Editor UI state."""

from __future__ import annotations

from cdmw.domain.mesh import MeshEditorUiState
from cdmw.domain.mesh.authoring_capability import MeshOutputPolicy
from cdmw.ui.mesh_editor.actions import MESH_EDITOR_VISIBLE_ACTIONS, mesh_editor_actions_by_key


class MeshEditorStatePresentationMixin:
    def _mesh_editor_action_presentation(
        self,
        ui_state: MeshEditorUiState,
        *,
        has_standalone: bool,
        has_target: bool,
        workflow_mode: str,
    ) -> tuple[str, str, dict[str, str], set[str]]:
        session_text = ""
        authoring_tooltip = ""
        authoring_blockers: dict[str, str] = {}
        visible_action_keys = {action.key for action in MESH_EDITOR_VISIBLE_ACTIONS}
        if has_standalone:
            format_label = ui_state.mesh_format.upper() or "UNKNOWN"
            policy_label = ui_state.output_policy.replace("_", " ").title()
            session_text = (
                f"Mode: standalone | Edit: {ui_state.mode} | "
                f"{format_label} LOD{ui_state.lod_index} | Output: {policy_label} | "
                f"Exact write: {ui_state.exact_write_status.replace('_', '-')}"
            )
            authoring_tooltip = ui_state.policy_reason
            visible_action_keys = set(ui_state.visible_actions)
            authoring_blockers = dict(ui_state.action_blockers)
            for action_key in ui_state.mutation_actions:
                if not ui_state.action_enabled(action_key):
                    authoring_blockers.setdefault(action_key, ui_state.authoring_blocker)
            synchronization_blocker = self._resident_mutation_authoring_blocker()
            if synchronization_blocker:
                for action in mesh_editor_actions_by_key().values():
                    if action.command != "set_mode":
                        authoring_blockers[action.key] = synchronization_blocker
                authoring_tooltip = " ".join(
                    part for part in (authoring_tooltip, synchronization_blocker) if part
                )
        elif has_target:
            session_text = (
                f"Mode: {workflow_mode.replace('_', ' ')} | Edit: {self.current_edit_mode}"
            )
        return session_text, authoring_tooltip, authoring_blockers, visible_action_keys

    def _mesh_editor_task_active(self, *, include_package_build: bool) -> bool:
        return bool(
            self._standalone_action_worker_active()
            or self._standalone_validation_worker_active()
            or self._standalone_rebuild_report_worker_active()
            or self._mesh_direct_output_busy()
            or self._standalone_editable_package_task_active()
            or (include_package_build and self._standalone_dotnet_package_worker_active())
            or self._standalone_dotnet_import_worker_active()
            or (
                self._standalone_dotnet_editor_process_running()
                and self.standalone_dotnet_target_embedded
                and self.standalone_dotnet_embedded_state != "suspended"
            )
        )

    def _apply_mesh_editor_action_surfaces(
        self,
        ui_state: MeshEditorUiState,
        *,
        has_standalone: bool,
        has_target: bool,
        native_editor_available: bool,
        task_active: bool,
        visible_action_keys: set[str],
        authoring_blockers: dict[str, str],
    ) -> None:
        selection_empty = ui_state.selection.empty if has_standalone else self.current_selection_empty
        mode = ui_state.mode if has_standalone else self.current_edit_mode
        selection_shape = ui_state.selection_shape if has_standalone else self.current_selection_mode
        undo_count = ui_state.undo_count if has_standalone else self.current_undo_count
        redo_count = ui_state.redo_count if has_standalone else self.current_redo_count
        self.action_bar.setEnabled(not task_active)
        self.action_bar.set_action_visibility(visible_action_keys)
        self.action_bar.update_action_state(
            has_target=has_target,
            selection_empty=selection_empty,
            mode=mode,
            active_selection_mode=selection_shape,
            active_tool_key=(ui_state.active_tool if has_standalone else self.current_tool_action_key),
            undo_count=undo_count,
            redo_count=redo_count,
            native_editor_available=native_editor_available,
            authoring_blockers=authoring_blockers,
        )
        workspace_visibility = getattr(self.standalone_workspace, "set_action_visibility", None)
        if callable(workspace_visibility):
            workspace_visibility(visible_action_keys)
        workspace_state = getattr(self.standalone_workspace, "update_action_state", None)
        if callable(workspace_state):
            workspace_state(
                has_target=has_target,
                selection_empty=selection_empty,
                mode=mode,
                active_selection_mode=selection_shape,
                undo_count=undo_count,
                redo_count=redo_count,
                native_editor_available=native_editor_available,
                authoring_blockers=authoring_blockers,
            )

    def _apply_mesh_editor_launch_button_state(
        self,
        *,
        has_standalone: bool,
        task_active: bool,
    ) -> None:
        process_running = self._standalone_dotnet_editor_process_running()
        dotnet_button = getattr(self, "standalone_dotnet_editor_button", None)
        if dotnet_button is not None:
            dotnet_button.setEnabled(has_standalone and not task_active and not process_running)
        embedded_dotnet_button = getattr(self, "embedded_dotnet_editor_button", None)
        if embedded_dotnet_button is None:
            return
        try:
            embedded_dotnet_button.setEnabled(
                self.workspace_stack.currentWidget() is self.embedded_builder_host
                and not task_active
                and not process_running
            )
        except RuntimeError:
            if embedded_dotnet_button is getattr(self, "embedded_dotnet_editor_button", None):
                self.embedded_dotnet_editor_button = None

    def _apply_mesh_editor_output_control_state(
        self,
        ui_state: MeshEditorUiState,
        *,
        has_standalone: bool,
        has_archive_target: bool,
        output_task_active: bool,
    ) -> None:
        exact_session = bool(
            has_standalone
            and ui_state.output_policy == MeshOutputPolicy.EXACT_GAME_ASSET.value
        )
        rebuild_allowed = self._standalone_rebuild_allowed()
        for button_name in (
            "standalone_run_validation_report_button",
            "standalone_export_mesh_file_button",
            "standalone_build_mod_button",
            "standalone_install_overlay_button",
            "standalone_restore_overlay_button",
            "standalone_export_editable_package_button",
            "standalone_import_edited_package_button",
            "standalone_open_editable_package_folder_button",
        ):
            button = getattr(self, button_name, None)
            if button is None:
                continue
            enabled = has_standalone and not output_task_active
            if button_name != "standalone_open_editable_package_folder_button":
                enabled = enabled and exact_session
            if button_name in {
                "standalone_export_mesh_file_button",
                "standalone_build_mod_button",
                "standalone_install_overlay_button",
            }:
                enabled = enabled and rebuild_allowed
                if button_name != "standalone_export_mesh_file_button":
                    enabled = enabled and has_archive_target
            elif button_name == "standalone_restore_overlay_button":
                receipt = self._mesh_overlay_receipt_path()
                enabled = enabled and receipt is not None and receipt.is_file()
            button.setEnabled(enabled)
            if button_name != "standalone_open_editable_package_folder_button":
                self._apply_exact_output_tooltip(button, exact_session=exact_session)
        self._set_rebuild_report_button_enabled(
            has_standalone and exact_session and not output_task_active
        )
        self._set_rebuild_asset_button_enabled(
            has_standalone
            and exact_session
            and not output_task_active
            and rebuild_allowed
        )

    @staticmethod
    def _apply_exact_output_tooltip(button: object, *, exact_session: bool) -> None:
        exact_tooltip = button.property("meshEditorExactOutputToolTip")
        if exact_tooltip is None:
            exact_tooltip = button.toolTip()
            button.setProperty("meshEditorExactOutputToolTip", exact_tooltip)
        button.setToolTip(
            str(exact_tooltip or "")
            if exact_session
            else "This control is for Exact Game Asset output. "
            "Free Edit publishes through Export Free Edit OBJ."
        )


__all__ = ["MeshEditorStatePresentationMixin"]
