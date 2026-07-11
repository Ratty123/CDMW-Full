from __future__ import annotations
from collections.abc import Mapping
from cdmw.domain.mesh import MeshEditCommand
from cdmw.domain.mesh import MeshEditSelection
from cdmw.services.mesh_service import MeshService
from cdmw.modding.mesh_native_core import clear_native_mesh_core_fallback_counts
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.modding.mesh_native_core import native_mesh_core_fallback_counts
from cdmw.modding.mesh_native_core import native_mesh_core_fallback_events
import time
from tools.mesh_harness.fixtures import _build_long_edit_mesh, _long_edit_split_selection, _long_edit_topology_selection, _long_edit_vertex_selection, build_native_benchmark_mesh
from tools.mesh_harness.service_summary import _command_summary, _mesh_face_count, _mesh_geometry_signature, _mesh_textures, _mesh_vertex_count, _mesh_vertices_changed, _selection_snapshot

def run_long_edit_mesh_tools() -> dict[str, object]:
    clear_native_mesh_core_fallback_counts()
    native_available = native_mesh_core_available()
    tool_results: list[dict[str, object]] = []
    for action, repeat_count, command_factory in (('move', 6, lambda: MeshEditCommand('transform', selection=_long_edit_vertex_selection(), params={'translate': (0.0, 0.0, 0.04)})), ('grab', 6, lambda: MeshEditCommand('brush', selection=_long_edit_vertex_selection(), mode='sculpt', params={'tool': 'grab', 'center': (0.0, 0.0, 0.2), 'radius': 3.0, 'strength': 0.75, 'delta': (0.0, 0.02, 0.04)})), ('smooth', 6, lambda: MeshEditCommand('brush', selection=_long_edit_vertex_selection(), mode='sculpt', params={'tool': 'smooth', 'center': (0.0, 0.0, 0.2), 'radius': 3.0, 'strength': 0.45, 'iterations': 2})), ('inflate', 6, lambda: MeshEditCommand('brush', selection=_long_edit_vertex_selection(), mode='sculpt', params={'tool': 'inflate', 'center': (0.0, 0.0, 0.2), 'radius': 3.0, 'strength': 0.6, 'amount': 0.04})), ('pinch', 6, lambda: MeshEditCommand('brush', selection=_long_edit_vertex_selection(), mode='sculpt', params={'tool': 'pinch', 'center': (0.0, 0.0, 0.2), 'radius': 3.0, 'strength': 0.65, 'amount': 0.08}))):
        tool_results.append(_run_long_vertex_edit_tool(action, repeat_count, command_factory))
    for action in ('delete', 'subdivide', 'refine_smooth', 'split'):
        for selection_kind in ('face', 'edge', 'vertex'):
            tool_results.append(_run_long_topology_edit_tool(action, selection_kind))
    fallback_counts = native_mesh_core_fallback_counts()
    fallback_events = list(native_mesh_core_fallback_events())
    fallback_ok = not (native_available and fallback_counts)
    failed = [item for item in tool_results if not item.get('ok')]
    return {'ok': bool(not failed and fallback_ok), 'tool_count': len(tool_results), 'failed_tools': [str(item.get('tool', '')) for item in failed] + ([] if fallback_ok else ['native_fallback']), 'native_core_available': native_available, 'native_fallback_ok': fallback_ok, 'native_fallback_counts': fallback_counts, 'native_fallback_events': fallback_events, 'tools': tool_results}

