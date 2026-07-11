from __future__ import annotations
from types import SimpleNamespace
from tools.mesh_harness.phase_support import PhaseResult
from collections.abc import Mapping
from cdmw.domain.mesh import MeshEditSelection
from cdmw.modding.mesh_parser import ParsedMesh
from pathlib import Path
from cdmw.rendering.native_d3d11_host import find_native_d3d11_host
import math
from cdmw.ui.mesh_editor.native_preview_payloads import mesh_edit_material_override_groups
from cdmw.ui.mesh_editor.native_preview_payloads import mesh_edit_selection_groups
from cdmw.ui.mesh_editor.native_preview_payloads import mesh_edit_triangle_groups
from cdmw.ui.mesh_editor.native_preview_payloads import mesh_edit_vertex_update_groups
from cdmw.ui.mesh_editor.native_preview_runtime import mesh_editor_write_native_preview_package
import os
import subprocess
import time
from tools.mesh_harness.constants import _LEGACY_SCREEN_CAMERA_FIELDS, _MK_LBUTTON, _WM_LBUTTONDOWN, _WM_LBUTTONUP, _WM_MOUSEMOVE
from tools.mesh_harness.fixtures import _build_two_part_synthetic_mesh, _selection_edges_from_group
from tools.mesh_harness.native_projection import _screen_source_transform_override_ok
from tools.mesh_harness.native_protocol import _close_process, _place_host_window_on_screen1, _send_json_command, _send_mouse_message, _wait_for_file, _wait_for_host_window, _wait_for_status
from tools.mesh_harness.png_evidence import _png_capture_summary, _write_checker_png

def _native_smoke_phase_1(state: SimpleNamespace) -> PhaseResult | None:
    state.loaded = _wait_for_status(state.status_file, {'loaded', 'resources_loaded'}, state.timeout_seconds)
    state.loaded_ok = state.loaded.get('event') in {'loaded', 'resources_loaded'}
    state.hwnd = _wait_for_host_window(state.process.pid, state.timeout_seconds)
    _place_host_window_on_screen1(state.hwnd)
    state.status_file.unlink(missing_ok=True)
    state.texture_status_before_sent = _send_json_command(state.hwnd, {'command': 'get_status'})
    state.texture_status_before = _wait_for_status(state.status_file, {'status'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.mesh_edit_enable_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_state', 'enabled': True, 'source_submesh_indices': [0], 'target_mode': 'brush', 'tool': 'grab'})
    state.mesh_edit_enable_status = _wait_for_status(state.status_file, {'mesh_edit_state'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.texture_status_enabled_sent = _send_json_command(state.hwnd, {'command': 'get_status'})
    state.texture_status_enabled = _wait_for_status(state.status_file, {'status'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.alignment_transform_sent = _send_json_command(state.hwnd, {'command': 'set_alignment_transforms', 'parts': [{'source_submesh_indices': [0], 'translation': [0.01, 0.0, 0.0], 'rotation_degrees': [0.0, 0.0, 0.0], 'scale_xyz': [1.01, 1.0, 1.0]}]})
    state.alignment_transform_status = _wait_for_status(state.status_file, {'alignment_transforms'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.grab_brush_target_down_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONDOWN, 440, 360, wparam=_MK_LBUTTON)
    state.grab_brush_target_started_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_started'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.grab_brush_target_move_sent = _send_mouse_message(state.hwnd, _WM_MOUSEMOVE, 472, 360, wparam=_MK_LBUTTON)
    state.grab_brush_target_preview_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_previewed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.grab_brush_target_up_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONUP, 472, 360)
    state.grab_brush_target_finished_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_finished'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.commands = [{'command': 'set_mesh_edit_selection', 'groups': mesh_edit_selection_groups(state.mesh, MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2)}))}, {'command': 'update_mesh_edit_vertices', 'groups': mesh_edit_vertex_update_groups(state.mesh, {0: (0, 1, 2)})}, {'command': 'set_material_overrides', **(mesh_edit_material_override_groups(state.mesh, (0,))[0] if mesh_edit_material_override_groups(state.mesh, (0,)) else {})}, {'command': 'replace_mesh_edit_triangles', 'groups': mesh_edit_triangle_groups(state.mesh), 'replace_all': True}]
    state.sent = [_send_json_command(state.hwnd, command) for command in state.commands]
    state.sent.extend((state.texture_status_before_sent, state.mesh_edit_enable_sent, state.texture_status_enabled_sent, state.alignment_transform_sent, state.grab_brush_target_down_sent, state.grab_brush_target_move_sent, state.grab_brush_target_up_sent))
    state.status_file.unlink(missing_ok=True)
    state.face_selection_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_selection', 'groups': [{'source_submesh_index': 0, 'source_face_indices': [0]}]})
    state.face_selection_status = _wait_for_status(state.status_file, {'mesh_edit_selection_changed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.face_region_sent = _send_json_command(state.hwnd, {'command': 'select_mesh_edit_region', 'target_mode': 'face', 'selection_mode': 'rectangle', 'selection_depth_mode': 'xray', 'start_x': 120, 'start_y': 90, 'end_x': 860, 'end_y': 630})
    state.face_region_status = _wait_for_status(state.status_file, {'mesh_edit_selection_changed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.edge_selection_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_selection', 'groups': [{'source_submesh_index': 0, 'source_edges': [[0, 1], [2, 3]]}]})
    state.edge_selection_status = _wait_for_status(state.status_file, {'mesh_edit_selection_changed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.source_selection_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_selection', 'groups': [{'source_submesh_index': 0, 'source_selected': True}]})
    state.source_selection_status = _wait_for_status(state.status_file, {'mesh_edit_selection_changed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.source_screen_selection_sent = _send_json_command(state.hwnd, {'command': 'select_mesh_edit_brush', 'target_mode': 'source', 'operation': 'replace', 'selection_depth_mode': 'xray', 'x': 440, 'y': 360})
    state.source_screen_selection_status = _wait_for_status(state.status_file, {'mesh_edit_selection_changed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.empty_selection_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_selection', 'groups': []})
    state.empty_selection_status = _wait_for_status(state.status_file, {'mesh_edit_selection_changed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.move_screen_selection_state_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_state', 'enabled': True, 'source_submesh_indices': [0], 'target_mode': 'selection', 'tool': 'move', 'selection_mode': 'brush', 'radius_pixels': 96})
    state.move_screen_selection_state_status = _wait_for_status(state.status_file, {'mesh_edit_state'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.move_screen_selection_down_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONDOWN, 440, 360, wparam=_MK_LBUTTON)
    state.move_screen_selection_started_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_started'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.move_screen_selection_up_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONUP, 440, 360)
    state.move_screen_selection_finished_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_finished'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.grab_screen_selection_state_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_state', 'enabled': True, 'source_submesh_indices': [0], 'target_mode': 'selection', 'tool': 'grab', 'selection_mode': 'brush', 'radius_pixels': 96, 'strength': 0.5})
    state.grab_screen_selection_state_status = _wait_for_status(state.status_file, {'mesh_edit_state'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.grab_screen_selection_down_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONDOWN, 440, 360, wparam=_MK_LBUTTON)
    state.grab_screen_selection_started_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_started'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.grab_screen_selection_up_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONUP, 440, 360)
    state.grab_screen_selection_finished_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_finished'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.selected_drag_selection_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_selection', 'groups': mesh_edit_selection_groups(state.mesh, MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2)}))})
    state.selected_drag_selection_status = _wait_for_status(state.status_file, {'mesh_edit_selection_changed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.selected_move_state_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_state', 'enabled': True, 'source_submesh_indices': [0], 'target_mode': 'selection', 'tool': 'move', 'selection_mode': 'brush', 'radius_pixels': 96})
    state.selected_move_state_status = _wait_for_status(state.status_file, {'mesh_edit_state'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.selected_move_down_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONDOWN, 440, 360, wparam=_MK_LBUTTON)
    state.selected_move_started_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_started'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.selected_move_move_sent = _send_mouse_message(state.hwnd, _WM_MOUSEMOVE, 472, 360, wparam=_MK_LBUTTON)
    state.selected_move_preview_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_previewed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.selected_move_up_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONUP, 472, 360)
    state.selected_move_finished_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_finished'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.selected_grab_selection_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_selection', 'groups': mesh_edit_selection_groups(state.mesh, MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2)}))})
    state.selected_grab_selection_status = _wait_for_status(state.status_file, {'mesh_edit_selection_changed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.selected_grab_state_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_state', 'enabled': True, 'source_submesh_indices': [0], 'target_mode': 'selection', 'tool': 'grab', 'selection_mode': 'brush', 'radius_pixels': 96, 'strength': 0.5})
    state.selected_grab_state_status = _wait_for_status(state.status_file, {'mesh_edit_state'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.selected_grab_down_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONDOWN, 440, 360, wparam=_MK_LBUTTON)
    state.selected_grab_started_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_started'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.selected_grab_move_sent = _send_mouse_message(state.hwnd, _WM_MOUSEMOVE, 472, 360, wparam=_MK_LBUTTON)
    state.selected_grab_preview_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_previewed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.selected_grab_up_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONUP, 472, 360)
    state.selected_grab_finished_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_finished'}, state.timeout_seconds)
    return None

