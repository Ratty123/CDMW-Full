from __future__ import annotations

import argparse
from collections import Counter
import ctypes
import json
import os
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path
from typing import Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cdmw.core.archive_extraction import _read_archive_entry_data_from_handle, read_archive_entry_data
from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_binary_preview import build_binary_sidecar_analysis_document
from cdmw.core.skeleton_resolver import resolve_skeleton_for_model
from cdmw.domain.mesh import MESH_EDIT_ACTIONS, MeshEditCommand, MeshEditSelection
from cdmw.models import ArchiveEntry
from cdmw.modding.animation_parser import parse_paa_animation_clip
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, parse_mesh
from cdmw.modding.skeleton_parser import parse_pab
from cdmw.modding.skeleton_variation_parser import parse_pabc_skeleton_variation
from cdmw.rendering.native_d3d11_host import find_native_d3d11_host
from cdmw.services.mesh_service import MeshService
from cdmw.ui.mesh_editor.native_preview_payloads import (
    mesh_edit_material_override_groups,
    mesh_edit_selection_groups,
    mesh_edit_triangle_groups,
    mesh_edit_vertex_update_groups,
    mesh_to_native_preview,
)
from cdmw.ui.mesh_editor.actions import MESH_EDITOR_ACTIONS
from cdmw.ui.mesh_editor.controller import MeshEditorController
from cdmw.ui.mesh_editor.native_preview_runtime import mesh_editor_write_native_preview_package

_WM_COPYDATA = 0x004A
_WM_CLOSE = 0x0010
_WM_COPYDATA_COMMAND = 0x43444D57
_HOST_CLASS = "CDMWNativeD3D11PreviewWindow"
_SYNTHETIC_MESH_FORMATS = ("pac", "pam", "pamlod")
_DEFAULT_GAME_ROOT = Path(r"C:\games\Steam\steamapps\common\Crimson Desert")
_REAL_ARCHIVE_RIGGING_SAMPLES = (
    "character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac",
    "character/model/1_pc/10_pgw/nude/cd_pgw_00_nude_00_0001.pac",
)
_REAL_ARCHIVE_ANIMATION_SAMPLE_LIMIT = 8
_REAL_ARCHIVE_ANIMATION_PREFERRED_PAA = (
    "character/motion/1_pc/14_ptm/00_mon/cd_hardptm_baxe_01_01_att_move_f_jumpatt_00.paa",
    "character/motion/1_pc/14_ptm/00_mon/cd_hardptm_baxe_01_01_att_nor_coma_move_f_00.paa",
    "character/motion/1_pc/14_ptm/00_mon/cd_ptm_basic_01_01_nor_std_idle_00.paa",
    "character/motion/1_pc/14_ptm/00_mon/cd_ptm_basic_00_01_normal_stand_idle_000.paa",
    "character/motion/1_pc/cd_phm_basic_00_00_abn_dam_upper_l_end_05_00.paa",
)
_REAL_ARCHIVE_SEQUENCE_SAMPLE = "sequencer/binary__/stageseq/abyssone/cd_seq_abyss_miseenscene_0003.paseqc"
_REAL_ARCHIVE_SEQUENCE_PTM_PAA = "character/motion/1_pc/14_ptm/01_npc/cd_ptm_backpack_00_00_nor_std_idle_ing_03.paa"
_REAL_ARCHIVE_SEQUENCE_PTM_PAB = "character/model/1_pc/14_ptm/ptm_01.pab"
_REAL_ARCHIVE_SEQUENCE_PTM_DESCRIPTOR = "character/prefab/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.prefabdata_xml"
_REAL_ARCHIVE_SEQUENCE_PTM_PAPR = "character/model/1_pc/14_ptm/ptm_01.papr"
_REAL_ARCHIVE_SEQUENCE_EXTENSIONS = (".paseq", ".paseqc", ".pastage", ".paschedule", ".paschedulepath")
_ADVANCED_AUTHORING_CORPUS_EXTENSIONS = (
    ".paa",
    ".paseq",
    ".paseqc",
    ".papr",
    ".pabc",
    ".pab",
    ".pac",
    ".pam",
    ".pamlod",
    ".hkx",
    ".xml",
    ".material",
    ".shader",
)
_ADVANCED_AUTHORING_CONFIDENCE_LABELS = ("proven", "inferred", "unknown", "blocked")
_ADVANCED_AUTHORING_STATE_LABELS = ("blocked", "preview-only", "exportable", "archive-mutable")


def build_synthetic_mesh(mesh_format: str = "pac") -> ParsedMesh:
    mesh_format = str(mesh_format or "pac").strip().lower()
    if mesh_format not in _SYNTHETIC_MESH_FORMATS:
        raise ValueError(f"Unsupported synthetic mesh format: {mesh_format!r}")
    submesh = SubMesh(
        name="harness_quad",
        material="harness_material",
        texture="harness.dds",
        vertices=[
            (-0.75, -0.75, 0.0),
            (0.75, -0.75, 0.0),
            (-0.75, 0.75, 0.0),
            (0.75, 0.75, 0.0),
        ],
        uvs=[(0.0, 1.0), (1.0, 1.0), (0.0, 0.0), (1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        faces=[(0, 1, 2), (1, 3, 2)],
        vertex_count=4,
        face_count=2,
    )
    return ParsedMesh(
        path=f"tools/harness_quad.{mesh_format}",
        format=mesh_format,
        bbox_min=(-0.75, -0.75, 0.0),
        bbox_max=(0.75, 0.75, 0.0),
        submeshes=[submesh],
        total_vertices=4,
        total_faces=2,
        has_uvs=True,
    )


def _build_malformed_face_mesh(mesh_format: str = "pac") -> ParsedMesh:
    mesh = build_synthetic_mesh(mesh_format)
    submesh = mesh.submeshes[0]
    submesh.faces = [(0, "bad", 3), (0, 1, 2), (0, True, 2), (0, 1.9, 2)]  # type: ignore[list-item]
    submesh.face_count = len(submesh.faces)
    mesh.total_faces = len(submesh.faces)
    return mesh


def _build_loose_edge_mesh(mesh_format: str = "pac") -> ParsedMesh:
    mesh = build_synthetic_mesh(mesh_format)
    submesh = mesh.submeshes[0]
    submesh.faces = []
    submesh.face_count = 0
    mesh.total_faces = 0
    return mesh


def _build_two_part_synthetic_mesh(mesh_format: str = "pac") -> ParsedMesh:
    mesh = build_synthetic_mesh(mesh_format)
    source = mesh.submeshes[0]
    source.preview_native_material_overrides = {"roughness": 0.2, "metalness": 0.6}
    source.cdmw_material_authority_profile = "material_authority_detail_mask"
    source.cdmw_material_authority_contract = "true_source_authority_detail_mask"
    mesh.submeshes.append(
        SubMesh(
            name="harness_quad_b",
            material="harness_material_b",
            texture="harness_b.dds",
            vertices=list(source.vertices),
            uvs=list(source.uvs),
            normals=list(source.normals),
            faces=list(source.faces),
            vertex_count=len(source.vertices),
            face_count=len(source.faces),
        )
    )
    mesh.total_vertices = sum(len(submesh.vertices) for submesh in mesh.submeshes)
    mesh.total_faces = sum(len(submesh.faces) for submesh in mesh.submeshes)
    return mesh


def _coverage_command(action: str) -> MeshEditCommand:
    vertices = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)})
    face = MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3)}, faces_by_submesh={0: (0,)})
    source = MeshEditSelection.from_maps(source_indices=(0,))
    edge = MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)})
    if action == "set_mode":
        return MeshEditCommand(action, mode="sculpt")
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
    if action in {"recalculate_normals", "generate_tangents", "flip_normals", "sharpen_normals", "soften_normals", "copy_normals"}:
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
    for mesh_format in _SYNTHETIC_MESH_FORMATS:
        for action in MESH_EDIT_ACTIONS:
            mesh = _build_two_part_synthetic_mesh(mesh_format) if action == "material_copy" else build_synthetic_mesh(mesh_format)
            view = service.open_edit_session(mesh, session_id=f"coverage-{mesh_format}-{action}", mode="edit")
            result = service.apply_command(view.session_id, _coverage_command(action))
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
        if action_key in {"uv_box_project", "uv_cylindrical_project", "uv_pack"}:
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


def _command_summary(result: object) -> dict[str, object]:
    return {
        "action": getattr(result, "action", ""),
        "status": getattr(result, "status", ""),
        "revision": getattr(result, "revision", 0),
        "affected_submesh_indices": list(getattr(result, "affected_submesh_indices", ())),
        "topology_changed": bool(getattr(result, "topology_changed", False)),
    }


def _palette_command_summary(action_key: str, command: str, result: object) -> dict[str, object]:
    edit_result = getattr(result, "edit_result")
    native_update = getattr(result, "native_update")
    summary = _command_summary(edit_result)
    summary["key"] = action_key
    summary["command"] = command
    summary["vertex_update_group_count"] = len(getattr(native_update, "vertex_groups", ()) or ())
    summary["triangle_group_count"] = len(getattr(native_update, "triangle_groups", ()) or ())
    summary["selection_group_count"] = len(getattr(native_update, "selection_groups", ()) or ())
    summary["selection_refresh"] = bool(getattr(native_update, "refresh_selection", False))
    summary["material_override_group_count"] = len(getattr(native_update, "material_override_groups", ()) or ())
    return summary


def _selection_operation_smoke(service: MeshService, session_id: str) -> dict[str, object]:
    service.apply_command(
        session_id,
        MeshEditCommand(
            "select",
            selection=MeshEditSelection.from_maps(
                vertices_by_submesh={0: (0,)},
                edges_by_submesh={0: ((0, 1),)},
                faces_by_submesh={0: (0,)},
                source_indices=(0,),
            ),
        ),
    )
    service.apply_command(
        session_id,
        MeshEditCommand(
            "select",
            selection=MeshEditSelection.from_maps(
                vertices_by_submesh={0: (3,)},
                edges_by_submesh={0: ((1, 2),)},
                faces_by_submesh={0: (1,)},
                source_indices=(1,),
            ),
            params={"operation": "add"},
        ),
    )
    added = _selection_snapshot(service.session_view(session_id).selection)
    service.apply_command(
        session_id,
        MeshEditCommand(
            "select",
            selection=MeshEditSelection.from_maps(
                vertices_by_submesh={0: (0,)},
                edges_by_submesh={0: ((0, 1),)},
                faces_by_submesh={0: (0,)},
                source_indices=(0,),
            ),
            params={"operation": "subtract"},
        ),
    )
    subtracted = _selection_snapshot(service.session_view(session_id).selection)
    service.apply_command(
        session_id,
        MeshEditCommand(
            "select",
            selection=MeshEditSelection.from_maps(
                vertices_by_submesh={0: (2, 3)},
                edges_by_submesh={0: ((1, 2), (2, 3))},
                faces_by_submesh={0: (1,)},
                source_indices=(1, 2),
            ),
            params={"operation": "toggle"},
        ),
    )
    toggled = _selection_snapshot(service.session_view(session_id).selection)
    return {
        "ok": bool(
            added["vertices_by_submesh"] == {"0": [0, 3]}
            and subtracted["vertices_by_submesh"] == {"0": [3]}
            and toggled["vertices_by_submesh"] == {"0": [2]}
            and added["edges_by_submesh"] == {"0": [[0, 1], [1, 2]]}
            and subtracted["edges_by_submesh"] == {"0": [[1, 2]]}
            and toggled["edges_by_submesh"] == {"0": [[2, 3]]}
            and toggled["faces_by_submesh"] == {}
            and toggled["source_indices"] == []
        ),
        "added": added,
        "subtracted": subtracted,
        "toggled": toggled,
    }


def _selection_pruning_smoke() -> dict[str, object]:
    service = MeshService()
    malformed_view = service.open_edit_session(_build_malformed_face_mesh(), session_id="selection-prune-malformed", mode="edit")
    service.apply_command(
        malformed_view.session_id,
        MeshEditCommand(
            "select",
            selection=MeshEditSelection.from_maps(
                vertices_by_submesh={0: (0, 3)},
                edges_by_submesh={0: ((0, 1), (0, 3))},
                faces_by_submesh={0: (0, 1)},
            ),
        ),
    )
    malformed = _selection_snapshot(service.session_view(malformed_view.session_id).selection)
    service.close_edit_session(malformed_view.session_id)

    loose_edge_view = service.open_edit_session(_build_loose_edge_mesh(), session_id="selection-prune-loose-edge", mode="edit")
    service.apply_command(
        loose_edge_view.session_id,
        MeshEditCommand("select", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 3), (1, 99))})),
    )
    loose_edge = _selection_snapshot(service.session_view(loose_edge_view.session_id).selection)
    service.close_edit_session(loose_edge_view.session_id)

    return {
        "ok": bool(
            malformed["vertices_by_submesh"] == {"0": [0, 3]}
            and malformed["edges_by_submesh"] == {"0": [[0, 1]]}
            and malformed["faces_by_submesh"] == {"0": [1]}
            and loose_edge["edges_by_submesh"] == {"0": [[0, 3]]}
        ),
        "malformed": malformed,
        "loose_edge": loose_edge,
    }


def _history_selection_smoke() -> dict[str, object]:
    service = MeshService()
    view = service.open_edit_session(build_synthetic_mesh(), session_id="history-selection-prune", mode="edit")
    duplicate = service.apply_command(
        view.session_id,
        MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})),
    )
    service.apply_command(
        view.session_id,
        MeshEditCommand("select", selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}, source_indices=(1,))),
    )
    before_undo = _selection_snapshot(service.session_view(view.session_id).selection)
    undo = service.undo(view.session_id)
    undo_view = service.session_view(view.session_id)
    after_undo = _selection_snapshot(undo_view.selection)
    service.close_edit_session(view.session_id)
    return {
        "ok": bool(
            duplicate.ok
            and duplicate.topology_changed
            and before_undo["source_indices"] == [1]
            and undo.ok
            and undo_view.submesh_count == 1
            and after_undo == {"vertices_by_submesh": {}, "edges_by_submesh": {}, "faces_by_submesh": {}, "source_indices": []}
        ),
        "duplicate": _command_summary(duplicate),
        "undo": _command_summary(undo),
        "before_undo": before_undo,
        "after_undo": after_undo,
        "submesh_count_after_undo": undo_view.submesh_count,
    }


def _history_context_smoke() -> dict[str, object]:
    service = MeshService()
    view = service.open_edit_session(build_synthetic_mesh(), session_id="history-context-restore", mode="edit")
    original_selection = MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})
    service.apply_command(view.session_id, MeshEditCommand("select", selection=original_selection))
    duplicate = service.apply_command(view.session_id, MeshEditCommand("duplicate"))
    service.apply_command(
        view.session_id,
        MeshEditCommand("select", selection=MeshEditSelection.from_maps(faces_by_submesh={1: (0,)}, source_indices=(1,))),
    )
    undo = service.undo(view.session_id)
    undo_selection = _selection_snapshot(service.session_view(view.session_id).selection)
    redo = service.redo(view.session_id)
    redo_selection = _selection_snapshot(service.session_view(view.session_id).selection)
    service.close_edit_session(view.session_id)
    mode_view = service.open_edit_session(build_synthetic_mesh(), session_id="history-mode-restore", mode="object")
    service.apply_command(
        mode_view.session_id,
        MeshEditCommand("select", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})),
    )
    mode_duplicate = service.apply_command(mode_view.session_id, MeshEditCommand("duplicate", mode="edit"))
    mode_after_duplicate = service.session_view(mode_view.session_id).mode
    mode_undo = service.undo(mode_view.session_id)
    mode_after_undo = service.session_view(mode_view.session_id).mode
    mode_redo = service.redo(mode_view.session_id)
    mode_after_redo = service.session_view(mode_view.session_id).mode
    service.close_edit_session(mode_view.session_id)
    return {
        "ok": bool(
            duplicate.ok
            and duplicate.topology_changed
            and undo.ok
            and undo_selection["faces_by_submesh"] == {"0": [0]}
            and undo_selection["source_indices"] == []
            and redo.ok
            and redo_selection["faces_by_submesh"] == {"1": [0]}
            and redo_selection["source_indices"] == [1]
            and mode_duplicate.ok
            and mode_after_duplicate == "edit"
            and mode_undo.ok
            and mode_after_undo == "object"
            and mode_redo.ok
            and mode_after_redo == "edit"
        ),
        "duplicate": _command_summary(duplicate),
        "undo": _command_summary(undo),
        "redo": _command_summary(redo),
        "after_undo": undo_selection,
        "after_redo": redo_selection,
        "mode_restore": {
            "duplicate": _command_summary(mode_duplicate),
            "undo": _command_summary(mode_undo),
            "redo": _command_summary(mode_redo),
            "after_duplicate": mode_after_duplicate,
            "after_undo": mode_after_undo,
            "after_redo": mode_after_redo,
        },
    }


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
            and face_assign.affected_submesh_indices == (1,)
            and len(submeshes) == 2
            and submeshes[0]["material"] == "harness_material"
            and submeshes[0]["face_count"] == 1
            and submeshes[1]["material"] == "face_material"
            and submeshes[1]["texture"] == "face.dds"
            and submeshes[1]["face_count"] == 1
            and submeshes[1]["overrides"] == {"roughness": 0.4}
            and face_copy.ok
            and face_copy.topology_changed
            and face_copy.affected_submesh_indices == (2,)
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


