from __future__ import annotations

import json
import time
from typing import Mapping

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import QProgressDialog



from cdmw.services.mesh_editor_error_codes import MeshEditorErrorCode, error_payload
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_dotnet_session_events import (
    MeshEditorDotNetSessionEventMixin,
)
from cdmw.ui.mesh_editor.tab_support import _mesh_edit_result_with_metric


class MeshEditorDotNetProcessMixin(MeshEditorDotNetSessionEventMixin):
    def _launch_standalone_dotnet_editor_package(self, package: _tab.MeshDotNetExperimentPackage) -> bool:
        executable = self._dotnet_editor_executable_path()
        if executable is None or not executable.is_file():
            message = "Mesh .NET/Vortice helper executable is missing."
            self._record_mesh_dotnet_event(
                "mesh_dotnet_process_start_failed",
                embedded=bool(self.standalone_dotnet_target_embedded),
                program=str(executable or ""),
                qprocess_error="missing_executable",
                qprocess_error_string=message,
                package_dir=str(package.package_dir),
            )
            if self.standalone_dotnet_target_embedded:
                self._set_embedded_dotnet_state("failed", active=False)
                self._notify_embedded_dotnet_launch_failed("mesh_dotnet_missing_executable", diagnostics=message)
            self._set_dotnet_status(message, error=True)
            return False
        host = (
            self.standalone_native_host
            if self.standalone_dotnet_target_embedded
            else getattr(self, "standalone_native_host_frame", None)
        )
        controller = getattr(host, "controller", None)
        if controller is None:
            self._set_dotnet_status("Mesh Editor .NET/Vortice host is unavailable.", error=True)
            return False
        self._wire_shared_dotnet_controller(host)
        target = self._dotnet_target_controller()
        if target is not None:
            try:
                session_bound = bool(
                    controller.set_authoritative_session_id(target.session_view().session_id)
                )
            except (AttributeError, RuntimeError, TypeError, ValueError):
                session_bound = False
            if not session_bound:
                self._set_dotnet_status(
                    "Mesh Editor authoring session changed while the resident helper was active. Close the current editor before opening another mesh.",
                    error=True,
                )
                if self.standalone_dotnet_target_embedded:
                    self._set_embedded_dotnet_state("failed", active=False)
                return False
        controller.set_configured_executable(executable)
        self.standalone_dotnet_stdout_tail = ""
        self.standalone_dotnet_stderr_tail = ""
        self.standalone_dotnet_last_program = str(executable)
        self.standalone_dotnet_last_arguments = ["--profile", "authoring"]
        self.standalone_dotnet_last_working_directory = str(package.package_dir)
        self.standalone_dotnet_experiment_package = package
        self.standalone_dotnet_material_signature = str(package.material_signature or "")
        self.standalone_dotnet_scene_request_id = 0
        self.standalone_dotnet_scene_generation = int(
            getattr(package.scene_frame, "scene_generation", 0) or 0
        )
        self.standalone_dotnet_scene_acknowledged_generation = 0
        self.standalone_dotnet_scene_pending = None
        self.standalone_dotnet_scene_acknowledged = None
        self.standalone_dotnet_scene_candidate = None
        self.standalone_dotnet_scene_frame = package.scene_frame
        self.standalone_dotnet_scene_queued = None
        if package.scene_frame is not None:
            self.standalone_dotnet_scene_desired.update(
                {
                    "comparison_mode": str(package.scene_frame.comparison_mode),
                    "interaction_mode": str(package.scene_frame.interaction_mode),
                }
            )
        try:
            host.show()
            if hasattr(self, "standalone_preview_stack") and not self.standalone_dotnet_target_embedded:
                self.standalone_preview_stack.setCurrentWidget(host)
        except (AttributeError, RuntimeError):
            pass
        if not host.load_package(package, reset_view=self.standalone_dotnet_editor_process is None):
            self._set_dotnet_status("Mesh Editor .NET/Vortice host rejected the authoring package.", error=True)
            if self.standalone_dotnet_target_embedded:
                self._set_embedded_dotnet_state("failed", active=False)
            return False
        self._sync_shared_dotnet_process_identity(controller)
        self.standalone_dotnet_update_queue.set_context(
            session_id=self.standalone_dotnet_lifecycle_session_id,
            process_generation=self.standalone_dotnet_process_generation,
        )
        self._record_mesh_dotnet_event(
            "mesh_dotnet_shared_host_load",
            embedded=bool(self.standalone_dotnet_target_embedded),
            package_dir=str(package.package_dir),
            process_generation=self.standalone_dotnet_process_generation,
        )
        if self.standalone_dotnet_target_embedded:
            self._set_embedded_dotnet_state("launching", active=False)
        self._set_dotnet_status("Loading Mesh Editor in the resident .NET/Vortice viewport...")
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        return True
    def _confirm_dotnet_process_started(self, process: _tab.QProcess) -> bool:
        try:
            return process.state() != _tab.QProcess.NotRunning
        except RuntimeError:
            return False
    def _dotnet_process_diagnostics(self, process: _tab.QProcess) -> str:
        payload = self._dotnet_process_event_payload(process)
        pieces: list[str] = []
        for key in ("qprocess_error_string", "stderr_tail", "stdout_tail", "status_message"):
            value = str(payload.get(key, "") or "").strip()
            if value:
                pieces.append(value[:800])
        return " | ".join(pieces) if pieces else "process did not start and reported no diagnostics"
    def _standalone_dotnet_editor_process_running(self) -> bool:
        controller = self._active_shared_dotnet_controller()
        return bool(controller is not None and getattr(controller, "is_running", False))
    def _stop_standalone_dotnet_editor_process(self, *, embedded_state: str = "closed") -> None:
        self._cancel_dotnet_material_compile()
        self.standalone_dotnet_ready_timer.stop()
        self.standalone_dotnet_deactivate_timer.stop()
        self.standalone_dotnet_finish_scene_timer.stop()
        # The renderer that held the working state is going away. If the session
        # still holds edits, it enters recovery rather than being quietly
        # forgotten along with the pending finish below -- the difference is
        # whether a later finish can report success over a state nobody can
        # vouch for.
        self._require_edit_session_recovery(reason="resident_editor_process_stopped")
        self.standalone_dotnet_finish_scene_pending = None
        controller = self._active_shared_dotnet_controller()
        if self.standalone_dotnet_target_embedded:
            self._set_embedded_dotnet_state(embedded_state, active=False)
        self.standalone_dotnet_editor_process = None
        self.standalone_dotnet_update_ack_start_timer.stop()
        self.standalone_dotnet_update_ack_timer.stop()
        self.standalone_dotnet_update_queue.reset()
        self.standalone_pending_dotnet_live_stroke_outcome = None
        self._cancel_pending_dotnet_captures()
        self.standalone_dotnet_scene_request_id += 1
        self.standalone_dotnet_scene_pending = None
        self.standalone_dotnet_scene_candidate = None
        self.standalone_dotnet_scene_queued = None
        self.standalone_dotnet_pending_clone_material_model = None
        self.standalone_dotnet_pending_reference_material_model = None
        self.standalone_dotnet_pending_imported_material_publish = False
        self.standalone_dotnet_pending_paired_material_model = None
        self.standalone_dotnet_pending_paired_material_upgrade = None
        # A textured view this tab still meant to restore belongs to the session
        # that is ending; the next one starts from its own scene.
        self._forget_deferred_textured_view()
        if self.standalone_dotnet_scene_worker is not None:
            self.standalone_dotnet_scene_worker.stop()
        if controller is not None:
            try:
                controller.clear_preview()
            except RuntimeError:
                # An embedded host can already be deleted by the time its
                # modeless builder-finished callback reaches Mesh Editor.
                pass
    def _handle_standalone_dotnet_editor_finished(
        self,
        process: _tab.QProcess,
        package: _tab.MeshDotNetExperimentPackage,
    ) -> None:
        if self.standalone_dotnet_editor_process is not process:
            return
        self._handle_dotnet_protocol_stdout_ready(process)
        embedded_state_before_finish = self.standalone_dotnet_embedded_state
        process_payload = self._dotnet_process_event_payload(process, package=package)
        self._record_mesh_dotnet_event("mesh_dotnet_process_finished", **process_payload)
        self.standalone_dotnet_ready_timer.stop()
        self.standalone_dotnet_finish_scene_timer.stop()
        self.standalone_dotnet_finish_scene_pending = None
        self.standalone_dotnet_editor_process = None
        self._cancel_dotnet_material_compile()
        self.standalone_dotnet_update_ack_start_timer.stop()
        self.standalone_dotnet_update_ack_timer.stop()
        self.standalone_dotnet_update_queue.reset()
        self.standalone_pending_dotnet_live_stroke_outcome = None
        self._cancel_pending_dotnet_captures()
        self.standalone_dotnet_scene_request_id += 1
        self.standalone_dotnet_scene_pending = None
        self.standalone_dotnet_scene_candidate = None
        self.standalone_dotnet_scene_queued = None
        self.standalone_dotnet_pending_clone_material_model = None
        self.standalone_dotnet_pending_reference_material_model = None
        self.standalone_dotnet_pending_imported_material_publish = False
        self.standalone_dotnet_pending_paired_material_model = None
        self.standalone_dotnet_pending_paired_material_upgrade = None
        # A textured view this tab still meant to restore belongs to the session
        # that is ending; the next one starts from its own scene.
        self._forget_deferred_textured_view()
        if self.standalone_dotnet_scene_worker is not None:
            self.standalone_dotnet_scene_worker.stop()
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        payload: dict[str, object] = {}
        if package.status_path.is_file():
            try:
                loaded = json.loads(package.status_path.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, dict):
                    payload = loaded
            except ValueError:
                payload = {"event": "error", "message": "status JSON could not be parsed"}
        self.standalone_dotnet_status_payload = dict(payload)
        try:
            evaluation_path = _tab.write_mesh_dotnet_experiment_evaluation(package, payload)
        except Exception as exc:
            self._record_mesh_dotnet_event("mesh_dotnet_evaluation_write_failed", error=str(exc))
            evaluation_path = None
        event = str(payload.get("event", "") or "closed").strip().lower()
        message = str(payload.get("message", "") or "").strip()
        if self.standalone_dotnet_target_embedded:
            if self.standalone_dotnet_exit_pending and not self.standalone_dotnet_deactivate_acknowledged:
                self.standalone_dotnet_deactivate_acknowledged = True
                self._complete_pending_dotnet_exit()
            intentional_exit = bool(
                self.standalone_dotnet_embedded_exit_finalized
                or self.standalone_dotnet_exit_pending
                or embedded_state_before_finish == "suspended"
            )
            if not intentional_exit:
                detail = message or "Embedded .NET helper exited unexpectedly."
                self._set_embedded_dotnet_state("failed", active=False)
                self._set_embedded_dotnet_preview_loading(False, detail)
                self._notify_embedded_dotnet_launch_failed("mesh_edit_dotnet_failed", diagnostics=detail)
                self._set_dotnet_status(
                    "Mesh .NET editor exited; resident edits remain saved but preview is unavailable. " + detail,
                    error=True,
                )
                return
            completed = self._complete_embedded_dotnet_exit("dotnet_process_finished")
            if completed:
                self._set_embedded_dotnet_state("closed", active=False)
            if event in {"error", "blocked_renderer_unavailable"}:
                text = (
                    "Mesh .NET editor closed with an error; resident native edits were preserved. "
                    f"{message or 'External editor reported an error.'}"
                )
                self._set_dotnet_status(text, error=True)
            elif completed:
                self._set_dotnet_status("Mesh .NET editor closed; resident edits saved and textured preview restored.")
            return
        if event in {"error", "blocked_renderer_unavailable"}:
            text = f"Mesh .NET editor experiment error: {message or 'external editor reported an error.'}"
            if evaluation_path is not None:
                text += f" Evaluation: {evaluation_path}"
            self._set_dotnet_status(text, error=True)
            if self.standalone_dotnet_target_embedded:
                self._notify_embedded_dotnet_launch_failed("mesh_dotnet_status_error", diagnostics=message or text)
            return
        if not self._handle_dotnet_renderer_status(
            payload,
            source_event="process_finished",
        ):
            return
        output_obj = _tab.mesh_dotnet_experiment_output_obj_path(package, payload)
        if output_obj is not None and self._start_standalone_dotnet_output_import(package, payload):
            self.status_message_requested.emit(f"Mesh .NET editor experiment closed; importing {output_obj}.", False)
            return
        output_hint = str(payload.get("edited_package", "") or package.output_dir)
        text = f"Mesh .NET editor experiment closed. Output package: {output_hint}"
        if evaluation_path is not None:
            text += f" Evaluation: {evaluation_path}"
        self._set_dotnet_status(text)
    def _handle_standalone_dotnet_editor_error(self, process: _tab.QProcess, qprocess_error: object = None) -> None:
        if self.standalone_dotnet_editor_process is not process:
            return
        closing = self.standalone_dotnet_target_embedded and self.standalone_dotnet_embedded_state == "closing"
        self.standalone_dotnet_ready_timer.stop()
        detail = self._dotnet_process_diagnostics(process)
        payload = self._dotnet_process_event_payload(process, qprocess_error=qprocess_error)
        self._record_mesh_dotnet_event("mesh_dotnet_process_error", **payload)
        package = self.standalone_dotnet_experiment_package
        if package is not None:
            try:
                _tab.write_mesh_dotnet_launch_diagnostics(package, payload)
            except Exception as diag_exc:
                self._record_mesh_dotnet_event("mesh_dotnet_launch_diagnostics_write_failed", error=str(diag_exc))
        text = f"Mesh .NET editor experiment process error: {detail}"
        if self.standalone_dotnet_target_embedded:
            if closing:
                try:
                    stopped = process.state() == _tab.QProcess.NotRunning
                except RuntimeError:
                    stopped = True
                if stopped:
                    self._handle_dotnet_protocol_stdout_ready(process)
                    self.standalone_dotnet_deactivate_acknowledged = True
                    self._complete_pending_dotnet_exit()
            else:
                self._set_embedded_dotnet_state("failed", active=False)
                self._set_embedded_dotnet_preview_loading(False, text)
                self._notify_embedded_dotnet_launch_failed("mesh_edit_dotnet_failed", diagnostics=detail)
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        self._set_dotnet_status(text, error=True)
    def _standalone_action_worker_active(self) -> bool:
        if (
            self.standalone_action_dotnet_command
            and int(self.standalone_action_request_id) > 0
            and int(self.standalone_action_finished_request_id) == int(self.standalone_action_request_id)
        ):
            # A .NET command result may immediately trigger the next correlated
            # wizard command. The worker has already produced its final result;
            # only QThread's queued finished/deleteLater cleanup remains. Treat
            # that narrow handoff window as idle so the next command is not
            # falsely rejected as busy. Identity checks in cleanup keep the old
            # thread from clearing a newly installed worker.
            return False
        return self.standalone_action_thread is not None or self.standalone_action_worker is not None
    def _start_standalone_action_worker(self, action: object, *, action_text: str) -> bool:
        controller = self.standalone_controller
        if controller is None:
            return False
        if self._standalone_action_worker_active():
            self.status_message_requested.emit("Wait for the current Mesh Editor action to finish, or cancel it first.", True)
            return True
        command = self._standalone_action_command(action, controller, action_text=action_text)
        if command is None:
            return False
        session_id = str(controller.active_session_id or "")
        if not session_id:
            return False
        self.standalone_action_request_id += 1
        request_id = self.standalone_action_request_id
        worker = _tab.MeshEditCommandWorker(request_id, controller.mesh_service, session_id, command, action_text=action_text)
        thread = QThread(self)
        progress = QProgressDialog(f"Applying {action_text}...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Mesh Editor")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(250)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(self._cancel_standalone_action_worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(self._handle_standalone_action_progress)
        worker.completed.connect(self._handle_standalone_action_completed)
        worker.cancelled.connect(self._handle_standalone_action_cancelled)
        worker.error.connect(self._handle_standalone_action_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_action_worker(target_thread, target_worker))
        self.standalone_action_thread = thread
        self.standalone_action_worker = worker
        self.standalone_action_progress = progress
        self.standalone_action_text = str(action_text or "Mesh Editor action")
        self.standalone_action_controller = controller
        self.standalone_action_dotnet_command = ""
        self.standalone_action_dotnet_request_payload = None
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        self.status_message_requested.emit(f"Applying {action_text} in the background...", False)
        thread.start(QThread.LowPriority)
        return True
    def _start_dotnet_action_worker(
        self,
        controller: _tab.MeshEditorController,
        command: _tab.MeshEditCommand,
        *,
        command_name: str,
        request_payload: Mapping[str, object] | None = None,
    ) -> bool:
        normalized_name = str(command_name or command.action or "command")
        if self._standalone_action_worker_active():
            self._send_dotnet_command_result(
                normalized_name,
                ok=False,
                status="busy",
                diagnostics=("Wait for the current Mesh Editor action to finish.",),
                request_payload=request_payload,
            )
            return True
        self.standalone_action_request_id += 1
        request_id = self.standalone_action_request_id
        worker = _tab.MeshEditCommandWorker(
            request_id,
            controller.mesh_service,
            str(controller.active_session_id or ""),
            command,
            action_text=str(command.label or normalized_name),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress_changed.connect(self._handle_dotnet_action_progress)
        worker.completed.connect(self._handle_standalone_action_completed)
        worker.cancelled.connect(self._handle_standalone_action_cancelled)
        worker.error.connect(self._handle_standalone_action_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_action_worker(
                target_thread,
                target_worker,
            )
        )
        self.standalone_action_thread = thread
        self.standalone_action_worker = worker
        self.standalone_action_text = str(command.label or normalized_name)
        self.standalone_action_controller = controller
        self.standalone_action_edit_session_generation = self._edit_session_generation()
        self.standalone_action_dotnet_command = normalized_name
        self.standalone_action_dotnet_request_payload = (
            dict(request_payload) if request_payload is not None else None
        )
        self._set_dotnet_status(f"Applying {self.standalone_action_text} in the background...")
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        thread.start(QThread.LowPriority)
        return True
    def _dotnet_action_belongs_to_current_edit_session(self, request_id: int) -> bool:
        """Whether a returning command result still belongs to the live session.

        The request id says the result is from the newest command. It cannot say
        that the session the command was issued against still exists: a Finish,
        a Cancel, or a renderer restart in between leaves a result that is
        newest and yet applies to a working state that has moved on.
        """

        if int(request_id) != int(self.standalone_action_request_id):
            return False
        recorded = int(getattr(self, "standalone_action_edit_session_generation", -1))
        if recorded < 0:
            return True
        current = self._edit_session_generation()
        if current < 0 or current == recorded:
            return True
        self._record_mesh_dotnet_event(
            "mesh_dotnet_edit_command_stale_session",
            request_id=int(request_id),
            command=str(self.standalone_action_dotnet_command or ""),
            recorded_session_generation=recorded,
            current_session_generation=current,
            **error_payload(
                MeshEditorErrorCode.EDIT_REQUEST_STALE,
                "the Edit Mesh session moved on while this command was running",
            ),
        )
        return False

    def _handle_dotnet_action_progress(self, request_id: int, _percent: int, message: str) -> None:
        if int(request_id) == int(self.standalone_action_request_id):
            self._set_dotnet_status(str(message or "Applying Mesh Editor action..."))
    def _handle_standalone_action_progress(self, request_id: int, percent: int, message: str) -> None:
        if int(request_id) != int(self.standalone_action_request_id):
            return
        # Progress is a queued cross-thread signal, so one emitted just before
        # the result can be delivered just after it. Letting that through
        # repaints the status line with "Applied Rotate." over the finished
        # session state the completion handler had already written.
        if int(request_id) <= int(self.standalone_action_finished_request_id):
            return
        bounded_percent = max(0, min(100, int(percent or 0)))
        progress = self.standalone_action_progress
        if progress is not None:
            progress.setLabelText(str(message or "Applying Mesh Editor action..."))
            progress.setValue(bounded_percent)
        # The worker's 100% sample is terminal progress, not authoritative
        # session state. It can arrive immediately before the completion slot,
        # and a nested Qt event loop can expose that sample after the native
        # update is already visible. Completion owns the revision/status line.
        if bounded_percent >= 100:
            return
        self.standalone_status_label.setText(str(message or "Applying Mesh Editor action..."))
    def _handle_standalone_action_completed(self, request_id: int, result: object) -> None:
        if not self._dotnet_action_belongs_to_current_edit_session(request_id):
            # The result is dropped, but anything waiting on the action draining
            # is not: a pending exit still has to complete, or Finish Edit Mesh
            # waits forever on a command whose result was discarded.
            if int(request_id) == int(self.standalone_action_request_id):
                self.standalone_action_finished_request_id = int(request_id)
                self._complete_pending_dotnet_exit()
            return
        self.standalone_action_finished_request_id = int(request_id)
        controller = self.standalone_action_controller or self.standalone_controller
        if controller is None:
            return
        if self.standalone_action_dotnet_command:
            if isinstance(result, _tab.MeshEditResult):
                self._apply_dotnet_result_update(
                    controller,
                    result,
                    command_name=self.standalone_action_dotnet_command,
                    request_payload=self.standalone_action_dotnet_request_payload,
                )
            self._complete_pending_dotnet_exit()
            return
        update_started = time.perf_counter()
        native_update = controller.native_update_for_result(result)
        result = _mesh_edit_result_with_metric(
            result,
            "preview_delta_build_ms",
            (time.perf_counter() - update_started) * 1000.0,
        )
        execution = _tab.MeshEditorActionExecution(
            edit_result=result,
            native_update=native_update,
        )
        self._finish_standalone_action_execution(execution, action_text=self.standalone_action_text)
    def _handle_standalone_action_cancelled(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_action_request_id):
            return
        self.standalone_action_finished_request_id = int(request_id)
        text = str(message or "Mesh Editor action cancelled.")
        if self.standalone_action_dotnet_command:
            self._send_dotnet_command_result(
                self.standalone_action_dotnet_command,
                ok=False,
                status="cancelled",
                diagnostics=(text,),
                request_payload=self.standalone_action_dotnet_request_payload,
            )
            self._send_dotnet_session_state()
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, False)
        if self.standalone_action_text == "Object Transform" and self.standalone_controller is not None:
            self.update_editor_session_state(self.standalone_controller.session_view())
        self._complete_pending_dotnet_exit()
    def _handle_standalone_action_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_action_request_id):
            return
        self.standalone_action_finished_request_id = int(request_id)
        text = str(message or "Mesh Editor action failed.")
        if self.standalone_action_dotnet_command:
            self._send_dotnet_command_result(
                self.standalone_action_dotnet_command,
                ok=False,
                status="error",
                diagnostics=(text,),
                request_payload=self.standalone_action_dotnet_request_payload,
            )
            self._send_dotnet_session_state()
            if self.standalone_action_dotnet_command.startswith("morph_"):
                self._send_dotnet_cached_morph_state(
                    request_payload=self.standalone_action_dotnet_request_payload,
                    failure=text,
                )
        self.standalone_status_label.setText(text)
        self.status_message_requested.emit(text, True)
        if self.standalone_action_text == "Object Transform" and self.standalone_controller is not None:
            self.update_editor_session_state(self.standalone_controller.session_view())
        self._complete_pending_dotnet_exit()
    def _cleanup_standalone_action_worker(
        self,
        thread: QThread,
        worker: _tab.MeshEditCommandWorker,
    ) -> None:
        if (
            self.standalone_action_thread is not thread
            or self.standalone_action_worker is not worker
        ):
            # A completed .NET command may start its correlated successor before
            # QThread delivers this older cleanup. Every shared field below now
            # belongs to that successor, so stale cleanup must have no effects.
            return
        dotnet_action = bool(self.standalone_action_dotnet_command)
        self.standalone_action_thread = None
        self.standalone_action_worker = None
        self.standalone_action_text = ""
        self.standalone_action_controller = None
        self.standalone_action_dotnet_command = ""
        self.standalone_action_dotnet_request_payload = None
        progress = self.standalone_action_progress
        if progress is not None:
            progress.close()
            progress.deleteLater()
            self.standalone_action_progress = None
        self.update_editor_action_state(selection_empty=self.current_selection_empty)
        if self._standalone_dotnet_editor_process_running() and not dotnet_action:
            self._send_dotnet_session_state()
        self._complete_pending_dotnet_exit()
        self._retry_pending_dotnet_finish()
    def _retry_pending_dotnet_finish(self) -> None:
        # A Finish Edit Mesh that was refused for "busy" runs itself now that
        # the worker has drained; making the reader click the button again is
        # how "Finish does nothing" reports happen.
        if not self.standalone_dotnet_finish_retry_pending:
            return
        self.standalone_dotnet_finish_retry_pending = False
        if (
            self.standalone_dotnet_target_embedded
            and not self.standalone_dotnet_exit_pending
            and self._standalone_dotnet_editor_process_running()
        ):
            self._finish_embedded_dotnet_edit_mode()
    def _cancel_standalone_action_worker(self) -> None:
        worker = self.standalone_action_worker
        thread = self.standalone_action_thread
        if worker is None and thread is None:
            return
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
            except RuntimeError:
                pass