def run_native_mesh_editor_workflow() -> dict[str, object]:
    clear_native_mesh_core_fallback_counts()
    native_available = native_mesh_core_available()
    service = MeshService()
    view = service.open_edit_session(_build_long_edit_mesh(), session_id='native-editor-workflow', mode='edit')
    selection_commands: list[dict[str, object]] = []
    commands: list[dict[str, object]] = []
    counts: list[dict[str, object]] = []

    def count_snapshot(label: str) -> None:
        mesh = service.working_mesh(view.session_id, clone=False)
        counts.append({'label': label, 'vertices': _mesh_vertex_count(mesh), 'faces': _mesh_face_count(mesh), 'undo_count': service.session_view(view.session_id).undo_count, 'redo_count': service.session_view(view.session_id).redo_count})

    def run_command(label: str, command: MeshEditCommand) -> object:
        started = time.perf_counter()
        result = service.apply_command(view.session_id, command)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        summary = _command_summary(result)
        summary['label'] = label
        summary['elapsed_ms'] = elapsed_ms
        commands.append(summary)
        count_snapshot(label)
        return result

    def run_selection_command(label: str, selection: MeshEditSelection, operation: str) -> object:
        started = time.perf_counter()
        result = service.apply_command(view.session_id, MeshEditCommand('select', selection=selection, params={'operation': operation}, mode='edit'))
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        summary = _command_summary(result)
        summary['label'] = label
        summary['elapsed_ms'] = elapsed_ms
        summary['selection'] = _selection_snapshot(service.session_view(view.session_id).selection)
        selection_commands.append(summary)
        return result
    count_snapshot('open')
    selected_one = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}, edges_by_submesh={0: ((0, 1),)}, faces_by_submesh={0: (0,)}, source_indices=(0,))
    selected_all = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3, 4)}, faces_by_submesh={0: (0, 1, 2, 3)}, source_indices=(0,))
    select_replace = run_selection_command('select_replace', selected_one, 'replace')
    select_grow = run_selection_command('select_grow', selected_one, 'grow')
    select_shrink = run_selection_command('select_shrink', selected_all, 'shrink')
    select_smooth = run_selection_command('select_smooth', selected_all, 'smooth')
    delete = run_command('delete', MeshEditCommand('delete', selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), mode='edit'))
    subdivide = run_command('subdivide', MeshEditCommand('subdivide', selection=MeshEditSelection.from_maps(source_indices=(0,)), params={'max_faces_per_submesh': 512, 'recompute_normals': True}, mode='edit'))
    refine = run_command('refine_smooth', MeshEditCommand('refine_smooth', selection=MeshEditSelection.from_maps(source_indices=(0,)), params={'max_faces_per_submesh': 512, 'smooth_iterations': 2, 'smooth_strength': 0.45, 'recompute_normals': True}, mode='edit'))
    vertex_count = len(service.working_mesh(view.session_id, clone=False).submeshes[0].vertices or ())
    brush = run_command('brush', MeshEditCommand('brush', selection=MeshEditSelection.from_maps(vertices_by_submesh={0: tuple(range(vertex_count))}), params={'tool': 'smooth', 'center': (0.0, 0.0, 0.2), 'radius': 3.0, 'strength': 0.45, 'iterations': 2}, mode='sculpt'))
    before_undo = _mesh_geometry_signature(service.working_mesh(view.session_id, clone=False))
    undo_started = time.perf_counter()
    undo = service.undo(view.session_id)
    undo_elapsed_ms = (time.perf_counter() - undo_started) * 1000.0
    undo_summary = _command_summary(undo)
    undo_summary['label'] = 'undo'
    undo_summary['elapsed_ms'] = undo_elapsed_ms
    commands.append(undo_summary)
    count_snapshot('undo')
    after_undo = _mesh_geometry_signature(service.working_mesh(view.session_id, clone=False))
    redo_started = time.perf_counter()
    redo = service.redo(view.session_id)
    redo_elapsed_ms = (time.perf_counter() - redo_started) * 1000.0
    redo_summary = _command_summary(redo)
    redo_summary['label'] = 'redo'
    redo_summary['elapsed_ms'] = redo_elapsed_ms
    commands.append(redo_summary)
    count_snapshot('redo')
    after_redo = _mesh_geometry_signature(service.working_mesh(view.session_id, clone=False))
    fallback_counts = native_mesh_core_fallback_counts()
    fallback_events = list(native_mesh_core_fallback_events())
    fallback_ok = not (native_available and fallback_counts)
    command_ok = all((bool(getattr(result, 'ok', False)) for result in (select_replace, select_grow, select_shrink, select_smooth, delete, subdivide, refine, brush, undo, redo)))
    topology_ok = counts[1]['faces'] < counts[0]['faces'] and counts[2]['faces'] > counts[1]['faces'] and (counts[3]['faces'] >= counts[2]['faces'])
    undo_redo_ok = after_undo != before_undo and after_redo == before_undo
    service.close_edit_session(view.session_id)
    return {'ok': bool(command_ok and topology_ok and undo_redo_ok and fallback_ok), 'native_core_available': native_available, 'native_fallback_ok': fallback_ok, 'native_fallback_counts': fallback_counts, 'native_fallback_events': fallback_events, 'command_ok': command_ok, 'topology_ok': topology_ok, 'undo_redo_ok': undo_redo_ok, 'selection_commands': selection_commands, 'commands': commands, 'counts': counts}