def _edge_face_topology_smoke() -> dict[str, object]:
    service = MeshService()
    duplicate_view = service.open_edit_session(build_synthetic_mesh(), session_id="edge-face-duplicate", mode="edit")
    duplicate = service.apply_command(
        duplicate_view.session_id,
        MeshEditCommand("duplicate", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
    )
    duplicate_mesh = service.working_mesh(duplicate_view.session_id)
    copied = duplicate_mesh.submeshes[1] if len(duplicate_mesh.submeshes) > 1 else SubMesh()
    service.close_edit_session(duplicate_view.session_id)

    mirror_view = service.open_edit_session(build_synthetic_mesh(), session_id="edge-face-mirror", mode="edit")
    mirror = service.apply_command(
        mirror_view.session_id,
        MeshEditCommand("mirror", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}), params={"axis": "x"}),
    )
    mirror_mesh = service.working_mesh(mirror_view.session_id)
    mirrored = mirror_mesh.submeshes[1] if len(mirror_mesh.submeshes) > 1 else SubMesh()
    service.close_edit_session(mirror_view.session_id)

    delete_view = service.open_edit_session(build_synthetic_mesh(), session_id="edge-face-delete", mode="edit")
    delete = service.apply_command(
        delete_view.session_id,
        MeshEditCommand("delete", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
    )
    delete_submesh = service.working_mesh(delete_view.session_id).submeshes[0]
    service.close_edit_session(delete_view.session_id)

    dissolve_view = service.open_edit_session(build_synthetic_mesh(), session_id="edge-face-dissolve", mode="edit")
    dissolve = service.apply_command(
        dissolve_view.session_id,
        MeshEditCommand("dissolve", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
    )
    dissolve_submesh = service.working_mesh(dissolve_view.session_id).submeshes[0]
    service.close_edit_session(dissolve_view.session_id)

    internal_dissolve_view = service.open_edit_session(build_synthetic_mesh(), session_id="internal-edge-dissolve", mode="edit")
    internal_dissolve = service.apply_command(
        internal_dissolve_view.session_id,
        MeshEditCommand("dissolve", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((1, 2),)})),
    )
    internal_dissolve_submesh = service.working_mesh(internal_dissolve_view.session_id).submeshes[0]
    service.close_edit_session(internal_dissolve_view.session_id)

    subdivide_view = service.open_edit_session(build_synthetic_mesh(), session_id="edge-face-subdivide", mode="edit")
    subdivide = service.apply_command(
        subdivide_view.session_id,
        MeshEditCommand("subdivide", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
    )
    subdivide_submesh = service.working_mesh(subdivide_view.session_id).submeshes[0]
    service.close_edit_session(subdivide_view.session_id)

    loop_cut_mesh = build_synthetic_mesh()
    loop_cut_seed = loop_cut_mesh.submeshes[0]
    loop_cut_seed.vertices = loop_cut_seed.vertices[:3]
    loop_cut_seed.uvs = loop_cut_seed.uvs[:3]
    loop_cut_seed.normals = loop_cut_seed.normals[:3]
    loop_cut_seed.faces = [(0, 1, 2)]
    loop_cut_seed.vertex_count = 3
    loop_cut_seed.face_count = 1
    loop_cut_mesh.total_vertices = 3
    loop_cut_mesh.total_faces = 1
    loop_cut_view = service.open_edit_session(loop_cut_mesh, session_id="two-edge-loop-cut", mode="edit")
    loop_cut = service.apply_command(
        loop_cut_view.session_id,
        MeshEditCommand("loop_cut", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 2))})),
    )
    loop_cut_submesh = service.working_mesh(loop_cut_view.session_id).submeshes[0]
    service.close_edit_session(loop_cut_view.session_id)

    multi_cut_mesh = build_synthetic_mesh()
    multi_cut_seed = multi_cut_mesh.submeshes[0]
    multi_cut_seed.vertices = multi_cut_seed.vertices[:3]
    multi_cut_seed.uvs = multi_cut_seed.uvs[:3]
    multi_cut_seed.normals = multi_cut_seed.normals[:3]
    multi_cut_seed.faces = [(0, 1, 2)]
    multi_cut_seed.vertex_count = 3
    multi_cut_seed.face_count = 1
    multi_cut_mesh.total_vertices = 3
    multi_cut_mesh.total_faces = 1
    multi_cut_view = service.open_edit_session(multi_cut_mesh, session_id="multi-edge-loop-cut", mode="edit")
    multi_cut = service.apply_command(
        multi_cut_view.session_id,
        MeshEditCommand("loop_cut", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}), params={"cuts": 2}),
    )
    multi_cut_submesh = service.working_mesh(multi_cut_view.session_id).submeshes[0]
    service.close_edit_session(multi_cut_view.session_id)

    factor_cut_mesh = build_synthetic_mesh()
    factor_cut_seed = factor_cut_mesh.submeshes[0]
    factor_cut_seed.vertices = factor_cut_seed.vertices[:3]
    factor_cut_seed.uvs = factor_cut_seed.uvs[:3]
    factor_cut_seed.normals = factor_cut_seed.normals[:3]
    factor_cut_seed.faces = [(0, 1, 2)]
    factor_cut_seed.vertex_count = 3
    factor_cut_seed.face_count = 1
    factor_cut_mesh.total_vertices = 3
    factor_cut_mesh.total_faces = 1
    factor_cut_view = service.open_edit_session(factor_cut_mesh, session_id="factor-edge-loop-cut", mode="edit")
    factor_cut = service.apply_command(
        factor_cut_view.session_id,
        MeshEditCommand("loop_cut", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}), params={"factor": 0.25}),
    )
    factor_cut_submesh = service.working_mesh(factor_cut_view.session_id).submeshes[0]
    service.close_edit_session(factor_cut_view.session_id)

    split_view = service.open_edit_session(build_synthetic_mesh(), session_id="edge-face-split", mode="edit")
    split = service.apply_command(
        split_view.session_id,
        MeshEditCommand("split", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
    )
    split_mesh = service.working_mesh(split_view.session_id)
    service.close_edit_session(split_view.session_id)

    separate_view = service.open_edit_session(build_synthetic_mesh(), session_id="edge-face-separate", mode="edit")
    separate = service.apply_command(
        separate_view.session_id,
        MeshEditCommand("separate", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})),
    )
    separate_mesh = service.working_mesh(separate_view.session_id)
    service.close_edit_session(separate_view.session_id)

    fill_view = service.open_edit_session(build_synthetic_mesh(), session_id="edge-face-fill", mode="edit")
    fill = service.apply_command(
        fill_view.session_id,
        MeshEditCommand("fill", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 3), (0, 3))})),
    )
    fill_submesh = service.working_mesh(fill_view.session_id).submeshes[0]
    service.close_edit_session(fill_view.session_id)

    quad_fill_mesh = build_synthetic_mesh()
    quad_fill_mesh.submeshes[0].faces = []
    quad_fill_mesh.submeshes[0].face_count = 0
    quad_fill_mesh.total_faces = 0
    quad_fill_view = service.open_edit_session(quad_fill_mesh, session_id="quad-loop-fill", mode="edit")
    quad_fill = service.apply_command(
        quad_fill_view.session_id,
        MeshEditCommand("fill", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 3), (2, 3), (0, 2))})),
    )
    quad_fill_submesh = service.working_mesh(quad_fill_view.session_id).submeshes[0]
    service.close_edit_session(quad_fill_view.session_id)

    face_fill_view = service.open_edit_session(build_synthetic_mesh(), session_id="face-fill-noop", mode="edit")
    face_fill = service.apply_command(
        face_fill_view.session_id,
        MeshEditCommand("fill", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}, source_indices=(0,))),
    )
    face_fill_submesh = service.working_mesh(face_fill_view.session_id).submeshes[0]
    service.close_edit_session(face_fill_view.session_id)

    existing_fill_view = service.open_edit_session(build_synthetic_mesh(), session_id="existing-fill-noop", mode="edit")
    existing_fill = service.apply_command(
        existing_fill_view.session_id,
        MeshEditCommand("fill", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (1, 2), (0, 2))})),
    )
    existing_fill_submesh = service.working_mesh(existing_fill_view.session_id).submeshes[0]
    service.close_edit_session(existing_fill_view.session_id)

    extrude_view = service.open_edit_session(build_synthetic_mesh(), session_id="region-extrude", mode="edit")
    extrude = service.apply_command(
        extrude_view.session_id,
        MeshEditCommand("extrude", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)}), params={"offset": (0.0, 0.0, 0.2)}),
    )
    extrude_submesh = service.working_mesh(extrude_view.session_id).submeshes[0]
    service.close_edit_session(extrude_view.session_id)

    edge_extrude_mesh = build_synthetic_mesh()
    edge_extrude_mesh.submeshes[0].faces = []
    edge_extrude_mesh.submeshes[0].face_count = 0
    edge_extrude_mesh.total_faces = 0
    edge_extrude_view = service.open_edit_session(edge_extrude_mesh, session_id="loose-edge-extrude", mode="edit")
    edge_extrude = service.apply_command(
        edge_extrude_view.session_id,
        MeshEditCommand("extrude", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)}), params={"offset": (0.0, 0.0, 0.2)}),
    )
    edge_extrude_submesh = service.working_mesh(edge_extrude_view.session_id).submeshes[0]
    service.close_edit_session(edge_extrude_view.session_id)

    non_edge_extrude_view = service.open_edit_session(build_synthetic_mesh(), session_id="non-edge-extrude", mode="edit")
    non_edge_extrude = service.apply_command(
        non_edge_extrude_view.session_id,
        MeshEditCommand("extrude", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 3),)}), params={"offset": (0.0, 0.0, 0.2)}),
    )
    non_edge_extrude_submesh = service.working_mesh(non_edge_extrude_view.session_id).submeshes[0]
    service.close_edit_session(non_edge_extrude_view.session_id)

    inset_view = service.open_edit_session(build_synthetic_mesh(), session_id="region-inset", mode="edit")
    inset = service.apply_command(
        inset_view.session_id,
        MeshEditCommand("inset", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)}), params={"amount": 0.5}),
    )
    inset_submesh = service.working_mesh(inset_view.session_id).submeshes[0]
    service.close_edit_session(inset_view.session_id)

    inset_zero_view = service.open_edit_session(build_synthetic_mesh(), session_id="zero-inset", mode="edit")
    inset_zero = service.apply_command(
        inset_zero_view.session_id,
        MeshEditCommand("inset", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0, 1)}), params={"amount": 0.0}),
    )
    inset_zero_submesh = service.working_mesh(inset_zero_view.session_id).submeshes[0]
    service.close_edit_session(inset_zero_view.session_id)

    merge_mesh = build_synthetic_mesh()
    merge_submesh_seed = merge_mesh.submeshes[0]
    merge_submesh_seed.vertices.append(merge_submesh_seed.vertices[1])
    merge_submesh_seed.uvs.append(merge_submesh_seed.uvs[1])
    merge_submesh_seed.normals.append(merge_submesh_seed.normals[1])
    merge_submesh_seed.faces.append((0, 4, 2))
    merge_submesh_seed.vertex_count = len(merge_submesh_seed.vertices)
    merge_submesh_seed.face_count = len(merge_submesh_seed.faces)
    merge_mesh.total_vertices = len(merge_submesh_seed.vertices)
    merge_mesh.total_faces = len(merge_submesh_seed.faces)
    merge_view = service.open_edit_session(merge_mesh, session_id="duplicate-merge", mode="edit")
    merge = service.apply_command(
        merge_view.session_id,
        MeshEditCommand("merge", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 4)})),
    )
    merge_submesh = service.working_mesh(merge_view.session_id).submeshes[0]
    service.close_edit_session(merge_view.session_id)

    weld_mesh = build_synthetic_mesh()
    weld_submesh_seed = weld_mesh.submeshes[0]
    weld_submesh_seed.vertices.append(weld_submesh_seed.vertices[1])
    weld_submesh_seed.uvs.append(weld_submesh_seed.uvs[1])
    weld_submesh_seed.normals.append(weld_submesh_seed.normals[1])
    weld_submesh_seed.faces.append((0, 4, 2))
    weld_submesh_seed.vertex_count = len(weld_submesh_seed.vertices)
    weld_submesh_seed.face_count = len(weld_submesh_seed.faces)
    weld_mesh.total_vertices = len(weld_submesh_seed.vertices)
    weld_mesh.total_faces = len(weld_submesh_seed.faces)
    weld_view = service.open_edit_session(weld_mesh, session_id="duplicate-weld", mode="edit")
    weld = service.apply_command(
        weld_view.session_id,
        MeshEditCommand("weld", selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (1, 4)}), params={"threshold": 0.001}),
    )
    weld_submesh = service.working_mesh(weld_view.session_id).submeshes[0]
    service.close_edit_session(weld_view.session_id)

    bridge_mesh = build_synthetic_mesh()
    bridge_mesh.submeshes[0].faces = []
    bridge_mesh.submeshes[0].face_count = 0
    bridge_mesh.total_faces = 0
    bridge_view = service.open_edit_session(bridge_mesh, session_id="loose-edge-bridge", mode="edit")
    bridge = service.apply_command(
        bridge_view.session_id,
        MeshEditCommand("bridge", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (2, 3))})),
    )
    bridge_submesh = service.working_mesh(bridge_view.session_id).submeshes[0]
    service.close_edit_session(bridge_view.session_id)

    filled_bridge_view = service.open_edit_session(build_synthetic_mesh(), session_id="filled-edge-bridge", mode="edit")
    filled_bridge = service.apply_command(
        filled_bridge_view.session_id,
        MeshEditCommand("bridge", selection=MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1), (2, 3))})),
    )
    filled_bridge_submesh = service.working_mesh(filled_bridge_view.session_id).submeshes[0]
    service.close_edit_session(filled_bridge_view.session_id)

    empty_recalc_view = service.open_edit_session(build_synthetic_mesh(), session_id="empty-normal-recalc", mode="edit")
    empty_recalc_submesh = service.working_mesh(empty_recalc_view.session_id).submeshes[0]
    empty_recalc_submesh.normals = [(0.0, 0.0, -1.0)] * len(empty_recalc_submesh.vertices)
    empty_recalc = service.apply_command(empty_recalc_view.session_id, MeshEditCommand("recalculate_normals"))
    empty_recalc_normals = [list(normal) for normal in empty_recalc_submesh.normals]
    service.close_edit_session(empty_recalc_view.session_id)

    source_recalc_view = service.open_edit_session(build_synthetic_mesh(), session_id="source-normal-recalc", mode="edit")
    source_recalc_submesh = service.working_mesh(source_recalc_view.session_id).submeshes[0]
    source_recalc_submesh.normals = [(0.0, 0.0, -1.0)] * len(source_recalc_submesh.vertices)
    source_recalc = service.apply_command(
        source_recalc_view.session_id,
        MeshEditCommand("recalculate_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
    )
    source_recalc_normals = [list(normal) for normal in source_recalc_submesh.normals]
    service.close_edit_session(source_recalc_view.session_id)

    face_flip_view = service.open_edit_session(build_synthetic_mesh(), session_id="face-normal-flip", mode="edit")
    face_flip = service.apply_command(
        face_flip_view.session_id,
        MeshEditCommand("flip_normals", selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})),
    )
    face_flip_submesh = service.working_mesh(face_flip_view.session_id).submeshes[0]
    service.close_edit_session(face_flip_view.session_id)

    empty_flip_view = service.open_edit_session(build_synthetic_mesh(), session_id="empty-normal-flip", mode="edit")
    empty_flip = service.apply_command(empty_flip_view.session_id, MeshEditCommand("flip_normals"))
    empty_flip_submesh = service.working_mesh(empty_flip_view.session_id).submeshes[0]
    service.close_edit_session(empty_flip_view.session_id)

    source_flip_view = service.open_edit_session(build_synthetic_mesh(), session_id="source-normal-flip", mode="edit")
    source_flip = service.apply_command(
        source_flip_view.session_id,
        MeshEditCommand("flip_normals", selection=MeshEditSelection.from_maps(source_indices=(0,))),
    )
    source_flip_submesh = service.working_mesh(source_flip_view.session_id).submeshes[0]
    service.close_edit_session(source_flip_view.session_id)

    return {
        "ok": bool(
            duplicate.ok
            and duplicate.topology_changed
            and duplicate.affected_submesh_indices == (1,)
            and len(duplicate_mesh.submeshes) == 2
            and copied.vertex_count == 3
            and copied.face_count == 1
            and copied.faces == [(0, 1, 2)]
            and mirror.ok
            and mirror.topology_changed
            and len(mirror_mesh.submeshes) == 2
            and mirrored.vertex_count == 3
            and mirrored.face_count == 1
            and mirrored.faces == [(0, 2, 1)]
            and delete.ok
            and delete.topology_changed
            and delete_submesh.vertex_count == 3
            and delete_submesh.face_count == 1
            and delete_submesh.faces == [(0, 2, 1)]
            and dissolve.ok
            and dissolve.topology_changed
            and dissolve_submesh.vertex_count == 4
            and dissolve_submesh.face_count == 1
            and dissolve_submesh.faces == [(1, 3, 2)]
            and internal_dissolve.ok
            and internal_dissolve.topology_changed
            and internal_dissolve_submesh.vertex_count == 4
            and internal_dissolve_submesh.face_count == 2
            and internal_dissolve_submesh.faces == [(0, 1, 3), (0, 3, 2)]
            and subdivide.ok
            and subdivide.topology_changed
            and subdivide_submesh.vertex_count == 7
            and subdivide_submesh.face_count == 5
            and loop_cut.ok
            and loop_cut.topology_changed
            and loop_cut_submesh.vertex_count == 5
            and loop_cut_submesh.face_count == 3
            and loop_cut_submesh.faces == [(3, 1, 4), (0, 3, 4), (0, 4, 2)]
            and multi_cut.ok
            and multi_cut.topology_changed
            and multi_cut_submesh.vertex_count == 5
            and multi_cut_submesh.face_count == 3
            and multi_cut_submesh.faces == [(0, 3, 2), (3, 4, 2), (4, 1, 2)]
            and factor_cut.ok
            and factor_cut.topology_changed
            and factor_cut_submesh.vertex_count == 4
            and factor_cut_submesh.face_count == 2
            and factor_cut_submesh.vertices[3] == (-0.375, -0.75, 0.0)
            and factor_cut_submesh.uvs[3] == (0.25, 1.0)
            and factor_cut_submesh.faces == [(0, 3, 2), (3, 1, 2)]
            and split.ok
            and split.topology_changed
            and len(split_mesh.submeshes) == 1
            and split_mesh.submeshes[0].vertex_count == 6
            and split_mesh.submeshes[0].face_count == 2
            and split_mesh.submeshes[0].faces == [(0, 4, 5), (1, 3, 2)]
            and separate.ok
            and separate.topology_changed
            and len(separate_mesh.submeshes) == 2
            and separate_mesh.submeshes[0].face_count == 1
            and separate_mesh.submeshes[1].face_count == 1
            and fill.ok
            and fill.topology_changed
            and fill_submesh.face_count == 3
            and fill_submesh.faces[-1] == (0, 1, 3)
            and quad_fill.ok
            and quad_fill.topology_changed
            and quad_fill_submesh.face_count == 2
            and quad_fill_submesh.faces == [(0, 1, 3), (0, 3, 2)]
            and face_fill.ok
            and not face_fill.topology_changed
            and face_fill_submesh.face_count == 2
            and existing_fill.ok
            and not existing_fill.topology_changed
            and existing_fill_submesh.face_count == 2
            and extrude.ok
            and extrude.topology_changed
            and extrude_submesh.vertex_count == 8
            and extrude_submesh.face_count == 12
            and edge_extrude.ok
            and edge_extrude.topology_changed
            and edge_extrude_submesh.vertex_count == 6
            and edge_extrude_submesh.face_count == 2
            and edge_extrude_submesh.faces == [(0, 1, 5), (0, 5, 4)]
            and non_edge_extrude.ok
            and not non_edge_extrude.topology_changed
            and non_edge_extrude.affected_submesh_indices == ()
            and non_edge_extrude_submesh.vertex_count == 4
            and non_edge_extrude_submesh.face_count == 2
            and inset.ok
            and inset.topology_changed
            and inset_submesh.vertex_count == 8
            and inset_submesh.face_count == 10
            and inset_zero.ok
            and not inset_zero.topology_changed
            and inset_zero_submesh.vertex_count == 4
            and inset_zero_submesh.face_count == 2
            and merge.ok
            and merge.topology_changed
            and merge_submesh.vertex_count == 4
            and merge_submesh.face_count == 2
            and weld.ok
            and weld.topology_changed
            and weld_submesh.vertex_count == 4
            and weld_submesh.face_count == 2
            and bridge.ok
            and bridge.topology_changed
            and bridge_submesh.face_count == 2
            and bridge_submesh.faces == [(0, 1, 3), (0, 3, 2)]
            and filled_bridge.ok
            and not filled_bridge.topology_changed
            and filled_bridge_submesh.face_count == 2
            and empty_recalc.ok
            and empty_recalc.affected_submesh_indices == ()
            and empty_recalc_normals == [[0.0, 0.0, -1.0]] * 4
            and source_recalc.ok
            and source_recalc.affected_submesh_indices == (0,)
            and source_recalc_normals == [[0.0, 0.0, 1.0]] * 4
            and face_flip.ok
            and not face_flip.topology_changed
            and face_flip.affected_submesh_indices == (0,)
            and face_flip_submesh.faces == [(0, 2, 1), (1, 3, 2)]
            and empty_flip.ok
            and not empty_flip.topology_changed
            and empty_flip.affected_submesh_indices == ()
            and empty_flip_submesh.faces == [(0, 1, 2), (1, 3, 2)]
            and source_flip.ok
            and not source_flip.topology_changed
            and source_flip.affected_submesh_indices == (0,)
            and source_flip_submesh.faces == [(0, 2, 1), (1, 2, 3)]
        ),
        "command": _command_summary(duplicate),
        "submesh_count": len(duplicate_mesh.submeshes),
        "copied_vertex_count": int(copied.vertex_count or len(copied.vertices)),
        "copied_face_count": int(copied.face_count or len(copied.faces)),
        "copied_faces": [list(face) for face in copied.faces],
        "mirror": {
            "command": _command_summary(mirror),
            "submesh_count": len(mirror_mesh.submeshes),
            "vertex_count": int(mirrored.vertex_count or len(mirrored.vertices)),
            "face_count": int(mirrored.face_count or len(mirrored.faces)),
            "vertices": [list(vertex) for vertex in mirrored.vertices],
            "faces": [list(face) for face in mirrored.faces],
        },
        "delete": {
            "command": _command_summary(delete),
            "vertex_count": int(delete_submesh.vertex_count or len(delete_submesh.vertices)),
            "face_count": int(delete_submesh.face_count or len(delete_submesh.faces)),
            "faces": [list(face) for face in delete_submesh.faces],
        },
        "dissolve": {
            "command": _command_summary(dissolve),
            "vertex_count": int(dissolve_submesh.vertex_count or len(dissolve_submesh.vertices)),
            "face_count": int(dissolve_submesh.face_count or len(dissolve_submesh.faces)),
            "faces": [list(face) for face in dissolve_submesh.faces],
        },
        "internal_dissolve": {
            "command": _command_summary(internal_dissolve),
            "vertex_count": int(internal_dissolve_submesh.vertex_count or len(internal_dissolve_submesh.vertices)),
            "face_count": int(internal_dissolve_submesh.face_count or len(internal_dissolve_submesh.faces)),
            "faces": [list(face) for face in internal_dissolve_submesh.faces],
        },
        "subdivide": {
            "command": _command_summary(subdivide),
            "vertex_count": int(subdivide_submesh.vertex_count or len(subdivide_submesh.vertices)),
            "face_count": int(subdivide_submesh.face_count or len(subdivide_submesh.faces)),
            "faces": [list(face) for face in subdivide_submesh.faces],
        },
        "loop_cut_two_edges": {
            "command": _command_summary(loop_cut),
            "vertex_count": int(loop_cut_submesh.vertex_count or len(loop_cut_submesh.vertices)),
            "face_count": int(loop_cut_submesh.face_count or len(loop_cut_submesh.faces)),
            "faces": [list(face) for face in loop_cut_submesh.faces],
            "changed_vertices": {str(submesh): list(vertices) for submesh, vertices in loop_cut.changed_vertices_by_submesh},
        },
        "loop_cut_multi": {
            "command": _command_summary(multi_cut),
            "vertex_count": int(multi_cut_submesh.vertex_count or len(multi_cut_submesh.vertices)),
            "face_count": int(multi_cut_submesh.face_count or len(multi_cut_submesh.faces)),
            "vertices": [list(vertex) for vertex in multi_cut_submesh.vertices],
            "uvs": [list(uv) for uv in multi_cut_submesh.uvs],
            "faces": [list(face) for face in multi_cut_submesh.faces],
            "changed_vertices": {str(submesh): list(vertices) for submesh, vertices in multi_cut.changed_vertices_by_submesh},
        },
        "loop_cut_factor": {
            "command": _command_summary(factor_cut),
            "vertex_count": int(factor_cut_submesh.vertex_count or len(factor_cut_submesh.vertices)),
            "face_count": int(factor_cut_submesh.face_count or len(factor_cut_submesh.faces)),
            "vertices": [list(vertex) for vertex in factor_cut_submesh.vertices],
            "uvs": [list(uv) for uv in factor_cut_submesh.uvs],
            "faces": [list(face) for face in factor_cut_submesh.faces],
            "changed_vertices": {str(submesh): list(vertices) for submesh, vertices in factor_cut.changed_vertices_by_submesh},
        },
        "split": {
            "command": _command_summary(split),
            "submesh_count": len(split_mesh.submeshes),
            "vertex_count": int(split_mesh.submeshes[0].vertex_count or len(split_mesh.submeshes[0].vertices)),
            "face_count": int(split_mesh.submeshes[0].face_count or len(split_mesh.submeshes[0].faces)),
            "faces": [list(face) for face in split_mesh.submeshes[0].faces],
            "changed_vertices": {str(submesh): list(vertices) for submesh, vertices in split.changed_vertices_by_submesh},
        },
        "separate": {
            "command": _command_summary(separate),
            "submesh_count": len(separate_mesh.submeshes),
            "source_face_count": int(separate_mesh.submeshes[0].face_count or len(separate_mesh.submeshes[0].faces)),
            "moved_face_count": int(separate_mesh.submeshes[1].face_count or len(separate_mesh.submeshes[1].faces)) if len(separate_mesh.submeshes) > 1 else 0,
        },
        "fill": {
            "command": _command_summary(fill),
            "face_count": int(fill_submesh.face_count or len(fill_submesh.faces)),
            "faces": [list(face) for face in fill_submesh.faces],
        },
        "quad_fill": {
            "command": _command_summary(quad_fill),
            "face_count": int(quad_fill_submesh.face_count or len(quad_fill_submesh.faces)),
            "faces": [list(face) for face in quad_fill_submesh.faces],
        },
        "face_fill": {
            "command": _command_summary(face_fill),
            "face_count": int(face_fill_submesh.face_count or len(face_fill_submesh.faces)),
            "faces": [list(face) for face in face_fill_submesh.faces],
        },
        "existing_fill": {
            "command": _command_summary(existing_fill),
            "face_count": int(existing_fill_submesh.face_count or len(existing_fill_submesh.faces)),
            "faces": [list(face) for face in existing_fill_submesh.faces],
        },
        "extrude": {
            "command": _command_summary(extrude),
            "vertex_count": int(extrude_submesh.vertex_count or len(extrude_submesh.vertices)),
            "face_count": int(extrude_submesh.face_count or len(extrude_submesh.faces)),
            "changed_vertices": {str(submesh): list(vertices) for submesh, vertices in extrude.changed_vertices_by_submesh},
        },
        "edge_extrude": {
            "command": _command_summary(edge_extrude),
            "vertex_count": int(edge_extrude_submesh.vertex_count or len(edge_extrude_submesh.vertices)),
            "face_count": int(edge_extrude_submesh.face_count or len(edge_extrude_submesh.faces)),
            "vertices": [list(vertex) for vertex in edge_extrude_submesh.vertices],
            "uvs": [list(uv) for uv in edge_extrude_submesh.uvs],
            "faces": [list(face) for face in edge_extrude_submesh.faces],
            "changed_vertices": {str(submesh): list(vertices) for submesh, vertices in edge_extrude.changed_vertices_by_submesh},
        },
        "non_edge_extrude": {
            "command": _command_summary(non_edge_extrude),
            "vertex_count": int(non_edge_extrude_submesh.vertex_count or len(non_edge_extrude_submesh.vertices)),
            "face_count": int(non_edge_extrude_submesh.face_count or len(non_edge_extrude_submesh.faces)),
            "faces": [list(face) for face in non_edge_extrude_submesh.faces],
        },
        "inset": {
            "command": _command_summary(inset),
            "vertex_count": int(inset_submesh.vertex_count or len(inset_submesh.vertices)),
            "face_count": int(inset_submesh.face_count or len(inset_submesh.faces)),
            "changed_vertices": {str(submesh): list(vertices) for submesh, vertices in inset.changed_vertices_by_submesh},
        },
        "inset_zero": {
            "command": _command_summary(inset_zero),
            "vertex_count": int(inset_zero_submesh.vertex_count or len(inset_zero_submesh.vertices)),
            "face_count": int(inset_zero_submesh.face_count or len(inset_zero_submesh.faces)),
            "faces": [list(face) for face in inset_zero_submesh.faces],
        },
        "merge": {
            "command": _command_summary(merge),
            "vertex_count": int(merge_submesh.vertex_count or len(merge_submesh.vertices)),
            "face_count": int(merge_submesh.face_count or len(merge_submesh.faces)),
            "faces": [list(face) for face in merge_submesh.faces],
        },
        "weld": {
            "command": _command_summary(weld),
            "vertex_count": int(weld_submesh.vertex_count or len(weld_submesh.vertices)),
            "face_count": int(weld_submesh.face_count or len(weld_submesh.faces)),
            "faces": [list(face) for face in weld_submesh.faces],
        },
        "bridge": {
            "command": _command_summary(bridge),
            "face_count": int(bridge_submesh.face_count or len(bridge_submesh.faces)),
            "faces": [list(face) for face in bridge_submesh.faces],
        },
        "filled_bridge": {
            "command": _command_summary(filled_bridge),
            "face_count": int(filled_bridge_submesh.face_count or len(filled_bridge_submesh.faces)),
            "faces": [list(face) for face in filled_bridge_submesh.faces],
        },
        "empty_recalculate_normals": {
            "command": _command_summary(empty_recalc),
            "normals": empty_recalc_normals,
        },
        "source_recalculate_normals": {
            "command": _command_summary(source_recalc),
            "normals": source_recalc_normals,
        },
        "face_flip_normals": {
            "command": _command_summary(face_flip),
            "face_count": int(face_flip_submesh.face_count or len(face_flip_submesh.faces)),
            "faces": [list(face) for face in face_flip_submesh.faces],
        },
        "empty_flip_normals": {
            "command": _command_summary(empty_flip),
            "face_count": int(empty_flip_submesh.face_count or len(empty_flip_submesh.faces)),
            "faces": [list(face) for face in empty_flip_submesh.faces],
        },
        "source_flip_normals": {
            "command": _command_summary(source_flip),
            "face_count": int(source_flip_submesh.face_count or len(source_flip_submesh.faces)),
            "faces": [list(face) for face in source_flip_submesh.faces],
        },
    }


def _selection_snapshot(selection: MeshEditSelection) -> dict[str, object]:
    return {
        "vertices_by_submesh": {str(submesh): list(indices) for submesh, indices in selection.vertices_by_submesh},
        "edges_by_submesh": {str(submesh): [list(edge) for edge in edges] for submesh, edges in selection.edges_by_submesh},
        "faces_by_submesh": {str(submesh): list(indices) for submesh, indices in selection.faces_by_submesh},
        "source_indices": list(selection.source_indices),
    }


def run_native_smoke(mesh: ParsedMesh, output_dir: Path, *, timeout_seconds: float = 15.0) -> dict[str, object]:
    if os.name != "nt":
        return {"ok": False, "error": "native D3D11 harness requires Windows"}
    host_binary = find_native_d3d11_host()
    if host_binary is None:
        return {"ok": False, "error": "native D3D11 preview host not found"}

    package_dir = output_dir / "preview_package"
    status_file = output_dir / "native_status.json"
    capture_path = output_dir / "preview.png"
    package_dir = mesh_editor_write_native_preview_package(
        mesh,
        output_root=package_dir,
        use_textures=False,
        backend="d3d11",
    )
    process = subprocess.Popen(
        [
            str(host_binary),
            "--backend",
            "d3d11",
            "--preview-package",
            str(package_dir),
            "--status-file",
            str(status_file),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        loaded = _wait_for_status(status_file, {"loaded", "resources_loaded"}, timeout_seconds)
        loaded_ok = loaded.get("event") in {"loaded", "resources_loaded"}
        hwnd = _wait_for_host_window(process.pid, timeout_seconds)
        commands = [
            {"command": "set_mesh_edit_state", "enabled": True, "source_submesh_indices": [0], "target_mode": "brush", "tool": "grab"},
            {"command": "set_mesh_edit_selection", "groups": mesh_edit_selection_groups(mesh, MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2)}))},
            {"command": "update_mesh_edit_vertices", "groups": mesh_edit_vertex_update_groups(mesh, {0: (0, 1, 2)})},
            {"command": "set_material_overrides", **(mesh_edit_material_override_groups(mesh, (0,))[0] if mesh_edit_material_override_groups(mesh, (0,)) else {})},
            {"command": "replace_mesh_edit_triangles", "groups": mesh_edit_triangle_groups(mesh), "replace_all": True},
        ]
        sent = [_send_json_command(hwnd, command) for command in commands]
        status_file.unlink(missing_ok=True)
        face_selection_sent = _send_json_command(
            hwnd,
            {"command": "set_mesh_edit_selection", "groups": [{"source_submesh_index": 0, "source_face_indices": [0]}]},
        )
        face_selection_status = _wait_for_status(status_file, {"mesh_edit_selection_changed"}, timeout_seconds)
        status_file.unlink(missing_ok=True)
        face_region_sent = _send_json_command(
            hwnd,
            {
                "command": "select_mesh_edit_region",
                "target_mode": "face",
                "selection_mode": "rectangle",
                "selection_depth_mode": "xray",
                "start_x": 120,
                "start_y": 90,
                "end_x": 860,
                "end_y": 630,
            },
        )
        face_region_status = _wait_for_status(status_file, {"mesh_edit_selection_changed"}, timeout_seconds)
        status_file.unlink(missing_ok=True)
        edge_selection_sent = _send_json_command(
            hwnd,
            {"command": "set_mesh_edit_selection", "groups": [{"source_submesh_index": 0, "source_edges": [[0, 1], [2, 3]]}]},
        )
        edge_selection_status = _wait_for_status(status_file, {"mesh_edit_selection_changed"}, timeout_seconds)
        status_file.unlink(missing_ok=True)
        empty_selection_sent = _send_json_command(
            hwnd,
            {"command": "set_mesh_edit_selection", "groups": []},
        )
        empty_selection_status = _wait_for_status(status_file, {"mesh_edit_selection_changed"}, timeout_seconds)
        status_file.unlink(missing_ok=True)
        edge_brush_state_sent = _send_json_command(
            hwnd,
            {
                "command": "set_mesh_edit_state",
                "enabled": True,
                "source_submesh_indices": [0],
                "target_mode": "edge",
                "tool": "vertex",
                "selection_mode": "brush",
                "selection_depth_mode": "xray",
                "radius_pixels": 96,
            },
        )
        status_file.unlink(missing_ok=True)
        edge_brush_sent = _send_json_command(
            hwnd,
            {"command": "select_mesh_edit_brush", "x": 490, "y": 360},
        )
        edge_brush_status = _wait_for_status(status_file, {"mesh_edit_selection_changed"}, timeout_seconds)
        status_file.unlink(missing_ok=True)
        created_part_sent = _send_json_command(
            hwnd,
            {
                "command": "replace_mesh_edit_triangles",
                "groups": mesh_edit_triangle_groups(_build_two_part_synthetic_mesh(), (1,)),
            },
        )
        created_part_status = _wait_for_status(status_file, {"mesh_edit_triangles_replaced"}, timeout_seconds)
        status_file.unlink(missing_ok=True)
        pruned_part_sent = _send_json_command(
            hwnd,
            {
                "command": "replace_mesh_edit_triangles",
                "groups": mesh_edit_triangle_groups(mesh),
                "replace_all": True,
            },
        )
        pruned_part_status = _wait_for_status(status_file, {"mesh_edit_triangles_replaced"}, timeout_seconds)
        capture_sent = _send_json_command(hwnd, {"command": "capture_frame", "path": str(capture_path)})
        sent.extend((
            face_selection_sent,
            face_region_sent,
            edge_selection_sent,
            empty_selection_sent,
            edge_brush_state_sent,
            edge_brush_sent,
            created_part_sent,
            pruned_part_sent,
            capture_sent,
        ))
        captured = _wait_for_file(capture_path, timeout_seconds)
        capture_summary = _png_capture_summary(capture_path) if captured else {"ok": False, "error": "capture missing"}
        face_payload = dict(face_selection_status.get("payload", {}) or {})
        face_selection_ok = (
            int(face_payload.get("selected_vertex_count", 0) or 0) >= 3
            and int(face_payload.get("selected_face_count", 0) or 0) >= 1
        )
        face_region_payload = dict(face_region_status.get("payload", {}) or {})
        face_region_ok = (
            int(face_region_payload.get("selected_vertex_count", 0) or 0) >= 3
            and int(face_region_payload.get("selected_face_count", 0) or 0) >= 1
            and any(group.get("source_face_indices") for group in tuple(face_region_payload.get("groups") or ()) if isinstance(group, dict))
        )
        edge_payload = dict(edge_selection_status.get("payload", {}) or {})
        edge_groups = tuple(edge_payload.get("groups") or ())
        edge_selection_ok = (
            int(edge_payload.get("selected_vertex_count", 0) or 0) >= 4
            and int(edge_payload.get("selected_edge_count", 0) or 0) >= 2
            and any(tuple(group.get("source_edges") or ()) == ([0, 1], [2, 3]) for group in edge_groups if isinstance(group, dict))
        )
        edge_brush_payload = dict(edge_brush_status.get("payload", {}) or {})
        edge_brush_edges = [
            tuple(edge)
            for group in tuple(edge_brush_payload.get("groups") or ())
            if isinstance(group, dict)
            for edge in tuple(group.get("source_edges") or ())
        ]
        edge_brush_ok = (
            int(edge_brush_payload.get("selected_vertex_count", 0) or 0) >= 2
            and int(edge_brush_payload.get("selected_edge_count", 0) or 0) >= 1
            and (1, 2) in edge_brush_edges
            and all(0 <= int(index) < len(mesh.submeshes[0].vertices) for edge in edge_brush_edges for index in edge)
        )
        created_part_ok = int(created_part_status.get("replaced_batches", 0) or 0) >= 1
        pruned_part_ok = int(pruned_part_status.get("removed_batches", 0) or 0) >= 1
        empty_selection_payload = dict(empty_selection_status.get("payload", {}) or {})
        empty_selection_ok = (
            int(empty_selection_payload.get("selected_vertex_count", -1) or 0) == 0
            and int(empty_selection_payload.get("selected_edge_count", -1) or 0) == 0
            and int(empty_selection_payload.get("selected_face_count", -1) or 0) == 0
            and not tuple(empty_selection_payload.get("groups") or ())
        )
        capture_ok = bool(capture_summary.get("ok"))
        return {
            "ok": bool(
                loaded_ok
                and hwnd
                and all(sent)
                and capture_ok
                and face_selection_ok
                and face_region_ok
                and edge_selection_ok
                and empty_selection_ok
                and edge_brush_ok
                and created_part_ok
                and pruned_part_ok
            ),
            "host": str(host_binary),
            "package_dir": str(package_dir),
            "status_file": str(status_file),
            "preview_png": str(capture_path),
            "commands_sent": sent,
            "loaded_status": loaded,
            "face_selection_status": face_selection_status,
            "face_region_status": face_region_status,
            "edge_selection_status": edge_selection_status,
            "empty_selection_status": empty_selection_status,
            "edge_brush_status": edge_brush_status,
            "created_part_status": created_part_status,
            "pruned_part_status": pruned_part_status,
            "captured": captured,
            "capture_summary": capture_summary,
        }
    finally:
        _close_process(process)


