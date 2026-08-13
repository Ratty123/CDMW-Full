"""Result assembly and selection diagnostics for the real .NET mesh gate.

Split out of :mod:`tools.mesh_harness.real_dotnet` to keep that file inside the
repository's owned-file size ratchet. This half holds the pieces that read state
and turn it into evidence rather than driving the editor: the front-facing
anchor search, the ordered protocol trail, the settled-pane projection lookup,
the selection-push bookkeeping that says which push the helper answered with,
and the final result payload.

The functions the gate monkeypatches are re-exported from ``real_dotnet``, so
callers there resolve them through that module's namespace and patching it still
intercepts.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from cdmw.modding.mesh_native_core import (
    NATIVE_MESH_CORE_BACKEND_ID,
    native_mesh_core_fallback_counts,
    native_mesh_core_fallback_events,
)
from tools.mesh_harness.archive_provenance import (
    _archive_content_fingerprints,
    _archive_entry_provenance,
    _archive_source_file_snapshot,
)
from tools.mesh_harness.png_evidence import _write_real_archive_visual_edit_proof
from tools.mesh_harness.real_common import _read_archive_payload

from tools.mesh_harness.native_projection import (
    _finite_float,
    _project_world_to_screen,
    _timing_summary,
)
from tools.mesh_harness.evidence import _real_game_mesh_evidence
from tools.mesh_harness.real_dotnet_capture import capture_dotnet_viewport as _capture_viewport
from tools.mesh_harness.real_dotnet_display import exercise_geometry_display_modes
from tools.mesh_harness.real_dotnet_evidence import (
    _DOTNET_RENDERER_BACKEND,
    _indices_by_submesh,
    _part_selection_evidence,
    _pick_probe,
    _result_gates,
    _revision_ack_tail,
)
from tools.mesh_harness.real_dotnet_flow import production_flow_gates
from tools.mesh_harness.real_dotnet_material import (
    material_parameter_evidence,
    material_parameter_gates,
    resident_material_evidence,
    resident_material_gates,
)
from tools.mesh_harness.service_summary import _command_summary

#: A full-mesh selection would otherwise bury the trail it is meant to make
#: readable, so long arrays are summarised rather than written whole.
_TRAIL_ARRAY_LIMIT = 512


def _front_facing_vertex_selection_anchor(
    submesh: object,
    matrix: tuple[object, ...],
    *,
    viewport_width: float,
    viewport_height: float,
) -> tuple[int, int, tuple[float, float]] | None:
    """Choose an exact visible vertex using the renderer's winding contract."""

    vertices = tuple(getattr(submesh, "vertices", ()) or ())
    faces = tuple(getattr(submesh, "faces", ()) or ())
    viewport_center = (viewport_width * 0.5, viewport_height * 0.5)
    candidates: list[tuple[float, int, tuple[int, int, tuple[float, float]]]] = []
    for face_index, face in enumerate(faces):
        indices = tuple(int(value) for value in tuple(face or ())[:3])
        if len(indices) != 3 or any(index < 0 or index >= len(vertices) for index in indices):
            continue
        projected = tuple(
            _project_world_to_screen(
                matrix,
                vertices[index],
                viewport_x=0.0,
                viewport_y=0.0,
                viewport_width=viewport_width,
                viewport_height=viewport_height,
            )
            for index in indices
        )
        if any(point is None for point in projected):
            continue
        points = tuple(point for point in projected if point is not None)
        area = (
            (points[1][0] - points[0][0]) * (points[2][1] - points[0][1])
            - (points[1][1] - points[0][1]) * (points[2][0] - points[0][0])
        )
        if area >= -0.01:
            continue
        center = (
            sum(point[0] for point in points) / 3.0,
            sum(point[1] for point in points) / 3.0,
        )
        vertex_offset = min(
            range(3),
            key=lambda offset: math.hypot(
                points[offset][0] - center[0],
                points[offset][1] - center[1],
            ),
        )
        point = points[vertex_offset]
        if not (0.0 <= point[0] < viewport_width and 0.0 <= point[1] < viewport_height):
            continue
        score = math.hypot(center[0] - viewport_center[0], center[1] - viewport_center[1])
        candidates.append((score, face_index, (face_index, indices[vertex_offset], point)))
    return min(candidates, default=None, key=lambda item: (item[0], item[1]))[2] if candidates else None


