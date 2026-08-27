from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.modding.mesh_native_core import (
    NATIVE_MESH_CORE_BACKEND_ID,
    clear_native_mesh_core_fallback_counts,
    native_mesh_core_available,
    native_mesh_core_fallback_counts,
    native_mesh_core_fallback_events,
)
from cdmw.services.mesh_service import MeshService
from tools.mesh_harness.archive_provenance import (
    _archive_content_fingerprints,
    _archive_entry_provenance,
    _archive_source_file_snapshot,
    _hydrate_real_archive_mesh_materials,
)
from tools.mesh_harness.constants import (
    _MK_LBUTTON,
    _REAL_ARCHIVE_RIGGING_SAMPLES,
    _WM_LBUTTONDOWN,
    _WM_LBUTTONUP,
    _WM_MOUSEMOVE,
)
from tools.mesh_harness.native_projection import (
    _finite_float,
    _project_world_to_screen,
    _projected_face_cluster_for_drag,
    _timing_summary,
)
from tools.mesh_harness.win32_input import _host_window_rect, _send_mouse_message
from tools.mesh_harness.png_evidence import _write_real_archive_visual_edit_proof
from tools.mesh_harness.performance_contract import (
    PERFORMANCE_HARNESS_EVIDENCE_SCHEMA,
    PerformanceRequest,
    begin_performance_capture,
    finish_performance_capture,
)
from tools.mesh_harness.real_dotnet_performance import (
    _configure_performance_viewport,
    _performance_requires_edit_preparation,
    _restore_performance_viewport,
    _run_performance_interactions,
)
from tools.mesh_harness.real_common import _archive_entry_indexes, _archive_key, _read_archive_payload
from tools.mesh_harness.real_dotnet_capture import (
    capture_dotnet_viewport as _capture_viewport,
    exercise_deterministic_offscreen_capture,
)
from tools.mesh_harness.real_dotnet_material import (
    exercise_material_parameter_update,
    exercise_resident_material_update,
    material_parameter_evidence,
    material_parameter_gates,
    request_full_renderer_status,
    resident_material_evidence,
    resident_material_gates,
)
from tools.mesh_harness.real_dotnet_geometry import refresh_editable_viewport_rectangle
from tools.mesh_harness.real_dotnet_flow import (
    exercise_assignment_and_mesh_edits,
    exercise_coherent_export,
    production_flow_gates,
    record_flow_step,
)
from tools.mesh_harness.real_dotnet_topology import exercise_exact_topology_rebuild
from tools.mesh_harness.real_dotnet_input import (
    drive_viewport_selection,
    drive_viewport_stroke,
    exercise_side_by_side_wheel_zoom,
)
from tools.mesh_harness.real_dotnet_display import (
    exercise_builder_presentation_controls,
    exercise_geometry_display_modes,
)
from tools.mesh_harness.service_summary import _command_summary
from tools.mesh_harness.real_dotnet_evidence import (
    _DOTNET_RENDERER_BACKEND,
    _base_error,
    _drive_viewport_stroke,
    _has_real_archive_texture_provenance,
    _indices_by_submesh,
    _part_selection_evidence,
    _pick_probe,
    _prepare_real_asset,
    _pump_for,
    _pump_until,
    _record_stroke_geometry_evidence,
    _result_gates,
    _revision_ack_tail,
    _wait_protocol_event,
)
from tools.mesh_harness.real_dotnet_report import (
    _TRAIL_ARRAY_LIMIT,
    _applied_selection_push_id,
    _finish_result,
    _front_facing_vertex_selection_anchor,
    _last_select_request_id,
    _resident_selection_inputs,
    _settled_screen_projection,
    _trail_value,
    write_protocol_trail,
)
from tools.mesh_harness.real_dotnet_session import (
    _install_timing_probes,
    _start_embedded_editor,
)


















