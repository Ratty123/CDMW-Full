from __future__ import annotations
from types import SimpleNamespace
from tools.mesh_harness.phase_support import PhaseResult
from collections.abc import Mapping
from cdmw.domain.mesh import MeshEditSelection
from cdmw.ui.mesh_editor.controller import MeshEditorController
from pathlib import Path
from cdmw.ui.mesh_editor.controller import apply_native_update_to_host
from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts
from cdmw.rendering.native_d3d11_host import find_native_d3d11_host
from cdmw.ui.mesh_editor.native_preview_runtime import mesh_editor_write_native_preview_package
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.modding.mesh_native_core import native_mesh_core_fallback_counts
from cdmw.modding.mesh_native_core import native_mesh_core_fallback_events
import os
import subprocess
import time
from tools.mesh_harness.constants import _LEGACY_SCREEN_CAMERA_FIELDS
from tools.mesh_harness.fixtures import build_synthetic_mesh
from tools.mesh_harness.native_projection import _matrix_only_screen_payload, _screen_drag_for_z_delta, _screen_source_transform_override_ok
from tools.mesh_harness.native_protocol import _NativeD3D11HarnessHost, _close_process, _place_host_window_on_screen1, _wait_for_host_window, _wait_for_status
from tools.mesh_harness.png_evidence import _write_checker_png
from tools.mesh_harness.service_summary import _command_summary

