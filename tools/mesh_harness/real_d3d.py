from __future__ import annotations
from types import SimpleNamespace
from tools.mesh_harness.phase_support import PhaseResult
from collections.abc import Mapping
from cdmw.ui.mesh_editor.controller import MeshEditorController
from pathlib import Path
from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts
from cdmw.rendering.native_d3d11_host import find_native_d3d11_host
import math
from cdmw.ui.mesh_editor.native_preview_runtime import mesh_editor_write_native_preview_package
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.modding.mesh_native_core import native_mesh_core_fallback_counts
from cdmw.modding.mesh_native_core import native_mesh_core_fallback_events
import os
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.modding.mesh_parser import parse_mesh
from hashlib import sha256
import subprocess
import time
from tools.mesh_harness.constants import _MK_LBUTTON, _REAL_ARCHIVE_RIGGING_SAMPLES, _WM_LBUTTONDOWN, _WM_LBUTTONUP, _WM_MOUSEMOVE
from tools.mesh_harness.archive_provenance import _archive_content_fingerprints, _archive_entry_provenance, _archive_source_file_snapshot, _resolve_real_archive_mesh_textures
from tools.mesh_harness.native_projection import _finite_float, _payload_frame_count, _project_world_to_screen, _projected_face_cluster_for_drag, _timing_summary
from tools.mesh_harness.native_protocol import _NativeD3D11HarnessHost, _close_process, _host_window_rect, _place_host_window_on_screen1, _send_json_command, _send_mouse_message, _wait_for_host_window, _wait_for_status
from tools.mesh_harness.png_evidence import _png_capture_summary, _write_real_archive_visual_edit_proof
from tools.mesh_harness.real_common import _archive_entry_indexes, _archive_key, _read_archive_payload
from tools.mesh_harness.service_summary import _command_summary