def _native_smoke_phase_2(state: SimpleNamespace) -> PhaseResult | None:
    state.edge_brush_state_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_state', 'enabled': True, 'source_submesh_indices': [0], 'target_mode': 'edge', 'tool': 'vertex', 'selection_mode': 'brush', 'selection_depth_mode': 'xray', 'radius_pixels': 96})
    state.status_file.unlink(missing_ok=True)
    state.edge_brush_sent = _send_json_command(state.hwnd, {'command': 'select_mesh_edit_brush', 'x': 490, 'y': 360})
    state.edge_brush_status = _wait_for_status(state.status_file, {'mesh_edit_selection_changed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.drag_selection_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_selection', 'groups': [{'source_submesh_index': 0, 'source_vertex_indices': [0, 1]}]})
    state.drag_selection_status = _wait_for_status(state.status_file, {'mesh_edit_selection_changed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.drag_state_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_state', 'enabled': True, 'source_submesh_indices': [0], 'target_mode': 'selection', 'tool': 'move', 'selection_mode': 'brush', 'radius_pixels': 96})
    state.drag_state_status = _wait_for_status(state.status_file, {'mesh_edit_state'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.stroke_down_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONDOWN, 440, 360, wparam=_MK_LBUTTON)
    state.stroke_started_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_started'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.stroke_move_sent = _send_mouse_message(state.hwnd, _WM_MOUSEMOVE, 472, 360, wparam=_MK_LBUTTON)
    state.stroke_preview_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_previewed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.stroke_up_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONUP, 472, 360)
    state.stroke_finished_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_finished'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.brush_stroke_state_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_state', 'enabled': True, 'source_submesh_indices': [0], 'target_mode': 'selection', 'tool': 'grab', 'selection_mode': 'brush', 'radius_pixels': 96, 'strength': 0.5})
    state.brush_stroke_state_status = _wait_for_status(state.status_file, {'mesh_edit_state'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.brush_stroke_down_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONDOWN, 440, 360, wparam=_MK_LBUTTON)
    state.brush_stroke_started_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_started'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.brush_stroke_move_sent = _send_mouse_message(state.hwnd, _WM_MOUSEMOVE, 472, 360, wparam=_MK_LBUTTON)
    state.brush_stroke_preview_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_previewed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.brush_stroke_up_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONUP, 472, 360)
    state.brush_stroke_finished_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_finished'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.smooth_stroke_state_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_state', 'enabled': True, 'source_submesh_indices': [0], 'target_mode': 'selection', 'tool': 'smooth', 'selection_mode': 'brush', 'radius_pixels': 96, 'strength': 0.5, 'smooth_iterations': 2})
    state.smooth_stroke_state_status = _wait_for_status(state.status_file, {'mesh_edit_state'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.smooth_stroke_down_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONDOWN, 440, 360, wparam=_MK_LBUTTON)
    state.smooth_stroke_started_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_started'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.smooth_stroke_move_sent = _send_mouse_message(state.hwnd, _WM_MOUSEMOVE, 472, 360, wparam=_MK_LBUTTON)
    state.smooth_stroke_preview_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_previewed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.smooth_stroke_up_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONUP, 472, 360)
    state.smooth_stroke_finished_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_finished'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.inflate_stroke_state_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_state', 'enabled': True, 'source_submesh_indices': [0], 'target_mode': 'selection', 'tool': 'inflate', 'selection_mode': 'brush', 'radius_pixels': 96, 'strength': 0.5})
    state.inflate_stroke_state_status = _wait_for_status(state.status_file, {'mesh_edit_state'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.inflate_stroke_down_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONDOWN, 440, 360, wparam=_MK_LBUTTON)
    state.inflate_stroke_started_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_started'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.inflate_stroke_move_sent = _send_mouse_message(state.hwnd, _WM_MOUSEMOVE, 472, 360, wparam=_MK_LBUTTON)
    state.inflate_stroke_preview_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_previewed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.inflate_stroke_up_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONUP, 472, 360)
    state.inflate_stroke_finished_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_finished'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.remove_release_state_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_state', 'enabled': True, 'source_submesh_indices': [0], 'target_mode': 'brush', 'tool': 'remove', 'delete_mode': 'release', 'selection_mode': 'brush', 'selection_depth_mode': 'xray', 'radius_pixels': 96})
    state.remove_release_state_status = _wait_for_status(state.status_file, {'mesh_edit_state'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.remove_release_down_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONDOWN, 440, 360, wparam=_MK_LBUTTON)
    state.remove_release_started_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_started'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.remove_release_move_sent = _send_mouse_message(state.hwnd, _WM_MOUSEMOVE, 472, 360, wparam=_MK_LBUTTON)
    state.remove_release_preview_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_previewed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.remove_release_up_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONUP, 472, 360)
    state.remove_release_finished_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_finished'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.remove_live_state_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_state', 'enabled': True, 'source_submesh_indices': [0], 'target_mode': 'brush', 'tool': 'remove', 'delete_mode': 'live', 'selection_mode': 'brush', 'selection_depth_mode': 'xray', 'radius_pixels': 96})
    state.remove_live_state_status = _wait_for_status(state.status_file, {'mesh_edit_state'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.remove_live_down_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONDOWN, 440, 360, wparam=_MK_LBUTTON)
    state.remove_live_started_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_started'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.remove_live_move_sent = _send_mouse_message(state.hwnd, _WM_MOUSEMOVE, 472, 360, wparam=_MK_LBUTTON)
    state.remove_live_preview_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_previewed'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.remove_live_up_sent = _send_mouse_message(state.hwnd, _WM_LBUTTONUP, 472, 360)
    state.remove_live_finished_status = _wait_for_status(state.status_file, {'mesh_edit_stroke_finished'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.drag_restore_state_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_state', 'enabled': True, 'source_submesh_indices': [0], 'target_mode': 'edge', 'tool': 'vertex', 'selection_mode': 'brush', 'selection_depth_mode': 'xray', 'radius_pixels': 96})
    state.drag_restore_state_status = _wait_for_status(state.status_file, {'mesh_edit_state'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.brush_drag_status_before_sent = _send_json_command(state.hwnd, {'command': 'get_status'})
    state.brush_drag_status_before = _wait_for_status(state.status_file, {'status'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.brush_drag_started_at = time.monotonic()
    state.brush_drag_messages = [_send_mouse_message(state.hwnd, _WM_LBUTTONDOWN, 440, 360, wparam=_MK_LBUTTON)]
    state.brush_drag_messages.extend((_send_mouse_message(state.hwnd, _WM_MOUSEMOVE, 440 + step * 4, 360, wparam=_MK_LBUTTON) for step in range(1, 61)))
    state.brush_drag_messages.append(_send_mouse_message(state.hwnd, _WM_LBUTTONUP, 684, 360))
    state.brush_drag_elapsed_ms = (time.monotonic() - state.brush_drag_started_at) * 1000.0
    state.brush_drag_status_after_sent = _send_json_command(state.hwnd, {'command': 'get_status'})
    state.brush_drag_status_after = _wait_for_status(state.status_file, {'status'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.created_part_sent = _send_json_command(state.hwnd, {'command': 'replace_mesh_edit_triangles', 'groups': mesh_edit_triangle_groups(_build_two_part_synthetic_mesh(), (1,))})
    state.created_part_status = _wait_for_status(state.status_file, {'mesh_edit_triangles_replaced'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.pruned_part_sent = _send_json_command(state.hwnd, {'command': 'replace_mesh_edit_triangles', 'groups': mesh_edit_triangle_groups(state.mesh), 'replace_all': True})
    state.pruned_part_status = _wait_for_status(state.status_file, {'mesh_edit_triangles_replaced'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.mesh_edit_disable_sent = _send_json_command(state.hwnd, {'command': 'set_mesh_edit_state', 'enabled': False})
    state.mesh_edit_disable_status = _wait_for_status(state.status_file, {'mesh_edit_state'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.texture_status_disabled_sent = _send_json_command(state.hwnd, {'command': 'get_status'})
    state.texture_status_disabled = _wait_for_status(state.status_file, {'status'}, state.timeout_seconds)
    state.status_file.unlink(missing_ok=True)
    state.capture_sent = _send_json_command(state.hwnd, {'command': 'capture_frame', 'path': str(state.capture_path)})
    state.sent.extend((state.face_selection_sent, state.face_region_sent, state.edge_selection_sent, state.source_selection_sent, state.source_screen_selection_sent, state.empty_selection_sent, state.move_screen_selection_state_sent, state.move_screen_selection_down_sent, state.move_screen_selection_up_sent, state.grab_screen_selection_state_sent, state.grab_screen_selection_down_sent, state.grab_screen_selection_up_sent, state.selected_drag_selection_sent, state.selected_move_state_sent, state.selected_move_down_sent, state.selected_move_move_sent, state.selected_move_up_sent, state.selected_grab_selection_sent, state.selected_grab_state_sent, state.selected_grab_down_sent, state.selected_grab_move_sent, state.selected_grab_up_sent, state.edge_brush_state_sent, state.edge_brush_sent, state.drag_selection_sent, state.drag_state_sent, state.stroke_down_sent, state.stroke_move_sent, state.stroke_up_sent, state.brush_stroke_state_sent, state.brush_stroke_down_sent, state.brush_stroke_move_sent, state.brush_stroke_up_sent, state.smooth_stroke_state_sent, state.smooth_stroke_down_sent, state.smooth_stroke_move_sent, state.smooth_stroke_up_sent, state.inflate_stroke_state_sent, state.inflate_stroke_down_sent, state.inflate_stroke_move_sent, state.inflate_stroke_up_sent, state.remove_release_state_sent, state.remove_release_down_sent, state.remove_release_move_sent, state.remove_release_up_sent, state.remove_live_state_sent, state.remove_live_down_sent, state.remove_live_move_sent, state.remove_live_up_sent, state.drag_restore_state_sent, state.brush_drag_status_before_sent, *state.brush_drag_messages, state.brush_drag_status_after_sent, state.created_part_sent, state.pruned_part_sent, state.mesh_edit_disable_sent, state.texture_status_disabled_sent, state.capture_sent))
    return None

def _native_smoke_phase_3(state: SimpleNamespace) -> PhaseResult | None:
    state.captured = _wait_for_file(state.capture_path, state.timeout_seconds)
    state.capture_summary = _png_capture_summary(state.capture_path) if state.captured else {'ok': False, 'error': 'capture missing'}
    state.face_payload = dict(state.face_selection_status.get('payload', {}) or {})
    state.face_selection_ok = int(state.face_payload.get('selected_vertex_count', 0) or 0) >= 3 and int(state.face_payload.get('selected_face_count', 0) or 0) >= 1
    state.face_region_payload = dict(state.face_region_status.get('payload', {}) or {})
    state.raw_face_region_screen_region = state.face_region_payload.get('screen_region')
    state.face_region_screen_region = dict(state.raw_face_region_screen_region) if isinstance(state.raw_face_region_screen_region, Mapping) else {}
    state.face_region_world_view_projection = tuple(state.face_region_screen_region.get('world_view_projection') or ())
    state.face_region_world_view_projection_ok = len(state.face_region_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.face_region_world_view_projection))
    state.face_region_ok = state.face_region_status.get('event') == 'mesh_edit_selection_changed' and str(state.face_region_payload.get('target_mode') or '').strip().lower() == 'face' and (str(state.face_region_payload.get('selection_depth_mode') or '').strip().lower() in {'visible', 'xray'}) and ('groups' not in state.face_region_payload) and ('screen_region' in state.face_region_payload) and all((field in state.face_region_screen_region for field in ('mode', 'start_x', 'start_y', 'end_x', 'end_y', 'viewport_width', 'viewport_height'))) and state.face_region_world_view_projection_ok
    state.edge_payload = dict(state.edge_selection_status.get('payload', {}) or {})
    state.edge_groups = tuple(state.edge_payload.get('groups') or ())
    state.edge_selection_edges = [edge for group in state.edge_groups if isinstance(group, Mapping) for edge in _selection_edges_from_group(group)]
    state.edge_selection_ok = int(state.edge_payload.get('selected_vertex_count', 0) or 0) >= 4 and int(state.edge_payload.get('selected_edge_count', 0) or 0) >= 2 and ((0, 1) in state.edge_selection_edges) and ((2, 3) in state.edge_selection_edges)
    state.source_payload = dict(state.source_selection_status.get('payload', {}) or {})
    state.source_groups = tuple(state.source_payload.get('groups') or ())
    state.source_selected_groups = [group for group in state.source_groups if isinstance(group, Mapping) and group.get('source_selected') is True]
    state.source_selection_compact = bool(state.source_selected_groups) and all(('source_vertex_indices' not in group and 'source_vertex_indices_binary' not in group and ('source_vertex_start' not in group) and ('source_vertex_count' not in group) for group in state.source_selected_groups))
    state.source_selection_ok = int(state.source_payload.get('selected_vertex_count', 0) or 0) >= len(state.mesh.submeshes[0].vertices) and state.source_selection_compact
    state.source_screen_selection_payload = dict(state.source_screen_selection_status.get('payload', {}) or {})
    state.raw_source_screen_brush = state.source_screen_selection_payload.get('screen_brush')
    state.source_screen_brush = dict(state.raw_source_screen_brush) if isinstance(state.raw_source_screen_brush, Mapping) else {}
    state.source_screen_world_view_projection = tuple(state.source_screen_brush.get('world_view_projection') or ())
    state.source_screen_world_view_projection_ok = len(state.source_screen_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.source_screen_world_view_projection))
    state.source_screen_selection_ok = state.source_screen_selection_status.get('event') == 'mesh_edit_selection_changed' and str(state.source_screen_selection_payload.get('target_mode') or '').strip().lower() == 'source' and (str(state.source_screen_selection_payload.get('selection_depth_mode') or '').strip().lower() == 'xray') and ('screen_brush' in state.source_screen_selection_payload) and ('groups' not in state.source_screen_selection_payload) and all((field in state.source_screen_brush for field in ('x', 'y', 'radius_pixels', 'viewport_width', 'viewport_height'))) and state.source_screen_world_view_projection_ok
    state.move_screen_selection_payload = dict(state.move_screen_selection_started_status.get('payload', {}) or {})
    state.raw_move_screen_brush = state.move_screen_selection_payload.get('screen_brush')
    state.move_screen_brush = dict(state.raw_move_screen_brush) if isinstance(state.raw_move_screen_brush, Mapping) else {}
    state.raw_move_screen_drag = state.move_screen_selection_payload.get('screen_drag')
    state.move_screen_drag = dict(state.raw_move_screen_drag) if isinstance(state.raw_move_screen_drag, Mapping) else {}
    state.move_screen_selection_world_view_projection = tuple(state.move_screen_brush.get('world_view_projection') or ())
    state.move_screen_selection_world_view_projection_ok = len(state.move_screen_selection_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.move_screen_selection_world_view_projection))
    state.move_screen_selection_ok = state.move_screen_selection_state_status.get('event') == 'mesh_edit_state' and state.move_screen_selection_started_status.get('event') == 'mesh_edit_stroke_started' and (state.move_screen_selection_finished_status.get('event') == 'mesh_edit_stroke_finished') and (str(state.move_screen_selection_payload.get('tool') or '').strip().lower() == 'move') and (str(state.move_screen_selection_payload.get('target_mode') or '').strip().lower() == 'vertex') and ('groups' not in state.move_screen_selection_payload) and ('screen_brush' in state.move_screen_selection_payload) and ('screen_drag' in state.move_screen_selection_payload) and ('center' not in state.move_screen_selection_payload) and all((field in state.move_screen_brush for field in ('x', 'y', 'radius_pixels', 'viewport_width', 'viewport_height'))) and all((field in state.move_screen_drag for field in ('start_x', 'start_y', 'end_x', 'end_y'))) and state.move_screen_selection_world_view_projection_ok
    state.grab_screen_selection_payload = dict(state.grab_screen_selection_started_status.get('payload', {}) or {})
    state.raw_grab_selection_screen_brush = state.grab_screen_selection_payload.get('screen_brush')
    state.grab_selection_screen_brush = dict(state.raw_grab_selection_screen_brush) if isinstance(state.raw_grab_selection_screen_brush, Mapping) else {}
    state.raw_grab_selection_screen_drag = state.grab_screen_selection_payload.get('screen_drag')
    state.grab_selection_screen_drag = dict(state.raw_grab_selection_screen_drag) if isinstance(state.raw_grab_selection_screen_drag, Mapping) else {}
    state.grab_screen_selection_world_view_projection = tuple(state.grab_selection_screen_brush.get('world_view_projection') or ())
    state.grab_screen_selection_world_view_projection_ok = len(state.grab_screen_selection_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.grab_screen_selection_world_view_projection))
    state.grab_screen_selection_ok = state.grab_screen_selection_state_status.get('event') == 'mesh_edit_state' and state.grab_screen_selection_started_status.get('event') == 'mesh_edit_stroke_started' and (state.grab_screen_selection_finished_status.get('event') == 'mesh_edit_stroke_finished') and (str(state.grab_screen_selection_payload.get('tool') or '').strip().lower() == 'grab') and (str(state.grab_screen_selection_payload.get('target_mode') or '').strip().lower() == 'vertex') and ('groups' not in state.grab_screen_selection_payload) and ('screen_brush' in state.grab_screen_selection_payload) and ('screen_drag' in state.grab_screen_selection_payload) and ('strength' in state.grab_screen_selection_payload) and ('center' not in state.grab_screen_selection_payload) and all((field in state.grab_selection_screen_brush for field in ('x', 'y', 'radius_pixels', 'viewport_width', 'viewport_height'))) and all((field in state.grab_selection_screen_drag for field in ('start_x', 'start_y', 'end_x', 'end_y'))) and state.grab_screen_selection_world_view_projection_ok
    state.selected_move_started_payload = dict(state.selected_move_started_status.get('payload', {}) or {})
    state.selected_move_preview_payload = dict(state.selected_move_preview_status.get('payload', {}) or {})
    state.selected_move_resident_selection_ok = state.selected_drag_selection_status.get('event') == 'mesh_edit_selection_changed' and state.selected_move_state_status.get('event') == 'mesh_edit_state' and (state.selected_move_started_status.get('event') == 'mesh_edit_stroke_started') and (state.selected_move_preview_status.get('event') == 'mesh_edit_stroke_previewed') and (state.selected_move_finished_status.get('event') == 'mesh_edit_stroke_finished') and (str(state.selected_move_started_payload.get('tool') or '').strip().lower() == 'move') and (str(state.selected_move_preview_payload.get('tool') or '').strip().lower() == 'move') and ('groups' not in state.selected_move_started_payload) and ('groups' not in state.selected_move_preview_payload) and ('screen_drag' in state.selected_move_started_payload) and ('screen_drag' in state.selected_move_preview_payload) and ('screen_brush' not in state.selected_move_started_payload) and ('screen_brush' not in state.selected_move_preview_payload) and ('center' not in state.selected_move_started_payload) and ('center' not in state.selected_move_preview_payload)
    state.selected_grab_started_payload = dict(state.selected_grab_started_status.get('payload', {}) or {})
    state.selected_grab_preview_payload = dict(state.selected_grab_preview_status.get('payload', {}) or {})
    state.selected_grab_resident_selection_ok = state.selected_grab_selection_status.get('event') == 'mesh_edit_selection_changed' and state.selected_grab_state_status.get('event') == 'mesh_edit_state' and (state.selected_grab_started_status.get('event') == 'mesh_edit_stroke_started') and (state.selected_grab_preview_status.get('event') == 'mesh_edit_stroke_previewed') and (state.selected_grab_finished_status.get('event') == 'mesh_edit_stroke_finished') and (str(state.selected_grab_started_payload.get('tool') or '').strip().lower() == 'grab') and (str(state.selected_grab_preview_payload.get('tool') or '').strip().lower() == 'grab') and ('groups' not in state.selected_grab_started_payload) and ('groups' not in state.selected_grab_preview_payload) and ('screen_drag' in state.selected_grab_started_payload) and ('screen_drag' in state.selected_grab_preview_payload) and ('screen_brush' not in state.selected_grab_started_payload) and ('screen_brush' not in state.selected_grab_preview_payload) and ('strength' in state.selected_grab_started_payload) and ('strength' in state.selected_grab_preview_payload) and ('center' not in state.selected_grab_started_payload) and ('center' not in state.selected_grab_preview_payload)
    state.edge_brush_payload = dict(state.edge_brush_status.get('payload', {}) or {})
    state.raw_edge_brush_screen_brush = state.edge_brush_payload.get('screen_brush')
    state.edge_brush_screen_brush = dict(state.raw_edge_brush_screen_brush) if isinstance(state.raw_edge_brush_screen_brush, Mapping) else {}
    state.edge_brush_world_view_projection = tuple(state.edge_brush_screen_brush.get('world_view_projection') or ())
    state.edge_brush_world_view_projection_ok = len(state.edge_brush_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.edge_brush_world_view_projection))
    state.edge_brush_ok = state.edge_brush_status.get('event') == 'mesh_edit_selection_changed' and str(state.edge_brush_payload.get('target_mode') or '').strip().lower() == 'edge' and (str(state.edge_brush_payload.get('selection_depth_mode') or '').strip().lower() in {'visible', 'xray'}) and ('groups' not in state.edge_brush_payload) and ('screen_brush' in state.edge_brush_payload) and all((field in state.edge_brush_screen_brush for field in ('x', 'y', 'radius_pixels', 'viewport_width', 'viewport_height'))) and state.edge_brush_world_view_projection_ok
    state.grab_brush_target_started_payload = dict(state.grab_brush_target_started_status.get('payload', {}) or {})
    state.grab_brush_target_preview_payload = dict(state.grab_brush_target_preview_status.get('payload', {}) or {})
    state.raw_grab_started_screen_brush = state.grab_brush_target_started_payload.get('screen_brush')
    state.grab_started_screen_brush = dict(state.raw_grab_started_screen_brush) if isinstance(state.raw_grab_started_screen_brush, Mapping) else {}
    state.raw_grab_preview_screen_brush = state.grab_brush_target_preview_payload.get('screen_brush')
    state.grab_preview_screen_brush = dict(state.raw_grab_preview_screen_brush) if isinstance(state.raw_grab_preview_screen_brush, Mapping) else {}
    state.grab_started_world_view_projection = tuple(state.grab_started_screen_brush.get('world_view_projection') or ())
    state.grab_preview_world_view_projection = tuple(state.grab_preview_screen_brush.get('world_view_projection') or ())
    state.grab_started_world_view_projection_ok = len(state.grab_started_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.grab_started_world_view_projection))
    state.grab_preview_world_view_projection_ok = len(state.grab_preview_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.grab_preview_world_view_projection))
    state.grab_brush_target_screen_brush_ok = state.grab_brush_target_started_status.get('event') == 'mesh_edit_stroke_started' and state.grab_brush_target_preview_status.get('event') == 'mesh_edit_stroke_previewed' and (state.grab_brush_target_finished_status.get('event') == 'mesh_edit_stroke_finished') and (str(state.grab_brush_target_started_payload.get('tool') or '').strip().lower() == 'grab') and (str(state.grab_brush_target_preview_payload.get('tool') or '').strip().lower() == 'grab') and (str(state.grab_brush_target_started_payload.get('target_mode') or '').strip().lower() == 'brush') and (str(state.grab_brush_target_preview_payload.get('target_mode') or '').strip().lower() == 'brush') and ('groups' not in state.grab_brush_target_started_payload) and ('groups' not in state.grab_brush_target_preview_payload) and ('screen_brush' in state.grab_brush_target_started_payload) and ('screen_brush' in state.grab_brush_target_preview_payload) and ('screen_drag' in state.grab_brush_target_preview_payload) and ('center' not in state.grab_brush_target_started_payload) and ('center' not in state.grab_brush_target_preview_payload) and all((field in state.grab_started_screen_brush for field in ('x', 'y', 'radius_pixels', 'viewport_width', 'viewport_height'))) and all((field in state.grab_preview_screen_brush for field in ('x', 'y', 'radius_pixels', 'viewport_width', 'viewport_height'))) and state.grab_started_world_view_projection_ok and state.grab_preview_world_view_projection_ok
    return None

def _native_smoke_phase_4(state: SimpleNamespace) -> PhaseResult | None:
    state.stroke_started_payload = dict(state.stroke_started_status.get('payload', {}) or {})
    state.stroke_preview_payload = dict(state.stroke_preview_status.get('payload', {}) or {})
    state.brush_stroke_preview_payload = dict(state.brush_stroke_preview_status.get('payload', {}) or {})
    state.smooth_stroke_preview_payload = dict(state.smooth_stroke_preview_status.get('payload', {}) or {})
    state.inflate_stroke_started_payload = dict(state.inflate_stroke_started_status.get('payload', {}) or {})
    state.inflate_stroke_preview_payload = dict(state.inflate_stroke_preview_status.get('payload', {}) or {})
    state.remove_release_started_payload = dict(state.remove_release_started_status.get('payload', {}) or {})
    state.remove_release_preview_payload = dict(state.remove_release_preview_status.get('payload', {}) or {})
    state.remove_live_started_payload = dict(state.remove_live_started_status.get('payload', {}) or {})
    state.remove_live_preview_payload = dict(state.remove_live_preview_status.get('payload', {}) or {})
    state.raw_stroke_screen_drag = state.stroke_preview_payload.get('screen_drag')
    state.stroke_screen_drag = dict(state.raw_stroke_screen_drag) if isinstance(state.raw_stroke_screen_drag, Mapping) else {}
    state.raw_brush_screen_drag = state.brush_stroke_preview_payload.get('screen_drag')
    state.brush_screen_drag = dict(state.raw_brush_screen_drag) if isinstance(state.raw_brush_screen_drag, Mapping) else {}
    state.stroke_camera_world_omitted = 'camera_world' not in state.stroke_screen_drag
    state.brush_camera_world_omitted = 'camera_world' not in state.brush_screen_drag
    state.raw_smooth_screen_brush = state.smooth_stroke_preview_payload.get('screen_brush')
    state.smooth_screen_brush = dict(state.raw_smooth_screen_brush) if isinstance(state.raw_smooth_screen_brush, Mapping) else {}
    state.raw_inflate_started_screen_brush = state.inflate_stroke_started_payload.get('screen_brush')
    state.inflate_started_screen_brush = dict(state.raw_inflate_started_screen_brush) if isinstance(state.raw_inflate_started_screen_brush, Mapping) else {}
    state.raw_inflate_screen_brush = state.inflate_stroke_preview_payload.get('screen_brush')
    state.inflate_screen_brush = dict(state.raw_inflate_screen_brush) if isinstance(state.raw_inflate_screen_brush, Mapping) else {}
    state.raw_inflate_started_screen_radius = state.inflate_stroke_started_payload.get('screen_radius')
    state.inflate_started_screen_radius = dict(state.raw_inflate_started_screen_radius) if isinstance(state.raw_inflate_started_screen_radius, Mapping) else {}
    state.raw_inflate_screen_radius = state.inflate_stroke_preview_payload.get('screen_radius')
    state.inflate_screen_radius = dict(state.raw_inflate_screen_radius) if isinstance(state.raw_inflate_screen_radius, Mapping) else {}
    state.raw_remove_release_started_screen_brush = state.remove_release_started_payload.get('screen_brush')
    state.remove_release_started_screen_brush = dict(state.raw_remove_release_started_screen_brush) if isinstance(state.raw_remove_release_started_screen_brush, Mapping) else {}
    state.raw_remove_release_screen_brush = state.remove_release_preview_payload.get('screen_brush')
    state.remove_release_screen_brush = dict(state.raw_remove_release_screen_brush) if isinstance(state.raw_remove_release_screen_brush, Mapping) else {}
    state.raw_remove_live_started_screen_brush = state.remove_live_started_payload.get('screen_brush')
    state.remove_live_started_screen_brush = dict(state.raw_remove_live_started_screen_brush) if isinstance(state.raw_remove_live_started_screen_brush, Mapping) else {}
    state.raw_remove_live_screen_brush = state.remove_live_preview_payload.get('screen_brush')
    state.remove_live_screen_brush = dict(state.raw_remove_live_screen_brush) if isinstance(state.raw_remove_live_screen_brush, Mapping) else {}
    state.smooth_world_view_projection = tuple(state.smooth_screen_brush.get('world_view_projection') or ())
    state.smooth_world_view_projection_ok = len(state.smooth_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.smooth_world_view_projection))
    state.inflate_world_view_projection = tuple(state.inflate_screen_brush.get('world_view_projection') or ())
    state.inflate_world_view_projection_ok = len(state.inflate_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.inflate_world_view_projection))
    state.inflate_started_world_view_projection = tuple(state.inflate_started_screen_brush.get('world_view_projection') or ())
    state.inflate_started_world_view_projection_ok = len(state.inflate_started_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.inflate_started_world_view_projection))
    state.inflate_started_radius_camera_world_omitted = 'camera_world' not in state.inflate_started_screen_radius
    state.inflate_started_radius_world_view_projection = tuple(state.inflate_started_screen_radius.get('world_view_projection') or ())
    state.inflate_started_radius_world_view_projection_ok = len(state.inflate_started_radius_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.inflate_started_radius_world_view_projection))
    state.inflate_radius_camera_world_omitted = 'camera_world' not in state.inflate_screen_radius
    state.inflate_radius_world_view_projection = tuple(state.inflate_screen_radius.get('world_view_projection') or ())
    state.inflate_radius_world_view_projection_ok = len(state.inflate_radius_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.inflate_radius_world_view_projection))
    state.remove_release_started_world_view_projection = tuple(state.remove_release_started_screen_brush.get('world_view_projection') or ())
    state.remove_release_started_world_view_projection_ok = len(state.remove_release_started_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.remove_release_started_world_view_projection))
    state.remove_release_world_view_projection = tuple(state.remove_release_screen_brush.get('world_view_projection') or ())
    state.remove_release_world_view_projection_ok = len(state.remove_release_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.remove_release_world_view_projection))
    state.remove_live_started_world_view_projection = tuple(state.remove_live_started_screen_brush.get('world_view_projection') or ())
    state.remove_live_started_world_view_projection_ok = len(state.remove_live_started_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.remove_live_started_world_view_projection))
    state.remove_live_world_view_projection = tuple(state.remove_live_screen_brush.get('world_view_projection') or ())
    state.remove_live_world_view_projection_ok = len(state.remove_live_world_view_projection) == 16 and all((isinstance(value, (int, float)) and math.isfinite(float(value)) for value in state.remove_live_world_view_projection))
    state.screen_payloads_without_legacy_camera_fields_ok = all((_LEGACY_SCREEN_CAMERA_FIELDS.isdisjoint(payload) for payload in (state.face_region_screen_region, state.source_screen_brush, state.move_screen_brush, state.move_screen_drag, state.grab_selection_screen_brush, state.grab_selection_screen_drag, state.edge_brush_screen_brush, state.grab_started_screen_brush, state.grab_preview_screen_brush, state.stroke_screen_drag, state.brush_screen_drag, state.smooth_screen_brush, state.inflate_started_screen_brush, state.inflate_screen_brush, state.inflate_started_screen_radius, state.inflate_screen_radius, state.remove_release_started_screen_brush, state.remove_release_screen_brush, state.remove_live_started_screen_brush, state.remove_live_screen_brush)))
    state.screen_payloads_with_source_transform_overrides_ok = state.alignment_transform_status.get('event') == 'alignment_transforms' and all((_screen_source_transform_override_ok(payload) for payload in (state.face_region_screen_region, state.source_screen_brush, state.move_screen_brush, state.move_screen_drag, state.grab_selection_screen_brush, state.grab_selection_screen_drag, state.edge_brush_screen_brush, state.grab_started_screen_brush, state.grab_preview_screen_brush, state.stroke_screen_drag, state.brush_screen_drag, state.smooth_screen_brush, state.inflate_started_screen_brush, state.inflate_screen_brush, state.inflate_started_screen_radius, state.inflate_screen_radius, state.remove_release_started_screen_brush, state.remove_release_screen_brush, state.remove_live_started_screen_brush, state.remove_live_screen_brush)))
    state.stroke_preview_brush_fields = {'amount', 'center', 'falloff', 'invert', 'radius', 'smooth_iterations', 'strength'}
    state.stroke_preview_move_metadata_fields = {'delete_mode', 'mode', 'phase', 'scope_mode', 'selected_vertex_count'}
    state.stroke_compact_preview_ok = state.drag_selection_status.get('event') == 'mesh_edit_selection_changed' and state.drag_state_status.get('event') == 'mesh_edit_state' and (state.stroke_started_status.get('event') == 'mesh_edit_stroke_started') and (state.stroke_preview_status.get('event') == 'mesh_edit_stroke_previewed') and (state.stroke_finished_status.get('event') == 'mesh_edit_stroke_finished') and (state.drag_restore_state_status.get('event') == 'mesh_edit_state') and ('groups' not in state.stroke_started_payload) and ('groups' not in state.stroke_preview_payload) and ('screen_brush' not in state.stroke_started_payload) and ('screen_brush' not in state.stroke_preview_payload) and ('screen_drag' in state.stroke_started_payload) and ('delta' not in state.stroke_preview_payload) and ('step_delta' not in state.stroke_preview_payload) and ('screen_drag' in state.stroke_preview_payload) and ('start_x' in state.stroke_screen_drag) and ('end_x' in state.stroke_screen_drag) and state.stroke_camera_world_omitted and ('delta_x_pixels' not in state.stroke_screen_drag) and state.stroke_preview_brush_fields.isdisjoint(state.stroke_preview_payload) and state.stroke_preview_move_metadata_fields.isdisjoint(state.stroke_preview_payload)
    return None