def _d3d_delta_phase_1(state: SimpleNamespace) -> PhaseResult | None:
    state.loaded = _wait_for_status(state.status_file, {'loaded', 'resources_loaded'}, state.timeout_seconds)
    state.loaded_ok = state.loaded.get('event') in {'loaded', 'resources_loaded'}
    state.hwnd = _wait_for_host_window(state.process.pid, state.timeout_seconds)
    _place_host_window_on_screen1(state.hwnd)
    state.status_file.unlink(missing_ok=True)
    state.controller.open_mesh(state.mesh, session_id='native-editor-d3d11-delta', mode='sculpt')
    state.source_transform_overrides = [{'source_submesh_index': 0, 'world_transform': [1.01, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.01, 0.0, 0.0, 1.0]}]
    state.transform_screen_drag = _matrix_only_screen_payload(_screen_drag_for_z_delta(0.025))
    state.transform_screen_drag['source_submesh_world_transforms'] = state.source_transform_overrides
    state.transform_started = time.perf_counter()
    state.transform_execution = state.controller.run_editor_action('transform_move', selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}), screen_drag=state.transform_screen_drag)
    state.transform_elapsed_ms = (time.perf_counter() - state.transform_started) * 1000.0
    state.transform_host = _NativeD3D11HarnessHost(state.hwnd)
    state.transform_update_started = time.perf_counter()
    state.transform_update_ok = apply_native_update_to_host(state.transform_host, state.transform_execution.native_update)
    state.transform_d3d11_update_ms = (time.perf_counter() - state.transform_update_started) * 1000.0
    state.transform_update_event = _wait_for_status(state.status_file, {'mesh_edit_vertices_updated', 'mesh_edit_triangles_replaced'}, state.timeout_seconds) if state.transform_update_ok else {}
    state.status_file.unlink(missing_ok=True)
    state.brush_screen_drag = _matrix_only_screen_payload(_screen_drag_for_z_delta(0.05))
    state.brush_screen_drag['source_submesh_world_transforms'] = state.source_transform_overrides
    state.action_started = time.perf_counter()
    state.execution = state.controller.run_editor_action('brush_grab', selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)}), strength=0.75, screen_drag=state.brush_screen_drag)
    state.action_elapsed_ms = (time.perf_counter() - state.action_started) * 1000.0
    state.host = _NativeD3D11HarnessHost(state.hwnd)
    state.update_started = time.perf_counter()
    state.update_ok = apply_native_update_to_host(state.host, state.execution.native_update)
    state.d3d11_update_ms = (time.perf_counter() - state.update_started) * 1000.0
    state.update_event = _wait_for_status(state.status_file, {'mesh_edit_vertices_updated', 'mesh_edit_triangles_replaced'}, state.timeout_seconds) if state.update_ok else {}
    state.status_file.unlink(missing_ok=True)
    state.topology_started = time.perf_counter()
    state.topology_execution = state.controller.run_editor_action('subdivide', selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), max_faces_per_submesh=512, recompute_normals=True)
    state.topology_elapsed_ms = (time.perf_counter() - state.topology_started) * 1000.0
    state.topology_host = _NativeD3D11HarnessHost(state.hwnd, status_file=state.status_file, timeout_seconds=state.timeout_seconds)
    state.topology_update_started = time.perf_counter()
    state.topology_update_ok = apply_native_update_to_host(state.topology_host, state.topology_execution.native_update)
    state.topology_d3d11_update_ms = (time.perf_counter() - state.topology_update_started) * 1000.0
    state.topology_update_event = state.topology_host.triangle_events[0] if state.topology_host.triangle_events else {}
    state.appended_started = time.perf_counter()
    state.appended_execution = state.controller.run_editor_action('duplicate', selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}))
    state.appended_elapsed_ms = (time.perf_counter() - state.appended_started) * 1000.0
    state.appended_host = _NativeD3D11HarnessHost(state.hwnd, status_file=state.status_file, timeout_seconds=state.timeout_seconds)
    state.appended_update_started = time.perf_counter()
    state.appended_update_ok = apply_native_update_to_host(state.appended_host, state.appended_execution.native_update)
    state.appended_d3d11_update_ms = (time.perf_counter() - state.appended_update_started) * 1000.0
    state.appended_update_event = state.appended_host.triangle_events[0] if state.appended_host.triangle_events else {}
    state.separated_started = time.perf_counter()
    state.separated_execution = state.controller.run_editor_action('separate', selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}))
    state.separated_elapsed_ms = (time.perf_counter() - state.separated_started) * 1000.0
    state.separated_host = _NativeD3D11HarnessHost(state.hwnd, status_file=state.status_file, timeout_seconds=state.timeout_seconds)
    state.separated_update_started = time.perf_counter()
    state.separated_update_ok = apply_native_update_to_host(state.separated_host, state.separated_execution.native_update)
    state.separated_d3d11_update_ms = (time.perf_counter() - state.separated_update_started) * 1000.0
    state.separated_update_event = state.separated_host.triangle_events[0] if state.separated_host.triangle_events else {}
    state.separated_sources = state.separated_host.triangle_calls[0].get('source_submesh_indices') if state.separated_host.triangle_calls else []
    state.separated_new_index = max(state.separated_execution.edit_result.affected_submesh_indices or (-1,))
    state.undo_separate_started = time.perf_counter()
    state.undo_separate_execution = state.controller.run_editor_action('undo')
    state.undo_separate_elapsed_ms = (time.perf_counter() - state.undo_separate_started) * 1000.0
    state.undo_separate_host = _NativeD3D11HarnessHost(state.hwnd, status_file=state.status_file, timeout_seconds=state.timeout_seconds)
    state.undo_separate_update_started = time.perf_counter()
    state.undo_separate_update_ok = apply_native_update_to_host(state.undo_separate_host, state.undo_separate_execution.native_update)
    state.undo_separate_d3d11_update_ms = (time.perf_counter() - state.undo_separate_update_started) * 1000.0
    state.undo_separate_update_event = state.undo_separate_host.triangle_events[0] if state.undo_separate_host.triangle_events else {}
    state.undo_separate_sources = state.undo_separate_host.triangle_calls[0].get('source_submesh_indices') if state.undo_separate_host.triangle_calls else []
    return None

