from __future__ import annotations

import json
from typing import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from cdmw.ui.shell.settings_bridge import read_bool_setting
from cdmw.ui.mesh_editor.actions import mesh_editor_actions_by_key


from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab


from cdmw.ui.mesh_editor.tab_dotnet_lifecycle import MeshEditorDotNetLifecycleMixin


def _record_interaction_decision(target: object, event: str, **payload: object) -> None:
    recorder = getattr(target, "_record_dotnet_interaction_decision", None)
    if callable(recorder):
        recorder(event, **payload)


class MeshEditorDotNetCommandMixin(MeshEditorDotNetLifecycleMixin):
    def _queue_dotnet_topology_after_selection(
        self,
        command_name: str,
        request_payload: Mapping[str, object],
    ) -> bool:
        if command_name not in {"subdivide", "subdivide_selection", "refine", "refine_smooth"}:
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
        self.standalone_pending_dotnet_topology_request = dict(request_payload)
        self._set_dotnet_status("Finishing the selection gesture before applying topology...")
        return True

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
        )
        if self.standalone_dotnet_target_embedded:
            self._apply_embedded_native_update(update)
            if outcome.phase != "update":
                # Only a finished stroke is worth recording; the update phases
                # are provisional and are superseded by the one that lands.
                self._commit_embedded_edit_result(
                    outcome.result,
                    command_name=str(outcome.result.action or "stroke"),
                    request_payload=request_payloads[-1] if request_payloads else None,
                )
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
            elif outcome.source == "dotnet_selection":
                self.standalone_native_selection_stroke_id = ""
            else:
                self.standalone_native_mesh_edit_stroke_id = ""
            self._send_dotnet_session_state()
            self._retry_pending_dotnet_finish()
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
        if failure.cancelled:
            _record_interaction_decision(self,
                "mesh_edit_dispatch_cancelled",
                source=str(failure.source or ""),
                phase=str(failure.phase or ""),
                dispatcher_sequence=int(failure.sequence),
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
        self._retry_pending_dotnet_topology_command()

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
                _record_interaction_decision(self,
                    "mesh_edit_morph_change_queued",
                    request_id=int(payload.get("request_id", 0) or 0),
                    change_id=change_id,
                    definition_id=definition_id,
                    phase=phase,
                    value=self._standalone_native_payload_float(payload.get("value"), 0.0),
                    dispatcher_sequence=sequence,
                )
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
        elif command == "morph_configure_refit":
            params.update({
                "garment_submesh_indices": tuple(local_selection.source_indices),
                "enabled": bool(payload.get("enabled", True)),
                "intensity_percent": self._standalone_native_payload_float(
                    payload.get("intensity_percent"), 100.0
                ),
                "mode": str(payload.get("mode") or "surface").strip().lower(),
                "clearance_percent": self._standalone_native_payload_float(
                    payload.get("clearance_percent"), 0.0
                ),
            })
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
            selection=local_selection if command in {
                "morph_author_definition", "morph_set_driver", "morph_bind", "morph_configure_refit",
            } else None,
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

    def _handle_dotnet_layer_command(
        self,
        controller: _tab.MeshEditorController,
        command: str,
        payload: Mapping[str, object],
    ) -> bool | None:
        if command == "layer_delete":
            layer_id = str(payload.get("layer_id", "") or "").strip()
            return self._start_dotnet_action_worker(
                controller,
                _tab.MeshEditCommand(
                    "layer_delete",
                    params={"layer_id": layer_id},
                    mode="edit",
                    label="Delete Layer",
                ),
                command_name=command,
                request_payload=payload,
            )
        if command not in {"layer_activate", "layer_rename", "layer_visibility", "layer_move"}:
            return None
        layer_id = str(payload.get("layer_id", "") or "").strip()
        try:
            if command == "layer_activate":
                controller.activate_geometry_layer(layer_id)
            elif command == "layer_rename":
                controller.rename_geometry_layer(layer_id, str(payload.get("name", "") or ""))
            elif command == "layer_visibility":
                controller.set_geometry_layer_visibility(layer_id, bool(payload.get("visible", False)))
            else:
                controller.move_geometry_layer(
                    layer_id,
                    self._standalone_native_payload_int(payload.get("direction"), 0),
                )
            revision = controller.session_view().revision
        except Exception as exc:
            self._set_dotnet_status(f"Mesh .NET editor layer command failed: {exc}", error=True)
            self._send_dotnet_command_result(
                command,
                ok=False,
                status="error",
                diagnostics=(str(exc),),
                request_payload=payload,
            )
            self._send_dotnet_session_state()
            return False
        self._send_dotnet_command_result(
            command,
            ok=True,
            status="applied",
            revision=revision,
            request_payload=payload,
        )
        self._send_dotnet_session_state()
        return True

    def _handle_dotnet_direct_command(
        self,
        controller: _tab.MeshEditorController,
        command: str,
        payload: Mapping[str, object],
        local_selection: _tab.MeshEditSelection,
        *,
        selection_supplied: bool,
        target_mode: str,
    ) -> bool | None:
        if command == "copy":
            worker_command = _tab.MeshEditCommand(
                "copy",
                selection=local_selection if selection_supplied else None,
                params={"target_mode": target_mode},
                mode="edit",
                label="Copy Selection",
            )
        elif command == "paste":
            worker_command = _tab.MeshEditCommand("paste", mode="edit", label="Paste Selection")
        elif command == "clear_selection":
            worker_command = _tab.MeshEditCommand(
                "select",
                selection=_tab.MeshEditSelection(),
                params={"operation": "replace"},
                label="Clear Selection",
            )
        elif command == "select_all":
            worker_command = _tab.MeshEditCommand(
                "select",
                selection=_tab.MeshEditSelection(),
                params={"operation": "all", "target_mode": "vertex"},
                label="Select All",
            )
        elif command in {"grow", "shrink", "invert"}:
            normalized_target = target_mode if target_mode in {"vertex", "edge", "face"} else "vertex"
            worker_command = _tab.MeshEditCommand(
                "select",
                selection=local_selection,
                params={"operation": command, "target_mode": normalized_target},
                label=command.replace("_", " ").title(),
            )
        else:
            return None
        return self._start_dotnet_action_worker(
            controller,
            worker_command,
            command_name=command,
            request_payload=payload,
        )

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
                action = mesh_editor_actions_by_key().get(action_key)
                params: dict[str, object] = dict(action.params) if action is not None else {}
                if (
                    action_key in {"transform_move", "delete", "duplicate", "subdivide", "refine_smooth"}
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
