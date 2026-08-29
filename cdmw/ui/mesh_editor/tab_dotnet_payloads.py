from __future__ import annotations

from types import SimpleNamespace
from typing import Mapping, Sequence

from cdmw.domain.mesh.resident_mutation import ResidentMutationBatch
from cdmw.ui.mesh_editor.actions import (
    MESH_EDITOR_SESSION_ACTIONS,
    mesh_editor_action_authoring_blocker,
    visible_actions_for_session,
)
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_dotnet_material_parameters import (
    MeshEditorDotNetMaterialParameterMixin,
)


class MeshEditorDotNetPayloadMixin(MeshEditorDotNetMaterialParameterMixin):
    def _flush_dotnet_protocol_messages(self, timeout_ms: int = 500) -> bool:
        del timeout_ms
        return True
    def _send_dotnet_session_state(
        self,
        *,
        include_selection: bool = True,
        session_view: _tab.MeshEditSessionView | None = None,
    ) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        view = session_view
        if view is None:
            try:
                view = controller.session_view()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return False
        visible_actions = visible_actions_for_session(
            view.mesh_format,
            view.lod_index,
            view.output_policy,
            free_edit_destination_ready=view.output_destination_ready,
        )
        actions = sorted(action.key for action in visible_actions)
        unavailable_reasons = {
            action.key: blocker
            for action in MESH_EDITOR_SESSION_ACTIONS
            if (
                blocker := mesh_editor_action_authoring_blocker(
                    action.key,
                    mesh_format=view.mesh_format,
                    lod_index=view.lod_index,
                    output_policy=view.output_policy,
                    free_edit_destination=view.output_destination,
                    free_edit_destination_ready=view.output_destination_ready,
                )
            )
        }
        payload = {
            "event": "session_state",
            "session_id": view.session_id,
            "process_generation": self.standalone_dotnet_process_generation,
            "mode": view.mode,
            "revision": view.revision,
            "edit_revision": view.resident_revision,
            # Two keys because they are two things. `selection_mode` is the drag
            # gesture the helper whitelists as brush/lasso/rectangle; an element
            # kind arriving here was silently ignored by it and reset the
            # reader's shape on the way back.
            "selection_mode": str(getattr(controller, "active_selection_mode", "") or self.current_selection_mode or "brush"),
            "element_type": str(getattr(controller, "active_element_type", "") or self.current_element_type or "vertex"),
            "submesh_count": view.submesh_count,
            "vertex_count": view.vertex_count,
            "face_count": view.face_count,
            "undo_count": view.undo_count,
            "redo_count": view.redo_count,
            "history_cursor": view.history_cursor,
            "history_entries": [
                {
                    "action": entry.action,
                    "label": entry.label,
                    "state": entry.state,
                }
                for entry in view.history_entries
            ],
            "actions": actions,
            "selection_depth_mode": "visible",
            "mesh_format": view.mesh_format,
            "lod_index": view.lod_index,
            "output_policy": view.output_policy,
            "output_destination": view.output_destination,
            "output_destination_ready": view.output_destination_ready,
            "authoring_enabled": view.authoring_enabled,
            "exact_write_status": view.exact_write_status,
            "output_policy_reason": view.output_policy_reason,
            "unavailable_action_reasons": unavailable_reasons,
            "exact_output_required": view.output_policy == "exact_game_asset",
        }
        if include_selection:
            payload["selection"] = self._dotnet_selection_payload(view.selection)
            try:
                payload["geometry_layers"] = controller.geometry_layer_state()
            except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
                payload["geometry_layers"] = {
                    "revision": 0,
                    "active_layer_id": "base",
                    "clipboard_ready": False,
                    "layers": (),
                }
        return self._send_dotnet_protocol_message(payload)

    def _send_dotnet_cached_morph_state(
        self,
        *,
        request_payload: Mapping[str, object] | None = None,
        failure: str = "",
    ) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        try:
            state = controller.cached_morph_state()
            view = controller.session_view()
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            return False
        if state is None:
            return False
        payload: dict[str, object] = {
            "event": "morph_state_update",
            "session_id": state.session_id or view.session_id,
            "process_generation": self.standalone_dotnet_process_generation,
            "revision": view.revision,
            "edit_revision": view.resident_revision,
            "native_edit_revision": state.edit_revision,
            "state_revision": state.state_revision,
            "change_id": state.change_id,
            "profile_id": state.profile_id,
            "preset_id": state.preset_id,
            "topology_fingerprint": state.topology_fingerprint,
            "available_profiles": [
                {"profile_id": profile_id, "name": name}
                for profile_id, name in state.available_profiles
            ],
            "available_presets": [
                {"preset_id": preset_id, "name": name}
                for preset_id, name in state.available_presets
            ],
            "definitions": [
                {
                    "definition_id": definition.definition_id,
                    "label": definition.label,
                    "category": definition.category,
                    "min_percent": definition.min_percent,
                    "max_percent": definition.max_percent,
                    "default_percent": definition.default_percent,
                    "value": dict(state.values).get(definition.definition_id, definition.default_percent),
                    "rule": definition.rule.kind,
                    "axis": definition.rule.axis,
                    "amount": definition.rule.amount,
                    "falloff": definition.rule.falloff,
                    "feather": definition.rule.feather,
                    "parameters": {key: value for key, value in definition.rule.parameters},
                    "mirror_mode": definition.mirror_mode,
                    "pivot": list(definition.pivot),
                    "local_basis": [list(axis) for axis in definition.local_basis],
                }
                for definition in state.definitions
            ],
            "values": {key: value for key, value in state.values},
            "driver_submesh_indices": list(state.driver_submesh_indices),
            "refit": {
                "driver_submesh_indices": list(state.refit.driver_submesh_indices),
                "garment_submesh_indices": list(state.refit.garment_submesh_indices),
                "bound_vertex_count": state.refit.bound_vertex_count,
                "maximum_distance": state.refit.maximum_distance,
                "p95_distance": state.refit.p95_distance,
                "warning_distance": state.refit.warning_distance,
                "distance_warning": state.refit.distance_warning,
                "driver_triangle_count": state.refit.driver_triangle_count,
                "candidate_triangle_tests": state.refit.candidate_triangle_tests,
                "garment_settings": [
                    {
                        "submesh_index": settings.submesh_index,
                        "enabled": settings.enabled,
                        "intensity_percent": settings.intensity_percent,
                        "mode": settings.mode,
                        "clearance_percent": settings.clearance_percent,
                    }
                    for settings in state.refit.garment_settings
                ],
            },
            "unbaked": state.unbaked,
            "topology_blocked": state.topology_blocked,
            "busy": state.busy,
            "failure": str(failure or state.failure),
            "diagnostics": list(state.diagnostics),
        }
        if request_payload is not None:
            for key in ("request_id", "base_revision", "protocol_version"):
                if key in request_payload:
                    payload[key] = request_payload[key]
        self.standalone_dotnet_morph_sent_state_revision = int(state.state_revision)
        self.standalone_dotnet_morph_sent_change_id = str(state.change_id or "")
        self.standalone_dotnet_morph_sent_request_id = self._standalone_native_payload_int(payload.get("request_id"), 0)
        return self._send_dotnet_protocol_message(payload)
    @staticmethod
    def _dotnet_selection_payload(selection: _tab.MeshEditSelection) -> dict[str, object]:
        return {
            "vertices_by_submesh": selection.vertices_by_submesh,
            "edges_by_submesh": selection.edges_by_submesh,
            "faces_by_submesh": selection.faces_by_submesh,
            "source_indices": selection.source_indices,
            "empty": selection.is_empty(),
        }
    @classmethod
    def _dotnet_local_selection_payload_to_selection(cls, payload: Mapping[str, object]) -> _tab.MeshEditSelection:
        raw_selection = payload.get("local_selection")
        if not isinstance(raw_selection, Mapping):
            raw_selection = payload.get("selection")
        if not isinstance(raw_selection, Mapping):
            return _tab.MeshEditSelection()
        vertices = cls._dotnet_index_map(raw_selection.get("vertices_by_submesh"))
        faces = cls._dotnet_index_map(raw_selection.get("faces_by_submesh"))
        edges = cls._dotnet_edge_map(raw_selection.get("edges_by_submesh"))
        if not edges:
            edges = cls._dotnet_edge_descriptors(raw_selection.get("edge_descriptors"))
        sources = cls._dotnet_int_values(
            raw_selection.get("source_indices", raw_selection.get("sources", ()))
        )
        return _tab.MeshEditSelection.from_maps(
            vertices_by_submesh=vertices,
            edges_by_submesh=edges,
            faces_by_submesh=faces,
            source_indices=sources,
        )
    @classmethod
    def _dotnet_index_map(cls, value: object) -> dict[int, tuple[int, ...]]:
        result: dict[int, tuple[int, ...]] = {}
        for submesh, values in cls._dotnet_map_items(value):
            indices = tuple(sorted({index for index in cls._dotnet_int_values(values) if index >= 0}))
            if indices:
                result[submesh] = indices
        return result
    @classmethod
    def _dotnet_edge_map(cls, value: object) -> dict[int, tuple[tuple[int, int], ...]]:
        result: dict[int, tuple[tuple[int, int], ...]] = {}
        for submesh, raw_edges in cls._dotnet_map_items(value):
            pairs = cls._dotnet_edge_pairs(raw_edges)
            if pairs:
                result[submesh] = pairs
        return result
    @classmethod
    def _dotnet_edge_descriptors(cls, value: object) -> dict[int, tuple[tuple[int, int], ...]]:
        if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
            return {}
        try:
            items = tuple(value or ())  # type: ignore[arg-type]
        except TypeError:
            return {}
        result: dict[int, set[tuple[int, int]]] = {}
        for item in items:
            if not isinstance(item, Mapping):
                continue
            submesh = cls._standalone_native_payload_int(
                item.get("source_submesh_index", item.get("submesh_index", -1)),
                -1,
            )
            a = cls._standalone_native_payload_int(item.get("vertex_a"), -1)
            b = cls._standalone_native_payload_int(item.get("vertex_b"), -1)
            if submesh < 0 or a < 0 or b < 0 or a == b:
                continue
            pair = (a, b) if a <= b else (b, a)
            result.setdefault(submesh, set()).add(pair)
        return {submesh: tuple(sorted(pairs)) for submesh, pairs in sorted(result.items())}
    @classmethod
    def _dotnet_map_items(cls, value: object) -> tuple[tuple[int, object], ...]:
        pairs: list[tuple[int, object]] = []
        if isinstance(value, Mapping):
            iterable = value.items()
        elif not isinstance(value, (str, bytes)):
            try:
                iterable = tuple(value or ())  # type: ignore[arg-type]
            except TypeError:
                iterable = ()
        else:
            iterable = ()
        for item in iterable:
            if isinstance(value, Mapping):
                raw_key, raw_values = item
            else:
                if isinstance(item, Mapping):
                    raw_key = item.get("index", item.get("submesh", item.get("submesh_index", -1)))
                    raw_values = item.get("indices", item.get("values", item.get("edges", ())))
                else:
                    try:
                        item_values = tuple(item or ())  # type: ignore[arg-type]
                    except TypeError:
                        continue
                    if len(item_values) < 2:
                        continue
                    raw_key, raw_values = item_values[0], item_values[1]
            key = cls._standalone_native_payload_int(raw_key, -1)
            if key >= 0:
                pairs.append((key, raw_values))
        return tuple(pairs)
    @classmethod
    def _dotnet_int_values(cls, value: object) -> tuple[int, ...]:
        if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
            return ()
        try:
            raw_values = tuple(value or ())  # type: ignore[arg-type]
        except TypeError:
            return ()
        return tuple(cls._standalone_native_payload_int(raw, -1) for raw in raw_values)
    @classmethod
    def _dotnet_edge_pairs(cls, value: object) -> tuple[tuple[int, int], ...]:
        if isinstance(value, Mapping) or isinstance(value, (str, bytes)):
            return ()
        try:
            raw_edges = tuple(value or ())  # type: ignore[arg-type]
        except TypeError:
            return ()
        edges: set[tuple[int, int]] = set()
        for raw_edge in raw_edges:
            if isinstance(raw_edge, Mapping):
                a = cls._standalone_native_payload_int(raw_edge.get("vertex_a"), -1)
                b = cls._standalone_native_payload_int(raw_edge.get("vertex_b"), -1)
            else:
                try:
                    pair_values = tuple(raw_edge or ())[:2]  # type: ignore[arg-type]
                except TypeError:
                    continue
                if len(pair_values) < 2:
                    continue
                a = cls._standalone_native_payload_int(pair_values[0], -1)
                b = cls._standalone_native_payload_int(pair_values[1], -1)
            if a >= 0 and b >= 0 and a != b:
                edges.add((a, b) if a <= b else (b, a))
        return tuple(sorted(edges))
    def _send_dotnet_command_result(
        self,
        command: str,
        *,
        ok: bool,
        status: str,
        revision: int | None = None,
        diagnostics: Sequence[object] = (),
        request_payload: Mapping[str, object] | None = None,
        authoritative_geometry_pending: bool = False,
    ) -> bool:
        payload: dict[str, object] = {
            "event": "command_result",
            "command": command,
            "ok": bool(ok),
            "status": status,
            "diagnostics": [str(item) for item in diagnostics],
        }
        if authoritative_geometry_pending:
            payload["authoritative_geometry_pending"] = True
        if revision is not None:
            protocol_revision = max(0, int(revision))
            if request_payload is not None:
                try:
                    protocol_revision = max(
                        protocol_revision,
                        int(request_payload.get("base_revision", 0) or 0),
                    )
                except (TypeError, ValueError, OverflowError):
                    pass
            payload["revision"] = protocol_revision
            payload["edit_revision"] = protocol_revision
        if request_payload is not None:
            for key in (
                "session_id",
                "request_id",
                "base_revision",
                "process_generation",
                "protocol_version",
            ):
                if key in request_payload:
                    payload[key] = request_payload[key]
        if not ok:
            self._record_mesh_dotnet_event(
                "mesh_dotnet_command_result_failed",
                command=str(command or "command"),
                status=str(status or "error"),
                diagnostics=tuple(str(item) for item in diagnostics),
            )
        return self._send_dotnet_protocol_message(payload)
    def _resident_mutation_batch_for_update(
        self,
        update: _tab.MeshEditorNativeUpdate,
        *,
        result: _tab.MeshEditResult | None = None,
        request_payload: Mapping[str, object] | None = None,
    ) -> ResidentMutationBatch | None:
        controller = self._dotnet_target_controller()
        if controller is None:
            return None
        view = update.session_view
        if view is None:
            try:
                view = controller.session_view()
            except (AttributeError, RuntimeError, TypeError, ValueError):
                return None
        session_id = str(view.session_id or "").strip()
        process_generation = max(0, int(self.standalone_dotnet_process_generation or 0))
        target_revision = max(0, int(view.resident_revision or 0))
        if not session_id or process_generation <= 0 or target_revision <= 0:
            return None
        queue = self.standalone_dotnet_update_queue
        preferred_request_id = 0
        if request_payload is not None:
            try:
                preferred_request_id = max(0, int(request_payload.get("request_id", 0) or 0))
            except (TypeError, ValueError, OverflowError):
                preferred_request_id = 0
        request_id = queue.reserve_request_id(preferred_request_id)
        base_revision = queue.next_base_revision
        if target_revision <= base_revision:
            return None
        topology_update = None
        if update.triangle_groups or update.triangle_source_submesh_indices or update.replace_all_triangles:
            topology_update = {
                "triangle_groups": [dict(group) for group in update.triangle_groups],
                "triangle_source_submesh_indices": list(update.triangle_source_submesh_indices),
                "replace_all_triangles": bool(update.replace_all_triangles),
                "final_submesh_count": update.final_submesh_count,
            }
        material_updates, material_affected = self._normalized_dotnet_material_parameter_groups(
            update.material_override_groups
        )
        selection_update = (
            self._dotnet_selection_payload(view.selection)
            if update.refresh_selection
            else None
        )
        affected: set[int] = set(material_affected)
        if result is not None:
            affected.update(int(index) for index in tuple(result.affected_submesh_indices or ()) if int(index) >= 0)
        for group in update.vertex_groups:
            try:
                affected.add(int(group.get("source_submesh_index", -1)))
            except (TypeError, ValueError, OverflowError):
                continue
        affected.update(int(index) for index in update.triangle_source_submesh_indices if int(index) >= 0)
        affected.discard(-1)
        action = str(getattr(result, "action", "") or "").strip()
        if not action and request_payload is not None:
            action = str(
                request_payload.get("command", request_payload.get("event", "")) or ""
            ).strip()
        return ResidentMutationBatch(
            session_id=session_id,
            process_generation=process_generation,
            request_id=request_id,
            base_revision=base_revision,
            target_revision=target_revision,
            action=action or "native_update",
            vertex_updates=tuple(dict(group) for group in update.vertex_groups),
            topology_update=topology_update,
            material_updates=tuple(material_updates),
            selection_update=selection_update,
            history_state={
                "undo_count": view.undo_count,
                "redo_count": view.redo_count,
                "history_cursor": view.history_cursor,
                "history_entries": [
                    {
                        "action": entry.action,
                        "label": entry.label,
                        "state": entry.state,
                    }
                    for entry in view.history_entries
                ],
            },
            final_submesh_count=update.final_submesh_count,
            affected_submesh_indices=tuple(affected),
        )

    def _legacy_dotnet_native_update_packets(
        self,
        update: _tab.MeshEditorNativeUpdate,
        batch: ResidentMutationBatch,
    ) -> list[dict[str, object]]:
        base: dict[str, object] = {}
        base["session_id"] = batch.session_id
        base["edit_revision"] = batch.target_revision
        base["revision"] = batch.target_revision
        base["request_id"] = batch.request_id
        base["base_revision"] = batch.base_revision
        base["process_generation"] = batch.process_generation
        base["protocol_version"] = 2
        edit_packets: list[dict[str, object]] = []
        if update.vertex_groups:
            edit_packets.append({
                **base,
                "event": "preview_vertex_update",
                "vertex_groups": update.vertex_groups,
            })
        if update.triangle_groups or update.triangle_source_submesh_indices or update.replace_all_triangles:
            edit_packets.append({
                **base,
                "event": "preview_triangle_update",
                "triangle_groups": update.triangle_groups,
                "triangle_source_submesh_indices": update.triangle_source_submesh_indices,
                "replace_all_triangles": update.replace_all_triangles,
                "final_submesh_count": update.final_submesh_count,
                "material_override_groups": update.material_override_groups,
            })
        if update.refresh_selection:
            edit_packets.append({
                **base,
                "event": "selection_update",
                "selection": dict(batch.selection_update or {}),
                "selection_groups": update.selection_groups,
            })
        return edit_packets

    def _send_dotnet_native_update(
        self,
        update: _tab.MeshEditorNativeUpdate,
        *,
        result: _tab.MeshEditResult | None = None,
        request_payload: Mapping[str, object] | None = None,
        commit_embedded: bool = False,
        resident_history: bool = False,
        refresh_morph_state: bool = False,
    ) -> bool:
        batch = self._resident_mutation_batch_for_update(
            update,
            result=result,
            request_payload=request_payload,
        )
        has_payload = bool(
            update.vertex_groups
            or update.triangle_groups
            or update.triangle_source_submesh_indices
            or update.material_override_groups
            or update.refresh_selection
            or update.replace_all_triangles
        )
        if batch is None:
            if has_payload:
                return False
            if result is not None:
                return self._send_dotnet_command_result(
                    result.action,
                    ok=str(result.status or "").strip().lower() != "error",
                    status=str(result.status or ""),
                    revision=result.revision,
                    diagnostics=result.diagnostics,
                    request_payload=request_payload,
                )
            return True
        queue = self.standalone_dotnet_update_queue
        edit_packets: list[dict[str, object]]
        if queue.mutation_batch_capable:
            edit_packets = [batch.as_protocol_payload()]
            queued = queue.enqueue_mutation_batch(batch)
        else:
            edit_packets = self._legacy_dotnet_native_update_packets(update, batch)
            safe_v2_single_surface = (
                len(edit_packets) == 1
                and edit_packets[0].get("event")
                in {
                    "preview_vertex_update",
                    "preview_triangle_update",
                    "selection_update",
                }
                and not update.material_override_groups
                and not refresh_morph_state
            )
            if not safe_v2_single_surface:
                queue.fail_degraded_mutation(batch.as_protocol_payload())
                queued = False
            else:
                queued = queue.enqueue(batch.target_revision, edit_packets)
        if queued:
            self.standalone_dotnet_update_ack_start_timer.start(0)
            if result is not None and queue.mutation_batch_capable:
                self.standalone_dotnet_pending_mutation_commits[batch.request_id] = {
                    "result": result,
                    "update": update,
                    "command_name": str(result.action or "command"),
                    "request_payload": dict(request_payload or {}),
                    "commit_embedded": bool(commit_embedded),
                    "resident_history": bool(resident_history),
                    "refresh_morph_state": bool(refresh_morph_state),
                    "target_revision": batch.target_revision,
                }
            self._sync_resident_mutation_recovery_state()
        elif edit_packets:
            self._sync_resident_mutation_recovery_state()
            if result is None:
                return False
            failure_code = "mesh_dotnet_native_update_enqueue_failed"
            diagnostics = (
                f"Mesh .NET editor command failed: {failure_code}",
            )
            self._record_mesh_dotnet_event(
                "mesh_dotnet_native_update_enqueue_failed",
                command=str(result.action or "command"),
                request_id=batch.request_id,
                revision=batch.target_revision,
                packet_events=tuple(
                    str(packet.get("event", "") or "") for packet in edit_packets
                ),
                queue_metrics=self.standalone_dotnet_update_queue.metrics(),
            )
            self._send_dotnet_command_result(
                result.action,
                ok=False,
                status="error",
                revision=batch.target_revision,
                diagnostics=diagnostics,
                request_payload=request_payload,
            )
            return False
        if result is not None:
            request_event = str(
                request_payload.get("event", "") if request_payload is not None else ""
            ).strip().lower()
            return self._send_dotnet_command_result(
                result.action,
                ok=str(result.status or "").strip().lower() != "error",
                status=str(result.status or ""),
                revision=batch.target_revision,
                diagnostics=result.diagnostics,
                request_payload=request_payload,
                authoritative_geometry_pending=(
                    request_event
                    in {"stroke_begin", "stroke_update", "stroke_end", "stroke_cancel"}
                    and bool(update.vertex_groups)
                ),
            )
        return queued
    def _dotnet_screen_selection_payload(self, payload: Mapping[str, object]) -> dict[str, object]:
        screen_payload: dict[str, object] = {}
        raw_screen_brush = payload.get("screen_brush")
        raw_screen_region = payload.get("screen_region")
        if isinstance(raw_screen_brush, Mapping):
            screen_payload["screen_brush"] = self._native_screen_payload(raw_screen_brush)
        if isinstance(raw_screen_region, Mapping):
            screen_payload["screen_region"] = self._native_screen_payload(raw_screen_region)
        if "falloff" in payload:
            screen_payload["falloff"] = str(payload.get("falloff") or "smooth")
        if "paint_sample" in payload:
            screen_payload["paint_sample"] = bool(payload.get("paint_sample"))
        if "paint_final" in payload:
            screen_payload["paint_final"] = bool(payload.get("paint_final"))
        # Edit Mesh screen gestures select mesh elements. Whole-part selection
        # belongs exclusively to the PARTS list and must never be inferred from
        # a viewport hit. Keep the legacy edge/face targets for protocol
        # compatibility; unknown or stale part/source targets fall back to the
        # user-facing vertex target.
        target_mode = str(payload.get("target_mode", "vertex") or "vertex").strip().lower()
        screen_payload["target_mode"] = (
            target_mode if target_mode in {"vertex", "edge", "face"} else "vertex"
        )
        depth_mode = str(payload.get("selection_depth_mode", "visible") or "visible").strip().lower()
        screen_payload["selection_depth_mode"] = "xray" if depth_mode == "xray" else "visible"
        return screen_payload
    def _commit_embedded_edit_result(
        self,
        result: _tab.MeshEditResult,
        *,
        command_name: str = "",
        request_payload: object = None,
        authoritative_selection: _tab.MeshEditSelection | None = None,
        resident_history: bool = False,
    ) -> bool:
        """Let the builder record an edit the embedded editor raised itself.

        Applying the native update only repaints the preview. Without this the
        builder's own mesh, totals, part rows and revision keep describing the
        mesh as it was before the edit, and a duplicated part never becomes a
        routable source.
        """
        builder = self.active_builder()
        commit = getattr(builder, "_mesh_editor_commit_dotnet_edit_result", None) if builder is not None else None
        if not callable(commit):
            return False
        selection = authoritative_selection
        if selection is None and isinstance(request_payload, Mapping):
            try:
                selection = self._dotnet_local_selection_payload_to_selection(request_payload)
            except (AttributeError, TypeError, ValueError):
                selection = None
        action = str(command_name or getattr(result, "action", "") or "")
        try:
            commit_kwargs: dict[str, object] = {
                "action_key": action,
                "action_text": action or "edit",
                "selection": selection,
            }
            if resident_history:
                commit_kwargs["resident_history"] = True
            return bool(
                commit(result, **commit_kwargs)
            )
        except Exception as exc:
            self._record_runtime_event("mesh_editor_embedded_commit_failed", error=str(exc))
            return False

    def _apply_dotnet_result_update(
        self,
        controller: _tab.MeshEditorController,
        result: _tab.MeshEditResult,
        *,
        command_name: str = "",
        request_payload: Mapping[str, object] | None = None,
    ) -> bool:
        try:
            update = controller.native_update_for_result(result)
        except Exception as exc:
            self._set_dotnet_status(f"Mesh .NET editor command failed: {exc}", error=True)
            self._send_dotnet_command_result(
                command_name or result.action,
                ok=False,
                status="error",
                diagnostics=(str(exc),),
                request_payload=request_payload,
            )
            return False
        selection_result = str(result.action or "").strip().lower() in {
            "select",
            "clear_selection",
        }
        has_update_payload = bool(
            update.vertex_groups
            or update.triangle_groups
            or update.triangle_source_submesh_indices
            or update.selection_groups
            or update.refresh_selection
            or update.material_override_groups
            or update.replace_all_triangles
        )
        if self.standalone_dotnet_target_embedded and not has_update_payload:
            self._commit_embedded_edit_result(
                result,
                command_name=command_name,
                request_payload=request_payload,
                authoritative_selection=(
                    update.session_view.selection
                    if selection_result and update.session_view is not None
                    else None
                ),
            )
            self._refresh_embedded_workspace_from_builder(
                include_derived=not selection_result,
                session_view=update.session_view if selection_result else None,
            )
        presentation_sent = self._send_dotnet_native_update(
            update,
            result=result,
            request_payload=request_payload,
            commit_embedded=bool(self.standalone_dotnet_target_embedded and has_update_payload),
            refresh_morph_state=(
                (command_name or result.action).strip().lower().startswith("morph_")
                or (command_name or result.action).strip().lower() in {"undo", "redo"}
                or result.topology_changed
            ),
        )
        if not presentation_sent:
            failure_code = "mesh_dotnet_native_update_publish_failed"
            self._set_dotnet_status(
                f"Mesh .NET editor command failed: {failure_code}",
                error=True,
            )
            if self.standalone_dotnet_target_embedded:
                self._request_or_stop_blocked_embedded_dotnet(
                    "mesh_dotnet_native_update_publish_failed"
                )
            else:
                self._stop_standalone_dotnet_editor_process(embedded_state="failed")
            return False
        normalized_command = (command_name or result.action).strip().lower()
        refresh_morph_state = (
            normalized_command.startswith("morph_")
            or normalized_command in {"undo", "redo"}
            or result.topology_changed
        )
        if not has_update_payload:
            self._send_dotnet_session_state(
                include_selection=not selection_result,
                session_view=update.session_view if selection_result else None,
            )
        if refresh_morph_state and not has_update_payload:
            self._send_dotnet_cached_morph_state(request_payload=request_payload)
        return str(result.status or "").strip().lower() != "error"
