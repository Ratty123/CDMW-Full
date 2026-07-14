from __future__ import annotations

import json
from typing import Mapping

from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor import tab_dotnet_material_commit as _material_commit
from cdmw.ui.mesh_editor.tab_dotnet_resources import MeshEditorDotNetResourceProtocolMixin
from cdmw.ui.mesh_editor.process_io import DOTNET_PROTOCOL_EVENT_LIMIT


_CORRELATED_HELPER_REQUEST_EVENTS = frozenset(
    {
        "select_request",
        "selection_request",
        "stroke_begin",
        "stroke_update",
        "stroke_end",
        "stroke_cancel",
        "command_request",
        "command_requested",
        "placement_transform_request",
        "capture_request",
        "save_request",
    }
)
_CORRELATION_FIELDS = ("session_id", "request_id", "process_generation")


def _dotnet_event_requires_correlation(event: str, payload: Mapping[str, object]) -> bool:
    return event in _CORRELATED_HELPER_REQUEST_EVENTS or any(field in payload for field in _CORRELATION_FIELDS)


class MeshEditorDotNetProtocolMixin(MeshEditorDotNetResourceProtocolMixin):
    def _append_dotnet_protocol_event(self, payload: Mapping[str, object]) -> None:
        self.standalone_dotnet_protocol_events.append(dict(payload))
        if len(self.standalone_dotnet_protocol_events) > DOTNET_PROTOCOL_EVENT_LIMIT:
            del self.standalone_dotnet_protocol_events[:-DOTNET_PROTOCOL_EVENT_LIMIT]

    def _connect_dotnet_protocol(self, process: _tab.QProcess) -> None:
        self.standalone_dotnet_update_ack_timer.stop()
        self.standalone_dotnet_update_queue.reset()
        self.standalone_texture_region_queue.reset()
        self.standalone_dotnet_material_parameter_timer.stop()
        self.standalone_dotnet_pending_material_parameter_payload = None
        _material_commit.remember_sent_material_parameters(self, None)
        _material_commit.remember_sent_material_resources(self, None)
        self.standalone_dotnet_protocol_stdout = ""
        self.standalone_dotnet_protocol_events = []
        self.standalone_dotnet_capabilities.clear()
        self.standalone_dotnet_provenance_verified = False
        self.standalone_dotnet_presentation_pending = None
        self.standalone_dotnet_presentation_queued = False
        self.standalone_dotnet_presentation_acknowledged = None
        try:
            process.readyReadStandardOutput.connect(
                lambda target=process: self._handle_dotnet_protocol_stdout_ready(target)
            )
            process.started.connect(self._send_dotnet_session_state)
        except (AttributeError, RuntimeError, TypeError):
            pass
        try:
            process.readyReadStandardError.connect(
                lambda target=process: self._handle_dotnet_protocol_stderr_ready(target)
            )
        except (AttributeError, RuntimeError, TypeError):
            pass
    def _handle_dotnet_protocol_stdout_ready(self, process: _tab.QProcess) -> None:
        if self.standalone_dotnet_editor_process is not process:
            return
        try:
            raw = bytes(process.readAllStandardOutput())
        except (AttributeError, RuntimeError, TypeError):
            return
        if not raw:
            return
        self.standalone_dotnet_protocol_stdout += raw.decode("utf-8", "replace")
        if len(self.standalone_dotnet_protocol_stdout) > _tab.DOTNET_PROTOCOL_BUFFER_LIMIT:
            buffered = len(self.standalone_dotnet_protocol_stdout)
            self.standalone_dotnet_protocol_stdout = ""
            self._record_mesh_dotnet_event("mesh_dotnet_protocol_buffer_limit", buffered_chars=buffered)
            self._set_dotnet_status("Mesh .NET editor protocol exceeded its input limit.", error=True)
            self._stop_standalone_dotnet_editor_process(embedded_state="failed")
            return
        while "\n" in self.standalone_dotnet_protocol_stdout:
            line, self.standalone_dotnet_protocol_stdout = self.standalone_dotnet_protocol_stdout.split("\n", 1)
            if len(line) > _tab.DOTNET_PROTOCOL_LINE_LIMIT:
                self._record_mesh_dotnet_event("mesh_dotnet_protocol_line_limit", line_chars=len(line))
                self._set_dotnet_status("Mesh .NET editor protocol ignored an oversized message.", error=True)
                continue
            self._handle_dotnet_protocol_line(line.strip())
    def _handle_dotnet_protocol_stderr_ready(self, process: _tab.QProcess) -> None:
        if self.standalone_dotnet_editor_process is not process:
            return
        try:
            raw = bytes(process.readAllStandardError())
        except (AttributeError, RuntimeError, TypeError):
            return
        self.standalone_dotnet_stderr_tail = _tab.append_bounded_text(
            self.standalone_dotnet_stderr_tail,
            raw.decode("utf-8", "replace"),
        )
    def _handle_dotnet_protocol_line(self, line: str) -> bool:
        if not line:
            return False
        try:
            payload = json.loads(line)
        except ValueError:
            self._set_dotnet_status("Mesh .NET editor protocol ignored malformed JSON.", error=True)
            return False
        if not isinstance(payload, dict):
            self._set_dotnet_status("Mesh .NET editor protocol ignored non-object JSON.", error=True)
            return False
        return self._handle_dotnet_protocol_event(payload)
    def _sync_dotnet_update_ack_timer(self) -> None:
        metrics = self.standalone_dotnet_update_queue.metrics()
        if int(metrics.get("active_revision", 0) or 0) > 0:
            self.standalone_dotnet_update_ack_timer.start(1_000)
        else:
            self.standalone_dotnet_update_ack_timer.stop()
    def _handle_dotnet_update_ack_timeout(self) -> None:
        metrics = self.standalone_dotnet_update_queue.metrics()
        revision = int(metrics.get("active_revision", 0) or 0)
        if revision <= 0 or not self.standalone_dotnet_update_queue.expire_active(revision):
            return
        self._record_mesh_dotnet_event("mesh_dotnet_update_ack_timeout", edit_revision=revision)
        self._sync_dotnet_update_ack_timer()
    def _handle_dotnet_protocol_event(self, payload: Mapping[str, object]) -> bool:
        event = str(payload.get("event", payload.get("type", "")) or "").strip().lower()
        if not event:
            self._set_dotnet_status("Mesh .NET editor protocol message had no event.", error=True)
            return False
        if event == "presentation_split_changed":
            self._append_dotnet_protocol_event(payload)
            handler = getattr(
                self.active_builder(),
                "_mesh_editor_embedded_split_ratio_changed",
                None,
            )
            if not callable(handler):
                return False
            try:
                return bool(handler(float(payload.get("ratio", 0.5) or 0.5)))
            except (TypeError, ValueError, AttributeError, RuntimeError):
                return False
        if event in {"preview_vertex_update_ack", "preview_triangle_update_ack"}:
            self._append_dotnet_protocol_event(payload)
            handled = self.standalone_dotnet_update_queue.acknowledge(event, payload)
            self._sync_dotnet_update_ack_timer()
            return handled
        if event in {"texture_region_applied", "texture_region_failed"}:
            if not self._dotnet_session_matches(payload):
                return False
            self._append_dotnet_protocol_event(payload)
            return self.standalone_texture_region_queue.acknowledge(event, payload)
        if event == "scene_state_update_ack":
            return self._handle_dotnet_scene_state_ack(payload)
        if event == "presentation_state_update_ack":
            return self._handle_dotnet_presentation_state_ack(payload)
        self._append_dotnet_protocol_event(payload)
        if _dotnet_event_requires_correlation(event, payload) and not self._dotnet_session_matches(payload):
            self._send_dotnet_command_result(
                str(payload.get("command", event) or event),
                ok=False,
                status="error",
                diagnostics=("Stale .NET mesh editor session id.",),
                request_payload=payload,
            )
            return False
        lifecycle_result = self._handle_dotnet_lifecycle_event(payload, event)
        if lifecycle_result is not None:
            return lifecycle_result
        if event in {"material_sync_required", "material_state_applied", "material_state_failed", "material_reload_required"}:
            return self._handle_dotnet_material_protocol_event(payload, event)
        if event in {"material_parameter_applied", "material_parameter_failed"}:
            return self._handle_dotnet_material_parameter_event(payload, event)
        if event == "capture_result":
            return self._handle_dotnet_capture_result(payload)
        if event == "select_request":
            return self._handle_dotnet_select_request(payload)
        if event == "selection_request":
            return self._handle_dotnet_local_selection_request(payload)
        if event in {"stroke_begin", "stroke_update", "stroke_end", "stroke_cancel"}:
            return self._handle_dotnet_stroke_event(payload, event.removeprefix("stroke_"))
        if event in {"command_request", "command_requested"}:
            return self._handle_dotnet_command_request(payload)
        if event == "placement_transform_request":
            handler = getattr(self.active_builder(), "_mesh_editor_apply_dotnet_placement_state", None)
            placement = payload.get("placement")
            if not callable(handler) or not isinstance(placement, Mapping):
                self._send_dotnet_command_result(
                    "placement_transform",
                    ok=False,
                    status="unavailable",
                    diagnostics=("Resident placement bridge is unavailable.",),
                    request_payload=payload,
                )
                return False
            try:
                applied = bool(handler(placement))
                self._send_dotnet_command_result(
                    "placement_transform",
                    ok=applied,
                    status="applied" if applied else "rejected",
                    request_payload=payload,
                )
                return applied
            except Exception as exc:
                self._set_dotnet_status(f"Mesh .NET placement update failed: {exc}", error=True)
                self._send_dotnet_command_result(
                    "placement_transform",
                    ok=False,
                    status="error",
                    diagnostics=(str(exc),),
                    request_payload=payload,
                )
                return False
        if event == "save_request":
            if self.standalone_dotnet_target_embedded:
                return self._finish_embedded_dotnet_edit_mode(payload)
            sent = self._send_dotnet_protocol_message({"event": "close_request"})
            if sent:
                self._flush_dotnet_protocol_messages()
                self._set_dotnet_status("Saving resident .NET mesh edits...")
            return bool(sent)
        if event == "error":
            message = str(payload.get("message", "") or "Mesh .NET editor reported an error.")
            self._set_dotnet_status(message, error=True)
            return False
        return False

    def _handle_dotnet_lifecycle_event(
        self,
        payload: Mapping[str, object],
        event: str,
    ) -> bool | None:
        if event == "ready":
            self._observe_dotnet_capabilities(payload)
            if (
                "helper_build_provenance_v1" in self.standalone_dotnet_capabilities
                and not self.standalone_dotnet_provenance_verified
                and not self._verify_dotnet_helper_provenance(payload)
            ):
                return False
            self.standalone_dotnet_update_queue.observe_capabilities(payload)
            self.standalone_dotnet_material_signature = str(
                payload.get("material_signature", self.standalone_dotnet_material_signature) or ""
            )
            self.standalone_dotnet_status_payload["host_lifecycle_counts"] = dict(
                self.standalone_dotnet_lifecycle_counts
            )
            self.standalone_dotnet_ready_timer.stop()
            if not self._handle_dotnet_renderer_status(payload, source_event="ready"):
                if self.standalone_dotnet_target_embedded:
                    self._request_or_stop_blocked_embedded_dotnet("mesh_dotnet_renderer_blocked")
                return False
            renderer = payload.get("renderer")
            if isinstance(renderer, Mapping):
                self.standalone_dotnet_status_payload["renderer"] = dict(renderer)
            self._record_mesh_dotnet_event(
                "mesh_dotnet_process_ready",
                embedded=bool(self.standalone_dotnet_target_embedded),
                package_dir=str(getattr(self.standalone_dotnet_experiment_package, "package_dir", "") or ""),
                status_path=str(getattr(self.standalone_dotnet_experiment_package, "status_path", "") or ""),
            )
            if self.standalone_dotnet_target_embedded:
                self._record_mesh_dotnet_event(
                    "mesh_dotnet_embedded_ready_accepted",
                    dotnet_state=str(self.standalone_dotnet_embedded_state or ""),
                    package_dir=str(getattr(self.standalone_dotnet_experiment_package, "package_dir", "") or ""),
                    status_path=str(getattr(self.standalone_dotnet_experiment_package, "status_path", "") or ""),
                )
                self._set_embedded_dotnet_state("ready", active=True)
                self._notify_embedded_dotnet_ready()
                self.update_editor_action_state(selection_empty=self.current_selection_empty)
            self._send_dotnet_session_state()
            comparison_mode, interaction_mode = self._dotnet_initial_scene_modes(
                embedded=bool(self.standalone_dotnet_target_embedded)
            )
            self._send_dotnet_scene_state(
                comparison_mode=comparison_mode,
                interaction_mode=interaction_mode,
                placement=self._dotnet_current_placement_state(
                    embedded=bool(self.standalone_dotnet_target_embedded)
                ),
            )
            self._sync_embedded_builder_presentation_state()
            return True
        if event == "protocol_ready":
            self._observe_dotnet_capabilities(payload)
            if "helper_build_provenance_v1" in self.standalone_dotnet_capabilities and not self._verify_dotnet_helper_provenance(payload):
                return False
            self.standalone_dotnet_update_queue.observe_capabilities(payload)
            return True
        if event == "activated":
            self.standalone_dotnet_ready_timer.stop()
            if self.standalone_dotnet_target_embedded:
                self._set_embedded_dotnet_state("ready", active=True)
                self._notify_embedded_dotnet_ready()
                self.update_editor_action_state(selection_empty=self.current_selection_empty)
            self._send_dotnet_session_state()
            comparison_mode, interaction_mode = self._dotnet_initial_scene_modes(
                embedded=bool(self.standalone_dotnet_target_embedded)
            )
            self._send_dotnet_scene_state(
                comparison_mode=comparison_mode,
                interaction_mode=interaction_mode,
                placement=self._dotnet_current_placement_state(
                    embedded=bool(self.standalone_dotnet_target_embedded)
                ),
            )
            self._sync_embedded_builder_presentation_state()
            return True
        if event == "deactivated":
            if self.standalone_dotnet_target_embedded:
                self.standalone_dotnet_deactivate_timer.stop()
                self.standalone_dotnet_deactivate_acknowledged = True
                if self.standalone_dotnet_exit_pending:
                    self._complete_pending_dotnet_exit()
                else:
                    self._set_embedded_dotnet_state("suspended", active=False)
                    self.update_editor_action_state(selection_empty=self.current_selection_empty)
            return True
        if event == "metrics":
            metrics = payload.get("metrics", payload)
            if isinstance(metrics, Mapping):
                self.standalone_dotnet_status_payload["metrics"] = dict(metrics)
                renderer = metrics.get("renderer", payload.get("renderer"))
                if isinstance(renderer, Mapping):
                    self.standalone_dotnet_status_payload["renderer"] = dict(renderer)
                    if not self._handle_dotnet_renderer_status({"renderer": renderer}, source_event="metrics", emit_warning=False):
                        return False
            return True
        if event == "textures_ready":
            renderer = payload.get("renderer")
            if isinstance(renderer, Mapping):
                self.standalone_dotnet_status_payload["renderer"] = dict(renderer)
            self._set_dotnet_status(
                "Mesh .NET textures ready: "
                f"{int(payload.get('decoded_texture_resources', 0) or 0)} decoded, "
                f"{int(payload.get('texture_load_failures', 0) or 0)} failed."
            )
            return True
        if event == "textures_error":
            self._set_dotnet_status(str(payload.get("message", "Texture load failed.") or "Texture load failed."), error=True)
            return False
        return None

    def _handle_dotnet_scene_state_ack(self, payload: Mapping[str, object]) -> bool:
        pending = self.standalone_dotnet_scene_pending
        if pending is None or not self._dotnet_session_matches(payload):
            return False
        try:
            matches = all(
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
        except (TypeError, ValueError, OverflowError):
            return False
        if not matches:
            return False
        status = str(payload.get("status", "") or "").strip().lower()
        self.standalone_dotnet_scene_pending = None
        if status != "applied":
            self.standalone_dotnet_scene_candidate = None
            self._set_dotnet_status(
                "Resident scene frame was rejected; the last acknowledged frame remains active: "
                + str(payload.get("reason", "unknown reason") or "unknown reason"),
                error=True,
            )
            return False
        self.standalone_dotnet_scene_acknowledged_generation = int(
            payload.get("scene_generation", 0) or 0
        )
        self.standalone_dotnet_scene_acknowledged = dict(payload)
        if self.standalone_dotnet_scene_candidate is not None:
            self.standalone_dotnet_scene_frame = self.standalone_dotnet_scene_candidate
        self.standalone_dotnet_scene_candidate = None
        self._record_mesh_dotnet_event(
            "mesh_dotnet_scene_frame_applied",
            request_id=int(payload.get("request_id", 0) or 0),
            scene_generation=self.standalone_dotnet_scene_acknowledged_generation,
        )
        self._send_dotnet_presentation_state()
        return True
    def _handle_dotnet_presentation_state_ack(self, payload: Mapping[str, object]) -> bool:
        pending = self.standalone_dotnet_presentation_pending
        if pending is None or not self._dotnet_session_matches(payload):
            return False
        try:
            matches = (
                int(payload.get("request_id", 0) or 0) == int(pending["request_id"])
                and int(payload.get("process_generation", 0) or 0)
                == int(pending["process_generation"])
                and str(payload.get("session_id", "") or "") == str(pending["session_id"])
            )
        except (TypeError, ValueError, OverflowError):
            return False
        if not matches:
            return False
        self._append_dotnet_protocol_event(payload)
        self.standalone_dotnet_presentation_pending = None
        status = str(payload.get("status", "") or "").strip().lower()
        if status == "applied":
            self.standalone_dotnet_presentation_acknowledged = dict(payload)
            handled = True
        else:
            self._set_dotnet_status(
                "Resident .NET presentation state was rejected: "
                + str(payload.get("reason", "unknown reason") or "unknown reason"),
                error=True,
            )
            handled = False
        if self.standalone_dotnet_presentation_queued:
            self.standalone_dotnet_presentation_queued = False
            self._publish_dotnet_presentation_state()
        return handled