def _native_smoke_phase_5(state: SimpleNamespace) -> PhaseResult | None:
    state.brush_stroke_screen_drag_only_ok = state.brush_stroke_state_status.get('event') == 'mesh_edit_state' and state.brush_stroke_started_status.get('event') == 'mesh_edit_stroke_started' and (state.brush_stroke_preview_status.get('event') == 'mesh_edit_stroke_previewed') and (state.brush_stroke_finished_status.get('event') == 'mesh_edit_stroke_finished') and (str(state.brush_stroke_preview_payload.get('tool') or '').strip().lower() == 'grab') and ('groups' not in state.brush_stroke_preview_payload) and ('delta' not in state.brush_stroke_preview_payload) and ('step_delta' not in state.brush_stroke_preview_payload) and ('screen_drag' in state.brush_stroke_preview_payload) and ('start_x' in state.brush_screen_drag) and ('end_x' in state.brush_screen_drag) and state.brush_camera_world_omitted and ('delta_x_pixels' not in state.brush_screen_drag) and ('strength' in state.brush_stroke_preview_payload) and {'center', 'amount', 'radius', 'falloff', 'invert', 'smooth_iterations'}.isdisjoint(state.brush_stroke_preview_payload) and state.stroke_preview_move_metadata_fields.isdisjoint(state.brush_stroke_preview_payload)
    state.smooth_stroke_screen_brush_only_ok = state.smooth_stroke_state_status.get('event') == 'mesh_edit_state' and state.smooth_stroke_started_status.get('event') == 'mesh_edit_stroke_started' and (state.smooth_stroke_preview_status.get('event') == 'mesh_edit_stroke_previewed') and (state.smooth_stroke_finished_status.get('event') == 'mesh_edit_stroke_finished') and (str(state.smooth_stroke_preview_payload.get('tool') or '').strip().lower() == 'smooth') and ('groups' not in state.smooth_stroke_preview_payload) and ('screen_brush' in state.smooth_stroke_preview_payload) and all((field in state.smooth_screen_brush for field in ('x', 'y', 'radius_pixels', 'viewport_width', 'viewport_height'))) and state.smooth_world_view_projection_ok and ('screen_drag' not in state.smooth_stroke_preview_payload) and ('center' not in state.smooth_stroke_preview_payload) and ('smooth_iterations' in state.smooth_stroke_preview_payload) and ('strength' in state.smooth_stroke_preview_payload) and {'amount', 'radius', 'falloff', 'invert', 'screen_radius'}.isdisjoint(state.smooth_stroke_preview_payload) and state.stroke_preview_move_metadata_fields.isdisjoint(state.smooth_stroke_preview_payload)
    state.inflate_stroke_native_center_ok = state.inflate_stroke_state_status.get('event') == 'mesh_edit_state' and state.inflate_stroke_started_status.get('event') == 'mesh_edit_stroke_started' and (state.inflate_stroke_preview_status.get('event') == 'mesh_edit_stroke_previewed') and (state.inflate_stroke_finished_status.get('event') == 'mesh_edit_stroke_finished') and (str(state.inflate_stroke_started_payload.get('tool') or '').strip().lower() == 'inflate') and (str(state.inflate_stroke_preview_payload.get('tool') or '').strip().lower() == 'inflate') and (not tuple(state.inflate_stroke_started_payload.get('groups') or ())) and (str(state.inflate_stroke_started_payload.get('target_mode') or '').strip().lower() == 'selection') and (str(state.inflate_stroke_started_payload.get('selection_depth_mode') or '').strip().lower() in {'visible', 'xray'}) and ('center' not in state.inflate_stroke_started_payload) and ('center' not in state.inflate_stroke_preview_payload) and ('groups' not in state.inflate_stroke_preview_payload) and ('screen_brush' in state.inflate_stroke_started_payload) and ('screen_brush' in state.inflate_stroke_preview_payload) and ('screen_radius' in state.inflate_stroke_started_payload) and ('screen_radius' in state.inflate_stroke_preview_payload) and all((field in state.inflate_started_screen_brush for field in ('x', 'y', 'radius_pixels', 'viewport_width', 'viewport_height'))) and all((field in state.inflate_screen_brush for field in ('x', 'y', 'radius_pixels', 'viewport_width', 'viewport_height'))) and state.inflate_started_world_view_projection_ok and state.inflate_world_view_projection_ok and all((field in state.inflate_started_screen_radius for field in ('radius_pixels', 'viewport_width', 'viewport_height'))) and all((field in state.inflate_screen_radius for field in ('radius_pixels', 'viewport_width', 'viewport_height'))) and state.inflate_started_radius_camera_world_omitted and state.inflate_started_radius_world_view_projection_ok and state.inflate_radius_camera_world_omitted and state.inflate_radius_world_view_projection_ok and ('screen_drag' not in state.inflate_stroke_preview_payload) and ('strength' in state.inflate_stroke_preview_payload) and ('invert' in state.inflate_stroke_preview_payload) and {'amount', 'radius', 'falloff', 'smooth_iterations'}.isdisjoint(state.inflate_stroke_preview_payload) and state.stroke_preview_move_metadata_fields.isdisjoint(state.inflate_stroke_preview_payload)
    state.remove_release_screen_brush_only_ok = state.remove_release_state_status.get('event') == 'mesh_edit_state' and state.remove_release_started_status.get('event') == 'mesh_edit_stroke_started' and (state.remove_release_preview_status.get('event') == 'mesh_edit_stroke_previewed') and (state.remove_release_finished_status.get('event') == 'mesh_edit_stroke_finished') and (str(state.remove_release_started_payload.get('tool') or '').strip().lower() == 'remove') and (str(state.remove_release_preview_payload.get('tool') or '').strip().lower() == 'remove') and (str(state.remove_release_started_payload.get('delete_mode') or '').strip().lower() == 'release') and (str(state.remove_release_preview_payload.get('delete_mode') or '').strip().lower() == 'release') and (str(state.remove_release_started_payload.get('target_mode') or '').strip().lower() == 'face') and (str(state.remove_release_preview_payload.get('target_mode') or '').strip().lower() == 'face') and ('groups' not in state.remove_release_started_payload) and ('groups' not in state.remove_release_preview_payload) and ('screen_brush' in state.remove_release_started_payload) and ('screen_brush' in state.remove_release_preview_payload) and all((field in state.remove_release_started_screen_brush for field in ('x', 'y', 'radius_pixels', 'viewport_width', 'viewport_height'))) and all((field in state.remove_release_screen_brush for field in ('x', 'y', 'radius_pixels', 'viewport_width', 'viewport_height'))) and state.remove_release_started_world_view_projection_ok and state.remove_release_world_view_projection_ok and ('center' not in state.remove_release_started_payload) and ('center' not in state.remove_release_preview_payload) and ('screen_radius' not in state.remove_release_started_payload) and ('screen_radius' not in state.remove_release_preview_payload) and ('screen_drag' not in state.remove_release_preview_payload) and {'amount', 'radius', 'smooth_iterations', 'strength', 'invert'}.isdisjoint(state.remove_release_preview_payload) and {'mode', 'phase', 'scope_mode', 'selected_vertex_count'}.isdisjoint(state.remove_release_preview_payload)
    state.remove_live_screen_brush_only_ok = state.remove_live_state_status.get('event') == 'mesh_edit_state' and state.remove_live_started_status.get('event') == 'mesh_edit_stroke_started' and (state.remove_live_preview_status.get('event') == 'mesh_edit_stroke_previewed') and (state.remove_live_finished_status.get('event') == 'mesh_edit_stroke_finished') and (str(state.remove_live_started_payload.get('tool') or '').strip().lower() == 'remove') and (str(state.remove_live_preview_payload.get('tool') or '').strip().lower() == 'remove') and (str(state.remove_live_started_payload.get('delete_mode') or '').strip().lower() == 'live') and (str(state.remove_live_preview_payload.get('delete_mode') or '').strip().lower() == 'live') and (str(state.remove_live_started_payload.get('target_mode') or '').strip().lower() == 'face') and (str(state.remove_live_preview_payload.get('target_mode') or '').strip().lower() == 'face') and ('groups' not in state.remove_live_started_payload) and ('groups' not in state.remove_live_preview_payload) and ('screen_brush' in state.remove_live_started_payload) and ('screen_brush' in state.remove_live_preview_payload) and all((field in state.remove_live_started_screen_brush for field in ('x', 'y', 'radius_pixels', 'viewport_width', 'viewport_height'))) and all((field in state.remove_live_screen_brush for field in ('x', 'y', 'radius_pixels', 'viewport_width', 'viewport_height'))) and state.remove_live_started_world_view_projection_ok and state.remove_live_world_view_projection_ok and ('center' not in state.remove_live_started_payload) and ('center' not in state.remove_live_preview_payload) and ('screen_radius' not in state.remove_live_started_payload) and ('screen_radius' not in state.remove_live_preview_payload) and ('screen_drag' not in state.remove_live_preview_payload) and {'amount', 'radius', 'smooth_iterations', 'strength', 'invert'}.isdisjoint(state.remove_live_preview_payload) and {'mode', 'phase', 'scope_mode', 'selected_vertex_count'}.isdisjoint(state.remove_live_preview_payload)
    state.brush_drag_selection_event_delta = max(0, int(state.brush_drag_status_after.get('mesh_edit_selection_event_count', 0) or 0) - int(state.brush_drag_status_before.get('mesh_edit_selection_event_count', 0) or 0))
    state.brush_drag_event_budget = max(4, int(math.ceil(state.brush_drag_elapsed_ms / 16.0)) + 3)
    state.brush_drag_event_budget_ok = 1 <= state.brush_drag_selection_event_delta <= state.brush_drag_event_budget
    state.texture_cache_before = int(state.texture_status_before.get('texture_cache_entries', 0) or 0)
    state.texture_cache_enabled = int(state.texture_status_enabled.get('texture_cache_entries', 0) or 0)
    state.texture_cache_disabled = int(state.texture_status_disabled.get('texture_cache_entries', 0) or 0)
    state.texture_toggle_ok = state.texture_cache_before > 0 and state.texture_cache_enabled == state.texture_cache_before and (state.texture_cache_disabled == state.texture_cache_before) and (state.mesh_edit_enable_status.get('event') == 'mesh_edit_state') and (state.mesh_edit_disable_status.get('event') == 'mesh_edit_state') and (int(state.texture_status_disabled.get('parent_unresponsive_count', 0) or 0) == 0)
    state.created_part_ok = int(state.created_part_status.get('replaced_batches', 0) or 0) >= 1
    state.pruned_part_ok = int(state.pruned_part_status.get('removed_batches', 0) or 0) >= 1
    state.empty_selection_payload = dict(state.empty_selection_status.get('payload', {}) or {})
    state.empty_selection_ok = int(state.empty_selection_payload.get('selected_vertex_count', -1) or 0) == 0 and int(state.empty_selection_payload.get('selected_edge_count', -1) or 0) == 0 and (int(state.empty_selection_payload.get('selected_face_count', -1) or 0) == 0) and (not tuple(state.empty_selection_payload.get('groups') or ()))
    state.capture_ok = bool(state.capture_summary.get('ok'))
    return None

