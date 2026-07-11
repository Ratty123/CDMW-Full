from __future__ import annotations

from cdmw.domain.mesh import MeshEditCommand
from cdmw.domain.mesh import MeshEditSelection
from cdmw.services.mesh_service import MeshService

from tools.mesh_harness.fixtures import (
    _build_malformed_face_mesh,
    _build_two_part_synthetic_mesh,
    build_synthetic_mesh,
)

from tools.mesh_harness.service_summary import (
    _command_summary,
)

def _uv_operation_smoke() -> dict[str, object]:
    service = MeshService()
    view = service.open_edit_session(build_synthetic_mesh(), session_id="uv-pivot-flip", mode="edit")
    pivot_flip = service.apply_command(
        view.session_id,
        MeshEditCommand(
            "uv_transform",
            selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 2)}),
            params={"flip_u": True, "flip_v": True, "pivot": (0.25, 0.25)},
        ),
    )
    submesh = service.working_mesh(view.session_id).submeshes[0]
    service.close_edit_session(view.session_id)
    changed_vertices = {str(submesh_index): list(vertices) for submesh_index, vertices in pivot_flip.changed_vertices_by_submesh}
    uvs = [list(uv) for uv in submesh.uvs]
    normalize_view = service.open_edit_session(build_synthetic_mesh(), session_id="uv-normalize", mode="edit")
    normalize = service.apply_command(
        normalize_view.session_id,
        MeshEditCommand(
            "uv_transform",
            selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)}),
            params={"normalize": True, "target_max": (0.5, 0.5)},
        ),
    )
    normalize_uvs = [list(uv) for uv in service.working_mesh(normalize_view.session_id).submeshes[0].uvs]
    service.close_edit_session(normalize_view.session_id)
    project_mesh = build_synthetic_mesh()
    project_mesh.submeshes[0].uvs = [(0.0, 0.0)] * 4
    project_view = service.open_edit_session(project_mesh, session_id="uv-project", mode="edit")
    project = service.apply_command(
        project_view.session_id,
        MeshEditCommand(
            "uv_transform",
            selection=MeshEditSelection.from_maps(source_indices=(0,)),
            params={"projection": "planar", "plane": "xy"},
        ),
    )
    project_uvs = [list(uv) for uv in service.working_mesh(project_view.session_id).submeshes[0].uvs]
    service.close_edit_session(project_view.session_id)
    return {
        "ok": bool(
            pivot_flip.ok
            and changed_vertices == {"0": [1, 2]}
            and uvs[1] == [-0.5, -0.5]
            and uvs[2] == [0.5, 0.5]
            and normalize.ok
            and normalize_uvs == [[0.0, 0.5], [0.5, 0.5], [0.0, 0.0], [0.5, 0.0]]
            and project.ok
            and project_uvs == [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
        ),
        "pivot_flip": {
            "command": _command_summary(pivot_flip),
            "changed_vertices": changed_vertices,
            "uvs": uvs,
        },
        "normalize": {
            "command": _command_summary(normalize),
            "uvs": normalize_uvs,
        },
        "project": {
            "command": _command_summary(project),
            "uvs": project_uvs,
        },
    }

def _transform_target_smoke() -> dict[str, object]:
    service = MeshService()
    empty_view = service.open_edit_session(build_synthetic_mesh(), session_id="empty-transform-target", mode="edit")
    empty = service.apply_command(
        empty_view.session_id,
        MeshEditCommand("transform", params={"translate": (0.0, 0.0, 0.5)}),
    )
    empty_mesh = service.working_mesh(empty_view.session_id)
    empty_vertices = [list(vertex) for vertex in empty_mesh.submeshes[0].vertices]
    service.close_edit_session(empty_view.session_id)

    stale_edge_view = service.open_edit_session(build_synthetic_mesh(), session_id="stale-edge-transform-target", mode="edit")
    stale_edge = service.apply_command(
        stale_edge_view.session_id,
        MeshEditCommand(
            "transform",
            selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 99),)}),
            params={"translate": (0.0, 0.0, 0.5)},
        ),
    )
    stale_edge_mesh = service.working_mesh(stale_edge_view.session_id)
    stale_edge_vertices = [list(vertex) for vertex in stale_edge_mesh.submeshes[0].vertices]
    service.close_edit_session(stale_edge_view.session_id)

    non_edge_view = service.open_edit_session(build_synthetic_mesh(), session_id="non-edge-transform-target", mode="edit")
    non_edge = service.apply_command(
        non_edge_view.session_id,
        MeshEditCommand(
            "transform",
            selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 3),)}),
            params={"translate": (0.0, 0.0, 0.5)},
        ),
    )
    non_edge_mesh = service.working_mesh(non_edge_view.session_id)
    non_edge_vertices = [list(vertex) for vertex in non_edge_mesh.submeshes[0].vertices]
    service.close_edit_session(non_edge_view.session_id)

    source_view = service.open_edit_session(build_synthetic_mesh(), session_id="source-transform-target", mode="edit")
    source = service.apply_command(
        source_view.session_id,
        MeshEditCommand(
            "transform",
            selection=MeshEditSelection.from_maps(source_indices=(0,)),
            params={"translate": (0.0, 0.0, 0.5)},
        ),
    )
    source_mesh = service.working_mesh(source_view.session_id)
    source_vertices = [list(vertex) for vertex in source_mesh.submeshes[0].vertices]
    service.close_edit_session(source_view.session_id)
    return {
        "ok": bool(
            empty.ok
            and empty.affected_submesh_indices == ()
            and empty_vertices[0] == [-0.75, -0.75, 0.0]
            and stale_edge.ok
            and stale_edge.affected_submesh_indices == ()
            and stale_edge_vertices[0] == [-0.75, -0.75, 0.0]
            and non_edge.ok
            and non_edge.affected_submesh_indices == ()
            and non_edge_vertices[0] == [-0.75, -0.75, 0.0]
            and non_edge_vertices[3] == [0.75, 0.75, 0.0]
            and source.ok
            and source.affected_submesh_indices == (0,)
            and source_vertices[0] == [-0.75, -0.75, 0.5]
            and source_vertices[3] == [0.75, 0.75, 0.5]
        ),
        "empty": {
            "command": _command_summary(empty),
            "vertices": empty_vertices,
        },
        "stale_edge": {
            "command": _command_summary(stale_edge),
            "vertices": stale_edge_vertices,
        },
        "non_edge": {
            "command": _command_summary(non_edge),
            "vertices": non_edge_vertices,
        },
        "source": {
            "command": _command_summary(source),
            "vertices": source_vertices,
        },
    }