def _d3d_delta_phase_2(state: SimpleNamespace) -> PhaseResult | None:
    state.fallback_counts = native_mesh_core_fallback_counts()
    state.fallback_events = list(native_mesh_core_fallback_events())
    state.vertex_update_ok = state.update_event.get('event') == 'mesh_edit_vertices_updated' and int(state.update_event.get('changed_vertices', 0) or 0) > 0
    state.transform_vertex_update_ok = state.transform_update_event.get('event') == 'mesh_edit_vertices_updated' and int(state.transform_update_event.get('changed_vertices', 0) or 0) > 0
    state.transform_delta_ok = bool(state.transform_execution.edit_result.ok) and bool(state.transform_execution.native_update.vertex_groups) and (not state.transform_execution.native_update.triangle_groups) and (not state.transform_execution.native_update.replace_all_triangles) and (state.transform_host.calls == ['update_mesh_edit_vertices']) and state.transform_vertex_update_ok
    state.transform_screen_payload_ok = all((field in state.transform_screen_drag for field in ('start_x', 'start_y', 'end_x', 'end_y'))) and len(tuple(state.transform_screen_drag.get('world_view_projection') or ())) == 16 and ('camera_world' not in state.transform_screen_drag) and ('delta_x_pixels' not in state.transform_screen_drag)
    state.delta_only_ok = bool(state.execution.edit_result.ok) and bool(state.execution.native_update.vertex_groups) and (not state.execution.native_update.triangle_groups) and (not state.execution.native_update.replace_all_triangles) and (state.host.calls == ['update_mesh_edit_vertices']) and state.vertex_update_ok
    state.brush_screen_payload_ok = all((field in state.brush_screen_drag for field in ('start_x', 'start_y', 'end_x', 'end_y'))) and len(tuple(state.brush_screen_drag.get('world_view_projection') or ())) == 16 and ('camera_world' not in state.brush_screen_drag) and ('delta_x_pixels' not in state.brush_screen_drag)
    state.screen_payloads_without_legacy_camera_fields_ok = _LEGACY_SCREEN_CAMERA_FIELDS.isdisjoint(state.transform_screen_drag) and _LEGACY_SCREEN_CAMERA_FIELDS.isdisjoint(state.brush_screen_drag)
    state.screen_payloads_with_source_transform_overrides_ok = _screen_source_transform_override_ok(state.transform_screen_drag) and _screen_source_transform_override_ok(state.brush_screen_drag)
    state.dispatch_target_ms = 50.0
    state.transform_dispatch_target_ok = 0.0 < state.transform_elapsed_ms < state.dispatch_target_ms
    state.brush_dispatch_target_ok = 0.0 < state.action_elapsed_ms < state.dispatch_target_ms
    state.dispatch_target_ok = state.transform_dispatch_target_ok and state.brush_dispatch_target_ok
    state.topology_delta_ok = bool(state.topology_execution.edit_result.ok) and bool(state.topology_execution.edit_result.topology_changed) and bool(state.topology_execution.native_update.triangle_groups) and (not state.topology_execution.native_update.vertex_groups) and (not state.topology_execution.native_update.replace_all_triangles) and ('replace_mesh_edit_triangles' in state.topology_host.calls) and ('update_mesh_edit_vertices' not in state.topology_host.calls) and bool(state.topology_host.triangle_calls) and (not bool(state.topology_host.triangle_calls[0].get('replace_all'))) and (state.topology_host.triangle_calls[0].get('source_submesh_indices') == [0]) and (state.topology_update_event.get('event') == 'mesh_edit_triangles_replaced') and (int(state.topology_update_event.get('replaced_batches', 0) or 0) >= 1)
    state.appended_delta_ok = bool(state.appended_execution.edit_result.ok) and bool(state.appended_execution.edit_result.topology_changed) and (int(state.appended_execution.edit_result.submesh_count_delta or 0) > 0) and bool(state.appended_execution.native_update.triangle_groups) and (not state.appended_execution.native_update.vertex_groups) and (not state.appended_execution.native_update.replace_all_triangles) and ('replace_mesh_edit_triangles' in state.appended_host.calls) and ('update_mesh_edit_vertices' not in state.appended_host.calls) and bool(state.appended_host.triangle_calls) and (not bool(state.appended_host.triangle_calls[0].get('replace_all'))) and (state.appended_host.triangle_calls[0].get('source_submesh_indices') == [1]) and (state.appended_update_event.get('event') == 'mesh_edit_triangles_replaced') and (int(state.appended_update_event.get('replaced_batches', 0) or 0) >= 1)
    state.separated_delta_ok = bool(state.separated_execution.edit_result.ok) and bool(state.separated_execution.edit_result.topology_changed) and (int(state.separated_execution.edit_result.submesh_count_delta or 0) > 0) and bool(state.separated_execution.native_update.triangle_groups) and (not state.separated_execution.native_update.vertex_groups) and (not state.separated_execution.native_update.replace_all_triangles) and ('replace_mesh_edit_triangles' in state.separated_host.calls) and ('update_mesh_edit_vertices' not in state.separated_host.calls) and bool(state.separated_host.triangle_calls) and (not bool(state.separated_host.triangle_calls[0].get('replace_all'))) and (state.separated_sources == [0, state.separated_new_index]) and (state.separated_update_event.get('event') == 'mesh_edit_triangles_replaced') and (int(state.separated_update_event.get('replaced_batches', 0) or 0) >= 1)
    state.undo_separate_delta_ok = bool(state.undo_separate_execution.edit_result.ok) and bool(state.undo_separate_execution.edit_result.topology_changed) and (int(state.undo_separate_execution.edit_result.submesh_count_delta or 0) < 0) and bool(state.undo_separate_execution.native_update.triangle_source_submesh_indices) and (not state.undo_separate_execution.native_update.vertex_groups) and (not state.undo_separate_execution.native_update.replace_all_triangles) and ('replace_mesh_edit_triangles' in state.undo_separate_host.calls) and ('update_mesh_edit_vertices' not in state.undo_separate_host.calls) and bool(state.undo_separate_host.triangle_calls) and (not bool(state.undo_separate_host.triangle_calls[0].get('replace_all'))) and (sorted(state.undo_separate_sources) == [0, state.separated_new_index]) and (state.undo_separate_update_event.get('event') == 'mesh_edit_triangles_replaced') and (int(state.undo_separate_update_event.get('removed_batches', 0) or 0) >= 1)
    state.fallback_ok = not state.fallback_counts
    state.transform_summary = _command_summary(state.transform_execution.edit_result)
    state.transform_metrics = dict(state.transform_summary.get('metrics', {}) or {})
    state.transform_metrics['d3d11_update_ms'] = state.transform_d3d11_update_ms
    state.transform_summary['metrics'] = state.transform_metrics
    state.command_summary = _command_summary(state.execution.edit_result)
    state.command_metrics = dict(state.command_summary.get('metrics', {}) or {})
    state.command_metrics['d3d11_update_ms'] = state.d3d11_update_ms
    state.command_summary['metrics'] = state.command_metrics
    state.topology_summary = _command_summary(state.topology_execution.edit_result)
    state.topology_metrics = dict(state.topology_summary.get('metrics', {}) or {})
    state.topology_metrics['d3d11_update_ms'] = state.topology_d3d11_update_ms
    state.topology_summary['metrics'] = state.topology_metrics
    state.appended_summary = _command_summary(state.appended_execution.edit_result)
    state.appended_metrics = dict(state.appended_summary.get('metrics', {}) or {})
    state.appended_metrics['d3d11_update_ms'] = state.appended_d3d11_update_ms
    state.appended_summary['metrics'] = state.appended_metrics
    state.separated_summary = _command_summary(state.separated_execution.edit_result)
    state.separated_metrics = dict(state.separated_summary.get('metrics', {}) or {})
    state.separated_metrics['d3d11_update_ms'] = state.separated_d3d11_update_ms
    state.separated_summary['metrics'] = state.separated_metrics
    state.undo_separate_summary = _command_summary(state.undo_separate_execution.edit_result)
    state.undo_separate_metrics = dict(state.undo_separate_summary.get('metrics', {}) or {})
    state.undo_separate_metrics['d3d11_update_ms'] = state.undo_separate_d3d11_update_ms
    state.undo_separate_summary['metrics'] = state.undo_separate_metrics
    return None

