from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence

from PySide6.QtCore import QThread



from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


class MeshEditorDotNetLaunchMixin:
    def _record_mesh_dotnet_event(self, event: str, **payload: object) -> None:
        event_name = str(event or "").strip()
        if not event_name:
            return
        normalized = {str(key): self._json_safe_runtime_value(value) for key, value in payload.items()}
        builder = self.active_builder()
        for target in (builder, self.parent()):
            recorder = getattr(target, "_record_runtime_event", None) if target is not None else None
            if callable(recorder):
                try:
                    recorder(event_name, **normalized)
                    return
                except TypeError:
                    try:
                        recorder(event_name, normalized)
                        return
                    except Exception:
                        # Best effort: runtime-event sinks are optional diagnostics.
                        pass
                except Exception:
                    # Best effort: a broken parent/builder recorder must not fail UI work.
                    pass
        try:
            self.runtime_event_requested.emit(event_name, normalized)
        except RuntimeError:
            pass
    @staticmethod
    def _json_safe_runtime_value(value: object) -> object:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, Mapping):
            return {str(key): MeshEditorDotNetLaunchMixin._json_safe_runtime_value(item) for key, item in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [MeshEditorDotNetLaunchMixin._json_safe_runtime_value(item) for item in tuple(value)]
        return str(value)
    def _dotnet_editor_executable_resolution(self, *, log: bool = True) -> object:
        raw = str(self.settings.value("mesh_editor/dotnet_experiment_executable", "") or "").strip()
        resolution = _tab.resolve_mesh_dotnet_experiment_editor(raw)
        if log:
            self._record_mesh_dotnet_event("mesh_dotnet_executable_resolved", **resolution.as_event_payload())
        return resolution
    def _dotnet_editor_executable_path(self, *, log: bool = True) -> Path | None:
        resolution = self._dotnet_editor_executable_resolution(log=log)
        if not resolution.is_file or not resolution.resolved_path:
            return None
        return Path(resolution.resolved_path)
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
    def _start_dotnet_editor_requested(self, controller: _tab.MeshEditorController, *, embedded: bool) -> None:
        existing_controller = self.standalone_dotnet_target_controller
        self.standalone_dotnet_target_embedded = bool(embedded)
        self.standalone_dotnet_embedded_exit_finalized = False
        self.standalone_dotnet_exit_pending = False
        self.standalone_dotnet_deactivate_acknowledged = False
        self.standalone_dotnet_deactivate_timer.stop()
        if embedded and self._standalone_dotnet_editor_process_running():
            try:
                same_session = bool(
                    existing_controller is not None
                    and existing_controller.session_view().session_id == controller.session_view().session_id
                )
                current_material_signature = _tab.mesh_dotnet_material_input_signature(
                    controller.working_mesh(clone=False)
                )
                cached_material_signature = str(
                    self.standalone_dotnet_material_signature
                    or getattr(self.standalone_dotnet_experiment_package, "material_signature", "")
                    or ""
                )
                same_materials = bool(
                    cached_material_signature
                    and current_material_signature == cached_material_signature
                )
            except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
                same_session = False
                same_materials = False
                current_material_signature = ""
            resident_materials = self._dotnet_resident_material_updates_supported()
            if same_session and (same_materials or resident_materials):
                self.standalone_dotnet_target_controller = controller
                self._set_embedded_dotnet_state("launching", active=False)
                if self._send_dotnet_protocol_message(
                    {
                        "event": "activate_request",
                        "material_signature": current_material_signature,
                        "material_generation": self.standalone_dotnet_material_generation + (0 if same_materials else 1),
                    }
                ):
                    self._flush_dotnet_protocol_messages()
                    self._send_dotnet_session_state()
                    self.standalone_dotnet_ready_timer.start(10_000)
                    self._set_dotnet_status(
                        "Restoring cached Mesh .NET editor session..."
                        if same_materials
                        else "Synchronizing changed materials with the resident Mesh .NET editor..."
                    )
                    return
                self._stop_standalone_dotnet_editor_process(embedded_state="failed")
            else:
                if same_session and not same_materials:
                    self.standalone_dotnet_lifecycle_counts["full_reload_count"] += 1
                self._stop_standalone_dotnet_editor_process()
        executable = self._dotnet_editor_executable_path()
        builder = self.active_builder() if embedded else None
        if builder is not None:
            setattr(builder, "_mesh_editor_dotnet_available", bool(executable is not None and executable.is_file()))
        if executable is None or not executable.is_file():
            if embedded:
                self._set_embedded_dotnet_state("failed", active=False)
            message = (
                "Mesh .NET editor experiment is not configured. Set "
                "mesh_editor/dotnet_experiment_executable, CDMW_MESH_DOTNET_EXPERIMENT_EXE, or build the bundled helper."
            )
            self._record_mesh_dotnet_event(
                "mesh_dotnet_process_start_failed",
                embedded=bool(embedded),
                program=str(executable or ""),
                qprocess_error="missing_executable",
                qprocess_error_string=message,
            )
            self._set_dotnet_status(message, error=True)
            if embedded:
                self._notify_embedded_dotnet_launch_failed("mesh_dotnet_missing_executable", diagnostics=message)
            return
        if self._standalone_dotnet_package_worker_active():
            self._set_dotnet_status("Mesh .NET editor package is already preparing.")
            return
        if self._standalone_dotnet_editor_process_running():
            self._set_dotnet_status("Mesh .NET editor experiment is already running.")
            return
        session_id = controller.session_view().session_id
        if self.standalone_dotnet_lifecycle_session_id != session_id:
            self.standalone_dotnet_lifecycle_session_id = session_id
            for key in self.standalone_dotnet_lifecycle_counts:
                self.standalone_dotnet_lifecycle_counts[key] = 0
            self.standalone_dotnet_material_generation = 0
            self.standalone_dotnet_applied_material_generation = 0
            self.standalone_dotnet_completed_material_generation = 0
            self.standalone_dotnet_material_signature = ""
        self.standalone_dotnet_package_request_id += 1
        request_id = self.standalone_dotnet_package_request_id
        self.standalone_dotnet_target_controller = controller
        if embedded:
            self._set_embedded_dotnet_state("launching", active=False)
        self._record_mesh_dotnet_event(
            "mesh_dotnet_package_start",
            request_id=request_id,
            session_id=session_id,
            embedded=bool(embedded),
            executable=str(executable),
        )
        worker = _tab.MeshDotNetExperimentPackageWorker(request_id, controller.mesh_service, session_id)
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
        if not isinstance(package_object, _tab.MeshDotNetExperimentPackage):
            self._record_mesh_dotnet_event(
                "mesh_dotnet_package_error",
                request_id=request_id,
                embedded=bool(self.standalone_dotnet_target_embedded),
                elapsed_ms=float(elapsed_ms),
                error="package worker returned an invalid package",
            )
            self._set_dotnet_status("Mesh .NET editor package worker returned an invalid package.", error=True)
            return
        self.standalone_dotnet_lifecycle_counts["package_build_count"] += 1
        if self.standalone_dotnet_lifecycle_counts["initial_package_build_count"] == 0:
            self.standalone_dotnet_lifecycle_counts["initial_package_build_count"] = 1
        self._record_mesh_dotnet_event(
            "mesh_dotnet_package_ready",
            request_id=request_id,
            embedded=bool(self.standalone_dotnet_target_embedded),
            package_dir=str(package_object.package_dir),
            mesh_path=str(package_object.mesh_path),
            metadata_path=str(package_object.cdmeta_path),
            status_path=str(package_object.status_path),
            edit_operations_path=str(package_object.edit_operations_path),
            elapsed_ms=float(elapsed_ms),
        )
        if self._launch_standalone_dotnet_editor_package(package_object):
            self.status_message_requested.emit(
                f"Mesh .NET editor experiment package ready ({float(elapsed_ms):.1f} ms).",
                False,
            )
    def _handle_standalone_dotnet_package_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_dotnet_package_request_id):
            return
        text = f"Mesh .NET editor experiment package failed: {message}"
        self._record_mesh_dotnet_event(
            "mesh_dotnet_package_error",
            request_id=request_id,
            embedded=bool(self.standalone_dotnet_target_embedded),
            error=str(message),
        )
        if self.standalone_dotnet_target_embedded:
            self._set_embedded_dotnet_state("failed", active=False)
        self._set_dotnet_status(text, error=True)
        if self.standalone_dotnet_target_embedded:
            self._notify_embedded_dotnet_launch_failed("mesh_dotnet_package_error", diagnostics=str(message))
    def _cleanup_standalone_dotnet_package_worker(
        self,
        thread: QThread,
        worker: _tab.MeshDotNetExperimentPackageWorker,
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
        package: _tab.MeshDotNetExperimentPackage,
        status_payload: Mapping[str, object],
    ) -> bool:
        if not self._handle_dotnet_renderer_status(
            status_payload,
            source_event="output_import",
        ):
            return False
        if self.standalone_dotnet_target_embedded:
            return self._complete_embedded_dotnet_exit("dotnet_output_ignored")
        controller = self.standalone_dotnet_target_controller or self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Mesh .NET editor output import unavailable: no active session.", True)
            return False
        if self._standalone_dotnet_import_worker_active():
            self.status_message_requested.emit("Mesh .NET editor output import is already running.", False)
            return False
        self.standalone_dotnet_import_request_id += 1
        request_id = self.standalone_dotnet_import_request_id
        worker = _tab.MeshDotNetExperimentOutputImportWorker(
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
        if not isinstance(view, _tab.MeshEditSessionView):
            self._set_dotnet_status("Mesh .NET editor output import returned an invalid session view.", error=True)
            return
        controller = self.standalone_dotnet_target_controller or self.standalone_controller
        if controller is None:
            return
        if self.standalone_dotnet_target_embedded:
            if not self._complete_embedded_dotnet_exit("dotnet_output_import"):
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
                evaluation_path = _tab.write_mesh_dotnet_experiment_evaluation(
                    package,
                    self.standalone_dotnet_status_payload,
                    validation_report=validation,
                )
            except Exception as exc:
                self._record_mesh_dotnet_event("mesh_dotnet_evaluation_write_failed", error=str(exc))
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
        if self.standalone_dotnet_target_embedded:
            self._complete_embedded_dotnet_exit("dotnet_output_import_error")
    def _cleanup_standalone_dotnet_import_worker(
        self,
        thread: QThread,
        worker: _tab.MeshDotNetExperimentOutputImportWorker,
    ) -> None:
        if self.standalone_dotnet_import_thread is thread:
            self.standalone_dotnet_import_thread = None
        if self.standalone_dotnet_import_worker is worker:
            self.standalone_dotnet_import_worker = None
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
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
    def _complete_embedded_dotnet_exit(self, reason: str, *, final_state: str = "closed") -> bool:
        if not self.standalone_dotnet_target_embedded:
            return False
        if self.standalone_dotnet_embedded_exit_finalized:
            return True
        if not self._finalize_embedded_dotnet_import(str(reason or "dotnet_exit")):
            self._set_embedded_dotnet_state("failed", active=False)
            self._notify_embedded_dotnet_launch_failed("mesh_edit_dotnet_save_failed")
            return False
        self.standalone_dotnet_embedded_exit_finalized = True
        self.standalone_dotnet_exit_pending = False
        self.standalone_dotnet_deactivate_acknowledged = False
        self.standalone_dotnet_deactivate_timer.stop()
        self._set_embedded_dotnet_state(final_state, active=False)
        self._refresh_embedded_workspace_from_builder()
        return True
    def _complete_pending_dotnet_exit(self) -> None:
        if not self.standalone_dotnet_exit_pending or not self.standalone_dotnet_deactivate_acknowledged:
            return
        if self._standalone_action_worker_active():
            return
        self._complete_embedded_dotnet_exit("dotnet_deactivated", final_state="suspended")
    def _dotnet_target_controller(self) -> _tab.MeshEditorController | None:
        return self.standalone_dotnet_target_controller or self.standalone_controller
    def _notify_embedded_dotnet_ready(self) -> None:
        builder = self.active_builder()
        callback = getattr(builder, "_mesh_editor_embedded_dotnet_ready", None) if builder is not None else None
        if callable(callback):
            try:
                callback()
            except Exception as exc:
                self._record_mesh_dotnet_event("mesh_dotnet_ready_callback_error", error=str(exc))
    def _notify_embedded_dotnet_launch_failed(self, reason: str, *, diagnostics: str = "") -> None:
        if self.standalone_dotnet_target_embedded:
            self._set_embedded_dotnet_state("failed", active=False)
        builder = self.active_builder()
        callback = getattr(builder, "_mesh_editor_embedded_dotnet_failed", None) if builder is not None else None
        if callable(callback):
            try:
                callback(str(reason or "mesh_edit_dotnet_fallback"), str(diagnostics or ""))
                return
            except Exception as exc:
                self._record_mesh_dotnet_event("mesh_dotnet_failed_callback_error", reason=reason, error=str(exc))
