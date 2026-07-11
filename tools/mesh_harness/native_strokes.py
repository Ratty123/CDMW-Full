from __future__ import annotations
from types import SimpleNamespace
from tools.mesh_harness.phase_support import PhaseResult
from pathlib import Path
from cdmw.ui.mesh_editor.static_replacement_adapter import StaticReplacementMeshEditSession
from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.modding.mesh_native_core import native_mesh_core_fallback_counts
from cdmw.modding.mesh_native_core import native_mesh_core_fallback_events
import os
import struct
import tempfile
from tools.mesh_harness.constants import _LEGACY_SCREEN_CAMERA_FIELDS
from tools.mesh_harness.fixtures import build_synthetic_mesh
from tools.mesh_harness.native_projection import _emit_timed_stroke, _matrix_only_screen_payload, _screen_drag_for_z_delta, _screen_source_transform_override_ok, _wait_for_live_stroke_idle
from tools.mesh_harness.native_protocol import _StandaloneStrokeHarnessHost
from tools.mesh_harness.service_summary import _command_summary

def _standalone_stroke_phase_1(state: SimpleNamespace) -> PhaseResult | None:
    state.tab.set_native_preview_host(state.host)
    state.view = state.tab.open_mesh_session(build_synthetic_mesh(), session_id='native-editor-standalone-stroke', mode='edit')
    state.controller = state.tab.standalone_controller
    if state.controller is None:
        return PhaseResult({'ok': False, 'native_core_available': True, 'reason': 'standalone controller unavailable'})
    state.select_result = state.controller.select(vertices_by_submesh={0: (0, 1)})
    state.tab.update_editor_session_state(state.controller.session_view(), active_selection_mode=state.controller.active_selection_mode)
    state.tab.set_active_tool_state(mode='edit', active_tool_key='transform_move')
    state.before_vertex = tuple((float(value) for value in state.controller.working_mesh(clone=True).submeshes[0].vertices[0]))
    state.stroke_id = 'standalone-stroke-1'
    state.stroke_begin_drag = _matrix_only_screen_payload(_screen_drag_for_z_delta(0.0))
    state.stroke_update_drag = _matrix_only_screen_payload(_screen_drag_for_z_delta(0.05))
    state.begin_ms = _emit_timed_stroke(state.host.mesh_edit_stroke_started, {'stroke_id': state.stroke_id, 'tool': 'move', 'screen_drag': state.stroke_begin_drag})
    state.update_ms = _emit_timed_stroke(state.host.mesh_edit_stroke_previewed, {'stroke_id': state.stroke_id, 'tool': 'move', 'screen_drag': state.stroke_update_drag})
    state.end_ms = _emit_timed_stroke(state.host.mesh_edit_stroke_finished, {'stroke_id': state.stroke_id, 'tool': 'move'})
    state.first_stroke_idle = _wait_for_live_stroke_idle(state.tab, state.app)
    state.signal_results = {'begin': list(state.host.mesh_edit_stroke_started.results), 'update': list(state.host.mesh_edit_stroke_previewed.results), 'end': list(state.host.mesh_edit_stroke_finished.results)}
    state.app.processEvents()
    state.after_vertex = tuple((float(value) for value in state.controller.working_mesh(clone=True).submeshes[0].vertices[0]))
    state.after_view = state.controller.session_view()
    state.undo_result = state.controller.undo()
    state.undo_vertex = tuple((float(value) for value in state.controller.working_mesh(clone=True).submeshes[0].vertices[0]))
    state.tab.update_editor_session_state(state.controller.session_view(), active_selection_mode=state.controller.active_selection_mode)
    state.tab.set_active_tool_state(mode='sculpt', active_tool_key='brush_grab')
    state.before_brush_vertex = tuple((float(value) for value in state.controller.working_mesh(clone=True).submeshes[0].vertices[0]))
    state.brush_stroke_id = 'standalone-brush-stroke-1'
    state.brush_center = {'x': state.before_brush_vertex[0], 'y': state.before_brush_vertex[1], 'z': state.before_brush_vertex[2]}
    state.brush_weight = 0.25
    with tempfile.TemporaryDirectory(prefix='cdmw_standalone_brush_weights_') as state.brush_weight_dir:
        state.brush_weight_root = Path(state.brush_weight_dir)
        state.brush_indices_path = state.brush_weight_root / 'stroke_vertices.bin'
        state.brush_weights_path = state.brush_weight_root / 'stroke_weights.bin'
        state.brush_indices_path.write_bytes(struct.pack('=ii', 0, 1))
        state.brush_weights_path.write_bytes(struct.pack('=ff', state.brush_weight, 1.0))
        state.brush_groups = ({'source_submesh_index': 0, 'source_vertex_indices_binary': {'path': str(state.brush_indices_path), 'count': 2, 'components': 1, 'type': 'i32'}, 'source_vertex_weights_binary': {'path': str(state.brush_weights_path), 'count': 2, 'components': 1, 'type': 'f32'}},)
        state.brush_begin_drag = _matrix_only_screen_payload(_screen_drag_for_z_delta(0.0))
        state.brush_update_drag = _matrix_only_screen_payload(_screen_drag_for_z_delta(0.04))
        state.brush_begin_ms = _emit_timed_stroke(state.host.mesh_edit_stroke_started, {'stroke_id': state.brush_stroke_id, 'tool': 'grab', 'center': state.brush_center, 'screen_drag': state.brush_begin_drag, 'amount': 0.0, 'radius': 2.0, 'strength': 1.0, 'groups': state.brush_groups})
        state.brush_update_ms = _emit_timed_stroke(state.host.mesh_edit_stroke_previewed, {'stroke_id': state.brush_stroke_id, 'tool': 'grab', 'center': state.brush_center, 'screen_drag': state.brush_update_drag, 'amount': 0.04, 'radius': 2.0, 'strength': 1.0, 'groups': state.brush_groups})
        state.brush_end_ms = _emit_timed_stroke(state.host.mesh_edit_stroke_finished, {'stroke_id': state.brush_stroke_id, 'tool': 'grab'})
        state.brush_stroke_idle = _wait_for_live_stroke_idle(state.tab, state.app)
    state.brush_signal_results = {'begin': list(state.host.mesh_edit_stroke_started.results), 'update': list(state.host.mesh_edit_stroke_previewed.results), 'end': list(state.host.mesh_edit_stroke_finished.results)}
    state.app.processEvents()
    state.after_brush_vertex = tuple((float(value) for value in state.controller.working_mesh(clone=True).submeshes[0].vertices[0]))
    state.after_brush_view = state.controller.session_view()
    state.brush_metrics = dict(state.tab.standalone_last_action_metrics)
    state.brush_undo_result = state.controller.undo()
    state.brush_undo_vertex = tuple(float(value) for value in state.controller.working_mesh(clone=True).submeshes[0].vertices[0])
    return None

