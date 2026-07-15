from __future__ import annotations

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
from tools.mesh_harness.native_protocol import _send_mouse_message
from tools.mesh_harness.png_evidence import _write_real_archive_visual_edit_proof
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
    resident_material_evidence,
    resident_material_gates,
)
from tools.mesh_harness.real_dotnet_flow import (
    exercise_assignment_and_mesh_edits,
    exercise_coherent_export,
    exercise_linked_texture_strokes,
    production_flow_gates,
    record_flow_step,
)
from tools.mesh_harness.real_dotnet_input import (
    drive_viewport_stroke,
    exercise_side_by_side_wheel_zoom,
)
from tools.mesh_harness.real_dotnet_display import (
    exercise_builder_presentation_controls,
    exercise_geometry_display_modes,
)
from tools.mesh_harness.service_summary import _command_summary


_DOTNET_RENDERER_BACKEND = "d3d11_vortice_shader"


def _revision_ack_tail(state: SimpleNamespace) -> list[dict[str, object]]:
    events = tuple(
        getattr(getattr(state, "tab", None), "standalone_dotnet_protocol_events", ()) or ()
    )
    names = {"preview_vertex_update_ack", "preview_triangle_update_ack", "resident_state_resync_ack"}
    return [dict(event) for event in events if str(event.get("event", "")) in names][-32:]


def _base_error(state: SimpleNamespace, message: str) -> dict[str, object]:
    before = dict(getattr(state, "archive_content_fingerprints_before", {}) or {})
    after = _archive_content_fingerprints(getattr(state, "fingerprint_paths", ())) if before else {}
    metadata_before = dict(getattr(state, "archive_sources_before", {}) or {})
    metadata_after = _archive_source_file_snapshot(getattr(state, "entries", ())) if metadata_before else {}
    payload_unchanged = False
    model_entry = getattr(state, "model_entry", None)
    source_hash = str(getattr(state, "source_payload_sha256", "") or "")
    if model_entry is not None and source_hash:
        try:
            payload_unchanged = sha256(_read_archive_payload(model_entry)).hexdigest() == source_hash
        except Exception:
            payload_unchanged = False
    pamt_path = getattr(state, "pamt_path", None)
    no_source_archives = bool(pamt_path is not None and not Path(pamt_path).is_file())
    content_unchanged = bool(no_source_archives or (before and before == after))
    archives_unchanged = bool(
        no_source_archives
        or (before and before == after and metadata_before == metadata_after and payload_unchanged)
    )
    resolved_textures = list(getattr(state, "resolved_textures", ()) or ())
    real_texture_provenance_ok = bool(getattr(state, "real_texture_provenance_ok", False))
    no_synthetic_fallback = bool(getattr(state, "no_synthetic_fallback", False))
    return {
        "ok": False,
        "read_only": archives_unchanged,
        "backend": "dotnet",
        "renderer_backend": str(getattr(state, "renderer_backend", "") or ""),
        "edit_backend": NATIVE_MESH_CORE_BACKEND_ID if native_mesh_core_available() else "",
        "game_root": str(state.game_root),
        "model_path": str(getattr(getattr(state, "model_entry", None), "path", "") or ""),
        "archive_provenance": (
            _archive_entry_provenance(model_entry) if model_entry is not None else {}
        ),
        "source_payload_sha256": source_hash,
        "resolved_production_textures": resolved_textures,
        "bound_texture_count": len(resolved_textures),
        "texture_gate_ok": bool(real_texture_provenance_ok and no_synthetic_fallback),
        "real_texture_provenance_ok": real_texture_provenance_ok,
        "no_synthetic_fallback": no_synthetic_fallback,
        "error": str(message),
        "production_flow": list(getattr(state, "production_flow", ()) or ()),
        "geometry_display": dict(getattr(state, "geometry_display_evidence", {}) or {}),
        "builder_presentation": dict(getattr(state, "builder_presentation_evidence", {}) or {}),
        "camera_zoom": dict(getattr(state, "camera_zoom_evidence", {}) or {}),
        "linked_texture_updates": dict(getattr(state, "texture_flow_evidence", {}) or {}),
        "lifecycle_counts": dict(
            getattr(getattr(state, "tab", None), "standalone_dotnet_lifecycle_counts", {}) or {}
        ),
        "texture_region_queue": (
            state.tab.standalone_texture_region_queue.metrics()
            if getattr(state, "tab", None) is not None
            and hasattr(state.tab, "standalone_texture_region_queue")
            else {}
        ),
        "update_queue": (
            state.tab.standalone_dotnet_update_queue.metrics()
            if getattr(state, "tab", None) is not None
            and hasattr(state.tab, "standalone_dotnet_update_queue")
            else {}
        ),
        "last_apply_update": dict(getattr(state, "last_apply_update_evidence", {}) or {}),
        "revision_ack_tail": _revision_ack_tail(state),
        "protocol_event_tail": list(
            tuple(getattr(getattr(state, "tab", None), "standalone_dotnet_protocol_events", ()) or ())[-16:]
        ),
        "dotnet_stderr_tail": str(
            getattr(getattr(state, "tab", None), "standalone_dotnet_stderr_tail", "") or ""
        )[-4000:],
        "archive_content_fingerprints_before": before,
        "archive_content_fingerprints_after": after,
        "archive_source_content_unchanged": content_unchanged,
        "archive_sources_unchanged": archives_unchanged,
        "source_payload_unchanged": payload_unchanged,
        "source_archives_unchanged": archives_unchanged,
        "source_archive_check": "not_applicable_no_source_archives" if no_source_archives else "verified" if archives_unchanged else "unverified",
    }


