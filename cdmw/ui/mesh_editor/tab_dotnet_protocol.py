from __future__ import annotations

import json

from typing import Mapping

from cdmw.services.mesh_interaction_diagnostics import (
    default_mesh_interaction_log_path,
    flush_mesh_interaction_events,
    record_mesh_interaction_event,
)
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor import tab_dotnet_material_commit as _material_commit
from cdmw.ui.mesh_editor.tab_dotnet_part_colour import MeshEditorDotNetPartColourMixin
from cdmw.ui.mesh_editor.tab_dotnet_resources import MeshEditorDotNetResourceProtocolMixin
from cdmw.ui.mesh_editor.process_io import DOTNET_PROTOCOL_EVENT_LIMIT
from cdmw.ui.mesh_editor.tab_support import (
    STANDALONE_NATIVE_TOOL_STATE as _STANDALONE_NATIVE_TOOL_STATE,
)


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
        "viewport_display_request",
        "capture_request",
        "save_request",
    }
)
_CORRELATION_FIELDS = ("session_id", "request_id", "process_generation")
_SHARED_CONTROLLER_LIFECYCLE_EVENTS = frozenset(
    {
        "activated",
        "package_load_received",
        "package_load_started",
        "package_load_applied",
        "package_load_failed",
    }
)


def _dotnet_protocol_trail_path() -> "object | None":
    """Return the path owned by the background interaction recorder."""

    try:
        return default_mesh_interaction_log_path()
    except Exception:
        return None


def _write_dotnet_protocol_trail(
    payload: Mapping[str, object],
    *,
    direction: str = "helper_to_host",
    kind: str = "protocol",
) -> bool:
    """Queue one protocol/session event without touching disk on the UI thread."""

    event = str(payload.get("event", payload.get("type", "")) or "").strip().lower()
    return record_mesh_interaction_event(
        kind,
        direction,
        payload,
        critical=event in {
            "error",
            "stroke_end",
            "stroke_cancel",
            "command_result",
            "package_load_failed",
            "textures_error",
        },
    )


def _flush_dotnet_protocol_trail(timeout_seconds: float = 1.0) -> bool:
    return flush_mesh_interaction_events(timeout_seconds)


def _dotnet_event_requires_correlation(event: str, payload: Mapping[str, object]) -> bool:
    # The shared resident controller owns request/generation correlation for
    # package and activation lifecycle events before forwarding them to Mesh
    # Editor consumers. Activation deliberately carries activation_request_id,
    # not the mutation envelope's request_id.
    if event in _SHARED_CONTROLLER_LIFECYCLE_EVENTS:
        return False
    return event in _CORRELATED_HELPER_REQUEST_EVENTS or any(field in payload for field in _CORRELATION_FIELDS)