def run_scenario(scenario: str, output_dir: Path, *, game_root: Path | str | None = None) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if scenario == "real-archive-rigging-smoke":
        real_archive_result = run_real_archive_rigging_smoke(Path(game_root) if game_root is not None else _DEFAULT_GAME_ROOT)
        result = {
            "scenario": scenario,
            "ok": bool(real_archive_result.get("ok")),
            "real_archive": real_archive_result,
        }
    elif scenario == "real-archive-animation-binding-smoke":
        animation_result = run_real_archive_animation_binding_smoke(
            Path(game_root) if game_root is not None else _DEFAULT_GAME_ROOT,
        )
        result = {
            "scenario": scenario,
            "ok": bool(animation_result.get("ok")),
            "real_archive_animation": animation_result,
        }
    elif scenario == "real-archive-sequence-binding-smoke":
        sequence_result = run_real_archive_sequence_binding_smoke(
            Path(game_root) if game_root is not None else _DEFAULT_GAME_ROOT,
        )
        result = {
            "scenario": scenario,
            "ok": bool(sequence_result.get("ok")),
            "real_archive_sequence": sequence_result,
        }
    elif scenario == "real-archive-app-workflow-smoke":
        app_result = run_real_archive_app_workflow_smoke(
            Path(game_root) if game_root is not None else _DEFAULT_GAME_ROOT,
            output_dir,
        )
        result = {
            "scenario": scenario,
            "ok": bool(app_result.get("ok")),
            "real_archive_app": app_result,
        }
    else:
        mesh, service_result = run_service_smoke()
        native_result = (
            run_native_smoke(mesh, output_dir)
            if scenario == "full-suite-smoke"
            else {"ok": True, "skipped": "service-only scenario"}
        )
        result = {
            "scenario": scenario,
            "ok": bool(service_result.get("ok") and native_result.get("ok")),
            "service": service_result,
            "native": native_result,
        }
    evidence_report_path = output_dir / "evidence_report.json"
    evidence_report_path.write_text(
        json.dumps(_mesh_editor_evidence_report(scenario, result), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    result["evidence_report_path"] = str(evidence_report_path)
    (output_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def _mesh_editor_evidence_report(scenario: str, result: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema": "cdmw_mesh_editor_evidence_report_v1",
        "scenario": scenario,
        "ok": bool(result.get("ok")),
        "read_only": _result_contains_read_only(result),
        "confidence_labels": list(_ADVANCED_AUTHORING_CONFIDENCE_LABELS),
        "state_labels": list(_ADVANCED_AUTHORING_STATE_LABELS),
        "feature_status_rows": _mesh_editor_feature_status_rows(result),
        "corpus_manifest": _result_corpus_manifest(result),
    }


def _mesh_editor_feature_status_rows(result: Mapping[str, object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    service = result.get("service") if isinstance(result.get("service"), Mapping) else None
    if service is not None:
        rows.append(
            _feature_status_row(
                "Mesh edit session",
                "exportable" if bool(service.get("ok")) else "blocked",
                "proven" if bool(service.get("ok")) else "blocked",
                "Synthetic PAC/PAM/PAMLOD edit commands and package export validator path covered.",
            )
        )
    real_archive = result.get("real_archive") if isinstance(result.get("real_archive"), Mapping) else None
    if real_archive is not None:
        rows.append(
            _feature_status_row(
                "Rig pose preview",
                "preview-only" if bool(real_archive.get("ok")) else "blocked",
                "proven" if bool(real_archive.get("ok")) else "unknown",
                "Read-only real archive PAB skinning smoke.",
            )
        )
    animation = result.get("real_archive_animation") if isinstance(result.get("real_archive_animation"), Mapping) else None
    if animation is not None:
        rows.append(
            _feature_status_row(
                "PAA playback",
                "preview-only" if bool(animation.get("safe_playback_ready")) else "blocked",
                "proven" if bool(animation.get("safe_playback_ready")) else "unknown",
                "Exact PAB bone-hash-owned tracks only.",
            )
        )
    sequence = result.get("real_archive_sequence") if isinstance(result.get("real_archive_sequence"), Mapping) else None
    if sequence is not None:
        paa_binding = sequence.get("paa_binding") if isinstance(sequence.get("paa_binding"), Mapping) else {}
        rows.append(
            _feature_status_row(
                "PASEQ/PASEQC playback",
                "preview-only" if bool(paa_binding.get("ready")) else "blocked",
                "proven" if bool(paa_binding.get("ready")) else "unknown",
                str(sequence.get("timing_status") or "timing evidence unavailable"),
            )
        )
        rows.append(
            _feature_status_row(
                "PAPR constraints",
                "blocked",
                "unknown",
                "Read-only PAR metadata; solver fields not proven.",
            )
        )
    rows.append(
        _feature_status_row(
            "Direct archive mutation",
            "blocked",
            "blocked",
            "Harness is read-only; ArchiveMutationService dry-run/backup/readback gates still required.",
        )
    )
    return rows


def _feature_status_row(feature: str, state: str, confidence: str, detail: str) -> dict[str, str]:
    return {
        "feature": feature,
        "state": state if state in _ADVANCED_AUTHORING_STATE_LABELS else "blocked",
        "confidence": confidence if confidence in _ADVANCED_AUTHORING_CONFIDENCE_LABELS else "unknown",
        "detail": detail,
    }


def _result_contains_read_only(value: object) -> bool:
    if isinstance(value, Mapping):
        if bool(value.get("read_only")):
            return True
        return any(_result_contains_read_only(child) for child in value.values())
    if isinstance(value, (list, tuple)):
        return any(_result_contains_read_only(child) for child in value)
    return False


def _result_corpus_manifest(result: Mapping[str, object]) -> dict[str, object]:
    for key in ("real_archive_sequence", "real_archive_animation", "real_archive"):
        nested = result.get(key)
        if isinstance(nested, Mapping) and isinstance(nested.get("corpus_manifest"), Mapping):
            return dict(nested["corpus_manifest"])  # type: ignore[index]
    return _mesh_editor_advanced_authoring_corpus_manifest(())


def _mesh_editor_advanced_authoring_corpus_manifest(
    entries: Sequence[ArchiveEntry],
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]] | None = None,
) -> dict[str, object]:
    entries_by_path = entries_by_path or _archive_entry_indexes(entries)[0]
    formats: dict[str, dict[str, object]] = {
        extension: {"entry_count": 0, "packages": [], "examples": []}
        for extension in _ADVANCED_AUTHORING_CORPUS_EXTENSIONS
    }
    packages_by_extension: dict[str, set[str]] = {extension: set() for extension in _ADVANCED_AUTHORING_CORPUS_EXTENSIONS}
    examples_by_extension: dict[str, list[str]] = {extension: [] for extension in _ADVANCED_AUTHORING_CORPUS_EXTENSIONS}
    for entry in entries:
        extension = str(entry.extension or "").lower()
        if extension not in formats:
            continue
        formats[extension]["entry_count"] = int(formats[extension]["entry_count"]) + 1
        packages_by_extension[extension].add(entry.pamt_path.parent.name)
        if len(examples_by_extension[extension]) < 4:
            examples_by_extension[extension].append(entry.path)
    for extension, row in formats.items():
        row["packages"] = sorted(packages_by_extension[extension])
        row["examples"] = tuple(examples_by_extension[extension])
    return {
        "schema": "cdmw_mesh_editor_advanced_authoring_corpus_v1",
        "formats": formats,
        "sample_families": tuple(_mesh_editor_sample_family_rows(entries_by_path)),
    }


def _mesh_editor_sample_family_rows(
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for name, path, linked_descriptor, linked_skeleton, linked_mesh, confidence in (
        (
            "ptm-skinned-mesh-rig",
            _REAL_ARCHIVE_RIGGING_SAMPLES[0],
            _REAL_ARCHIVE_SEQUENCE_PTM_DESCRIPTOR,
            _REAL_ARCHIVE_SEQUENCE_PTM_PAB,
            _REAL_ARCHIVE_RIGGING_SAMPLES[0],
            "proven",
        ),
        (
            "ptm-sequence-playback",
            _REAL_ARCHIVE_SEQUENCE_SAMPLE,
            "",
            _REAL_ARCHIVE_SEQUENCE_PTM_PAB,
            _REAL_ARCHIVE_RIGGING_SAMPLES[0],
            "inferred",
        ),
        (
            "ptm-paa-bound-clip",
            _REAL_ARCHIVE_SEQUENCE_PTM_PAA,
            "",
            _REAL_ARCHIVE_SEQUENCE_PTM_PAB,
            _REAL_ARCHIVE_RIGGING_SAMPLES[0],
            "proven",
        ),
        (
            "ptm-papr-constraint-metadata",
            _REAL_ARCHIVE_SEQUENCE_PTM_PAPR,
            _REAL_ARCHIVE_SEQUENCE_PTM_DESCRIPTOR,
            _REAL_ARCHIVE_SEQUENCE_PTM_PAB,
            _REAL_ARCHIVE_RIGGING_SAMPLES[0],
            "unknown",
        ),
    ):
        entry = _entry_by_archive_path(entries_by_path, path)
        if entry is None:
            continue
        rows.append(
            {
                "family": name,
                "path": entry.path,
                "format": entry.extension,
                "archive_package": entry.pamt_path.parent.name,
                "linked_descriptor": linked_descriptor,
                "linked_skeleton": linked_skeleton,
                "linked_mesh": linked_mesh,
                "confidence": confidence,
            }
        )
    return rows


def run_real_archive_app_workflow_smoke(game_root: Path, output_dir: Path) -> dict[str, object]:
    pamt_path = game_root / "0009" / "0.pamt"
    if not pamt_path.is_file():
        return {
            "ok": False,
            "read_only": True,
            "skipped": f"missing PAMT: {pamt_path}",
            "game_root": str(game_root),
            "pamt_path": str(pamt_path),
        }

    entries = parse_archive_pamt(pamt_path)
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    result = _run_real_archive_app_workflow_sample(
        _REAL_ARCHIVE_RIGGING_SAMPLES[0],
        entries,
        entries_by_path,
        entries_by_basename,
        output_dir,
        game_root=game_root,
        pamt_path=pamt_path,
    )
    result["corpus_manifest"] = _mesh_editor_advanced_authoring_corpus_manifest(entries, entries_by_path)
    return result


def run_real_archive_animation_binding_smoke(game_root: Path) -> dict[str, object]:
    pamt_path = game_root / "0009" / "0.pamt"
    if not pamt_path.is_file():
        return {
            "ok": False,
            "read_only": True,
            "skipped": f"missing PAMT: {pamt_path}",
            "game_root": str(game_root),
            "pamt_path": str(pamt_path),
        }

    entries = parse_archive_pamt(pamt_path)
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    corpus_manifest = _mesh_editor_advanced_authoring_corpus_manifest(entries, entries_by_path)
    model_path = _REAL_ARCHIVE_RIGGING_SAMPLES[0]
    model_entry = next(iter(entries_by_path.get(_archive_key(model_path), ())), None)
    if model_entry is None:
        return {
            "ok": False,
            "read_only": True,
            "game_root": str(game_root),
            "pamt_path": str(pamt_path),
            "model_path": model_path,
            "corpus_manifest": corpus_manifest,
            "error": "model entry not found",
        }

    try:
        pac_data = _read_archive_payload(model_entry)
        skeleton_entry, report = resolve_skeleton_for_model(
            model_entry,
            entries,
            archive_entries_by_normalized_path=entries_by_path,
            archive_entries_by_basename=entries_by_basename,
            pac_data=pac_data,
            read_entry_data=_read_archive_payload,
        )
        if skeleton_entry is None:
            return {
                "ok": False,
                "read_only": True,
                "game_root": str(game_root),
                "pamt_path": str(pamt_path),
                "model_path": model_entry.path,
                "confidence": report.confidence,
                "descriptor_path": report.descriptor_path,
                "corpus_manifest": corpus_manifest,
                "error": "skeleton entry not resolved",
            }

        mesh = parse_mesh(pac_data, model_entry.path)
        skeleton = parse_pab(_read_archive_payload(skeleton_entry), skeleton_entry.path)
        variation_summary = _real_archive_skeleton_variation_summary(report.skeleton_variation_path, entries_by_path, skeleton)
        bone_names = _skeleton_bone_name_bytes(skeleton)
        paa_entries = _real_archive_animation_sample_entries(entries, entries_by_path, _REAL_ARCHIVE_ANIMATION_SAMPLE_LIMIT)
        samples: list[dict[str, object]] = []
        selected_clip = None
        for entry in paa_entries:
            sample, clip = _analyse_real_archive_animation_entry(entry, bone_names, skeleton=skeleton)
            samples.append(sample)
            if selected_clip is None and clip is not None:
                selected_clip = clip
        paa_count = sum(1 for entry in entries if _archive_key(entry.path).endswith(".paa"))
        paseq_count = sum(1 for entry in entries if _archive_key(entry.path).endswith(".paseq"))
        total_keyframe_rows = sum(int(sample.get("keyframe_rows") or 0) for sample in samples)
        total_exact_tracks = sum(int(sample.get("exact_bone_hash_track_count") or 0) for sample in samples)
        total_bound_bones = sum(int(sample.get("bound_bone_count") or 0) for sample in samples)
        total_bone_name_hits = sum(int(sample.get("bone_name_hit_count") or 0) for sample in samples)
        safe_playback_ready = selected_clip is not None
        playback_pose_changed = (
            _prove_real_archive_paa_playback_deformation(mesh, skeleton, selected_clip)
            if selected_clip is not None
            else False
        )
        blockers = _real_archive_animation_binding_blockers(
            sample_count=len(samples),
            keyframe_rows=total_keyframe_rows,
            exact_tracks=total_exact_tracks,
            bound_bones=total_bound_bones,
            bone_name_hits=total_bone_name_hits,
            paseq_count=paseq_count,
        )
        return {
            "ok": bool(
                report.confidence == "descriptor"
                and samples
                and variation_summary.get("matched_record_count")
                and safe_playback_ready
            ),
            "read_only": True,
            "game_root": str(game_root),
            "pamt_path": str(pamt_path),
            "entry_count": len(entries),
            "model_path": model_entry.path,
            "skeleton_path": skeleton_entry.path,
            "confidence": report.confidence,
            "descriptor_path": report.descriptor_path,
            "skeleton_variation_path": report.skeleton_variation_path,
            "animation_constraint_path": report.animation_constraint_path,
            "socket_path": report.socket_path,
            "corpus_manifest": corpus_manifest,
            "skeleton_variation": variation_summary,
            "bone_count": int(getattr(skeleton, "bone_count", 0) or len(getattr(skeleton, "bones", ()) or ())),
            "paa_entry_count": int(paa_count),
            "paseq_entry_count": int(paseq_count),
            "sample_count": len(samples),
            "safe_playback_ready": safe_playback_ready,
            "playback_pose_changed": playback_pose_changed,
            "selected_clip_source": getattr(selected_clip, "source", "") if selected_clip is not None else "",
            "binding_blockers": blockers,
            "total_keyframe_rows": int(total_keyframe_rows),
            "total_exact_bone_hash_track_count": int(total_exact_tracks),
            "total_bound_bone_count": int(total_bound_bones),
            "total_bone_name_hits": int(total_bone_name_hits),
            "samples": samples,
        }
    except Exception as exc:
        return {
            "ok": False,
            "read_only": True,
            "model_path": model_entry.path,
            "corpus_manifest": corpus_manifest,
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_real_archive_sequence_binding_smoke(game_root: Path) -> dict[str, object]:
    entries, pamt_paths, pamt_errors = _real_archive_all_pamt_entries(game_root)
    if not pamt_paths:
        return {
            "ok": False,
            "read_only": True,
            "skipped": f"missing PAMT files under: {game_root}",
            "game_root": str(game_root),
        }
    if not entries:
        return {
            "ok": False,
            "read_only": True,
            "game_root": str(game_root),
            "pamt_count": len(pamt_paths),
            "pamt_errors": pamt_errors,
            "error": "no archive index entries parsed",
        }

    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    corpus_manifest = _mesh_editor_advanced_authoring_corpus_manifest(entries, entries_by_path)
    sequence_entry = _entry_by_archive_path(entries_by_path, _REAL_ARCHIVE_SEQUENCE_SAMPLE)
    skeleton_entry = _entry_by_archive_path(entries_by_path, _REAL_ARCHIVE_SEQUENCE_PTM_PAB)
    model_entry = _entry_by_archive_path(entries_by_path, _REAL_ARCHIVE_RIGGING_SAMPLES[0])
    missing_required = [
        label
        for label, entry in (
            (_REAL_ARCHIVE_SEQUENCE_SAMPLE, sequence_entry),
            (_REAL_ARCHIVE_SEQUENCE_PTM_PAB, skeleton_entry),
            (_REAL_ARCHIVE_RIGGING_SAMPLES[0], model_entry),
        )
        if entry is None
    ]
    sequence_counts = _real_archive_extension_counts_by_package(entries, _REAL_ARCHIVE_SEQUENCE_EXTENSIONS)
    papr_status = _real_archive_papr_read_status(entries)
    sequence_timing_corpus = _real_archive_sequence_timing_corpus_summary(entries)
    if missing_required:
        return {
            "ok": False,
            "read_only": True,
            "game_root": str(game_root),
            "pamt_count": len(pamt_paths),
            "entry_count": len(entries),
            "sequence_entry_counts_by_package": sequence_counts,
            "sequence_timing_corpus": sequence_timing_corpus,
            "papr_read_status": papr_status,
            "corpus_manifest": corpus_manifest,
            "missing_required": missing_required,
        }

    try:
        assert sequence_entry is not None
        assert skeleton_entry is not None
        assert model_entry is not None
        sequence_data = _read_archive_payload(sequence_entry)
        source_sequence_path = _source_sequence_path_for_compiled_sequence(sequence_entry.path)
        source_sequence_entry = _entry_by_archive_path(entries_by_path, source_sequence_path)
        source_sequence_data = _read_archive_payload(source_sequence_entry) if source_sequence_entry is not None else b""
        source_sequence_timing_probe = _binary_timing_probe_counts(source_sequence_data) if source_sequence_data else {}
        source_sequence_document = (
            build_binary_sidecar_analysis_document(
                source_sequence_data,
                source_sequence_entry.path,
                extension=source_sequence_entry.extension,
                source_entry=source_sequence_entry,
                archive_entries_by_normalized_path=entries_by_path,
                archive_entries_by_basename=entries_by_basename,
            )
            if source_sequence_entry is not None
            else {}
        )
        source_sequence_timing_evidence = _document_paseq_timing_evidence(source_sequence_document)
        source_sequence_refs = _document_asset_reference_paths(source_sequence_document)
        source_paseq = source_sequence_document.get("paseq", {}) if isinstance(source_sequence_document, Mapping) else {}
        source_timeline = source_paseq.get("timeline", {}) if isinstance(source_paseq, Mapping) else {}
        sequence_document = build_binary_sidecar_analysis_document(
            sequence_data,
            sequence_entry.path,
            extension=sequence_entry.extension,
            source_entry=sequence_entry,
            archive_entries_by_normalized_path=entries_by_path,
            archive_entries_by_basename=entries_by_basename,
        )
        sequence_refs = _document_asset_reference_paths(sequence_document)
        resolved_refs = _document_related_resolved_paths(sequence_document)
        paseq = sequence_document.get("paseq", {}) if isinstance(sequence_document, dict) else {}
        timeline = paseq.get("timeline", {}) if isinstance(paseq, dict) else {}
        playback = paseq.get("playback_readiness", {}) if isinstance(paseq, dict) else {}
        linked_paa_path = (
            _REAL_ARCHIVE_SEQUENCE_PTM_PAA
            if _archive_key(_REAL_ARCHIVE_SEQUENCE_PTM_PAA) in {_archive_key(path) for path in sequence_refs}
            else next((path for path in sequence_refs if path.lower().endswith(".paa") and "/14_ptm/" in path.lower()), "")
        )
        linked_paa_entry = _entry_by_archive_path(entries_by_path, linked_paa_path) if linked_paa_path else None
        if linked_paa_entry is None:
            linked_paa_entry = _entry_by_archive_path(entries_by_path, _REAL_ARCHIVE_SEQUENCE_PTM_PAA)
            linked_paa_path = linked_paa_entry.path if linked_paa_entry is not None else linked_paa_path

        reference_overlap = _sequence_reference_overlap(source_sequence_refs, sequence_refs, active_path=linked_paa_path)
        lane_pair_summary = _sequence_lane_pair_summary(source_timeline, timeline, active_path=linked_paa_path)
        event_marker_overlap = _sequence_event_marker_overlap(source_timeline, timeline)
        timeline_field_overlap = _sequence_timeline_field_overlap(source_timeline, timeline)
        timeline_field_aliases = _sequence_timeline_field_semantic_aliases(source_timeline, timeline)
        source_active_lane_record_context = _sequence_path_record_context(source_sequence_data, linked_paa_path)
        compiled_active_lane_record_context = _sequence_path_record_context(sequence_data, linked_paa_path)
        sequence_lane = _paseq_lane_for_path(timeline, linked_paa_path)
        skeleton = parse_pab(_read_archive_payload(skeleton_entry), skeleton_entry.path)
        mesh = parse_mesh(_read_archive_payload(model_entry), model_entry.path)
        clip = None
        binding = None
        if linked_paa_entry is not None:
            paa_data = _read_archive_payload(linked_paa_entry)
            frame_rate_source, frame_rate_confidence = _sequence_frame_rate_metadata(source_sequence_timing_probe)
            clip, binding = parse_paa_animation_clip(
                paa_data,
                linked_paa_entry.path,
                skeleton=skeleton,
                frame_rate_source=frame_rate_source,
                frame_rate_confidence=frame_rate_confidence,
                sequence_path=sequence_entry.path,
                sequence_lane_index=sequence_lane.get("index", -1),
                sequence_lane_source_offset=sequence_lane.get("source_offset", 0),
                sequence_lane_confidence=sequence_lane.get("confidence", ""),
            )
            paa_timing = _binary_timing_probe_counts(paa_data)
        else:
            frame_rate_source, frame_rate_confidence = _sequence_frame_rate_metadata(source_sequence_timing_probe)
            paa_timing = {}

        ready_binding = bool(binding is not None and binding.ready and clip is not None)
        playback_sample = (
            _sample_real_archive_paa_playback(mesh, skeleton, clip)
            if clip is not None
            else {"ready": False, "sampled_bone_count": 0, "pose_changed": False}
        )
        playback_sample_ok = bool(
            playback_sample.get("ready")
            and playback_sample.get("pose_changed")
            and playback_sample.get("export_geometry_unchanged")
            and playback_sample.get("deterministic_repeat_seek")
            and int(playback_sample.get("sampled_bone_count") or 0) == 46
            and int(playback_sample.get("repeat_sampled_bone_count") or 0) == 46
            and int(playback_sample.get("active_sequence_lane_index") or -1) == 1
        )
        source_timing_evidence = (
            source_sequence_timing_evidence
            if isinstance(source_sequence_timing_evidence, Mapping)
            else {}
        )
        fps_candidate_rows = source_timing_evidence.get("fps_candidate_value_rows")
        fps_candidate_rows = fps_candidate_rows if isinstance(fps_candidate_rows, Sequence) else ()
        fps_candidate_signature = tuple(
            (
                int(row.get("offset") or 0),
                str(row.get("kind") or ""),
                int(row.get("value") or 0),
                str(row.get("status") or ""),
                str(row.get("value_confidence") or ""),
            )
            for row in fps_candidate_rows
            if isinstance(row, Mapping)
        )
        blend_candidate_rows = source_timing_evidence.get("blend_candidate_value_rows")
        blend_candidate_rows = blend_candidate_rows if isinstance(blend_candidate_rows, Sequence) else ()
        blend_candidate_signature = tuple(
            (
                int(row.get("offset") or 0),
                round(float(row.get("value") or 0.0), 6),
                str(row.get("status") or ""),
                str(row.get("value_confidence") or ""),
            )
            for row in tuple(blend_candidate_rows)[:4]
            if isinstance(row, Mapping)
        )
        paseq_timing_ok = bool(
            int(source_timing_evidence.get("fps_field_declaration_count") or 0) == 2
            and str(source_timing_evidence.get("fps_binding_status") or "")
            == "source_paseq_fps_field_declared_value_offset_unmapped"
            and int(source_timing_evidence.get("fps_candidate_value_region_start") or 0) == 20985
            and fps_candidate_signature
            == (
                (21976, "u32_fps_candidate", 30, "not_bound_length_prefixed_string_context", "blocked"),
                (22116, "u32_fps_candidate", 30, "not_bound_length_prefixed_string_context", "blocked"),
                (24836, "u32_fps_candidate", 24, "unbound_binary_scalar_candidate", "unknown"),
                (30692, "u32_fps_candidate", 15, "unbound_binary_scalar_candidate", "unknown"),
            )
        )
        paseq_blend_value_ok = bool(
            int(source_timing_evidence.get("blend_field_declaration_count") or 0) == 8
            and str(source_timing_evidence.get("blend_binding_status") or "")
            == "blend_fields_declared_value_offsets_unmapped"
            and str(source_timing_evidence.get("blend_candidate_value_scan") or "")
            == "aligned_4_byte_little_endian_nonzero_float32"
            and int(source_timing_evidence.get("blend_candidate_value_region_start") or 0) == 20985
            and int(source_timing_evidence.get("blend_candidate_value_count") or 0) == 32
            and blend_candidate_signature
            == (
                (21336, 0.001953, "unbound_binary_scalar_candidate", "unknown"),
                (22304, 0.078125, "unbound_binary_scalar_candidate", "unknown"),
                (22560, 2.0, "unbound_binary_scalar_candidate", "unknown"),
                (22564, 0.001953, "unbound_binary_scalar_candidate", "unknown"),
            )
        )
        sequence_reference_ok = bool(
            reference_overlap.get("status") == "source_compiled_clip_reference_overlap"
            and int(reference_overlap.get("source_reference_count") or 0) == 3
            and int(reference_overlap.get("compiled_reference_count") or 0) == 2
            and int(reference_overlap.get("overlap_reference_count") or 0) == 2
            and int(reference_overlap.get("source_only_reference_count") or 0) == 1
            and int(reference_overlap.get("compiled_only_reference_count") or 0) == 0
            and bool(reference_overlap.get("active_clip_in_overlap"))
            and tuple(reference_overlap.get("overlap_paths") or ())
            == (
                "character/motion/1_pc/1_phm/01_npc/cd_phm_backpack_00_00_nor_std_idle_02.paa",
                "character/motion/1_pc/14_ptm/01_npc/cd_ptm_backpack_00_00_nor_std_idle_ing_03.paa",
            )
            and tuple(reference_overlap.get("source_only_paths") or ())
            == ("character/motion/1_pc/1_phm/cd_phm_basic_00_00_normal_stand_idle_004.paa",)
        )
        lane_pair_signature = tuple(
            (
                str(row.get("path") or ""),
                int(row.get("source_lane_index") or 0),
                int(row.get("compiled_lane_index") or 0),
                int(row.get("source_offset") or 0),
                int(row.get("compiled_offset") or 0),
                bool(row.get("active_clip")),
            )
            for row in lane_pair_summary.get("lane_pairs") or ()
            if isinstance(row, Mapping)
        )
        sequence_lane_pair_ok = bool(
            lane_pair_summary.get("status") == "source_compiled_lane_pair_overlap"
            and int(lane_pair_summary.get("source_lane_count") or 0) == 3
            and int(lane_pair_summary.get("compiled_lane_count") or 0) == 2
            and int(lane_pair_summary.get("lane_pair_count") or 0) == 2
            and int(lane_pair_summary.get("active_lane_pair_count") or 0) == 1
            and lane_pair_signature
            == (
                (
                    "character/motion/1_pc/1_phm/01_npc/cd_phm_backpack_00_00_nor_std_idle_02.paa",
                    0,
                    0,
                    21702,
                    11018,
                    False,
                ),
                (
                    "character/motion/1_pc/14_ptm/01_npc/cd_ptm_backpack_00_00_nor_std_idle_ing_03.paa",
                    2,
                    1,
                    22031,
                    11402,
                    True,
                ),
            )
        )
        event_marker_signature = tuple(
            (
                str(row.get("text") or ""),
                int(row.get("source_offset") or 0),
                int(row.get("compiled_offset") or 0),
            )
            for row in event_marker_overlap.get("overlap_markers") or ()
            if isinstance(row, Mapping)
        )
        sequence_event_marker_ok = bool(
            event_marker_overlap.get("status") == "source_compiled_event_marker_overlap"
            and int(event_marker_overlap.get("source_marker_count") or 0) == 64
            and int(event_marker_overlap.get("compiled_marker_count") or 0) == 39
            and int(event_marker_overlap.get("overlap_marker_count") or 0) == 14
            and int(event_marker_overlap.get("source_only_marker_count") or 0) == 50
            and int(event_marker_overlap.get("compiled_only_marker_count") or 0) == 25
            and event_marker_signature
            == (
                ("_startTimePiece", 237, 900),
                ("_endTimePiece", 273, 936),
                ("_startOffsetTimePiece", 953, 5998),
                ("_endOffsetTimePiece", 995, 6040),
                ("_hasSequencerCamera", 1035, 6080),
                ("_hasSequencerCamera_Jump", 1074, 6119),
                ("_hasTransformBlend", 1118, 6163),
                ("GameData_TimelineEvent_BodyAnimation", 4742, 5072),
                ("SequencerGamePlayDataEventKey", 4792, 815),
                ("_startOffset", 4990, 5320),
                ("_isLoop", 5125, 2045),
                ("_gimmickTriggerCheckTargetDataList", 11257, 4210),
                ("_connectTrigger", 11635, 3768),
                ("_triggerTagList", 19760, 6349),
            )
        )
        timeline_field_signature = tuple(
            (
                str(row.get("name") or ""),
                str(row.get("role") or ""),
                int(row.get("source_offset") or 0),
                int(row.get("compiled_offset") or 0),
                str(row.get("source_declared_type") or ""),
                str(row.get("compiled_declared_type") or ""),
            )
            for row in timeline_field_overlap.get("overlap_fields") or ()
            if isinstance(row, Mapping)
        )
        source_only_timeline_fields = set(str(value) for value in timeline_field_overlap.get("source_only_fields") or ())
        compiled_only_timeline_fields = set(str(value) for value in timeline_field_overlap.get("compiled_only_fields") or ())
        sequence_timeline_field_ok = bool(
            timeline_field_overlap.get("status") == "source_compiled_timeline_field_overlap"
            and int(timeline_field_overlap.get("source_unique_field_count") or 0) == 173
            and int(timeline_field_overlap.get("compiled_unique_field_count") or 0) == 87
            and int(timeline_field_overlap.get("overlap_field_count") or 0) == 45
            and int(timeline_field_overlap.get("source_only_field_count") or 0) == 128
            and int(timeline_field_overlap.get("compiled_only_field_count") or 0) == 42
            and timeline_field_signature[:8]
            == (
                ("_startTimePiece", "timing", 237, 900, "int32", "int32"),
                ("_endTimePiece", "timing", 273, 936, "int32", "int32"),
                ("_timelineName", "timing", 762, 5807, "staticstringA", "staticstringA"),
                ("_startOffsetTimePiece", "timing", 953, 5998, "int32", "int32"),
                ("_endOffsetTimePiece", "timing", 995, 6040, "int32", "int32"),
                ("_hasSequencerCamera", "scene_context", 1035, 6080, "bool", "bool"),
                ("_hasSequencerCamera_Jump", "scene_context", 1074, 6119, "bool", "bool"),
                ("_hasTransformBlend", "timing", 1118, 6163, "bool", "bool"),
            )
            and {
                "_framesPerSecond",
                "_startBlendingTime",
                "_endBlendingTime",
                "_translationErrorBlend",
                "_rotationErrorBlend",
            }.issubset(source_only_timeline_fields)
            and {"_startBlendTime", "_autoMovingBlend"}.issubset(compiled_only_timeline_fields)
        )
        timeline_field_alias_signature = tuple(
            (
                str(row.get("source_name") or ""),
                str(row.get("compiled_name") or ""),
                str(row.get("alias_key") or ""),
                int(row.get("source_offset") or 0),
                int(row.get("compiled_offset") or 0),
                str(row.get("source_declared_type") or ""),
                str(row.get("compiled_declared_type") or ""),
            )
            for row in timeline_field_aliases.get("alias_rows") or ()
            if isinstance(row, Mapping)
        )
        sequence_timeline_field_alias_ok = bool(
            timeline_field_aliases.get("status") == "source_compiled_timeline_field_semantic_aliases"
            and int(timeline_field_aliases.get("alias_count") or 0) == 1
            and timeline_field_alias_signature
            == (("_startBlendingTime", "_startBlendTime", "startblendtime", 15775, 1678, "float", "float"),)
            and "_endBlendingTime" in set(str(value) for value in timeline_field_aliases.get("unmatched_source_fields") or ())
        )
        source_record_string_signature = tuple(
            (
                int(row.get("offset") or 0),
                int(row.get("length") or 0),
                str(row.get("text") or ""),
            )
            for row in source_active_lane_record_context.get("length_prefixed_strings") or ()
            if isinstance(row, Mapping)
        )
        compiled_record_string_signature = tuple(
            (
                int(row.get("offset") or 0),
                int(row.get("length") or 0),
                str(row.get("text") or ""),
            )
            for row in compiled_active_lane_record_context.get("length_prefixed_strings") or ()
            if isinstance(row, Mapping)
        )
        compiled_record_scalar_signature = tuple(
            (
                int(row.get("offset") or 0),
                int(row.get("u32") or 0),
            )
            for row in compiled_active_lane_record_context.get("scalar_rows") or ()
            if isinstance(row, Mapping)
        )
        sequence_active_lane_record_context_ok = bool(
            source_active_lane_record_context.get("status") == "path_record_window_recovered"
            and int(source_active_lane_record_context.get("path_text_offset") or 0) == 22031
            and int(source_active_lane_record_context.get("path_length_offset") or 0) == 22027
            and int(source_active_lane_record_context.get("length_prefixed_string_count") or 0) == 8
            and int(source_active_lane_record_context.get("fps_like_u32_count") or 0) == 2
            and source_record_string_signature[:5]
            == (
                (21942, 30, "GameCharacterSubtitleEventData"),
                (21980, 26, "NHM_Citizen_BackPack_11229"),
                (22014, 5, "UnitY"),
                (22027, 81, linked_paa_path),
                (22116, 30, "NTM_Citizen_Peddler_BackPack_1"),
            )
            and compiled_active_lane_record_context.get("status") == "path_record_window_recovered"
            and int(compiled_active_lane_record_context.get("path_text_offset") or 0) == 11402
            and int(compiled_active_lane_record_context.get("path_length_offset") or 0) == 11398
            and int(compiled_active_lane_record_context.get("length_prefixed_string_count") or 0) == 1
            and int(compiled_active_lane_record_context.get("fps_like_u32_count") or 0) == 0
            and int(compiled_active_lane_record_context.get("float32_candidate_count") or 0) == 0
            and compiled_record_string_signature
            == ((11398, 81, linked_paa_path),)
            and compiled_record_scalar_signature[:9]
            == (
                (11340, 1024),
                (11360, 2048),
                (11376, 2048),
                (11484, 111),
                (11492, 2),
                (11500, 2304),
                (11516, 2304),
                (11540, 257),
                (11556, 45),
            )
        )
        papr_metadata_totals = papr_status.get("constraint_metadata_totals")
        papr_metadata_totals = papr_metadata_totals if isinstance(papr_metadata_totals, Mapping) else {}
        papr_expression_shape_totals = papr_status.get("constraint_expression_shape_totals")
        papr_expression_shape_totals = papr_expression_shape_totals if isinstance(papr_expression_shape_totals, Mapping) else {}
        papr_expression_syntax_signature_totals = papr_status.get("constraint_expression_syntax_signature_totals")
        papr_expression_syntax_signature_totals = (
            papr_expression_syntax_signature_totals
            if isinstance(papr_expression_syntax_signature_totals, Mapping)
            else {}
        )
        papr_numeric_role_totals = papr_status.get("constraint_expression_numeric_role_totals")
        papr_numeric_role_totals = papr_numeric_role_totals if isinstance(papr_numeric_role_totals, Mapping) else {}
        papr_family_totals = papr_status.get("constraint_candidate_family_totals")
        papr_family_totals = papr_family_totals if isinstance(papr_family_totals, Mapping) else {}
        papr_solver_totals = papr_status.get("constraint_candidate_solver_status_totals")
        papr_solver_totals = papr_solver_totals if isinstance(papr_solver_totals, Mapping) else {}
        papr_family_channel_totals = papr_status.get("constraint_candidate_family_channel_totals")
        papr_family_channel_totals = papr_family_channel_totals if isinstance(papr_family_channel_totals, Mapping) else {}
        papr_driver_channel_totals = papr_family_channel_totals.get("driver_expression_candidate")
        papr_driver_channel_totals = papr_driver_channel_totals if isinstance(papr_driver_channel_totals, Mapping) else {}
        papr_limit_channel_totals = papr_family_channel_totals.get("local_transform_limit_candidate")
        papr_limit_channel_totals = papr_limit_channel_totals if isinstance(papr_limit_channel_totals, Mapping) else {}
        papr_family_limit_totals = papr_status.get("constraint_candidate_family_limit_totals")
        papr_family_limit_totals = papr_family_limit_totals if isinstance(papr_family_limit_totals, Mapping) else {}
        papr_driver_limit_totals = papr_family_limit_totals.get("driver_expression_candidate")
        papr_driver_limit_totals = papr_driver_limit_totals if isinstance(papr_driver_limit_totals, Mapping) else {}
        papr_limit_limit_totals = papr_family_limit_totals.get("local_transform_limit_candidate")
        papr_limit_limit_totals = papr_limit_limit_totals if isinstance(papr_limit_limit_totals, Mapping) else {}
        papr_layout_status_totals = papr_status.get("constraint_record_layout_status_totals")
        papr_layout_status_totals = papr_layout_status_totals if isinstance(papr_layout_status_totals, Mapping) else {}
        papr_field_sequence_totals = papr_status.get("constraint_record_field_sequence_totals")
        papr_field_sequence_totals = papr_field_sequence_totals if isinstance(papr_field_sequence_totals, Mapping) else {}
        papr_gap_status_totals = papr_status.get("constraint_record_gap_status_totals")
        papr_gap_status_totals = papr_gap_status_totals if isinstance(papr_gap_status_totals, Mapping) else {}
        papr_gap_class_totals = papr_status.get("constraint_record_gap_class_totals")
        papr_gap_class_totals = papr_gap_class_totals if isinstance(papr_gap_class_totals, Mapping) else {}
        papr_gap_scalar_status_totals = papr_status.get("constraint_record_gap_scalar_status_totals")
        papr_gap_scalar_status_totals = papr_gap_scalar_status_totals if isinstance(papr_gap_scalar_status_totals, Mapping) else {}
        papr_gap_scalar_kind_totals = papr_status.get("constraint_record_gap_scalar_kind_totals")
        papr_gap_scalar_kind_totals = papr_gap_scalar_kind_totals if isinstance(papr_gap_scalar_kind_totals, Mapping) else {}
        papr_gap_numeric_match_status_totals = papr_status.get("constraint_record_gap_numeric_match_status_totals")
        papr_gap_numeric_match_status_totals = papr_gap_numeric_match_status_totals if isinstance(papr_gap_numeric_match_status_totals, Mapping) else {}
        papr_gap_numeric_match_role_totals = papr_status.get("constraint_record_gap_numeric_match_role_totals")
        papr_gap_numeric_match_role_totals = papr_gap_numeric_match_role_totals if isinstance(papr_gap_numeric_match_role_totals, Mapping) else {}
        papr_gap_numeric_match_scalar_kind_totals = papr_status.get("constraint_record_gap_numeric_match_scalar_kind_totals")
        papr_gap_numeric_match_scalar_kind_totals = papr_gap_numeric_match_scalar_kind_totals if isinstance(papr_gap_numeric_match_scalar_kind_totals, Mapping) else {}
        papr_gap_numeric_match_storage_totals = papr_status.get("constraint_record_gap_numeric_match_storage_totals")
        papr_gap_numeric_match_storage_totals = papr_gap_numeric_match_storage_totals if isinstance(papr_gap_numeric_match_storage_totals, Mapping) else {}
        papr_gap_numeric_match_pair_totals = papr_status.get("constraint_record_gap_numeric_match_pair_totals")
        papr_gap_numeric_match_pair_totals = papr_gap_numeric_match_pair_totals if isinstance(papr_gap_numeric_match_pair_totals, Mapping) else {}
        papr_gap_numeric_match_value_confidence_totals = papr_status.get(
            "constraint_record_gap_numeric_match_value_confidence_totals"
        )
        papr_gap_numeric_match_value_confidence_totals = (
            papr_gap_numeric_match_value_confidence_totals
            if isinstance(papr_gap_numeric_match_value_confidence_totals, Mapping)
            else {}
        )
        papr_gap_numeric_match_family_totals = papr_status.get("constraint_record_gap_numeric_match_family_totals")
        papr_gap_numeric_match_family_totals = papr_gap_numeric_match_family_totals if isinstance(papr_gap_numeric_match_family_totals, Mapping) else {}
        papr_gap_numeric_match_family_row_totals = papr_status.get("constraint_record_gap_numeric_match_family_row_totals")
        papr_gap_numeric_match_family_row_totals = papr_gap_numeric_match_family_row_totals if isinstance(papr_gap_numeric_match_family_row_totals, Mapping) else {}
        papr_gap_numeric_match_family_role_totals = papr_status.get(
            "constraint_record_gap_numeric_match_family_role_totals"
        )
        papr_gap_numeric_match_family_role_totals = (
            papr_gap_numeric_match_family_role_totals
            if isinstance(papr_gap_numeric_match_family_role_totals, Mapping)
            else {}
        )
        papr_driver_role_totals = papr_gap_numeric_match_family_role_totals.get("driver_expression_candidate")
        papr_driver_role_totals = papr_driver_role_totals if isinstance(papr_driver_role_totals, Mapping) else {}
        papr_limit_role_totals = papr_gap_numeric_match_family_role_totals.get("local_transform_limit_candidate")
        papr_limit_role_totals = papr_limit_role_totals if isinstance(papr_limit_role_totals, Mapping) else {}
        papr_gap_numeric_match_family_pair_totals = papr_status.get(
            "constraint_record_gap_numeric_match_family_pair_totals"
        )
        papr_gap_numeric_match_family_pair_totals = (
            papr_gap_numeric_match_family_pair_totals
            if isinstance(papr_gap_numeric_match_family_pair_totals, Mapping)
            else {}
        )
        papr_driver_pair_totals = papr_gap_numeric_match_family_pair_totals.get("driver_expression_candidate")
        papr_driver_pair_totals = papr_driver_pair_totals if isinstance(papr_driver_pair_totals, Mapping) else {}
        papr_limit_pair_totals = papr_gap_numeric_match_family_pair_totals.get("local_transform_limit_candidate")
        papr_limit_pair_totals = papr_limit_pair_totals if isinstance(papr_limit_pair_totals, Mapping) else {}
        papr_gap_numeric_match_family_value_confidence_totals = papr_status.get(
            "constraint_record_gap_numeric_match_family_value_confidence_totals"
        )
        papr_gap_numeric_match_family_value_confidence_totals = (
            papr_gap_numeric_match_family_value_confidence_totals
            if isinstance(papr_gap_numeric_match_family_value_confidence_totals, Mapping)
            else {}
        )
        papr_driver_value_confidence_totals = papr_gap_numeric_match_family_value_confidence_totals.get(
            "driver_expression_candidate"
        )
        papr_driver_value_confidence_totals = (
            papr_driver_value_confidence_totals
            if isinstance(papr_driver_value_confidence_totals, Mapping)
            else {}
        )
        papr_limit_value_confidence_totals = papr_gap_numeric_match_family_value_confidence_totals.get(
            "local_transform_limit_candidate"
        )
        papr_limit_value_confidence_totals = (
            papr_limit_value_confidence_totals
            if isinstance(papr_limit_value_confidence_totals, Mapping)
            else {}
        )
        papr_gap_numeric_match_signature_totals = papr_status.get(
            "constraint_record_gap_numeric_match_signature_totals"
        )
        papr_gap_numeric_match_signature_totals = (
            papr_gap_numeric_match_signature_totals
            if isinstance(papr_gap_numeric_match_signature_totals, Mapping)
            else {}
        )
        papr_gap_numeric_match_candidate_relative_signature_totals = papr_status.get(
            "constraint_record_gap_numeric_match_candidate_relative_signature_totals"
        )
        papr_gap_numeric_match_candidate_relative_signature_totals = (
            papr_gap_numeric_match_candidate_relative_signature_totals
            if isinstance(papr_gap_numeric_match_candidate_relative_signature_totals, Mapping)
            else {}
        )
        papr_top_limit_signature = (
            "family=local_transform_limit_candidate|role=limit_argument|"
            "pair=parent>target|storage=f32|scalar=u32_u16_candidate|"
            "value=approx_float32_numeric_value_match_layout_unproven|prev=13|next=107"
        )
        papr_top_driver_signature = (
            "family=driver_expression_candidate|role=channel_coefficient|"
            "pair=parent>helper|storage=f32|scalar=f32_unit_candidate|"
            "value=exact_float32_numeric_value_match_layout_unproven|prev=383|next=29"
        )
        papr_top_limit_relative_signature = (
            "family=local_transform_limit_candidate|role=limit_argument|"
            "pair=parent>target|storage=f32|scalar=u32_u16_candidate|"
            "value=approx_float32_numeric_value_match_layout_unproven|prev=13|next=107|rel=-161"
        )
        papr_second_limit_relative_signature = (
            "family=local_transform_limit_candidate|role=limit_argument|"
            "pair=parent>target|storage=f32|scalar=u32_u16_candidate|"
            "value=approx_float32_numeric_value_match_layout_unproven|prev=13|next=107|rel=-189"
        )
        papr_gap_numeric_match_previous_delta_totals = papr_status.get(
            "constraint_record_gap_numeric_match_previous_delta_totals"
        )
        papr_gap_numeric_match_previous_delta_totals = (
            papr_gap_numeric_match_previous_delta_totals
            if isinstance(papr_gap_numeric_match_previous_delta_totals, Mapping)
            else {}
        )
        papr_gap_numeric_match_next_delta_totals = papr_status.get(
            "constraint_record_gap_numeric_match_next_delta_totals"
        )
        papr_gap_numeric_match_next_delta_totals = (
            papr_gap_numeric_match_next_delta_totals
            if isinstance(papr_gap_numeric_match_next_delta_totals, Mapping)
            else {}
        )
        papr_gap_numeric_match_candidate_relative_offset_totals = papr_status.get(
            "constraint_record_gap_numeric_match_candidate_relative_offset_totals"
        )
        papr_gap_numeric_match_candidate_relative_offset_totals = (
            papr_gap_numeric_match_candidate_relative_offset_totals
            if isinstance(papr_gap_numeric_match_candidate_relative_offset_totals, Mapping)
            else {}
        )
        papr_gap_numeric_match_rows = papr_status.get("constraint_record_gap_numeric_match_rows")
        papr_gap_numeric_match_rows = papr_gap_numeric_match_rows if isinstance(papr_gap_numeric_match_rows, tuple | list) else ()
        papr_gap_numeric_match_row_confidences = Counter(
            str(row.get("value_confidence") or "")
            for row in papr_gap_numeric_match_rows
            if isinstance(row, Mapping)
        )
        papr_corpus_ok = bool(
            int(papr_status.get("read_ok_count") or 0) == 20
            and int(papr_metadata_totals.get("constraint_record_candidates") or 0) == 545
            and sum(int(count or 0) for count in papr_expression_shape_totals.values()) == 545
            and int(papr_expression_shape_totals.get("linear_channel_transform_candidate") or 0) == 374
            and int(papr_expression_shape_totals.get("absolute_channel_transform_candidate") or 0) == 55
            and int(papr_expression_shape_totals.get("limit_linear_channel_transform_candidate") or 0) == 96
            and int(papr_expression_shape_totals.get("limit_absolute_channel_transform_candidate") or 0) == 15
            and int(papr_expression_shape_totals.get("channel_reference_expression_candidate") or 0) == 5
            and sum(int(count or 0) for count in papr_expression_syntax_signature_totals.values()) == 545
            and len(papr_expression_syntax_signature_totals) == 28
            and int(papr_expression_syntax_signature_totals.get(
                "role=driver_expression|shape=linear_channel_transform_candidate|"
                "channels=Local_Euler_Z|limits=none|numeric_roles=channel_coefficient>additive_offset"
            ) or 0) == 125
            and int(papr_expression_syntax_signature_totals.get(
                "role=driver_expression|shape=linear_channel_transform_candidate|"
                "channels=Local_Euler_Y|limits=none|numeric_roles=channel_coefficient>additive_offset"
            ) or 0) == 109
            and int(papr_expression_syntax_signature_totals.get(
                "role=limit_expression|shape=limit_linear_channel_transform_candidate|"
                "channels=Local_Euler_Z|limits=amin|"
                "numeric_roles=channel_coefficient>additive_offset>limit_argument"
            ) or 0) == 38
            and sum(int(count or 0) for count in papr_numeric_role_totals.values()) == 1177
            and int(papr_numeric_role_totals.get("channel_coefficient") or 0) == 460
            and int(papr_numeric_role_totals.get("additive_offset") or 0) == 455
            and int(papr_numeric_role_totals.get("limit_argument") or 0) == 111
            and int(papr_numeric_role_totals.get("channel_divisor") or 0) == 75
            and int(papr_numeric_role_totals.get("numeric_constant") or 0) == 76
            and int(papr_family_totals.get("driver_expression_candidate") or 0) == 434
            and int(papr_family_totals.get("local_transform_limit_candidate") or 0) == 111
            and int(papr_driver_channel_totals.get("Local_Euler_X") or 0) == 9
            and int(papr_driver_channel_totals.get("Local_Euler_Y") or 0) == 169
            and int(papr_driver_channel_totals.get("Local_Euler_Z") or 0) == 256
            and int(papr_limit_channel_totals.get("Local_Euler_X") or 0) == 15
            and int(papr_limit_channel_totals.get("Local_Euler_Y") or 0) == 18
            and int(papr_limit_channel_totals.get("Local_Euler_Z") or 0) == 78
            and not papr_driver_limit_totals
            and int(papr_limit_limit_totals.get("amin") or 0) == 91
            and int(papr_limit_limit_totals.get("amax") or 0) == 20
            and int(papr_solver_totals.get("blocked_record_layout_unproven") or 0) == 545
            and int(papr_layout_status_totals.get("nearby_string_span_only_value_layout_unproven") or 0) == 545
            and sum(int(count or 0) for count in papr_field_sequence_totals.values()) == 545
            and int(papr_field_sequence_totals.get("parent>helper>target>expression") or 0) > 0
            and sum(int(count or 0) for count in papr_gap_status_totals.values()) == 545
            and int(papr_gap_status_totals.get("binary_like_interfield_gap_bytes_unbound") or 0) == 544
            and int(papr_gap_status_totals.get("printable_interfield_gap_bytes_unbound") or 0) == 1
            and sum(int(count or 0) for count in papr_gap_class_totals.values()) == 946
            and int(papr_gap_class_totals.get("binary_gap") or 0) == 757
            and int(papr_gap_class_totals.get("overlap_or_shared_string") or 0) == 179
            and int(papr_gap_class_totals.get("printable_ascii_gap") or 0) == 5
            and int(papr_gap_class_totals.get("zero_padding") or 0) == 5
            and int(papr_status.get("constraint_record_gap_pair_total") or 0) == 946
            and int(papr_status.get("constraint_record_gap_max_size") or 0) == 741
            and sum(int(count or 0) for count in papr_gap_scalar_status_totals.values()) == 545
            and int(papr_gap_scalar_status_totals.get("unbound_interfield_scalar_candidates") or 0) == 498
            and int(papr_gap_scalar_status_totals.get("no_interfield_scalar_candidates") or 0) == 47
            and sum(int(count or 0) for count in papr_gap_scalar_kind_totals.values()) == 3472
            and int(papr_gap_scalar_kind_totals.get("f32_unit_candidate") or 0) == 1433
            and int(papr_gap_scalar_kind_totals.get("f32_angle_candidate") or 0) == 1201
            and int(papr_gap_scalar_kind_totals.get("u32_u16_candidate") or 0) == 532
            and int(papr_gap_scalar_kind_totals.get("zero_word") or 0) == 187
            and int(papr_gap_scalar_kind_totals.get("f32_small_candidate") or 0) == 75
            and int(papr_gap_scalar_kind_totals.get("u32_u8_candidate") or 0) == 42
            and int(papr_gap_scalar_kind_totals.get("u32_bool_candidate") or 0) == 2
            and int(papr_status.get("constraint_record_gap_aligned_word_total") or 0) == 26169
            and int(papr_status.get("constraint_record_gap_scalar_candidate_total") or 0) == 3472
            and int(papr_status.get("constraint_record_gap_scalar_candidate_max") or 0) == 35
            and sum(int(count or 0) for count in papr_gap_numeric_match_status_totals.values()) == 545
            and int(papr_gap_numeric_match_status_totals.get("unbound_scalar_numeric_constant_matches") or 0) == 26
            and int(papr_gap_numeric_match_status_totals.get("no_scalar_numeric_constant_matches") or 0) == 519
            and sum(int(count or 0) for count in papr_gap_numeric_match_role_totals.values()) == 60
            and int(papr_gap_numeric_match_role_totals.get("limit_argument") or 0) == 31
            and int(papr_gap_numeric_match_role_totals.get("channel_coefficient") or 0) == 18
            and int(papr_gap_numeric_match_role_totals.get("additive_offset") or 0) == 11
            and sum(int(count or 0) for count in papr_gap_numeric_match_scalar_kind_totals.values()) == 60
            and int(papr_gap_numeric_match_scalar_kind_totals.get("f32_unit_candidate") or 0) == 27
            and int(papr_gap_numeric_match_scalar_kind_totals.get("u32_u16_candidate") or 0) == 26
            and int(papr_gap_numeric_match_scalar_kind_totals.get("zero_word") or 0) == 5
            and int(papr_gap_numeric_match_scalar_kind_totals.get("f32_small_candidate") or 0) == 2
            and sum(int(count or 0) for count in papr_gap_numeric_match_storage_totals.values()) == 60
            and int(papr_gap_numeric_match_storage_totals.get("f32") or 0) == 55
            and int(papr_gap_numeric_match_storage_totals.get("u32") or 0) == 5
            and int(papr_status.get("constraint_record_gap_numeric_match_total") or 0) == 60
            and int(papr_status.get("constraint_record_gap_numeric_match_max") or 0) == 5
            and sum(int(count or 0) for count in papr_gap_numeric_match_pair_totals.values()) == 60
            and int(papr_gap_numeric_match_pair_totals.get("parent>target") or 0) == 29
            and int(papr_gap_numeric_match_pair_totals.get("parent>expression") or 0) == 18
            and int(papr_gap_numeric_match_pair_totals.get("parent>helper") or 0) == 12
            and int(papr_gap_numeric_match_pair_totals.get("target>expression") or 0) == 1
            and sum(int(count or 0) for count in papr_gap_numeric_match_value_confidence_totals.values()) == 60
            and int(papr_gap_numeric_match_value_confidence_totals.get("approx_float32_numeric_value_match_layout_unproven") or 0) == 35
            and int(papr_gap_numeric_match_value_confidence_totals.get("exact_float32_numeric_value_match_layout_unproven") or 0) == 20
            and int(papr_gap_numeric_match_value_confidence_totals.get("exact_u32_numeric_value_match_layout_unproven") or 0) == 5
            and sum(int(count or 0) for count in papr_gap_numeric_match_family_totals.values()) == 60
            and sum(int(count or 0) for count in papr_gap_numeric_match_family_row_totals.values()) == 26
            and int(papr_gap_numeric_match_family_totals.get("driver_expression_candidate") or 0) == 18
            and int(papr_gap_numeric_match_family_totals.get("local_transform_limit_candidate") or 0) == 42
            and int(papr_gap_numeric_match_family_row_totals.get("driver_expression_candidate") or 0) == 11
            and int(papr_gap_numeric_match_family_row_totals.get("local_transform_limit_candidate") or 0) == 15
            and sum(int(count or 0) for count in papr_driver_role_totals.values()) == 18
            and int(papr_driver_role_totals.get("channel_coefficient") or 0) == 18
            and sum(int(count or 0) for count in papr_limit_role_totals.values()) == 42
            and int(papr_limit_role_totals.get("additive_offset") or 0) == 11
            and int(papr_limit_role_totals.get("limit_argument") or 0) == 31
            and sum(int(count or 0) for count in papr_driver_pair_totals.values()) == 18
            and int(papr_driver_pair_totals.get("parent>expression") or 0) == 3
            and int(papr_driver_pair_totals.get("parent>helper") or 0) == 12
            and int(papr_driver_pair_totals.get("parent>target") or 0) == 3
            and sum(int(count or 0) for count in papr_limit_pair_totals.values()) == 42
            and int(papr_limit_pair_totals.get("parent>expression") or 0) == 15
            and int(papr_limit_pair_totals.get("parent>target") or 0) == 26
            and int(papr_limit_pair_totals.get("target>expression") or 0) == 1
            and sum(int(count or 0) for count in papr_driver_value_confidence_totals.values()) == 18
            and int(papr_driver_value_confidence_totals.get("approx_float32_numeric_value_match_layout_unproven") or 0) == 2
            and int(papr_driver_value_confidence_totals.get("exact_float32_numeric_value_match_layout_unproven") or 0) == 16
            and sum(int(count or 0) for count in papr_limit_value_confidence_totals.values()) == 42
            and int(papr_limit_value_confidence_totals.get("approx_float32_numeric_value_match_layout_unproven") or 0) == 33
            and int(papr_limit_value_confidence_totals.get("exact_float32_numeric_value_match_layout_unproven") or 0) == 4
            and int(papr_limit_value_confidence_totals.get("exact_u32_numeric_value_match_layout_unproven") or 0) == 5
            and sum(int(count or 0) for count in papr_gap_numeric_match_signature_totals.values()) == 60
            and len(papr_gap_numeric_match_signature_totals) == 46
            and int(papr_gap_numeric_match_signature_totals.get(papr_top_limit_signature) or 0) == 4
            and int(papr_gap_numeric_match_signature_totals.get(papr_top_driver_signature) or 0) == 2
            and sum(int(count or 0) for count in papr_gap_numeric_match_candidate_relative_signature_totals.values()) == 60
            and len(papr_gap_numeric_match_candidate_relative_signature_totals) == 55
            and int(papr_gap_numeric_match_candidate_relative_signature_totals.get(papr_top_limit_relative_signature) or 0) == 2
            and int(papr_gap_numeric_match_candidate_relative_signature_totals.get(papr_second_limit_relative_signature) or 0) == 2
            and sum(int(count or 0) for count in papr_gap_numeric_match_previous_delta_totals.values()) == 60
            and sum(int(count or 0) for count in papr_gap_numeric_match_next_delta_totals.values()) == 60
            and len(papr_gap_numeric_match_previous_delta_totals) == 30
            and len(papr_gap_numeric_match_next_delta_totals) == 34
            and int(papr_gap_numeric_match_previous_delta_totals.get("9") or 0) == 4
            and int(papr_gap_numeric_match_previous_delta_totals.get("20") or 0) == 4
            and int(papr_gap_numeric_match_previous_delta_totals.get("387") or 0) == 2
            and int(papr_gap_numeric_match_next_delta_totals.get("23") or 0) == 4
            and int(papr_gap_numeric_match_next_delta_totals.get("111") or 0) == 4
            and int(papr_gap_numeric_match_next_delta_totals.get("611") or 0) == 1
            and sum(int(count or 0) for count in papr_gap_numeric_match_candidate_relative_offset_totals.values()) == 60
            and len(papr_gap_numeric_match_candidate_relative_offset_totals) == 41
            and int(papr_gap_numeric_match_candidate_relative_offset_totals.get("-105") or 0) == 5
            and int(papr_gap_numeric_match_candidate_relative_offset_totals.get("-109") or 0) == 4
            and int(papr_gap_numeric_match_candidate_relative_offset_totals.get("-81") or 0) == 3
            and int(papr_gap_numeric_match_candidate_relative_offset_totals.get("-6") or 0) == 2
            and int(papr_status.get("constraint_record_gap_numeric_match_min_previous_delta") or 0) == 1
            and int(papr_status.get("constraint_record_gap_numeric_match_max_previous_delta") or 0) == 387
            and int(papr_status.get("constraint_record_gap_numeric_match_min_next_delta") or 0) == 2
            and int(papr_status.get("constraint_record_gap_numeric_match_max_next_delta") or 0) == 611
            and int(papr_status.get("constraint_record_gap_numeric_match_min_candidate_relative_offset") or 0) == -624
            and int(papr_status.get("constraint_record_gap_numeric_match_max_candidate_relative_offset") or 0) == -6
            and papr_status.get("constraint_record_gap_numeric_match_offset_confidence")
            == "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven"
            and papr_status.get("constraint_record_gap_numeric_match_candidate_relative_offset_confidence")
            == "observed_relative_to_inferred_candidate_offset_value_layout_unproven"
            and len(papr_gap_numeric_match_rows) == 24
            and papr_gap_numeric_match_row_confidences["approx_float32_numeric_value_match_layout_unproven"] == 16
            and papr_gap_numeric_match_row_confidences["exact_float32_numeric_value_match_layout_unproven"] == 7
            and papr_gap_numeric_match_row_confidences["exact_u32_numeric_value_match_layout_unproven"] == 1
            and isinstance(papr_gap_numeric_match_rows[0], Mapping)
            and papr_gap_numeric_match_rows[0].get("path") == "character/model/1_pc/14_ptm/ptm_01.papr"
            and papr_gap_numeric_match_rows[0].get("constraint_type") == "local_transform_limit_candidate"
            and papr_gap_numeric_match_rows[0].get("numeric_role") == "limit_argument"
            and papr_gap_numeric_match_rows[0].get("candidate_relative_offset") == -81
            and papr_gap_numeric_match_rows[0].get("candidate_relative_match_signature")
            == (
                "family=local_transform_limit_candidate|role=limit_argument|"
                "pair=parent>target|storage=f32|scalar=u32_u16_candidate|"
                "value=approx_float32_numeric_value_match_layout_unproven|prev=50|next=27|rel=-81"
            )
            and papr_gap_numeric_match_rows[0].get("value_confidence")
            == "approx_float32_numeric_value_match_layout_unproven"
        )
        return {
            "ok": bool(
                sequence_refs
                and linked_paa_entry is not None
                and ready_binding
                and paseq_timing_ok
                and paseq_blend_value_ok
                and sequence_reference_ok
                and sequence_lane_pair_ok
                and sequence_event_marker_ok
                and sequence_timeline_field_ok
                and sequence_timeline_field_alias_ok
                and sequence_active_lane_record_context_ok
                and playback_sample_ok
                and papr_corpus_ok
            ),
            "read_only": True,
            "game_root": str(game_root),
            "pamt_count": len(pamt_paths),
            "pamt_errors": pamt_errors,
            "entry_count": len(entries),
            "sequence_entry_counts_by_package": sequence_counts,
            "sequence_timing_corpus": sequence_timing_corpus,
            "sequence_path": sequence_entry.path,
            "sequence_package": sequence_entry.pamt_path.parent.name,
            "sequence_size": len(sequence_data),
            "source_sequence_path": source_sequence_path,
            "source_sequence_found": source_sequence_entry is not None,
            "source_sequence_timing_probe": source_sequence_timing_probe,
            "source_sequence_timing_evidence": source_sequence_timing_evidence,
            "source_sequence_blend_value_ok": paseq_blend_value_ok,
            "source_sequence_asset_reference_count": len(source_sequence_refs),
            "source_sequence_paa_reference_count": sum(1 for path in source_sequence_refs if path.lower().endswith(".paa")),
            "source_sequence_ptm_paa_references": [
                path for path in source_sequence_refs if path.lower().endswith(".paa") and "/14_ptm/" in path.lower()
            ],
            "source_compiled_reference_overlap": reference_overlap,
            "source_compiled_lane_pair_summary": lane_pair_summary,
            "source_compiled_event_marker_overlap": event_marker_overlap,
            "source_compiled_timeline_field_overlap": timeline_field_overlap,
            "source_compiled_timeline_field_semantic_aliases": timeline_field_aliases,
            "source_active_lane_record_context": source_active_lane_record_context,
            "compiled_active_lane_record_context": compiled_active_lane_record_context,
            "sequence_active_lane_record_context_ok": sequence_active_lane_record_context_ok,
            "sequence_asset_reference_count": len(sequence_refs),
            "sequence_paa_reference_count": sum(1 for path in sequence_refs if path.lower().endswith(".paa")),
            "sequence_ptm_paa_references": [path for path in sequence_refs if path.lower().endswith(".paa") and "/14_ptm/" in path.lower()],
            "sequence_resolved_reference_count": len(resolved_refs),
            "sequence_timeline_lane_count": int(timeline.get("lane_count") or 0) if isinstance(timeline, dict) else 0,
            "sequence_animation_lane_count": int((timeline.get("lane_kind_counts") or {}).get("animation") or 0)
            if isinstance(timeline, dict) and isinstance(timeline.get("lane_kind_counts"), dict)
            else 0,
            "sequence_timeline_field_count": int(timeline.get("timeline_field_count") or 0) if isinstance(timeline, dict) else 0,
            "sequence_playback_status": str(playback.get("status") or "") if isinstance(playback, dict) else "",
            "sequence_playback_gaps": tuple(str(value) for value in (playback.get("blocking_gaps") or ())) if isinstance(playback, dict) else (),
            "sequence_timing_probe": _binary_timing_probe_counts(sequence_data),
            "linked_paa_path": linked_paa_path,
            "linked_paa_found": linked_paa_entry is not None,
            "model_path": model_entry.path,
            "skeleton_path": skeleton_entry.path,
            "paa_binding": {
                "ready": ready_binding,
                "frame_rate": float(getattr(binding, "frame_rate", 0.0) or 0.0) if binding is not None else 0.0,
                "frame_rate_source": str(getattr(binding, "frame_rate_source", frame_rate_source) or "") if binding is not None else frame_rate_source,
                "frame_rate_confidence": str(getattr(binding, "frame_rate_confidence", frame_rate_confidence) or "") if binding is not None else frame_rate_confidence,
                "timing_status": str(getattr(binding, "timing_status", "") or "") if binding is not None else "timing_unproven",
                "game_accurate_timing": bool(getattr(clip, "game_accurate_timing", False)) if clip is not None else False,
                "quaternion_order": str(getattr(binding, "quaternion_order", "") or "") if binding is not None else "",
                "exact_bone_hash_track_count": int(getattr(binding, "exact_bone_hash_track_count", 0) or 0) if binding is not None else 0,
                "bound_bone_count": int(getattr(binding, "bound_bone_count", 0) or 0) if binding is not None else 0,
                "keyframe_count": int(getattr(binding, "keyframe_count", 0) or 0) if binding is not None else 0,
                "frame_start": int(getattr(binding, "frame_start", 0) or 0) if binding is not None else 0,
                "frame_end": int(getattr(binding, "frame_end", 0) or 0) if binding is not None else 0,
                "duration_seconds": float(getattr(clip, "duration_seconds", 0.0) or 0.0) if clip is not None else 0.0,
                "parser_mode": str(getattr(binding, "parser_mode", "") or "") if binding is not None else "",
                "sequence_segment_count": len(tuple(getattr(clip, "sequence_segments", ()) or ())) if clip is not None else 0,
                "sequence_segments": _clip_sequence_segments_json(clip),
            },
            "playback_sample_ok": playback_sample_ok,
            "playback_sample": playback_sample,
            "paa_timing_probe": paa_timing,
            "timing_status": str(sequence_timing_corpus.get("fps_evidence_status") or "sequence_fields_found_but_runtime_fps_not_explicit"),
            "quaternion_status": "paa_rows_decode_as_normalized_xyzw_half_float_quaternions_bound_by_pab_hash",
            "papr_read_status": papr_status,
            "corpus_manifest": corpus_manifest,
        }
    except Exception as exc:
        return {
            "ok": False,
            "read_only": True,
            "game_root": str(game_root),
            "sequence_path": getattr(sequence_entry, "path", _REAL_ARCHIVE_SEQUENCE_SAMPLE),
            "corpus_manifest": corpus_manifest,
            "error": f"{type(exc).__name__}: {exc}",
        }


def run_real_archive_rigging_smoke(game_root: Path) -> dict[str, object]:
    pamt_path = game_root / "0009" / "0.pamt"
    if not pamt_path.is_file():
        return {
            "ok": False,
            "read_only": True,
            "skipped": f"missing PAMT: {pamt_path}",
            "game_root": str(game_root),
            "pamt_path": str(pamt_path),
        }

    entries = parse_archive_pamt(pamt_path)
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    samples = [
        _run_real_archive_rigging_sample(model_path, entries, entries_by_path, entries_by_basename)
        for model_path in _REAL_ARCHIVE_RIGGING_SAMPLES
    ]
    return {
        "ok": bool(samples) and all(bool(sample.get("ok")) for sample in samples),
        "read_only": True,
        "game_root": str(game_root),
        "pamt_path": str(pamt_path),
        "sample_count": len(samples),
        "corpus_manifest": _mesh_editor_advanced_authoring_corpus_manifest(entries, entries_by_path),
        "samples": samples,
    }


def _run_real_archive_rigging_sample(
    model_path: str,
    entries: Sequence[ArchiveEntry],
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
) -> dict[str, object]:
    model_entry = next(iter(entries_by_path.get(_archive_key(model_path), ())), None)
    if model_entry is None:
        return {"ok": False, "model_path": model_path, "error": "model entry not found"}

    try:
        pac_data = _read_archive_payload(model_entry)
        mesh = parse_mesh(pac_data, model_entry.path)
        skeleton_entry, report = resolve_skeleton_for_model(
            model_entry,
            entries,
            archive_entries_by_normalized_path=entries_by_path,
            archive_entries_by_basename=entries_by_basename,
            pac_data=pac_data,
            read_entry_data=_read_archive_payload,
        )
        if skeleton_entry is None:
            return {
                "ok": False,
                "model_path": model_entry.path,
                "confidence": report.confidence,
                "descriptor_path": report.descriptor_path,
                "error": "skeleton entry not resolved",
            }
        skeleton = parse_pab(_read_archive_payload(skeleton_entry), skeleton_entry.path)
        constraint_evidence = _papr_constraint_evidence_for_path(
            entries_by_path,
            entries_by_basename,
            report.animation_constraint_path,
        )

        service = MeshService()
        view = service.open_edit_session(mesh, mode="object")
        summary = service.attach_skeleton(
            view.session_id,
            skeleton,
            source_path=skeleton_entry.path,
            skeleton_descriptor_source=report.descriptor_path,
            skeleton_variation_source=report.skeleton_variation_path,
            animation_constraint_source=report.animation_constraint_path,
            animation_constraint_evidence=constraint_evidence,
            socket_source=report.socket_path,
        )
        selected_bone, pose_changed = _prove_pose_deformation(service, view.session_id, len(getattr(skeleton, "bones", ()) or ()))
        summary = service.skeleton_summary(view.session_id)
        return {
            "ok": bool(pose_changed and report.confidence == "descriptor"),
            "model_path": model_entry.path,
            "skeleton_path": skeleton_entry.path,
            "confidence": report.confidence,
            "descriptor_path": report.descriptor_path,
            "skeleton_variation_path": report.skeleton_variation_path,
            "animation_constraint_path": report.animation_constraint_path,
            "socket_path": report.socket_path,
            "bone_count": int(getattr(skeleton, "bone_count", 0) or len(getattr(skeleton, "bones", ()) or ())),
            "submesh_count": len(getattr(mesh, "submeshes", ()) or ()),
            "vertex_count": int(getattr(mesh, "total_vertices", 0) or 0),
            "weighted_vertex_count": summary.weighted_vertex_count,
            "selected_bone_index": selected_bone,
            "pose_changed": pose_changed,
            "animation_status": summary.animation_status,
            "animation_playback_ready": summary.animation_playback_ready,
            "animation_blockers": list(summary.animation_blockers),
            "constraint_evidence_status": summary.animation_constraint_evidence.status,
            "constraint_string_evidence": summary.animation_constraint_evidence.string_evidence_count,
            "constraint_record_candidates": summary.animation_constraint_evidence.record_candidate_count,
            "constraint_related_physics": summary.animation_constraint_evidence.related_physics_count,
        }
    except Exception as exc:
        return {"ok": False, "model_path": model_entry.path, "error": f"{type(exc).__name__}: {exc}"}


def _run_real_archive_app_workflow_sample(
    model_path: str,
    entries: Sequence[ArchiveEntry],
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
    output_dir: Path,
    *,
    game_root: Path,
    pamt_path: Path,
) -> dict[str, object]:
    model_entry = next(iter(entries_by_path.get(_archive_key(model_path), ())), None)
    if model_entry is None:
        return {"ok": False, "read_only": True, "model_path": model_path, "error": "model entry not found"}
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QSettings, Qt
        from PySide6.QtWidgets import QApplication, QToolButton, QTreeWidget

        from cdmw.ui.mesh_editor import MeshEditorTab

        pac_data = _read_archive_payload(model_entry)
        mesh = parse_mesh(pac_data, model_entry.path)
        skeleton_entry, report = resolve_skeleton_for_model(
            model_entry,
            entries,
            archive_entries_by_normalized_path=entries_by_path,
            archive_entries_by_basename=entries_by_basename,
            pac_data=pac_data,
            read_entry_data=_read_archive_payload,
        )
        if skeleton_entry is None:
            return {
                "ok": False,
                "read_only": True,
                "model_path": model_entry.path,
                "confidence": report.confidence,
                "descriptor_path": report.descriptor_path,
                "error": "skeleton entry not resolved",
            }
        skeleton = parse_pab(_read_archive_payload(skeleton_entry), skeleton_entry.path)
        constraint_evidence = _papr_constraint_evidence_for_path(
            entries_by_path,
            entries_by_basename,
            report.animation_constraint_path,
        )

        app = QApplication.instance() or QApplication(["mesh-editor-real-archive-app-workflow"])
        settings_file = output_dir / "mesh_editor_app_workflow.ini"
        settings = QSettings(str(settings_file), QSettings.Format.IniFormat)
        settings.setFallbacksEnabled(False)
        tab = MeshEditorTab(settings=settings)
        try:
            view = tab.open_mesh_session(mesh, target_entry=model_entry, session_id="real-archive-app-workflow", mode="edit")
            if tab.standalone_controller is None:
                return {"ok": False, "read_only": True, "model_path": model_entry.path, "error": "controller missing"}
            controller = tab.standalone_controller
            controller.attach_skeleton(
                skeleton,
                source_path=skeleton_entry.path,
                skeleton_descriptor_source=report.descriptor_path,
                skeleton_variation_source=report.skeleton_variation_path,
                animation_constraint_source=report.animation_constraint_path,
                animation_constraint_evidence=constraint_evidence,
                socket_source=report.socket_path,
            )
            tab.update_editor_session_state(view, active_selection_mode=controller.active_selection_mode)
            app.processEvents()

            skeleton_tree = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorSkeletonPanel")
            if skeleton_tree is None:
                return {"ok": False, "read_only": True, "model_path": model_entry.path, "error": "skeleton panel missing"}
            selected_bone = next(iter(_weighted_bone_candidates(controller.working_mesh(clone=False), len(getattr(skeleton, "bones", ()) or ()))), -1)
            clicked_bone = False
            for index in range(skeleton_tree.topLevelItemCount()):
                item = skeleton_tree.topLevelItem(index)
                try:
                    item_bone = int(item.data(0, Qt.ItemDataRole.UserRole))
                except (TypeError, ValueError):
                    continue
                if item_bone == selected_bone:
                    tab.standalone_workspace._skeleton_tree_item_clicked(item, 0)
                    clicked_bone = True
                    break

            pose_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorPosePreviewButton")
            rotate_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorPoseRotateYButton")
            if pose_button is not None:
                pose_button.click()
            if rotate_button is not None:
                rotate_button.click()
            app.processEvents()

            summary = controller.skeleton_summary()
            pose_changed = _mesh_vertices_changed(controller.working_mesh(clone=False), controller.pose_preview_mesh())
            rows = [
                (skeleton_tree.topLevelItem(index).text(0), skeleton_tree.topLevelItem(index).text(1))
                for index in range(skeleton_tree.topLevelItemCount())
            ]
            resolver_row = next((value for label, value in rows if label == "Resolver"), "")
            animation_row = next((value for label, value in rows if label == "Animation"), "")
            constraint_row = next((value for label, value in rows if label == "Constraint Evidence"), "")
            constraint_family_row = next((value for label, value in rows if label == "Constraint Families"), "")
            constraint_match_row = next((value for label, value in rows if label == "Constraint Bone Matches"), "")
            constraint_expression_row = next((value for label, value in rows if label == "Constraint Expressions"), "")
            constraint_offset_row = next((value for label, value in rows if label == "Constraint Field Offsets"), "")
            constraint_numeric_match_row = next((value for label, value in rows if label == "Constraint Numeric Matches"), "")
            constraint_solver_row = next((value for label, value in rows if label == "Constraint Solver Readiness"), "")
            constraint_family_detail_rows = {
                label: value
                for label, value in rows
                if str(label).startswith("Constraint Family:")
            }
            driver_family_row = constraint_family_detail_rows.get("Constraint Family: driver_expression_candidate", "")
            limit_family_row = constraint_family_detail_rows.get("Constraint Family: local_transform_limit_candidate", "")
            constraint_candidate_rows = [
                value
                for label, value in rows
                if str(label).startswith("Constraint Candidate:")
            ]
            ok = bool(
                tab.current_archive_selection is model_entry
                and controller.active_session_id
                and clicked_bone
                and pose_changed
                and report.confidence == "descriptor"
                and report.descriptor_path
                and report.skeleton_variation_path
                and "playback blocked" in animation_row
                and "solver blocked" in constraint_row
                and "driver_expression_candidate=49" in constraint_family_row
                and "local_transform_limit_candidate=16" in constraint_family_row
                and "candidate rows" in constraint_match_row
                and "target suffix_base_name" in constraint_match_row
                and "helper exact_name" in constraint_match_row
                and "parent prefix_base_name" in constraint_match_row
                and "channel Local_Euler_Z" in constraint_expression_row
                and "shape linear_channel_transform_candidate" in constraint_expression_row
                and "numeric role channel_coefficient" in constraint_expression_row
                and "syntax signatures 17 unique" in constraint_expression_row
                and "semantics unknown" in constraint_expression_row
                and "target=59" in constraint_offset_row
                and "helper=36" in constraint_offset_row
                and "parent=32" in constraint_offset_row
                and "10 unbound text/scalar numeric matches" in constraint_numeric_match_row
                and "unbound_scalar_numeric_constant_matches=5" in constraint_numeric_match_row
                and "channel_coefficient=5" in constraint_numeric_match_row
                and "limit_argument=5" in constraint_numeric_match_row
                and "storage f32=9" in constraint_numeric_match_row
                and "u32=1" in constraint_numeric_match_row
                and "pairs parent>expression=5" in constraint_numeric_match_row
                and "parent>helper=2" in constraint_numeric_match_row
                and "parent>target=3" in constraint_numeric_match_row
                and "value confidence approx_float32_numeric_value_match_layout_unproven=6" in constraint_numeric_match_row
                and "exact_float32_numeric_value_match_layout_unproven=3" in constraint_numeric_match_row
                and "exact_u32_numeric_value_match_layout_unproven=1" in constraint_numeric_match_row
                and "families driver_expression_candidate=5" in constraint_numeric_match_row
                and "local_transform_limit_candidate=5" in constraint_numeric_match_row
                and "family rows driver_expression_candidate=3" in constraint_numeric_match_row
                and "local_transform_limit_candidate=2" in constraint_numeric_match_row
                and "rel signatures 10 unique" in constraint_numeric_match_row
                and "prev deltas 11=1" in constraint_numeric_match_row
                and "20=2" in constraint_numeric_match_row
                and "380=1 (range 11-380)" in constraint_numeric_match_row
                and "next deltas 5=1" in constraint_numeric_match_row
                and "167=2" in constraint_numeric_match_row
                and "611=1 (range 5-611)" in constraint_numeric_match_row
                and "candidate rel offsets -615=1" in constraint_numeric_match_row
                and "-81=1" in constraint_numeric_match_row
                and "-77=1 (range -615--77)" in constraint_numeric_match_row
                and "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven" in constraint_numeric_match_row
                and "observed_relative_to_inferred_candidate_offset_value_layout_unproven" in constraint_numeric_match_row
                and "value layout unproven" in constraint_numeric_match_row
                and "solver ready=0" in constraint_solver_row
                and "target bound=59" in constraint_solver_row
                and "record layout unproven=65" in constraint_solver_row
                and "expression semantics unknown=65" in constraint_solver_row
                and "candidates=49" in driver_family_row
                and "target bound=45" in driver_family_row
                and "helper bound=24" in driver_family_row
                and "parent bound=19" in driver_family_row
                and "record layout unproven=49" in driver_family_row
                and "expression semantics unknown=49" in driver_family_row
                and "candidates=16" in limit_family_row
                and "target bound=14" in limit_family_row
                and "helper bound=12" in limit_family_row
                and "parent bound=6" in limit_family_row
                and "record layout unproven=16" in limit_family_row
                and "expression semantics unknown=16" in limit_family_row
                and constraint_candidate_rows
                and any("disabled" in value and "blocked_record_layout_unproven" in value for value in constraint_candidate_rows)
                and any("(#" in value and "exact_name" in value for value in constraint_candidate_rows)
                and any("suffix_base_name" in value for value in constraint_candidate_rows)
                and any("prefix_base_name" in value for value in constraint_candidate_rows)
                and any("channels proven: Local_Euler_Z" in value and "numeric constants=" in value for value in constraint_candidate_rows)
                and any("shape inferred_readable_expression_syntax" in value for value in constraint_candidate_rows)
                and any("numeric roles inferred_readable_expression_syntax" in value for value in constraint_candidate_rows)
                and any("limits proven: amin" in value for value in constraint_candidate_rows)
                and any("semantics unknown" in value for value in constraint_candidate_rows)
                and any("fields proven_decoded_string_offsets" in value and "expr@" in value and "target@" in value for value in constraint_candidate_rows)
                and any("gaps binary_like_interfield_gap_bytes_unbound" in value for value in constraint_candidate_rows)
                and any("scalars unbound_interfield_scalar_candidates" in value for value in constraint_candidate_rows)
            )
            return {
                "ok": ok,
                "read_only": True,
                "workflow": "PAMT target lookup -> MeshEditorTab standalone session -> Skeleton panel pose controls",
                "game_root": str(game_root),
                "pamt_path": str(pamt_path),
                "settings_file": str(settings_file),
                "entry_count": len(entries),
                "model_path": model_entry.path,
                "skeleton_path": skeleton_entry.path,
                "confidence": report.confidence,
                "descriptor_path": report.descriptor_path,
                "skeleton_variation_path": report.skeleton_variation_path,
                "animation_constraint_path": report.animation_constraint_path,
                "socket_path": report.socket_path,
                "session_id": controller.active_session_id,
                "pose_changed": pose_changed,
                "selected_bone_index": selected_bone,
                "clicked_bone": clicked_bone,
                "weighted_vertex_count": summary.weighted_vertex_count,
                "animation_status": summary.animation_status,
                "animation_playback_ready": summary.animation_playback_ready,
                "constraint_evidence_status": summary.animation_constraint_evidence.status,
                "constraint_string_evidence": summary.animation_constraint_evidence.string_evidence_count,
                "constraint_record_candidates": summary.animation_constraint_evidence.record_candidate_count,
                "constraint_related_physics": summary.animation_constraint_evidence.related_physics_count,
                "animation_row": animation_row,
                "constraint_row": constraint_row,
                "constraint_family_row": constraint_family_row,
                "constraint_match_row": constraint_match_row,
                "constraint_expression_row": constraint_expression_row,
                "constraint_offset_row": constraint_offset_row,
                "constraint_numeric_match_row": constraint_numeric_match_row,
                "constraint_solver_row": constraint_solver_row,
                "constraint_family_detail_rows": constraint_family_detail_rows,
                "constraint_candidate_rows": constraint_candidate_rows,
                "resolver_row": resolver_row,
            }
        finally:
            tab.close_standalone_session()
            tab.deleteLater()
            app.processEvents()
            settings.sync()
    except Exception as exc:
        return {"ok": False, "read_only": True, "model_path": model_entry.path, "error": f"{type(exc).__name__}: {exc}"}


def _real_archive_all_pamt_entries(game_root: Path) -> tuple[tuple[ArchiveEntry, ...], tuple[Path, ...], tuple[dict[str, str], ...]]:
    pamt_paths = tuple(sorted(Path(game_root).glob("*/0.pamt")))
    entries: list[ArchiveEntry] = []
    errors: list[dict[str, str]] = []
    for pamt_path in pamt_paths:
        try:
            entries.extend(parse_archive_pamt(pamt_path))
        except Exception as exc:
            errors.append({"pamt_path": str(pamt_path), "error": f"{type(exc).__name__}: {exc}"})
    return tuple(entries), pamt_paths, tuple(errors)


def _real_archive_extension_counts_by_package(
    entries: Sequence[ArchiveEntry],
    extensions: Sequence[str],
) -> dict[str, dict[str, int]]:
    wanted = {str(extension).lower() for extension in extensions}
    counts: dict[str, Counter[str]] = {}
    for entry in entries:
        extension = str(entry.extension or "").lower()
        if extension not in wanted:
            continue
        package = entry.pamt_path.parent.name
        counts.setdefault(package, Counter())[extension] += 1
    return {package: dict(counter) for package, counter in sorted(counts.items())}


def _real_archive_papr_read_status(entries: Sequence[ArchiveEntry]) -> dict[str, object]:
    papr_entries = [entry for entry in entries if str(entry.extension or "").lower() == ".papr"]
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    status_counts: Counter[str] = Counter()
    constraint_metadata_totals: Counter[str] = Counter()
    constraint_expression_role_totals: Counter[str] = Counter()
    constraint_expression_shape_totals: Counter[str] = Counter()
    constraint_expression_syntax_signature_totals: Counter[str] = Counter()
    constraint_expression_numeric_role_totals: Counter[str] = Counter()
    constraint_expression_channel_totals: Counter[str] = Counter()
    constraint_limit_operator_totals: Counter[str] = Counter()
    constraint_offset_field_totals: Counter[str] = Counter()
    constraint_candidate_family_totals: Counter[str] = Counter()
    constraint_candidate_solver_status_totals: Counter[str] = Counter()
    constraint_candidate_family_field_totals: dict[str, Counter[str]] = {}
    constraint_candidate_family_channel_totals: dict[str, Counter[str]] = {}
    constraint_candidate_family_limit_totals: dict[str, Counter[str]] = {}
    constraint_record_layout_status_totals: Counter[str] = Counter()
    constraint_record_field_sequence_totals: Counter[str] = Counter()
    constraint_record_gap_status_totals: Counter[str] = Counter()
    constraint_record_gap_class_totals: Counter[str] = Counter()
    constraint_record_gap_scalar_status_totals: Counter[str] = Counter()
    constraint_record_gap_scalar_kind_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_status_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_role_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_scalar_kind_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_storage_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_pair_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_value_confidence_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_family_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_family_row_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_family_role_totals: dict[str, Counter[str]] = {}
    constraint_record_gap_numeric_match_family_pair_totals: dict[str, Counter[str]] = {}
    constraint_record_gap_numeric_match_family_value_confidence_totals: dict[str, Counter[str]] = {}
    constraint_record_gap_numeric_match_signature_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_candidate_relative_signature_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_previous_delta_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_next_delta_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_candidate_relative_offset_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_previous_deltas: list[int] = []
    constraint_record_gap_numeric_match_next_deltas: list[int] = []
    constraint_record_gap_numeric_match_candidate_relative_offsets: list[int] = []
    constraint_record_gap_numeric_match_rows: list[dict[str, object]] = []
    constraint_record_gap_numeric_match_offset_confidence = ""
    constraint_record_gap_numeric_match_candidate_relative_offset_confidence = ""
    constraint_record_layout_max_span_size = 0
    constraint_record_gap_pair_total = 0
    constraint_record_gap_max_size = 0
    constraint_record_gap_aligned_word_total = 0
    constraint_record_gap_scalar_candidate_total = 0
    constraint_record_gap_scalar_candidate_max = 0
    constraint_record_gap_numeric_match_total = 0
    constraint_record_gap_numeric_match_max = 0
    examples: dict[str, str] = {}
    sample: dict[str, object] = {}
    analysis_errors: list[dict[str, str]] = []
    ok_count = 0
    for entry in papr_entries:
        try:
            data, decompressed, note = read_archive_entry_data(entry)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            status = message.split(" for ", 1)[0]
            status_counts[status] += 1
            examples.setdefault(status, entry.path)
        else:
            ok_count += 1
            status_counts["ok"] += 1
            examples.setdefault("ok", entry.path)
            constraint_metadata = _papr_constraint_metadata_summary(
                data,
                entry,
                entries_by_path=entries_by_path,
                entries_by_basename=entries_by_basename,
            )
            if "error" in constraint_metadata:
                if len(analysis_errors) < 4:
                    analysis_errors.append({"path": entry.path, "error": str(constraint_metadata["error"])})
            else:
                for key in (
                    "schema_declarations",
                    "schema_declared_members",
                    "field_like_identifiers",
                    "asset_reference_hints",
                    "offset_candidates",
                    "count_offset_pair_candidates",
                    "float_vector_candidates",
                    "related_file_rows",
                    "related_files_resolved",
                    "constraint_string_evidence",
                    "constraint_record_candidates",
                    "constraint_related_physics",
                ):
                    constraint_metadata_totals[key] += int(constraint_metadata.get(key) or 0)
                _counter_update_ints(constraint_expression_role_totals, constraint_metadata.get("constraint_expression_role_counts"))
                _counter_update_ints(constraint_expression_shape_totals, constraint_metadata.get("constraint_expression_shape_counts"))
                _counter_update_ints(
                    constraint_expression_syntax_signature_totals,
                    constraint_metadata.get("constraint_expression_syntax_signature_counts"),
                )
                _counter_update_ints(constraint_expression_numeric_role_totals, constraint_metadata.get("constraint_expression_numeric_role_counts"))
                _counter_update_ints(constraint_expression_channel_totals, constraint_metadata.get("constraint_expression_channel_counts"))
                _counter_update_ints(constraint_limit_operator_totals, constraint_metadata.get("constraint_limit_operator_counts"))
                _counter_update_ints(constraint_offset_field_totals, constraint_metadata.get("constraint_offset_field_counts"))
                _papr_candidate_family_update(
                    constraint_candidate_family_totals,
                    constraint_candidate_solver_status_totals,
                    constraint_candidate_family_field_totals,
                    constraint_candidate_family_channel_totals,
                    constraint_candidate_family_limit_totals,
                    constraint_metadata.get("constraint_record_candidate_rows"),
                )
                record_layout_evidence = constraint_metadata.get("constraint_record_layout_evidence")
                if isinstance(record_layout_evidence, Mapping):
                    for status, count in (record_layout_evidence.get("layout_status_counts") or {}).items():
                        constraint_record_layout_status_totals[str(status)] += int(count or 0)
                    for sequence, count in (record_layout_evidence.get("field_sequence_counts") or {}).items():
                        constraint_record_field_sequence_totals[str(sequence)] += int(count or 0)
                    for status, count in (record_layout_evidence.get("gap_status_counts") or {}).items():
                        constraint_record_gap_status_totals[str(status)] += int(count or 0)
                    for gap_class, count in (record_layout_evidence.get("gap_class_counts") or {}).items():
                        constraint_record_gap_class_totals[str(gap_class)] += int(count or 0)
                    for status, count in (record_layout_evidence.get("gap_scalar_status_counts") or {}).items():
                        constraint_record_gap_scalar_status_totals[str(status)] += int(count or 0)
                    for scalar_kind, count in (record_layout_evidence.get("gap_scalar_kind_counts") or {}).items():
                        constraint_record_gap_scalar_kind_totals[str(scalar_kind)] += int(count or 0)
                    for status, count in (record_layout_evidence.get("gap_numeric_match_status_counts") or {}).items():
                        constraint_record_gap_numeric_match_status_totals[str(status)] += int(count or 0)
                    for role, count in (record_layout_evidence.get("gap_numeric_match_role_counts") or {}).items():
                        constraint_record_gap_numeric_match_role_totals[str(role)] += int(count or 0)
                    for scalar_kind, count in (record_layout_evidence.get("gap_numeric_match_scalar_kind_counts") or {}).items():
                        constraint_record_gap_numeric_match_scalar_kind_totals[str(scalar_kind)] += int(count or 0)
                    for storage, count in (record_layout_evidence.get("gap_numeric_match_storage_counts") or {}).items():
                        constraint_record_gap_numeric_match_storage_totals[str(storage)] += int(count or 0)
                    for pair, count in (record_layout_evidence.get("gap_numeric_match_pair_counts") or {}).items():
                        constraint_record_gap_numeric_match_pair_totals[str(pair)] += int(count or 0)
                    for confidence, count in (record_layout_evidence.get("gap_numeric_match_value_confidence_counts") or {}).items():
                        constraint_record_gap_numeric_match_value_confidence_totals[str(confidence)] += int(count or 0)
                    for family, count in (record_layout_evidence.get("gap_numeric_match_family_counts") or {}).items():
                        constraint_record_gap_numeric_match_family_totals[str(family)] += int(count or 0)
                    for family, count in (record_layout_evidence.get("gap_numeric_match_family_row_counts") or {}).items():
                        constraint_record_gap_numeric_match_family_row_totals[str(family)] += int(count or 0)
                    family_role_counts = record_layout_evidence.get("gap_numeric_match_family_role_counts")
                    if isinstance(family_role_counts, Mapping):
                        for family, role_counts in family_role_counts.items():
                            if not isinstance(role_counts, Mapping):
                                continue
                            family_counter = constraint_record_gap_numeric_match_family_role_totals.setdefault(
                                str(family),
                                Counter(),
                            )
                            for role, count in role_counts.items():
                                family_counter[str(role)] += int(count or 0)
                    family_pair_counts = record_layout_evidence.get("gap_numeric_match_family_pair_counts")
                    if isinstance(family_pair_counts, Mapping):
                        for family, pair_counts in family_pair_counts.items():
                            if not isinstance(pair_counts, Mapping):
                                continue
                            family_counter = constraint_record_gap_numeric_match_family_pair_totals.setdefault(
                                str(family),
                                Counter(),
                            )
                            for pair, count in pair_counts.items():
                                family_counter[str(pair)] += int(count or 0)
                    family_value_confidence_counts = record_layout_evidence.get(
                        "gap_numeric_match_family_value_confidence_counts"
                    )
                    if isinstance(family_value_confidence_counts, Mapping):
                        for family, confidence_counts in family_value_confidence_counts.items():
                            if not isinstance(confidence_counts, Mapping):
                                continue
                            family_counter = constraint_record_gap_numeric_match_family_value_confidence_totals.setdefault(
                                str(family),
                                Counter(),
                            )
                            for confidence, count in confidence_counts.items():
                                family_counter[str(confidence)] += int(count or 0)
                    for signature, count in (record_layout_evidence.get("gap_numeric_match_signature_counts") or {}).items():
                        constraint_record_gap_numeric_match_signature_totals[str(signature)] += int(count or 0)
                    for signature, count in (
                        record_layout_evidence.get("gap_numeric_match_candidate_relative_signature_counts") or {}
                    ).items():
                        constraint_record_gap_numeric_match_candidate_relative_signature_totals[
                            str(signature)
                        ] += int(count or 0)
                    for delta, count in (record_layout_evidence.get("gap_numeric_match_previous_delta_counts") or {}).items():
                        constraint_record_gap_numeric_match_previous_delta_totals[str(delta)] += int(count or 0)
                    for delta, count in (record_layout_evidence.get("gap_numeric_match_next_delta_counts") or {}).items():
                        constraint_record_gap_numeric_match_next_delta_totals[str(delta)] += int(count or 0)
                    for relative_offset, count in (
                        record_layout_evidence.get("gap_numeric_match_candidate_relative_offset_counts") or {}
                    ).items():
                        constraint_record_gap_numeric_match_candidate_relative_offset_totals[
                            str(relative_offset)
                        ] += int(count or 0)
                    constraint_record_layout_max_span_size = max(
                        constraint_record_layout_max_span_size,
                        int(record_layout_evidence.get("max_span_size") or 0),
                    )
                    constraint_record_gap_pair_total += int(record_layout_evidence.get("gap_pair_count") or 0)
                    constraint_record_gap_max_size = max(
                        constraint_record_gap_max_size,
                        int(record_layout_evidence.get("max_gap_size") or 0),
                    )
                    constraint_record_gap_aligned_word_total += int(record_layout_evidence.get("gap_aligned_word_count") or 0)
                    constraint_record_gap_scalar_candidate_total += int(record_layout_evidence.get("gap_scalar_candidate_count") or 0)
                    constraint_record_gap_scalar_candidate_max = max(
                        constraint_record_gap_scalar_candidate_max,
                        int(record_layout_evidence.get("max_gap_scalar_candidate_count") or 0),
                    )
                    constraint_record_gap_numeric_match_total += int(record_layout_evidence.get("gap_numeric_match_count") or 0)
                    constraint_record_gap_numeric_match_max = max(
                        constraint_record_gap_numeric_match_max,
                        int(record_layout_evidence.get("max_gap_numeric_match_count") or 0),
                    )
                    if int(record_layout_evidence.get("gap_numeric_match_count") or 0) > 0:
                        match_rows = record_layout_evidence.get("gap_numeric_match_rows")
                        if isinstance(match_rows, tuple | list):
                            for match_row in match_rows:
                                if len(constraint_record_gap_numeric_match_rows) >= 24:
                                    break
                                if not isinstance(match_row, Mapping):
                                    continue
                                sample_row = dict(match_row)
                                sample_row["path"] = entry.path
                                constraint_record_gap_numeric_match_rows.append(sample_row)
                        try:
                            constraint_record_gap_numeric_match_previous_deltas.extend(
                                (
                                    int(record_layout_evidence.get("min_gap_numeric_match_previous_delta") or 0),
                                    int(record_layout_evidence.get("max_gap_numeric_match_previous_delta") or 0),
                                )
                            )
                            constraint_record_gap_numeric_match_next_deltas.extend(
                                (
                                    int(record_layout_evidence.get("min_gap_numeric_match_next_delta") or 0),
                                    int(record_layout_evidence.get("max_gap_numeric_match_next_delta") or 0),
                                )
                            )
                            constraint_record_gap_numeric_match_candidate_relative_offsets.extend(
                                (
                                    int(record_layout_evidence.get("min_gap_numeric_match_candidate_relative_offset") or 0),
                                    int(record_layout_evidence.get("max_gap_numeric_match_candidate_relative_offset") or 0),
                                )
                            )
                        except (TypeError, ValueError):
                            pass
                        if record_layout_evidence.get("gap_numeric_match_offset_confidence"):
                            constraint_record_gap_numeric_match_offset_confidence = str(
                                record_layout_evidence.get("gap_numeric_match_offset_confidence")
                            )
                        if record_layout_evidence.get("gap_numeric_match_candidate_relative_offset_confidence"):
                            constraint_record_gap_numeric_match_candidate_relative_offset_confidence = str(
                                record_layout_evidence.get(
                                    "gap_numeric_match_candidate_relative_offset_confidence"
                                )
                            )
                constraint_metadata_totals["constraint_expression_numeric_values"] += int(
                    constraint_metadata.get("constraint_expression_numeric_values") or 0
                )
            if not sample:
                sample = {
                    "path": entry.path,
                    "size": len(data),
                    "decompressed": bool(decompressed),
                    "note": note,
                    "head4_hex": data[:4].hex(),
                    "head4_ascii": data[:4].decode("ascii", "replace"),
                    "constraint_metadata": constraint_metadata,
                }
    return {
        "entry_count": len(papr_entries),
        "read_ok_count": ok_count,
        "error_count": len(papr_entries) - ok_count,
        "constraint_solving_supported": False,
        "constraint_metadata_totals": dict(constraint_metadata_totals),
        "constraint_expression_role_totals": dict(constraint_expression_role_totals),
        "constraint_expression_shape_totals": dict(constraint_expression_shape_totals),
        "constraint_expression_syntax_signature_totals": dict(constraint_expression_syntax_signature_totals),
        "constraint_expression_numeric_role_totals": dict(constraint_expression_numeric_role_totals),
        "constraint_expression_channel_totals": dict(constraint_expression_channel_totals),
        "constraint_limit_operator_totals": dict(constraint_limit_operator_totals),
        "constraint_offset_field_totals": dict(constraint_offset_field_totals),
        "constraint_candidate_family_totals": dict(constraint_candidate_family_totals),
        "constraint_candidate_solver_status_totals": dict(constraint_candidate_solver_status_totals),
        "constraint_candidate_family_field_totals": {
            family: dict(counter)
            for family, counter in sorted(constraint_candidate_family_field_totals.items())
        },
        "constraint_candidate_family_channel_totals": {
            family: dict(counter)
            for family, counter in sorted(constraint_candidate_family_channel_totals.items())
        },
        "constraint_candidate_family_limit_totals": {
            family: dict(counter)
            for family, counter in sorted(constraint_candidate_family_limit_totals.items())
        },
        "constraint_record_layout_status_totals": dict(constraint_record_layout_status_totals),
        "constraint_record_field_sequence_totals": dict(constraint_record_field_sequence_totals),
        "constraint_record_gap_status_totals": dict(constraint_record_gap_status_totals),
        "constraint_record_gap_class_totals": dict(constraint_record_gap_class_totals),
        "constraint_record_gap_scalar_status_totals": dict(constraint_record_gap_scalar_status_totals),
        "constraint_record_gap_scalar_kind_totals": dict(constraint_record_gap_scalar_kind_totals),
        "constraint_record_gap_numeric_match_status_totals": dict(constraint_record_gap_numeric_match_status_totals),
        "constraint_record_gap_numeric_match_role_totals": dict(constraint_record_gap_numeric_match_role_totals),
        "constraint_record_gap_numeric_match_scalar_kind_totals": dict(constraint_record_gap_numeric_match_scalar_kind_totals),
        "constraint_record_gap_numeric_match_storage_totals": dict(constraint_record_gap_numeric_match_storage_totals),
        "constraint_record_gap_numeric_match_pair_totals": dict(constraint_record_gap_numeric_match_pair_totals),
        "constraint_record_gap_numeric_match_value_confidence_totals": dict(
            constraint_record_gap_numeric_match_value_confidence_totals
        ),
        "constraint_record_gap_numeric_match_family_totals": dict(constraint_record_gap_numeric_match_family_totals),
        "constraint_record_gap_numeric_match_family_row_totals": dict(constraint_record_gap_numeric_match_family_row_totals),
        "constraint_record_gap_numeric_match_family_role_totals": {
            family: dict(counter)
            for family, counter in sorted(constraint_record_gap_numeric_match_family_role_totals.items())
        },
        "constraint_record_gap_numeric_match_family_pair_totals": {
            family: dict(counter)
            for family, counter in sorted(constraint_record_gap_numeric_match_family_pair_totals.items())
        },
        "constraint_record_gap_numeric_match_family_value_confidence_totals": {
            family: dict(counter)
            for family, counter in sorted(
                constraint_record_gap_numeric_match_family_value_confidence_totals.items()
            )
        },
        "constraint_record_gap_numeric_match_signature_totals": dict(
            constraint_record_gap_numeric_match_signature_totals
        ),
        "constraint_record_gap_numeric_match_candidate_relative_signature_totals": dict(
            constraint_record_gap_numeric_match_candidate_relative_signature_totals
        ),
        "constraint_record_gap_numeric_match_previous_delta_totals": dict(
            constraint_record_gap_numeric_match_previous_delta_totals
        ),
        "constraint_record_gap_numeric_match_next_delta_totals": dict(
            constraint_record_gap_numeric_match_next_delta_totals
        ),
        "constraint_record_gap_numeric_match_candidate_relative_offset_totals": dict(
            constraint_record_gap_numeric_match_candidate_relative_offset_totals
        ),
        "constraint_record_layout_max_span_size": constraint_record_layout_max_span_size,
        "constraint_record_gap_pair_total": constraint_record_gap_pair_total,
        "constraint_record_gap_max_size": constraint_record_gap_max_size,
        "constraint_record_gap_aligned_word_total": constraint_record_gap_aligned_word_total,
        "constraint_record_gap_scalar_candidate_total": constraint_record_gap_scalar_candidate_total,
        "constraint_record_gap_scalar_candidate_max": constraint_record_gap_scalar_candidate_max,
        "constraint_record_gap_numeric_match_total": constraint_record_gap_numeric_match_total,
        "constraint_record_gap_numeric_match_max": constraint_record_gap_numeric_match_max,
        "constraint_record_gap_numeric_match_rows": tuple(constraint_record_gap_numeric_match_rows),
        "constraint_record_gap_numeric_match_min_previous_delta": (
            min(constraint_record_gap_numeric_match_previous_deltas)
            if constraint_record_gap_numeric_match_previous_deltas
            else 0
        ),
        "constraint_record_gap_numeric_match_max_previous_delta": (
            max(constraint_record_gap_numeric_match_previous_deltas)
            if constraint_record_gap_numeric_match_previous_deltas
            else 0
        ),
        "constraint_record_gap_numeric_match_min_next_delta": (
            min(constraint_record_gap_numeric_match_next_deltas)
            if constraint_record_gap_numeric_match_next_deltas
            else 0
        ),
        "constraint_record_gap_numeric_match_max_next_delta": (
            max(constraint_record_gap_numeric_match_next_deltas)
            if constraint_record_gap_numeric_match_next_deltas
            else 0
        ),
        "constraint_record_gap_numeric_match_min_candidate_relative_offset": (
            min(constraint_record_gap_numeric_match_candidate_relative_offsets)
            if constraint_record_gap_numeric_match_candidate_relative_offsets
            else 0
        ),
        "constraint_record_gap_numeric_match_max_candidate_relative_offset": (
            max(constraint_record_gap_numeric_match_candidate_relative_offsets)
            if constraint_record_gap_numeric_match_candidate_relative_offsets
            else 0
        ),
        "constraint_record_gap_numeric_match_offset_confidence": constraint_record_gap_numeric_match_offset_confidence,
        "constraint_record_gap_numeric_match_candidate_relative_offset_confidence": (
            constraint_record_gap_numeric_match_candidate_relative_offset_confidence
        ),
        "constraint_analysis_errors": tuple(analysis_errors),
        "status_counts": dict(status_counts),
        "examples": examples,
        "sample": sample,
    }


def _counter_update_ints(counter: Counter[str], values: object) -> None:
    if not isinstance(values, Mapping):
        return
    for key, value in values.items():
        counter[str(key)] += int(value or 0)


def _papr_candidate_family_update(
    family_totals: Counter[str],
    solver_status_totals: Counter[str],
    family_field_totals: dict[str, Counter[str]],
    family_channel_totals: dict[str, Counter[str]],
    family_limit_totals: dict[str, Counter[str]],
    rows: object,
) -> None:
    if not isinstance(rows, tuple | list):
        return
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        family = str(row.get("constraint_type") or "constraint_candidate")
        family_totals[family] += 1
        solver_status_totals[str(row.get("solver_status") or "blocked")] += 1
        field_totals = family_field_totals.setdefault(family, Counter())
        for field, label in (
            ("target_bone", "target"),
            ("helper_bone", "helper"),
            ("parent_bone", "parent"),
            ("expression", "expression"),
        ):
            if str(row.get(field) or "").strip():
                field_totals[label] += 1
        channel_totals = family_channel_totals.setdefault(family, Counter())
        for channel in row.get("expression_channels") or ():
            channel_totals[str(channel)] += 1
        limit_totals = family_limit_totals.setdefault(family, Counter())
        for operator in row.get("limit_operators") or ():
            limit_totals[str(operator)] += 1


def _papr_constraint_metadata_summary(
    data: bytes,
    entry: ArchiveEntry,
    *,
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]] | None = None,
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]] | None = None,
) -> dict[str, object]:
    try:
        document = build_binary_sidecar_analysis_document(
            data,
            entry.path,
            extension=".papr",
            source_entry=entry,
            archive_entries_by_normalized_path=entries_by_path if entries_by_path is not None else None,
            archive_entries_by_basename=entries_by_basename if entries_by_basename is not None else None,
        )
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    summary = document.get("summary", {}) if isinstance(document.get("summary"), Mapping) else {}
    container = document.get("container", {}) if isinstance(document.get("container"), Mapping) else {}
    editing = document.get("editing", {}) if isinstance(document.get("editing"), Mapping) else {}
    papr = document.get("papr", {}) if isinstance(document.get("papr"), Mapping) else {}
    expression_evidence = papr.get("expression_evidence") if isinstance(papr.get("expression_evidence"), Mapping) else {}
    offset_evidence = papr.get("offset_evidence") if isinstance(papr.get("offset_evidence"), Mapping) else {}
    record_layout_evidence = papr.get("record_layout_evidence") if isinstance(papr.get("record_layout_evidence"), Mapping) else {}
    return {
        "container_family": str(container.get("recognized_family") or "unknown"),
        "schema_declarations": int(summary.get("schema_declarations") or 0),
        "schema_declared_members": int(summary.get("schema_declared_members") or 0),
        "field_like_identifiers": int(summary.get("field_like_identifiers") or 0),
        "asset_reference_hints": int(summary.get("asset_reference_hints") or 0),
        "offset_candidates": int(summary.get("offset_candidates") or 0),
        "count_offset_pair_candidates": int(summary.get("count_offset_pair_candidates") or 0),
        "float_vector_candidates": int(summary.get("float_vector_candidates") or 0),
        "related_file_rows": int(summary.get("related_file_rows") or 0),
        "related_files_resolved": int(summary.get("related_files_resolved") or 0),
        "constraint_string_evidence": int(papr.get("string_evidence_count") or 0),
        "constraint_record_candidates": int(papr.get("record_candidate_count") or 0),
        "constraint_record_candidate_rows": tuple(papr.get("record_candidates") or ()),
        "constraint_record_layout_evidence": dict(record_layout_evidence),
        "constraint_record_gap_status_counts": dict(record_layout_evidence.get("gap_status_counts") or {}) if isinstance(record_layout_evidence.get("gap_status_counts"), Mapping) else {},
        "constraint_record_gap_class_counts": dict(record_layout_evidence.get("gap_class_counts") or {}) if isinstance(record_layout_evidence.get("gap_class_counts"), Mapping) else {},
        "constraint_record_gap_scalar_status_counts": dict(record_layout_evidence.get("gap_scalar_status_counts") or {}) if isinstance(record_layout_evidence.get("gap_scalar_status_counts"), Mapping) else {},
        "constraint_record_gap_scalar_kind_counts": dict(record_layout_evidence.get("gap_scalar_kind_counts") or {}) if isinstance(record_layout_evidence.get("gap_scalar_kind_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_status_counts": dict(record_layout_evidence.get("gap_numeric_match_status_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_status_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_role_counts": dict(record_layout_evidence.get("gap_numeric_match_role_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_role_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_scalar_kind_counts": dict(record_layout_evidence.get("gap_numeric_match_scalar_kind_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_scalar_kind_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_storage_counts": dict(record_layout_evidence.get("gap_numeric_match_storage_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_storage_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_pair_counts": dict(record_layout_evidence.get("gap_numeric_match_pair_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_pair_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_value_confidence_counts": dict(record_layout_evidence.get("gap_numeric_match_value_confidence_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_value_confidence_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_family_counts": dict(record_layout_evidence.get("gap_numeric_match_family_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_family_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_family_row_counts": dict(record_layout_evidence.get("gap_numeric_match_family_row_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_family_row_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_family_role_counts": dict(record_layout_evidence.get("gap_numeric_match_family_role_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_family_role_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_family_pair_counts": dict(record_layout_evidence.get("gap_numeric_match_family_pair_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_family_pair_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_family_value_confidence_counts": dict(record_layout_evidence.get("gap_numeric_match_family_value_confidence_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_family_value_confidence_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_signature_counts": dict(record_layout_evidence.get("gap_numeric_match_signature_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_signature_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_candidate_relative_signature_counts": dict(record_layout_evidence.get("gap_numeric_match_candidate_relative_signature_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_candidate_relative_signature_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_previous_delta_counts": dict(record_layout_evidence.get("gap_numeric_match_previous_delta_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_previous_delta_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_next_delta_counts": dict(record_layout_evidence.get("gap_numeric_match_next_delta_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_next_delta_counts"), Mapping) else {},
        "constraint_record_gap_numeric_match_candidate_relative_offset_counts": dict(record_layout_evidence.get("gap_numeric_match_candidate_relative_offset_counts") or {}) if isinstance(record_layout_evidence.get("gap_numeric_match_candidate_relative_offset_counts"), Mapping) else {},
        "constraint_record_gap_pair_count": int(record_layout_evidence.get("gap_pair_count") or 0),
        "constraint_record_gap_max_size": int(record_layout_evidence.get("max_gap_size") or 0),
        "constraint_record_gap_aligned_word_count": int(record_layout_evidence.get("gap_aligned_word_count") or 0),
        "constraint_record_gap_scalar_candidate_count": int(record_layout_evidence.get("gap_scalar_candidate_count") or 0),
        "constraint_record_gap_scalar_candidate_max": int(record_layout_evidence.get("max_gap_scalar_candidate_count") or 0),
        "constraint_record_gap_numeric_match_count": int(record_layout_evidence.get("gap_numeric_match_count") or 0),
        "constraint_record_gap_numeric_match_max": int(record_layout_evidence.get("max_gap_numeric_match_count") or 0),
        "constraint_record_gap_numeric_match_rows": tuple(record_layout_evidence.get("gap_numeric_match_rows") or ()),
        "constraint_record_gap_numeric_match_min_previous_delta": int(record_layout_evidence.get("min_gap_numeric_match_previous_delta") or 0),
        "constraint_record_gap_numeric_match_max_previous_delta": int(record_layout_evidence.get("max_gap_numeric_match_previous_delta") or 0),
        "constraint_record_gap_numeric_match_min_next_delta": int(record_layout_evidence.get("min_gap_numeric_match_next_delta") or 0),
        "constraint_record_gap_numeric_match_max_next_delta": int(record_layout_evidence.get("max_gap_numeric_match_next_delta") or 0),
        "constraint_record_gap_numeric_match_min_candidate_relative_offset": int(record_layout_evidence.get("min_gap_numeric_match_candidate_relative_offset") or 0),
        "constraint_record_gap_numeric_match_max_candidate_relative_offset": int(record_layout_evidence.get("max_gap_numeric_match_candidate_relative_offset") or 0),
        "constraint_record_gap_numeric_match_offset_confidence": str(record_layout_evidence.get("gap_numeric_match_offset_confidence") or ""),
        "constraint_record_gap_numeric_match_candidate_relative_offset_confidence": str(record_layout_evidence.get("gap_numeric_match_candidate_relative_offset_confidence") or ""),
        "constraint_expression_evidence": dict(expression_evidence),
        "constraint_expression_role_counts": dict(expression_evidence.get("expression_role_counts") or {}) if isinstance(expression_evidence.get("expression_role_counts"), Mapping) else {},
        "constraint_expression_shape_counts": dict(expression_evidence.get("shape_counts") or {}) if isinstance(expression_evidence.get("shape_counts"), Mapping) else {},
        "constraint_expression_syntax_signature_counts": dict(expression_evidence.get("syntax_signature_counts") or {}) if isinstance(expression_evidence.get("syntax_signature_counts"), Mapping) else {},
        "constraint_expression_numeric_role_counts": dict(expression_evidence.get("numeric_role_counts") or {}) if isinstance(expression_evidence.get("numeric_role_counts"), Mapping) else {},
        "constraint_expression_channel_counts": dict(expression_evidence.get("channel_counts") or {}) if isinstance(expression_evidence.get("channel_counts"), Mapping) else {},
        "constraint_limit_operator_counts": dict(expression_evidence.get("limit_operator_counts") or {}) if isinstance(expression_evidence.get("limit_operator_counts"), Mapping) else {},
        "constraint_expression_numeric_values": int(expression_evidence.get("numeric_value_count") or 0),
        "constraint_offset_evidence": dict(offset_evidence),
        "constraint_offset_field_counts": {
            "target": int(offset_evidence.get("target_offset_count") or 0),
            "helper": int(offset_evidence.get("helper_offset_count") or 0),
            "parent": int(offset_evidence.get("parent_offset_count") or 0),
        },
        "constraint_role_counts": dict(papr.get("role_counts") or {}) if isinstance(papr.get("role_counts"), Mapping) else {},
        "constraint_related_physics": len(papr.get("related_physics_rows") or ()),
        "constraint_evidence_status": str(papr.get("status") or "no_constraint_evidence_recovered"),
        "editing_supported": bool(editing.get("supported")),
        "constraint_solving_supported": False,
        "status": "read_only_schema_recovery",
    }


def _papr_constraint_evidence_for_path(
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
    path: object,
) -> dict[str, object]:
    entry = _entry_by_archive_path(entries_by_path, path)
    if entry is None:
        return {}
    try:
        return _papr_constraint_metadata_summary(
            _read_archive_payload(entry),
            entry,
            entries_by_path=entries_by_path,
            entries_by_basename=entries_by_basename,
        )
    except Exception:
        return {}


def _real_archive_sequence_timing_corpus_summary(entries: Sequence[ArchiveEntry]) -> dict[str, object]:
    sequence_entries = [
        entry
        for entry in entries
        if str(entry.extension or "").lower() in _REAL_ARCHIVE_SEQUENCE_EXTENSIONS
    ]
    by_extension_counts = _real_archive_extension_counts_by_package(sequence_entries, _REAL_ARCHIVE_SEQUENCE_EXTENSIONS)
    entries_by_paz: dict[Path, list[ArchiveEntry]] = {}
    for entry in sequence_entries:
        entries_by_paz.setdefault(entry.paz_file, []).append(entry)
    field_counts: Counter[str] = Counter()
    integer_counts: Counter[str] = Counter()
    float_counts: Counter[str] = Counter()
    per_extension: dict[str, Counter[str]] = {}
    explicit_fps_paths: list[str] = []
    float_fps_paths: list[str] = []
    errors: list[dict[str, str]] = []
    read_count = 0
    for paz_file, paz_entries in entries_by_paz.items():
        try:
            handle_context = paz_file.open("rb")
        except Exception as exc:
            for entry in paz_entries[:8 - len(errors)]:
                errors.append({"path": entry.path, "error": f"{type(exc).__name__}: {exc}"})
            continue
        with handle_context as handle:
            for entry in paz_entries:
                extension = str(entry.extension or "").lower()
                extension_counts = per_extension.setdefault(extension, Counter())
                extension_counts["files"] += 1
                try:
                    data, _decompressed, _note = _read_archive_entry_data_from_handle(handle, entry)
                except Exception as exc:
                    if len(errors) < 8:
                        errors.append({"path": entry.path, "error": f"{type(exc).__name__}: {exc}"})
                    continue
                read_count += 1
                probe = _binary_timing_probe_counts(data)
                for name, count in (probe.get("field_counts") or {}).items():
                    value = int(count or 0)
                    field_counts[str(name)] += value
                    extension_counts[str(name)] += value
                for name, count in (probe.get("integer_counts") or {}).items():
                    value = int(count or 0)
                    integer_counts[str(name)] += value
                    extension_counts[f"u{name}"] += value
                current_float_total = 0
                for name, count in (probe.get("float_counts") or {}).items():
                    value = int(count or 0)
                    float_counts[str(name)] += value
                    extension_counts[f"f{name}"] += value
                    current_float_total += value
                if int(probe.get("explicit_fps_field_count") or 0) > 0 and len(explicit_fps_paths) < 8:
                    explicit_fps_paths.append(entry.path)
                if current_float_total > 0 and len(float_fps_paths) < 8:
                    float_fps_paths.append(entry.path)
    explicit_fps_total = int(field_counts.get("_framespersecond", 0))
    float_fps_total = sum(int(float_counts.get(str(value), 0)) for value in (15, 24, 30, 60))
    status = (
        "explicit_fps_evidence_found_in_sequence_family_corpus"
        if explicit_fps_total > 0
        else "fps_float_candidates_only_in_sequence_family_corpus"
        if float_fps_total > 0
        else "no_explicit_fps_evidence_in_sequence_family_corpus"
    )
    return {
        "entry_count": len(sequence_entries),
        "read_count": read_count,
        "error_count": len(sequence_entries) - read_count,
        "entry_counts_by_package": by_extension_counts,
        "field_counts": dict(field_counts),
        "integer_counts": dict(integer_counts),
        "float_counts": dict(float_counts),
        "per_extension": {extension: dict(counter) for extension, counter in sorted(per_extension.items())},
        "explicit_fps_field_count": explicit_fps_total,
        "float_fps_value_count": float_fps_total,
        "explicit_fps_examples": tuple(explicit_fps_paths),
        "float_fps_examples": tuple(float_fps_paths),
        "read_errors": tuple(errors),
        "fps_evidence_status": status,
    }


def _entry_by_archive_path(
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
    path: object,
) -> ArchiveEntry | None:
    return next(iter(entries_by_path.get(_archive_key(path), ())), None)


def _source_sequence_path_for_compiled_sequence(path: object) -> str:
    value = str(path or "").replace("\\", "/").strip()
    lowered = value.lower()
    if lowered.endswith(".paseqc"):
        return value[:-1]
    return value


def _document_asset_reference_paths(document: Mapping[str, object]) -> tuple[str, ...]:
    references = document.get("references", {}) if isinstance(document, Mapping) else {}
    rows = references.get("asset_reference_hints", ()) if isinstance(references, Mapping) else ()
    result: list[str] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, Sequence) else ():
        if not isinstance(row, Mapping):
            continue
        path = str(row.get("path") or "").replace("\\", "/").strip()
        key = _archive_key(path)
        if key and key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)


def _sequence_reference_overlap(
    source_refs: Sequence[str],
    compiled_refs: Sequence[str],
    *,
    active_path: object = "",
) -> dict[str, object]:
    source_keys = {_archive_key(path) for path in source_refs if _archive_key(path)}
    compiled_keys = {_archive_key(path) for path in compiled_refs if _archive_key(path)}
    overlap = tuple(path for path in source_refs if _archive_key(path) in compiled_keys)
    source_only = tuple(path for path in source_refs if _archive_key(path) not in compiled_keys)
    compiled_only = tuple(path for path in compiled_refs if _archive_key(path) not in source_keys)
    active_key = _archive_key(active_path)
    active_in_overlap = bool(active_key and active_key in {_archive_key(path) for path in overlap})
    overlap_paa_count = sum(1 for path in overlap if str(path).lower().endswith(".paa"))
    status = (
        "source_compiled_clip_reference_overlap"
        if overlap_paa_count > 0
        else "no_source_compiled_clip_reference_overlap"
    )
    return {
        "status": status,
        "confidence": "proven_reference_string_overlap" if overlap_paa_count > 0 else "blocked",
        "source_reference_count": len(source_refs),
        "compiled_reference_count": len(compiled_refs),
        "overlap_reference_count": len(overlap),
        "source_only_reference_count": len(source_only),
        "compiled_only_reference_count": len(compiled_only),
        "source_paa_reference_count": sum(1 for path in source_refs if str(path).lower().endswith(".paa")),
        "compiled_paa_reference_count": sum(1 for path in compiled_refs if str(path).lower().endswith(".paa")),
        "overlap_paa_reference_count": overlap_paa_count,
        "active_clip_in_overlap": active_in_overlap,
        "overlap_paths": overlap,
        "source_only_paths": source_only,
        "compiled_only_paths": compiled_only,
    }


def _sequence_lane_pair_summary(
    source_timeline: Mapping[str, object],
    compiled_timeline: Mapping[str, object],
    *,
    active_path: object = "",
) -> dict[str, object]:
    source_lanes = tuple(
        row for row in (source_timeline.get("lanes") or ()) if isinstance(row, Mapping)
    ) if isinstance(source_timeline, Mapping) else ()
    compiled_lanes = tuple(
        row for row in (compiled_timeline.get("lanes") or ()) if isinstance(row, Mapping)
    ) if isinstance(compiled_timeline, Mapping) else ()
    compiled_by_key = {
        _archive_key(row.get("path")): row
        for row in compiled_lanes
        if _archive_key(row.get("path"))
    }
    active_key = _archive_key(active_path)
    pairs: list[dict[str, object]] = []
    for source_lane in source_lanes:
        key = _archive_key(source_lane.get("path"))
        compiled_lane = compiled_by_key.get(key)
        if not key or compiled_lane is None:
            continue
        pairs.append(
            {
                "path": str(source_lane.get("path") or ""),
                "source_lane_index": int(source_lane.get("index") or 0),
                "compiled_lane_index": int(compiled_lane.get("index") or 0),
                "source_offset": int(source_lane.get("source_offset") or 0),
                "compiled_offset": int(compiled_lane.get("source_offset") or 0),
                "source_confidence": str(source_lane.get("confidence") or ""),
                "compiled_confidence": str(compiled_lane.get("confidence") or ""),
                "active_clip": bool(active_key and key == active_key),
                "status": "source_compiled_lane_pair_read_only",
                "confidence": "proven_reference_string_overlap",
            }
        )
    active_pair_count = sum(1 for row in pairs if bool(row.get("active_clip")))
    return {
        "status": "source_compiled_lane_pair_overlap" if pairs else "no_source_compiled_lane_pair_overlap",
        "confidence": "proven_reference_string_overlap" if pairs else "blocked",
        "source_lane_count": len(source_lanes),
        "compiled_lane_count": len(compiled_lanes),
        "lane_pair_count": len(pairs),
        "active_lane_pair_count": active_pair_count,
        "lane_pairs": tuple(pairs),
    }


def _sequence_event_marker_overlap(
    source_timeline: Mapping[str, object],
    compiled_timeline: Mapping[str, object],
) -> dict[str, object]:
    source_markers = tuple(
        row for row in (source_timeline.get("event_markers") or ()) if isinstance(row, Mapping)
    ) if isinstance(source_timeline, Mapping) else ()
    compiled_markers = tuple(
        row for row in (compiled_timeline.get("event_markers") or ()) if isinstance(row, Mapping)
    ) if isinstance(compiled_timeline, Mapping) else ()
    compiled_by_key: dict[str, Mapping[str, object]] = {}
    for row in compiled_markers:
        key = str(row.get("text") or "").strip().casefold()
        if key and key not in compiled_by_key:
            compiled_by_key[key] = row
    source_keys = {str(row.get("text") or "").strip().casefold() for row in source_markers}
    source_keys.discard("")
    compiled_keys = set(compiled_by_key)
    overlap_rows: list[dict[str, object]] = []
    for row in source_markers:
        text = str(row.get("text") or "").strip()
        key = text.casefold()
        compiled_row = compiled_by_key.get(key)
        if not text or compiled_row is None:
            continue
        overlap_rows.append(
            {
                "text": text,
                "source_offset": int(row.get("offset") or 0),
                "compiled_offset": int(compiled_row.get("offset") or 0),
                "source_role": str(row.get("role") or ""),
                "compiled_role": str(compiled_row.get("role") or ""),
                "status": "source_compiled_event_marker_overlap_read_only",
                "confidence": "proven_readable_string_overlap",
            }
        )
    source_only = tuple(
        str(row.get("text") or "").strip()
        for row in source_markers
        if str(row.get("text") or "").strip().casefold() not in compiled_keys
    )
    compiled_only = tuple(
        str(row.get("text") or "").strip()
        for row in compiled_markers
        if str(row.get("text") or "").strip().casefold() not in source_keys
    )
    return {
        "status": "source_compiled_event_marker_overlap" if overlap_rows else "no_source_compiled_event_marker_overlap",
        "confidence": "proven_readable_string_overlap" if overlap_rows else "blocked",
        "source_marker_count": len(source_markers),
        "compiled_marker_count": len(compiled_markers),
        "overlap_marker_count": len(overlap_rows),
        "source_only_marker_count": len(source_only),
        "compiled_only_marker_count": len(compiled_only),
        "overlap_markers": tuple(overlap_rows),
        "source_only_markers": source_only,
        "compiled_only_markers": compiled_only,
    }


def _sequence_timeline_field_overlap(
    source_timeline: Mapping[str, object],
    compiled_timeline: Mapping[str, object],
) -> dict[str, object]:
    def unique_fields(timeline: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
        rows = tuple(
            row for row in (timeline.get("timeline_fields") or ()) if isinstance(row, Mapping)
        ) if isinstance(timeline, Mapping) else ()
        result: dict[str, Mapping[str, object]] = {}
        for row in rows:
            name = str(row.get("name") or "").strip()
            key = name.casefold()
            if key and key not in result:
                result[key] = row
        return result

    source_fields = unique_fields(source_timeline)
    compiled_fields = unique_fields(compiled_timeline)
    overlap_rows: list[dict[str, object]] = []
    for key, source_row in source_fields.items():
        compiled_row = compiled_fields.get(key)
        if compiled_row is None:
            continue
        overlap_rows.append(
            {
                "name": str(source_row.get("name") or ""),
                "role": str(source_row.get("role") or ""),
                "source_offset": int(source_row.get("offset") or 0),
                "compiled_offset": int(compiled_row.get("offset") or 0),
                "source_declared_type": str(source_row.get("declared_type") or ""),
                "compiled_declared_type": str(compiled_row.get("declared_type") or ""),
                "source_confidence": str(source_row.get("confidence") or ""),
                "compiled_confidence": str(compiled_row.get("confidence") or ""),
                "status": "source_compiled_timeline_field_overlap_read_only",
                "confidence": "proven_field_name_overlap",
            }
        )
    source_only = tuple(
        str(row.get("name") or "")
        for key, row in source_fields.items()
        if key not in compiled_fields
    )
    compiled_only = tuple(
        str(row.get("name") or "")
        for key, row in compiled_fields.items()
        if key not in source_fields
    )
    return {
        "status": "source_compiled_timeline_field_overlap" if overlap_rows else "no_source_compiled_timeline_field_overlap",
        "confidence": "proven_field_name_overlap" if overlap_rows else "blocked",
        "source_unique_field_count": len(source_fields),
        "compiled_unique_field_count": len(compiled_fields),
        "overlap_field_count": len(overlap_rows),
        "source_only_field_count": len(source_only),
        "compiled_only_field_count": len(compiled_only),
        "overlap_fields": tuple(overlap_rows),
        "source_only_fields": source_only,
        "compiled_only_fields": compiled_only,
    }


def _sequence_timeline_field_semantic_aliases(
    source_timeline: Mapping[str, object],
    compiled_timeline: Mapping[str, object],
) -> dict[str, object]:
    def unique_fields(timeline: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
        rows = tuple(
            row for row in (timeline.get("timeline_fields") or ()) if isinstance(row, Mapping)
        ) if isinstance(timeline, Mapping) else ()
        result: dict[str, Mapping[str, object]] = {}
        for row in rows:
            name = str(row.get("name") or "").strip()
            key = name.casefold()
            if key and key not in result:
                result[key] = row
        return result

    def alias_key(name: object) -> str:
        text = str(name or "").strip().lstrip("_").casefold().replace("blending", "blend")
        return "".join(character for character in text if character.isalnum())

    source_fields = unique_fields(source_timeline)
    compiled_fields = unique_fields(compiled_timeline)
    source_only = {
        key: row
        for key, row in source_fields.items()
        if key not in compiled_fields
    }
    compiled_only_by_alias: dict[str, Mapping[str, object]] = {}
    for key, row in compiled_fields.items():
        if key in source_fields:
            continue
        alias = alias_key(row.get("name"))
        if alias and alias not in compiled_only_by_alias:
            compiled_only_by_alias[alias] = row

    alias_rows: list[dict[str, object]] = []
    unmatched_source_fields: list[str] = []
    for row in source_only.values():
        alias = alias_key(row.get("name"))
        compiled_row = compiled_only_by_alias.get(alias)
        if compiled_row is None:
            unmatched_source_fields.append(str(row.get("name") or ""))
            continue
        alias_rows.append(
            {
                "alias_key": alias,
                "source_name": str(row.get("name") or ""),
                "compiled_name": str(compiled_row.get("name") or ""),
                "source_offset": int(row.get("offset") or 0),
                "compiled_offset": int(compiled_row.get("offset") or 0),
                "source_declared_type": str(row.get("declared_type") or ""),
                "compiled_declared_type": str(compiled_row.get("declared_type") or ""),
                "status": "source_compiled_timeline_field_semantic_alias_read_only",
                "confidence": "inferred_name_alias_value_unbound",
            }
        )
    return {
        "status": "source_compiled_timeline_field_semantic_aliases" if alias_rows else "no_source_compiled_timeline_field_semantic_alias",
        "confidence": "inferred_name_alias_value_unbound" if alias_rows else "blocked",
        "alias_count": len(alias_rows),
        "alias_rows": tuple(alias_rows),
        "unmatched_source_fields": tuple(unmatched_source_fields),
    }


def _sequence_path_record_context(
    data: bytes,
    path: object,
    *,
    window_before: int = 96,
    window_after: int = 192,
) -> dict[str, object]:
    path_text = str(path or "").replace("\\", "/").strip()
    path_bytes = path_text.encode("ascii", errors="ignore")
    text_offset = data.find(path_bytes) if path_bytes else -1
    if text_offset < 0:
        return {
            "status": "path_not_found",
            "confidence": "blocked",
            "binding_status": "active_lane_record_layout_unbound",
            "path": path_text,
        }

    path_length_offset = -1
    if text_offset >= 4 and int(struct.unpack_from("<I", data, text_offset - 4)[0]) == len(path_bytes):
        path_length_offset = text_offset - 4
    window_start = max(0, text_offset - max(0, int(window_before)))
    window_end = min(len(data), text_offset + max(0, int(window_after)))
    strings: list[dict[str, object]] = []
    scalar_rows: list[dict[str, object]] = []
    fps_like_u32_count = 0
    float32_candidate_count = 0
    interesting_u32 = {1, 2, 5, 7, 15, 19, 24, 26, 30, 33, 35, 45, 60, 81, 111, 256, 257, 272, 768, 1024, 1536, 2048, 2304}

    for offset in range(window_start, max(window_start, window_end - 3)):
        word = int(struct.unpack_from("<I", data, offset)[0])
        if 3 <= word <= 160 and offset + 4 + word <= window_end:
            text_bytes = data[offset + 4 : offset + 4 + word]
            if all(32 <= byte < 127 for byte in text_bytes):
                strings.append(
                    {
                        "offset": offset,
                        "relative_offset": offset - text_offset,
                        "length": word,
                        "text": text_bytes.decode("ascii"),
                    }
                )

    first_aligned_offset = window_start + (-window_start % 4)
    for offset in range(first_aligned_offset, max(first_aligned_offset, window_end - 3), 4):
        word = int(struct.unpack_from("<I", data, offset)[0])
        if word in {15, 24, 30, 60}:
            fps_like_u32_count += 1
        float_value = float(struct.unpack_from("<f", data, offset)[0])
        is_float_candidate = 0.00001 <= abs(float_value) <= 10.0
        if is_float_candidate:
            float32_candidate_count += 1
        if word in interesting_u32 or is_float_candidate:
            row: dict[str, object] = {
                "offset": offset,
                "relative_offset": offset - text_offset,
                "u32": word,
                "hex": data[offset : offset + 4].hex(),
            }
            if is_float_candidate:
                row["float32"] = round(float_value, 6)
            scalar_rows.append(row)

    return {
        "status": "path_record_window_recovered",
        "confidence": "read_only_window_context",
        "binding_status": "active_lane_record_layout_unbound",
        "path": path_text,
        "path_length": len(path_bytes),
        "path_length_offset": path_length_offset,
        "path_text_offset": text_offset,
        "window_start": window_start,
        "window_end": window_end,
        "length_prefixed_string_count": len(strings),
        "length_prefixed_strings": tuple(strings[:12]),
        "fps_like_u32_count": fps_like_u32_count,
        "float32_candidate_count": float32_candidate_count,
        "scalar_rows": tuple(scalar_rows[:24]),
    }


def _paseq_lane_for_path(timeline: Mapping[str, object], path: object) -> Mapping[str, object]:
    target = _archive_key(path)
    if not target:
        return {}
    lanes = timeline.get("lanes", ()) if isinstance(timeline, Mapping) else ()
    for row in lanes if isinstance(lanes, Sequence) else ():
        if isinstance(row, Mapping) and _archive_key(row.get("path")) == target:
            return row
    return {}


def _document_paseq_timing_evidence(document: Mapping[str, object]) -> Mapping[str, object]:
    paseq = document.get("paseq", {}) if isinstance(document, Mapping) else {}
    timeline = paseq.get("timeline", {}) if isinstance(paseq, Mapping) else {}
    evidence = timeline.get("timing_evidence", {}) if isinstance(timeline, Mapping) else {}
    return evidence if isinstance(evidence, Mapping) else {}


def _document_related_resolved_paths(document: Mapping[str, object]) -> tuple[str, ...]:
    references = document.get("references", {}) if isinstance(document, Mapping) else {}
    rows = references.get("related_files", ()) if isinstance(references, Mapping) else ()
    result: list[str] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, Sequence) else ():
        if not isinstance(row, Mapping):
            continue
        path = str(row.get("resolved_archive_path") or "").replace("\\", "/").strip()
        key = _archive_key(path)
        if key and key not in seen:
            seen.add(key)
            result.append(path)
    return tuple(result)


def _clip_sequence_segments_json(clip: object | None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    segments = tuple(getattr(clip, "sequence_segments", ()) or ()) if clip is not None else ()
    for segment in segments:
        field_confidence = {
            str(name): str(confidence)
            for name, confidence in tuple(getattr(segment, "field_confidence", ()) or ())
        }
        rows.append(
            {
                "sequence_path": str(getattr(segment, "sequence_path", "") or ""),
                "clip_path": str(getattr(segment, "clip_path", "") or ""),
                "lane_index": int(getattr(segment, "lane_index", -1) or -1),
                "lane_source_offset": int(getattr(segment, "lane_source_offset", 0) or 0),
                "start_frame": int(getattr(segment, "start_frame", 0) or 0),
                "end_frame": int(getattr(segment, "end_frame", 0) or 0),
                "start_seconds": float(getattr(segment, "start_seconds", 0.0) or 0.0),
                "end_seconds": float(getattr(segment, "end_seconds", 0.0) or 0.0),
                "blend_weight": float(getattr(segment, "blend_weight", 1.0) or 1.0),
                "skeleton_source": str(getattr(segment, "skeleton_source", "") or ""),
                "status": str(getattr(segment, "status", "") or ""),
                "field_confidence": field_confidence,
            }
        )
    return rows


def _binary_timing_probe_counts(data: bytes) -> dict[str, object]:
    lowered = data.lower()
    field_counts = {
        "_framespersecond": lowered.count(b"_framespersecond"),
        "_starttimepiece": lowered.count(b"_starttimepiece"),
        "_endtimepiece": lowered.count(b"_endtimepiece"),
        "_duration": lowered.count(b"_duration"),
        "_frame": lowered.count(b"_frame"),
        "_time": lowered.count(b"_time"),
    }
    integer_counts = {str(value): data.count(struct.pack("<I", value)) for value in (15, 24, 30, 60)}
    float_counts = {str(value): data.count(struct.pack("<f", float(value))) for value in (15, 24, 30, 60)}
    return {
        "field_counts": field_counts,
        "integer_counts": integer_counts,
        "float_counts": float_counts,
        "explicit_fps_field_count": field_counts["_framespersecond"],
    }


def _archive_entry_indexes(
    entries: Sequence[ArchiveEntry],
) -> tuple[dict[str, tuple[ArchiveEntry, ...]], dict[str, tuple[ArchiveEntry, ...]]]:
    by_path: dict[str, list[ArchiveEntry]] = {}
    by_basename: dict[str, list[ArchiveEntry]] = {}
    for entry in entries:
        key = _archive_key(entry.path)
        if key:
            by_path.setdefault(key, []).append(entry)
            by_basename.setdefault(key.rsplit("/", 1)[-1], []).append(entry)
    return (
        {key: tuple(values) for key, values in by_path.items()},
        {key: tuple(values) for key, values in by_basename.items()},
    )


def _archive_key(path: object) -> str:
    return str(path or "").replace("\\", "/").lower().strip("/")


def _read_archive_payload(entry: ArchiveEntry) -> bytes:
    data, _decompressed, _note = read_archive_entry_data(entry)
    return data


def _real_archive_skeleton_variation_summary(
    variation_path: str,
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
    skeleton: object,
) -> dict[str, object]:
    entry = next(iter(entries_by_path.get(_archive_key(variation_path), ())), None)
    if entry is None:
        return {"path": variation_path, "found": False}
    try:
        variation = parse_pabc_skeleton_variation(_read_archive_payload(entry), entry.path, skeleton=skeleton)
    except Exception as exc:
        return {"path": variation_path, "found": True, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "path": entry.path,
        "found": True,
        "record_count": variation.record_count,
        "matched_record_count": variation.matched_record_count,
        "record_stride": variation.record_stride,
        "tail_size": variation.tail_size,
        "confidence": variation.confidence,
        "first_records": [
            {
                "bone_hash": record.bone_hash,
                "bone_index": record.bone_index,
                "bone_name": record.bone_name,
                "offset": record.offset,
            }
            for record in variation.records[:8]
        ],
    }


def _real_archive_animation_sample_entries(
    entries: Sequence[ArchiveEntry],
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
    limit: int,
) -> tuple[ArchiveEntry, ...]:
    selected: list[ArchiveEntry] = []
    seen: set[str] = set()

    def append(entry: ArchiveEntry | None) -> None:
        if entry is None or len(selected) >= limit:
            return
        key = _archive_key(entry.path)
        if key and key not in seen:
            selected.append(entry)
            seen.add(key)

    for path in _REAL_ARCHIVE_ANIMATION_PREFERRED_PAA:
        append(next(iter(entries_by_path.get(_archive_key(path), ())), None))

    local_entries = [
        entry
        for entry in entries
        if _archive_key(entry.path).endswith(".paa") and "/1_pc/14_ptm/" in _archive_key(entry.path)
    ]
    for entry in _evenly_spaced_entries(local_entries, limit - len(selected)):
        append(entry)

    if len(selected) < limit:
        all_paa_entries = [entry for entry in entries if _archive_key(entry.path).endswith(".paa")]
        for entry in _evenly_spaced_entries(all_paa_entries, limit - len(selected)):
            append(entry)

    return tuple(selected)


def _evenly_spaced_entries(entries: Sequence[ArchiveEntry], limit: int) -> tuple[ArchiveEntry, ...]:
    if limit <= 0 or not entries:
        return ()
    if len(entries) <= limit:
        return tuple(entries)
    if limit == 1:
        return (entries[0],)
    indexes: list[int] = []
    span = len(entries) - 1
    for index in range(limit):
        candidate = round(index * span / (limit - 1))
        if candidate not in indexes:
            indexes.append(candidate)
    return tuple(entries[index] for index in indexes[:limit])


def _analyse_real_archive_animation_entry(
    entry: ArchiveEntry,
    bone_names: Sequence[bytes],
    *,
    skeleton: object,
) -> tuple[dict[str, object], object | None]:
    data = _read_archive_payload(entry)
    document = build_binary_sidecar_analysis_document(data, entry.path, extension=".paa")
    animation = document.get("animation", {}) if isinstance(document, dict) else {}
    tables = list(animation.get("keyframe_table_candidates") or ()) if isinstance(animation, dict) else []
    strings = (document.get("strings", {}) or {}).get("readable_rows", ()) if isinstance(document, dict) else ()
    relationships = document.get("references", {}) if isinstance(document, dict) else {}
    asset_references = (relationships.get("asset_reference_hints", {}) or ()) if isinstance(relationships, dict) else ()
    raw = data.lower()
    bone_name_hits = [name.decode("ascii", "ignore") for name in bone_names if name and name in raw]
    first_table = tables[0] if tables and isinstance(tables[0], dict) else {}
    clip, binding = parse_paa_animation_clip(data, entry.path, skeleton=skeleton)
    return {
        "path": entry.path,
        "size": len(data),
        "keyframe_table_candidates": len(tables),
        "keyframe_rows": sum(int(table.get("row_count") or 0) for table in tables if isinstance(table, dict)),
        "exact_bone_hash_track_count": binding.exact_bone_hash_track_count,
        "bound_bone_count": binding.bound_bone_count,
        "bound_keyframe_count": binding.keyframe_count,
        "frame_start": binding.frame_start,
        "frame_end": binding.frame_end,
        "frame_rate": binding.frame_rate,
        "frame_rate_source": binding.frame_rate_source,
        "frame_rate_confidence": binding.frame_rate_confidence,
        "timing_status": binding.timing_status,
        "game_accurate_timing": bool(getattr(clip, "game_accurate_timing", False)) if clip is not None else False,
        "duration_seconds": float(getattr(clip, "duration_seconds", 0.0) or 0.0) if clip is not None else 0.0,
        "quaternion_order": binding.quaternion_order,
        "parser_mode": binding.parser_mode,
        "string_record_count": len(strings),
        "asset_reference_count": len(asset_references),
        "bone_name_hit_count": len(bone_name_hits),
        "bone_name_hits": bone_name_hits[:8],
        "first_table": {
            key: first_table.get(key)
            for key in ("offset", "row_count", "frame_start", "frame_end", "value_kind", "row_format", "confidence")
        },
    }, clip


def _skeleton_bone_name_bytes(skeleton: object) -> tuple[bytes, ...]:
    result: list[bytes] = []
    seen: set[bytes] = set()
    for bone in tuple(getattr(skeleton, "bones", ()) or ()):
        name = str(getattr(bone, "name", "") or "").strip()
        encoded = name.encode("ascii", "ignore").lower()
        if len(encoded) >= 4 and encoded not in seen:
            result.append(encoded)
            seen.add(encoded)
    return tuple(result)


def _real_archive_animation_binding_blockers(
    *,
    sample_count: int,
    keyframe_rows: int,
    exact_tracks: int,
    bound_bones: int,
    bone_name_hits: int,
    paseq_count: int,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if sample_count <= 0:
        blockers.append("No .paa payloads were sampled from the real archive index.")
    if keyframe_rows <= 0:
        blockers.append("Sampled PAA payloads exposed no decoded value-keyframe rows in the current inspector.")
    if exact_tracks <= 0:
        blockers.append("Sampled PAA keyframe tables did not have PAB bone hashes at table_offset - 8.")
        if bone_name_hits <= 0:
            blockers.append("Sampled PAA payloads contained no attached PAB bone-name strings.")
    if bound_bones <= 0:
        blockers.append("No sampled PAA tracks could be bound to attached PAB bones.")
    if exact_tracks <= 0 and paseq_count <= 0:
        blockers.append("No .paseq entries were present in the sampled package index for sequence context.")
    return tuple(blockers)


def _sequence_frame_rate_metadata(probe: Mapping[str, object]) -> tuple[str, str]:
    if int(probe.get("explicit_fps_field_count") or 0) > 0:
        return "source_paseq_framesPerSecond_field_unbound", "unknown"
    float_counts = probe.get("float_counts") if isinstance(probe.get("float_counts"), Mapping) else {}
    if any(int(float_counts.get(str(value), 0) or 0) > 0 for value in (15, 24, 30, 60)):
        return "sequence_float_fps_candidate", "inferred"
    return "parser_default_30fps", "inferred"


def _sample_real_archive_paa_playback(mesh: ParsedMesh, skeleton: object, clip: object) -> dict[str, object]:
    service = MeshService()
    view = service.open_edit_session(mesh, mode="edit")
    service.attach_skeleton(view.session_id, skeleton)
    service.attach_animation_clip(view.session_id, clip)  # type: ignore[arg-type]
    duration = float(getattr(clip, "duration_seconds", 0.0) or 0.0)
    sample_time = min(max(duration * 0.5, 1.0 / 30.0), 2.0)
    before = service.working_mesh(view.session_id, clone=True)
    summary = service.seek_animation(view.session_id, sample_time)
    preview = service.pose_preview_mesh(view.session_id)
    repeat_summary = service.seek_animation(view.session_id, sample_time)
    repeat_preview = service.pose_preview_mesh(view.session_id)
    after = service.working_mesh(view.session_id, clone=True)
    playback = summary.animation_playback
    repeat_playback = repeat_summary.animation_playback
    time_seconds = float(playback.time_seconds)
    repeat_time_seconds = float(repeat_playback.time_seconds)
    sampled_bone_count = int(playback.sampled_bone_count)
    repeat_sampled_bone_count = int(repeat_playback.sampled_bone_count)
    return {
        "ready": bool(playback.ready),
        "enabled": bool(playback.enabled),
        "time_seconds": time_seconds,
        "repeat_time_seconds": repeat_time_seconds,
        "duration_seconds": float(playback.duration_seconds),
        "sampled_bone_count": sampled_bone_count,
        "repeat_sampled_bone_count": repeat_sampled_bone_count,
        "sequence_segment_count": int(playback.sequence_segment_count),
        "active_sequence_lane_index": int(playback.active_sequence_lane_index),
        "active_sequence_path": str(playback.active_sequence_path or ""),
        "active_sequence_clip_path": str(playback.active_sequence_clip_path or ""),
        "active_sequence_status": str(playback.active_sequence_status or ""),
        "pose_changed": _mesh_vertices_changed(before, preview),
        "deterministic_repeat_seek": bool(
            abs(time_seconds - repeat_time_seconds) <= 1e-9
            and sampled_bone_count == repeat_sampled_bone_count
            and not _mesh_vertices_changed(preview, repeat_preview)
        ),
        "export_geometry_unchanged": not _mesh_vertices_changed(before, after),
        "timing_confidence": str(playback.timing_confidence or ""),
        "timing_status": str(playback.timing_status or ""),
        "game_accurate_timing": bool(playback.game_accurate_timing),
        "status": str(playback.status or ""),
    }


def _prove_real_archive_paa_playback_deformation(mesh: ParsedMesh, skeleton: object, clip: object) -> bool:
    return bool(_sample_real_archive_paa_playback(mesh, skeleton, clip).get("pose_changed"))


def _prove_pose_deformation(service: MeshService, session_id: str, bone_count: int) -> tuple[int, bool]:
    for bone_index in _weighted_bone_candidates(service.working_mesh(session_id), bone_count):
        service.reset_pose(session_id)
        service.set_pose_preview(session_id, True)
        service.select_bone(session_id, bone_index)
        service.rotate_selected_bone(session_id, (0.0, 20.0, 0.0))
        if _mesh_vertices_changed(service.working_mesh(session_id), service.pose_preview_mesh(session_id)):
            return bone_index, True
    return -1, False


def _weighted_bone_candidates(mesh: ParsedMesh, bone_count: int) -> tuple[int, ...]:
    result: list[int] = []
    seen: set[int] = set()
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        for index_row, weight_row in zip(getattr(submesh, "bone_indices", ()) or (), getattr(submesh, "bone_weights", ()) or ()):
            for raw_index, raw_weight in zip(_tuple_row(index_row), _tuple_row(weight_row)):
                try:
                    bone_index = int(raw_index)
                    weight = float(raw_weight)
                except (TypeError, ValueError, OverflowError):
                    continue
                if 0 <= bone_index < bone_count and weight > 1e-6 and bone_index not in seen:
                    seen.add(bone_index)
                    result.append(bone_index)
                    if len(result) >= 32:
                        return tuple(result)
    return tuple(result)


def _mesh_vertices_changed(before: ParsedMesh, after: ParsedMesh) -> bool:
    for before_submesh, after_submesh in zip(before.submeshes, after.submeshes):
        for before_vertex, after_vertex in zip(before_submesh.vertices, after_submesh.vertices):
            before_vec = _vec3(before_vertex)
            after_vec = _vec3(after_vertex)
            if before_vec and after_vec and any(abs(after_vec[axis] - before_vec[axis]) > 1e-5 for axis in range(3)):
                return True
    return False


def _tuple_row(value: object) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    try:
        return tuple(value)  # type: ignore[arg-type]
    except TypeError:
        return (value,)


def _vec3(value: object) -> tuple[float, float, float]:
    try:
        vec = tuple(float(component) for component in value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return ()
    return vec[:3] if len(vec) >= 3 else ()


def _wait_for_status(path: Path, event_names: set[str], timeout_seconds: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, object] = {}
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                last_payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                last_payload = {}
            if last_payload.get("event") in event_names:
                return last_payload
            if last_payload.get("event") == "error":
                return last_payload
        time.sleep(0.05)
    return {}


def _wait_for_file(path: Path, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if path.is_file() and path.stat().st_size > 0:
            return True
        time.sleep(0.05)
    return False


def _png_capture_summary(path: Path) -> dict[str, object]:
    try:
        data = path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return {"ok": False, "error": "not a PNG"}
        width = 0
        height = 0
        bit_depth = 0
        color_type = -1
        idat_chunks: list[bytes] = []
        offset = 8
        while offset + 12 <= len(data):
            chunk_len = struct.unpack(">I", data[offset : offset + 4])[0]
            chunk_type = data[offset + 4 : offset + 8]
            payload_start = offset + 8
            payload_end = payload_start + chunk_len
            if payload_end + 4 > len(data):
                return {"ok": False, "error": "truncated PNG chunk"}
            payload = data[payload_start:payload_end]
            offset = payload_end + 4
            if chunk_type == b"IHDR":
                width, height, bit_depth, color_type = struct.unpack(">IIBB", payload[:10])
            elif chunk_type == b"IDAT":
                idat_chunks.append(payload)
            elif chunk_type == b"IEND":
                break

        channels_by_type = {0: 1, 2: 3, 6: 4}
        channels = channels_by_type.get(color_type)
        if width <= 0 or height <= 0 or not idat_chunks:
            return {"ok": False, "error": "missing PNG image data", "width": width, "height": height}
        if bit_depth != 8 or channels is None:
            return {
                "ok": False,
                "error": f"unsupported PNG format bit_depth={bit_depth} color_type={color_type}",
                "width": width,
                "height": height,
            }

        raw = zlib.decompress(b"".join(idat_chunks))
        row_bytes = width * channels
        if len(raw) < (row_bytes + 1) * height:
            return {"ok": False, "error": "truncated PNG scanlines", "width": width, "height": height}

        unique_rgb: set[tuple[int, int, int]] = set()
        bright_samples = 0
        sampled_pixels = 0
        sample_stride = max(1, (width * height) // 20000)
        previous = bytearray(row_bytes)
        cursor = 0
        for y in range(height):
            filter_type = raw[cursor]
            cursor += 1
            scanline = bytearray(raw[cursor : cursor + row_bytes])
            cursor += row_bytes
            _png_unfilter_scanline(scanline, previous, channels, filter_type)
            for x in range(width):
                if ((y * width) + x) % sample_stride:
                    continue
                pixel_offset = x * channels
                if channels == 1:
                    rgb = (scanline[pixel_offset], scanline[pixel_offset], scanline[pixel_offset])
                else:
                    rgb = (scanline[pixel_offset], scanline[pixel_offset + 1], scanline[pixel_offset + 2])
                unique_rgb.add(rgb)
                bright_samples += int(sum(rgb) >= 96)
                sampled_pixels += 1
            previous = scanline

        ok = width >= 64 and height >= 64 and len(unique_rgb) >= 2 and bright_samples > 0
        return {
            "ok": ok,
            "width": width,
            "height": height,
            "unique_rgb_count": len(unique_rgb),
            "bright_sample_count": bright_samples,
            "sampled_pixel_count": sampled_pixels,
        }
    except (OSError, ValueError, zlib.error, struct.error) as exc:
        return {"ok": False, "error": str(exc)}


def _png_unfilter_scanline(scanline: bytearray, previous: bytearray, channels: int, filter_type: int) -> None:
    for index, value in enumerate(scanline):
        left = scanline[index - channels] if index >= channels else 0
        up = previous[index]
        up_left = previous[index - channels] if index >= channels else 0
        if filter_type == 0:
            continue
        if filter_type == 1:
            scanline[index] = (value + left) & 0xFF
        elif filter_type == 2:
            scanline[index] = (value + up) & 0xFF
        elif filter_type == 3:
            scanline[index] = (value + ((left + up) // 2)) & 0xFF
        elif filter_type == 4:
            scanline[index] = (value + _png_paeth(left, up, up_left)) & 0xFF
        else:
            raise ValueError(f"unsupported PNG filter: {filter_type}")


def _png_paeth(left: int, up: int, up_left: int) -> int:
    estimate = left + up - up_left
    left_distance = abs(estimate - left)
    up_distance = abs(estimate - up)
    up_left_distance = abs(estimate - up_left)
    if left_distance <= up_distance and left_distance <= up_left_distance:
        return left
    if up_distance <= up_left_distance:
        return up
    return up_left


def _wait_for_host_window(pid: int, timeout_seconds: float) -> int:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        hwnd = _find_host_window(pid)
        if hwnd:
            return hwnd
        time.sleep(0.05)
    return 0


def _find_host_window(pid: int) -> int:
    user32 = ctypes.windll.user32
    matches: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def enum_proc(hwnd: int, _lparam: int) -> bool:
        window_pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(window_pid))
        if int(window_pid.value) != int(pid):
            return True
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(ctypes.c_void_p(hwnd), buffer, len(buffer))
        if buffer.value == _HOST_CLASS:
            matches.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(enum_proc, None)
    return matches[0] if matches else 0


def _send_json_command(hwnd: int, payload: Mapping[str, object]) -> bool:
    class CopyDataStruct(ctypes.Structure):
        _fields_ = [
            ("dwData", ctypes.c_size_t),
            ("cbData", ctypes.c_uint),
            ("lpData", ctypes.c_void_p),
        ]

    encoded = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8") + b"\0"
    buffer = ctypes.create_string_buffer(encoded)
    cds = CopyDataStruct(_WM_COPYDATA_COMMAND, len(encoded), ctypes.cast(buffer, ctypes.c_void_p))
    result_value = ctypes.c_size_t()
    sent = ctypes.windll.user32.SendMessageTimeoutW(
        ctypes.c_void_p(hwnd),
        _WM_COPYDATA,
        0,
        ctypes.byref(cds),
        0x0002,
        2000,
        ctypes.byref(result_value),
    )
    return bool(sent and result_value.value)


def _close_process(process: subprocess.Popen[bytes]) -> None:
    try:
        hwnd = _find_host_window(process.pid)
        if hwnd:
            ctypes.windll.user32.PostMessageW(ctypes.c_void_p(hwnd), _WM_CLOSE, 0, 0)
        process.wait(timeout=2.0)
    except Exception:
        process.kill()
        process.wait(timeout=2.0)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Mesh Editor service/native preview harness without starting the app.")
    parser.add_argument(
        "--scenario",
        default="full-suite-smoke",
        choices=(
            "full-suite-smoke",
            "service-smoke",
            "real-archive-rigging-smoke",
            "real-archive-animation-binding-smoke",
            "real-archive-sequence-binding-smoke",
            "real-archive-app-workflow-smoke",
        ),
    )
    parser.add_argument("--game-root", type=Path, default=_DEFAULT_GAME_ROOT)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = run_scenario(args.scenario, args.output, game_root=args.game_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
