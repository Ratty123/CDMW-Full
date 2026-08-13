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
    exercise_linked_texture_strokes,
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
from tools.mesh_harness.real_dotnet_session import (
    _install_timing_probes,
    _start_embedded_editor,
)
















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
    tool_cursor = len(state.tab.standalone_dotnet_protocol_events)
    state.tool_state_sent = bool(
        state.tool_state_sent
        and state.selection_tool_state_sent
        and state.tab._send_dotnet_protocol_message(
            {"event": "tool_state", "tool": "move", "target_mode": "vertex"}
        )
    )
    state.tool_state_event = _wait_protocol_event(
        state, "tool_state_applied", tool_cursor, 5.0
    )
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


#: Arrays longer than this are recorded as a length plus their head and tail.
#: Selections of a few hundred stay whole, which is the point; a full-mesh
#: selection would otherwise bury the trail it is meant to make readable.
_TRAIL_ARRAY_LIMIT = 512


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

    # Aim input at the same pane the matrix was built for. The renderer's status
    # payload disagrees with it here, publishing 1047x1195 for a pane that its
    # own ActivePaneBounds and Windows both report as 1242x1195, and the status
    # is the outlier of the three. Projection and input have to come from one
    # rectangle or the press lands somewhere the projection never described, so
    # both take the bounds the renderer itself paired with the matrix. The
    # disagreement is recorded rather than smoothed over.
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
        message = exercise_linked_texture_strokes(state, pump_until=_pump_until)
        if message:
            return _base_error(state, message)
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