class MeshEditorDotNetProtocolMixin(
    MeshEditorDotNetPartColourMixin,
    MeshEditorDotNetResourceProtocolMixin,
):
    def _append_dotnet_protocol_event(self, payload: Mapping[str, object]) -> None:
        self.standalone_dotnet_protocol_events.append(dict(payload))
        if len(self.standalone_dotnet_protocol_events) > DOTNET_PROTOCOL_EVENT_LIMIT:
            del self.standalone_dotnet_protocol_events[:-DOTNET_PROTOCOL_EVENT_LIMIT]
        _write_dotnet_protocol_trail(payload)

    def _record_dotnet_interaction_decision(self, event: str, **payload: object) -> None:
        controller = getattr(self, "standalone_controller", None)
        details: dict[str, object] = {
            "event": str(event or "host_decision"),
            "session_id": str(getattr(controller, "active_session_id", "") or ""),
            "process_generation": int(
                getattr(self, "standalone_dotnet_process_generation", 0) or 0
            ),
            **payload,
        }
        dispatcher = getattr(self, "standalone_live_stroke_dispatcher", None)
        metrics = getattr(dispatcher, "metrics", None)
        if callable(metrics):
            try:
                details["dispatcher"] = dict(metrics())
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        _write_dotnet_protocol_trail(
            details,
            direction="host_internal",
            kind="host_decision",
        )

    def _reset_resident_mutation_ui_state(self) -> None:
        self.standalone_dotnet_pending_mutation_commits.clear()
        self.standalone_dotnet_recovery_failure_reported = False

    def _finalize_resident_mutation_ui_commit(self, payload: Mapping[str, object]) -> None:
        try:
            request_id = int(payload.get("request_id", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            return
        pending = self.standalone_dotnet_pending_mutation_commits.get(request_id)
        if pending is None:
            return
        metrics = self.standalone_dotnet_update_queue.metrics()
        target_revision = int(pending.get("target_revision", 0) or 0)
        status = str(payload.get("status", "") or "").strip().lower()
        if (
            status not in {"applied", "already_applied"}
            or int(metrics.get("last_acked_revision", 0) or 0) < target_revision
        ):
            return
        self.standalone_dotnet_pending_mutation_commits.pop(request_id, None)
        result = pending.get("result")
        update = pending.get("update")
        if not isinstance(result, _tab.MeshEditResult) or not isinstance(update, _tab.MeshEditorNativeUpdate):
            return
        selection_result = str(result.action or "").strip().lower() in {
            "select",
            "clear_selection",
        }
        if bool(pending.get("commit_embedded")):
            committed = self._commit_embedded_edit_result(
                result,
                command_name=str(pending.get("command_name", result.action) or result.action),
                request_payload=pending.get("request_payload"),
                authoritative_selection=(
                    update.session_view.selection
                    if selection_result and update.session_view is not None
                    else None
                ),
                resident_history=bool(pending.get("resident_history")),
            )
            if not committed:
                message = "Mesh Editor renderer synchronization failed. Reload the session to continue editing."
                self._set_dotnet_status(message, error=True)
                self.status_message_requested.emit(message, True)
                self._request_or_stop_blocked_embedded_dotnet(
                    "mesh_dotnet_embedded_commit_settlement_failed"
                )
                return
            self._refresh_embedded_workspace_from_builder(
                include_derived=not selection_result,
                session_view=update.session_view if selection_result else None,
            )
            if selection_result:
                self._refresh_embedded_active_selection_summary(
                    selection=(
                        update.session_view.selection
                        if update.session_view is not None
                        else None
                    )
                )
        controller = self._dotnet_target_controller()
        view = update.session_view
        if view is None and controller is not None:
            try:
                view = controller.session_view()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                view = None
        if view is not None:
            self.update_editor_session_state(
                view,
                active_selection_mode=str(
                    getattr(controller, "active_selection_mode", "") or self.current_selection_mode
                ),
            )
        if bool(pending.get("refresh_morph_state")):
            self._send_dotnet_cached_morph_state(
                request_payload=pending.get("request_payload")
            )
        self._record_mesh_dotnet_event(
            "mesh_dotnet_resident_mutation_committed",
            request_id=request_id,
            edit_revision=target_revision,
            command=str(result.action or "command"),
        )

    def _sync_resident_mutation_recovery_state(self) -> None:
        metrics = self.standalone_dotnet_update_queue.metrics()
        ui_state = self._refresh_mesh_editor_ui_state()
        if ui_state.invariant_errors and not self.standalone_dotnet_recovery_failure_reported:
            self.standalone_dotnet_recovery_failure_reported = True
            message = "Mesh Editor renderer synchronization failed. Reload the session to continue editing."
            self._set_dotnet_status(message, error=True)
            self.status_message_requested.emit(message, True)
            self._record_mesh_dotnet_event(
                "mesh_editor_ui_state_invariant_failed",
                error_code=ui_state.recovery_error_code,
                session_id=ui_state.session_id,
                process_generation=ui_state.process_generation,
                request_id=ui_state.pending_request_id,
                base_revision=ui_state.pending_base_revision,
                target_revision=ui_state.pending_target_revision,
                service_revision=ui_state.service_revision,
                renderer_revision=ui_state.renderer_revision,
                ui_state=ui_state.as_payload(),
                queue_metrics=metrics,
            )
        if bool(metrics.get("recovery_failed")):
            if not self.standalone_dotnet_recovery_failure_reported:
                self.standalone_dotnet_recovery_failure_reported = True
                message = "Mesh Editor renderer synchronization failed. Reload the session to continue editing."
                self._set_dotnet_status(message, error=True)
                self.status_message_requested.emit(message, True)
                self._record_mesh_dotnet_event(
                    "mesh_dotnet_resident_mutation_recovery_failed",
                    session_id=ui_state.session_id,
                    process_generation=ui_state.process_generation,
                    request_id=ui_state.pending_request_id,
                    base_revision=ui_state.pending_base_revision,
                    target_revision=ui_state.pending_target_revision,
                    service_revision=ui_state.service_revision,
                    renderer_revision=ui_state.renderer_revision,
                    queue_metrics=metrics,
                    ui_state=ui_state.as_payload(),
                )
        elif bool(metrics.get("resync_active")):
            self.standalone_dotnet_recovery_failure_reported = False
            self._set_dotnet_status(
                "Mesh Editor is synchronizing with the renderer. Editing is temporarily unavailable."
            )
        else:
            self.standalone_dotnet_recovery_failure_reported = False
        self._sync_state()

    def _connect_dotnet_protocol(self, process: _tab.QProcess) -> None:
        self.standalone_dotnet_update_ack_start_timer.stop()
        self.standalone_dotnet_update_ack_timer.stop()
        self._reset_resident_mutation_ui_state()
        self.standalone_dotnet_update_queue.reset()
        self.standalone_dotnet_material_parameter_timer.stop()
        self.standalone_dotnet_pending_material_parameter_payload = None
        _material_commit.remember_sent_material_parameters(self, None)
        _material_commit.remember_sent_material_resources(self, None)
        self.standalone_dotnet_protocol_stdout = ""
        self.standalone_dotnet_protocol_events = []
        self.standalone_dotnet_capabilities.clear()
        self.standalone_dotnet_provenance_verified = False
        self.standalone_dotnet_morph_sent_state_revision = -1
        self.standalone_dotnet_morph_ack_state_revision = -1
        self.standalone_dotnet_morph_sent_change_id = ""
        self.standalone_dotnet_morph_sent_request_id = 0
        self.standalone_dotnet_presentation_pending = None
        self.standalone_dotnet_presentation_queued = False
        self.standalone_dotnet_presentation_acknowledged = None
        # A fresh process holds no presentation state.
        self.standalone_dotnet_presentation_published_content = None
        self._record_dotnet_interaction_decision(
            "mesh_edit_session_protocol_connected",
            embedded=bool(self.standalone_dotnet_target_embedded),
        )
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
        # Drain every complete message before enforcing the buffer limit. A busy
        # UI thread lets a legitimate burst (a live stroke reports one message
        # per sampled mouse move) accumulate past the limit in a single read, and
        # tearing the editor down over well-formed messages is what made brush
        # and move strokes look like a helper crash. The limit exists to bound an
        # unterminated message, so it is applied to the residue below.
        while "\n" in self.standalone_dotnet_protocol_stdout:
            line, self.standalone_dotnet_protocol_stdout = self.standalone_dotnet_protocol_stdout.split("\n", 1)
            if len(line) > _tab.DOTNET_PROTOCOL_LINE_LIMIT:
                self._record_mesh_dotnet_event("mesh_dotnet_protocol_line_limit", line_chars=len(line))
                self._set_dotnet_status("Mesh .NET editor protocol ignored an oversized message.", error=True)
                continue
            self._handle_dotnet_protocol_line(line.strip())
        if len(self.standalone_dotnet_protocol_stdout) > _tab.DOTNET_PROTOCOL_BUFFER_LIMIT:
            buffered = len(self.standalone_dotnet_protocol_stdout)
            self.standalone_dotnet_protocol_stdout = ""
            self._record_mesh_dotnet_event("mesh_dotnet_protocol_buffer_limit", buffered_chars=buffered)
            self._set_dotnet_status("Mesh .NET editor protocol exceeded its input limit.", error=True)
            self._stop_standalone_dotnet_editor_process(embedded_state="failed")
            return
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
            # Dense real-PAC topology updates can take longer than one second
            # in the renderer even though they are progressing normally. Keep
            # recovery bounded without racing a valid acknowledgement.
            self.standalone_dotnet_update_ack_timer.start(5_000)
        else:
            self.standalone_dotnet_update_ack_timer.stop()
    def _handle_dotnet_update_ack_timeout(self) -> None:
        metrics = self.standalone_dotnet_update_queue.metrics()
        revision = int(metrics.get("active_revision", 0) or 0)
        if revision <= 0 or not self.standalone_dotnet_update_queue.expire_active(revision):
            return
        self._record_mesh_dotnet_event("mesh_dotnet_update_ack_timeout", edit_revision=revision)
        self._sync_dotnet_update_ack_timer()
        self._sync_resident_mutation_recovery_state()
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
        if event in {
            "preview_vertex_update_ack",
            "preview_triangle_update_ack",
            "resident_state_resync_ack",
            "resident_mutation_batch_ack",
        }:
            self._append_dotnet_protocol_event(payload)
            handled = self.standalone_dotnet_update_queue.acknowledge(event, payload)
            self._sync_dotnet_update_ack_timer()
            if event == "resident_mutation_batch_ack":
                self._finalize_resident_mutation_ui_commit(payload)
            self._sync_resident_mutation_recovery_state()
            if handled:
                self._flush_pending_dotnet_live_stroke_presentation()
            return handled
        if event == "scene_state_update_ack":
            return self._handle_dotnet_scene_state_ack(payload)
        if event == "morph_state_update_ack":
            if not self._dotnet_session_matches(payload):
                return False
            revision = self._standalone_native_payload_int(payload.get("state_revision"), -1)
            change_id = str(payload.get("change_id") or "")
            request_id = self._standalone_native_payload_int(payload.get("request_id"), 0)
            if (
                revision != self.standalone_dotnet_morph_sent_state_revision
                or revision <= self.standalone_dotnet_morph_ack_state_revision
                or change_id != self.standalone_dotnet_morph_sent_change_id
                or request_id != self.standalone_dotnet_morph_sent_request_id
            ):
                return False
            self.standalone_dotnet_morph_ack_state_revision = revision
            return True
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
        if event in {
            "performance_capture_started",
            "performance_capture_stopping",
            "performance_capture_complete",
        }:
            self.standalone_dotnet_status_payload["performance_capture"] = dict(payload)
            return True
        if event == "renderer_status":
            renderer = payload.get("renderer")
            if not isinstance(renderer, Mapping):
                return False
            self.standalone_dotnet_status_payload["renderer"] = dict(renderer)
            self.standalone_dotnet_status_payload["renderer_status_response"] = {
                "request_id": int(payload.get("request_id", 0) or 0),
                "session_id": str(payload.get("session_id", "") or ""),
                "process_generation": int(payload.get("process_generation", 0) or 0),
            }
            return self._handle_dotnet_renderer_status(
                {"renderer": renderer},
                source_event="renderer_status",
                emit_warning=False,
            )
        return self._handle_dotnet_request_event(payload, event)

    def _handle_dotnet_request_event(self, payload: Mapping[str, object], event: str) -> bool:
        """Dispatch the helper's requests, as opposed to its acknowledgements.

        The clauses above this one report that something the host asked for has
        landed. These are the helper asking the host to do something, which is
        the half that can refuse, fail, or answer with a correlated result.
        """

        if event == "select_request":
            return self._handle_dotnet_select_request(payload)
        if event == "selection_request":
            return self._handle_dotnet_local_selection_request(payload)
        if event in {"stroke_begin", "stroke_update", "stroke_end", "stroke_cancel"}:
            return self._handle_dotnet_stroke_event(payload, event.removeprefix("stroke_"))
        if event in {"command_request", "command_requested"}:
            return self._handle_dotnet_command_request(payload)
        if event == "tool_changed":
            return self._handle_dotnet_tool_changed(payload)
        if event == "viewport_display_request":
            return self._handle_embedded_viewport_display_mode(
                str(payload.get("mode", "") or "")
            )
        if event == "part_material_edit_request":
            return self._handle_dotnet_part_material_edit_request(payload)
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
                applied = bool(
                    handler(
                        placement,
                        phase=str(payload.get("placement_phase", "end") or "end"),
                    )
                )
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
            self._set_embedded_dotnet_preview_loading(False, message)
            self._set_dotnet_status(message, error=True)
            return False
        return False

    def _handle_dotnet_tool_changed(self, payload: Mapping[str, object]) -> bool:
        # The editor's tool rail is the only tool picker visible in Edit Mesh.
        # The builder must adopt what it armed before the next control refresh.
        adopt = getattr(self.active_builder(), "_mesh_editor_dotnet_tool_changed", None)
        if callable(adopt):
            try:
                return bool(adopt(dict(payload)))
            except Exception as exc:
                self._record_runtime_event("mesh_editor_dotnet_tool_changed_failed", error=str(exc))
                return False
        tool = str(payload.get("tool", "") or "").strip().lower()
        action_key, edit_mode = next(
            (
                (key, mode)
                for key, (native_tool, _target_mode, mode) in _STANDALONE_NATIVE_TOOL_STATE.items()
                if native_tool == tool
            ),
            ("", ""),
        )
        if tool != "orbit" and not action_key:
            return False
        self.set_active_tool_state(mode=edit_mode, active_tool_key=action_key)
        return True

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
                    self._set_embedded_dotnet_preview_loading(
                        False,
                        "Mesh Editor preview renderer is unavailable.",
                    )
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
            self._set_embedded_dotnet_preview_loading(False, "Preview ready.")
            # The working model is committed to the resident session here, so
            # this is where an imported model publishes its own materials. The
            # launch package deliberately carries none, and before this the only
            # route ran inside the Original resolver -- so an import whose
            # Original pane never resolved stayed grey forever.
            self.commit_imported_working_model_materials(reason="resident_ready")
            self._flush_pending_dotnet_reference_material_resources()
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
            # `activated` is emitted *after* the helper has revealed its window.
            # Re-pushing state the rehydrator already delivered before activation
            # makes the helper re-run its interaction-mode controls on screen, so
            # the reader watches the tool rail re-assert itself. A resume that
            # never went through a package apply has no rehydrate behind it and
            # still needs this.
            if not self._dotnet_state_already_pushed_for_process():
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
            self._set_embedded_dotnet_preview_loading(False, "Preview ready.")
            # A resumed session commits the same working model, and the helper
            # it is resuming into may be a different process that holds none of
            # its materials.
            self.commit_imported_working_model_materials(reason="resident_activated")
            self._flush_pending_dotnet_reference_material_resources()
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
        finish_matcher = getattr(self, "_dotnet_finish_scene_matches", None)
        finish_matches = bool(callable(finish_matcher) and finish_matcher(payload))
        self.standalone_dotnet_scene_pending = None
        if status != "applied":
            self.standalone_dotnet_scene_candidate = None
            self._set_dotnet_status(
                "Resident scene frame was rejected; the last acknowledged frame remains active: "
                + str(payload.get("reason", "unknown reason") or "unknown reason"),
                error=True,
            )
            if finish_matches:
                self._fail_embedded_dotnet_edit_mode_finish(
                    "Resident placement mode transition could not be queued."
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
        self._observe_edit_session_from_scene_frame()
        if finish_matches:
            self._complete_embedded_dotnet_edit_mode_finish()
        if not self._sync_embedded_builder_presentation_state():
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
            # The helper did not take it, so it is not holding it. Forget the
            # record or the next publish would be skipped as already-applied.
            self.standalone_dotnet_presentation_published_content = None
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