def _prepare_real_asset(game_root: Path, output_dir: Path, timeout_seconds: float) -> SimpleNamespace | dict[str, object]:
    state = SimpleNamespace(game_root=game_root, output_dir=output_dir, timeout_seconds=float(timeout_seconds))
    state.production_flow = []
    state.deadline = time.monotonic() + state.timeout_seconds
    try:
        if output_dir.resolve().is_relative_to(game_root.resolve()):
            return {**_base_error(state, "Visual-proof output must be outside the game root."), "read_only": False}
    except OSError:
        return {**_base_error(state, "Could not validate visual-proof output ownership."), "read_only": False}
    if os.name != "nt":
        return _base_error(state, "Embedded .NET/Vortice proof requires Windows.")
    state.pamt_path = game_root / "0009" / "0.pamt"
    if not state.pamt_path.is_file():
        return _base_error(state, f"Missing PAMT: {state.pamt_path}")
    state.entries = parse_archive_pamt(state.pamt_path)
    state.archive_sources_before = _archive_source_file_snapshot(state.entries)
    state.entries_by_path, state.entries_by_basename = _archive_entry_indexes(state.entries)
    model_path = _REAL_ARCHIVE_RIGGING_SAMPLES[0]
    state.model_entry = next(iter(state.entries_by_path.get(_archive_key(model_path), ())), None)
    if state.model_entry is None:
        return _base_error(state, f"Model entry not found: {model_path}")
    state.pac_data = _read_archive_payload(state.model_entry)
    state.source_payload_sha256 = sha256(state.pac_data).hexdigest()
    state.mesh = MeshService().load_mesh_bytes(state.pac_data, state.model_entry.path)
    editable = [
        (index, submesh)
        for index, submesh in enumerate(state.mesh.submeshes)
        if getattr(submesh, "vertices", None) and getattr(submesh, "faces", None)
    ]
    if not editable:
        return _base_error(state, "PAC parsed with no editable mesh geometry.")
    state.submesh_index, state.submesh = max(editable, key=lambda item: (len(item[1].faces), len(item[1].vertices)))
    state.original_vertex_positions = tuple(
        tuple(tuple(float(component) for component in vertex) for vertex in submesh.vertices)
        for submesh in state.mesh.submeshes
    )
    state.resolved_textures, state.material_resolution_diagnostics = _hydrate_real_archive_mesh_materials(
        state.mesh,
        state.model_entry,
        state.entries_by_path,
        state.entries_by_basename,
    )
    state.real_texture_provenance_ok = bool(state.resolved_textures) and all(
        row.get("source_kind") == "archive"
        and bool(row.get("source_sha256"))
        and isinstance(row.get("archive_provenance"), Mapping)
        for row in state.resolved_textures
    )
    state.no_synthetic_fallback = state.real_texture_provenance_ok and all(
        "checker" not in str(row.get("source_path", "")).casefold() for row in state.resolved_textures
    )
    if not state.real_texture_provenance_ok or not state.no_synthetic_fallback:
        return _base_error(state, "No production archive texture could be resolved for the real PAC mesh.")
    state.fingerprint_paths = [Path(state.model_entry.pamt_path), Path(state.model_entry.paz_file)]
    for row in state.resolved_textures:
        provenance = row.get("archive_provenance")
        if isinstance(provenance, Mapping):
            state.fingerprint_paths.extend(
                Path(str(provenance[key]))
                for key in ("pamt_path", "paz_path")
                if str(provenance.get(key, "")).strip()
            )
    state.archive_content_fingerprints_before = _archive_content_fingerprints(state.fingerprint_paths)
    state.before_capture_path = output_dir / "real_archive_dotnet_before.png"
    state.selected_before_capture_path = output_dir / "real_archive_dotnet_selected_before_drag.png"
    state.after_capture_path = output_dir / "real_archive_dotnet_after_drag.png"
    state.visual_proof_path = output_dir / "real_archive_dotnet_visual_edit_proof.png"
    return state


