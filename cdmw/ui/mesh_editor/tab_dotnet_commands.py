from __future__ import annotations

import json
from typing import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from cdmw.ui.shell.settings_bridge import read_bool_setting
from cdmw.ui.mesh_editor.actions import mesh_editor_actions_by_key


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


class MeshEditorDotNetCommandMixin:
    def _reject_dotnet_mutation_while_busy(
        self,
        command_name: str,
        request_payload: Mapping[str, object] | None = None,
    ) -> bool:
        normalized = str(command_name or "command").strip().lower()
        if self._standalone_action_worker_active():
            self._send_dotnet_command_result(
                normalized,
                ok=False,
                status="busy",
                diagnostics=("Wait for the current Mesh Editor action to finish.",),
                request_payload=request_payload,
            )
            return True
        live_stroke_busy = normalized != "stroke" and bool(
            str(self.standalone_native_mesh_edit_stroke_id or "").strip()
        )
        if normalized != "morph_change":
            live_stroke_busy = live_stroke_busy or bool(
                str(getattr(self, "standalone_dotnet_morph_change_id", "") or "").strip()
            )
        dispatcher = self.standalone_live_stroke_dispatcher
        if normalized != "stroke" and dispatcher is not None:
            try:
                metrics = dispatcher.metrics()
            except (AttributeError, RuntimeError):
                metrics = {"active": 1}
            live_stroke_busy = live_stroke_busy or any(
                int(metrics.get(key, 0) or 0) > 0
                for key in ("active", "control_depth", "queue_depth")
            )
        if not live_stroke_busy:
            return False
        self._send_dotnet_command_result(
            normalized,
            ok=False,
            status="busy",
            diagnostics=("Wait for the active Mesh Editor stroke to finish.",),
            request_payload=request_payload,
        )
        return True
    def _handle_dotnet_select_request(self, payload: Mapping[str, object]) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        if self._reject_dotnet_mutation_while_busy("select", payload):
            return True
        screen_payload = self._dotnet_screen_selection_payload(payload)
        if not any(key in screen_payload for key in ("screen_brush", "screen_region")):
            self._send_dotnet_command_result("select", ok=False, status="error", diagnostics=("Missing screen selection payload.",), request_payload=payload)
            return False
        operation = str(payload.get("operation", payload.get("selection_operation", "replace")) or "replace").strip().lower()
        try:
            command = _tab.MeshEditCommand(
                "select",
                selection=_tab.MeshEditSelection(),
                params={
                    "operation": operation,
                    "_native_screen_selection_payload": screen_payload,
                },
                label="Select Mesh",
            )
        except Exception as exc:
            self._set_dotnet_status(f"Mesh .NET editor selection failed: {exc}", error=True)
            self._send_dotnet_command_result("select", ok=False, status="error", diagnostics=(str(exc),), request_payload=payload)
            return False
        return self._start_dotnet_action_worker(
            controller,
            command,
            command_name="select",
            request_payload=payload,
        )
    def _handle_dotnet_local_selection_request(self, payload: Mapping[str, object]) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None or not isinstance(payload.get("local_selection"), Mapping):
            return False
        if self._reject_dotnet_mutation_while_busy("select", payload):
            return True
        selection = self._dotnet_local_selection_payload_to_selection(payload)
        return self._start_dotnet_action_worker(
            controller,
            _tab.MeshEditCommand(
                "select",
                selection=selection,
                params={"operation": "replace"},
                label="Select Mesh",
            ),
            command_name="select",
            request_payload=payload,
        )
    def _handle_dotnet_stroke_event(self, payload: Mapping[str, object], phase: str) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        if self._reject_dotnet_mutation_while_busy("stroke", payload):
            return True
        command = self._standalone_native_mesh_edit_stroke_command(payload, phase)
        if command is None:
            self._send_dotnet_command_result("stroke", ok=False, status="error", diagnostics=("Invalid stroke payload.",), request_payload=payload)
            return False
        blocked_command = "transform" if command.action == "transform" else "brush"
        if self._native_editor_action_blocked(blocked_command, embedded=self.standalone_dotnet_target_embedded):
            return False
        stroke_id = str(payload.get("stroke_id", "") or "").strip()
        if phase == "begin":
            self.standalone_native_mesh_edit_stroke_id = stroke_id
        command_params = dict(command.params)
        try:
            queued_command = _tab.MeshEditCommand(
                command.action,
                selection=command.selection,
                params=command_params,
                mode=command.mode,
                label=command.label,
            )
        except Exception as exc:
            if phase in {"begin", "end", "cancel"}:
                self.standalone_native_mesh_edit_stroke_id = ""
            self._set_dotnet_status(f"Mesh .NET editor stroke failed: {exc}", error=True)
            self._send_dotnet_command_result(command.action, ok=False, status="error", diagnostics=(str(exc),), request_payload=payload)
            return False
        sequence = self._ensure_standalone_live_stroke_dispatcher().submit(
            controller,
            queued_command,
            phase,
            source="dotnet",
            request_payload=payload,
        )
        if sequence > 0:
            return True
        if phase in {"begin", "end", "cancel"}:
            self.standalone_native_mesh_edit_stroke_id = ""
        self._send_dotnet_command_result(
            command.action,
            ok=False,
            status="cancelled",
            diagnostics=("Mesh Editor live-stroke dispatcher is stopping.",),
            request_payload=payload,
        )
        return False
    def _handle_dotnet_live_stroke_completed(self, outcome: object) -> None:
        if not isinstance(outcome, _tab.MeshLiveStrokeOutcome) or outcome.source not in {"dotnet", "dotnet_morph"}:
            return
        controller = self._dotnet_target_controller()
        if controller is None or outcome.controller is not controller:
            return
        update = outcome.native_update
        if self.standalone_dotnet_target_embedded:
            self._apply_embedded_native_update(update)
            if outcome.phase != "update":
                self._refresh_embedded_workspace_from_builder()
        elif (
            update.vertex_groups
            or update.triangle_groups
            or update.triangle_source_submesh_indices
            or update.selection_groups
            or update.refresh_selection
            or update.material_override_groups
            or update.replace_all_triangles
        ):
            self._apply_standalone_native_update(update)
            if outcome.phase != "update":
                _tab.QTimer.singleShot(0, self._sync_state)
        request_payloads = tuple(outcome.request_payloads)
        for coalesced_payload in request_payloads[:-1]:
            self._send_dotnet_command_result(
                outcome.result.action,
                ok=True,
                status="coalesced",
                revision=outcome.result.revision,
                diagnostics=("Superseded by a newer cumulative stroke update.",),
                request_payload=coalesced_payload,
            )
        self._send_dotnet_native_update(
            update,
            result=outcome.result,
            request_payload=request_payloads[-1] if request_payloads else None,
        )
        if outcome.source == "dotnet_morph":
            self._send_dotnet_cached_morph_state(
                request_payload=request_payloads[-1] if request_payloads else None,
            )
        if outcome.phase in {"end", "cancel"}:
            if outcome.source == "dotnet_morph":
                self.standalone_dotnet_morph_change_id = ""
            else:
                self.standalone_native_mesh_edit_stroke_id = ""
            self._send_dotnet_session_state()
    def _handle_dotnet_live_stroke_failed(self, failure: object) -> None:
        if not isinstance(failure, _tab.MeshLiveStrokeFailure) or failure.source not in {"dotnet", "dotnet_morph"}:
            return
        controller = self._dotnet_target_controller()
        if controller is None or failure.controller is not controller:
            return
        if failure.phase in {"begin", "end", "cancel"}:
            if failure.source == "dotnet_morph":
                self.standalone_dotnet_morph_change_id = ""
            else:
                self.standalone_native_mesh_edit_stroke_id = ""
        if failure.cancelled:
            return
        message = f"Mesh .NET editor stroke failed: {failure.message}"
        self._set_dotnet_status(message, error=True)
        request_payloads = tuple(failure.request_payloads) or (None,)
        for request_payload in request_payloads:
            self._send_dotnet_command_result(
                "morph_change" if failure.source == "dotnet_morph" else "stroke",
                ok=False,
                status="error",
                diagnostics=(failure.message,),
                request_payload=request_payload,
            )
        if failure.source == "dotnet_morph":
            self._send_dotnet_cached_morph_state(
                request_payload=request_payloads[-1],
                failure=failure.message,
            )

    def _handle_dotnet_morph_command_request(
        self,
        controller: _tab.MeshEditorController,
        command: str,
        payload: Mapping[str, object],
    ) -> bool:
        if command == "morph_change":
            phase = str(payload.get("phase", "end") or "end").strip().lower()
            change_id = str(payload.get("change_id") or "").strip()
            definition_id = str(payload.get("definition_id") or "").strip()
            if phase not in {"begin", "update", "end", "cancel"} or not change_id or not definition_id:
                self._send_dotnet_command_result(
                    command,
                    ok=False,
                    status="error",
                    diagnostics=("Morph change requires definition_id, change_id, and a valid phase.",),
                    request_payload=payload,
                )
                return False
            if self._standalone_action_worker_active() or self.standalone_native_mesh_edit_stroke_id:
                return self._reject_dotnet_mutation_while_busy(command, payload)
            if phase == "begin":
                if self.standalone_dotnet_morph_change_id and self.standalone_dotnet_morph_change_id != change_id:
                    self._send_dotnet_command_result(
                        command,
                        ok=False,
                        status="busy",
                        diagnostics=("Finish the active Morph & Refit slider change first.",),
                        request_payload=payload,
                    )
                    return True
                self.standalone_dotnet_morph_change_id = change_id
            elif self.standalone_dotnet_morph_change_id and self.standalone_dotnet_morph_change_id != change_id:
                self._send_dotnet_command_result(
                    command,
                    ok=False,
                    status="error",
                    diagnostics=("Ignored stale Morph & Refit change id.",),
                    request_payload=payload,
                )
                return False
            queued = _tab.MeshEditCommand(
                "morph_change",
                params={
                    "definition_id": definition_id,
                    "value": self._standalone_native_payload_float(payload.get("value"), 0.0),
                    "phase": phase,
                    "change_id": change_id,
                },
                label="Adjust Procedural Morph",
            )
            sequence = self._ensure_standalone_live_stroke_dispatcher().submit(
                controller,
                queued,
                phase,
                source="dotnet_morph",
                request_payload=payload,
            )
            if sequence > 0:
                return True
            if phase in {"begin", "end", "cancel"}:
                self.standalone_dotnet_morph_change_id = ""
            self._send_dotnet_command_result(
                command,
                ok=False,
                status="cancelled",
                diagnostics=("Morph & Refit dispatcher is stopping.",),
                request_payload=payload,
            )
            return False

        if self._reject_dotnet_mutation_while_busy(command, payload):
            return True
        local_selection = self._dotnet_local_selection_payload_to_selection(payload)
        params: dict[str, object] = {}
        if command in {"morph_activate", "morph_delete_profile"}:
            params["profile_id"] = str(payload.get("profile_id") or "").strip()
        elif command == "morph_delete_definition":
            params["definition_id"] = str(payload.get("definition_id") or "").strip()
        elif command in {"morph_apply_preset", "morph_delete_preset"}:
            params["preset_id"] = str(payload.get("preset_id") or "").strip()
        elif command == "morph_save_preset":
            params.update({
                "preset_id": str(payload.get("preset_id") or "").strip(),
                "name": str(payload.get("name") or payload.get("preset_name") or "").strip(),
            })
        elif command == "morph_set_driver":
            params["submesh_indices"] = tuple(local_selection.source_indices)
        elif command == "morph_bind":
            params["garment_submesh_indices"] = tuple(local_selection.source_indices)
        elif command == "morph_author_definition":
            for key in (
                "profile_id", "profile_name", "definition_id", "label", "category",
                "rule", "axis", "amount", "feather", "falloff", "mirror_mode",
                "min_percent", "max_percent", "default_percent", "local_basis",
                "preserve_selection", "source_definition_id",
            ):
                if key in payload:
                    params[key] = payload[key]
        worker_command = _tab.MeshEditCommand(
            command,
            selection=local_selection if command in {"morph_author_definition", "morph_set_driver", "morph_bind"} else None,
            params=params,
            label=command.removeprefix("morph_").replace("_", " ").title(),
        )
        return self._start_dotnet_action_worker(
            controller,
            worker_command,
            command_name=command,
            request_payload=payload,
        )

    def _handle_dotnet_embedded_part_command(
        self,
        command: str,
        local_selection: object,
        target_mode: str,
        payload: Mapping[str, object],
    ) -> bool | None:
        if not (
            self.standalone_dotnet_target_embedded
            and target_mode in {"part", "source"}
            and command in {"delete", "duplicate", "toggle_visibility"}
        ):
            return None
        runner = getattr(self.active_builder(), "_mesh_editor_embedded_run_part_action", None)
        if not callable(runner):
            self._send_dotnet_command_result(
                command,
                ok=False,
                status="unavailable",
                diagnostics=("Resident part action bridge is unavailable.",),
                request_payload=payload,
            )
            return False
        try:
            ok = bool(runner(command, tuple(local_selection.source_indices)))
        except Exception as exc:
            self._set_dotnet_status(f"Mesh .NET editor part action failed: {command}: {exc}", error=True)
            self._send_dotnet_command_result(
                command,
                ok=False,
                status="error",
                diagnostics=(str(exc),),
                request_payload=payload,
            )
            return False
        revision = None
        current_controller = self._dotnet_target_controller()
        if current_controller is not None:
            try:
                revision = current_controller.session_view().revision
            except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
                pass
        self._refresh_embedded_workspace_from_builder()
        self._send_dotnet_command_result(
            command,
            ok=ok,
            status="applied" if ok else "no_change",
            revision=revision,
            request_payload=payload,
        )
        self._send_dotnet_session_state()
        return ok

    def _handle_dotnet_command_request(self, payload: Mapping[str, object]) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        command = str(payload.get("command", payload.get("action", "")) or "").strip().lower()
        command = command.replace("-", "_")
        if not command:
            self._send_dotnet_command_result("command", ok=False, status="error", diagnostics=("Missing command.",), request_payload=payload)
            return False
        if command.startswith("morph_"):
            return self._handle_dotnet_morph_command_request(controller, command, payload)
        if self._reject_dotnet_mutation_while_busy(command, payload):
            return True
        if command in {"copy", "paste"}:
            self._send_dotnet_command_result(
                command,
                ok=False,
                status="disabled",
                diagnostics=("Mesh clipboard is disabled until metadata-preserving paste is proved; use Duplicate for same-selection copies.",),
                request_payload=payload,
            )
            return False
        local_selection = self._dotnet_local_selection_payload_to_selection(payload)
        selection_supplied = isinstance(payload.get("local_selection"), Mapping) or isinstance(
            payload.get("selection"), Mapping
        )
        action_selection = local_selection if selection_supplied else None
        target_mode = str(payload.get("target_mode", "") or "").strip().lower()
        embedded_result = self._handle_dotnet_embedded_part_command(
            command,
            local_selection,
            target_mode,
            payload,
        )
        if embedded_result is not None:
            return embedded_result
        try:
            if command == "clear_selection":
                return self._start_dotnet_action_worker(
                    controller,
                    _tab.MeshEditCommand(
                        "select",
                        selection=_tab.MeshEditSelection(),
                        params={"operation": "replace"},
                        label="Clear Selection",
                    ),
                    command_name=command,
                    request_payload=payload,
                )
            elif command == "select_all":
                summary = controller.workspace_summary()
                target_mode = str(payload.get("target_mode", "vertex") or "vertex").strip().lower()
                return self._start_dotnet_action_worker(
                    controller,
                    _tab.MeshEditCommand(
                        "select",
                        selection=_tab.MeshEditSelection.from_maps(
                            source_indices=tuple(part.index for part in summary.parts)
                        ),
                        params={"operation": "all", "target_mode": target_mode},
                        label="Select All",
                    ),
                    command_name=command,
                    request_payload=payload,
                )
            elif command in {"grow", "shrink", "invert"}:
                return self._start_dotnet_action_worker(
                    controller,
                    _tab.MeshEditCommand(
                        "select",
                        selection=local_selection,
                        params={"operation": command, "target_mode": target_mode or "vertex"},
                        label=command.replace("_", " ").title(),
                    ),
                    command_name=command,
                    request_payload=payload,
                )
            else:
                aliases = {
                    "delete_selection": "delete",
                    "subdivide_selection": "subdivide",
                    "refine": "refine_smooth",
                    "duplicate_selection": "duplicate",
                    "move": "transform_move",
                    "grab": "brush_grab",
                    "smooth": "brush_smooth",
                    "inflate": "brush_inflate",
                    "pinch": "brush_pinch",
                }
                action_key = aliases.get(command, command)
                params: dict[str, object] = {}
                if action_key == "transform_move":
                    if "delta" in payload:
                        params["delta"] = self._standalone_native_payload_vec3(payload.get("delta"))
                    elif "translate" in payload:
                        params["translate"] = self._standalone_native_payload_vec3(payload.get("translate"))
                    elif "step" in payload:
                        step = self._standalone_native_payload_float(payload.get("step"), 0.0)
                        axis = str(payload.get("axis", "x") or "x").strip().lower()
                        params["delta"] = (step if axis == "x" else 0.0, step if axis == "y" else 0.0, step if axis == "z" else 0.0)
                    if "axis" in payload:
                        params["axis"] = str(payload.get("axis") or "").strip().lower()
                action = mesh_editor_actions_by_key().get(action_key)
                if (
                    action is not None
                    and self._standalone_action_can_run_in_background(action)
                ):
                    worker_command = _tab.MeshEditCommand(
                        action=str(action.command or action_key),
                        selection=action_selection,
                        params=params,
                        mode=str(action.mode or "") or None,
                        label=str(action.text or command),
                    )
                    return self._start_dotnet_action_worker(
                        controller,
                        worker_command,
                        command_name=command,
                        request_payload=payload,
                    )
                result = controller.apply_editor_action(action_key, selection=action_selection, **params)
        except Exception as exc:
            self._set_dotnet_status(f"Mesh .NET editor command failed: {command}: {exc}", error=True)
            self._send_dotnet_command_result(command, ok=False, status="error", diagnostics=(str(exc),), request_payload=payload)
            return False
        return self._apply_dotnet_result_update(controller, result, command_name=command, request_payload=payload)
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
        if not self.standalone_dotnet_target_embedded:
            return False
        if self._reject_dotnet_mutation_while_busy("save_request", request_payload):
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
            self._send_dotnet_command_result(
                "save_request",
                ok=False,
                status="busy",
                diagnostics=("Wait for the active Mesh Editor stroke to finish.",),
                request_payload=request_payload,
            )
            return True
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
        ):
            self._send_dotnet_command_result(
                "save_request",
                ok=False,
                status="error",
                diagnostics=("Resident placement mode transition could not be queued.",),
                request_payload=request_payload,
            )
            return False
        if not self._finalize_embedded_dotnet_import("dotnet_finish_edit"):
            self._send_dotnet_scene_state(
                interaction_mode="mesh_edit",
                comparison_mode="replacement_only",
            )
            self._send_dotnet_command_result(
                "save_request",
                ok=False,
                status="error",
                diagnostics=("Resident mesh edit finalization failed.",),
                request_payload=request_payload,
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
            request_payload=request_payload,
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
