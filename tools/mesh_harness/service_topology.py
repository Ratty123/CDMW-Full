from __future__ import annotations
from types import SimpleNamespace
from cdmw.domain.mesh import MeshEditCommand
from cdmw.domain.mesh import MeshEditSelection
from cdmw.services.mesh_service import MeshService
from cdmw.modding.mesh_parser import SubMesh
from tools.mesh_harness.fixtures import build_synthetic_mesh
from tools.mesh_harness.service_summary import _command_summary

def _topology_phase_1(state: SimpleNamespace) -> None:
    state.service = MeshService()
    state.duplicate_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='edge-face-duplicate', mode='edit')
    state.duplicate = state.service.apply_command(state.duplicate_view.session_id, MeshEditCommand('duplicate', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})))
    state.duplicate_mesh = state.service.working_mesh(state.duplicate_view.session_id)
    state.copied = state.duplicate_mesh.submeshes[1] if len(state.duplicate_mesh.submeshes) > 1 else SubMesh()
    state.service.close_edit_session(state.duplicate_view.session_id)
    state.mirror_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='edge-face-mirror', mode='edit')
    state.mirror = state.service.apply_command(state.mirror_view.session_id, MeshEditCommand('mirror', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}), params={'axis': 'x'}))
    state.mirror_mesh = state.service.working_mesh(state.mirror_view.session_id)
    state.mirrored = state.mirror_mesh.submeshes[1] if len(state.mirror_mesh.submeshes) > 1 else SubMesh()
    state.service.close_edit_session(state.mirror_view.session_id)
    state.delete_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='edge-face-delete', mode='edit')
    state.delete = state.service.apply_command(state.delete_view.session_id, MeshEditCommand('delete', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})))
    state.delete_submesh = state.service.working_mesh(state.delete_view.session_id).submeshes[0]
    state.service.close_edit_session(state.delete_view.session_id)
    state.dissolve_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='edge-face-dissolve', mode='edit')
    state.dissolve = state.service.apply_command(state.dissolve_view.session_id, MeshEditCommand('dissolve', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})))
    state.dissolve_submesh = state.service.working_mesh(state.dissolve_view.session_id).submeshes[0]
    state.service.close_edit_session(state.dissolve_view.session_id)
    state.internal_dissolve_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='internal-edge-dissolve', mode='edit')
    state.internal_dissolve = state.service.apply_command(state.internal_dissolve_view.session_id, MeshEditCommand('dissolve', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)})))
    state.internal_dissolve_submesh = state.service.working_mesh(state.internal_dissolve_view.session_id).submeshes[0]
    state.service.close_edit_session(state.internal_dissolve_view.session_id)
    state.subdivide_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='edge-face-subdivide', mode='edit')
    state.subdivide = state.service.apply_command(state.subdivide_view.session_id, MeshEditCommand('subdivide', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})))
    state.subdivide_submesh = state.service.working_mesh(state.subdivide_view.session_id).submeshes[0]
    state.service.close_edit_session(state.subdivide_view.session_id)
    state.loop_cut_mesh = build_synthetic_mesh()
    state.loop_cut_seed = state.loop_cut_mesh.submeshes[0]
    state.loop_cut_seed.vertices = state.loop_cut_seed.vertices[:3]
    state.loop_cut_seed.uvs = state.loop_cut_seed.uvs[:3]
    state.loop_cut_seed.normals = state.loop_cut_seed.normals[:3]
    state.loop_cut_seed.faces = [(0, 1, 2)]
    state.loop_cut_seed.vertex_count = 3
    state.loop_cut_seed.face_count = 1
    state.loop_cut_mesh.total_vertices = 3
    state.loop_cut_mesh.total_faces = 1
    state.loop_cut_view = state.service.open_edit_session(state.loop_cut_mesh, session_id='two-edge-loop-cut', mode='edit')
    state.loop_cut = state.service.apply_command(state.loop_cut_view.session_id, MeshEditCommand('loop_cut', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 2))})))
    state.loop_cut_submesh = state.service.working_mesh(state.loop_cut_view.session_id).submeshes[0]
    state.service.close_edit_session(state.loop_cut_view.session_id)
    state.multi_cut_mesh = build_synthetic_mesh()
    state.multi_cut_seed = state.multi_cut_mesh.submeshes[0]
    state.multi_cut_seed.vertices = state.multi_cut_seed.vertices[:3]
    state.multi_cut_seed.uvs = state.multi_cut_seed.uvs[:3]
    state.multi_cut_seed.normals = state.multi_cut_seed.normals[:3]
    state.multi_cut_seed.faces = [(0, 1, 2)]
    state.multi_cut_seed.vertex_count = 3
    state.multi_cut_seed.face_count = 1
    state.multi_cut_mesh.total_vertices = 3
    state.multi_cut_mesh.total_faces = 1
    state.multi_cut_view = state.service.open_edit_session(state.multi_cut_mesh, session_id='multi-edge-loop-cut', mode='edit')
    state.multi_cut = state.service.apply_command(state.multi_cut_view.session_id, MeshEditCommand('loop_cut', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}), params={'cuts': 2}))
    state.multi_cut_submesh = state.service.working_mesh(state.multi_cut_view.session_id).submeshes[0]
    state.service.close_edit_session(state.multi_cut_view.session_id)
    state.factor_cut_mesh = build_synthetic_mesh()
    state.factor_cut_seed = state.factor_cut_mesh.submeshes[0]
    state.factor_cut_seed.vertices = state.factor_cut_seed.vertices[:3]
    state.factor_cut_seed.uvs = state.factor_cut_seed.uvs[:3]
    state.factor_cut_seed.normals = state.factor_cut_seed.normals[:3]
    state.factor_cut_seed.faces = [(0, 1, 2)]
    state.factor_cut_seed.vertex_count = 3
    state.factor_cut_seed.face_count = 1
    state.factor_cut_mesh.total_vertices = 3
    state.factor_cut_mesh.total_faces = 1
    state.factor_cut_view = state.service.open_edit_session(state.factor_cut_mesh, session_id='factor-edge-loop-cut', mode='edit')
    state.factor_cut = state.service.apply_command(state.factor_cut_view.session_id, MeshEditCommand('loop_cut', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}), params={'factor': 0.25}))
    state.factor_cut_submesh = state.service.working_mesh(state.factor_cut_view.session_id).submeshes[0]
    state.service.close_edit_session(state.factor_cut_view.session_id)