def _standalone_stroke_phase_2(state: SimpleNamespace) -> PhaseResult | None:
    state.metrics = dict(state.tab.standalone_last_action_metrics)
    state.screen_selection_ms = _emit_timed_stroke(state.host.mesh_edit_selection_changed, {'operation': 'replace', 'falloff': 'smooth', 'target_mode': 'vertex', 'selection_depth_mode': 'visible', 'screen_brush': {'x': 175.0, 'y': 175.0, 'radius_pixels': 3.0, 'viewport_width': 200.0, 'viewport_height': 200.0, 'world_view_projection': [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.5, 1.0]}})
    state.screen_selection_results = list(state.host.mesh_edit_selection_changed.results)
    state.screen_selection_vertices = sorted(state.controller.session_view().selection.vertex_map().get(0, ()))
    state.edge_screen_selection_ms = _emit_timed_stroke(state.host.mesh_edit_selection_changed, {'operation': 'replace', 'falloff': 'smooth', 'target_mode': 'edge', 'selection_depth_mode': 'visible', 'screen_brush': {'x': 100.0, 'y': 175.0, 'radius_pixels': 3.0, 'viewport_width': 200.0, 'viewport_height': 200.0, 'world_view_projection': [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.5, 1.0]}})
    state.edge_screen_selection_results = list(state.host.mesh_edit_selection_changed.results)
    state.screen_selection_edges = sorted((tuple(edge) for edge in state.controller.session_view().selection.edge_map().get(0, ())))
    state.face_screen_selection_ms = _emit_timed_stroke(state.host.mesh_edit_selection_changed, {'operation': 'replace', 'falloff': 'smooth', 'target_mode': 'face', 'selection_depth_mode': 'visible', 'screen_brush': {'x': 62.0, 'y': 138.0, 'radius_pixels': 3.0, 'viewport_width': 200.0, 'viewport_height': 200.0, 'world_view_projection': [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.5, 1.0]}})
    state.face_screen_selection_results = list(state.host.mesh_edit_selection_changed.results)
    state.screen_selection_faces = sorted(state.controller.session_view().selection.face_map().get(0, ()))
    state.screen_selection_ok = state.screen_selection_results == [True] and state.edge_screen_selection_results == [True] and (state.face_screen_selection_results == [True]) and (state.screen_selection_vertices == [1]) and (state.screen_selection_edges == [(0, 1)]) and (state.screen_selection_faces == [0])
    state.screen_selection_metrics = dict(state.tab.standalone_last_action_metrics)
    return None