def _topology_target_smoke() -> dict[str, object]:
    service = MeshService()
    duplicate_empty_view = service.open_edit_session(build_synthetic_mesh(), session_id="empty-duplicate-target", mode="edit")
    duplicate_empty = service.apply_command(duplicate_empty_view.session_id, MeshEditCommand("duplicate"))
    duplicate_empty_count = service.session_view(duplicate_empty_view.session_id).submesh_count
    service.close_edit_session(duplicate_empty_view.session_id)

    duplicate_invalid_face_view = service.open_edit_session(build_synthetic_mesh(), session_id="invalid-face-duplicate-target", mode="edit")
    duplicate_invalid_face = service.apply_command(
        duplicate_invalid_face_view.session_id,
        MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (99,)})),
    )
    duplicate_invalid_face_count = service.session_view(duplicate_invalid_face_view.session_id).submesh_count
    service.close_edit_session(duplicate_invalid_face_view.session_id)

    malformed_face_mesh = _build_malformed_face_mesh()
    duplicate_malformed_face_view = service.open_edit_session(malformed_face_mesh, session_id="malformed-face-duplicate-target", mode="edit")
    duplicate_malformed_face = service.apply_command(
        duplicate_malformed_face_view.session_id,
        MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})),
    )
    duplicate_malformed_face_count = service.session_view(duplicate_malformed_face_view.session_id).submesh_count
    service.close_edit_session(duplicate_malformed_face_view.session_id)

    duplicate_source_view = service.open_edit_session(build_synthetic_mesh(), session_id="source-duplicate-target", mode="edit")
    duplicate_source = service.apply_command(
        duplicate_source_view.session_id,
        MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(source_indices=(0,))),
    )
    duplicate_source_count = service.session_view(duplicate_source_view.session_id).submesh_count
    service.close_edit_session(duplicate_source_view.session_id)

    mirror_empty_view = service.open_edit_session(build_synthetic_mesh(), session_id="empty-mirror-target", mode="edit")
    mirror_empty = service.apply_command(mirror_empty_view.session_id, MeshEditCommand("mirror", params={"axis": "x"}))
    mirror_empty_count = service.session_view(mirror_empty_view.session_id).submesh_count
    service.close_edit_session(mirror_empty_view.session_id)

    mirror_invalid_face_view = service.open_edit_session(build_synthetic_mesh(), session_id="invalid-face-mirror-target", mode="edit")
    mirror_invalid_face = service.apply_command(
        mirror_invalid_face_view.session_id,
        MeshEditCommand("mirror", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (99,)}), params={"axis": "x"}),
    )
    mirror_invalid_face_count = service.session_view(mirror_invalid_face_view.session_id).submesh_count
    service.close_edit_session(mirror_invalid_face_view.session_id)

    mirror_source_view = service.open_edit_session(build_synthetic_mesh(), session_id="source-mirror-target", mode="edit")
    mirror_source = service.apply_command(
        mirror_source_view.session_id,
        MeshEditCommand("mirror", selection=MeshEditSelection.from_maps(source_indices=(0,)), params={"axis": "x"}),
    )
    mirror_source_mesh = service.working_mesh(mirror_source_view.session_id)
    mirrored_vertices = [list(vertex) for vertex in mirror_source_mesh.submeshes[1].vertices] if len(mirror_source_mesh.submeshes) > 1 else []
    service.close_edit_session(mirror_source_view.session_id)

    mirror_in_place_empty_view = service.open_edit_session(build_synthetic_mesh(), session_id="empty-in-place-mirror-target", mode="edit")
    mirror_in_place_empty = service.apply_command(
        mirror_in_place_empty_view.session_id,
        MeshEditCommand("mirror", params={"axis": "x", "in_place": True}),
    )
    mirror_in_place_vertices = [list(vertex) for vertex in service.working_mesh(mirror_in_place_empty_view.session_id).submeshes[0].vertices]
    service.close_edit_session(mirror_in_place_empty_view.session_id)

    return {
        "ok": bool(
            duplicate_empty.ok
            and not duplicate_empty.topology_changed
            and duplicate_empty.affected_submesh_indices == ()
            and duplicate_empty_count == 1
            and duplicate_invalid_face.ok
            and not duplicate_invalid_face.topology_changed
            and duplicate_invalid_face.affected_submesh_indices == ()
            and duplicate_invalid_face_count == 1
            and duplicate_malformed_face.ok
            and not duplicate_malformed_face.topology_changed
            and duplicate_malformed_face.affected_submesh_indices == ()
            and duplicate_malformed_face_count == 1
            and duplicate_source.ok
            and duplicate_source.affected_submesh_indices == (1,)
            and duplicate_source_count == 2
            and mirror_empty.ok
            and not mirror_empty.topology_changed
            and mirror_empty.affected_submesh_indices == ()
            and mirror_empty_count == 1
            and mirror_invalid_face.ok
            and not mirror_invalid_face.topology_changed
            and mirror_invalid_face.affected_submesh_indices == ()
            and mirror_invalid_face_count == 1
            and mirror_source.ok
            and mirror_source.affected_submesh_indices == (1,)
            and len(mirrored_vertices) == 4
            and mirrored_vertices[1] == [-0.75, -0.75, 0.0]
            and mirror_in_place_empty.ok
            and mirror_in_place_empty.affected_submesh_indices == ()
            and mirror_in_place_vertices[1] == [0.75, -0.75, 0.0]
        ),
        "duplicate_empty": {"command": _command_summary(duplicate_empty), "submesh_count": duplicate_empty_count},
        "duplicate_invalid_face": {"command": _command_summary(duplicate_invalid_face), "submesh_count": duplicate_invalid_face_count},
        "duplicate_malformed_face": {"command": _command_summary(duplicate_malformed_face), "submesh_count": duplicate_malformed_face_count},
        "duplicate_source": {"command": _command_summary(duplicate_source), "submesh_count": duplicate_source_count},
        "mirror_empty": {"command": _command_summary(mirror_empty), "submesh_count": mirror_empty_count},
        "mirror_invalid_face": {"command": _command_summary(mirror_invalid_face), "submesh_count": mirror_invalid_face_count},
        "mirror_source": {"command": _command_summary(mirror_source), "vertices": mirrored_vertices},
        "mirror_in_place_empty": {"command": _command_summary(mirror_in_place_empty), "vertices": mirror_in_place_vertices},
    }