def _topology_phase_2(state: SimpleNamespace) -> None:
    state.split_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='edge-face-split', mode='edit')
    state.split = state.service.apply_command(state.split_view.session_id, MeshEditCommand('split', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})))
    state.split_mesh = state.service.working_mesh(state.split_view.session_id)
    state.service.close_edit_session(state.split_view.session_id)
    state.separate_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='edge-face-separate', mode='edit')
    state.separate = state.service.apply_command(state.separate_view.session_id, MeshEditCommand('separate', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})))
    state.separate_mesh = state.service.working_mesh(state.separate_view.session_id)
    state.service.close_edit_session(state.separate_view.session_id)
    state.fill_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='edge-face-fill', mode='edit')
    state.fill = state.service.apply_command(state.fill_view.session_id, MeshEditCommand('fill', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 3), (0, 3))})))
    state.fill_submesh = state.service.working_mesh(state.fill_view.session_id).submeshes[0]
    state.service.close_edit_session(state.fill_view.session_id)
    state.quad_fill_mesh = build_synthetic_mesh()
    state.quad_fill_mesh.submeshes[0].faces = []
    state.quad_fill_mesh.submeshes[0].face_count = 0
    state.quad_fill_mesh.total_faces = 0
    state.quad_fill_view = state.service.open_edit_session(state.quad_fill_mesh, session_id='quad-loop-fill', mode='edit')
    state.quad_fill = state.service.apply_command(state.quad_fill_view.session_id, MeshEditCommand('fill', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 3), (2, 3), (0, 2))})))
    state.quad_fill_submesh = state.service.working_mesh(state.quad_fill_view.session_id).submeshes[0]
    state.service.close_edit_session(state.quad_fill_view.session_id)
    state.face_fill_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='face-fill-noop', mode='edit')
    state.face_fill = state.service.apply_command(state.face_fill_view.session_id, MeshEditCommand('fill', selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}, source_indices=(0,))))
    state.face_fill_submesh = state.service.working_mesh(state.face_fill_view.session_id).submeshes[0]
    state.service.close_edit_session(state.face_fill_view.session_id)
    state.existing_fill_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='existing-fill-noop', mode='edit')
    state.existing_fill = state.service.apply_command(state.existing_fill_view.session_id, MeshEditCommand('fill', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 2), (0, 2))})))
    state.existing_fill_submesh = state.service.working_mesh(state.existing_fill_view.session_id).submeshes[0]
    state.service.close_edit_session(state.existing_fill_view.session_id)
    state.extrude_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='region-extrude', mode='edit')
    state.extrude = state.service.apply_command(state.extrude_view.session_id, MeshEditCommand('extrude', selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)}), params={'offset': (0.0, 0.0, 0.2)}))
    state.extrude_submesh = state.service.working_mesh(state.extrude_view.session_id).submeshes[0]
    state.service.close_edit_session(state.extrude_view.session_id)
    state.edge_extrude_mesh = build_synthetic_mesh()
    state.edge_extrude_mesh.submeshes[0].faces = []
    state.edge_extrude_mesh.submeshes[0].face_count = 0
    state.edge_extrude_mesh.total_faces = 0
    state.edge_extrude_view = state.service.open_edit_session(state.edge_extrude_mesh, session_id='loose-edge-extrude', mode='edit')
    state.edge_extrude = state.service.apply_command(state.edge_extrude_view.session_id, MeshEditCommand('extrude', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}), params={'offset': (0.0, 0.0, 0.2)}))
    state.edge_extrude_submesh = state.service.working_mesh(state.edge_extrude_view.session_id).submeshes[0]
    state.service.close_edit_session(state.edge_extrude_view.session_id)
    state.non_edge_extrude_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='non-edge-extrude', mode='edit')
    state.non_edge_extrude = state.service.apply_command(state.non_edge_extrude_view.session_id, MeshEditCommand('extrude', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 3),)}), params={'offset': (0.0, 0.0, 0.2)}))
    state.non_edge_extrude_submesh = state.service.working_mesh(state.non_edge_extrude_view.session_id).submeshes[0]
    state.service.close_edit_session(state.non_edge_extrude_view.session_id)
    state.inset_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='region-inset', mode='edit')
    state.inset = state.service.apply_command(state.inset_view.session_id, MeshEditCommand('inset', selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)}), params={'amount': 0.5}))
    state.inset_submesh = state.service.working_mesh(state.inset_view.session_id).submeshes[0]
    state.service.close_edit_session(state.inset_view.session_id)
    state.inset_zero_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='zero-inset', mode='edit')
    state.inset_zero = state.service.apply_command(state.inset_zero_view.session_id, MeshEditCommand('inset', selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)}), params={'amount': 0.0}))
    state.inset_zero_submesh = state.service.working_mesh(state.inset_zero_view.session_id).submeshes[0]
    state.service.close_edit_session(state.inset_zero_view.session_id)