def run_native_mesh_editor_benchmark() -> dict[str, object]:
    clear_native_mesh_core_fallback_counts()
    native_available = native_mesh_core_available()
    build_started = time.perf_counter()
    mesh = build_native_benchmark_mesh()
    build_elapsed_ms = (time.perf_counter() - build_started) * 1000.0
    service = MeshService()
    open_started = time.perf_counter()
    view = service.open_edit_session(mesh, session_id='native-editor-benchmark', mode='edit')
    open_elapsed_ms = (time.perf_counter() - open_started) * 1000.0
    selection_commands: list[dict[str, object]] = []
    commands: list[dict[str, object]] = []
    counts: list[dict[str, object]] = []

    def count_snapshot(label: str) -> None:
        current_view = service.session_view(view.session_id)
        counts.append({'label': label, 'vertices': current_view.vertex_count, 'faces': current_view.face_count, 'undo_count': current_view.undo_count, 'redo_count': current_view.redo_count})

    def run_command(label: str, command: MeshEditCommand) -> object:
        started = time.perf_counter()
        result = service.apply_command(view.session_id, command)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        summary = _command_summary(result)
        summary['label'] = label
        summary['elapsed_ms'] = elapsed_ms
        commands.append(summary)
        count_snapshot(label)
        return result
    count_snapshot('open')
    benchmark_vertex_count = service.session_view(view.session_id).vertex_count

    def run_selection_command(label: str, command: MeshEditCommand) -> object:
        started = time.perf_counter()
        result = service.apply_command(view.session_id, command)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        summary = _command_summary(result)
        summary['label'] = label
        summary['elapsed_ms'] = elapsed_ms
        summary['selected_vertex_count'] = sum((len(values) for _, values in service.session_view(view.session_id).selection.vertices_by_submesh))
        selection_commands.append(summary)
        return result
    select_grow_source = run_selection_command('select_grow_source_100k', MeshEditCommand('select', selection=MeshEditSelection.from_maps(source_indices=(0,)), params={'operation': 'grow'}, mode='edit'))
    select_smooth_local = run_selection_command('select_smooth_local_512', MeshEditCommand('select', selection=MeshEditSelection.from_maps(vertices_by_submesh={0: tuple(range(min(512, benchmark_vertex_count)))}), params={'operation': 'smooth'}, mode='edit'))
    delete = run_command('delete', MeshEditCommand('delete', selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), params={'_include_preview_deltas': False}, mode='edit'))
    subdivide = run_command('subdivide', MeshEditCommand('subdivide', selection=MeshEditSelection.from_maps(source_indices=(0,)), params={'max_faces_per_submesh': 512, 'recompute_normals': True, '_include_preview_deltas': False}, mode='edit'))
    refine = run_command('refine_smooth', MeshEditCommand('refine_smooth', selection=MeshEditSelection.from_maps(source_indices=(0,)), params={'max_faces_per_submesh': 512, 'smooth_iterations': 1, 'smooth_strength': 0.35, 'recompute_normals': True, '_include_preview_deltas': False}, mode='edit'))
    vertex_count = service.session_view(view.session_id).vertex_count
    brush_selection = tuple(range(min(32, vertex_count)))
    brush = run_command('brush', MeshEditCommand('brush', selection=MeshEditSelection.from_maps(vertices_by_submesh={0: brush_selection}), params={'tool': 'grab', 'center': (16.0, 0.0, 0.0), 'radius': 8.0, 'strength': 0.5, 'delta': (0.0, 0.0, 0.05)}, mode='sculpt'))
    undo = service.undo(view.session_id)
    undo_summary = _command_summary(undo)
    undo_summary['label'] = 'undo'
    commands.append(undo_summary)
    count_snapshot('undo')
    redo = service.redo(view.session_id)
    redo_summary = _command_summary(redo)
    redo_summary['label'] = 'redo'
    commands.append(redo_summary)
    count_snapshot('redo')
    fallback_counts = native_mesh_core_fallback_counts()
    fallback_events = list(native_mesh_core_fallback_events())
    fallback_ok = not (native_available and fallback_counts)
    command_ok = all((bool(getattr(result, 'ok', False)) for result in (select_grow_source, select_smooth_local, delete, subdivide, refine, brush, undo, redo)))
    benchmark_target_ok = counts[0]['vertices'] >= 100000 and counts[0]['faces'] >= 200000
    topology_ok = counts[1]['faces'] < counts[0]['faces'] and counts[2]['faces'] > counts[1]['faces'] and (counts[3]['faces'] >= counts[2]['faces'])
    brush_changed_ok = bool(commands[3].get('affected_submesh_indices'))
    brush_elapsed_ms = float(commands[3].get('elapsed_ms', 0.0) or 0.0)
    normal_edit_target_ok = brush_elapsed_ms < 250.0
    selection_metrics_ok = all((isinstance(item.get('metrics'), Mapping) and 'cpp_ms' in item['metrics'] for item in selection_commands))
    native_roundtrip_metrics_ok = all((isinstance(item.get('metrics'), Mapping) and 'native_apply_roundtrip_ms' in item['metrics'] and ('native_apply_overhead_ms' in item['metrics']) and ('service_total_ms' in item['metrics']) for item in commands[:4]))
    native_history_metrics_ok = all((isinstance(item.get('metrics'), Mapping) and 'native_history_roundtrip_ms' in item['metrics'] and ('service_total_ms' in item['metrics']) for item in commands[4:6]))
    selection_local_elapsed_ms = float(selection_commands[1].get('elapsed_ms', 0.0) or 0.0) if len(selection_commands) > 1 else 0.0
    selection_local_target_ok = 0.0 < selection_local_elapsed_ms < 250.0
    service.close_edit_session(view.session_id)
    return {'ok': bool(command_ok and benchmark_target_ok and topology_ok and brush_changed_ok and normal_edit_target_ok and selection_metrics_ok and native_roundtrip_metrics_ok and native_history_metrics_ok and selection_local_target_ok and fallback_ok), 'native_core_available': native_available, 'native_fallback_ok': fallback_ok, 'native_fallback_counts': fallback_counts, 'native_fallback_events': fallback_events, 'build_elapsed_ms': build_elapsed_ms, 'open_elapsed_ms': open_elapsed_ms, 'command_ok': command_ok, 'benchmark_target_ok': benchmark_target_ok, 'topology_ok': topology_ok, 'brush_changed_ok': brush_changed_ok, 'normal_edit_target_ok': normal_edit_target_ok, 'normal_edit_elapsed_ms': brush_elapsed_ms, 'selection_metrics_ok': selection_metrics_ok, 'native_roundtrip_metrics_ok': native_roundtrip_metrics_ok, 'native_history_metrics_ok': native_history_metrics_ok, 'selection_local_target_ok': selection_local_target_ok, 'selection_local_elapsed_ms': selection_local_elapsed_ms, 'selection_commands': selection_commands, 'commands': commands, 'counts': counts}