def _real_d3d_phase_1(state: SimpleNamespace) -> PhaseResult | None:
    state.controller = MeshEditorController()
    state.loaded = _wait_for_status(state.status_file, {'loaded', 'resources_loaded'}, state.timeout_seconds)
    state.loaded_ok = state.loaded.get('event') in {'loaded', 'resources_loaded'}
    state.hwnd = _wait_for_host_window(state.process.pid, state.timeout_seconds)
    _place_host_window_on_screen1(state.hwnd)
    state.status_file.unlink(missing_ok=True)
    if not state.loaded_ok or not state.hwnd:
        return PhaseResult({'ok': False, 'read_only': True, 'native_core_available': True, 'model_path': state.model_entry.path, 'error': 'D3D11 host did not load real PAC preview'})
    _send_json_command(state.hwnd, {'command': 'capture_frame', 'path': str(state.before_capture_path)})
    state.before_capture_event = _wait_for_status(state.status_file, {'frame_capture'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.mesh_editor import MeshEditorTab
    state.app = QApplication.instance() or QApplication(['real-archive-mesh-editor-d3d11-edit'])
    state.settings = QSettings(str(state.output_dir / 'real_archive_mesh_editor_d3d11_edit.ini'), QSettings.Format.IniFormat)
    state.settings.setFallbacksEnabled(False)
    state.tab = MeshEditorTab(settings=state.settings)
    state.edit_host = _NativeD3D11HarnessHost(state.hwnd, status_file=state.status_file, timeout_seconds=state.timeout_seconds)
    state.tab.set_native_preview_host(state.edit_host)
    state.tab.open_mesh_session(state.mesh, target_entry=state.model_entry, session_id='real-archive-d3d11-edit', mode='edit')
    state.controller = state.tab.standalone_controller
    if state.controller is None:
        return PhaseResult({'ok': False, 'read_only': True, 'native_core_available': True, 'model_path': state.model_entry.path, 'error': 'MeshEditorTab controller missing'})
    state.status_file.unlink(missing_ok=True)
    state.tab.set_active_tool_state(mode='edit', active_tool_key='transform_move')
    state.mesh_edit_state_event = _wait_for_status(state.status_file, {'mesh_edit_state'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.projection_probe_start = (700, 360) if state.side_by_side else (440, 360)
    state.projection_probe_down_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONDOWN, state.projection_probe_start[0], state.projection_probe_start[1], wparam=_MK_LBUTTON)
    state.projection_probe_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_started'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.projection_payload = state.projection_probe_status.get('payload', {})
    state.projection_drag = dict(state.projection_payload.get('screen_drag', {})) if isinstance(state.projection_payload, Mapping) and isinstance(state.projection_payload.get('screen_drag'), Mapping) else {}
    state.projection_probe_up_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONUP, state.projection_probe_start[0], state.projection_probe_start[1])
    state.projection_probe_finished_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_previewed', 'mesh_edit_stroke_finished'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.projected_center = None
    if state.projection_drag:
        state.viewport_x = float(state.projection_drag.get('viewport_x', 0.0) or 0.0)
        state.viewport_y = float(state.projection_drag.get('viewport_y', 0.0) or 0.0)
        state.viewport_width = float(state.projection_drag.get('viewport_width', 0.0) or 0.0)
        state.viewport_height = float(state.projection_drag.get('viewport_height', 0.0) or 0.0)
        state.selected_faces = _projected_face_cluster_for_drag(state.submesh, tuple(state.projection_drag.get('world_view_projection') or ()), viewport_x=state.viewport_x, viewport_y=state.viewport_y, viewport_width=state.viewport_width, viewport_height=state.viewport_height)
    else:
        state.viewport_x = state.viewport_y = state.viewport_width = state.viewport_height = 0.0
        state.selected_faces = tuple(range(min(12, len(state.submesh.faces))))
    state.face_vertices = sorted({int(vertex_index) for face_index in state.selected_faces for vertex_index in state.submesh.faces[face_index]})
    state.before_vertices = [tuple((float(component) for component in state.mesh.submeshes[state.submesh_index].vertices[index])) for index in state.face_vertices]
    state.selected_center = tuple((sum((vertex[axis] for vertex in state.before_vertices)) / len(state.before_vertices) for axis in range(3))) if state.before_vertices else (0.0, 0.0, 0.0)
    if state.projection_drag:
        state.projected_center = _project_world_to_screen(tuple(state.projection_drag.get('world_view_projection') or ()), state.selected_center, viewport_x=state.viewport_x, viewport_y=state.viewport_y, viewport_width=state.viewport_width, viewport_height=state.viewport_height)
    state.selected_projection_ok = state.projected_center is not None
    state.select_result = state.controller.select(faces_by_submesh={state.submesh_index: state.selected_faces}, operation='replace')
    state.tab.update_editor_session_state(state.controller.session_view(), active_selection_mode=state.controller.active_selection_mode)
    state.select_update = state.controller.native_update_for_result(state.select_result)
    state.select_update_ok = state.tab._apply_standalone_native_update(state.select_update)
    state.status_file.unlink(missing_ok=True)
    _send_json_command(state.hwnd, {'command': 'capture_frame', 'path': str(state.selected_before_capture_path)})
    state.selected_before_capture_event = _wait_for_status(state.status_file, {'frame_capture'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    if state.selected_projection_ok:
        state.mouse_drag_start = (int(round(min(max(state.projected_center[0], state.viewport_x), state.viewport_x + max(state.viewport_width - 1.0, 0.0)))), int(round(min(max(state.projected_center[1], state.viewport_y), state.viewport_y + max(state.viewport_height - 1.0, 0.0)))))
    else:
        state.mouse_drag_start = state.projection_probe_start
    state.mouse_drag_points = tuple(((state.mouse_drag_start[0] + offset, state.mouse_drag_start[1]) for offset in range(1, 41)))
    state.mouse_drag_end = state.mouse_drag_points[-1]
    state.heartbeat_started = time.perf_counter()
    state.heartbeat_timer = QTimer()
    state.heartbeat_timer.setInterval(10)
    state.heartbeat_timer.timeout.connect(lambda: state.heartbeat_ms.append((time.perf_counter() - state.heartbeat_started) * 1000.0))
    state.heartbeat_timer.start()
    state.app.processEvents()
    state.native_window_rect_before = _host_window_rect(state.hwnd)
    state.action_started = time.perf_counter()
    state.mouse_down_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONDOWN, state.mouse_drag_start[0], state.mouse_drag_start[1], wparam=_MK_LBUTTON)
    state.stroke_started_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_started'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.stroke_started_handled = state.tab._handle_standalone_native_mesh_edit_stroke_started(state.stroke_started_status.get('payload', {}))
    state.mouse_move_sent = True
    state.stroke_preview_statuses: list[dict[str, object]] = []
    state.stroke_preview_handled = True
    state.edit_update_events: list[dict[str, object]] = []
    state.live_stroke_timings: list[dict[str, object]] = []
    state.d3d11_update_ms = 0.0
    state.previous_frame_count = _payload_frame_count(state.stroke_started_status.get('payload', {}))
    for state.move_index, (state.move_x, state.move_y) in enumerate(state.mouse_drag_points):
        state.mouse_move_sent = bool(state.mouse_move_sent and _send_mouse_message(state.hwnd, _WM_MOUSEMOVE, state.move_x, state.move_y, wparam=_MK_LBUTTON))
        state.preview_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_previewed'}, state.timeout_seconds)
        state.status_file.unlink(missing_ok=True)
        state.stroke_preview_statuses.append(state.preview_status)
        state.send_metric_start = len(state.edit_host.send_metrics)
        state.handler_started = time.perf_counter()
        state.preview_handled = state.tab._handle_standalone_native_mesh_edit_stroke_previewed(state.preview_status.get('payload', {}))
        state.handler_ms = max(0.0, (time.perf_counter() - state.handler_started) * 1000.0)
        state.stroke_preview_handled = bool(state.stroke_preview_handled and state.preview_handled)
        state.event_wait_started = time.perf_counter()
        state.update_event = _wait_for_status(state.status_file, {'mesh_edit_vertices_updated', 'mesh_edit_triangles_replaced'}, state.timeout_seconds) if state.preview_handled else {}
        state.event_wait_ms = max(0.0, (time.perf_counter() - state.event_wait_started) * 1000.0) if state.preview_handled else 0.0
        state.d3d11_update_ms += state.handler_ms + state.event_wait_ms
        state.status_file.unlink(missing_ok=True)
        state.edit_update_events.append(state.update_event)
        state.payload = state.preview_status.get('payload', {})
        state.frame_count = _payload_frame_count(state.payload)
        state.metrics = dict(state.tab.standalone_last_action_metrics)
        state.update_send_metrics = state.edit_host.send_metrics[state.send_metric_start:]
        state.live_stroke_timings.append({'move_index': state.move_index, 'handled': bool(state.preview_handled), 'frame_count': state.frame_count, 'frame_delta': max(0, state.frame_count - state.previous_frame_count) if state.previous_frame_count >= 0 and state.frame_count >= 0 else -1, 'handler_ms': state.handler_ms, 'event_wait_ms': state.event_wait_ms, 'total_update_ms': state.handler_ms + state.event_wait_ms, 'service_total_ms': _finite_float(state.metrics.get('service_total_ms')), 'service_dispatch_ms': _finite_float(state.metrics.get('service_dispatch_ms')), 'native_apply_roundtrip_ms': _finite_float(state.metrics.get('native_apply_roundtrip_ms')), 'native_apply_overhead_ms': _finite_float(state.metrics.get('native_apply_overhead_ms')), 'cpp_ms': _finite_float(state.metrics.get('cpp_ms')), 'io_serialization_ms': _finite_float(state.metrics.get('io_serialization_ms')), 'python_apply_ms': _finite_float(state.metrics.get('python_apply_ms')), 'd3d11_send_ms': sum((_finite_float(item.get('send_ms')) for item in state.update_send_metrics)), 'd3d11_payload_bytes': sum((int(item.get('payload_bytes', 0) or 0) for item in state.update_send_metrics)), 'd3d11_send_count': len(state.update_send_metrics)})
        state.previous_frame_count = state.frame_count if state.frame_count >= 0 else state.previous_frame_count
    state.stroke_preview_status = state.stroke_preview_statuses[-1] if state.stroke_preview_statuses else {}
    state.edit_update_event = state.edit_update_events[-1] if state.edit_update_events else {}
    state.edit_result = state.tab.standalone_last_action_result
    state.mouse_up_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONUP, state.mouse_drag_end[0], state.mouse_drag_end[1])
    state.native_window_rect_after = _host_window_rect(state.hwnd)
    state.stroke_finished_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_finished'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.stroke_finished_handler_started = time.perf_counter()
    state.stroke_finished_handled = state.tab._handle_standalone_native_mesh_edit_stroke_finished(state.stroke_finished_status.get('payload', {}))
    state.stroke_finished_handler_ms = (time.perf_counter() - state.stroke_finished_handler_started) * 1000.0
    state.stroke_idle_deadline = time.monotonic() + state.timeout_seconds
    state.stroke_dispatcher = state.tab.standalone_live_stroke_dispatcher
    while state.stroke_dispatcher is not None and (not state.stroke_dispatcher.wait_idle(0.0)) and (time.monotonic() < state.stroke_idle_deadline):
        state.app.processEvents()
        time.sleep(0.005)
    state.app.processEvents()
    state.stroke_dispatch_idle = bool(state.stroke_dispatcher is not None and state.stroke_dispatcher.wait_idle(0.0))
    state.stroke_dispatch_metrics = state.stroke_dispatcher.metrics() if state.stroke_dispatcher is not None else {}
    state.action_elapsed_ms = (time.perf_counter() - state.action_started) * 1000.0
    state.app.processEvents()
    state.heartbeat_elapsed_ms = (time.perf_counter() - state.heartbeat_started) * 1000.0
    state.heartbeat_timer.stop()
    state.heartbeat_points = [0.0, *state.heartbeat_ms, state.heartbeat_elapsed_ms]
    state.heartbeat_gaps = [state.heartbeat_points[index] - state.heartbeat_points[index - 1] for index in range(1, len(state.heartbeat_points))]
    state.max_heartbeat_gap_ms = max(state.heartbeat_gaps, default=state.heartbeat_elapsed_ms)
    state.heartbeat_ok = bool(len(state.heartbeat_ms) >= 2 and state.max_heartbeat_gap_ms < 200.0)
    _send_json_command(state.hwnd, {'command': 'capture_frame', 'path': str(state.after_capture_path)})
    state.after_capture_event = _wait_for_status(state.status_file, {'frame_capture'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.native_window_stationary_ok = bool(state.native_window_rect_before and state.native_window_rect_before == state.native_window_rect_after)
    return None

def _real_d3d_phase_2(state: SimpleNamespace) -> PhaseResult | None:
    state.after_mesh = state.controller.working_mesh(clone=True)
    state.after_vertices = [tuple((float(component) for component in state.after_mesh.submeshes[state.submesh_index].vertices[index])) for index in state.face_vertices]
    state.after_selected_center = tuple((sum((vertex[axis] for vertex in state.after_vertices)) / len(state.after_vertices) for axis in range(3))) if state.after_vertices else (0.0, 0.0, 0.0)
    state.stroke_preview_payload = state.stroke_preview_status.get('payload', {})
    state.stroke_preview_drag = dict(state.stroke_preview_payload.get('screen_drag', {})) if isinstance(state.stroke_preview_payload, Mapping) and isinstance(state.stroke_preview_payload.get('screen_drag'), Mapping) else {}
    state.projection_check_drag = state.stroke_preview_drag or state.projection_drag
    state.projected_after_center = _project_world_to_screen(tuple(state.projection_check_drag.get('world_view_projection') or ()), state.after_selected_center, viewport_x=float(state.projection_check_drag.get('viewport_x', 0.0) or 0.0), viewport_y=float(state.projection_check_drag.get('viewport_y', 0.0) or 0.0), viewport_width=float(state.projection_check_drag.get('viewport_width', 0.0) or 0.0), viewport_height=float(state.projection_check_drag.get('viewport_height', 0.0) or 0.0)) if state.projection_check_drag else None
    state.projected_screen_delta = (state.projected_after_center[0] - state.projected_center[0], state.projected_after_center[1] - state.projected_center[1]) if state.projected_center is not None and state.projected_after_center is not None else None
    state.expected_screen_delta = (state.mouse_drag_end[0] - state.mouse_drag_start[0], state.mouse_drag_end[1] - state.mouse_drag_start[1])
    state.projected_screen_error = math.hypot(state.projected_screen_delta[0] - state.expected_screen_delta[0], state.projected_screen_delta[1] - state.expected_screen_delta[1]) if state.projected_screen_delta is not None else float('inf')
    state.projected_drag_tracks_cursor = bool(state.projected_screen_delta is not None and state.projected_screen_error <= max(8.0, math.hypot(state.expected_screen_delta[0], state.expected_screen_delta[1]) * 0.35))
    state.replacement_viewport_offset_ok = not state.side_by_side or state.viewport_x > 1.0
    state.drag_points_in_replacement_viewport = all((state.viewport_x <= point[0] <= state.viewport_x + max(state.viewport_width - 1.0, 0.0) and state.viewport_y <= point[1] <= state.viewport_y + max(state.viewport_height - 1.0, 0.0) for point in (state.mouse_drag_start, *state.mouse_drag_points, state.mouse_drag_end)))
    state.moved = any((any((abs(after[axis] - before[axis]) > 1e-05 for axis in range(3))) for before, after in zip(state.before_vertices, state.after_vertices)))
    state.changed_vertex_keys = {(candidate_index, vertex_index) for candidate_index, candidate in enumerate(state.after_mesh.submeshes) for vertex_index, vertex in enumerate(candidate.vertices) if candidate_index >= len(state.original_vertex_positions) or vertex_index >= len(state.original_vertex_positions[candidate_index]) or any((abs(float(vertex[axis]) - state.original_vertex_positions[candidate_index][vertex_index][axis]) > 1e-08 for axis in range(min(3, len(vertex)))))}
    state.selected_vertex_keys = {(state.submesh_index, int(vertex_index)) for vertex_index in state.face_vertices}
    state.changed_only_selected_geometry = bool(state.changed_vertex_keys and state.changed_vertex_keys.issubset(state.selected_vertex_keys))
    state.max_selected_vertex_delta = max((math.sqrt(sum(((after[axis] - before[axis]) * (after[axis] - before[axis]) for axis in range(3)))) for before, after in zip(state.before_vertices, state.after_vertices)), default=0.0)
    state.fallback_counts = native_mesh_core_fallback_counts()
    state.before_capture_summary = _png_capture_summary(state.before_capture_path) if state.before_capture_path.is_file() else {'ok': False, 'error': 'before capture missing'}
    state.selected_before_capture_summary = _png_capture_summary(state.selected_before_capture_path) if state.selected_before_capture_path.is_file() else {'ok': False, 'error': 'selected-before capture missing'}
    state.after_capture_summary = _png_capture_summary(state.after_capture_path) if state.after_capture_path.is_file() else {'ok': False, 'error': 'after capture missing'}
    state.visual_proof_summary = _write_real_archive_visual_edit_proof(state.selected_before_capture_path, state.after_capture_path, state.visual_proof_path, before_center=state.projected_center, after_center=state.projected_after_center)
    state.changed_vertices_raw = state.edit_result.changed_vertices_by_submesh if state.edit_result is not None else ()
    if isinstance(state.changed_vertices_raw, Mapping):
        state.changed_vertex_groups = tuple(state.changed_vertices_raw.values())
    else:
        state.changed_vertex_groups = tuple((values for _submesh, values in tuple(state.changed_vertices_raw or ())))
    state.edit_changed_vertices = 0
    for state.values in state.changed_vertex_groups:
        if isinstance(state.values, Mapping):
            state.descriptor = state.values.get('changed_vertices_binary') or state.values.get('source_vertex_indices_binary')
            if isinstance(state.descriptor, Mapping):
                state.edit_changed_vertices += int(state.descriptor.get('count', 0) or 0)
            else:
                state.edit_changed_vertices += int(state.values.get('source_vertex_count', 0) or 0)
        else:
            state.edit_changed_vertices += len(tuple(state.values or ()))
    state.frame_budget_ms = 1000.0 / 60.0
    state.live_stroke_timing_summary = {'frame_budget_ms': state.frame_budget_ms, 'handler': _timing_summary(state.live_stroke_timings, 'handler_ms'), 'event_wait': _timing_summary(state.live_stroke_timings, 'event_wait_ms'), 'total_update': _timing_summary(state.live_stroke_timings, 'total_update_ms'), 'native_apply_roundtrip': _timing_summary(state.live_stroke_timings, 'native_apply_roundtrip_ms'), 'cpp': _timing_summary(state.live_stroke_timings, 'cpp_ms'), 'io_serialization': _timing_summary(state.live_stroke_timings, 'io_serialization_ms'), 'd3d11_send': _timing_summary(state.live_stroke_timings, 'd3d11_send_ms'), 'max_payload_bytes': max((int(item.get('d3d11_payload_bytes', 0) or 0) for item in state.live_stroke_timings), default=0)}
    state.live_stroke_frame_budget_ok = bool(state.live_stroke_timings and all((bool(item.get('handled')) for item in state.live_stroke_timings)) and all((_finite_float(item.get('handler_ms')) <= state.frame_budget_ms for item in state.live_stroke_timings)))
    state.archive_sources_after = _archive_source_file_snapshot(state.entries)
    state.archive_sources_metadata_unchanged = state.archive_sources_before == state.archive_sources_after
    state.archive_content_fingerprints_after = _archive_content_fingerprints(state.fingerprint_paths)
    state.archive_source_content_unchanged = state.archive_content_fingerprints_before == state.archive_content_fingerprints_after
    state.archive_sources_unchanged = bool(state.archive_sources_metadata_unchanged and state.archive_source_content_unchanged)
    try:
        state.source_payload_unchanged = sha256(_read_archive_payload(state.model_entry)).hexdigest() == state.source_payload_sha256
    except Exception:
        state.source_payload_unchanged = False
    state.read_only_ok = bool(state.archive_sources_unchanged and state.source_payload_unchanged)
    state.fallback_gate_ok = not state.fallback_counts
    state.ok = bool(state.select_result.ok and state.select_update_ok and (state.edit_result is not None) and state.edit_result.ok and state.projection_probe_down_sent and state.projection_probe_up_sent and (state.projection_probe_status.get('event') == 'mesh_edit_stroke_started') and (state.projection_probe_finished_status.get('event') in {'mesh_edit_stroke_previewed', 'mesh_edit_stroke_finished'}) and state.selected_projection_ok and state.mouse_down_sent and state.mouse_move_sent and state.mouse_up_sent and (state.stroke_started_status.get('event') == 'mesh_edit_stroke_started') and (len(state.stroke_preview_statuses) == len(state.mouse_drag_points)) and all((status.get('event') == 'mesh_edit_stroke_previewed' for status in state.stroke_preview_statuses)) and (state.stroke_finished_status.get('event') == 'mesh_edit_stroke_finished') and state.stroke_started_handled and state.stroke_preview_handled and state.stroke_finished_handled and state.stroke_dispatch_idle and all((event.get('event') == 'mesh_edit_vertices_updated' for event in state.edit_update_events)) and all((int(event.get('changed_vertices', 0) or 0) > 0 for event in state.edit_update_events)) and state.moved and state.changed_only_selected_geometry and (0.01 <= state.max_selected_vertex_delta <= 0.25) and state.projected_drag_tracks_cursor and state.replacement_viewport_offset_ok and state.drag_points_in_replacement_viewport and state.before_capture_summary.get('ok') and state.selected_before_capture_summary.get('ok') and state.after_capture_summary.get('ok') and state.visual_proof_summary.get('ok') and state.live_stroke_frame_budget_ok and state.heartbeat_ok and state.native_window_stationary_ok and state.read_only_ok and state.texture_gate_ok and state.fallback_gate_ok)
    return None

def _real_d3d_result(state: SimpleNamespace):
    return {'ok': state.ok, 'read_only': state.read_only_ok, 'native_core_available': True, 'workflow': 'PAMT PAC entry + production archive DDS -> native face select -> D3D11 mouse ring drag -> MeshEditorTab native stroke handler -> D3D11 vertex delta -> before/after capture', 'display_mode': 'side_by_side' if state.side_by_side else 'replacement_only', 'game_root': str(state.game_root), 'pamt_path': str(state.pamt_path), 'model_path': state.model_entry.path, 'archive_provenance': _archive_entry_provenance(state.model_entry), 'backend': 'd3d11', 'source_payload_sha256': state.source_payload_sha256, 'source_payload_unchanged': state.source_payload_unchanged, 'archive_sources_before': state.archive_sources_before, 'archive_sources_after': state.archive_sources_after, 'archive_sources_metadata_unchanged': state.archive_sources_metadata_unchanged, 'archive_content_fingerprints_before': state.archive_content_fingerprints_before, 'archive_content_fingerprints_after': state.archive_content_fingerprints_after, 'archive_source_content_unchanged': state.archive_source_content_unchanged, 'archive_sources_unchanged': state.archive_sources_unchanged, 'texture_gate_ok': state.texture_gate_ok, 'bound_texture_count': len(state.resolved_textures), 'real_texture_provenance_ok': state.real_texture_provenance_ok, 'no_synthetic_fallback': state.no_synthetic_fallback, 'resolved_production_textures': list(state.resolved_textures), 'submesh_index': state.submesh_index, 'selected_face': state.selected_faces[0] if state.selected_faces else -1, 'selected_face_count': len(state.selected_faces), 'before_vertex_count': len(state.submesh.vertices), 'before_face_count': len(state.submesh.faces), 'selected_face_vertices': state.face_vertices, 'selected_face_before_vertices': [list(vertex) for vertex in state.before_vertices], 'selected_face_after_vertices': [list(vertex) for vertex in state.after_vertices], 'selected_face_moved': state.moved, 'changed_vertex_count': len(state.changed_vertex_keys), 'changed_only_selected_geometry': state.changed_only_selected_geometry, 'native_changed_vertices': state.edit_changed_vertices, 'select_update_ok': state.select_update_ok, 'edit_update_ok': bool(state.stroke_preview_handled), 'edit_update_event': state.edit_update_event, 'host_calls': list(state.edit_host.calls), 'mesh_edit_state_event': state.mesh_edit_state_event, 'mesh_edit_states': list(state.edit_host.mesh_edit_states), 'projection_probe_down_sent': state.projection_probe_down_sent, 'projection_probe_up_sent': state.projection_probe_up_sent, 'projection_probe_status': state.projection_probe_status, 'projection_probe_finished_status': state.projection_probe_finished_status, 'selected_center': list(state.selected_center), 'selected_projected_screen_center': list(state.projected_center) if state.projected_center is not None else None, 'selected_projected_after_screen_center': list(state.projected_after_center) if state.projected_after_center is not None else None, 'selected_projected_screen_delta': list(state.projected_screen_delta) if state.projected_screen_delta is not None else None, 'expected_screen_delta': list(state.expected_screen_delta), 'selected_projected_screen_error': state.projected_screen_error, 'selected_projected_drag_tracks_cursor': state.projected_drag_tracks_cursor, 'replacement_viewport_offset_ok': state.replacement_viewport_offset_ok, 'drag_points_in_replacement_viewport': state.drag_points_in_replacement_viewport, 'replacement_viewport': {'x': state.viewport_x, 'y': state.viewport_y, 'width': state.viewport_width, 'height': state.viewport_height}, 'selected_projection_ok': state.selected_projection_ok, 'mouse_down_sent': state.mouse_down_sent, 'mouse_move_sent': state.mouse_move_sent, 'mouse_up_sent': state.mouse_up_sent, 'mouse_drag_start': list(state.mouse_drag_start), 'mouse_drag_points': [list(point) for point in state.mouse_drag_points], 'mouse_drag_end': list(state.mouse_drag_end), 'mouse_drag_pixels': math.sqrt((state.mouse_drag_end[0] - state.mouse_drag_start[0]) * (state.mouse_drag_end[0] - state.mouse_drag_start[0]) + (state.mouse_drag_end[1] - state.mouse_drag_start[1]) * (state.mouse_drag_end[1] - state.mouse_drag_start[1])), 'max_selected_vertex_delta': state.max_selected_vertex_delta, 'stroke_started_status': state.stroke_started_status, 'stroke_preview_status': state.stroke_preview_status, 'stroke_preview_statuses': state.stroke_preview_statuses, 'stroke_finished_status': state.stroke_finished_status, 'edit_update_events': state.edit_update_events, 'stroke_started_handled': state.stroke_started_handled, 'stroke_preview_handled': state.stroke_preview_handled, 'stroke_finished_handled': state.stroke_finished_handled, 'stroke_finished_handler_ms': state.stroke_finished_handler_ms, 'stroke_dispatch_idle': state.stroke_dispatch_idle, 'stroke_dispatch_metrics': state.stroke_dispatch_metrics, 'live_stroke_timings': state.live_stroke_timings, 'live_stroke_timing_summary': state.live_stroke_timing_summary, 'live_stroke_frame_budget_ok': state.live_stroke_frame_budget_ok, 'live_stroke_frame_budget_ms': state.frame_budget_ms, 'heartbeat_count': len(state.heartbeat_ms), 'heartbeat_timestamps_ms': state.heartbeat_ms, 'max_heartbeat_gap_ms': state.max_heartbeat_gap_ms, 'heartbeat_ok': state.heartbeat_ok, 'native_window_rect_before': list(state.native_window_rect_before) if state.native_window_rect_before else None, 'native_window_rect_after': list(state.native_window_rect_after) if state.native_window_rect_after else None, 'native_window_stationary_ok': state.native_window_stationary_ok, 'd3d11_send_metrics': list(state.edit_host.send_metrics), 'before_capture_png': str(state.before_capture_path), 'selected_before_capture_png': str(state.selected_before_capture_path), 'after_capture_png': str(state.after_capture_path), 'visual_edit_proof_png': str(state.visual_proof_path), 'before_capture_event': state.before_capture_event, 'selected_before_capture_event': state.selected_before_capture_event, 'after_capture_event': state.after_capture_event, 'before_capture_summary': state.before_capture_summary, 'selected_before_capture_summary': state.selected_before_capture_summary, 'after_capture_summary': state.after_capture_summary, 'visual_edit_proof_summary': state.visual_proof_summary, 'action_elapsed_ms': state.action_elapsed_ms, 'd3d11_update_ms': state.d3d11_update_ms, 'command': _command_summary(state.edit_result) if state.edit_result is not None else {}, 'native_fallback_ok': state.fallback_gate_ok, 'native_fallback_counts': state.fallback_counts, 'native_fallback_events': list(native_mesh_core_fallback_events())}

def run_real_archive_mesh_editor_d3d11_edit_smoke(game_root: Path, output_dir: Path, *, side_by_side: bool=False, timeout_seconds: float=20.0) -> dict[str, object]:
    clear_native_mesh_core_fallback_counts()
    try:
        output_inside_game_root = output_dir.resolve().is_relative_to(game_root.resolve())
    except OSError:
        output_inside_game_root = True
    if output_inside_game_root:
        return {'ok': False, 'read_only': False, 'error': 'Visual-proof output must be outside the game root.', 'game_root': str(game_root), 'output_dir': str(output_dir)}
    if os.name != 'nt':
        return {'ok': False, 'read_only': True, 'native_core_available': native_mesh_core_available(), 'reason': 'D3D11 harness requires Windows'}
    host_binary = find_native_d3d11_host()
    if host_binary is None:
        return {'ok': False, 'read_only': True, 'native_core_available': native_mesh_core_available(), 'reason': 'native D3D11 preview host not found'}
    if not native_mesh_core_available():
        return {'ok': False, 'read_only': True, 'native_core_available': False, 'reason': 'native mesh core binary not available'}
    pamt_path = game_root / '0009' / '0.pamt'
    if not pamt_path.is_file():
        return {'ok': False, 'read_only': True, 'native_core_available': True, 'skipped': f'missing PAMT: {pamt_path}', 'game_root': str(game_root), 'pamt_path': str(pamt_path)}
    entries = parse_archive_pamt(pamt_path)
    archive_sources_before = _archive_source_file_snapshot(entries)
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    model_path = _REAL_ARCHIVE_RIGGING_SAMPLES[0]
    model_entry = next(iter(entries_by_path.get(_archive_key(model_path), ())), None)
    if model_entry is None:
        return {'ok': False, 'read_only': True, 'native_core_available': True, 'model_path': model_path, 'error': 'model entry not found'}
    pac_data = _read_archive_payload(model_entry)
    source_payload_sha256 = sha256(pac_data).hexdigest()
    mesh = parse_mesh(pac_data, model_entry.path)
    editable = [(index, submesh) for index, submesh in enumerate(mesh.submeshes) if getattr(submesh, 'vertices', None) and getattr(submesh, 'faces', None)]
    if not editable:
        return {'ok': False, 'read_only': True, 'native_core_available': True, 'model_path': model_entry.path, 'error': 'PAC parsed with no editable mesh geometry'}
    original_vertex_positions = tuple((tuple((tuple((float(component) for component in vertex)) for vertex in candidate.vertices)) for candidate in mesh.submeshes))
    submesh_index, submesh = max(editable, key=lambda item: (len(item[1].faces), len(item[1].vertices)))
    resolved_textures = _resolve_real_archive_mesh_textures(mesh, model_entry, entries_by_path, entries_by_basename)
    real_texture_provenance_ok = bool(resolved_textures) and all((bool(row.get('archive_path')) and bool(row.get('source_sha256')) and (row.get('source_kind') == 'archive') and isinstance(row.get('archive_provenance'), Mapping) for row in resolved_textures))
    no_synthetic_fallback = real_texture_provenance_ok and all(('checker' not in str(row.get('source_path', '')).casefold() for row in resolved_textures))
    texture_gate_ok = bool(real_texture_provenance_ok and no_synthetic_fallback)
    archive_sources_after_texture_resolution = _archive_source_file_snapshot(entries)
    texture_resolution_read_only = archive_sources_before == archive_sources_after_texture_resolution
    if not texture_gate_ok:
        return {'ok': False, 'read_only': texture_resolution_read_only, 'native_core_available': True, 'game_root': str(game_root), 'pamt_path': str(pamt_path), 'model_path': model_entry.path, 'source_payload_sha256': source_payload_sha256, 'texture_gate_ok': False, 'real_texture_provenance_ok': real_texture_provenance_ok, 'no_synthetic_fallback': no_synthetic_fallback, 'resolved_production_textures': [], 'archive_sources_unchanged': texture_resolution_read_only, 'error': 'No production archive texture could be resolved for the real PAC mesh.'}
    fingerprint_paths = [Path(model_entry.pamt_path), Path(model_entry.paz_file)]
    for texture in resolved_textures:
        provenance = texture.get('archive_provenance')
        if isinstance(provenance, Mapping):
            fingerprint_paths.extend((Path(str(provenance[key])) for key in ('pamt_path', 'paz_path') if str(provenance.get(key, '')).strip()))
    archive_content_fingerprints_before = _archive_content_fingerprints(fingerprint_paths)
    package_dir = mesh_editor_write_native_preview_package(mesh, reference_mesh=mesh if side_by_side else None, output_root=output_dir / 'real_archive_d3d11_package', use_textures=True, backend='d3d11', display_mode='side_by_side' if side_by_side else 'replacement_only')
    status_file = output_dir / 'real_archive_d3d11_status.json'
    before_capture_path = output_dir / 'real_archive_before.png'
    selected_before_capture_path = output_dir / 'real_archive_selected_before_drag.png'
    after_capture_path = output_dir / 'real_archive_after_drag.png'
    visual_proof_path = output_dir / 'real_archive_visual_edit_proof.png'
    process = subprocess.Popen([str(host_binary), '--backend', 'd3d11', '--preview-package', str(package_dir), '--status-file', str(status_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    controller = None
    tab = None
    edit_host = None
    heartbeat_timer = None
    heartbeat_started = 0.0
    heartbeat_ms: list[float] = []
    state = SimpleNamespace(**locals())
    try:
        outcome = _real_d3d_phase_1(state)
        if outcome is not None:
            return outcome.value
        outcome = _real_d3d_phase_2(state)
        if outcome is not None:
            return outcome.value
        return _real_d3d_result(state)
    finally:
        if state.heartbeat_timer is not None:
            state.heartbeat_timer.stop()
        if state.edit_host is not None:
            state.edit_host.close()
        if state.tab is not None:
            try:
                state.tab.request_shutdown()
                state.tab.deleteLater()
            except Exception:
                pass
        elif state.controller is not None:
            state.controller.close_active_session()
        _close_process(state.process)