def _last_select_request_id(state: SimpleNamespace) -> int:
    """The request id of the newest selection request the helper raised."""

    newest = 0
    for event in tuple(state.tab.standalone_dotnet_protocol_events):
        if str(event.get("event", "") or "").strip().lower() != "select_request":
            continue
        try:
            newest = max(newest, int(event.get("request_id", 0) or 0))
        except (TypeError, ValueError):
            continue
    return newest


def _applied_selection_push_id(event: object) -> int:
    """Which push the helper had applied when it answered a tool state."""

    local_selection = event.get("local_selection") if isinstance(event, Mapping) else None
    push = (
        local_selection.get("last_host_selection_push")
        if isinstance(local_selection, Mapping)
        else None
    )
    try:
        return int((push or {}).get("request_id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _resident_selection_inputs(state: SimpleNamespace) -> dict[str, object]:
    """Record what decides `reuse_resident_selection` for the Move stroke.

    `tab_interaction` reuses the committed selection only when
    `standalone_dotnet_target_controller` resolves to a controller whose session
    view still holds a selection.  When it does not, Move re-picks a screen
    brush footprint instead, so the two drag gates need to tell those apart.
    """

    report: dict[str, object] = {}
    tab = getattr(state, "tab", None)
    target = getattr(tab, "standalone_dotnet_target_controller", None)
    harness = getattr(state, "controller", None)
    report["target_controller_present"] = target is not None
    report["target_controller_is_harness_controller"] = target is harness
    report["fallback_controller_present"] = (
        getattr(tab, "standalone_controller", None) is not None
    )
    for label, controller in (("target", target), ("harness", harness)):
        if controller is None:
            report[f"{label}_session_id"] = None
            report[f"{label}_selection_empty"] = None
            report[f"{label}_selection_vertex_count"] = None
            report[f"{label}_selection_counts_by_submesh"] = None
            report[f"{label}_selection_indices_by_submesh"] = None
            continue
        try:
            view = controller.session_view()
            report[f"{label}_session_id"] = str(getattr(view, "session_id", ""))
            report[f"{label}_selection_empty"] = bool(view.selection.is_empty())
            vertex_map = view.selection.vertex_map()
            report[f"{label}_selection_vertex_count"] = sum(
                len(indices) for indices in vertex_map.values()
            )
            report[f"{label}_selection_counts_by_submesh"] = {
                str(submesh): len(indices)
                for submesh, indices in sorted(vertex_map.items())
            }
            report[f"{label}_selection_indices_by_submesh"] = {
                str(submesh): sorted(int(index) for index in indices)
                for submesh, indices in sorted(vertex_map.items())
            }
        except (AttributeError, RuntimeError, TypeError, ValueError) as error:
            report[f"{label}_session_id"] = None
            report[f"{label}_selection_empty"] = None
            report[f"{label}_selection_vertex_count"] = None
            report[f"{label}_selection_counts_by_submesh"] = None
            report[f"{label}_selection_indices_by_submesh"] = None
            report[f"{label}_error"] = f"{type(error).__name__}: {error}"
    return report


def _trail_value(value: object, depth: int = 0) -> object:
    if depth > 6:
        return "<deep>"
    if isinstance(value, Mapping):
        return {str(key): _trail_value(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        items = list(value)
        if len(items) > _TRAIL_ARRAY_LIMIT:
            return {
                "length": len(items),
                "head": [_trail_value(item, depth + 1) for item in items[:32]],
                "tail": [_trail_value(item, depth + 1) for item in items[-8:]],
            }
        return [_trail_value(item, depth + 1) for item in items]
    return value


def write_protocol_trail(state: SimpleNamespace, name: str = "protocol_trail.jsonl") -> str:
    """Write every protocol event in order, beside the rest of the evidence.

    ``result.json`` keeps only the newest event of a handful of named kinds,
    which cannot answer *which* message committed a selection: the question needs
    the ordering, and it needs the events the summary drops, ``select_request``
    among them. One JSON object per line, in arrival order, with long arrays
    summarised so a whole-mesh selection cannot bury the trail.
    """
    output_dir = getattr(state, "output_dir", None)
    if output_dir is None:
        return ""
    path = Path(output_dir) / name
    events = tuple(getattr(state.tab, "standalone_dotnet_protocol_events", ()) or ())
    lines: list[str] = []
    for index, event in enumerate(events):
        payload = {"index": index}
        if isinstance(event, Mapping):
            payload.update({str(key): _trail_value(item) for key, item in event.items()})
        else:
            payload["event"] = repr(event)
        lines.append(json.dumps(payload, sort_keys=True))
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    temporary.replace(path)
    return str(path)


def _settled_screen_projection(
    state: SimpleNamespace,
) -> tuple[tuple[object, ...], float, float] | None:
    """The newest matrix the helper emitted, with the pane it was built for.

    Every ``select_request`` carries ``world_view_projection`` beside the
    ``viewport_width``/``viewport_height`` of the pane that produced it, so the
    pair is always self-consistent. Reading the newest one is how a caller
    obtains a projection for the pane as it stands now rather than as it stood
    when an earlier probe ran.
    """
    for event in reversed(tuple(state.tab.standalone_dotnet_protocol_events)):
        if str(event.get("event", "") or "").strip().lower() != "select_request":
            continue
        brush = event.get("screen_brush")
        if not isinstance(brush, Mapping):
            continue
        matrix = tuple(brush.get("world_view_projection", ()) or ())
        width = float(brush.get("viewport_width", 0) or 0)
        height = float(brush.get("viewport_height", 0) or 0)
        if len(matrix) == 16 and width > 0.0 and height > 0.0:
            return matrix, width, height
    return None


def _finish_result(state: SimpleNamespace) -> dict[str, object]:
    state.after_center = tuple(sum(vertex[axis] for vertex in state.after_vertices) / len(state.after_vertices) for axis in range(3))
    matrix = tuple(state.projection_drag.get("world_view_projection", ()) or ())
    state.projected_after_center = _project_world_to_screen(
        matrix,
        state.after_center,
        viewport_x=0.0,
        viewport_y=0.0,
        viewport_width=float(getattr(state, "projection_viewport_width", 0.0))
        or float(state.viewport.get("width", 0) or 0),
        viewport_height=float(getattr(state, "projection_viewport_height", 0.0))
        or float(state.viewport.get("height", 0) or 0),
    )
    projected_delta = (
        state.projected_after_center[0] - state.projected_center[0],
        state.projected_after_center[1] - state.projected_center[1],
    )
    expected_delta = (
        state.mouse_drag_effective_end[0] - state.mouse_drag_start[0],
        state.mouse_drag_effective_end[1] - state.mouse_drag_start[1],
    )
    state.projected_screen_error = math.hypot(projected_delta[0] - expected_delta[0], projected_delta[1] - expected_delta[1])
    state.projected_drag_tracks_cursor = state.projected_screen_error <= max(8.0, math.hypot(*expected_delta) * 0.35)
    state.visual_proof_summary = _write_real_archive_visual_edit_proof(
        state.selected_before_capture_path,
        state.after_capture_path,
        state.visual_proof_path,
        before_center=state.projected_center,
        after_center=state.projected_after_center,
        # The centres are in the pane the projection was built for; the captures are
        # whatever the window was when they were grabbed, and it narrows mid-run.
        projection_size=(state.projection_viewport_width, state.projection_viewport_height),
    )
    state.handler_summary = _timing_summary(state.stroke_handler_timings, "handler_ms")
    state.handler_p95_ms = _finite_float(state.handler_summary.get("p95_ms"))
    state.update_queue_metrics = state.tab.standalone_dotnet_update_queue.metrics()
    state.fallback_counts = native_mesh_core_fallback_counts()
    state.resident_material_gates = resident_material_gates(state)
    state.material_parameter_gates = material_parameter_gates(state)
    state.archive_sources_after = _archive_source_file_snapshot(state.entries)
    state.archive_content_fingerprints_after = _archive_content_fingerprints(state.fingerprint_paths)
    state.archive_sources_unchanged = state.archive_sources_before == state.archive_sources_after
    state.archive_source_content_unchanged = state.archive_content_fingerprints_before == state.archive_content_fingerprints_after
    state.source_payload_unchanged = sha256(_read_archive_payload(state.model_entry)).hexdigest() == state.source_payload_sha256
    gates = _result_gates(state)
    ok = bool(all(gates.values()) and state.mouse_down_sent and state.mouse_move_sent and state.mouse_up_sent)
    last_result = state.stroke_results[-1] if state.stroke_results else None
    return {
        "ok": ok,
        "status_messages": [dict(entry) for entry in tuple(getattr(state, "status_messages", ()) or ())],
        "read_only": gates["source_archives_unchanged"],
        "backend": "dotnet",
        "renderer_backend": state.renderer_backend,
        "edit_backend": NATIVE_MESH_CORE_BACKEND_ID if gates["edit_backend_ok"] else "",
        "workflow": "Ready -> select -> transform -> scalar -> two linked texture strokes -> committed DDS assignment -> UV edit -> duplicate/delete -> undo/redo -> coherent editable export -> full output reparse",
        "game_root": str(state.game_root),
        "pamt_path": str(state.pamt_path),
        "model_path": state.model_entry.path,
        "viewport_refresh": getattr(state, "viewport_refresh", {}),
        "archive_provenance": _archive_entry_provenance(state.model_entry),
        "source_payload_sha256": state.source_payload_sha256,
        "source_payload_unchanged": state.source_payload_unchanged,
        "archive_sources_unchanged": state.archive_sources_unchanged,
        "archive_source_content_unchanged": state.archive_source_content_unchanged,
        "archive_content_fingerprints_before": state.archive_content_fingerprints_before,
        "archive_content_fingerprints_after": state.archive_content_fingerprints_after,
        "bound_texture_count": len(state.resolved_textures),
        "resolved_production_textures": list(state.resolved_textures),
        "renderer": state.renderer,
        "viewport": state.viewport,
        "resident_material_update": resident_material_evidence(state),
        "resident_material_parameter_update": material_parameter_evidence(state),
        "geometry_display": dict(state.geometry_display_evidence),
        "builder_presentation": dict(state.builder_presentation_evidence),
        "camera_zoom": dict(getattr(state, "camera_zoom_evidence", {}) or {}),
        "production_flow": list(state.production_flow),
        "linked_texture_updates": dict(state.texture_flow_evidence),
        "resident_mesh_edits": dict(state.edit_flow_evidence),
        "resident_export": dict(state.export_flow_evidence),
        "exact_topology_rebuild": dict(getattr(state, "topology_rebuild_evidence", {}) or {}),
        "performance_capture": dict(getattr(state, "performance_capture_evidence", {}) or {}),
        "lifecycle_counts": dict(state.tab.standalone_dotnet_lifecycle_counts),
        "process_identity": {
            "initial_pid": state.production_process_pid,
            "final_pid": int(state.tab.standalone_dotnet_editor_process.processId()),
            "initial_windows": dict(state.production_window_identity),
            "final_windows": dict(state.final_window_identity),
        },
        "helper_provenance": dict(state.protocol_ready.get("provenance", {}) or {}),
        "offscreen_icon_capture": dict(state.offscreen_capture_evidence),
        "protocol_events": {
            "protocol_ready": state.protocol_ready,
            "ready": state.ready_event,
            "textures_ready": state.textures_event,
            "material_state_applied": state.material_state_applied,
            "material_parameter_applied": state.material_parameter_applied,
            "tool_state_applied": state.tool_state_event,
        },
        "part_selection": _part_selection_evidence(state),
        "submesh_index": state.submesh_index,
        "selected_faces": list(state.selected_faces),
        "selected_face_vertices": state.face_vertices,
        "selected_face_before_vertices": [list(vertex) for vertex in state.before_vertices],
        "selected_face_after_vertices": [list(vertex) for vertex in state.after_vertices],
        "selected_vertex_count": len(state.selected_vertex_keys),
        "selected_vertex_counts_by_submesh": {
            str(submesh_index): sum(
                1
                for selected_submesh_index, _vertex_index in state.selected_vertex_keys
                if selected_submesh_index == submesh_index
            )
            for submesh_index in sorted(
                {submesh_index for submesh_index, _vertex_index in state.selected_vertex_keys}
            )
        },
        "changed_vertex_count": len(state.changed_vertex_keys),
        "changed_vertex_counts_by_submesh": {
            str(submesh_index): sum(
                1
                for changed_submesh_index, _vertex_index in state.changed_vertex_keys
                if changed_submesh_index == submesh_index
            )
            for submesh_index in sorted(
                {submesh_index for submesh_index, _vertex_index in state.changed_vertex_keys}
            )
        },
        "selection_pick_probe": _pick_probe(state.tool_state_event),
        # Both index sets in full, per submesh. A 64-entry sample cannot tell a
        # subset apart from a disjoint set living in another index space, and
        # that distinction is the whole diagnosis when these two disagree.
        "selected_vertex_indices_by_submesh": _indices_by_submesh(state.selected_vertex_keys),
        "changed_vertex_indices_by_submesh": _indices_by_submesh(state.changed_vertex_keys),
        "unexpected_changed_vertex_count": len(
            state.unexpected_changed_vertex_keys
        ),
        "unexpected_changed_vertex_sample": [
            [submesh_index, vertex_index]
            for submesh_index, vertex_index in sorted(
                state.unexpected_changed_vertex_keys
            )[:64]
        ],
        "changed_only_selected_geometry": state.changed_only_selected_geometry,
        "selection_diagnostics": {
            "projection_seed_submesh_index": int(
                state.projection_seed_submesh_index
            ),
            "authoritative_primary_submesh_index": int(state.submesh_index),
            "projection_probe_mode": state.projection_probe_mode,
            "projection_probe_authority_settled": bool(
                state.projection_probe_authority_settled
            ),
            "projection_surface_reconciliation": dict(
                state.projection_surface_reconciliation
            ),
            "physical_selection_anchor": dict(
                state.physical_selection_anchor
            ),
            "resident_selection_inputs": dict(
                getattr(state, "resident_selection_inputs", {}) or {}
            ),
            "selection_publication_settled": dict(
                getattr(state, "selection_publication_settled", {}) or {}
            ),
        },
        "selected_projected_screen_center": list(state.projected_center),
        "selected_projected_after_screen_center": list(state.projected_after_center),
        "selected_projected_screen_delta": list(projected_delta),
        "selected_projected_screen_error": state.projected_screen_error,
        "mouse_drag_start": list(state.mouse_drag_start),
        "mouse_drag_points": [list(point) for point in state.mouse_drag_points],
        "mouse_drag_end": list(state.mouse_drag_end),
        "mouse_drag_effective_end": list(state.mouse_drag_effective_end),
        "mouse_input_backend": "win32_physical_cursor",
        "input_window_activated": bool(getattr(state, "input_window_activated", False)),
        "physical_viewport_origin": [
            int(state.viewport_rect_before[0]),
            int(state.viewport_rect_before[1]),
        ] if state.viewport_rect_before else None,
        "stroke_update_count": len(state.stroke_updates),
        "stroke_terminal_coverage": dict(state.stroke_terminal_coverage),
        "stroke_handler_timings": state.stroke_handler_timings,
        "stroke_handler_timing_summary": state.handler_summary,
        "stroke_completion_timings": state.stroke_completion_timings,
        "stroke_completion_stage_timings": state.stroke_completion_stage_timings,
        "main_thread_edit_handler_p95_ms": state.handler_p95_ms,
        "live_stroke_frame_budget_ms": 1000.0 / 60.0,
        "max_heartbeat_gap_ms": state.max_heartbeat_gap_ms,
        "heartbeat_sample_count": max(0, len(state.heartbeat_gaps) - 1),
        "heartbeat_gaps_ms": state.heartbeat_gaps,
        "update_queue_metrics": state.update_queue_metrics,
        "form_rect_before": list(state.form_rect_before) if state.form_rect_before else None,
        "form_rect_after": list(state.form_rect_after) if state.form_rect_after else None,
        "viewport_rect_before": list(state.viewport_rect_before) if state.viewport_rect_before else None,
        "viewport_rect_after": list(state.viewport_rect_after) if state.viewport_rect_after else None,
        "before_capture_png": str(state.before_capture_path),
        "selected_before_capture_png": str(state.selected_before_capture_path),
        "after_capture_png": str(state.after_capture_path),
        "visual_edit_proof_png": str(state.visual_proof_path),
        "before_capture_summary": state.before_capture_summary,
        "selected_before_capture_summary": state.selected_before_capture_summary,
        "after_capture_summary": state.after_capture_summary,
        "visual_edit_proof_summary": state.visual_proof_summary,
        "action_elapsed_ms": state.action_elapsed_ms,
        "command": _command_summary(last_result) if last_result is not None else {},
        "native_fallback_counts": state.fallback_counts,
        "native_fallback_events": list(native_mesh_core_fallback_events()),
        "protocol_trail_jsonl": write_protocol_trail(state),
        "gates": gates,
    }
