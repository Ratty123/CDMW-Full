from __future__ import annotations

from cdmw.domain.mesh import MeshEditCommand
from cdmw.domain.mesh import MeshEditSelection
from cdmw.services.mesh_service import MeshService
from cdmw.modding.mesh_parser import ParsedMesh

from tools.mesh_harness.fixtures import (
    build_synthetic_mesh,
)

from tools.mesh_harness.service_coverage import (
    run_controller_action_palette_coverage,
    run_service_command_coverage,
)

from tools.mesh_harness.service_selection import (
    _history_context_smoke,
    _history_selection_smoke,
    _selection_operation_smoke,
    _selection_pruning_smoke,
)

from tools.mesh_harness.service_summary import (
    _command_summary,
)

from tools.mesh_harness.service_targets import (
    _material_operation_smoke,
    _topology_target_smoke,
    _transform_target_smoke,
    _uv_operation_smoke,
)

from tools.mesh_harness.service_topology import (
    _edge_face_topology_smoke,
)

def run_service_smoke() -> tuple[ParsedMesh, dict[str, object]]:
    service = MeshService()
    view = service.open_edit_session(build_synthetic_mesh(), session_id="harness", mode="edit")
    selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)}, faces_by_submesh={0: (0,)})
    selection_operations = _selection_operation_smoke(service, view.session_id)
    selection_pruning = _selection_pruning_smoke()
    history_selection = _history_selection_smoke()
    history_context = _history_context_smoke()
    edge_face_topology = _edge_face_topology_smoke()
    uv_operations = _uv_operation_smoke()
    material_operations = _material_operation_smoke()
    transform_targets = _transform_target_smoke()
    topology_targets = _topology_target_smoke()
    results = [
        service.apply_command(view.session_id, MeshEditCommand("select", selection=selection)),
        service.apply_command(
            view.session_id,
            MeshEditCommand("transform", params={"translate": (0.03, 0.03, 0.21), "axis": "z", "snap": 0.05}),
        ),
        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "transform",
                selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1,)}),
                params={"pivot": (0.0, 0.0, 0.2), "scale": (1.05, 1.05, 1.0), "rotate": (0.0, 0.0, 5.0)},
            ),
        ),
        service.apply_command(
            view.session_id,
            MeshEditCommand("brush", mode="sculpt", params={"tool": "pinch", "center": (0.0, 0.0, 0.2), "radius": 3.0, "strength": 0.25, "amount": 0.1}),
        ),
        service.apply_command(
            view.session_id,
            MeshEditCommand("bridge", mode="edit", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (2, 3))})),
        ),
        service.apply_command(
            view.session_id,
            MeshEditCommand("loop_cut", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 3),)})),
        ),
        service.apply_command(
            view.session_id,
            MeshEditCommand("edge_split", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)})),
        ),
        service.apply_command(view.session_id, MeshEditCommand("extrude", params={"offset": (0.0, 0.0, 0.2)})),
        service.apply_command(view.session_id, MeshEditCommand("uv_transform", params={"rotate": 5.0, "pivot": (0.5, 0.5), "offset": (0.05, -0.05)})),
        service.apply_command(
            view.session_id,
            MeshEditCommand(
                "material_assign",
                selection=MeshEditSelection.from_maps(source_indices=(0,)),
                params={
                    "material": "edited_material",
                    "texture": "edited.dds",
                    "material_authority_profile": "material_authority_detail_mask",
                    "roughness": 0.4,
                    "metalness": 0.2,
                },
            ),
        ),
    ]
    undo = service.undo(view.session_id)
    redo = service.redo(view.session_id)
    mesh = service.working_mesh(view.session_id, clone=True)
    final_view = service.session_view(view.session_id)
    coverage = run_service_command_coverage()
    palette = run_controller_action_palette_coverage()
    ok = (
        all(result.ok for result in results)
        and undo.ok
        and redo.ok
        and mesh.total_faces > 2
        and bool(selection_operations.get("ok"))
        and bool(selection_pruning.get("ok"))
        and bool(history_selection.get("ok"))
        and bool(history_context.get("ok"))
        and bool(edge_face_topology.get("ok"))
        and bool(uv_operations.get("ok"))
        and bool(material_operations.get("ok"))
        and bool(transform_targets.get("ok"))
        and bool(topology_targets.get("ok"))
        and bool(coverage.get("ok"))
        and bool(palette.get("ok"))
    )
    return mesh, {
        "ok": bool(ok),
        "session": {
            "revision": final_view.revision,
            "submesh_count": final_view.submesh_count,
            "vertex_count": final_view.vertex_count,
            "face_count": final_view.face_count,
            "undo_count": final_view.undo_count,
            "redo_count": final_view.redo_count,
        },
        "commands": [_command_summary(result) for result in (*results, undo, redo)],
        "selection_operations": selection_operations,
        "selection_pruning": selection_pruning,
        "history_selection": history_selection,
        "history_context": history_context,
        "edge_face_topology": edge_face_topology,
        "uv_operations": uv_operations,
        "material_operations": material_operations,
        "transform_targets": transform_targets,
        "topology_targets": topology_targets,
        "coverage": coverage,
        "palette": palette,
    }