def _run_long_vertex_edit_tool(action: str, repeat_count: int, command_factory: object) -> dict[str, object]:
    service = MeshService()
    view = service.open_edit_session(_build_long_edit_mesh(), session_id=f'long-edit-{action}', mode='edit')
    before = service.working_mesh(view.session_id, clone=True)
    texture_before = _mesh_textures(before)
    commands: list[dict[str, object]] = []
    started = time.perf_counter()
    for _index in range(int(repeat_count)):
        command = command_factory()
        result = service.apply_command(view.session_id, command)
        commands.append(_command_summary(result))
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    after = service.working_mesh(view.session_id, clone=True)
    service.apply_command(view.session_id, MeshEditCommand('set_mode', mode='object'))
    service.apply_command(view.session_id, MeshEditCommand('set_mode', mode='edit'))
    toggled = service.working_mesh(view.session_id, clone=True)
    service.close_edit_session(view.session_id)
    changed = _mesh_vertices_changed(before, toggled)
    toggle_persistence_ok = _mesh_geometry_signature(after) == _mesh_geometry_signature(toggled)
    texture_ok = _mesh_textures(toggled) == texture_before
    command_ok = all((command['status'] == 'ok' for command in commands))
    return {'tool': action, 'ok': bool(command_ok and changed and toggle_persistence_ok and texture_ok), 'repeat_count': int(repeat_count), 'elapsed_ms': elapsed_ms, 'command_ok': command_ok, 'changed_vertices': changed, 'toggle_persistence_ok': toggle_persistence_ok, 'texture_ok': texture_ok, 'face_count_before': _mesh_face_count(before), 'face_count_after': _mesh_face_count(after), 'commands': commands}