def _execute_performance_capture(state: SimpleNamespace, request: PerformanceRequest) -> str:
    try:
        if not _configure_performance_viewport(state, request):
            return "Could not size the resident performance viewport to the manifest contract."
        message = begin_performance_capture(state, request, pump_until=_pump_until)
        if message:
            return message
        interaction_execution = _run_performance_interactions(state, request)
        if not interaction_execution.get("ok"):
            return "Configured performance interactions did not execute completely."
        return finish_performance_capture(state, pump_until=_pump_until)
    finally:
        _restore_performance_viewport(state)








def _prepare_selection_projection(
    state: SimpleNamespace,
) -> tuple[tuple[int, ...], list[int], tuple[object, ...]]:
    # Edit Mesh viewport gestures own mesh-vertex selection; whole parts belong
    # only to the PARTS list. Ask Select for a screen payload at the viewport
    # centre so the projection probe cannot move the temporary seed submesh.
    # The probe's selection is cleared before the measured physical gesture.
    state.projection_seed_submesh_index = int(state.submesh_index)
    state.projection_probe_mode = "select_screen_brush"
    initial_faces = tuple(range(len(state.submesh.faces)))
    initial_vertex_indices = sorted(
        {vertex for face_index in initial_faces for vertex in state.submesh.faces[int(face_index)]}
    )
    tool_cursor = len(state.tab.standalone_dotnet_protocol_events)
    state.tool_state_sent = state.tab._send_dotnet_protocol_message(
        {
            "event": "tool_state",
            "tool": "select",
            "target_mode": "vertex",
            "selection_mode": "brush",
            "selection_operation": "replace",
        }
    )
    state.projection_tool_state_event = _wait_protocol_event(
        state, "tool_state_applied", tool_cursor, 5.0
    )
    # Re-read the viewport rectangle before using it to aim anything. The one
    # carried on the ready event describes the embedded editor window before it
    # was revealed and grown -- 547x603 against a live 1467x1139 here -- and the
    # projection matrix below is paired with the *live* pane. Aiming a probe, a
    # projection and a drag with a mix of the two clamps the stroke to a right
    # edge that moved long ago. Both payloads are editable-pane-local, so a fresh
    # read is directly comparable; the renderer publishes it on demand.
    state.viewport_refresh = refresh_editable_viewport_rectangle(state, _pump_until)
    width = int(state.viewport.get("width", 0) or 0)
    height = int(state.viewport.get("height", 0) or 0)
    client_x = int(state.viewport.get("client_x", 0) or 0)
    client_y = int(state.viewport.get("client_y", 0) or 0)
    probe = (client_x + max(1, width // 2), client_y + max(1, height // 2))
    cursor = len(state.tab.standalone_dotnet_protocol_events)
    state.probe_down_sent = _send_mouse_message(state.viewport_hwnd, _WM_LBUTTONDOWN, *probe, wparam=_MK_LBUTTON)
    state.probe_started = _wait_protocol_event(state, "select_request", cursor, 2.0)
    cursor = len(state.tab.standalone_dotnet_protocol_events)
    state.probe_up_sent = _send_mouse_message(state.viewport_hwnd, _WM_LBUTTONUP, *probe)
    state.probe_finished = _wait_protocol_event(
        state, "select_request", cursor, 2.0
    )
    state.projection_probe_authority_settled = bool(
        state.probe_finished
        and _pump_until(
            state,
            lambda: not state.tab._standalone_action_worker_active(),
            5.0,
        )
    )
    screen_brush = (
        state.probe_finished.get("screen_brush", {})
        if isinstance(state.probe_finished, Mapping)
        else {}
    )
    state.projection_drag = (
        dict(screen_brush) if isinstance(screen_brush, Mapping) else {}
    )
    matrix = tuple(state.projection_drag.get("world_view_projection", ()) or ())
    # Project through the surface this matrix was actually built for. The
    # renderer pairs each matrix with the active pane's bounds, which are not
    # the host window's client size: projecting a pane matrix through the
    # window size scaled every screen-space result by the ratio between them
    # (418/698 here), so a drag that tracked the cursor exactly looked like it
    # under-tracked by 40%.
    state.projection_viewport_width = float(
        state.projection_drag.get("viewport_width", 0) or 0
    ) or float(width)
    state.projection_viewport_height = float(
        state.projection_drag.get("viewport_height", 0) or 0
    ) or float(height)
    projection_width = int(round(state.projection_viewport_width))
    projection_height = int(round(state.projection_viewport_height))
    surface_rect = _host_window_rect(state.viewport_hwnd)
    surface_width = int(surface_rect[2] - surface_rect[0]) if surface_rect else 0
    surface_height = int(surface_rect[3] - surface_rect[1]) if surface_rect else 0
    state.projection_surface_reconciliation = {
        "status_width": width,
        "status_height": height,
        "projection_width": projection_width,
        "projection_height": projection_height,
        "surface_width": surface_width,
        "surface_height": surface_height,
        "reconciled": False,
    }
    # The host can resize the embedded child after the correlated renderer-status
    # reply but before the first pointer event is dispatched. Trust the newer
    # projection dimensions only when Windows independently reports the exact
    # same child-surface rectangle; otherwise the stroke driver keeps rejecting
    # the disagreement as before.
    if (
        surface_rect
        and (projection_width, projection_height) == (surface_width, surface_height)
        and (width, height) != (projection_width, projection_height)
    ):
        state.viewport.update(
            {
                "screen_x": int(surface_rect[0]),
                "screen_y": int(surface_rect[1]),
                "client_x": 0,
                "client_y": 0,
                "width": projection_width,
                "height": projection_height,
            }
        )
        state.projection_surface_reconciliation["reconciled"] = True
    return initial_faces, initial_vertex_indices, matrix


def _arm_move_and_read_applied_selection(state: SimpleNamespace) -> None:
    """Arm Move and read the selection the helper has actually applied.

    The helper answers `tool_state` from the selection push it has already
    applied, and that trails the gesture by one. Measured in the trail: the
    answer following the push for request 8 still reported request 4, the
    projection probe's 39 vertices, so a single ask samples the selection before
    last. Re-ask until the applied push has caught up with the gesture's own
    newest request, and record whether it did.
    """

    expected_push = _last_select_request_id(state)
    arming: dict[str, object] = {"expected_push_request_id": expected_push, "attempts": 0}
    state.tool_state_sent = bool(state.tool_state_sent and state.selection_tool_state_sent)
    state.tool_state_event = {}
    for attempt in range(1, 5):
        if not state.tool_state_sent:
            break
        tool_cursor = len(state.tab.standalone_dotnet_protocol_events)
        state.tool_state_sent = bool(
            state.tab._send_dotnet_protocol_message(
                {"event": "tool_state", "tool": "move", "target_mode": "vertex"}
            )
        )
        if not state.tool_state_sent:
            break
        state.tool_state_event = _wait_protocol_event(
            state, "tool_state_applied", tool_cursor, 5.0
        )
        arming["attempts"] = attempt
        arming["applied_push_request_id"] = _applied_selection_push_id(state.tool_state_event)
        if _applied_selection_push_id(state.tool_state_event) >= expected_push:
            break
        _pump_for(state, 0.1)
    arming["caught_up"] = bool(
        int(arming.get("applied_push_request_id", 0) or 0) >= expected_push
    )
    state.selection_publication_settled = arming


def _drive_projected_vertex_selection(
    state: SimpleNamespace,
    initial_faces: tuple[int, ...],
    initial_vertex_indices: list[int],
    matrix: tuple[object, ...],
) -> dict[str, object] | None:
    selected_faces = _projected_face_cluster_for_drag(
        state.submesh,
        matrix,
        viewport_x=0.0,
        viewport_y=0.0,
        viewport_width=state.projection_viewport_width,
        viewport_height=state.projection_viewport_height,
    ) if matrix else initial_faces
    # Projected faces choose a stable on-mesh target for the physical Select
    # gesture. The direct seed above exists only long enough to obtain this
    # renderer projection; it is cleared before Select is armed and is never
    # used as the Move selection under test.
    state.projected_anchor_faces = selected_faces or initial_faces
    current = state.controller.working_mesh(clone=False)
    anchor_vertex_indices = sorted(
        {
            int(vertex_index)
            for face_index in state.projected_anchor_faces
            if 0 <= int(face_index) < len(state.submesh.faces)
            for vertex_index in state.submesh.faces[int(face_index)]
            if 0 <= int(vertex_index) < len(current.submeshes[state.submesh_index].vertices)
        }
    ) or initial_vertex_indices
    selection_anchor = _front_facing_vertex_selection_anchor(
        state.submesh,
        matrix,
        viewport_width=state.projection_viewport_width,
        viewport_height=state.projection_viewport_height,
    ) if matrix else None
    state.physical_selection_anchor = {
        "face_index": int(selection_anchor[0]),
        "vertex_index": int(selection_anchor[1]),
        "point": [float(selection_anchor[2][0]), float(selection_anchor[2][1])],
    } if selection_anchor is not None else {}
    projected_anchor_center = selection_anchor[2] if selection_anchor is not None else None
    state.select_result = state.controller.select(operation="replace")
    state.tab._send_dotnet_session_state()
    select_tool_cursor = len(state.tab.standalone_dotnet_protocol_events)
    state.selection_tool_state_sent = state.tab._send_dotnet_protocol_message(
        {
            "event": "tool_state",
            "tool": "select",
            "target_mode": "vertex",
            "selection_mode": "brush",
            "selection_operation": "replace",
        }
    )
    state.selection_tool_state_event = _wait_protocol_event(
        state, "tool_state_applied", select_tool_cursor, 5.0
    )
    state.physical_select_gesture = (
        drive_viewport_selection(
            state,
            point=projected_anchor_center,
            pump_for=_pump_for,
            pump_until=_pump_until,
        )
        if projected_anchor_center is not None
        else {"ok": False, "reason": "projection_missing"}
    )
    _arm_move_and_read_applied_selection(state)
    state.resident_selection_inputs = _resident_selection_inputs(state)
    tool_selection = state.tool_state_event.get("local_selection", {})
    tool_selection = tool_selection if isinstance(tool_selection, Mapping) else {}
    selected_sources = tuple(
        int(value) for value in tuple(tool_selection.get("source_indices", ()) or ())
    )
    raw_vertex_map = tool_selection.get("vertices_by_submesh")
    raw_vertex_map = raw_vertex_map if isinstance(raw_vertex_map, Mapping) else {}
    selected_vertex_keys: set[tuple[int, int]] = set()
    for raw_submesh_index, raw_indices in raw_vertex_map.items():
        try:
            selected_submesh_index = int(raw_submesh_index)
        except (TypeError, ValueError):
            continue
        for raw_vertex_index in tuple(raw_indices or ()):
            try:
                selected_vertex_keys.add((selected_submesh_index, int(raw_vertex_index)))
            except (TypeError, ValueError):
                continue
    state.selected_vertex_keys = selected_vertex_keys
    selected_vertices_by_submesh: dict[int, tuple[int, ...]] = {}
    for selected_submesh_index in sorted(
        {submesh_index for submesh_index, _vertex_index in selected_vertex_keys}
    ):
        selected_vertices_by_submesh[selected_submesh_index] = tuple(
            sorted(
                vertex_index
                for submesh_index, vertex_index in selected_vertex_keys
                if submesh_index == selected_submesh_index
            )
        )
    projection_seed_submesh_index = int(
        getattr(state, "projection_seed_submesh_index", state.submesh_index)
    )
    if projection_seed_submesh_index in selected_vertices_by_submesh:
        selected_submesh_index = projection_seed_submesh_index
    elif selected_vertices_by_submesh:
        selected_submesh_index = max(
            selected_vertices_by_submesh,
            key=lambda submesh_index: (
                len(selected_vertices_by_submesh[submesh_index]),
                -submesh_index,
            ),
        )
    else:
        selected_submesh_index = projection_seed_submesh_index
    selected_vertices = selected_vertices_by_submesh.get(selected_submesh_index, ())
    if selected_vertices and 0 <= selected_submesh_index < len(current.submeshes):
        # Overlapping archive parts can put the visible brush hit on a different
        # submesh from the largest part used to obtain the projection matrix.
        # The helper's authoritative selection owns the subsequent Move proof;
        # rejecting that valid hit made the real-PAC gate fail intermittently.
        state.submesh_index = selected_submesh_index
        state.submesh = current.submeshes[selected_submesh_index]
    selected_part_rows = tuple(state.tool_state_event.get("parts_list_selected_indices", ()) or ())
    state.part_selection_remained_empty = bool(
        not selected_sources
        and int(state.tool_state_event.get("selected_part_index", -2)) == -1
        and int(state.tool_state_event.get("parts_list_selected_index", -2)) == -1
        and not selected_part_rows
    )
    state.viewport_mesh_selection_armed = bool(
        state.part_selection_remained_empty
        and state.physical_select_gesture.get("ok") is True
        and str(tool_selection.get("target_mode", "vertex") or "vertex").strip().lower() == "vertex"
        and selected_vertex_keys
        and selected_vertices
    )
    selected_vertex_set = set(selected_vertices)
    state.selected_faces = tuple(
        face_index
        for face_index, face in enumerate(state.submesh.faces)
        if any(int(vertex_index) in selected_vertex_set for vertex_index in face)
    )
    state.face_vertices = list(selected_vertices)
    if (
        not state.tool_state_sent
        or not state.tool_state_event
        or not state.selection_tool_state_event
        or not state.viewport_mesh_selection_armed
    ):
        return _base_error(
            state,
            "The physical production Select gesture did not settle as a viewport vertex selection with PARTS empty.",
        )
    return None
















def _adopt_settled_projection(
    state: SimpleNamespace,
    matrix: tuple[object, ...],
) -> tuple[object, ...]:
    """Re-aim the projection at the pane the drag will actually be dispatched into.

    The embedded viewport settles to its final width on the first real pointer
    input: measured here it is 1047 wide when the projection probe runs and 1242
    once the physical Select gesture has landed, at the same origin and height.
    Projecting the selection centre through the narrower pane and then clicking
    that pixel in the wider one put the press about 97 px left of the selection,
    onto a different submesh, so the Move grabbed geometry the selection never
    contained and the selected vertices never moved at all.

    The gesture that just ran published its own matrix beside its own pane
    bounds, so adopting that pair costs no extra input and cannot disturb the
    selection under test. The refresh is what makes the stroke driver's existing
    surface guard meaningful, because that guard compares the projection against
    ``state.viewport``.
    """
    state.selection_viewport_refresh = refresh_editable_viewport_rectangle(state, _pump_until)
    settled = _settled_screen_projection(state)
    reconciliation = getattr(state, "projection_surface_reconciliation", None)
    if not isinstance(reconciliation, dict):
        reconciliation = {}
        state.projection_surface_reconciliation = reconciliation
    if settled is None:
        reconciliation["settled_projection_adopted"] = False
        reconciliation["settled_projection_reason"] = "no select_request carried a screen payload"
        return matrix

    settled_matrix, settled_width, settled_height = settled
    previous = (
        float(getattr(state, "projection_viewport_width", 0.0) or 0.0),
        float(getattr(state, "projection_viewport_height", 0.0) or 0.0),
    )
    reconciliation["settled_projection_width"] = settled_width
    reconciliation["settled_projection_height"] = settled_height
    reconciliation["probe_projection_width"] = previous[0]
    reconciliation["probe_projection_height"] = previous[1]
    if (settled_width, settled_height) == previous:
        reconciliation["settled_projection_adopted"] = False
        reconciliation["settled_projection_reason"] = "pane unchanged since the probe"
        return matrix

    state.projection_viewport_width = settled_width
    state.projection_viewport_height = settled_height
    updated = dict(state.projection_drag) if isinstance(state.projection_drag, Mapping) else {}
    updated.update(
        {
            "world_view_projection": settled_matrix,
            "viewport_width": settled_width,
            "viewport_height": settled_height,
        }
    )
    state.projection_drag = updated

    # Aim input at the same pane the matrix was built for. The status read here
    # is the one sampled before the probe, and the pane settles on the first
    # pointer input, so it can describe the pane as it was rather than as it is.
    # Projection and input have to come from one rectangle or the press lands
    # somewhere the projection never described, so both take the bounds the
    # renderer itself paired with the matrix, and the difference is recorded
    # rather than smoothed over. It no longer means the renderer is wrong: the
    # status used to be cached against the outer control while reporting the
    # child surface, which held it at the pre-settle size for the rest of the
    # session, and that is fixed.
    status_width = float(state.viewport.get("width", 0) or 0)
    status_height = float(state.viewport.get("height", 0) or 0)
    reconciliation["status_disagreed_with_settled_pane"] = (
        status_width,
        status_height,
    ) != (settled_width, settled_height)
    reconciliation["status_viewport_width"] = status_width
    reconciliation["status_viewport_height"] = status_height
    state.viewport.update(
        {"width": int(round(settled_width)), "height": int(round(settled_height))}
    )
    reconciliation["settled_projection_adopted"] = True
    reconciliation["settled_projection_reason"] = "the pane settled after the probe"
    return settled_matrix


def _capture_selected_projection_state(
    state: SimpleNamespace,
    matrix: tuple[object, ...],
) -> dict[str, object] | None:
    # Replaying host selection restores Orbit, so the final Move publication
    # above must remain the last tool state before the physical deformation.
    _pump_for(state, 0.15)
    matrix = _adopt_settled_projection(state, matrix)
    current = state.controller.working_mesh(clone=False)
    state.before_vertices = [
        tuple(float(value) for value in current.submeshes[state.submesh_index].vertices[index])
        for index in state.face_vertices
    ]
    selected_vertices_world = [
        tuple(
            float(value)
            for value in current.submeshes[state.submesh_index].vertices[vertex_index]
        )
        for vertex_index in state.face_vertices
    ]
    state.selected_center = tuple(
        sum(vertex[axis] for vertex in selected_vertices_world) / len(selected_vertices_world)
        for axis in range(3)
    )
    state.projected_center = _project_world_to_screen(
        matrix,
        state.selected_center,
        viewport_x=0.0,
        viewport_y=0.0,
        viewport_width=state.projection_viewport_width,
        viewport_height=state.projection_viewport_height,
    ) if matrix else None
    state.selected_before_capture_summary = _capture_viewport(state, state.selected_before_capture_path)
    if (
        not state.tool_state_sent
        or not state.tool_state_event
        or not state.selection_tool_state_event
        or state.projected_center is None
    ):
        return _base_error(state, "Could not configure the production .NET Move tool and projected mesh selection.")
    return None


def _configure_selection_and_projection(state: SimpleNamespace) -> dict[str, object] | None:
    initial_faces, initial_vertex_indices, matrix = _prepare_selection_projection(state)
    error = _drive_projected_vertex_selection(
        state,
        initial_faces,
        initial_vertex_indices,
        matrix,
    )
    if error is not None:
        return error
    return _capture_selected_projection_state(state, matrix)




def run_real_archive_mesh_editor_dotnet_edit_smoke(
    game_root: Path,
    output_dir: Path,
    *,
    timeout_seconds: float = 45.0,
    performance_request: PerformanceRequest | None = None,
) -> dict[str, object]:
    clear_native_mesh_core_fallback_counts()
    output_dir.mkdir(parents=True, exist_ok=True)
    effective_timeout_seconds = float(timeout_seconds)
    if performance_request is not None:
        effective_timeout_seconds += float(performance_request.duration_seconds) + 30.0
    prepared = (
        _prepare_real_asset(
            Path(game_root),
            Path(output_dir),
            effective_timeout_seconds,
            model_path=performance_request.manifest.asset_model_path,
        )
        if performance_request is not None
        else _prepare_real_asset(Path(game_root), Path(output_dir), effective_timeout_seconds)
    )
    if isinstance(prepared, dict):
        if performance_request is not None:
            prepared["performance_capture"] = {
                "schema": PERFORMANCE_HARNESS_EVIDENCE_SCHEMA,
                "configured": True,
                "active": False,
                "ok": False,
                "status": "not_started",
                "request": performance_request.as_evidence(),
            }
        return prepared
    state = prepared
    state.tab = state.controller = state.heartbeat_timer = state.process = None
    state.output_dir = Path(output_dir)
    state.topology_rebuild_evidence = {}
    state.topology_rebuild_ok = False
    state.performance_request = performance_request
    state.performance_capture_evidence = (
        {
            "schema": PERFORMANCE_HARNESS_EVIDENCE_SCHEMA,
            "configured": True,
            "active": False,
            "ok": False,
            "status": "pending_helper_ready",
            "request": performance_request.as_evidence(),
        }
        if performance_request is not None
        else {}
    )
    state.performance_heartbeat_callback = None
    performance_completed = False
    try:
        error = _start_embedded_editor(state)
        if error is not None:
            return error
        if performance_request is not None and not _performance_requires_edit_preparation(performance_request):
            message = _execute_performance_capture(state, performance_request)
            performance_completed = not bool(message)
            if message:
                return _base_error(state, message)
        state.process = state.tab.standalone_dotnet_editor_process
        error = exercise_resident_material_update(
            state, base_error=_base_error, pump_until=_pump_until, wait_protocol_event=_wait_protocol_event
        )
        if error is not None:
            return error
        state.offscreen_capture_evidence = exercise_deterministic_offscreen_capture(
            state,
            pump_until=_pump_until,
            wait_protocol_event=_wait_protocol_event,
        )
        if not state.offscreen_capture_evidence.get("ok"):
            return _base_error(state, "Deterministic production offscreen icon capture failed.")
        message = exercise_builder_presentation_controls(
            state,
            pump_until=_pump_until,
            capture_viewport=_capture_viewport,
        )
        if message:
            return _base_error(state, message)
        message = exercise_geometry_display_modes(
            state,
            pump_until=_pump_until,
            capture_viewport=_capture_viewport,
        )
        if message:
            return _base_error(state, message)
        error = _configure_selection_and_projection(state)
        if error is not None:
            return error
        record_flow_step(state, "select", submesh_index=state.submesh_index, face_count=len(state.selected_faces))
        error = _drive_viewport_stroke(state)
        if error is not None:
            return error
        _record_stroke_geometry_evidence(state)
        record_flow_step(state, "transform", update_count=len(state.stroke_updates))
        error = exercise_material_parameter_update(
            state,
            base_error=_base_error,
            pump_until=_pump_until,
            wait_protocol_event=_wait_protocol_event,
            capture_viewport=_capture_viewport,
        )
        if error is not None:
            return error
        record_flow_step(
            state,
            "scalar_update",
            parameter_generation=int(state.material_parameter_payload.get("parameter_generation", 0) or 0),
        )
        message = exercise_assignment_and_mesh_edits(state, pump_until=_pump_until)
        if message:
            return _base_error(state, message)
        message = exercise_coherent_export(state, pump_until=_pump_until)
        if message:
            return _base_error(state, message)
        message = exercise_exact_topology_rebuild(state, pump_until=_pump_until)
        if message:
            return _base_error(state, message)
        if performance_request is not None and not performance_completed:
            message = _execute_performance_capture(state, performance_request)
            if message:
                return _base_error(state, message)
        return _finish_result(state)
    except Exception as exc:
        return _base_error(state, f"{type(exc).__name__}: {exc}")
    finally:
        if getattr(state, "performance_capture_evidence", {}).get("active"):
            try:
                finish_performance_capture(state, pump_until=_pump_until)
            except Exception as exc:
                state.performance_capture_evidence.update(
                    {
                        "active": False,
                        "ok": False,
                        "status": "shutdown_error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        if state.heartbeat_timer is not None:
            state.heartbeat_timer.stop()
        if state.tab is not None:
            try:
                state.tab._stop_standalone_dotnet_editor_process()
                if state.process is not None:
                    _pump_until(state, lambda: not state.tab._standalone_dotnet_editor_process_running(), 5.0)
                state.tab.deleteLater()
                state.app.processEvents()
            except Exception:
                pass
        if state.controller is not None:
            try:
                state.controller.close_active_session()
            except Exception:
                pass
        if hasattr(state, "settings"):
            state.settings.sync()


def run_real_archive_mesh_editor_dotnet_zoom_smoke(
    game_root: Path,
    output_dir: Path,
    *,
    timeout_seconds: float = 45.0,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared = _prepare_real_asset(Path(game_root), Path(output_dir), timeout_seconds)
    if isinstance(prepared, dict):
        return prepared
    state = prepared
    state.tab = state.controller = state.heartbeat_timer = state.process = None
    try:
        error = _start_embedded_editor(state, side_by_side_camera=True)
        if error is not None:
            return error
        state.camera_zoom_evidence = exercise_side_by_side_wheel_zoom(
            state,
            pump_for=_pump_for,
            pump_until=_pump_until,
            capture_viewport=_capture_viewport,
        )
        state.archive_sources_after = _archive_source_file_snapshot(state.entries)
        state.archive_content_fingerprints_after = _archive_content_fingerprints(
            state.fingerprint_paths
        )
        state.archive_sources_unchanged = (
            state.archive_sources_before == state.archive_sources_after
        )
        state.archive_source_content_unchanged = (
            state.archive_content_fingerprints_before
            == state.archive_content_fingerprints_after
        )
        state.source_payload_unchanged = (
            sha256(_read_archive_payload(state.model_entry)).hexdigest()
            == state.source_payload_sha256
        )
        gates = {
            "camera_zoom": bool(state.camera_zoom_evidence.get("ok")),
            "renderer_backend": state.renderer_backend == _DOTNET_RENDERER_BACKEND,
            "source_archives_unchanged": bool(
                state.archive_sources_unchanged
                and state.archive_source_content_unchanged
                and state.source_payload_unchanged
            ),
        }
        return {
            "ok": all(gates.values()),
            "read_only": gates["source_archives_unchanged"],
            "backend": "dotnet",
            "renderer_backend": state.renderer_backend,
            "edit_backend": NATIVE_MESH_CORE_BACKEND_ID if native_mesh_core_available() else "",
            "game_root": str(state.game_root),
            "model_path": state.model_entry.path,
            "camera_zoom": dict(state.camera_zoom_evidence),
            "archive_content_fingerprints_before": state.archive_content_fingerprints_before,
            "archive_content_fingerprints_after": state.archive_content_fingerprints_after,
            "source_payload_unchanged": state.source_payload_unchanged,
            "source_archives_unchanged": gates["source_archives_unchanged"],
            "gates": gates,
        }
    except Exception as exc:
        return _base_error(state, f"{type(exc).__name__}: {exc}")
    finally:
        if state.heartbeat_timer is not None:
            state.heartbeat_timer.stop()
        if state.tab is not None:
            try:
                state.tab._stop_standalone_dotnet_editor_process()
                _pump_until(
                    state,
                    lambda: not state.tab._standalone_dotnet_editor_process_running(),
                    5.0,
                )
                state.tab.deleteLater()
                state.app.processEvents()
            except Exception:
                pass
        if state.controller is not None:
            try:
                state.controller.close_active_session()
            except Exception:
                pass
        if hasattr(state, "settings"):
            state.settings.sync()


__all__ = [
    "run_real_archive_mesh_editor_dotnet_edit_smoke",
    "run_real_archive_mesh_editor_dotnet_zoom_smoke",
]