def _d3d_delta_phase_3(state: SimpleNamespace) -> PhaseResult | None:

    def metrics_include(summary: Mapping[str, object], *keys: str) -> bool:
        metrics = summary.get('metrics')
        return isinstance(metrics, Mapping) and all((isinstance(metrics.get(key), (int, float)) and float(metrics[key]) >= 0.0 for key in keys))
    state.native_apply_and_d3d11_metrics_ok = all((metrics_include(summary, 'cpp_ms', 'native_apply_roundtrip_ms', 'native_apply_overhead_ms', 'service_total_ms', 'd3d11_update_ms') for summary in (state.transform_summary, state.command_summary, state.topology_summary, state.appended_summary, state.separated_summary)))
    state.native_history_and_d3d11_metrics_ok = metrics_include(state.undo_separate_summary, 'native_history_roundtrip_ms', 'service_total_ms', 'd3d11_update_ms')
    return None

def _d3d_delta_result(state: SimpleNamespace):
    return {'ok': bool(state.loaded_ok and state.hwnd and state.transform_delta_ok and state.transform_screen_payload_ok and state.transform_update_ok and state.delta_only_ok and state.brush_screen_payload_ok and state.screen_payloads_without_legacy_camera_fields_ok and state.screen_payloads_with_source_transform_overrides_ok and state.dispatch_target_ok and state.topology_delta_ok and state.topology_update_ok and state.appended_delta_ok and state.appended_update_ok and state.separated_delta_ok and state.separated_update_ok and state.undo_separate_delta_ok and state.undo_separate_update_ok and state.native_apply_and_d3d11_metrics_ok and state.native_history_and_d3d11_metrics_ok and state.fallback_ok), 'native_core_available': state.native_available, 'host': str(state.host_binary), 'loaded_status': state.loaded, 'transform_action_elapsed_ms': state.transform_elapsed_ms, 'transform_d3d11_update_ms': state.transform_d3d11_update_ms, 'transform_command': state.transform_summary, 'transform_vertex_group_count': len(state.transform_execution.native_update.vertex_groups or ()), 'transform_triangle_group_count': len(state.transform_execution.native_update.triangle_groups or ()), 'transform_replace_all_triangles': bool(state.transform_execution.native_update.replace_all_triangles), 'transform_host_calls': list(state.transform_host.calls), 'transform_update_event': state.transform_update_event, 'transform_delta_ok': state.transform_delta_ok, 'transform_screen_payload_ok': state.transform_screen_payload_ok, 'transform_dispatch_target_ok': state.transform_dispatch_target_ok, 'action_elapsed_ms': state.action_elapsed_ms, 'd3d11_update_ms': state.d3d11_update_ms, 'command': state.command_summary, 'vertex_group_count': len(state.execution.native_update.vertex_groups or ()), 'triangle_group_count': len(state.execution.native_update.triangle_groups or ()), 'replace_all_triangles': bool(state.execution.native_update.replace_all_triangles), 'host_calls': list(state.host.calls), 'update_event': state.update_event, 'delta_only_ok': state.delta_only_ok, 'brush_screen_payload_ok': state.brush_screen_payload_ok, 'screen_payloads_without_legacy_camera_fields_ok': state.screen_payloads_without_legacy_camera_fields_ok, 'screen_payloads_with_source_transform_overrides_ok': state.screen_payloads_with_source_transform_overrides_ok, 'brush_dispatch_target_ok': state.brush_dispatch_target_ok, 'dispatch_target_ms': state.dispatch_target_ms, 'dispatch_target_ok': state.dispatch_target_ok, 'topology_action_elapsed_ms': state.topology_elapsed_ms, 'topology_d3d11_update_ms': state.topology_d3d11_update_ms, 'topology_command': state.topology_summary, 'topology_triangle_group_count': len(state.topology_execution.native_update.triangle_groups or ()), 'topology_replace_all_triangles': bool(state.topology_execution.native_update.replace_all_triangles), 'topology_host_calls': list(state.topology_host.calls), 'topology_triangle_calls': list(state.topology_host.triangle_calls), 'topology_update_event': state.topology_update_event, 'topology_delta_ok': state.topology_delta_ok, 'appended_action_elapsed_ms': state.appended_elapsed_ms, 'appended_d3d11_update_ms': state.appended_d3d11_update_ms, 'appended_command': state.appended_summary, 'appended_triangle_group_count': len(state.appended_execution.native_update.triangle_groups or ()), 'appended_replace_all_triangles': bool(state.appended_execution.native_update.replace_all_triangles), 'appended_host_calls': list(state.appended_host.calls), 'appended_triangle_calls': list(state.appended_host.triangle_calls), 'appended_update_event': state.appended_update_event, 'appended_delta_ok': state.appended_delta_ok, 'separated_action_elapsed_ms': state.separated_elapsed_ms, 'separated_d3d11_update_ms': state.separated_d3d11_update_ms, 'separated_command': state.separated_summary, 'separated_triangle_group_count': len(state.separated_execution.native_update.triangle_groups or ()), 'separated_replace_all_triangles': bool(state.separated_execution.native_update.replace_all_triangles), 'separated_host_calls': list(state.separated_host.calls), 'separated_triangle_calls': list(state.separated_host.triangle_calls), 'separated_update_event': state.separated_update_event, 'separated_delta_ok': state.separated_delta_ok, 'undo_separate_action_elapsed_ms': state.undo_separate_elapsed_ms, 'undo_separate_d3d11_update_ms': state.undo_separate_d3d11_update_ms, 'undo_separate_command': state.undo_separate_summary, 'undo_separate_triangle_group_count': len(state.undo_separate_execution.native_update.triangle_groups or ()), 'undo_separate_replace_all_triangles': bool(state.undo_separate_execution.native_update.replace_all_triangles), 'undo_separate_host_calls': list(state.undo_separate_host.calls), 'undo_separate_triangle_calls': list(state.undo_separate_host.triangle_calls), 'undo_separate_update_event': state.undo_separate_update_event, 'undo_separate_delta_ok': state.undo_separate_delta_ok, 'native_apply_and_d3d11_metrics_ok': state.native_apply_and_d3d11_metrics_ok, 'native_history_and_d3d11_metrics_ok': state.native_history_and_d3d11_metrics_ok, 'native_fallback_ok': state.fallback_ok, 'native_fallback_counts': state.fallback_counts, 'native_fallback_events': state.fallback_events}

