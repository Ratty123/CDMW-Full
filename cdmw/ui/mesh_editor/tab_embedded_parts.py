from __future__ import annotations

from PySide6.QtCore import QTimer

from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_dotnet_presentation import MeshEditorDotNetPresentationMixin


class MeshEditorEmbeddedPartsMixin(MeshEditorDotNetPresentationMixin):
    """Embedded-editor part selection, part context actions, and compare mode."""

    def _set_embedded_part_selection(self, source_indices: object) -> bool:
        controller = self._embedded_builder_controller()
        if controller is None:
            return False
        try:
            normalized = tuple(sorted({int(index) for index in tuple(source_indices or ()) if int(index) >= 0}))
            result = controller.select(source_indices=normalized, operation="replace")
            update = controller.native_update_for_result(result)
        except (TypeError, ValueError, RuntimeError):
            return False
        self._apply_embedded_native_update(update)
        self._send_embedded_dotnet_native_update(update)
        self._refresh_embedded_workspace_from_builder()
        return True

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
        self._send_embedded_dotnet_native_update(update)
        self._refresh_embedded_workspace_from_builder()
        selected_names = ", ".join(part.name for part in controller.workspace_summary().parts if part.selected)
        self.status_message_requested.emit(
            f"Embedded Mesh Editor selected {len(controller.session_view().selection.source_indices)} part(s){': ' + selected_names if selected_names else ''}.",
            False,
        )
        return True

    def _embedded_selection_for_part_context(
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
            update = controller.native_update_for_result(result)
            self._apply_embedded_native_update(update)
            self._send_embedded_dotnet_native_update(update)
            selected_sources = {clicked_index}
            self._refresh_embedded_workspace_from_builder()
        return _tab.MeshEditSelection.from_maps(source_indices=selected_sources)

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

    def _handle_embedded_compare_mode(self, mode: str) -> None:
        normalized = str(mode or "edited").strip().lower()
        comparison_mode = {"source": "original_only", "ghost": "overlay"}.get(normalized, "replacement_only")
        if self._send_dotnet_scene_state(comparison_mode=comparison_mode):
            self.status_message_requested.emit(f"Embedded .NET compare view: {normalized}.", False)
            return
        self.status_message_requested.emit(f"Embedded Mesh Editor compare mode selected: {normalized}.", False)

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
                # Best effort: builder bone selection mirroring is optional UI sync.
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
        canonical_menu = getattr(self.active_builder(), "_show_replacement_sources_context_menu_for_viewport", None)
        if callable(canonical_menu):
            QTimer.singleShot(0, lambda index=int(part_index), position=global_pos: canonical_menu(index, position))
            return True
        QTimer.singleShot(0, lambda index=int(part_index), position=global_pos: workspace.show_part_context_menu_for_part(index, position))
        return True