def _run_long_topology_edit_tool(action: str, selection_kind: str) -> dict[str, object]:
    service = MeshService()
    view = service.open_edit_session(_build_long_edit_mesh(), session_id=f'long-edit-{action}-{selection_kind}', mode='edit')
    before = service.working_mesh(view.session_id, clone=True)
    texture_before = _mesh_textures(before)
    params: dict[str, object] = {'recompute_normals': True}
    if action in {'subdivide', 'refine_smooth'}:
        params.update({'max_faces_per_submesh': 512, 'smooth_iterations': 2, 'smooth_strength': 0.45})
    started = time.perf_counter()
    selection = _long_edit_split_selection(selection_kind) if action == 'split' else _long_edit_topology_selection(selection_kind)
    result = service.apply_command(view.session_id, MeshEditCommand(action, selection=selection, params=params))
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    after = service.working_mesh(view.session_id, clone=True)
    service.apply_command(view.session_id, MeshEditCommand('set_mode', mode='object'))
    service.apply_command(view.session_id, MeshEditCommand('set_mode', mode='edit'))
    toggled = service.working_mesh(view.session_id, clone=True)
    service.close_edit_session(view.session_id)
    before_faces = _mesh_face_count(before)
    toggled_faces = _mesh_face_count(toggled)
    before_vertices = _mesh_vertex_count(before)
    toggled_vertices = _mesh_vertex_count(toggled)
    if action == 'delete':
        topology_delta_ok = toggled_faces < before_faces
    elif action == 'split':
        topology_delta_ok = toggled_vertices > before_vertices and toggled_faces == before_faces
    else:
        topology_delta_ok = toggled_faces > before_faces
    toggle_persistence_ok = _mesh_geometry_signature(after) == _mesh_geometry_signature(toggled)
    texture_ok = _mesh_textures(toggled) == texture_before
    return {'tool': f'{action}_{selection_kind}', 'ok': bool(result.ok and topology_delta_ok and toggle_persistence_ok and texture_ok), 'elapsed_ms': elapsed_ms, 'command': _command_summary(result), 'topology_delta_ok': topology_delta_ok, 'toggle_persistence_ok': toggle_persistence_ok, 'texture_ok': texture_ok, 'face_count_before': before_faces, 'face_count_after': toggled_faces, 'submesh_count_before': len(before.submeshes), 'submesh_count_after': len(toggled.submeshes), 'vertex_count_before': before_vertices, 'vertex_count_after': toggled_vertices}