def _material_operation_smoke() -> dict[str, object]:
    service = MeshService()
    view = service.open_edit_session(build_synthetic_mesh(), session_id="face-material-assign", mode="edit")
    face_assign = service.apply_command(
        view.session_id,
        MeshEditCommand(
            "material_assign",
            selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
            params={
                "material": "face_material",
                "texture": "face.dds",
                "material_profile": "runtime_xml",
                "native_material_overrides": {"roughness": 0.4},
            },
        ),
    )
    mesh = service.working_mesh(view.session_id)
    service.close_edit_session(view.session_id)
    submeshes = [
        {
            "material": str(submesh.material or ""),
            "texture": str(submesh.texture or ""),
            "face_count": int(submesh.face_count or len(submesh.faces)),
            "overrides": dict(getattr(submesh, "preview_native_material_overrides", {}) or {}),
        }
        for submesh in mesh.submeshes
    ]
    copy_view = service.open_edit_session(_build_two_part_synthetic_mesh(), session_id="face-material-copy", mode="edit")
    face_copy = service.apply_command(
        copy_view.session_id,
        MeshEditCommand(
            "material_copy",
            selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}),
            params={"source_submesh_index": 0},
        ),
    )
    copy_mesh = service.working_mesh(copy_view.session_id)
    service.close_edit_session(copy_view.session_id)
    copied_submeshes = [
        {
            "material": str(submesh.material or ""),
            "texture": str(submesh.texture or ""),
            "face_count": int(submesh.face_count or len(submesh.faces)),
            "overrides": dict(getattr(submesh, "preview_native_material_overrides", {}) or {}),
        }
        for submesh in copy_mesh.submeshes
    ]
    plain_view = service.open_edit_session(_build_two_part_synthetic_mesh(), session_id="plain-material-assign-reset", mode="edit")
    plain_assign = service.apply_command(
        plain_view.session_id,
        MeshEditCommand(
            "material_assign",
            selection=MeshEditSelection.from_maps(source_indices=(0,)),
            params={"material": "plain_material", "texture": "plain.dds"},
        ),
    )
    plain_submesh = service.working_mesh(plain_view.session_id).submeshes[0]
    material_route_attrs = (
        "cdmw_material_authority_profile",
        "cdmw_material_authority_contract",
        "cdmw_source_material_name",
        "cdmw_target_material_name",
        "cdmw_target_material_slot_index",
        "cdmw_material_slot_kind",
        "cdmw_source_texture_set_key",
        "cdmw_material_route_status",
        "cdmw_material_route_reason",
    )
    plain_reset = {
        "command": _command_summary(plain_assign),
        "material": str(plain_submesh.material or ""),
        "texture": str(plain_submesh.texture or ""),
        "has_route_metadata": any(hasattr(plain_submesh, attr_name) for attr_name in material_route_attrs),
        "overrides": dict(getattr(plain_submesh, "preview_native_material_overrides", {}) or {}),
    }
    service.close_edit_session(plain_view.session_id)
    return {
        "ok": bool(
            face_assign.ok
            and face_assign.topology_changed
            and set(face_assign.affected_submesh_indices) == {0, 1}
            and len(submeshes) == 2
            and submeshes[0]["material"] == "harness_material"
            and submeshes[0]["face_count"] == 1
            and submeshes[1]["material"] == "face_material"
            and submeshes[1]["texture"] == "face.dds"
            and submeshes[1]["face_count"] == 1
            and submeshes[1]["overrides"] == {"roughness": 0.4}
            and face_copy.ok
            and face_copy.topology_changed
            and set(face_copy.affected_submesh_indices) == {1, 2}
            and len(copied_submeshes) == 3
            and copied_submeshes[1]["material"] == "harness_material_b"
            and copied_submeshes[1]["face_count"] == 1
            and copied_submeshes[2]["material"] == "harness_material"
            and copied_submeshes[2]["texture"] == "harness.dds"
            and copied_submeshes[2]["face_count"] == 1
            and copied_submeshes[2]["overrides"] == {"roughness": 0.2, "metalness": 0.6}
            and plain_assign.ok
            and plain_assign.affected_submesh_indices == (0,)
            and plain_reset["material"] == "plain_material"
            and plain_reset["texture"] == "plain.dds"
            and not plain_reset["has_route_metadata"]
            and plain_reset["overrides"] == {}
        ),
        "face_assign": {
            "command": _command_summary(face_assign),
            "submeshes": submeshes,
        },
        "face_copy": {
            "command": _command_summary(face_copy),
            "submeshes": copied_submeshes,
        },
        "plain_assign_reset": plain_reset,
    }