def _topology_phase_3(state: SimpleNamespace) -> None:
    state.merge_mesh = build_synthetic_mesh()
    state.merge_submesh_seed = state.merge_mesh.submeshes[0]
    state.merge_submesh_seed.vertices.append(state.merge_submesh_seed.vertices[1])
    state.merge_submesh_seed.uvs.append(state.merge_submesh_seed.uvs[1])
    state.merge_submesh_seed.normals.append(state.merge_submesh_seed.normals[1])
    state.merge_submesh_seed.faces.append((0, 4, 2))
    state.merge_submesh_seed.vertex_count = len(state.merge_submesh_seed.vertices)
    state.merge_submesh_seed.face_count = len(state.merge_submesh_seed.faces)
    state.merge_mesh.total_vertices = len(state.merge_submesh_seed.vertices)
    state.merge_mesh.total_faces = len(state.merge_submesh_seed.faces)
    state.merge_view = state.service.open_edit_session(state.merge_mesh, session_id='duplicate-merge', mode='edit')
    state.merge = state.service.apply_command(state.merge_view.session_id, MeshEditCommand('merge', selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 4)})))
    state.merge_submesh = state.service.working_mesh(state.merge_view.session_id).submeshes[0]
    state.service.close_edit_session(state.merge_view.session_id)
    state.weld_mesh = build_synthetic_mesh()
    state.weld_submesh_seed = state.weld_mesh.submeshes[0]
    state.weld_submesh_seed.vertices.append(state.weld_submesh_seed.vertices[1])
    state.weld_submesh_seed.uvs.append(state.weld_submesh_seed.uvs[1])
    state.weld_submesh_seed.normals.append(state.weld_submesh_seed.normals[1])
    state.weld_submesh_seed.faces.append((0, 4, 2))
    state.weld_submesh_seed.vertex_count = len(state.weld_submesh_seed.vertices)
    state.weld_submesh_seed.face_count = len(state.weld_submesh_seed.faces)
    state.weld_mesh.total_vertices = len(state.weld_submesh_seed.vertices)
    state.weld_mesh.total_faces = len(state.weld_submesh_seed.faces)
    state.weld_view = state.service.open_edit_session(state.weld_mesh, session_id='duplicate-weld', mode='edit')
    state.weld = state.service.apply_command(state.weld_view.session_id, MeshEditCommand('weld', selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 4)}), params={'threshold': 0.001}))
    state.weld_submesh = state.service.working_mesh(state.weld_view.session_id).submeshes[0]
    state.service.close_edit_session(state.weld_view.session_id)
    state.bridge_mesh = build_synthetic_mesh()
    state.bridge_mesh.submeshes[0].faces = []
    state.bridge_mesh.submeshes[0].face_count = 0
    state.bridge_mesh.total_faces = 0
    state.bridge_view = state.service.open_edit_session(state.bridge_mesh, session_id='loose-edge-bridge', mode='edit')
    state.bridge = state.service.apply_command(state.bridge_view.session_id, MeshEditCommand('bridge', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (2, 3))})))
    state.bridge_submesh = state.service.working_mesh(state.bridge_view.session_id).submeshes[0]
    state.service.close_edit_session(state.bridge_view.session_id)
    state.filled_bridge_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='filled-edge-bridge', mode='edit')
    state.filled_bridge = state.service.apply_command(state.filled_bridge_view.session_id, MeshEditCommand('bridge', selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (2, 3))})))
    state.filled_bridge_submesh = state.service.working_mesh(state.filled_bridge_view.session_id).submeshes[0]
    state.service.close_edit_session(state.filled_bridge_view.session_id)
    state.empty_recalc_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='empty-normal-recalc', mode='edit')
    state.empty_recalc_submesh = state.service.working_mesh(state.empty_recalc_view.session_id).submeshes[0]
    state.empty_recalc_submesh.normals = [(0.0, 0.0, -1.0)] * len(state.empty_recalc_submesh.vertices)
    state.empty_recalc = state.service.apply_command(state.empty_recalc_view.session_id, MeshEditCommand('recalculate_normals'))
    state.empty_recalc_normals = [list(normal) for normal in state.empty_recalc_submesh.normals]
    state.service.close_edit_session(state.empty_recalc_view.session_id)
    state.source_recalc_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='source-normal-recalc', mode='edit')
    state.source_recalc_submesh = state.service.working_mesh(state.source_recalc_view.session_id).submeshes[0]
    state.source_recalc_submesh.normals = [(0.0, 0.0, -1.0)] * len(state.source_recalc_submesh.vertices)
    state.source_recalc = state.service.apply_command(state.source_recalc_view.session_id, MeshEditCommand('recalculate_normals', selection=MeshEditSelection.from_maps(source_indices=(0,))))
    state.source_recalc_submesh = state.service.working_mesh(state.source_recalc_view.session_id).submeshes[0]
    state.source_recalc_normals = [list(normal) for normal in state.source_recalc_submesh.normals]
    state.service.close_edit_session(state.source_recalc_view.session_id)
    state.face_flip_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='face-normal-flip', mode='edit')
    state.face_flip = state.service.apply_command(state.face_flip_view.session_id, MeshEditCommand('flip_normals', selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})))
    state.face_flip_submesh = state.service.working_mesh(state.face_flip_view.session_id).submeshes[0]
    state.service.close_edit_session(state.face_flip_view.session_id)
    state.empty_flip_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='empty-normal-flip', mode='edit')
    state.empty_flip = state.service.apply_command(state.empty_flip_view.session_id, MeshEditCommand('flip_normals'))
    state.empty_flip_submesh = state.service.working_mesh(state.empty_flip_view.session_id).submeshes[0]
    state.service.close_edit_session(state.empty_flip_view.session_id)
    state.source_flip_view = state.service.open_edit_session(build_synthetic_mesh(), session_id='source-normal-flip', mode='edit')
    state.source_flip = state.service.apply_command(state.source_flip_view.session_id, MeshEditCommand('flip_normals', selection=MeshEditSelection.from_maps(source_indices=(0,))))
    state.source_flip_submesh = state.service.working_mesh(state.source_flip_view.session_id).submeshes[0]
    state.service.close_edit_session(state.source_flip_view.session_id)

