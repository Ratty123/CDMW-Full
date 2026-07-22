from __future__ import annotations

from types import SimpleNamespace
from typing import Mapping, Sequence

from PySide6.QtCore import QTimer

from cdmw.ui.mesh_editor.actions import mesh_editor_actions_by_key
from cdmw.ui.mesh_editor.tab_compat import facade_globals as _tab
from cdmw.ui.mesh_editor.tab_dotnet_material_parameters import (
    MeshEditorDotNetMaterialParameterMixin,
)


class MeshEditorDotNetPayloadMixin(MeshEditorDotNetMaterialParameterMixin):
    def _flush_dotnet_protocol_messages(self, timeout_ms: int = 500) -> bool:
        del timeout_ms
        return True
    def _send_dotnet_session_state(self) -> bool:
        controller = self._dotnet_target_controller()
        if controller is None:
            return False
        try:
            view = controller.session_view()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        actions = sorted(mesh_editor_actions_by_key().keys())
        selection = view.selection
        payload = {
            "event": "session_state",
            "session_id": view.session_id,
            "process_generation": self.standalone_dotnet_process_generation,
            "mode": view.mode,
            "revision": view.revision,
            "selection_mode": str(getattr(controller, "active_selection_mode", "") or self.current_selection_mode or "vertex"),
            "selection": self._dotnet_selection_payload(selection),
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
            "edit_revision": view.revision,
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
    ) -> bool:
        payload: dict[str, object] = {
            "event": "command_result",
            "command": command,
            "ok": bool(ok),
            "status": status,
            "diagnostics": [str(item) for item in diagnostics],
        }
        if revision is not None:
            payload["revision"] = int(revision)
            payload["edit_revision"] = int(revision)
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
    def _send_dotnet_native_update(
        self,
        update: _tab.MeshEditorNativeUpdate,
        *,
        result: _tab.MeshEditResult | None = None,
        request_payload: Mapping[str, object] | None = None,
    ) -> None:
        controller = self._dotnet_target_controller()
        session_id = ""
        revision = None
        selection: _tab.MeshEditSelection | None = None
        if controller is not None:
            try:
                view = controller.session_view()
                session_id = view.session_id
                revision = view.revision
                selection = view.selection
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        base: dict[str, object] = {}
        if session_id:
            base["session_id"] = session_id
        if revision is not None:
            base["edit_revision"] = int(revision)
            base["revision"] = int(revision)
        if request_payload is not None:
            for key in ("request_id", "base_revision", "process_generation", "protocol_version"):
                if key in request_payload:
                    base[key] = request_payload[key]
        if update.material_override_groups:
            self.apply_resident_material_parameters(update.material_override_groups)
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
                "selection": self._dotnet_selection_payload(selection or _tab.MeshEditSelection()),
                "selection_groups": update.selection_groups,
            })
        self.standalone_dotnet_update_queue.enqueue(int(revision or 0), edit_packets)
        QTimer.singleShot(0, self._sync_dotnet_update_ack_timer)
        if result is not None:
            self._send_dotnet_command_result(
                result.action,
                ok=str(result.status or "").strip().lower() != "error",
                status=str(result.status or ""),
                revision=result.revision,
                diagnostics=result.diagnostics,
                request_payload=request_payload,
            )
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
        if "target_mode" in payload:
            screen_payload["target_mode"] = str(payload.get("target_mode") or "vertex")
        depth_mode = str(payload.get("selection_depth_mode", "visible") or "visible").strip().lower()
        screen_payload["selection_depth_mode"] = "xray" if depth_mode == "xray" else "visible"
        return screen_payload
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
        if self.standalone_dotnet_target_embedded:
            self._apply_embedded_native_update(update)
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
            QTimer.singleShot(0, self._sync_state)
        self._send_dotnet_native_update(
            update,
            result=result,
            request_payload=request_payload,
        )
        self._send_dotnet_session_state()
        normalized_command = (command_name or result.action).strip().lower()
        if normalized_command.startswith("morph_") or normalized_command in {"undo", "redo"} or result.topology_changed:
            self._send_dotnet_cached_morph_state(request_payload=request_payload)
        return str(result.status or "").strip().lower() != "error"
