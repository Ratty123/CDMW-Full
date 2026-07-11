from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import Signal

from cdmw.ui.mesh_editor.resident_texture_update_queue import ResidentTextureRegionRequest


_STANDALONE_NATIVE_TOOL_STATE: dict[str, tuple[str, str, str]] = {
    "transform_move": ("move", "selection", "edit"),
    "brush_grab": ("grab", "selection", "sculpt"),
    "brush_smooth": ("smooth", "selection", "sculpt"),
    "brush_inflate": ("inflate", "selection", "sculpt"),
    "brush_pinch": ("pinch", "selection", "sculpt"),
}


from cdmw.ui.mesh_editor.tab_support import (
    _mesh_edit_result_with_metric,
    _mesh_editor_texture_binding_target,
    _native_update_has_payload,
)


from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


def _mesh_texture_binding_targets(binding: object) -> tuple[str, tuple[int, ...]]:
    session_id = str(getattr(binding, "mesh_session_id", "") or "").strip()
    indices: set[int] = set()
    for raw_index in tuple(getattr(binding, "mesh_submesh_indices", ()) or ()):
        try:
            index = int(raw_index)
        except (TypeError, ValueError, OverflowError):
            continue
        if index >= 0:
            indices.add(index)
    if not session_id or not indices:
        legacy_session_id, legacy_index = _mesh_editor_texture_binding_target(
            getattr(binding, "source_identity_path", "")
        )
        session_id = session_id or legacy_session_id
        if not indices and legacy_index >= 0:
            indices.add(legacy_index)
    return session_id, tuple(sorted(indices))


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
        return self._open_selected_texture_in_editor_for_controller(
            self.standalone_controller,
            missing_controller_message="Open a standalone Mesh Editor session before opening a texture.",
        )
    def _open_selected_texture_in_editor_for_controller(
        self,
        controller: _tab.MeshEditorController | None,
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
        controller: _tab.MeshEditorController | None = None,
    ) -> None:
        controller = controller or self.standalone_controller
        if controller is None:
            return
        resolved = Path(source_path).expanduser().resolve()
        texture = str(getattr(target, "texture", "") or "")
        submesh_index = int(getattr(target, "submesh_index", -1))
        binding = _tab.TextureEditorSourceBinding(
            launch_origin="mesh_editor",
            display_name=str(getattr(target, "display_name", "") or resolved.name),
            source_path=str(resolved),
            source_identity_path=f"{controller.active_session_id}:{submesh_index}:{texture}",
            relative_path=archive_path or texture,
            archive_relative_path=archive_path or texture,
            original_dds_path=str(resolved) if resolved.suffix.lower() == ".dds" else "",
            texture_type="mesh_material",
            semantic_subtype=str(getattr(target, "material", "") or getattr(target, "source_texture_set_key", "") or "unknown"),
            mesh_session_id=str(controller.active_session_id or ""),
            mesh_resource_id=str(getattr(target, "source_texture_set_key", "") or texture),
            mesh_submesh_indices=(submesh_index,) if submesh_index >= 0 else (),
            mesh_channel="base",
        )
        self.open_texture_source_requested.emit(str(resolved), binding)
        self.status_message_requested.emit(f"Opening Mesh Editor texture in Texture Editor: {resolved.name}", False)
    def apply_texture_editor_dds_result(self, dds_path_text: str, binding: object) -> bool:
        commit_mode = str(getattr(binding, "mesh_commit_mode", "") or "").strip().lower()
        if commit_mode == "assign":
            return self.apply_texture_editor_dds_assignment(dds_path_text, binding)
        return self.apply_texture_editor_dds_preview(dds_path_text, binding)
    def apply_texture_editor_dds_assignment(self, dds_path_text: str, binding: object) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None or not isinstance(binding, _tab.TextureEditorSourceBinding):
            return False
        if str(binding.launch_origin or "") != "mesh_editor" or str(binding.texture_type or "") != "mesh_material":
            return False
        session_id, source_indices = _mesh_texture_binding_targets(binding)
        if session_id and session_id != controller.active_session_id:
            return False
        channel = str(binding.mesh_channel or "base").strip().lower()
        if channel not in {"base", "base_color", "albedo"}:
            self.status_message_requested.emit(
                f"Mesh Editor DDS assignment does not support the {channel or 'unknown'} channel yet.",
                True,
            )
            return False
        try:
            dds_path = Path(dds_path_text).expanduser()
        except OSError:
            self.status_message_requested.emit(f"Mesh Editor DDS assignment path is invalid: {dds_path_text}", True)
            return False
        if not dds_path.is_file():
            self.status_message_requested.emit(f"Mesh Editor DDS assignment not found: {dds_path}", True)
            return False
        resolved = dds_path.resolve()
        try:
            mesh = controller.working_mesh(clone=False)
            submesh_count = len(tuple(getattr(mesh, "submeshes", ()) or ()))
            source_indices = tuple(index for index in source_indices if 0 <= index < submesh_count)
            if not source_indices:
                return False
            result = controller.apply_command(
                _tab.MeshEditCommand(
                    "material_assign",
                    selection=_tab.MeshEditSelection.from_maps(source_indices=source_indices),
                    mode="edit",
                    params={"texture": str(resolved)},
                    label="Assign DDS",
                )
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self.status_message_requested.emit(f"Mesh Editor DDS assignment failed: {exc}", True)
            return False
        if not result.ok:
            diagnostic = "; ".join(str(item) for item in tuple(result.diagnostics or ()) if str(item).strip())
            self.status_message_requested.emit(
                f"Mesh Editor DDS assignment made no changes{': ' + diagnostic if diagnostic else ''}.",
                False,
            )
            return False
        affected = tuple(result.affected_submesh_indices or source_indices)
        for submesh_index in affected:
            self.standalone_texture_preview_overrides.pop(int(submesh_index), None)
        self.update_editor_session_state(
            controller.session_view(),
            active_selection_mode=controller.active_selection_mode,
        )
        if self._standalone_dotnet_editor_process_running() and self._dotnet_resident_material_updates_supported():
            preview_updated = bool(
                self._send_dotnet_session_state()
                and self._send_dotnet_material_state(
                    reason="texture_editor_assign",
                    affected_submeshes=affected,
                )
            )
        else:
            update = controller.native_update_for_result(result)
            if self.standalone_native_host is not None:
                preview_updated = self._apply_standalone_native_update(update)
            elif self._standalone_native_preview_update_active():
                preview_updated = self.start_standalone_native_preview_async(reset_view=False)
            else:
                self._refresh_standalone_preview()
                preview_updated = True
        self._update_standalone_status()
        if not preview_updated:
            self.status_message_requested.emit(
                "DDS was assigned to the edit session, but the resident preview did not accept the update.",
                True,
            )
            return False
        self.status_message_requested.emit(f"Assigned Mesh Editor DDS: {resolved.name}", False)
        return True
    def apply_texture_editor_region_patch(self, patch: object) -> bool:
        lease = getattr(patch, "composite_lease", None)
        def reject() -> bool:
            release = getattr(lease, "release", None)
            if callable(release):
                release()
            return False
        binding = getattr(patch, "binding", None)
        if not isinstance(binding, _tab.TextureEditorSourceBinding):
            return reject()
        if str(binding.launch_origin or "") != "mesh_editor" or str(binding.texture_type or "") != "mesh_material":
            return reject()
        if not self._standalone_dotnet_editor_process_running() or not self._dotnet_resident_texture_region_updates_supported():
            return reject()
        controller = self._dotnet_target_controller()
        if controller is None:
            return reject()
        session_id, source_indices = _mesh_texture_binding_targets(binding)
        try:
            view = controller.session_view()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return reject()
        if not session_id or session_id != view.session_id or not source_indices:
            return reject()
        channel = str(binding.mesh_channel or "base").strip().lower()
        if channel not in {"base", "base_color", "albedo"}:
            return reject()
        try:
            material_state = _tab.mesh_dotnet_material_state_payload(
                controller.working_mesh(clone=False),
                session_id=view.session_id,
                edit_revision=view.revision,
                generation=0,
            )
            material_submeshes = tuple(material_state.get("submeshes", ()) or ())
            resolved_targets: list[tuple[int, str]] = []
            for source_index in source_indices:
                if not 0 <= source_index < len(material_submeshes):
                    continue
                item = material_submeshes[source_index]
                channels = item.get("channels", {}) if isinstance(item, dict) else {}
                resource_id = str(channels.get("base", "") or "") if isinstance(channels, dict) else ""
                if resource_id:
                    resolved_targets.append((int(item.get("submesh_index", source_index)), resource_id))
            resource_ids = {resource_id for _submesh_index, resource_id in resolved_targets}
            if len(resource_ids) != 1:
                return reject()
            resource_id = next(iter(resource_ids))
            package = self.standalone_dotnet_experiment_package
            package_output_dir = getattr(package, "output_dir", None) if package is not None else None
            request = ResidentTextureRegionRequest(
                session_id=view.session_id,
                edit_revision=view.revision,
                document_texture_revision=int(getattr(patch, "texture_revision", 0) or 0),
                resource_id=resource_id,
                channel="base",
                affected_submeshes=tuple(sorted({index for index, _resource in resolved_targets})),
                texture_width=int(getattr(patch, "texture_width", 0) or 0),
                texture_height=int(getattr(patch, "texture_height", 0) or 0),
                rect=tuple(int(value) for value in tuple(getattr(patch, "rect", ()) or ())),
                row_pitch=int(getattr(patch, "row_pitch", 0) or 0),
                bgra=bytes(getattr(patch, "bgra", b"") or b""),
                current_rgba=getattr(patch, "current_rgba"),
                composite_lease=getattr(patch, "composite_lease"),
                logical_path=str(
                    binding.relative_path
                    or binding.archive_relative_path
                    or binding.source_path
                    or ""
                ),
                mesh_service=controller.mesh_service,
                output_root=(Path(package_output_dir) / "texture-regions") if package_output_dir else None,
            )
            queued = self.standalone_texture_region_queue.enqueue(request)
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            self.status_message_requested.emit(f"Mesh texture region update was rejected: {exc}", True)
            return reject()
        if queued:
            self.standalone_dotnet_lifecycle_counts["texture_region_update_count"] = (
                int(self.standalone_dotnet_lifecycle_counts.get("texture_region_update_count", 0)) + 1
            )
        return queued if queued else reject()
    def apply_texture_editor_dds_preview(self, dds_path_text: str, binding: object) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None or not isinstance(binding, _tab.TextureEditorSourceBinding):
            return False
        if str(binding.launch_origin or "") != "mesh_editor" or str(binding.texture_type or "") != "mesh_material":
            return False
        session_id, source_indices = _mesh_texture_binding_targets(binding)
        submesh_index = source_indices[0] if source_indices else -1
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
        if (
            self._standalone_dotnet_editor_process_running()
            and self._dotnet_resident_material_updates_supported()
        ):
            mesh_snapshot = controller.working_mesh(clone=True)
            self._apply_texture_preview_overrides(mesh_snapshot)
            if self._send_dotnet_material_state(
                reason="texture_editor_preview",
                affected_submeshes=(int(submesh_index),),
                mesh_snapshot=mesh_snapshot,
            ):
                self.status_message_requested.emit(
                    f"Updating resident .NET Mesh Editor texture: {resolved.name}", False
                )
                return True
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