def _native_smoke_result(state: SimpleNamespace):
    return {'ok': bool(state.loaded_ok and state.hwnd and all(state.sent) and state.capture_ok and state.face_selection_ok and state.face_region_ok and state.edge_selection_ok and state.source_selection_ok and state.source_screen_selection_ok and state.empty_selection_ok and state.move_screen_selection_ok and state.grab_screen_selection_ok and state.selected_move_resident_selection_ok and state.selected_grab_resident_selection_ok and state.edge_brush_ok and state.grab_brush_target_screen_brush_ok and state.stroke_compact_preview_ok and state.brush_stroke_screen_drag_only_ok and state.smooth_stroke_screen_brush_only_ok and state.inflate_stroke_native_center_ok and state.remove_release_screen_brush_only_ok and state.remove_live_screen_brush_only_ok and state.screen_payloads_without_legacy_camera_fields_ok and state.screen_payloads_with_source_transform_overrides_ok and state.brush_drag_event_budget_ok and state.texture_toggle_ok and state.created_part_ok and state.pruned_part_ok), 'host': str(state.host_binary), 'package_dir': str(state.package_dir), 'status_file': str(state.status_file), 'texture_path': str(state.texture_path), 'preview_png': str(state.capture_path), 'commands_sent': state.sent, 'loaded_status': state.loaded, 'mesh_edit_enable_status': state.mesh_edit_enable_status, 'mesh_edit_disable_status': state.mesh_edit_disable_status, 'texture_status_before': state.texture_status_before, 'texture_status_enabled': state.texture_status_enabled, 'texture_status_disabled': state.texture_status_disabled, 'texture_toggle_ok': state.texture_toggle_ok, 'alignment_transform_status': state.alignment_transform_status, 'face_selection_status': state.face_selection_status, 'face_region_status': state.face_region_status, 'face_region_world_view_projection_ok': state.face_region_world_view_projection_ok, 'edge_selection_status': state.edge_selection_status, 'source_selection_status': state.source_selection_status, 'source_selection_ok': state.source_selection_ok, 'source_selection_compact': state.source_selection_compact, 'source_screen_selection_status': state.source_screen_selection_status, 'source_screen_selection_ok': state.source_screen_selection_ok, 'source_screen_selection_world_view_projection_ok': state.source_screen_world_view_projection_ok, 'empty_selection_status': state.empty_selection_status, 'move_screen_selection_state_status': state.move_screen_selection_state_status, 'move_screen_selection_started_status': state.move_screen_selection_started_status, 'move_screen_selection_finished_status': state.move_screen_selection_finished_status, 'move_screen_selection_world_view_projection_ok': state.move_screen_selection_world_view_projection_ok, 'move_screen_selection_ok': state.move_screen_selection_ok, 'grab_screen_selection_state_status': state.grab_screen_selection_state_status, 'grab_screen_selection_started_status': state.grab_screen_selection_started_status, 'grab_screen_selection_finished_status': state.grab_screen_selection_finished_status, 'grab_screen_selection_world_view_projection_ok': state.grab_screen_selection_world_view_projection_ok, 'grab_screen_selection_ok': state.grab_screen_selection_ok, 'selected_drag_selection_status': state.selected_drag_selection_status, 'selected_move_state_status': state.selected_move_state_status, 'selected_move_started_status': state.selected_move_started_status, 'selected_move_preview_status': state.selected_move_preview_status, 'selected_move_finished_status': state.selected_move_finished_status, 'selected_move_resident_selection_ok': state.selected_move_resident_selection_ok, 'selected_grab_selection_status': state.selected_grab_selection_status, 'selected_grab_state_status': state.selected_grab_state_status, 'selected_grab_started_status': state.selected_grab_started_status, 'selected_grab_preview_status': state.selected_grab_preview_status, 'selected_grab_finished_status': state.selected_grab_finished_status, 'selected_grab_resident_selection_ok': state.selected_grab_resident_selection_ok, 'edge_brush_status': state.edge_brush_status, 'edge_brush_world_view_projection_ok': state.edge_brush_world_view_projection_ok, 'grab_brush_target_started_status': state.grab_brush_target_started_status, 'grab_brush_target_preview_status': state.grab_brush_target_preview_status, 'grab_brush_target_finished_status': state.grab_brush_target_finished_status, 'grab_brush_target_world_view_projection_ok': state.grab_started_world_view_projection_ok and state.grab_preview_world_view_projection_ok, 'grab_brush_target_screen_brush_ok': state.grab_brush_target_screen_brush_ok, 'drag_selection_status': state.drag_selection_status, 'drag_state_status': state.drag_state_status, 'stroke_started_status': state.stroke_started_status, 'stroke_preview_status': state.stroke_preview_status, 'stroke_finished_status': state.stroke_finished_status, 'brush_stroke_state_status': state.brush_stroke_state_status, 'brush_stroke_started_status': state.brush_stroke_started_status, 'brush_stroke_preview_status': state.brush_stroke_preview_status, 'brush_stroke_finished_status': state.brush_stroke_finished_status, 'stroke_camera_world_omitted': state.stroke_camera_world_omitted, 'brush_stroke_camera_world_omitted': state.brush_camera_world_omitted, 'brush_stroke_screen_drag_only_ok': state.brush_stroke_screen_drag_only_ok, 'smooth_stroke_state_status': state.smooth_stroke_state_status, 'smooth_stroke_started_status': state.smooth_stroke_started_status, 'smooth_stroke_preview_status': state.smooth_stroke_preview_status, 'smooth_stroke_finished_status': state.smooth_stroke_finished_status, 'smooth_stroke_world_view_projection_ok': state.smooth_world_view_projection_ok, 'smooth_stroke_screen_brush_only_ok': state.smooth_stroke_screen_brush_only_ok, 'inflate_stroke_state_status': state.inflate_stroke_state_status, 'inflate_stroke_started_status': state.inflate_stroke_started_status, 'inflate_stroke_preview_status': state.inflate_stroke_preview_status, 'inflate_stroke_finished_status': state.inflate_stroke_finished_status, 'inflate_stroke_started_world_view_projection_ok': state.inflate_started_world_view_projection_ok, 'inflate_stroke_world_view_projection_ok': state.inflate_world_view_projection_ok, 'inflate_started_radius_camera_world_omitted': state.inflate_started_radius_camera_world_omitted, 'inflate_started_radius_world_view_projection_ok': state.inflate_started_radius_world_view_projection_ok, 'inflate_radius_camera_world_omitted': state.inflate_radius_camera_world_omitted, 'inflate_radius_world_view_projection_ok': state.inflate_radius_world_view_projection_ok, 'inflate_stroke_native_center_ok': state.inflate_stroke_native_center_ok, 'screen_payloads_without_legacy_camera_fields_ok': state.screen_payloads_without_legacy_camera_fields_ok, 'screen_payloads_with_source_transform_overrides_ok': state.screen_payloads_with_source_transform_overrides_ok, 'remove_release_state_status': state.remove_release_state_status, 'remove_release_started_status': state.remove_release_started_status, 'remove_release_preview_status': state.remove_release_preview_status, 'remove_release_finished_status': state.remove_release_finished_status, 'remove_release_started_world_view_projection_ok': state.remove_release_started_world_view_projection_ok, 'remove_release_world_view_projection_ok': state.remove_release_world_view_projection_ok, 'remove_release_screen_brush_only_ok': state.remove_release_screen_brush_only_ok, 'remove_live_state_status': state.remove_live_state_status, 'remove_live_started_status': state.remove_live_started_status, 'remove_live_preview_status': state.remove_live_preview_status, 'remove_live_finished_status': state.remove_live_finished_status, 'remove_live_started_world_view_projection_ok': state.remove_live_started_world_view_projection_ok, 'remove_live_world_view_projection_ok': state.remove_live_world_view_projection_ok, 'remove_live_screen_brush_only_ok': state.remove_live_screen_brush_only_ok, 'drag_restore_state_status': state.drag_restore_state_status, 'stroke_compact_preview_ok': state.stroke_compact_preview_ok, 'brush_drag_status_before': state.brush_drag_status_before, 'brush_drag_status_after': state.brush_drag_status_after, 'brush_drag_elapsed_ms': state.brush_drag_elapsed_ms, 'brush_drag_event_budget': state.brush_drag_event_budget, 'brush_drag_selection_event_delta': state.brush_drag_selection_event_delta, 'brush_drag_event_budget_ok': state.brush_drag_event_budget_ok, 'created_part_status': state.created_part_status, 'pruned_part_status': state.pruned_part_status, 'captured': state.captured, 'capture_summary': state.capture_summary}

