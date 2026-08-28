from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Signal

from cdmw.ui.mesh_editor.actions import MeshEditorAction


from cdmw.ui.mesh_editor.tab_support import (
    STANDALONE_NATIVE_TOOL_STATE as _STANDALONE_NATIVE_TOOL_STATE,
    _mesh_edit_result_with_metric,
    _native_update_has_payload,
)


from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab

class MeshEditorActionsMixin:
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
        blocker = self._standalone_action_authoring_blocker(
            normalized,
            deletes_parts=normalized == "delete",
        )
        if blocker:
            self.status_message_requested.emit(f"Mesh Editor action unavailable: {blocker}", True)
            return False
        if self._native_editor_action_blocked(normalized):
            return False
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before editing parts.", True)
            return False
        selection = self._selection_for_part_context(controller, part_index)
        if selection is None:
            return False
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
        controller: _tab.MeshEditorController,
        part_index: int,
    ) -> _tab.MeshEditSelection | None:
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
        return _tab.MeshEditSelection.from_maps(source_indices=selected_sources)
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
        blocker = self._standalone_action_authoring_blocker(key)
        if blocker:
            self.status_message_requested.emit(f"Mesh Editor action unavailable: {blocker}", True)
            return True
        if key in _STANDALONE_NATIVE_TOOL_STATE:
            self.set_active_tool_state(
                mode=str(getattr(action, "mode", "") or ""),
                active_tool_key=key,
            )
            if key == "select_parts":
                controller.apply_editor_action(action)
                self.update_editor_session_state(
                    controller.session_view(),
                    active_selection_mode=controller.active_selection_mode,
                )
                self.status_message_requested.emit("Select active. Choose Vertices, Wires, or Faces in the viewport.", False)
                return True
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

    def _handle_object_transform_requested(self, payload: object) -> bool:
        if not isinstance(payload, dict):
            self.status_message_requested.emit("Mesh Editor object transform was invalid.", True)
            return False
        if self.standalone_controller is None:
            return False
        if self._standalone_action_worker_active():
            self.update_editor_session_state(self.standalone_controller.session_view())
            self.status_message_requested.emit(
                "Wait for the current Mesh Editor action before changing Object Transform.",
                True,
            )
            return False
        action = MeshEditorAction(
            key="object_transform_commit",
            text="Object Transform",
            command="object_transform",
            category="transform",
            params=tuple(
                (key, tuple(payload.get(key, ())))
                for key in ("location", "rotation_degrees", "scale")
            ),
        )
        return self._start_standalone_action_worker(action, action_text="Object Transform")
    def _finish_standalone_action_execution(self, execution: object, *, action_text: str = "") -> bool:
        controller = self.standalone_controller
        if controller is None:
            return False
        self.update_editor_session_state(controller.session_view(), active_selection_mode=controller.active_selection_mode)
        edit_result = getattr(execution, "edit_result", None)
        native_update = getattr(execution, "native_update", _tab.MeshEditorNativeUpdate())
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
            if isinstance(edit_result, _tab.MeshEditResult):
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
    def _should_run_standalone_action_worker(self, action: object, controller: _tab.MeshEditorController) -> bool:
        if not self._standalone_action_can_run_in_background(action):
            return False
        if bool(getattr(action, "requires_selection", False)):
            try:
                return not controller.session_view().selection.is_empty()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return False
        return True
    def _standalone_action_can_run_in_background(self, action: object) -> bool:
        command = str(getattr(action, "command", "") or "").strip().lower()
        return bool(command and command not in {"set_mode", "select"})
    def _standalone_action_command(
        self,
        action: object,
        controller: _tab.MeshEditorController,
        *,
        action_text: str = "",
    ) -> _tab.MeshEditCommand | None:
        command = str(getattr(action, "command", "") or "").strip().lower()
        if not command or command in {"set_mode", "select"}:
            return None
        params = self._action_params(action)
        mode = str(getattr(action, "mode", "") or "").strip() or None
        return _tab.MeshEditCommand(
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
    def _apply_standalone_native_update(self, update: _tab.MeshEditorNativeUpdate) -> bool:
        host = self.standalone_native_host
        if host is not None:
            if _tab.apply_native_update_to_host(host, update):
                if host is getattr(self, "standalone_native_host_frame", None):
                    self.standalone_preview_stack.setCurrentWidget(self.standalone_native_host_frame)
                return True
        if _native_update_has_payload(update) or self._standalone_native_preview_update_active():
            message = ".NET/Vortice preview update failed; preview is stale. Retry the preview to resync."
            self.standalone_status_label.setText(message)
            self.status_message_requested.emit(message, True)
            return False
        return True
    def _standalone_native_preview_update_active(self) -> bool:
        return (
            self.standalone_preview_stack.currentWidget() is getattr(self, "standalone_native_host_frame", None)
            or self._standalone_native_process_running()
            or self.standalone_dotnet_package_thread is not None
        )
    def _refresh_standalone_preview(self) -> None:
        self.standalone_preview_stack.setCurrentWidget(self.standalone_native_host_frame)
        controller = self.standalone_controller
        if controller is None:
            self.standalone_native_host_frame.clear_preview()
            self.standalone_status_label.setText("No active edit session.")
            return
        view = controller.session_view()
        self._set_standalone_status(view)
    def _set_standalone_compare_mode(self, mode: str) -> None:
        normalized = str(mode or "edited").strip().lower()
        if normalized not in {"edited", "source", "ghost"}:
            normalized = "edited"
        self.standalone_compare_mode = normalized
        if not self.has_active_standalone_session():
            return
        comparison_mode = {"source": "original_only", "ghost": "overlay"}.get(normalized, "replacement_only")
        if self._send_dotnet_scene_state(comparison_mode=comparison_mode):
            self.standalone_status_label.setText(f"Resident .NET compare view: {normalized}.")
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
                self.standalone_status_label.setText(".NET/Vortice compare view: source.")
                return
            if self._standalone_native_preview_update_active():
                if self.standalone_dotnet_package_thread is None and self.start_standalone_native_preview_async(reset_view=False):
                    self.standalone_status_label.setText("Preparing .NET/Vortice source compare preview...")
                else:
                    self.standalone_status_label.setText(".NET/Vortice source compare preview pending.")
                return
            self._refresh_standalone_preview()
            return
        if normalized == "ghost" and self._standalone_native_preview_update_active() and not self.standalone_native_package_has_reference:
            if self.standalone_dotnet_package_thread is None and self.start_standalone_native_preview_async(reset_view=False):
                self.standalone_status_label.setText("Preparing .NET/Vortice ghost compare preview...")
            else:
                self.standalone_status_label.setText(".NET/Vortice ghost compare preview pending.")
            return
        host = self.standalone_native_host
        setter = getattr(host, "set_display_mode", None)
        if callable(setter) and self.standalone_preview_stack.currentWidget() is self.standalone_native_host_frame:
            display_mode = "overlay" if normalized == "ghost" else "replacement_only"
            if setter(display_mode):
                self.standalone_status_label.setText(f".NET/Vortice compare view: {normalized}.")
                return
            if self._standalone_native_preview_update_active():
                message = ".NET/Vortice compare view update failed; preview is stale. Retry the preview to resync."
                self.standalone_status_label.setText(message)
                self.status_message_requested.emit(message, True)
                return
        self._refresh_standalone_preview()
    def _update_standalone_status(self) -> None:
        if self.standalone_controller is None:
            return
        self._set_standalone_status(self.standalone_controller.session_view())
    def _set_standalone_status(self, view: _tab.MeshEditSessionView) -> None:
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
        self.status_message_requested.emit(
            "Texture editing is archived from Mesh Editor; use Texture Editor directly.",
            True,
        )
        return False
    def _open_selected_texture_in_editor_for_controller(
        self,
        controller: _tab.MeshEditorController | None,
        *,
        missing_controller_message: str = "Open a Mesh Editor session before opening a texture.",
    ) -> bool:
        _ = controller, missing_controller_message
        return False

    def _open_texture_target_source(
        self,
        target: object,
        source_path: Path,
        *,
        archive_path: str = "",
        controller: _tab.MeshEditorController | None = None,
    ) -> None:
        _ = target, source_path, archive_path, controller

    def apply_texture_editor_dds_result(self, dds_path_text: str, binding: object) -> bool:
        _ = dds_path_text, binding
        return False

    def apply_texture_editor_dds_assignment(self, dds_path_text: str, binding: object) -> bool:
        _ = dds_path_text, binding
        return False

    def apply_texture_editor_region_patch(self, patch: object) -> bool:
        lease = getattr(patch, "composite_lease", None)
        release = getattr(lease, "release", None)
        if callable(release):
            release()
        return False

    def apply_texture_editor_dds_preview(self, dds_path_text: str, binding: object) -> bool:
        _ = dds_path_text, binding
        return False

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
