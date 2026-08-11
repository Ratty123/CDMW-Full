from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cdmw.ui.archive_browser.static_replacement_viewport_display_modes import (
    MESH_PREVIEW_TEXTURED_DISPLAY_MODES,
    normalize_mesh_preview_display_mode,
    untextured_fallback_display_mode,
)
from cdmw.ui.mesh_editor.actions import NATIVE_EDITOR_SESSION_COMMANDS, normalize_mesh_selection_shape


from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_support import _validation_report_json_payload
from cdmw.ui.mesh_editor.tab_embedded_parts import MeshEditorEmbeddedPartsMixin


# How long a requested textured view waits for its resident material
# acknowledgement before the controls are put back to what the viewport is
# actually drawing.
PENDING_TEXTURED_VIEW_TIMEOUT_MS = 20_000

# The watchdog is there for a helper that never answers, not for work that is
# still running. Reading a full character's original textures out of the archive
# and compiling them routinely outlasts one interval, so each interval that ends
# with the compiler still busy buys another one, up to this many.
PENDING_TEXTURED_VIEW_MAX_EXTENSIONS = 9


class MeshEditorStateMixin(MeshEditorEmbeddedPartsMixin):
    def _entry_path(self, entry: object) -> str:
        return str(getattr(entry, "path", "") or getattr(entry, "name", "") or "").strip()
    def _entry_label(self, entry: object) -> str:
        return str(getattr(entry, "basename", "") or Path(self._entry_path(entry)).name or self._entry_path(entry) or "mesh").strip()
    def set_archive_selection(self, entry: Optional[_tab.ArchiveEntry]) -> None:
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
            self.current_request = _tab.MeshEditorSessionRequest(target_entry=entry, mode="modify_original")
        self._sync_state()
    def open_session(self, request: _tab.MeshEditorSessionRequest) -> None:
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
        publish_native: bool = True,
    ) -> None:
        if mode:
            self.current_edit_mode = str(mode)
        if active_selection_mode:
            self.current_selection_mode = normalize_mesh_selection_shape(active_selection_mode)
        if active_tool_key is not None:
            self.current_tool_action_key = str(active_tool_key)
        if selection_empty is not None:
            self.current_selection_empty = bool(selection_empty)
        if undo_count is not None:
            self.current_undo_count = max(0, int(undo_count or 0))
        if redo_count is not None:
            self.current_redo_count = max(0, int(redo_count or 0))
        self._sync_state()
        if publish_native:
            self._sync_standalone_native_mesh_edit_state()
    def update_editor_session_state(
        self,
        view: _tab.MeshEditSessionView | None,
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
        # A rebuild report goes stale when the geometry changes, not when the user
        # clicks a different part -- and this ran on every state refresh, so selecting
        # a part threw away a finished report the user could no longer inspect,
        # preview or package. Only a geometry command moves `revision`.
        stamped = self.standalone_rebuild_report_revision
        report_is_stale = (
            view is None
            or stamped is None
            or int(getattr(view, "revision", -1)) != int(stamped)
        )
        if callable(rebuild_updater) and report_is_stale:
            self.standalone_last_rebuild_report = None
            self.standalone_rebuild_report_revision = None
            rebuild_updater(None)
        if view is None:
            self.update_editor_action_state(
                mode="object",
                active_selection_mode="brush",
                selection_empty=True,
                undo_count=0,
                redo_count=0,
            )
            return
        self.update_editor_action_state(
            mode=str(view.mode or "object"),
            active_selection_mode=str(active_selection_mode or self.current_selection_mode or "brush"),
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
    def _refresh_standalone_export_validation(self, view: _tab.MeshEditSessionView | None) -> None:
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
        except Exception as exc:
            self._record_runtime_event("mesh_editor_export_validation_refresh_failed", error=str(exc))
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
    def _refresh_standalone_workspace_summary(self, view: _tab.MeshEditSessionView | None) -> None:
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
            # Best effort: standalone workspace summary is derived UI state.
            updater(None)
    def _refresh_standalone_uv_summary(self, view: _tab.MeshEditSessionView | None) -> None:
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
            # Best effort: standalone UV summary is derived UI state.
            updater(None)
    def _refresh_standalone_skeleton_summary(self, view: _tab.MeshEditSessionView | None) -> None:
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
            # Best effort: standalone skeleton summary is derived UI state.
            updater(None)
    def _refresh_standalone_compare_summary(self, view: _tab.MeshEditSessionView | None) -> None:
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
            # Best effort: standalone compare summary is derived UI state.
            updater(None)
    def _current_target_entry(self) -> Optional[_tab.ArchiveEntry]:
        if self.current_request is not None:
            return self.current_request.target_entry
        return self.current_archive_selection
    def _native_mesh_editor_available(self) -> bool:
        controller = getattr(self, "standalone_controller", None)
        if controller is not None and bool(getattr(controller, "active_session_id", "")):
            cached = getattr(self, "standalone_native_editor_available", None)
            if cached is not None:
                return bool(cached)
        try:
            return bool(_tab.native_mesh_core_available())
        except (OSError, RuntimeError, TypeError, ValueError):
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
        self.standalone_native_preview_button.setEnabled(False)
        self.action_bar.setVisible(False)
        task_active = (
            self._standalone_action_worker_active()
            or self._standalone_validation_worker_active()
            or self._standalone_rebuild_report_worker_active()
            or self._standalone_editable_package_task_active()
            or self._standalone_dotnet_package_worker_active()
            or self._standalone_dotnet_import_worker_active()
            or (
                self._standalone_dotnet_editor_process_running()
                and self.standalone_dotnet_embedded_state != "suspended"
            )
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
            dotnet_button.setEnabled(has_standalone and not task_active and not self._standalone_dotnet_editor_process_running())
        embedded_dotnet_button = getattr(self, "embedded_dotnet_editor_button", None)
        if embedded_dotnet_button is not None:
            try:
                embedded_dotnet_button.setEnabled(
                    self.workspace_stack.currentWidget() is self.embedded_builder_host
                    and not task_active
                    and not self._standalone_dotnet_editor_process_running()
                )
            except RuntimeError:
                # The modeless builder can be deleted before a queued archive
                # selection update reaches this tab.
                if embedded_dotnet_button is getattr(self, "embedded_dotnet_editor_button", None):
                    self.embedded_dotnet_editor_button = None
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
    def _embedded_builder_controller(self) -> _tab.MeshEditorController | None:
        builder = self.active_builder()
        getter = getattr(builder, "_mesh_editor_embedded_controller", None) if builder is not None else None
        if not callable(getter):
            return None
        try:
            controller = getter()
        except Exception:
            # Best effort: embedded builder controller lookup is optional UI state sync.
            return None
        return controller if isinstance(controller, _tab.MeshEditorController) else None
    def _refresh_embedded_workspace_from_builder(self) -> None:
        workspace = self.embedded_workspace
        if workspace is None:
            return
        controller = self._embedded_builder_controller()
        view: _tab.MeshEditSessionView | None = None
        if controller is not None:
            try:
                view = controller.session_view()
            except (AttributeError, RuntimeError, TypeError, ValueError):
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
                    # Best effort: workspace side panels are derived status only.
                    updater(None)
        workspace.update_rebuild_report(None)
        workspace.update_action_state(
            has_target=True,
            selection_empty=bool(view.selection.is_empty()),
            mode=str(view.mode or "edit"),
            active_selection_mode=str(getattr(controller, "active_selection_mode", "") or self.current_selection_mode or "brush"),
            undo_count=int(view.undo_count or 0),
            redo_count=int(view.redo_count or 0),
            native_editor_available=native_editor_available,
        )
        builder = self.active_builder()
        selection_changed = getattr(builder, "_mesh_editor_embedded_apply_part_selection_from_viewport", None)
        if callable(selection_changed):
            selection_changed(tuple(view.selection.source_indices))
    def _apply_embedded_native_update(self, update: _tab.MeshEditorNativeUpdate) -> bool:
        builder = self.active_builder()
        sender = getattr(builder, "_mesh_editor_embedded_apply_native_update", None) if builder is not None else None
        if callable(sender):
            try:
                return bool(sender(update))
            except Exception as exc:
                self._record_runtime_event("mesh_editor_embedded_native_update_failed", error=str(exc))
                return False
        return False
    def _send_embedded_dotnet_native_update(self, update: _tab.MeshEditorNativeUpdate) -> bool:
        if not (
            self.standalone_dotnet_target_embedded
            and self.standalone_dotnet_embedded_state == "ready"
            and self._standalone_dotnet_editor_process_running()
        ):
            return False
        self._send_dotnet_native_update(update)
        return True
    def _send_dotnet_scene_state(
        self,
        *,
        comparison_mode: str | None = None,
        interaction_mode: str | None = None,
        gizmo_tool: str | None = None,
        placement: Mapping[str, object] | None = None,
        source_identity: str = "",
        session_id: str = "",
    ) -> bool:
        if not self._standalone_dotnet_editor_process_running():
            return False
        if comparison_mode is not None:
            self.standalone_dotnet_scene_desired["comparison_mode"] = str(comparison_mode)
        if interaction_mode is not None:
            self.standalone_dotnet_scene_desired["interaction_mode"] = str(interaction_mode)
        if gizmo_tool is not None:
            self.standalone_dotnet_scene_desired["gizmo_tool"] = str(gizmo_tool)
        if placement is not None:
            return self._queue_dotnet_scene_frame_update()
        frame = self.standalone_dotnet_scene_candidate or self.standalone_dotnet_scene_frame
        if frame is None:
            # A first authoritative frame may still be calculating, but an
            # interaction transition cannot wait behind it: Finish Edit Mesh
            # must close the resident rails before the host reports success.
            # Publish the existing scene correlation without roles so the
            # helper changes only its interaction layout. The older worker is
            # made stale by the newer request id and cannot roll the mode back.
            return self._publish_dotnet_interaction_state(
                source_identity=source_identity,
                session_id=session_id,
            )
        # Mode-only transitions must not wait behind an older transform
        # calculation. Publishing the last authoritative frame with a newer
        # request id makes that worker result stale while keeping geometry and
        # placement recomputation off the UI thread.
        self.standalone_dotnet_scene_request_id += 1
        self.standalone_dotnet_scene_generation += 1
        try:
            frame = frame.with_protocol_context(
                scene_generation=self.standalone_dotnet_scene_generation,
                comparison_mode=str(self.standalone_dotnet_scene_desired["comparison_mode"]),
                interaction_mode=str(self.standalone_dotnet_scene_desired["interaction_mode"]),
            )
        except (AttributeError, TypeError, ValueError):
            return self._publish_dotnet_interaction_state(
                source_identity=source_identity,
                session_id=session_id,
            )
        return self._publish_dotnet_scene_frame(frame, self.standalone_dotnet_scene_request_id)

    def _publish_dotnet_interaction_state(
        self,
        *,
        source_identity: str = "",
        session_id: str = "",
    ) -> bool:
        source_identity = str(source_identity or "").strip()
        package = getattr(self, "standalone_dotnet_experiment_package", None)
        candidates = (
            self.standalone_dotnet_scene_candidate,
            self.standalone_dotnet_scene_frame,
            getattr(package, "scene_frame", None),
            self.standalone_dotnet_scene_acknowledged,
        )
        for candidate in candidates:
            if source_identity:
                break
            if isinstance(candidate, Mapping):
                value = candidate.get("source_identity", "")
            else:
                value = getattr(candidate, "source_identity", "")
            source_identity = str(value or "").strip()
            if source_identity:
                break
        # A correlated renderer request is the freshest session authority for
        # its response. Prefer it over cached lifecycle state so Finish cannot
        # be published back to a just-replaced session during reactivation.
        effective_session_id = str(
            session_id or self.standalone_dotnet_lifecycle_session_id or ""
        ).strip()
        if not source_identity or not effective_session_id:
            return False
        self.standalone_dotnet_scene_request_id += 1
        self.standalone_dotnet_scene_generation += 1
        request_id = self.standalone_dotnet_scene_request_id
        scene_generation = self.standalone_dotnet_scene_generation
        payload = {
            "event": "scene_state_update",
            "session_id": effective_session_id,
            "request_id": request_id,
            "process_generation": self.standalone_dotnet_process_generation,
            "protocol_version": 2,
            "source_identity": source_identity,
            "scene_generation": scene_generation,
            "comparison_mode": str(self.standalone_dotnet_scene_desired["comparison_mode"]),
            "interaction_mode": str(self.standalone_dotnet_scene_desired["interaction_mode"]),
            "gizmo": {
                "visible": True,
                "tool": str(self.standalone_dotnet_scene_desired["gizmo_tool"]),
                "space": "world",
            },
        }
        sent = self._send_dotnet_protocol_message(payload)
        if sent:
            self.standalone_dotnet_scene_candidate = None
            self.standalone_dotnet_scene_pending = {
                "session_id": effective_session_id,
                "request_id": request_id,
                "process_generation": self.standalone_dotnet_process_generation,
                "source_identity": source_identity,
                "scene_generation": scene_generation,
                "interaction_only": True,
            }
            self._flush_dotnet_protocol_messages()
            self._record_mesh_dotnet_event(
                "mesh_dotnet_scene_interaction_sent",
                request_id=request_id,
                scene_generation=scene_generation,
                interaction_mode=str(payload["interaction_mode"]),
            )
        return bool(sent)


    def _queue_dotnet_scene_frame_update(self) -> bool:
        controller = self._dotnet_target_controller()
        transform = self._dotnet_current_scene_transform(
            embedded=bool(self.standalone_dotnet_target_embedded)
        )
        if controller is None or transform is None:
            return False
        reference = self._dotnet_reference_mesh_for_package(
            controller,
            embedded=bool(self.standalone_dotnet_target_embedded),
        )
        if not isinstance(reference, _tab.ParsedMesh):
            return False
        base_frame = self.standalone_dotnet_scene_candidate or self.standalone_dotnet_scene_frame
        source_identity = str(getattr(base_frame, "source_identity", "") or "")
        if not source_identity:
            return False
        self.standalone_dotnet_scene_request_id += 1
        self.standalone_dotnet_scene_generation += 1
        spec = {
            "request_id": self.standalone_dotnet_scene_request_id,
            "generation": self.standalone_dotnet_scene_generation,
            "controller": controller,
            "reference": reference,
            "transform": transform,
            "source_identity": source_identity,
            "comparison_mode": str(self.standalone_dotnet_scene_desired["comparison_mode"]),
            "interaction_mode": str(self.standalone_dotnet_scene_desired["interaction_mode"]),
        }
        if self.standalone_dotnet_scene_thread is not None:
            self.standalone_dotnet_scene_queued = spec
            worker = self.standalone_dotnet_scene_worker
            if worker is not None:
                worker.stop()
            return True
        self._start_dotnet_scene_frame_worker(spec)
        return True

    def _start_dotnet_scene_frame_worker(self, spec: Mapping[str, object]) -> None:
        controller = spec["controller"]
        worker = _tab.MeshDotNetSceneFrameWorker(
            int(spec["request_id"]),
            controller.mesh_service,
            self.standalone_dotnet_lifecycle_session_id,
            spec["reference"],
            spec["transform"],
            source_identity=str(spec["source_identity"]),
            scene_generation=int(spec["generation"]),
            comparison_mode=str(spec["comparison_mode"]),
            interaction_mode=str(spec["interaction_mode"]),
        )
        thread = _tab.QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_dotnet_scene_frame_ready)
        worker.error.connect(self._handle_dotnet_scene_frame_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda target_thread=thread, target_worker=worker: self._cleanup_dotnet_scene_frame_worker(
                target_thread, target_worker
            )
        )
        self.standalone_dotnet_scene_thread = thread
        self.standalone_dotnet_scene_worker = worker
        thread.start(_tab.QThread.LowPriority)

    def _cleanup_dotnet_scene_frame_worker(self, thread: object, worker: object) -> None:
        if self.standalone_dotnet_scene_thread is thread:
            self.standalone_dotnet_scene_thread = None
        if self.standalone_dotnet_scene_worker is worker:
            self.standalone_dotnet_scene_worker = None
        queued = self.standalone_dotnet_scene_queued
        self.standalone_dotnet_scene_queued = None
        if queued is not None and self._standalone_dotnet_editor_process_running():
            self._start_dotnet_scene_frame_worker(queued)

    def _handle_dotnet_scene_frame_ready(
        self,
        request_id: int,
        frame: object,
        elapsed_ms: float,
    ) -> None:
        if int(request_id) != int(self.standalone_dotnet_scene_request_id):
            return
        if not self._standalone_dotnet_editor_process_running():
            return
        try:
            frame = frame.with_protocol_context(
                comparison_mode=str(self.standalone_dotnet_scene_desired["comparison_mode"]),
                interaction_mode=str(self.standalone_dotnet_scene_desired["interaction_mode"]),
            )
        except (AttributeError, TypeError, ValueError):
            return
        if self._publish_dotnet_scene_frame(frame, int(request_id)):
            self._record_mesh_dotnet_event(
                "mesh_dotnet_scene_frame_sent",
                request_id=int(request_id),
                scene_generation=int(getattr(frame, "scene_generation", 0) or 0),
                elapsed_ms=float(elapsed_ms),
            )

    def _handle_dotnet_scene_frame_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_dotnet_scene_request_id):
            return
        self._set_dotnet_status(
            f"Could not calculate the authoritative resident scene frame: {message}",
            error=True,
        )

    def _publish_dotnet_scene_frame(self, frame: object, request_id: int) -> bool:
        try:
            payload = dict(frame.to_protocol_payload())
        except (AttributeError, TypeError, ValueError):
            return False
        payload.update({
            "event": "scene_state_update",
            "session_id": self.standalone_dotnet_lifecycle_session_id,
            "request_id": int(request_id),
            "process_generation": self.standalone_dotnet_process_generation,
            "protocol_version": 2,
        })
        payload["gizmo"] = {
            "visible": True,
            "tool": str(self.standalone_dotnet_scene_desired["gizmo_tool"]),
            "space": "world",
        }
        sent = self._send_dotnet_protocol_message(payload)
        if sent:
            self.standalone_dotnet_scene_candidate = frame
            self.standalone_dotnet_scene_pending = {
                "session_id": self.standalone_dotnet_lifecycle_session_id,
                "request_id": int(request_id),
                "process_generation": self.standalone_dotnet_process_generation,
                "source_identity": str(payload.get("source_identity", "") or ""),
                "scene_generation": int(payload.get("scene_generation", 0) or 0),
            }
            self._flush_dotnet_protocol_messages()
        return bool(sent)
    def _handle_embedded_viewport_display_mode(
        self,
        mode: str,
        *,
        use_presentation_state: bool = False,
    ) -> bool:
        normalized = normalize_mesh_preview_display_mode(mode or "textured")
        # Remember the reader's choice before anything can return early. The
        # presentation snapshot is rebuilt after every accepted scene frame, and
        # while Edit Mesh is active it falls back to Wire + Vertices whenever
        # this slot is empty -- so a mode chosen here but not recorded survived
        # only until the next selection or frame landed, which is what read as
        # "it reverts on its own". Several branches below return before reaching
        # sync_viewport_display_combos, and each one used to leave the slot
        # unset; recording it up front makes the choice stick regardless of
        # which path the request takes.
        self._remember_mesh_edit_display_mode(normalized)
        self._remember_dotnet_desired_display_mode(normalized)
        # Any explicit request supersedes a textured view this tab is still
        # hoping to restore on its own, so it must never snap back later.
        self._forget_deferred_textured_view()
        if not bool(getattr(self.active_builder(), "_mesh_editor_embedded_dotnet_active", False)):
            if normalized in MESH_PREVIEW_TEXTURED_DISPLAY_MODES:
                fallback_mode = untextured_fallback_display_mode(normalized)
                self._remember_dotnet_desired_display_mode(fallback_mode)
                self.sync_viewport_display_combos(fallback_mode)
            self.status_message_requested.emit("Embedded .NET viewport is not ready yet.", True)
            return False
        if "viewport_display_modes_v1" not in self.standalone_dotnet_capabilities:
            if normalized in MESH_PREVIEW_TEXTURED_DISPLAY_MODES:
                fallback_mode = untextured_fallback_display_mode(normalized)
                self._remember_dotnet_desired_display_mode(fallback_mode)
                self.sync_viewport_display_combos(fallback_mode)
            self.status_message_requested.emit("Embedded .NET viewport does not support display-mode updates.", True)
            return False
        if normalized in MESH_PREVIEW_TEXTURED_DISPLAY_MODES:
            if not self._dotnet_resident_material_updates_supported():
                fallback_mode = untextured_fallback_display_mode(normalized)
                self._remember_dotnet_desired_display_mode(fallback_mode)
                self._send_embedded_viewport_display_mode(fallback_mode)
                self.sync_viewport_display_combos(fallback_mode)
                self.status_message_requested.emit(
                    "This .NET helper cannot load Mesh Editor textures in place. Update the helper; the untextured scene remains active.",
                    True,
                )
                return False
            builder = self.active_builder()
            request_textures = getattr(
                builder,
                "_mesh_editor_embedded_request_material_resources",
                None,
            )
            if self._dotnet_material_roles_ready():
                sent = self._send_requested_viewport_display_mode(
                    normalized,
                    use_presentation_state=use_presentation_state,
                )
                if sent:
                    self.sync_viewport_display_combos(normalized)
                    self._request_reference_textures_for_textured_view(
                        request_textures
                    )
                else:
                    fallback_mode = untextured_fallback_display_mode(normalized)
                    self._remember_dotnet_desired_display_mode(fallback_mode)
                    self.sync_viewport_display_combos(fallback_mode)
                return sent
            if not callable(request_textures):
                fallback_mode = untextured_fallback_display_mode(normalized)
                self._remember_dotnet_desired_display_mode(fallback_mode)
                self._send_embedded_viewport_display_mode(fallback_mode)
                self.sync_viewport_display_combos(fallback_mode)
                self.status_message_requested.emit(
                    "No texture resolver is available for this Mesh Editor session; the untextured scene remains active.",
                    True,
                )
                return False
            self.standalone_dotnet_pending_textured_view = True
            self.standalone_dotnet_pending_textured_view_mode = normalized
            self.standalone_dotnet_pending_textured_view_uses_presentation = bool(
                use_presentation_state
            )
            self.standalone_dotnet_pending_textured_view_extensions = 0
            fallback_mode = untextured_fallback_display_mode(normalized)
            self._send_requested_viewport_display_mode(
                fallback_mode,
                use_presentation_state=use_presentation_state,
                texture_request_pending=True,
                requested_mode=normalized,
            )
            self._remember_dotnet_desired_display_mode(fallback_mode)
            self.sync_viewport_display_combos(fallback_mode)
            self.status_message_requested.emit(
                "Loading Mesh Editor textures in the resident viewport...",
                False,
            )
            self._settle_requested_textured_view(request_textures())
            return True
        self.standalone_dotnet_pending_textured_view = False
        self.standalone_dotnet_pending_textured_view_mode = "textured"
        self.standalone_dotnet_pending_textured_view_uses_presentation = False
        sent = self._send_requested_viewport_display_mode(
            normalized,
            use_presentation_state=use_presentation_state,
        )
        if sent:
            self.sync_viewport_display_combos(normalized)
        return sent

    def _request_reference_textures_for_textured_view(self, request_textures: object) -> None:
        """Kick the Original pane's lazy texture resolve without waiting on it.

        Failures are reported by the resolver itself. They must not be raised as
        a textured-view failure here: the editable pane really is textured, and
        an error banner over a correct preview reads as the mode not having
        worked at all.
        """
        if not callable(request_textures):
            return
        try:
            request_textures()
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            self._record_mesh_dotnet_event(
                "mesh_dotnet_reference_texture_request_failed",
                error=str(exc),
            )

    def _settle_requested_textured_view(self, outcome: object) -> None:
        """Resolve a textured-view request whose resolver started no worker.

        A resolver that returns without starting anything sends no material
        update, so no `material_state_applied` is coming and nothing would ever
        clear `standalone_dotnet_pending_textured_view`. The viewport then sat
        on the untextured fallback while the Mesh view control still read
        "Solid (Textured)".
        """
        if not bool(self.standalone_dotnet_pending_textured_view):
            return
        normalized = str(outcome or "started").strip().lower()
        if normalized in {"unavailable", "failed"}:
            self._finish_pending_textured_view(
                success=False,
                reason=f"texture_resolver_{normalized}",
            )
            self.status_message_requested.emit(
                "No resolved textures are available for this Mesh Editor preview; the untextured scene remains active.",
                True,
            )
            return
        if (
            normalized == "already_loaded"
            and self._dotnet_material_roles_ready()
        ):
            # The resolved materials were already resident, so the republish
            # deduplicated and there is no acknowledgement left to wait for.
            # "Already resident" requires something to have been applied: the
            # generations both start at zero, so without that guard this declared
            # success before any material had ever reached the viewport.
            self._finish_pending_textured_view(success=True)
            return
        self._arm_pending_textured_view_watchdog()

    def _arm_pending_textured_view_watchdog(self) -> None:
        timer = getattr(self, "standalone_dotnet_pending_textured_view_timer", None)
        if timer is None:
            return
        timer.start(PENDING_TEXTURED_VIEW_TIMEOUT_MS)

    def _handle_pending_textured_view_timeout(self) -> None:
        if not bool(self.standalone_dotnet_pending_textured_view):
            return
        # Abandoning a compile that is still running is what left the viewport
        # flat: the materials landed seconds later and the acknowledgement then
        # had nothing left to complete. While the compiler is genuinely busy the
        # wait is making progress, so extend it instead of declaring failure.
        if (
            self._dotnet_material_compile_active()
            and self.standalone_dotnet_pending_textured_view_extensions
            < PENDING_TEXTURED_VIEW_MAX_EXTENSIONS
        ):
            self.standalone_dotnet_pending_textured_view_extensions += 1
            self._arm_pending_textured_view_watchdog()
            self.status_message_requested.emit(
                "Still preparing Mesh Editor textures for the resident viewport...",
                False,
            )
            return
        self._finish_pending_textured_view(
            success=False,
            reason="acknowledgement_timeout",
        )
        missing = self._dotnet_missing_material_roles()
        missing_text = ", ".join(
            self._dotnet_material_role_label(role) for role in missing
        )
        self.status_message_requested.emit(
            f"{missing_text or 'Mesh Editor'} textures did not reach the resident viewport in time; the untextured scene remains active.",
            True,
        )

    def _send_requested_viewport_display_mode(
        self,
        normalized: str,
        *,
        use_presentation_state: bool,
        texture_request_pending: bool = False,
        requested_mode: str = "",
    ) -> bool:
        if texture_request_pending:
            # A fallback is an effective renderer state, never presentation
            # authority. Use the narrow display message so the full desired
            # snapshot continues to remember Solid (Textured).
            return self._send_embedded_viewport_display_mode(
                normalized,
                texture_request_pending=True,
                requested_mode=requested_mode,
            )
        if use_presentation_state:
            return self._send_dotnet_presentation_state(
                {"display": {"mode": normalized}}
            )
        return self._send_embedded_viewport_display_mode(
            normalized,
            texture_request_pending=texture_request_pending,
        )

    def _send_embedded_viewport_display_mode(
        self,
        normalized: str,
        *,
        texture_request_pending: bool = False,
        requested_mode: str = "",
    ) -> bool:
        self.standalone_dotnet_viewport_display_request_id += 1
        payload: dict[str, object] = {
            "event": "viewport_display_update",
            "session_id": self.standalone_dotnet_lifecycle_session_id,
            "request_id": self.standalone_dotnet_viewport_display_request_id,
            "process_generation": self.standalone_dotnet_process_generation,
            "protocol_version": 2,
            "mode": normalized,
        }
        if texture_request_pending:
            payload["texture_request_pending"] = True
            payload["requested_mode"] = normalize_mesh_preview_display_mode(
                requested_mode or "textured"
            )
        sent = self._send_dotnet_protocol_message(payload)
        if not sent:
            self.status_message_requested.emit("Could not update embedded .NET viewport display mode.", True)
            return sent
        # The display mode is part of the presentation snapshot, and this is the
        # other channel that changes it. Both records have to follow it.
        #
        # The desired snapshot is what every later publish sends, and a publish
        # is triggered by things that carry no mode of their own -- a part
        # highlight, a visibility change, an armed tool. Leaving the old mode in
        # it meant the next of those re-asserted the mode the reader had just
        # moved away from: picking Solid (Textured) and then selecting a part
        # snapped the viewport back to Wire + Vertices, and the same publish in
        # placement snapped it back to Faces + Wire.
        if not texture_request_pending:
            self._remember_dotnet_desired_display_mode(normalized)
        return sent

    def _remember_dotnet_desired_display_mode(self, normalized: str) -> None:
        display = self.standalone_dotnet_presentation_desired.get("display")
        if not isinstance(display, dict):
            display = {}
            self.standalone_dotnet_presentation_desired["display"] = display
        display["mode"] = normalized
        # The record of what the helper is holding no longer describes it, so it
        # must not be used to skip a later presentation publish as
        # already-applied -- that would leave the helper on the mode this
        # message set with no way to move it back.
        self.standalone_dotnet_presentation_published_content = None
