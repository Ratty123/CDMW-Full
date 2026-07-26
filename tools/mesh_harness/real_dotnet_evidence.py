"""Asset preparation, pump/protocol waits and result-gate evidence shaping."""

from __future__ import annotations

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
from tools.mesh_harness.performance_contract import (
    PERFORMANCE_HARNESS_EVIDENCE_SCHEMA,
    PerformanceInteraction,
    PerformanceRequest,
    begin_performance_capture,
    finish_performance_capture,
    run_performance_interaction_schedule,
    service_performance_heartbeat,
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
        "status_messages": [dict(entry) for entry in tuple(getattr(state, "status_messages", ()) or ())],
        "dotnet_stderr_tail": str(
            getattr(getattr(state, "tab", None), "standalone_dotnet_stderr_tail", "") or ""
        )[-4000:],
        "performance_capture": getattr(state, "performance_capture_evidence", {}),
        "archive_content_fingerprints_before": before,
        "archive_content_fingerprints_after": after,
        "archive_source_content_unchanged": content_unchanged,
        "archive_sources_unchanged": archives_unchanged,
        "source_payload_unchanged": payload_unchanged,
        "source_archives_unchanged": archives_unchanged,
        "source_archive_check": "not_applicable_no_source_archives" if no_source_archives else "verified" if archives_unchanged else "unverified",
    }

def _has_real_archive_texture_provenance(row: Mapping[str, object]) -> bool:
    provenance = row.get("archive_provenance")
    if not isinstance(provenance, Mapping):
        return False
    return bool(
        str(row.get("source_sha256", "")).strip()
        and str(row.get("archive_path", "")).strip()
        and str(provenance.get("pamt_path", "")).strip()
        and str(provenance.get("paz_path", "")).strip()
        and str(provenance.get("virtual_path", "")).strip()
    )

def _prepare_real_asset(
    game_root: Path,
    output_dir: Path,
    timeout_seconds: float,
    *,
    model_path: str | None = None,
) -> SimpleNamespace | dict[str, object]:
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
    selected_model_path = str(model_path or _REAL_ARCHIVE_RIGGING_SAMPLES[0]).strip()
    state.model_entry = next(
        iter(state.entries_by_path.get(_archive_key(selected_model_path), ())),
        None,
    )
    if state.model_entry is None:
        return _base_error(state, f"Model entry not found: {selected_model_path}")
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
        _has_real_archive_texture_provenance(row) for row in state.resolved_textures
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
        service_performance_heartbeat(state)
        if predicate():
            return True
        time.sleep(0.005)
    state.app.processEvents()
    service_performance_heartbeat(state)
    return bool(predicate())

def _pump_for(state: SimpleNamespace, duration_seconds: float) -> None:
    deadline = min(float(state.deadline), time.monotonic() + max(0.0, float(duration_seconds)))
    while time.monotonic() < deadline:
        state.app.processEvents()
        service_performance_heartbeat(state)
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
    gates = {
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
    if getattr(state, "performance_request", None) is not None:
        gates["performance_capture"] = bool(
            getattr(state, "performance_capture_evidence", {}).get("ok")
        )
    return gates

def _part_selection_evidence(state: SimpleNamespace) -> dict[str, bool]:
    return {
        "initially_empty": state.initial_part_selection_empty,
        "face_selection_keeps_part_unselected": state.face_selection_keeps_part_unselected,
    }

__all__ = ['_base_error', '_drive_viewport_stroke', '_has_real_archive_texture_provenance', '_part_selection_evidence', '_prepare_real_asset', '_pump_for', '_pump_until', '_record_stroke_geometry_evidence', '_result_gates', '_revision_ack_tail', '_wait_protocol_event']