def _standalone_stroke_phase_3(state: SimpleNamespace) -> PhaseResult | None:
    state.fallback_counts = native_mesh_core_fallback_counts()
    state.fallback_events = list(native_mesh_core_fallback_events())
    state.enabled_states = [state for state in state.host.mesh_edit_states if bool(state.get('enabled'))]
    state.moved = any((abs(state.after_vertex[index] - state.before_vertex[index]) > 1e-08 for index in range(3)))
    state.undo_restored = all((abs(state.undo_vertex[index] - state.before_vertex[index]) <= 1e-08 for index in range(3)))
    state.brush_moved = any((abs(state.after_brush_vertex[index] - state.before_brush_vertex[index]) > 1e-08 for index in range(3)))
    state.brush_undo_restored = all((abs(state.brush_undo_vertex[index] - state.before_brush_vertex[index]) <= 1e-08 for index in range(3)))
    state.brush_weighted_delta_ok = abs(state.after_brush_vertex[2] - state.before_brush_vertex[2] - 0.04 * state.brush_weight) <= 1e-08
    state.dispatch_times = {'begin_ms': state.begin_ms, 'update_ms': state.update_ms, 'end_ms': state.end_ms}
    state.brush_dispatch_times = {'begin_ms': state.brush_begin_ms, 'update_ms': state.brush_update_ms, 'end_ms': state.brush_end_ms}
    state.dispatch_ok = max((*state.dispatch_times.values(), *state.brush_dispatch_times.values())) <= 50.0
    state.signals_ok = all((all((result is not False for result in results)) for results in (*state.signal_results.values(), *state.brush_signal_results.values())))
    state.fallback_ok = not state.fallback_counts
    state.screen_payloads_without_legacy_camera_fields_ok = all((_LEGACY_SCREEN_CAMERA_FIELDS.isdisjoint(payload) for payload in (state.stroke_begin_drag, state.stroke_update_drag, state.brush_begin_drag, state.brush_update_drag)))
    return None