def run_native_smoke(mesh: ParsedMesh, output_dir: Path, *, timeout_seconds: float=15.0) -> dict[str, object]:
    if os.name != 'nt':
        return {'ok': False, 'error': 'native D3D11 harness requires Windows'}
    host_binary = find_native_d3d11_host()
    if host_binary is None:
        return {'ok': False, 'error': 'native D3D11 preview host not found'}
    package_dir = output_dir / 'preview_package'
    status_file = output_dir / 'native_status.json'
    capture_path = output_dir / 'preview.png'
    texture_path = output_dir / 'harness_checker.png'
    _write_checker_png(texture_path)
    for submesh in mesh.submeshes:
        if submesh.uvs:
            submesh.texture = str(texture_path)
    package_dir = mesh_editor_write_native_preview_package(mesh, output_root=package_dir, use_textures=True, backend='d3d11')
    process = subprocess.Popen([str(host_binary), '--backend', 'd3d11', '--preview-package', str(package_dir), '--status-file', str(status_file)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    state = SimpleNamespace(**locals())
    try:
        phase_result = _native_smoke_phase_1(state)
        if phase_result is not None:
            return phase_result.value
        phase_result = _native_smoke_phase_2(state)
        if phase_result is not None:
            return phase_result.value
        phase_result = _native_smoke_phase_3(state)
        if phase_result is not None:
            return phase_result.value
        phase_result = _native_smoke_phase_4(state)
        if phase_result is not None:
            return phase_result.value
        phase_result = _native_smoke_phase_5(state)
        if phase_result is not None:
            return phase_result.value
        return _native_smoke_result(state)
    finally:
        _close_process(state.process)