def _pump_until(
    state: SimpleNamespace,
    predicate: Callable[[], bool],
    timeout_seconds: float | None = None,
) -> bool:
    deadline = min(
        float(state.deadline),
        time.monotonic() + float(timeout_seconds if timeout_seconds is not None else state.timeout_seconds),
    )
    while time.monotonic() < deadline:
        state.app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    state.app.processEvents()
    return bool(predicate())


def _pump_for(state: SimpleNamespace, duration_seconds: float) -> None:
    deadline = min(float(state.deadline), time.monotonic() + max(0.0, float(duration_seconds)))
    while time.monotonic() < deadline:
        state.app.processEvents()
        time.sleep(0.005)


def _wait_protocol_event(state: SimpleNamespace, name: str, cursor: int, timeout_seconds: float | None = None) -> dict[str, object]:
    found: dict[str, object] = {}

    def locate() -> bool:
        nonlocal found
        events = tuple(state.tab.standalone_dotnet_protocol_events)
        for event in events[max(0, int(cursor)) :]:
            if str(event.get("event", "") or "").strip().lower() == name:
                found = dict(event)
                return True
        return False

    _pump_until(state, locate, timeout_seconds)
    return found


def _install_timing_probes(state: SimpleNamespace) -> None:
    state.measure_stroke_handlers = False
    state.stroke_handler_timings = []
    state.stroke_results = []
    original_handler = state.tab._handle_dotnet_stroke_event

    def timed_handler(payload: Mapping[str, object], phase: str) -> bool:
        started = time.perf_counter()
        handled = bool(original_handler(payload, phase))
        if state.measure_stroke_handlers and phase == "update":
            state.stroke_handler_timings.append(
                {"phase": phase, "handled": handled, "handler_ms": (time.perf_counter() - started) * 1000.0}
            )
        return handled

    original_apply = state.tab._apply_dotnet_result_update

    def record_result(controller: object, result: object, *, command_name: str = "") -> bool:
        applied = bool(original_apply(controller, result, command_name=command_name))
        if state.measure_stroke_handlers and command_name in {"transform", "brush"}:
            state.stroke_results.append(result)
        return applied

    original_completed = state.tab._handle_dotnet_live_stroke_completed

    def record_completed(outcome: object) -> None:
        if str(getattr(outcome, "source", "") or "") == "dotnet":
            state.stroke_results.append(getattr(outcome, "result", None))
        original_completed(outcome)

    state.tab._handle_dotnet_stroke_event = timed_handler
    state.tab._apply_dotnet_result_update = record_result
    state.tab._handle_dotnet_live_stroke_completed = record_completed


