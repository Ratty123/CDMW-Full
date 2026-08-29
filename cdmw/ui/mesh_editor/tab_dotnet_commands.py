from __future__ import annotations

import json
import time
from typing import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from cdmw.ui.shell.settings_bridge import read_bool_setting
from cdmw.ui.mesh_editor.actions import mesh_editor_actions_by_key


from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


from cdmw.ui.mesh_editor.tab_dotnet_named_commands import MeshEditorDotNetNamedCommandMixin


def _record_interaction_decision(target: object, event: str, **payload: object) -> None:
    recorder = getattr(target, "_record_dotnet_interaction_decision", None)
    if callable(recorder):
        recorder(event, **payload)


_DOTNET_ACTION_ALIASES = {
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


class MeshEditorDotNetCommandMixin(MeshEditorDotNetNamedCommandMixin):
    def _queue_dotnet_topology_after_selection(
        self,
        command_name: str,
        request_payload: Mapping[str, object],
    ) -> bool:
        if command_name not in {"subdivide", "subdivide_selection", "refine", "refine_smooth", "separate"}:
            return False
        if not str(self.standalone_native_selection_stroke_id or "").strip():
            return False
        if self.standalone_pending_dotnet_topology_request is not None:
            self._send_dotnet_command_result(
                command_name,
                ok=False,
                status="busy",
                diagnostics=("A topology command is already waiting for the selection gesture.",),
                request_payload=request_payload,
            )
            return True
        queued_payload = dict(request_payload)
        # The helper's local_selection is the last acknowledged selection,
        # not the brush/lasso echo currently visible under the cursor. Execute
        # after the selection terminal with no explicit snapshot so the
        # resident service supplies its newly authoritative selection.
        queued_payload.pop("local_selection", None)
        queued_payload.pop("selection", None)
        self.standalone_pending_dotnet_topology_request = queued_payload
        self._set_dotnet_status("Finishing the selection gesture before applying topology...")
        return True

    @staticmethod
    def _separate_selection_diagnostic(selection: object) -> str | None:
        """Require component Faces from exactly one source part for Create Part."""
        face_map = getattr(selection, "face_map", lambda: {})()
        selected_faces: dict[int, tuple[int, ...]] = {}
        for submesh_index, faces in dict(face_map or {}).items():
            normalized = tuple(int(face) for face in (faces or ()))
            if normalized:
                selected_faces[int(submesh_index)] = normalized
        if not selected_faces:
            return "Create Part requires selected faces from exactly one source part."
        if len(selected_faces) != 1:
            return "Create Part requires faces belonging to one source part."
        return None

    def _reject_pending_dotnet_topology_command(self, reason: str) -> None:
        payload = self.standalone_pending_dotnet_topology_request
        self.standalone_pending_dotnet_topology_request = None
        if payload is None:
            return
        command_name = str(payload.get("command", payload.get("action", "subdivide")) or "subdivide")
        self._send_dotnet_command_result(
            command_name,
            ok=False,
            status="cancelled",
            diagnostics=(str(reason or "The selection gesture did not complete."),),
            request_payload=payload,
        )

    def _retry_pending_dotnet_topology_command(self) -> None:
        payload = self.standalone_pending_dotnet_topology_request
        if payload is None or str(self.standalone_native_selection_stroke_id or "").strip():
            return
        dispatcher = self.standalone_live_stroke_dispatcher
        if dispatcher is not None:
            try:
                metrics = dispatcher.metrics()
            except (AttributeError, RuntimeError):
                metrics = {"active": 1}
            if any(int(metrics.get(key, 0) or 0) > 0 for key in ("active", "control_depth", "queue_depth")):
                _tab.QTimer.singleShot(10, self._retry_pending_dotnet_topology_command)
                return
        self.standalone_pending_dotnet_topology_request = None
        self._handle_dotnet_command_request(payload)

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
        _record_interaction_decision(self,
            "mesh_edit_request_rejected_busy",
            command=normalized,
            request_id=int((request_payload or {}).get("request_id", 0) or 0),
        )
        self._send_dotnet_command_result(
            normalized,
            ok=False,
            status="busy",
            diagnostics=("Wait for the active Mesh Editor stroke to finish.",),
            request_payload=request_payload,
        )
        return True
    def _reject_dotnet_request_without_session(
        self,
        command_name: str,
        payload: Mapping[str, object],
    ) -> None:
        """Answer a helper request that arrived without a live edit session.

        Selection and stroke requests block the helper's viewport on an
        authoritative reply. Dropping one leaves the editor showing "awaiting
        authoritative result" for a click that will never be answered, which
        reads as the tool being broken.
        """
        _record_interaction_decision(self,
            "mesh_edit_request_rejected_no_session",
            command=str(command_name or "command"),
            request_id=int(payload.get("request_id", 0) or 0),
        )
        self._send_dotnet_command_result(
            command_name,
            ok=False,
            status="unavailable",
            diagnostics=("No live Mesh Editor session is attached.",),
            request_payload=payload,
        )

    def _handle_dotnet_select_request(self, payload: Mapping[str, object]) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None:
            self._reject_dotnet_request_without_session("select", payload)
            return False
        phase = str(payload.get("phase", "") or "").strip().lower()
        stroke_id = str(payload.get("stroke_id", "") or "").strip()
        try:
            stroke_sequence = int(payload.get("sequence", -1))
        except (TypeError, ValueError, OverflowError):
            stroke_sequence = -1
        if phase not in {"begin", "update", "end", "cancel"} or not stroke_id or stroke_sequence < 0:
            self._send_dotnet_command_result(
                "select",
                ok=False,
                status="error",
                diagnostics=("Selection request requires stroke_id, sequence, and begin/update/end/cancel phase.",),
                request_payload=payload,
            )
            return False
        active_stroke_id = str(self.standalone_native_selection_stroke_id or "").strip()
        if phase == "begin":
            if active_stroke_id and active_stroke_id != stroke_id:
                self._send_dotnet_command_result(
                    "select",
                    ok=False,
                    status="busy",
                    diagnostics=("Finish the active selection gesture first.",),
                    request_payload=payload,
                )
                return True
            self.standalone_native_selection_stroke_id = stroke_id
        elif active_stroke_id != stroke_id:
            self._send_dotnet_command_result(
                "select",
                ok=False,
                status="stale",
                diagnostics=("Selection gesture is stale or belongs to another session.",),
                request_payload=payload,
            )
            return False
        screen_payload = self._dotnet_screen_selection_payload(payload)
        if phase == "update" and not any(key in screen_payload for key in ("screen_brush", "screen_region")):
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
                    "selection_stroke_id": stroke_id,
                    "selection_stroke_phase": phase,
                    "selection_stroke_sequence": stroke_sequence,
                    "record_history": phase == "end",
                },
                label="Select Mesh",
            )
        except Exception as exc:
            self._set_dotnet_status(f"Mesh .NET editor selection failed: {exc}", error=True)
            self._send_dotnet_command_result("select", ok=False, status="error", diagnostics=(str(exc),), request_payload=payload)
            return False
        sequence = self._ensure_standalone_live_stroke_dispatcher().submit(
            controller,
            command,
            phase,
            source="dotnet_selection",
            request_payload=payload,
        )
        if sequence > 0:
            _record_interaction_decision(self,
                "mesh_edit_selection_queued",
                request_id=int(payload.get("request_id", 0) or 0),
                stroke_id=stroke_id,
                stroke_sequence=stroke_sequence,
                phase=phase,
                target_mode=str(payload.get("target_mode", "") or ""),
                operation=operation,
                dispatcher_sequence=sequence,
            )
            return True
        if phase in {"begin", "end", "cancel"}:
            self.standalone_native_selection_stroke_id = ""
        self._send_dotnet_command_result(
            "select",
            ok=False,
            status="cancelled",
            diagnostics=("Mesh Editor selection dispatcher is stopping.",),
            request_payload=payload,
        )
        return False
    def _handle_dotnet_local_selection_request(self, payload: Mapping[str, object]) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None or not isinstance(payload.get("local_selection"), Mapping):
            self._reject_dotnet_request_without_session("select", payload)
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
            self._reject_dotnet_request_without_session("stroke", payload)
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
            _record_interaction_decision(self,
                "mesh_edit_stroke_queued",
                request_id=int(payload.get("request_id", 0) or 0),
                stroke_id=stroke_id,
                phase=phase,
                tool=str(payload.get("tool", "") or ""),
                action=str(command.action or ""),
                dispatcher_sequence=sequence,
            )
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
    def _handle_dotnet_live_stroke_coalesced(self, notice: object) -> None:
        if not isinstance(notice, _tab.MeshLiveStrokeCoalesced):
            return
        controller = self._dotnet_target_controller()
        if controller is None or notice.controller is not controller:
            return
        command_name = (
            "morph_change"
            if notice.source == "dotnet_morph"
            else "select"
            if notice.source == "dotnet_selection"
            else str(notice.command_name or "stroke")
        )
        _record_interaction_decision(self,
            "mesh_edit_updates_coalesced",
            command=command_name,
            source=str(notice.source or ""),
            survivor_sequence=int(notice.survivor_sequence),
            coalesced_request_ids=tuple(
                int(payload.get("request_id", 0) or 0)
                for payload in notice.request_payloads
            ),
        )
        for request_payload in notice.request_payloads:
            self._send_dotnet_command_result(
                command_name,
                ok=True,
                status="coalesced",
                diagnostics=("Merged into the next cumulative stroke update.",),
                request_payload=request_payload,
            )

    def _dotnet_live_stroke_render_lane_busy(self) -> bool:
        queue = getattr(self, "standalone_dotnet_update_queue", None)
        metrics = queue.metrics() if queue is not None else {}
        return bool(
            int(metrics.get("active_revision", 0) or 0) > 0
            or int(metrics.get("pending_depth", 0) or 0) > 0
            or bool(metrics.get("resync_active", False))
        )

    def _coalesce_dotnet_live_stroke_presentation(self, outcome: object) -> None:
        if not isinstance(outcome, _tab.MeshLiveStrokeOutcome):
            return
        for request_payload in tuple(outcome.request_payloads):
            self._send_dotnet_command_result(
                str(outcome.result.action or "stroke"),
                ok=True,
                status="coalesced",
                revision=outcome.result.revision,
                diagnostics=("Superseded by a newer cumulative renderer update.",),
                request_payload=request_payload,
            )

    def _flush_pending_dotnet_live_stroke_presentation(self) -> bool:
        if self._dotnet_live_stroke_render_lane_busy():
            return False
        outcome = getattr(self, "standalone_pending_dotnet_live_stroke_outcome", None)
        if not isinstance(outcome, _tab.MeshLiveStrokeOutcome):
            return False
        self.standalone_pending_dotnet_live_stroke_outcome = None
        self._handle_dotnet_live_stroke_completed(outcome)
        return True

    def _commit_embedded_stroke_presentation(
        self,
        outcome: object,
        *,
        selection_outcome: bool,
        terminal_selection_presentation: bool,
        request_payloads: tuple,
        terminal_selection_stages: dict[str, float],
    ) -> bool:
        """Defer embedded settlement until the renderer acknowledges the batch."""

        _ = (
            outcome,
            selection_outcome,
            terminal_selection_presentation,
            request_payloads,
            terminal_selection_stages,
        )
        return True

    def _handle_dotnet_live_stroke_completed(self, outcome: object) -> None:
        if not isinstance(outcome, _tab.MeshLiveStrokeOutcome) or outcome.source not in {"dotnet", "dotnet_morph", "dotnet_selection"}:
            return
        controller = self._dotnet_target_controller()
        if controller is None or outcome.controller is not controller:
            return
        update = outcome.native_update
        request_payloads = tuple(outcome.request_payloads)
        _record_interaction_decision(self,
            "mesh_edit_dispatch_completed",
            source=str(outcome.source or ""),
            phase=str(outcome.phase or ""),
            dispatcher_sequence=int(outcome.sequence),
            revision=int(getattr(outcome.result, "revision", 0) or 0),
            request_ids=tuple(
                int(payload.get("request_id", 0) or 0)
                for payload in request_payloads
            ),
            vertex_group_count=len(tuple(update.vertex_groups or ())),
            triangle_group_count=len(tuple(update.triangle_groups or ())),
            selection_group_count=len(tuple(update.selection_groups or ())),
            # The apply already measured itself (editor_open/native_apply/cpp/io
            # milliseconds); until now the numbers died with the result object,
            # so a multi-second stroke in a trail could not name its slow stage.
            result_metrics={
                str(key): round(float(value), 3)
                for key, value in dict(outcome.result.metrics or {}).items()
            },
        )
        if outcome.source == "dotnet" and outcome.phase == "update" and self._dotnet_live_stroke_render_lane_busy():
            previous = getattr(self, "standalone_pending_dotnet_live_stroke_outcome", None)
            if previous is not None:
                self._coalesce_dotnet_live_stroke_presentation(previous)
            self.standalone_pending_dotnet_live_stroke_outcome = outcome
            return
        if outcome.source == "dotnet" and outcome.phase in {"end", "cancel"}:
            previous = getattr(self, "standalone_pending_dotnet_live_stroke_outcome", None)
            self.standalone_pending_dotnet_live_stroke_outcome = None
            if previous is not None:
                self._coalesce_dotnet_live_stroke_presentation(previous)
        selection_outcome = outcome.source == "dotnet_selection"
        terminal_selection_presentation = (
            selection_outcome and outcome.phase in {"end", "cancel"}
        )
        defer_selection_presentation = selection_outcome and not terminal_selection_presentation
        presentation_sent = True
        terminal_selection_started = (
            time.perf_counter() if terminal_selection_presentation else None
        )
        terminal_selection_stages: dict[str, float] = {}
        presentation_sent = self._commit_embedded_stroke_presentation(
            outcome,
            selection_outcome=selection_outcome,
            terminal_selection_presentation=terminal_selection_presentation,
            request_payloads=request_payloads,
            terminal_selection_stages=terminal_selection_stages,
        )
        for coalesced_payload in request_payloads[:-1]:
            self._send_dotnet_command_result(
                outcome.result.action,
                ok=True,
                status="coalesced",
                revision=outcome.result.revision,
                diagnostics=("Superseded by a newer cumulative stroke update.",),
                request_payload=coalesced_payload,
            )
        latest_request_payload = request_payloads[-1] if request_payloads else None
        if defer_selection_presentation:
            # The native session still consumes begin and every bounded or
            # coalesced update, while WinForms already paints the complete local
            # brush echo. A full selection_update here serializes and reparses
            # the existing or growing selection on both UI threads, then can
            # replace newer local pixels with an older authoritative snapshot.
            # Publish only end/cancel; nonterminal phases need a lightweight
            # request acknowledgement.
            _record_interaction_decision(self,
                "mesh_edit_selection_presentation_deferred",
                dispatcher_sequence=int(outcome.sequence),
                revision=int(getattr(outcome.result, "revision", 0) or 0),
                request_id=int((latest_request_payload or {}).get("request_id", 0) or 0),
            )
            presentation_sent = self._send_dotnet_command_result(
                outcome.result.action,
                ok=str(outcome.result.status or "").strip().lower() != "error",
                status="coalesced",
                revision=outcome.result.revision,
                diagnostics=(),
                request_payload=latest_request_payload,
            )
        else:
            stage_started = time.perf_counter()
            presentation_sent = self._send_dotnet_native_update(
                update,
                result=outcome.result,
                request_payload=latest_request_payload,
                commit_embedded=bool(
                    self.standalone_dotnet_target_embedded
                    and (
                        terminal_selection_presentation
                        or (not selection_outcome and outcome.phase == "end")
                    )
                ),
                resident_history=bool(
                    self.standalone_dotnet_target_embedded
                    and outcome.source == "dotnet"
                    and not selection_outcome
                    and outcome.phase == "end"
                ),
                refresh_morph_state=outcome.source == "dotnet_morph",
            )
            if terminal_selection_presentation:
                terminal_selection_stages["selection_publish_ms"] = (
                    time.perf_counter() - stage_started
                ) * 1000.0
        self._retire_completed_stroke(
            outcome,
            selection_outcome=selection_outcome,
            terminal_selection_presentation=terminal_selection_presentation,
            terminal_selection_started=terminal_selection_started,
            terminal_selection_stages=terminal_selection_stages,
            presentation_sent=presentation_sent,
            latest_request_payload=latest_request_payload,
        )

    def _retire_completed_stroke(
        self,
        outcome: object,
        *,
        selection_outcome: bool,
        terminal_selection_presentation: bool,
        terminal_selection_started: float | None,
        terminal_selection_stages: dict[str, float],
        presentation_sent: bool,
        latest_request_payload: object,
    ) -> None:
        """Clear the stroke's id and publish what its end leaves behind.

        Only end and cancel reach here. A publish that failed is treated as a
        cancelled gesture rather than a finished one, because the helper is
        about to be retired and a deferred Finish must not run against it.
        """

        update = outcome.native_update
        if outcome.phase in {"end", "cancel"}:
            if outcome.source == "dotnet_morph":
                self.standalone_dotnet_morph_change_id = ""
            elif outcome.source == "dotnet_selection":
                self.standalone_native_selection_stroke_id = ""
            else:
                self.standalone_native_mesh_edit_stroke_id = ""
            if terminal_selection_presentation and terminal_selection_started is not None:
                _record_interaction_decision(
                    self,
                    (
                        "mesh_edit_selection_terminal_completed"
                        if presentation_sent
                        else "mesh_edit_selection_terminal_publish_failed"
                    ),
                    phase=str(outcome.phase or ""),
                    revision=int(getattr(outcome.result, "revision", 0) or 0),
                    request_id=int((latest_request_payload or {}).get("request_id", 0) or 0),
                    elapsed_ms=(time.perf_counter() - terminal_selection_started) * 1000.0,
                    selection_group_count=len(tuple(update.selection_groups or ())),
                    direct_embedded_apply=False,
                    derived_workspace_refresh=False,
                    session_state_selection=False,
                    **terminal_selection_stages,
                )
            if selection_outcome and not presentation_sent:
                # The helper is about to be retired, so a deferred Finish must
                # not start a placement transition against that failed process.
                self.standalone_dotnet_finish_retry_pending = False
            else:
                self._retry_pending_dotnet_finish()
            if selection_outcome and (outcome.phase == "cancel" or not presentation_sent):
                cancel_reason = (
                    "mesh_dotnet_selection_authority_publish_failed"
                    if not presentation_sent
                    else "selection gesture cancelled."
                )
                self._reject_pending_dotnet_topology_command(
                    f"Mesh .NET editor selection failed: {cancel_reason}"
                )
                if not presentation_sent:
                    failure_code = "mesh_dotnet_selection_authority_publish_failed"
                    self._set_dotnet_status(
                        f"Mesh .NET editor command failed: {failure_code}",
                        error=True,
                    )
                    if self.standalone_dotnet_target_embedded:
                        self._request_or_stop_blocked_embedded_dotnet(
                            "mesh_dotnet_selection_authority_publish_failed"
                        )
                    else:
                        self._stop_standalone_dotnet_editor_process(embedded_state="failed")
            else:
                self._retry_pending_dotnet_topology_command()

    def _handle_dotnet_live_stroke_failed(self, failure: object) -> None:
        if not isinstance(failure, _tab.MeshLiveStrokeFailure) or failure.source not in {"dotnet", "dotnet_morph", "dotnet_selection"}:
            return
        controller = self._dotnet_target_controller()
        if controller is None or failure.controller is not controller:
            return
        if failure.phase in {"begin", "end", "cancel"} or failure.source == "dotnet_selection":
            if failure.source == "dotnet_morph":
                self.standalone_dotnet_morph_change_id = ""
            elif failure.source == "dotnet_selection":
                self.standalone_native_selection_stroke_id = ""
            else:
                self.standalone_native_mesh_edit_stroke_id = ""
        if failure.source == "dotnet_selection":
            self._reject_pending_dotnet_topology_command(
                f"Mesh .NET editor selection failed: {failure.message}"
            )
        if failure.cancelled:
            request_payloads = tuple(failure.request_payloads) or (None,)
            for request_payload in request_payloads:
                self._send_dotnet_command_result(
                    (
                        "morph_change"
                        if failure.source == "dotnet_morph"
                        else "select"
                        if failure.source == "dotnet_selection"
                        else "stroke"
                    ),
                    ok=False,
                    status="cancelled",
                    diagnostics=(failure.message,),
                    request_payload=request_payload,
                )
            _record_interaction_decision(self,
                "mesh_edit_dispatch_cancelled",
                source=str(failure.source or ""),
                phase=str(failure.phase or ""),
                dispatcher_sequence=int(failure.sequence),
                request_ids=tuple(
                    int(payload.get("request_id", 0) or 0)
                    for payload in failure.request_payloads
                ),
            )
            return
        _record_interaction_decision(self,
            "mesh_edit_dispatch_failed",
            source=str(failure.source or ""),
            phase=str(failure.phase or ""),
            dispatcher_sequence=int(failure.sequence),
            message=str(failure.message or ""),
            request_ids=tuple(
                int(payload.get("request_id", 0) or 0)
                for payload in failure.request_payloads
            ),
        )
        message = f"Mesh .NET editor stroke failed: {failure.message}"
        self._set_dotnet_status(message, error=True)
        request_payloads = tuple(failure.request_payloads) or (None,)
        for request_payload in request_payloads:
            self._send_dotnet_command_result(
                "morph_change" if failure.source == "dotnet_morph" else "select" if failure.source == "dotnet_selection" else "stroke",
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
        if failure.source != "dotnet_selection":
            self._retry_pending_dotnet_topology_command()

    def _handle_dotnet_command_request(self, payload: Mapping[str, object]) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        command = str(payload.get("command", payload.get("action", "")) or "").strip().lower()
        command = command.replace("-", "_")
        if not command:
            self._send_dotnet_command_result("command", ok=False, status="error", diagnostics=("Missing command.",), request_payload=payload)
            return False
        if command == "configure_free_edit":
            return self._configure_free_edit_output_requested(payload)
        if command == "export_free_edit":
            return self._start_free_edit_output_requested(payload)
        if command.startswith("morph_"):
            return self._handle_dotnet_morph_command_request(controller, command, payload)
        if (
            not self.standalone_dotnet_target_embedded
            and controller is getattr(self, "standalone_controller", None)
        ):
            blocker = self._standalone_action_authoring_blocker(command)
            if blocker:
                self._send_dotnet_command_result(
                    command,
                    ok=False,
                    status="unavailable",
                    diagnostics=(blocker,),
                    request_payload=payload,
                )
                return True
        if self._queue_dotnet_topology_after_selection(command, payload):
            return True
        if self._reject_dotnet_mutation_while_busy(command, payload):
            return True
        layer_result = self._handle_dotnet_layer_command(controller, command, payload)
        if layer_result is not None:
            return layer_result
        local_selection = self._dotnet_local_selection_payload_to_selection(payload)
        selection_supplied = isinstance(payload.get("local_selection"), Mapping) or isinstance(
            payload.get("selection"), Mapping
        )
        action_selection = local_selection if selection_supplied else None
        target_mode = str(payload.get("target_mode", "") or "").strip().lower()
        if (
            not self.standalone_dotnet_target_embedded
            and self._standalone_exact_output_required()
            and command == "delete"
            and bool(local_selection.source_indices)
            and not local_selection.vertices_by_submesh
            and not local_selection.edges_by_submesh
            and not local_selection.faces_by_submesh
        ):
            blocker = self._standalone_action_authoring_blocker(command, deletes_parts=True)
            self._send_dotnet_command_result(
                command,
                ok=False,
                status="unavailable",
                diagnostics=(blocker,),
                request_payload=payload,
            )
            return True
        if command == "separate":
            if target_mode != "face":
                self._send_dotnet_command_result(
                    command,
                    ok=False,
                    status="invalid_selection",
                    diagnostics=("Create Part requires Faces selection mode.",),
                    request_payload=payload,
                )
                return False
            selection_for_separate = local_selection if selection_supplied else controller.session_view().selection
            diagnostic = self._separate_selection_diagnostic(selection_for_separate)
            if diagnostic is not None:
                self._send_dotnet_command_result(
                    command,
                    ok=False,
                    status="invalid_selection",
                    diagnostics=(diagnostic,),
                    request_payload=payload,
                )
                return False
        embedded_result = self._handle_dotnet_embedded_part_command(
            command,
            local_selection,
            target_mode,
            payload,
        )
        if embedded_result is not None:
            return embedded_result
        try:
            direct_result = self._handle_dotnet_direct_command(
                controller,
                command,
                payload,
                local_selection,
                selection_supplied=selection_supplied,
                target_mode=target_mode,
            )
            if direct_result is not None:
                return direct_result
            else:
                action_key = _DOTNET_ACTION_ALIASES.get(command, command)
                action = mesh_editor_actions_by_key().get(action_key)
                params: dict[str, object] = dict(action.params) if action is not None else {}
                if (
                    action_key in {"transform_move", "delete", "duplicate", "subdivide", "refine_smooth", "separate"}
                    and selection_supplied
                    and local_selection.is_empty()
                ):
                    self._send_dotnet_command_result(
                        command,
                        ok=False,
                        status="no_selection",
                        diagnostics=("Select mesh vertices in the viewport or choose a part under PARTS first.",),
                        request_payload=payload,
                    )
                    return False
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