def _standalone_stroke_result(state: SimpleNamespace):
    return {'ok': bool(state.select_result.ok and state.moved and state.undo_result.ok and state.undo_restored and state.brush_moved and state.brush_weighted_delta_ok and state.brush_undo_result.ok and state.brush_undo_restored and (state.after_view.undo_count == 1) and (state.after_brush_view.undo_count == 1) and state.host.vertex_group_counts and (state.tab.standalone_native_mesh_edit_stroke_id == '') and state.enabled_states and state.dispatch_ok and state.first_stroke_idle and state.brush_stroke_idle and state.signals_ok and state.screen_selection_ok and state.screen_payloads_without_legacy_camera_fields_ok and state.fallback_ok), 'native_core_available': True, 'session_id': state.view.session_id, 'select': _command_summary(state.select_result), 'undo': _command_summary(state.undo_result), 'brush_undo': _command_summary(state.brush_undo_result), 'before_vertex': list(state.before_vertex), 'after_vertex': list(state.after_vertex), 'undo_vertex': list(state.undo_vertex), 'before_brush_vertex': list(state.before_brush_vertex), 'after_brush_vertex': list(state.after_brush_vertex), 'brush_undo_vertex': list(state.brush_undo_vertex), 'moved': state.moved, 'undo_restored': state.undo_restored, 'brush_moved': state.brush_moved, 'brush_weighted_delta_ok': state.brush_weighted_delta_ok, 'brush_undo_restored': state.brush_undo_restored, 'undo_count_after_stroke': state.after_view.undo_count, 'undo_count_after_brush': state.after_brush_view.undo_count, 'host_calls': list(state.host.calls), 'mesh_edit_state': state.enabled_states[-1] if state.enabled_states else {}, 'vertex_group_counts': list(state.host.vertex_group_counts), 'selection_group_counts': list(state.host.selection_group_counts), 'screen_selection_results': state.screen_selection_results, 'screen_selection_vertices': state.screen_selection_vertices, 'edge_screen_selection_results': state.edge_screen_selection_results, 'screen_selection_edges': [list(edge) for edge in state.screen_selection_edges], 'edge_screen_selection_ms': state.edge_screen_selection_ms, 'face_screen_selection_results': state.face_screen_selection_results, 'screen_selection_faces': state.screen_selection_faces, 'face_screen_selection_ms': state.face_screen_selection_ms, 'screen_selection_ms': state.screen_selection_ms, 'screen_selection_metrics': state.screen_selection_metrics, 'screen_selection_ok': state.screen_selection_ok, 'screen_payloads_without_legacy_camera_fields_ok': state.screen_payloads_without_legacy_camera_fields_ok, 'stroke_id_after_finish': state.tab.standalone_native_mesh_edit_stroke_id, 'dispatch_times_ms': state.dispatch_times, 'brush_dispatch_times_ms': state.brush_dispatch_times, 'first_stroke_idle': state.first_stroke_idle, 'brush_stroke_idle': state.brush_stroke_idle, 'dispatch_target_ok': state.dispatch_ok, 'signal_results': state.signal_results, 'brush_signal_results': state.brush_signal_results, 'signals_ok': state.signals_ok, 'last_action_metrics': state.metrics, 'brush_last_action_metrics': state.brush_metrics, 'native_fallback_ok': state.fallback_ok, 'native_fallback_counts': state.fallback_counts, 'native_fallback_events': state.fallback_events}

def run_native_mesh_editor_standalone_stroke() -> dict[str, object]:
    clear_native_mesh_core_fallback_counts()
    native_available = native_mesh_core_available()
    if not native_available:
        return {'ok': False, 'native_core_available': False, 'reason': 'native mesh core binary not available'}
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtCore import QCoreApplication, QEvent, QSettings
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.mesh_editor import MeshEditorTab
    app = QApplication.instance() or QApplication(['native-mesh-editor-standalone-stroke'])
    app.setQuitOnLastWindowClosed(False)
    tab = MeshEditorTab(settings=QSettings('CDMWHarness', 'NativeMeshEditorStandaloneStroke'))
    host = _StandaloneStrokeHarnessHost()
    controller = None
    state = SimpleNamespace(**locals())
    try:
        outcome = _standalone_stroke_phase_1(state)
        if outcome is not None:
            return outcome.value
        outcome = _standalone_stroke_phase_2(state)
        if outcome is not None:
            return outcome.value
        outcome = _standalone_stroke_phase_3(state)
        if outcome is not None:
            return outcome.value
        return _standalone_stroke_result(state)
    finally:
        dispatcher = state.tab.standalone_live_stroke_dispatcher
        state.tab.request_shutdown()
        if dispatcher is not None:
            dispatcher.stop()
        state.tab.deleteLater()
        QCoreApplication.sendPostedEvents(state.tab, QEvent.Type.DeferredDelete)
        state.app.processEvents()