def _start_embedded_editor(
    state: SimpleNamespace,
    *,
    side_by_side_camera: bool = False,
) -> dict[str, object] | None:
    os.environ["QT_QPA_PLATFORM"] = "windows"
    from PySide6.QtCore import QSettings, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QFrame, QVBoxLayout, QWidget
    from cdmw.ui.mesh_editor import MeshEditorTab
    from cdmw.ui.mesh_editor.controller import MeshEditorController

    state.app = QApplication.instance() or QApplication(["real-archive-mesh-editor-dotnet-edit"])
    state.settings = QSettings(str(state.output_dir / "real_archive_mesh_editor_dotnet.ini"), QSettings.Format.IniFormat)
    state.settings.setFallbacksEnabled(False)
    state.settings.setValue("mesh_editor/use_embedded_dotnet_viewport", True)
    state.controller = MeshEditorController()
    state.view = state.controller.open_mesh(state.mesh, session_id="real-archive-dotnet-edit", mode="edit")
    state.tab = MeshEditorTab(settings=state.settings)
    state.builder = QWidget()
    state.builder.setObjectName("RealDotNetMeshBuilder")
    layout = QVBoxLayout(state.builder)
    layout.setContentsMargins(0, 0, 0, 0)
    state.host = QFrame(state.builder)
    state.host.setObjectName("AlignmentNativeD3D11PreviewHost")
    state.host.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
    layout.addWidget(state.host)
    state.dotnet_ready_callback = False
    state.dotnet_failed = ""
    setattr(state.builder, "_mesh_editor_embedded_controller", lambda: state.controller)
    if side_by_side_camera:
        setattr(state.builder, "_mesh_editor_embedded_reference_mesh", lambda: state.mesh)
    setattr(
        state.builder,
        "_mesh_editor_embedded_comparison_mode",
        lambda: "side_by_side" if side_by_side_camera else "replacement_only",
    )
    setattr(
        state.builder,
        "_mesh_editor_embedded_interaction_mode",
        lambda: "placement" if side_by_side_camera else "mesh_edit",
    )
    setattr(state.builder, "_mesh_editor_embedded_dotnet_ready", lambda: setattr(state, "dotnet_ready_callback", True))
    setattr(
        state.builder,
        "_mesh_editor_embedded_dotnet_failed",
        lambda reason="", diagnostics="": setattr(state, "dotnet_failed", f"{reason}: {diagnostics}".strip(": ")),
    )
    state.tab.mount_embedded_builder(state.builder)
    screen = state.app.primaryScreen().availableGeometry()
    state.tab.setGeometry(screen.x() + 24, screen.y() + 24, max(960, min(1400, screen.width() - 48)), max(640, min(900, screen.height() - 48)))
    state.tab.show()
    state.tab.raise_()
    state.tab.activateWindow()
    state.app.processEvents()
    state.qt_host_hwnd = int(state.host.winId())
    _install_timing_probes(state)
    state.heartbeat_started = time.perf_counter()
    state.heartbeat_ms = []
    state.heartbeat_timer = QTimer(state.tab)
    state.heartbeat_timer.setInterval(10)
    state.heartbeat_timer.timeout.connect(
        lambda: state.heartbeat_ms.append((time.perf_counter() - state.heartbeat_started) * 1000.0)
    )
    state.heartbeat_timer.start()
    start = getattr(state.builder, "_mesh_editor_embedded_start_dotnet", None)
    if not callable(start):
        return _base_error(state, "Production embedded .NET start callback was not installed.")
    start()
    state.protocol_ready = _wait_protocol_event(state, "protocol_ready", 0)
    state.ready_event = _wait_protocol_event(state, "ready", 0)
    state.textures_event = _wait_protocol_event(state, "textures_ready", 0)
    if not state.protocol_ready or not state.ready_event or not state.textures_event or not state.dotnet_ready_callback:
        return _base_error(state, state.dotnet_failed or "Embedded .NET editor did not report protocol, renderer, and texture readiness.")
    state.renderer = dict(state.textures_event.get("renderer", state.ready_event.get("renderer", {})) or {})
    initial_selection = state.ready_event.get("local_selection", {})
    initial_selection = initial_selection if isinstance(initial_selection, Mapping) else {}
    state.initial_part_selection_empty = bool(
        not tuple(initial_selection.get("source_indices", ()) or ())
        and int(state.ready_event.get("selected_part_index", -2)) == -1
        and int(state.ready_event.get("parts_list_selected_index", -2)) == -1
    )
    state.renderer_backend = str(state.renderer.get("backend", "") or "")
    state.viewport = dict(state.renderer.get("viewport", {}) or {})
    state.viewport_hwnd = int(state.viewport.get("hwnd", 0) or 0)
    state.form_hwnd = int(state.viewport.get("form_hwnd", 0) or 0)
    if not state.viewport_hwnd or not state.form_hwnd:
        return _base_error(state, ".NET renderer did not publish its real viewport/form HWNDs.")
    state.production_process_pid = int(state.tab.standalone_dotnet_editor_process.processId())
    state.before_capture_summary = _capture_viewport(state, state.before_capture_path)
    if not state.before_capture_summary.get("ok"):
        return _base_error(
            state,
            str(state.before_capture_summary.get("error") or "Could not capture the real .NET viewport."),
        )
    state.production_window_identity = {"form_hwnd": state.form_hwnd, "viewport_hwnd": state.viewport_hwnd}
    record_flow_step(
        state,
        "ready",
        process_pid=state.production_process_pid,
        form_hwnd=state.form_hwnd,
        viewport_hwnd=state.viewport_hwnd,
    )
    return None