def _topology_result(state: SimpleNamespace) -> dict[str, object]:
    return {'ok': bool(state.duplicate.ok and state.duplicate.topology_changed and (state.duplicate.affected_submesh_indices == (1,)) and (len(state.duplicate_mesh.submeshes) == 2) and (state.copied.vertex_count == 3) and (state.copied.face_count == 1) and (state.copied.faces == [(0, 1, 2)]) and state.mirror.ok and state.mirror.topology_changed and (len(state.mirror_mesh.submeshes) == 2) and (state.mirrored.vertex_count == 3) and (state.mirrored.face_count == 1) and (state.mirrored.faces == [(0, 2, 1)]) and state.delete.ok and state.delete.topology_changed and (state.delete_submesh.vertex_count == 3) and (state.delete_submesh.face_count == 1) and (state.delete_submesh.faces == [(0, 2, 1)]) and state.dissolve.ok and state.dissolve.topology_changed and (state.dissolve_submesh.vertex_count == 4) and (state.dissolve_submesh.face_count == 1) and (state.dissolve_submesh.faces == [(1, 3, 2)]) and state.internal_dissolve.ok and state.internal_dissolve.topology_changed and (state.internal_dissolve_submesh.vertex_count == 4) and (state.internal_dissolve_submesh.face_count == 2) and (state.internal_dissolve_submesh.faces == [(0, 1, 3), (0, 3, 2)]) and state.subdivide.ok and state.subdivide.topology_changed and (state.subdivide_submesh.vertex_count == 7) and (state.subdivide_submesh.face_count == 5) and state.loop_cut.ok and state.loop_cut.topology_changed and (state.loop_cut_submesh.vertex_count == 5) and (state.loop_cut_submesh.face_count == 3) and (state.loop_cut_submesh.faces == [(3, 1, 4), (0, 3, 4), (0, 4, 2)]) and state.multi_cut.ok and state.multi_cut.topology_changed and (state.multi_cut_submesh.vertex_count == 5) and (state.multi_cut_submesh.face_count == 3) and (state.multi_cut_submesh.faces == [(0, 3, 2), (3, 4, 2), (4, 1, 2)]) and state.factor_cut.ok and state.factor_cut.topology_changed and (state.factor_cut_submesh.vertex_count == 4) and (state.factor_cut_submesh.face_count == 2) and (state.factor_cut_submesh.vertices[3] == (-0.375, -0.75, 0.0)) and (state.factor_cut_submesh.uvs[3] == (0.25, 1.0)) and (state.factor_cut_submesh.faces == [(0, 3, 2), (3, 1, 2)]) and state.split.ok and state.split.topology_changed and (len(state.split_mesh.submeshes) == 1) and (state.split_mesh.submeshes[0].vertex_count == 6) and (state.split_mesh.submeshes[0].face_count == 2) and (state.split_mesh.submeshes[0].faces == [(0, 4, 5), (1, 3, 2)]) and state.separate.ok and state.separate.topology_changed and (len(state.separate_mesh.submeshes) == 2) and (state.separate_mesh.submeshes[0].face_count == 1) and (state.separate_mesh.submeshes[1].face_count == 1) and state.fill.ok and state.fill.topology_changed and (state.fill_submesh.face_count == 3) and (state.fill_submesh.faces[-1] == (0, 1, 3)) and state.quad_fill.ok and state.quad_fill.topology_changed and (state.quad_fill_submesh.face_count == 2) and (state.quad_fill_submesh.faces == [(0, 1, 3), (0, 3, 2)]) and state.face_fill.ok and (not state.face_fill.topology_changed) and (state.face_fill_submesh.face_count == 2) and state.existing_fill.ok and (not state.existing_fill.topology_changed) and (state.existing_fill_submesh.face_count == 2) and state.extrude.ok and state.extrude.topology_changed and (state.extrude_submesh.vertex_count == 8) and (state.extrude_submesh.face_count == 12) and state.edge_extrude.ok and state.edge_extrude.topology_changed and (state.edge_extrude_submesh.vertex_count == 6) and (state.edge_extrude_submesh.face_count == 2) and (state.edge_extrude_submesh.faces == [(0, 1, 5), (0, 5, 4)]) and state.non_edge_extrude.ok and (not state.non_edge_extrude.topology_changed) and (state.non_edge_extrude.affected_submesh_indices == ()) and (state.non_edge_extrude_submesh.vertex_count == 4) and (state.non_edge_extrude_submesh.face_count == 2) and state.inset.ok and state.inset.topology_changed and (state.inset_submesh.vertex_count == 8) and (state.inset_submesh.face_count == 10) and state.inset_zero.ok and (not state.inset_zero.topology_changed) and (state.inset_zero_submesh.vertex_count == 4) and (state.inset_zero_submesh.face_count == 2) and state.merge.ok and state.merge.topology_changed and (state.merge_submesh.vertex_count == 4) and (state.merge_submesh.face_count == 2) and state.weld.ok and state.weld.topology_changed and (state.weld_submesh.vertex_count == 4) and (state.weld_submesh.face_count == 2) and state.bridge.ok and state.bridge.topology_changed and (state.bridge_submesh.face_count == 2) and (state.bridge_submesh.faces == [(0, 1, 3), (0, 3, 2)]) and state.filled_bridge.ok and (not state.filled_bridge.topology_changed) and (state.filled_bridge_submesh.face_count == 2) and state.empty_recalc.ok and (state.empty_recalc.affected_submesh_indices == ()) and (state.empty_recalc_normals == [[0.0, 0.0, -1.0]] * 4) and state.source_recalc.ok and (state.source_recalc.affected_submesh_indices == (0,)) and (state.source_recalc_normals == [[0.0, 0.0, 1.0]] * 4) and state.face_flip.ok and (not state.face_flip.topology_changed) and (state.face_flip.affected_submesh_indices == (0,)) and (state.face_flip_submesh.faces == [(0, 2, 1), (1, 3, 2)]) and state.empty_flip.ok and (not state.empty_flip.topology_changed) and (state.empty_flip.affected_submesh_indices == ()) and (state.empty_flip_submesh.faces == [(0, 1, 2), (1, 3, 2)]) and state.source_flip.ok and (not state.source_flip.topology_changed) and (state.source_flip.affected_submesh_indices == (0,)) and (state.source_flip_submesh.faces == [(0, 2, 1), (1, 2, 3)])), 'command': _command_summary(state.duplicate), 'submesh_count': len(state.duplicate_mesh.submeshes), 'copied_vertex_count': int(state.copied.vertex_count or len(state.copied.vertices)), 'copied_face_count': int(state.copied.face_count or len(state.copied.faces)), 'copied_faces': [list(face) for face in state.copied.faces], 'mirror': {'command': _command_summary(state.mirror), 'submesh_count': len(state.mirror_mesh.submeshes), 'vertex_count': int(state.mirrored.vertex_count or len(state.mirrored.vertices)), 'face_count': int(state.mirrored.face_count or len(state.mirrored.faces)), 'vertices': [list(vertex) for vertex in state.mirrored.vertices], 'faces': [list(face) for face in state.mirrored.faces]}, 'delete': {'command': _command_summary(state.delete), 'vertex_count': int(state.delete_submesh.vertex_count or len(state.delete_submesh.vertices)), 'face_count': int(state.delete_submesh.face_count or len(state.delete_submesh.faces)), 'faces': [list(face) for face in state.delete_submesh.faces]}, 'dissolve': {'command': _command_summary(state.dissolve), 'vertex_count': int(state.dissolve_submesh.vertex_count or len(state.dissolve_submesh.vertices)), 'face_count': int(state.dissolve_submesh.face_count or len(state.dissolve_submesh.faces)), 'faces': [list(face) for face in state.dissolve_submesh.faces]}, 'internal_dissolve': {'command': _command_summary(state.internal_dissolve), 'vertex_count': int(state.internal_dissolve_submesh.vertex_count or len(state.internal_dissolve_submesh.vertices)), 'face_count': int(state.internal_dissolve_submesh.face_count or len(state.internal_dissolve_submesh.faces)), 'faces': [list(face) for face in state.internal_dissolve_submesh.faces]}, 'subdivide': {'command': _command_summary(state.subdivide), 'vertex_count': int(state.subdivide_submesh.vertex_count or len(state.subdivide_submesh.vertices)), 'face_count': int(state.subdivide_submesh.face_count or len(state.subdivide_submesh.faces)), 'faces': [list(face) for face in state.subdivide_submesh.faces]}, 'loop_cut_two_edges': {'command': _command_summary(state.loop_cut), 'vertex_count': int(state.loop_cut_submesh.vertex_count or len(state.loop_cut_submesh.vertices)), 'face_count': int(state.loop_cut_submesh.face_count or len(state.loop_cut_submesh.faces)), 'faces': [list(face) for face in state.loop_cut_submesh.faces], 'changed_vertices': {str(submesh): list(vertices) for submesh, vertices in state.loop_cut.changed_vertices_by_submesh}}, 'loop_cut_multi': {'command': _command_summary(state.multi_cut), 'vertex_count': int(state.multi_cut_submesh.vertex_count or len(state.multi_cut_submesh.vertices)), 'face_count': int(state.multi_cut_submesh.face_count or len(state.multi_cut_submesh.faces)), 'vertices': [list(vertex) for vertex in state.multi_cut_submesh.vertices], 'uvs': [list(uv) for uv in state.multi_cut_submesh.uvs], 'faces': [list(face) for face in state.multi_cut_submesh.faces], 'changed_vertices': {str(submesh): list(vertices) for submesh, vertices in state.multi_cut.changed_vertices_by_submesh}}, 'loop_cut_factor': {'command': _command_summary(state.factor_cut), 'vertex_count': int(state.factor_cut_submesh.vertex_count or len(state.factor_cut_submesh.vertices)), 'face_count': int(state.factor_cut_submesh.face_count or len(state.factor_cut_submesh.faces)), 'vertices': [list(vertex) for vertex in state.factor_cut_submesh.vertices], 'uvs': [list(uv) for uv in state.factor_cut_submesh.uvs], 'faces': [list(face) for face in state.factor_cut_submesh.faces], 'changed_vertices': {str(submesh): list(vertices) for submesh, vertices in state.factor_cut.changed_vertices_by_submesh}}, 'split': {'command': _command_summary(state.split), 'submesh_count': len(state.split_mesh.submeshes), 'vertex_count': int(state.split_mesh.submeshes[0].vertex_count or len(state.split_mesh.submeshes[0].vertices)), 'face_count': int(state.split_mesh.submeshes[0].face_count or len(state.split_mesh.submeshes[0].faces)), 'faces': [list(face) for face in state.split_mesh.submeshes[0].faces], 'changed_vertices': {str(submesh): list(vertices) for submesh, vertices in state.split.changed_vertices_by_submesh}}, 'separate': {'command': _command_summary(state.separate), 'submesh_count': len(state.separate_mesh.submeshes), 'source_face_count': int(state.separate_mesh.submeshes[0].face_count or len(state.separate_mesh.submeshes[0].faces)), 'moved_face_count': int(state.separate_mesh.submeshes[1].face_count or len(state.separate_mesh.submeshes[1].faces)) if len(state.separate_mesh.submeshes) > 1 else 0}, 'fill': {'command': _command_summary(state.fill), 'face_count': int(state.fill_submesh.face_count or len(state.fill_submesh.faces)), 'faces': [list(face) for face in state.fill_submesh.faces]}, 'quad_fill': {'command': _command_summary(state.quad_fill), 'face_count': int(state.quad_fill_submesh.face_count or len(state.quad_fill_submesh.faces)), 'faces': [list(face) for face in state.quad_fill_submesh.faces]}, 'face_fill': {'command': _command_summary(state.face_fill), 'face_count': int(state.face_fill_submesh.face_count or len(state.face_fill_submesh.faces)), 'faces': [list(face) for face in state.face_fill_submesh.faces]}, 'existing_fill': {'command': _command_summary(state.existing_fill), 'face_count': int(state.existing_fill_submesh.face_count or len(state.existing_fill_submesh.faces)), 'faces': [list(face) for face in state.existing_fill_submesh.faces]}, 'extrude': {'command': _command_summary(state.extrude), 'vertex_count': int(state.extrude_submesh.vertex_count or len(state.extrude_submesh.vertices)), 'face_count': int(state.extrude_submesh.face_count or len(state.extrude_submesh.faces)), 'changed_vertices': {str(submesh): list(vertices) for submesh, vertices in state.extrude.changed_vertices_by_submesh}}, 'edge_extrude': {'command': _command_summary(state.edge_extrude), 'vertex_count': int(state.edge_extrude_submesh.vertex_count or len(state.edge_extrude_submesh.vertices)), 'face_count': int(state.edge_extrude_submesh.face_count or len(state.edge_extrude_submesh.faces)), 'vertices': [list(vertex) for vertex in state.edge_extrude_submesh.vertices], 'uvs': [list(uv) for uv in state.edge_extrude_submesh.uvs], 'faces': [list(face) for face in state.edge_extrude_submesh.faces], 'changed_vertices': {str(submesh): list(vertices) for submesh, vertices in state.edge_extrude.changed_vertices_by_submesh}}, 'non_edge_extrude': {'command': _command_summary(state.non_edge_extrude), 'vertex_count': int(state.non_edge_extrude_submesh.vertex_count or len(state.non_edge_extrude_submesh.vertices)), 'face_count': int(state.non_edge_extrude_submesh.face_count or len(state.non_edge_extrude_submesh.faces)), 'faces': [list(face) for face in state.non_edge_extrude_submesh.faces]}, 'inset': {'command': _command_summary(state.inset), 'vertex_count': int(state.inset_submesh.vertex_count or len(state.inset_submesh.vertices)), 'face_count': int(state.inset_submesh.face_count or len(state.inset_submesh.faces)), 'changed_vertices': {str(submesh): list(vertices) for submesh, vertices in state.inset.changed_vertices_by_submesh}}, 'inset_zero': {'command': _command_summary(state.inset_zero), 'vertex_count': int(state.inset_zero_submesh.vertex_count or len(state.inset_zero_submesh.vertices)), 'face_count': int(state.inset_zero_submesh.face_count or len(state.inset_zero_submesh.faces)), 'faces': [list(face) for face in state.inset_zero_submesh.faces]}, 'merge': {'command': _command_summary(state.merge), 'vertex_count': int(state.merge_submesh.vertex_count or len(state.merge_submesh.vertices)), 'face_count': int(state.merge_submesh.face_count or len(state.merge_submesh.faces)), 'faces': [list(face) for face in state.merge_submesh.faces]}, 'weld': {'command': _command_summary(state.weld), 'vertex_count': int(state.weld_submesh.vertex_count or len(state.weld_submesh.vertices)), 'face_count': int(state.weld_submesh.face_count or len(state.weld_submesh.faces)), 'faces': [list(face) for face in state.weld_submesh.faces]}, 'bridge': {'command': _command_summary(state.bridge), 'face_count': int(state.bridge_submesh.face_count or len(state.bridge_submesh.faces)), 'faces': [list(face) for face in state.bridge_submesh.faces]}, 'filled_bridge': {'command': _command_summary(state.filled_bridge), 'face_count': int(state.filled_bridge_submesh.face_count or len(state.filled_bridge_submesh.faces)), 'faces': [list(face) for face in state.filled_bridge_submesh.faces]}, 'empty_recalculate_normals': {'command': _command_summary(state.empty_recalc), 'normals': state.empty_recalc_normals}, 'source_recalculate_normals': {'command': _command_summary(state.source_recalc), 'normals': state.source_recalc_normals}, 'face_flip_normals': {'command': _command_summary(state.face_flip), 'face_count': int(state.face_flip_submesh.face_count or len(state.face_flip_submesh.faces)), 'faces': [list(face) for face in state.face_flip_submesh.faces]}, 'empty_flip_normals': {'command': _command_summary(state.empty_flip), 'face_count': int(state.empty_flip_submesh.face_count or len(state.empty_flip_submesh.faces)), 'faces': [list(face) for face in state.empty_flip_submesh.faces]}, 'source_flip_normals': {'command': _command_summary(state.source_flip), 'face_count': int(state.source_flip_submesh.face_count or len(state.source_flip_submesh.faces)), 'faces': [list(face) for face in state.source_flip_submesh.faces]}}

def _edge_face_topology_smoke() -> dict[str, object]:
    state = SimpleNamespace()
    _topology_phase_1(state)
    _topology_phase_2(state)
    _topology_phase_3(state)
    return _topology_result(state)