def run_native_mesh_editor_static_replacement_screen_stroke() -> dict[str, object]:
    clear_native_mesh_core_fallback_counts()
    native_available = native_mesh_core_available()
    if not native_available:
        return {'ok': False, 'native_core_available': False, 'reason': 'native mesh core binary not available'}
    session = StaticReplacementMeshEditSession(session_id='native-editor-static-screen-stroke')
    session.open(build_synthetic_mesh())
    try:
        screen_brush = {'x': 175.0, 'y': 175.0, 'radius_pixels': 3.0, 'viewport_width': 200.0, 'viewport_height': 200.0, 'world_view_projection': [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.5, 1.0]}
        source_transform_overrides = [{'source_submesh_index': 0, 'world_transform': [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.01, 0.0, 0.0, 1.0]}]
        screen_brush['source_submesh_world_transforms'] = source_transform_overrides
        screen_selection = {'target_mode': 'vertex', 'selection_depth_mode': 'visible', 'falloff': 'smooth', 'screen_brush': screen_brush}
        transform_begin_screen_drag = _matrix_only_screen_payload(_screen_drag_for_z_delta(0.02))
        transform_screen_drag = _matrix_only_screen_payload(_screen_drag_for_z_delta(0.03, start_z=0.02))
        descriptor_screen_drag = _matrix_only_screen_payload(_screen_drag_for_z_delta(0.02))
        brush_screen_drag = _matrix_only_screen_payload(_screen_drag_for_z_delta(0.04))
        transform_begin_screen_drag['source_submesh_world_transforms'] = source_transform_overrides
        transform_screen_drag['source_submesh_world_transforms'] = source_transform_overrides
        descriptor_screen_drag['source_submesh_world_transforms'] = source_transform_overrides
        brush_screen_drag['source_submesh_world_transforms'] = source_transform_overrides
        before_transform = tuple((float(value) for value in session.controller.working_mesh(clone=True).submeshes[0].vertices[1]))
        transform_begin = session.apply('transform', screen_drag=transform_begin_screen_drag, _native_screen_selection_payload=screen_selection, stroke_phase='begin', stroke_id='static-transform-stroke-1', recompute_normals=False, record_history=False, _require_native_history_delta=True)
        transform = session.apply('transform', screen_drag=transform_screen_drag, stroke_phase='update', stroke_id='static-transform-stroke-1', recompute_normals=False, record_history=False, _require_native_history_delta=True)
        transform_end = session.apply('transform', stroke_phase='end', stroke_id='static-transform-stroke-1', recompute_normals=False, record_history=False, _require_native_history_delta=True)
        after_transform = tuple((float(value) for value in session.controller.working_mesh(clone=True).submeshes[0].vertices[1]))
        before_descriptor_transform = after_transform
        descriptor_transform = session.apply('transform', screen_drag=descriptor_screen_drag, _native_selection_payload={'vertices_by_submesh': {0: {'start': 1, 'count': 1}}}, recompute_normals=False, record_history=False, _require_native_history_delta=True)
        after_descriptor_transform = tuple((float(value) for value in session.controller.working_mesh(clone=True).submeshes[0].vertices[1]))
        before_brush = after_descriptor_transform
        brush = session.apply('brush', mode='sculpt', tool='grab', screen_drag=brush_screen_drag, screen_brush=screen_brush, target_mode='vertex', selection_depth_mode='visible', strength=1.0, falloff='smooth', recompute_normals=False, record_history=False, _require_native_history_delta=True)
        after_brush = tuple((float(value) for value in session.controller.working_mesh(clone=True).submeshes[0].vertices[1]))
        fallback_counts = native_mesh_core_fallback_counts()
        fallback_ok = not fallback_counts
        transform_moved = abs(after_transform[2] - before_transform[2] - 0.05) <= 1e-08
        raw_transform_update_count = transform.edit_result.metrics.get('native_stroke_update_count')
        raw_transform_end_active = transform_end.edit_result.metrics.get('native_stroke_active')
        transform_update_count = float(raw_transform_update_count if raw_transform_update_count is not None else 0.0)
        transform_end_active = float(raw_transform_end_active if raw_transform_end_active is not None else 1.0)
        transform_incremental_drag_ok = transform_begin_screen_drag.get('start_x') == 0.0 and transform_begin_screen_drag.get('end_x') == 2.0 and (transform_screen_drag.get('start_x') == 2.0) and (transform_screen_drag.get('end_x') == 5.0) and (transform_update_count == 2.0) and (transform_end_active == 0.0)
        descriptor_transform_moved = abs(after_descriptor_transform[2] - before_descriptor_transform[2] - 0.02) <= 1e-08
        brush_delta_z = after_brush[2] - before_brush[2]
        brush_moved = 0.0 < brush_delta_z <= 0.04
        transform_delta_ok = bool(transform.edit_result.ok) and bool(transform.native_update.vertex_groups) and (not transform.native_update.triangle_groups) and bool(transform.changed_vertices_by_submesh)
        descriptor_transform_delta_ok = bool(descriptor_transform.edit_result.ok) and bool(descriptor_transform.native_update.vertex_groups) and (not descriptor_transform.native_update.triangle_groups) and bool(descriptor_transform.changed_vertices_by_submesh)
        brush_delta_ok = bool(brush.edit_result.ok) and bool(brush.native_update.vertex_groups) and (not brush.native_update.triangle_groups) and bool(brush.changed_vertices_by_submesh)
        screen_payloads_without_legacy_camera_fields_ok = all((_LEGACY_SCREEN_CAMERA_FIELDS.isdisjoint(payload) for payload in (transform_screen_drag, descriptor_screen_drag, brush_screen_drag, screen_brush)))
        screen_payloads_with_source_transform_overrides_ok = all((_screen_source_transform_override_ok(payload) for payload in (transform_screen_drag, descriptor_screen_drag, brush_screen_drag, screen_brush)))
        return {'ok': bool(transform_moved and transform_incremental_drag_ok and descriptor_transform_moved and brush_moved and transform_delta_ok and descriptor_transform_delta_ok and brush_delta_ok and screen_payloads_without_legacy_camera_fields_ok and screen_payloads_with_source_transform_overrides_ok and fallback_ok), 'native_core_available': True, 'transform_command': _command_summary(transform.edit_result), 'transform_begin_command': _command_summary(transform_begin.edit_result), 'transform_end_command': _command_summary(transform_end.edit_result), 'descriptor_transform_command': _command_summary(descriptor_transform.edit_result), 'brush_command': _command_summary(brush.edit_result), 'before_transform_vertex': list(before_transform), 'after_transform_vertex': list(after_transform), 'after_descriptor_transform_vertex': list(after_descriptor_transform), 'after_brush_vertex': list(after_brush), 'brush_delta_z': brush_delta_z, 'transform_moved': transform_moved, 'transform_incremental_drag_ok': transform_incremental_drag_ok, 'transform_begin_screen_drag': dict(transform_begin_screen_drag), 'transform_update_screen_drag': dict(transform_screen_drag), 'descriptor_transform_moved': descriptor_transform_moved, 'brush_moved': brush_moved, 'transform_delta_ok': transform_delta_ok, 'descriptor_transform_delta_ok': descriptor_transform_delta_ok, 'brush_delta_ok': brush_delta_ok, 'screen_payloads_without_legacy_camera_fields_ok': screen_payloads_without_legacy_camera_fields_ok, 'screen_payloads_with_source_transform_overrides_ok': screen_payloads_with_source_transform_overrides_ok, 'transform_vertex_group_count': len(transform.native_update.vertex_groups or ()), 'descriptor_transform_vertex_group_count': len(descriptor_transform.native_update.vertex_groups or ()), 'brush_vertex_group_count': len(brush.native_update.vertex_groups or ()), 'native_fallback_ok': fallback_ok, 'native_fallback_counts': fallback_counts, 'native_fallback_events': list(native_mesh_core_fallback_events())}
    finally:
        session.close()