def _configure_selection_and_projection(state: SimpleNamespace) -> dict[str, object] | None:
    initial_faces = tuple(range(min(12, len(state.submesh.faces))))
    state.controller.select(faces_by_submesh={state.submesh_index: initial_faces}, operation="replace")
    state.tab._send_dotnet_session_state()
    tool_cursor = len(state.tab.standalone_dotnet_protocol_events)
    state.tool_state_sent = state.tab._send_dotnet_protocol_message(
        {"event": "tool_state", "tool": "move", "target_mode": "face"}
    )
    state.tool_state_event = _wait_protocol_event(state, "tool_state_applied", tool_cursor)
    tool_selection = state.tool_state_event.get("local_selection", {})
    tool_selection = tool_selection if isinstance(tool_selection, Mapping) else {}
    state.face_selection_keeps_part_unselected = bool(
        not tuple(tool_selection.get("source_indices", ()) or ())
        and int(state.tool_state_event.get("selected_part_index", -2)) == -1
        and int(state.tool_state_event.get("parts_list_selected_index", -2)) == -1
    )
    width = int(state.viewport.get("width", 0) or 0)
    height = int(state.viewport.get("height", 0) or 0)
    client_x = int(state.viewport.get("client_x", 0) or 0)
    client_y = int(state.viewport.get("client_y", 0) or 0)
    probe = (client_x + max(1, width // 2), client_y + max(1, height // 2))
    cursor = len(state.tab.standalone_dotnet_protocol_events)
    state.probe_down_sent = _send_mouse_message(state.viewport_hwnd, _WM_LBUTTONDOWN, *probe, wparam=_MK_LBUTTON)
    state.probe_started = _wait_protocol_event(state, "stroke_begin", cursor)
    cursor = len(state.tab.standalone_dotnet_protocol_events)
    state.probe_up_sent = _send_mouse_message(state.viewport_hwnd, _WM_LBUTTONUP, *probe)
    state.probe_finished = _wait_protocol_event(state, "stroke_end", cursor)
    drag = state.probe_started.get("screen_drag", {}) if isinstance(state.probe_started, Mapping) else {}
    state.projection_drag = dict(drag) if isinstance(drag, Mapping) else {}
    matrix = tuple(state.projection_drag.get("world_view_projection", ()) or ())
    selected_faces = _projected_face_cluster_for_drag(
        state.submesh,
        matrix,
        viewport_x=0.0,
        viewport_y=0.0,
        viewport_width=float(width),
        viewport_height=float(height),
    ) if matrix else initial_faces
    state.selected_faces = selected_faces or initial_faces
    state.face_vertices = sorted(
        {vertex for face_index in state.selected_faces for vertex in state.submesh.faces[int(face_index)]}
    )
    state.select_result = state.controller.select(
        faces_by_submesh={state.submesh_index: state.selected_faces}, operation="replace"
    )
    state.tab._send_dotnet_session_state()
    _pump_for(state, 0.15)
    current = state.controller.working_mesh(clone=False)
    state.before_vertices = [tuple(float(value) for value in current.submeshes[state.submesh_index].vertices[index]) for index in state.face_vertices]
    state.selected_center = tuple(
        sum(vertex[axis] for vertex in state.before_vertices) / len(state.before_vertices) for axis in range(3)
    )
    state.projected_center = _project_world_to_screen(
        matrix,
        state.selected_center,
        viewport_x=0.0,
        viewport_y=0.0,
        viewport_width=float(width),
        viewport_height=float(height),
    ) if matrix else None
    state.selected_before_capture_summary = _capture_viewport(state, state.selected_before_capture_path)
    if not state.tool_state_sent or not state.tool_state_event or state.projected_center is None:
        return _base_error(state, "Could not configure the production .NET Move tool and projected face selection.")
    return None


def _drive_viewport_stroke(state: SimpleNamespace) -> dict[str, object] | None:
    return drive_viewport_stroke(
        state,
        base_error=_base_error,
        pump_for=_pump_for,
        pump_until=_pump_until,
        wait_protocol_event=_wait_protocol_event,
        capture_viewport=_capture_viewport,
    )


def _record_stroke_geometry_evidence(state: SimpleNamespace) -> None:
    state.after_mesh = state.controller.working_mesh(clone=True)
    state.after_vertices = [
        tuple(float(value) for value in state.after_mesh.submeshes[state.submesh_index].vertices[index])
        for index in state.face_vertices
    ]
    state.changed_vertex_keys = {
        (submesh_index, vertex_index)
        for submesh_index, submesh in enumerate(state.after_mesh.submeshes)
        for vertex_index, vertex in enumerate(submesh.vertices)
        if any(
            abs(float(vertex[axis]) - state.original_vertex_positions[submesh_index][vertex_index][axis]) > 1e-8
            for axis in range(3)
        )
    }
    state.selected_vertex_keys = {(state.submesh_index, index) for index in state.face_vertices}
    state.changed_only_selected_geometry = bool(state.changed_vertex_keys) and (
        state.changed_vertex_keys <= state.selected_vertex_keys
    )


def _result_gates(state: SimpleNamespace) -> dict[str, bool]:
    renderer_texture_ok = bool(
        int(state.renderer.get("resolved_texture_references", 0) or 0) > 0
        and int(state.renderer.get("existing_texture_files", 0) or 0) > 0
        and int(state.renderer.get("decoded_texture_resources", 0) or 0) > 0
        and int(state.renderer.get("texture_load_failures", 0) or 0) == 0
    )
    return {
        **state.resident_material_gates,
        **state.material_parameter_gates,
        **production_flow_gates(state),
        "real_pac_geometry_display_modes": bool(
            getattr(state, "geometry_display_evidence", {}).get("ok")
        ),
        "real_pac_builder_presentation": bool(
            getattr(state, "builder_presentation_evidence", {}).get("ok")
        ),
        "renderer_backend_ok": state.renderer_backend == _DOTNET_RENDERER_BACKEND,
        "renderer_gpu_backed": state.renderer.get("gpu_backed") is True,
        "edit_backend_ok": native_mesh_core_available() and not state.fallback_counts,
        "protocol_ready": bool(state.protocol_ready),
        "tool_state_applied": bool(state.tool_state_event),
        "part_selection_optional": bool(
            state.initial_part_selection_empty and state.face_selection_keeps_part_unselected
        ),
        "real_texture_provenance": bool(state.real_texture_provenance_ok),
        "real_textures_bound_and_decoded": renderer_texture_ok,
        "no_synthetic_fallback": bool(state.no_synthetic_fallback and renderer_texture_ok),
        "selected_geometry_only": bool(state.changed_only_selected_geometry),
        "selected_projection_tracks_cursor": bool(state.projected_drag_tracks_cursor),
        "native_window_stationary": bool(
            state.form_rect_before
            and state.form_rect_before == state.form_rect_after
            and state.viewport_rect_before == state.viewport_rect_after
        ),
        "live_stroke_frame_budget_ok": bool(
            state.stroke_handler_timings and state.handler_p95_ms < 1000.0 / 60.0
        ),
        "heartbeat_ok": bool(len(state.heartbeat_gaps) >= 2 and state.max_heartbeat_gap_ms < 200.0),
        "revision_acknowledged": bool(
            int(state.update_queue_metrics.get("active_revision", 0) or 0) == 0
            and int(state.update_queue_metrics.get("stale_acknowledgements", 0) or 0) == 0
        ),
        "captures_ok": bool(
            state.before_capture_summary.get("ok")
            and state.selected_before_capture_summary.get("ok")
            and state.after_capture_summary.get("ok")
            and state.visual_proof_summary.get("ok")
        ),
        "deterministic_offscreen_icon_capture": bool(
            getattr(state, "offscreen_capture_evidence", {}).get("ok")
        ),
        "source_archives_unchanged": bool(
            state.archive_sources_unchanged
            and state.archive_source_content_unchanged
            and state.source_payload_unchanged
        ),
    }


def _part_selection_evidence(state: SimpleNamespace) -> dict[str, bool]:
    return {
        "initially_empty": state.initial_part_selection_empty,
        "face_selection_keeps_part_unselected": state.face_selection_keeps_part_unselected,
    }


def _finish_result(state: SimpleNamespace) -> dict[str, object]:
    state.after_center = tuple(sum(vertex[axis] for vertex in state.after_vertices) / len(state.after_vertices) for axis in range(3))
    matrix = tuple(state.projection_drag.get("world_view_projection", ()) or ())
    state.projected_after_center = _project_world_to_screen(
        matrix,
        state.after_center,
        viewport_x=0.0,
        viewport_y=0.0,
        viewport_width=float(state.viewport.get("width", 0) or 0),
        viewport_height=float(state.viewport.get("height", 0) or 0),
    )
    projected_delta = (
        state.projected_after_center[0] - state.projected_center[0],
        state.projected_after_center[1] - state.projected_center[1],
    )
    expected_delta = (
        state.mouse_drag_end[0] - state.mouse_drag_start[0],
        state.mouse_drag_end[1] - state.mouse_drag_start[1],
    )
    state.projected_screen_error = math.hypot(projected_delta[0] - expected_delta[0], projected_delta[1] - expected_delta[1])
    state.projected_drag_tracks_cursor = state.projected_screen_error <= max(8.0, math.hypot(*expected_delta) * 0.35)
    state.visual_proof_summary = _write_real_archive_visual_edit_proof(
        state.selected_before_capture_path,
        state.after_capture_path,
        state.visual_proof_path,
        before_center=state.projected_center,
        after_center=state.projected_after_center,
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
        "read_only": gates["source_archives_unchanged"],
        "backend": "dotnet",
        "renderer_backend": state.renderer_backend,
        "edit_backend": NATIVE_MESH_CORE_BACKEND_ID if gates["edit_backend_ok"] else "",
        "workflow": "Ready -> select -> transform -> scalar -> two linked texture strokes -> committed DDS assignment -> UV edit -> duplicate/delete -> undo/redo -> coherent editable export -> full output reparse",
        "game_root": str(state.game_root),
        "pamt_path": str(state.pamt_path),
        "model_path": state.model_entry.path,
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
        "changed_vertex_count": len(state.changed_vertex_keys),
        "changed_only_selected_geometry": state.changed_only_selected_geometry,
        "selected_projected_screen_center": list(state.projected_center),
        "selected_projected_after_screen_center": list(state.projected_after_center),
        "selected_projected_screen_delta": list(projected_delta),
        "selected_projected_screen_error": state.projected_screen_error,
        "mouse_drag_start": list(state.mouse_drag_start),
        "mouse_drag_points": [list(point) for point in state.mouse_drag_points],
        "mouse_drag_end": list(state.mouse_drag_end),
        "mouse_input_backend": "win32_physical_cursor",
        "input_window_activated": bool(getattr(state, "input_window_activated", False)),
        "physical_viewport_origin": [
            int(state.viewport_rect_before[0]),
            int(state.viewport_rect_before[1]),
        ] if state.viewport_rect_before else None,
        "stroke_update_count": len(state.stroke_updates),
        "stroke_handler_timings": state.stroke_handler_timings,
        "stroke_handler_timing_summary": state.handler_summary,
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
        "gates": gates,
    }


def run_real_archive_mesh_editor_dotnet_edit_smoke(
    game_root: Path,
    output_dir: Path,
    *,
    timeout_seconds: float = 45.0,
) -> dict[str, object]:
    clear_native_mesh_core_fallback_counts()
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared = _prepare_real_asset(Path(game_root), Path(output_dir), timeout_seconds)
    if isinstance(prepared, dict):
        return prepared
    state = prepared
    state.tab = state.controller = state.heartbeat_timer = state.process = None
    try:
        error = _start_embedded_editor(state)
        if error is not None:
            return error
        state.offscreen_capture_evidence = exercise_deterministic_offscreen_capture(
            state,
            pump_until=_pump_until,
            wait_protocol_event=_wait_protocol_event,
        )
        if not state.offscreen_capture_evidence.get("ok"):
            return _base_error(state, "Deterministic production offscreen icon capture failed.")
        state.process = state.tab.standalone_dotnet_editor_process
        error = exercise_resident_material_update(
            state, base_error=_base_error, pump_until=_pump_until, wait_protocol_event=_wait_protocol_event
        )
        if error is not None:
            return error
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
        return _finish_result(state)
    except Exception as exc:
        return _base_error(state, f"{type(exc).__name__}: {exc}")
    finally:
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
