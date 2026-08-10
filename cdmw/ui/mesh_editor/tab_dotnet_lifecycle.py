from __future__ import annotations

import json
from typing import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from cdmw.ui.shell.settings_bridge import read_bool_setting
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


def _host_widget_hwnd(host_widget: object | None) -> int:
    if host_widget is None:
        return 0
    try:
        set_attribute = getattr(host_widget, "setAttribute")
        win_id = getattr(host_widget, "winId")
    except AttributeError:
        return 0
    try:
        set_attribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        return int(win_id())
    except (RuntimeError, TypeError, ValueError):
        return 0


class MeshEditorDotNetLifecycleMixin:
    def _dotnet_embedded_parent_hwnd(self) -> int:
        if not self.standalone_dotnet_target_embedded:
            if str(_tab.QApplication.platformName() or "").strip().lower() == "offscreen":
                return 0
            hwnd = _host_widget_hwnd(getattr(self, "standalone_native_host_frame", None))
            return hwnd if hwnd > 0 else 0
        builder = self.active_builder()
        if isinstance(builder, QWidget):
            host = builder.findChild(QWidget, "AlignmentDotNetVorticePreviewHost")
            hwnd = _host_widget_hwnd(host)
            if hwnd > 0:
                return hwnd
            hwnd = _host_widget_hwnd(builder)
            if hwnd > 0:
                return hwnd
        hwnd = _host_widget_hwnd(self.standalone_native_host)
        return hwnd if hwnd > 0 else 0
    def _dotnet_process_stream_tails(self, process: _tab.QProcess) -> tuple[str, str]:
        stdout = self.standalone_dotnet_stdout_tail
        stderr = self.standalone_dotnet_stderr_tail
        try:
            raw_stdout = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
            if raw_stdout:
                self.standalone_dotnet_stdout_tail = _tab.append_bounded_text(
                    self.standalone_dotnet_stdout_tail,
                    raw_stdout,
                )
                stdout = self.standalone_dotnet_stdout_tail
        except (AttributeError, RuntimeError):
            pass
        try:
            raw_stderr = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
            if raw_stderr:
                self.standalone_dotnet_stderr_tail = _tab.append_bounded_text(
                    self.standalone_dotnet_stderr_tail,
                    raw_stderr,
                )
                stderr = self.standalone_dotnet_stderr_tail
        except (AttributeError, RuntimeError):
            pass
        return stdout[-2000:], stderr[-2000:]
    def _dotnet_process_event_payload(
        self,
        process: _tab.QProcess | None,
        *,
        package: _tab.MeshDotNetExperimentPackage | None = None,
        qprocess_error: object = None,
    ) -> dict[str, object]:
        stdout_tail = self.standalone_dotnet_stdout_tail
        stderr_tail = self.standalone_dotnet_stderr_tail
        if process is not None:
            stdout_tail, stderr_tail = self._dotnet_process_stream_tails(process)
        process_state = "unknown"
        error_value = qprocess_error
        error_string = ""
        exit_code: object = ""
        exit_status: object = ""
        if process is not None:
            try:
                process_state = str(process.state())
            except (AttributeError, RuntimeError):
                pass
            try:
                if error_value is None:
                    error_value = process.error()
            except (AttributeError, RuntimeError):
                pass
            try:
                error_string = str(process.errorString() or "")
            except (AttributeError, RuntimeError):
                pass
            try:
                exit_code = int(process.exitCode())
            except (AttributeError, RuntimeError):
                pass
            try:
                exit_status = str(process.exitStatus())
            except (AttributeError, RuntimeError):
                pass
        status_payload: dict[str, object] = {}
        target_package = package or self.standalone_dotnet_experiment_package
        if target_package is not None and target_package.status_path.is_file():
            try:
                loaded = json.loads(target_package.status_path.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, dict):
                    status_payload = loaded
            except (OSError, ValueError):
                status_payload = {"event": "error", "message": "status JSON could not be parsed"}
        return {
            "program": self.standalone_dotnet_last_program,
            "arguments": tuple(self.standalone_dotnet_last_arguments),
            "working_directory": self.standalone_dotnet_last_working_directory,
            "embedded": bool(self.standalone_dotnet_target_embedded or self.standalone_dotnet_last_parent_hwnd > 0),
            "parent_hwnd": int(self.standalone_dotnet_last_parent_hwnd or 0),
            "process_state": process_state,
            "qprocess_error": str(error_value or ""),
            "qprocess_error_string": error_string,
            "exit_code": exit_code,
            "exit_status": exit_status,
            "stderr_tail": stderr_tail,
            "stdout_tail": stdout_tail,
            "status_path": str(target_package.status_path) if target_package is not None else "",
            "status_event": str(status_payload.get("event", "") or ""),
            "status_message": str(status_payload.get("message", "") or ""),
            "package_dir": str(target_package.package_dir) if target_package is not None else "",
        }
    def _request_embedded_dotnet_editor_close(self) -> bool:
        if not self.standalone_dotnet_target_embedded:
            return False
        if self._standalone_dotnet_package_worker_active():
            self._set_embedded_dotnet_state("closing", active=False)
            self._cancel_standalone_dotnet_package_worker()
            self.standalone_dotnet_exit_pending = True
            self.standalone_dotnet_deactivate_acknowledged = True
            return self._complete_embedded_dotnet_exit("dotnet_package_cancelled")
        if not self._standalone_dotnet_editor_process_running():
            return False
        process = self.standalone_dotnet_editor_process
        if process is None:
            return False
        self._set_embedded_dotnet_state("closing", active=False)
        self.standalone_dotnet_exit_pending = True
        self.standalone_dotnet_deactivate_acknowledged = False
        if not self._send_dotnet_protocol_message({"event": "deactivate_request"}):
            self._stop_standalone_dotnet_editor_process(embedded_state="closing")
            self.standalone_dotnet_deactivate_acknowledged = True
        else:
            self._flush_dotnet_protocol_messages()
            self.standalone_dotnet_deactivate_timer.start(2_000)
        if self._standalone_action_worker_active():
            self._cancel_standalone_action_worker()
            self._set_dotnet_status("Waiting for the active Mesh Editor command to stop before saving...")
            return True
        if self.standalone_dotnet_deactivate_acknowledged:
            self._complete_pending_dotnet_exit()
        else:
            self._set_dotnet_status("Waiting for Mesh .NET editor to finish queued edits before saving...")
        return True
    def _finish_embedded_dotnet_edit_mode(
        self,
        request_payload: Mapping[str, object] | None = None,
    ) -> bool:
        # Finish Edit Mesh has six ways to give up and, until now, only the
        # success path said anything a session capture could see. A reader whose
        # editor would not close left a trail that simply stopped, so every exit
        # names itself here.
        def _blocked(reason: str, **detail: object) -> None:
            self._record_mesh_dotnet_event(
                "mesh_dotnet_edit_mode_finish_blocked",
                reason=reason,
                process_generation=self.standalone_dotnet_process_generation,
                **detail,
            )

        if not self.standalone_dotnet_target_embedded:
            _blocked("not_embedded")
            return False
        if self.standalone_dotnet_finish_scene_pending is not None:
            _blocked("placement_transition_pending")
            self._send_dotnet_command_result(
                "save_request",
                ok=False,
                status="busy",
                diagnostics=("Waiting for Mesh .NET editor to finish queued edits before saving...",),
                request_payload=request_payload,
            )
            return True
        if self._reject_dotnet_mutation_while_busy("save_request", request_payload):
            _blocked("mutation_busy")
            self.standalone_dotnet_finish_retry_pending = True
            return True
        live_stroke_busy = bool(
            str(self.standalone_native_mesh_edit_stroke_id or "").strip()
        )
        dispatcher = self.standalone_live_stroke_dispatcher
        if dispatcher is not None:
            try:
                dispatcher_metrics = dispatcher.metrics()
            except RuntimeError:
                dispatcher_metrics = {"active": 1}
            live_stroke_busy = live_stroke_busy or any(
                int(dispatcher_metrics.get(key, 0) or 0) > 0
                for key in ("active", "control_depth", "queue_depth")
            )
        if live_stroke_busy:
            _blocked(
                "live_stroke_busy",
                stroke_id=str(self.standalone_native_mesh_edit_stroke_id or ""),
            )
            self.standalone_dotnet_finish_retry_pending = True
            self._send_dotnet_command_result(
                "save_request",
                ok=False,
                status="busy",
                diagnostics=("Wait for the active Mesh Editor stroke to finish.",),
                request_payload=request_payload,
            )
            return True
        # Past the busy gates: this attempt is the finish, so no deferred
        # retry may fire a second one behind it.
        self.standalone_dotnet_finish_retry_pending = False
        if not self._standalone_dotnet_editor_process_running():
            self._send_dotnet_command_result(
                "save_request",
                ok=False,
                status="unavailable",
                diagnostics=("Resident Mesh .NET editor is not running.",),
                request_payload=request_payload,
            )
            return False
        comparison_mode = "replacement_only"
        builder = self.active_builder()
        comparison_getter = getattr(
            builder,
            "_mesh_editor_embedded_placement_comparison_mode",
            getattr(
                builder,
                "_mesh_editor_embedded_comparison_mode",
                None,
            ),
        )
        if callable(comparison_getter):
            try:
                comparison_mode = str(comparison_getter() or "replacement_only")
            except (AttributeError, RuntimeError, TypeError, ValueError):
                comparison_mode = "replacement_only"
        if not self._send_dotnet_scene_state(
            interaction_mode="placement",
            comparison_mode=comparison_mode,
            gizmo_tool="move",
            source_identity=str((request_payload or {}).get("source_identity", "") or ""),
            session_id=str((request_payload or {}).get("session_id", "") or ""),
        ):
            self._send_dotnet_command_result(
                "save_request",
                ok=False,
                status="error",
                diagnostics=("Resident placement mode transition could not be queued.",),
                request_payload=request_payload,
            )
            return False
        scene_pending = self.standalone_dotnet_scene_pending
        if scene_pending is None:
            self._send_dotnet_command_result(
                "save_request",
                ok=False,
                status="error",
                diagnostics=("Resident placement mode transition could not be queued.",),
                request_payload=request_payload,
            )
            return False
        self.standalone_dotnet_finish_scene_pending = {
            key: scene_pending[key]
            for key in (
                "session_id",
                "request_id",
                "process_generation",
                "source_identity",
                "scene_generation",
            )
        }
        self.standalone_dotnet_finish_scene_pending["request_payload"] = dict(
            request_payload or {}
        )
        self.standalone_dotnet_finish_scene_timer.start(5_000)
        self._set_dotnet_status(
            "Waiting for Mesh .NET editor to finish queued edits before saving..."
        )
        return True
    def _dotnet_finish_scene_matches(self, payload: Mapping[str, object]) -> bool:
        pending = self.standalone_dotnet_finish_scene_pending
        if pending is None:
            return False
        try:
            return all(
                (
                    str(payload.get(key, "") or "") == str(pending[key])
                    if key in {"session_id", "source_identity"}
                    else int(payload.get(key, 0) or 0) == int(pending[key])
                )
                for key in (
                    "session_id",
                    "request_id",
                    "process_generation",
                    "source_identity",
                    "scene_generation",
                )
            )
        except (KeyError, TypeError, ValueError, OverflowError):
            return False

    def _fail_embedded_dotnet_edit_mode_finish(self, diagnostic: str) -> bool:
        pending = self.standalone_dotnet_finish_scene_pending
        if pending is None:
            return False
        self.standalone_dotnet_finish_scene_pending = None
        self.standalone_dotnet_finish_scene_timer.stop()
        request_payload = pending.get("request_payload")
        self._send_dotnet_command_result(
            "save_request",
            ok=False,
            status="error",
            diagnostics=(str(diagnostic or "Resident placement mode transition could not be queued."),),
            request_payload=(request_payload if isinstance(request_payload, Mapping) else None),
        )
        self._record_mesh_dotnet_event(
            "mesh_dotnet_edit_mode_finish_blocked",
            reason="placement_transition_failed",
            process_generation=self.standalone_dotnet_process_generation,
            diagnostic=str(diagnostic or ""),
        )
        return True

    def _handle_dotnet_finish_scene_timeout(self) -> None:
        pending = self.standalone_dotnet_finish_scene_pending
        if pending is None:
            return
        scene_pending = self.standalone_dotnet_scene_pending
        if scene_pending is not None and all(
            scene_pending.get(key) == pending.get(key)
            for key in (
                "session_id",
                "request_id",
                "process_generation",
                "source_identity",
                "scene_generation",
            )
        ):
            self.standalone_dotnet_scene_pending = None
        message = (
            "Finish Edit Mesh timed out because the resident placement view was not "
            "acknowledged within 5 seconds; Edit Mesh remains open."
        )
        self._fail_embedded_dotnet_edit_mode_finish(message)
        self._set_dotnet_status(message, error=True)

    def _complete_embedded_dotnet_edit_mode_finish(self) -> bool:
        pending = self.standalone_dotnet_finish_scene_pending
        if pending is None:
            return False
        self.standalone_dotnet_finish_scene_pending = None
        self.standalone_dotnet_finish_scene_timer.stop()
        request_payload = pending.get("request_payload")
        if not self._finalize_embedded_dotnet_import("dotnet_finish_edit"):
            # No re-arm. The builder unticks its checkbox before anything that
            # can fail here, so putting the helper back into mesh_edit left the
            # two sides disagreeing about the mode and the button dead. Report
            # the failure and leave the helper in the placement mode already
            # published above, which is the state the builder is now in.
            self._send_dotnet_command_result(
                "save_request",
                ok=False,
                status="error",
                diagnostics=("Resident mesh edit finalization failed.",),
                request_payload=(request_payload if isinstance(request_payload, Mapping) else None),
            )
            return False
        controller = self._dotnet_target_controller()
        revision = None
        if controller is not None:
            try:
                revision = int(controller.session_view().revision)
            except (AttributeError, RuntimeError, TypeError, ValueError):
                revision = None
        self._refresh_embedded_workspace_from_builder()
        self._send_dotnet_command_result(
            "save_request",
            ok=True,
            status="saved",
            revision=revision,
            request_payload=(request_payload if isinstance(request_payload, Mapping) else None),
        )
        self._record_mesh_dotnet_event(
            "mesh_dotnet_edit_mode_finished_resident",
            edit_revision=revision,
            process_generation=self.standalone_dotnet_process_generation,
        )
        self._set_dotnet_status(
            "Mesh .NET edit mode finished; resident placement preview remains active."
        )
        return True
    def _cancel_standalone_dotnet_import_worker(self) -> None:
        worker = self.standalone_dotnet_import_worker
        thread = self.standalone_dotnet_import_thread
        if worker is None and thread is None:
            return
        cancelled_before_commit = True
        if worker is not None:
            try:
                cancelled_before_commit = bool(worker.stop())
            except RuntimeError:
                pass
        if not cancelled_before_commit:
            self._set_dotnet_status(
                "Mesh .NET output commit is already in progress; waiting for its result."
            )
            return
        self.standalone_dotnet_import_request_id += 1
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass
    def _dotnet_developer_renderer_fallback_allowed(self) -> bool:
        return read_bool_setting(self.settings, "mesh_editor/developer_mode", False) and read_bool_setting(
            self.settings,
            "mesh_editor/developer_renderer_fallback",
            False,
        )
    def _dotnet_status_blockers(
        self,
        status_payload: Mapping[str, object],
        *,
        require_material_parity: bool = False,
    ) -> tuple[str, ...]:
        return _tab.mesh_dotnet_renderer_blockers(
            status_payload,
            embedded=bool(self.standalone_dotnet_target_embedded or self.standalone_dotnet_last_parent_hwnd > 0),
            developer_override=self._dotnet_developer_renderer_fallback_allowed(),
            require_material_parity=bool(require_material_parity and self.standalone_dotnet_target_embedded),
        )
    def _handle_dotnet_renderer_status(
        self,
        status_payload: Mapping[str, object],
        *,
        source_event: str,
        emit_warning: bool = True,
        require_material_parity: bool = False,
    ) -> bool:
        blockers = self._dotnet_status_blockers(
            status_payload,
            require_material_parity=require_material_parity,
        )
        if blockers:
            text = "Mesh .NET renderer blocked: " + "; ".join(blockers)
            self._record_mesh_dotnet_event(
                "mesh_dotnet_renderer_blocked",
                source_event=str(source_event or ""),
                embedded=bool(self.standalone_dotnet_target_embedded),
                dotnet_state=str(self.standalone_dotnet_embedded_state or ""),
                blockers=tuple(blockers),
            )
            self._set_dotnet_status(text, error=True)
            if self.standalone_dotnet_target_embedded:
                self._notify_embedded_dotnet_launch_failed("mesh_dotnet_renderer_blocked", diagnostics=text)
            return False
        if emit_warning:
            warnings = _tab.mesh_dotnet_material_parity_warnings(status_payload)
            if warnings:
                text = "Mesh .NET material preview is not authoritative: " + "; ".join(warnings)
                self._record_mesh_dotnet_event(
                    "mesh_dotnet_material_parity_warning",
                    source_event=str(source_event or ""),
                    embedded=bool(self.standalone_dotnet_target_embedded),
                    warnings=tuple(warnings),
                )
                self._set_dotnet_status(text, error=False)
        return True