def run_native_mesh_editor_d3d11_delta(output_dir: Path, *, timeout_seconds: float=15.0) -> dict[str, object]:
    clear_native_mesh_core_fallback_counts()
    if os.name != 'nt':
        return {'ok': False, 'native_core_available': native_mesh_core_available(), 'reason': 'D3D11 harness requires Windows'}
    host_binary = find_native_d3d11_host()
    if host_binary is None:
        return {'ok': False, 'native_core_available': native_mesh_core_available(), 'reason': 'native D3D11 preview host not found'}
    native_available = native_mesh_core_available()
    if not native_available:
        return {'ok': False, 'native_core_available': False, 'reason': 'native mesh core binary not available'}
    mesh = build_synthetic_mesh()
    texture_path = output_dir / 'd3d11_delta_checker.png'
    _write_checker_png(texture_path)
    for submesh in mesh.submeshes:
        if submesh.uvs:
            submesh.texture = str(texture_path)
    package_dir = mesh_editor_write_native_preview_package(mesh, output_root=output_dir / 'd3d11_delta_package', use_textures=True, backend='d3d11')
    status_file = output_dir / 'd3d11_delta_status.json'
    process = subprocess.Popen([str(host_binary), '--backend', 'd3d11', '--preview-package', str(package_dir), '--status-file', str(status_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tab = None
    controller = MeshEditorController()
    state = SimpleNamespace(**locals())
    try:
        outcome = _d3d_delta_phase_1(state)
        if outcome is not None:
            return outcome.value
        outcome = _d3d_delta_phase_2(state)
        if outcome is not None:
            return outcome.value
        outcome = _d3d_delta_phase_3(state)
        if outcome is not None:
            return outcome.value
        return _d3d_delta_result(state)
    finally:
        if state.controller is not None:
            state.controller.close_active_session()
        _close_process(state.process)
