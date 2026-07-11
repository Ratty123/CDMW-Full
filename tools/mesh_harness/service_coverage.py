from __future__ import annotations

from cdmw.ui.mesh_editor.actions import MESH_EDITOR_ACTIONS
from cdmw.domain.mesh import MESH_EDIT_ACTIONS
from cdmw.domain.mesh import MeshEditCommand
from cdmw.domain.mesh import MeshEditSelection
from cdmw.ui.mesh_editor.controller import MeshEditorController
from cdmw.services.mesh_service import MeshService

from tools.mesh_harness.constants import (
    _SYNTHETIC_MESH_FORMATS,
)

from tools.mesh_harness.fixtures import (
    _build_two_part_synthetic_mesh,
    build_synthetic_mesh,
)

from tools.mesh_harness.service_summary import (
    _command_summary,
    _palette_command_summary,
)

def _coverage_command(action: str) -> MeshEditCommand:
    vertices = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)})
    face = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)}, faces_by_submesh={0: (0,)})
    source = MeshEditSelection.from_maps(source_indices=(0,))
    edge = MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)})
    if action == "set_mode":
        return MeshEditCommand(action, mode="sculpt")
    if action in {"triangulate_display", "quadrangulate_display"}:
        return MeshEditCommand(action, selection=vertices, params={"allow_legacy_display_cleanup": True})
    if action == "select":
        return MeshEditCommand(action, selection=face)
    if action == "transform":
        return MeshEditCommand(action, selection=vertices, params={"translate": (0.03, 0.03, 0.13), "axis": "z", "snap": 0.05})
    if action == "brush":
        return MeshEditCommand(action, selection=vertices, mode="sculpt", params={"tool": "smooth", "center": (0.0, 0.0, 0.0), "radius": 3.0, "strength": 0.25})
    if action in {"delete", "dissolve", "subdivide", "split", "separate", "duplicate", "extrude", "inset"}:
        return MeshEditCommand(action, selection=face, params={"offset": (0.0, 0.0, 0.1), "amount": 0.2})
    if action == "mirror":
        return MeshEditCommand(action, selection=source, params={"axis": "x"})
    if action in {"loop_cut", "edge_split"}:
        return MeshEditCommand(action, selection=edge)
    if action in {"merge", "weld"}:
        return MeshEditCommand(action, selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)}))
    if action == "bridge":
        return MeshEditCommand(action, selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (2, 3))}))
    if action == "fill":
        return MeshEditCommand(action, selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2)}))
    if action in {
        "recalculate_normals",
        "generate_tangents",
        "flip_normals",
        "sharpen_normals",
        "soften_normals",
        "weighted_normals",
        "copy_normals",
    }:
        return MeshEditCommand(action, selection=source)
    if action == "uv_transform":
        return MeshEditCommand(
            action,
            selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}),
            params={"uv_island": True, "flip_u": True, "rotate": 5.0, "pivot": (0.5, 0.5), "offset": (0.05, 0.0)},
        )
    if action == "material_assign":
        return MeshEditCommand(action, selection=source, params={"material": "coverage_material", "texture": "coverage.dds"})
    if action == "material_copy":
        return MeshEditCommand(action, selection=MeshEditSelection.from_maps(source_indices=(1,)), params={"source_submesh_index": 0})
    return MeshEditCommand(action, selection=vertices)

def run_service_command_coverage() -> dict[str, object]:
    service = MeshService()
    commands: list[dict[str, object]] = []
    primary_format = _SYNTHETIC_MESH_FORMATS[0]
    for action in MESH_EDIT_ACTIONS:
        mesh = _build_two_part_synthetic_mesh(primary_format) if action == "material_copy" else build_synthetic_mesh(primary_format)
        view = service.open_edit_session(mesh, session_id=f"coverage-{primary_format}-{action}", mode="edit")
        result = service.apply_command(view.session_id, _coverage_command(action))
        summary = _command_summary(result)
        summary["mesh_format"] = primary_format
        commands.append(summary)
        service.close_edit_session(view.session_id)
    for mesh_format in _SYNTHETIC_MESH_FORMATS[1:]:
        view = service.open_edit_session(build_synthetic_mesh(mesh_format), session_id=f"coverage-{mesh_format}-transform", mode="edit")
        result = service.apply_command(view.session_id, _coverage_command("transform"))
        summary = _command_summary(result)
        summary["mesh_format"] = mesh_format
        commands.append(summary)
        service.close_edit_session(view.session_id)

    view = service.open_edit_session(build_synthetic_mesh(), session_id="coverage-history", mode="edit")
    selection = MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})
    service.apply_command(view.session_id, MeshEditCommand("transform", selection=selection, params={"translate": (0.0, 0.0, 0.1)}))
    commands.append(_command_summary(service.undo(view.session_id)))
    commands.append(_command_summary(service.redo(view.session_id)))
    service.close_edit_session(view.session_id)

    required = set(MESH_EDIT_ACTIONS) | {"undo", "redo"}
    covered = {str(command["action"]) for command in commands}
    covered_formats = {str(command.get("mesh_format", "")) for command in commands if command.get("mesh_format")}
    missing = sorted(required - covered)
    bad_status = [command for command in commands if command["status"] not in {"ok", "noop"}]
    return {
        "ok": not missing and not bad_status,
        "required_actions": sorted(required),
        "covered_actions": sorted(covered),
        "covered_formats": sorted(covered_formats),
        "missing_actions": missing,
        "commands": commands,
    }

def run_controller_action_palette_coverage() -> dict[str, object]:
    commands: list[dict[str, object]] = []
    for action in MESH_EDITOR_ACTIONS:
        mesh = _build_two_part_synthetic_mesh() if action.key == "material_copy" else build_synthetic_mesh()
        controller = MeshEditorController()
        controller.open_mesh(mesh, session_id=f"palette-{action.key}", mode="edit")
        selection, params = _palette_action_input(action.key, action.command)
        if action.command == "undo":
            controller.apply("transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}), translate=(0.0, 0.0, 0.1))
        elif action.command == "redo":
            controller.apply("transform", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}), translate=(0.0, 0.0, 0.1))
            controller.undo()
        result = controller.run_editor_action(action, selection=selection, **params)
        commands.append(_palette_command_summary(action.key, action.command, result))
        controller.close_active_session()

    required = {action.key for action in MESH_EDITOR_ACTIONS}
    covered = {str(command["key"]) for command in commands}
    missing = sorted(required - covered)
    bad_status = [command for command in commands if command["status"] not in {"ok", "noop"}]
    return {
        "ok": not missing and not bad_status,
        "required_actions": sorted(required),
        "covered_actions": sorted(covered),
        "missing_actions": missing,
        "commands": commands,
    }

def _palette_action_input(action_key: str, command: str) -> tuple[MeshEditSelection | None, dict[str, object]]:
    vertices = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)})
    face = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)}, faces_by_submesh={0: (0,)})
    source = MeshEditSelection.from_maps(source_indices=(0,))
    if command == "select":
        if action_key == "select_edge":
            return MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)}), {}
        if action_key == "select_face":
            return MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}), {}
        return MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}), {}
    if command == "transform":
        return vertices, {"translate": (0.0, 0.0, 0.1)} if action_key == "transform_move" else {}
    if command == "brush":
        return vertices, {"center": (0.0, 0.0, 0.0), "radius": 3.0, "strength": 0.25, "delta": (0.0, 0.0, 0.1), "amount": 0.1}
    if command in {"delete", "dissolve", "subdivide", "split", "separate", "duplicate", "extrude", "inset"}:
        return face, {"offset": (0.0, 0.0, 0.1), "amount": 0.2}
    if command == "mirror":
        return source, {"axis": "x"}
    if command in {"loop_cut", "edge_split"}:
        return MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)}), {}
    if command == "bridge":
        return MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (2, 3))}), {}
    if command in {"merge", "weld"}:
        return MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)}), {}
    if command == "fill":
        return MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2)}), {}
    if command in {"recalculate_normals", "generate_tangents", "flip_normals", "sharpen_normals", "soften_normals", "copy_normals"}:
        return source, {}
    if command == "uv_transform":
        if action_key == "uv_rotate_90":
            return MeshEditSelection.from_maps(vertices_by_submesh={0: (3,)}), {}
        if action_key == "uv_normalize":
            return MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)}), {"target_max": (0.5, 0.5)}
        if action_key == "uv_align_u":
            return MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1)}), {}
        if action_key == "uv_align_v":
            return MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 2)}), {}
        if action_key == "uv_planar_project":
            return MeshEditSelection.from_maps(source_indices=(0,)), {}
        if action_key in {"uv_box_project", "uv_cylindrical_project", "uv_auto_unwrap", "uv_pack"}:
            return MeshEditSelection.from_maps(source_indices=(0,)), {}
        if action_key == "uv_snap_grid":
            return MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}), {"offset": (0.08, 0.0)}
        if action_key == "uv_snap_pixels":
            return MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}), {"offset": (0.0006, 0.0)}
        return MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}), {"rotate": 5.0, "pivot": (0.5, 0.5), "offset": (0.05, 0.0)}
    if command == "material_assign":
        return source, {
            "material": "palette_material",
            "texture": "palette.dds",
            "material_authority_profile": "material_authority_detail_mask",
            "roughness": 0.35,
            "metalness": 0.15,
        }
    if command == "material_copy":
        return MeshEditSelection.from_maps(source_indices=(1,)), {"source_submesh_index": 0}
    return None, {}
