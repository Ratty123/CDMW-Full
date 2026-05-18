from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from cdmw.core.common import hidden_subprocess_kwargs
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.rendering.native_preview_core import find_native_preview_core_binary


NATIVE_MESH_BACKEND_ID = "cdmw_preview_core_mesh_audit_0.1"


def _native_diagnostic_args() -> list[str]:
    args: list[str] = []
    crash_dir = str(os.environ.get("CDMW_CRASH_DIR", "") or "").strip()
    diagnostic_log = str(os.environ.get("CDMW_NATIVE_DIAGNOSTIC_LOG", "") or "").strip()
    if crash_dir:
        args.extend(["--crash-dir", crash_dir])
    if diagnostic_log:
        args.extend(["--diagnostic-log", diagnostic_log])
    return args


def audit_mesh_native(data: bytes, filename: str = "", *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    return _run_mesh_file_report("mesh-audit-job", data, filename, timeout_seconds=timeout_seconds)


def _run_mesh_file_report(command: str, data: bytes, filename: str = "", *, timeout_seconds: float = 10.0) -> dict[str, Any]:
    binary = find_native_preview_core_binary()
    if binary is None:
        return {"status": "missing", "backend": NATIVE_MESH_BACKEND_ID}
    try:
        with tempfile.TemporaryDirectory(prefix="cdmw_mesh_native_audit_") as temp_dir:
            temp_path = Path(temp_dir)
            input_path = temp_path / "mesh_input.bin"
            report_path = temp_path / "mesh_audit.json"
            input_path.write_bytes(bytes(data))
            completed = subprocess.run(
                [
                    str(binary),
                    command,
                    str(input_path),
                    str(report_path),
                    str(filename or ""),
                    *_native_diagnostic_args(),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=max(1.0, float(timeout_seconds)),
                check=False,
                **hidden_subprocess_kwargs(),
            )
            if completed.returncode != 0 or not report_path.is_file():
                return {
                    "status": "error",
                    "backend": NATIVE_MESH_BACKEND_ID,
                    "message": completed.stderr.decode("utf-8", errors="replace")[:500],
                }
            parsed = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        return {"status": "error", "backend": NATIVE_MESH_BACKEND_ID, "message": str(exc)}
    return parsed if isinstance(parsed, dict) else {"status": "error", "backend": NATIVE_MESH_BACKEND_ID}


def parse_mesh_native(data: bytes, filename: str = "") -> Optional[ParsedMesh]:
    audit = _run_mesh_file_report("mesh-parse-job", data, filename)
    if audit.get("status") != "ok" or not audit.get("parity_ready"):
        return None
    # The native path is intentionally audit-only until parity tests prove that
    # converting the native model back into ParsedMesh is behaviorally identical.
    return None


def _sequence_payload(values: object) -> list:
    if not isinstance(values, (list, tuple)):
        return []
    payload: list = []
    for value in values:
        if isinstance(value, (list, tuple)):
            payload.append(list(value))
        else:
            payload.append(value)
    return payload


def _mesh_payload(mesh: ParsedMesh) -> dict[str, Any]:
    submeshes: list[dict[str, Any]] = []
    for submesh in getattr(mesh, "submeshes", []) or []:
        submeshes.append(
            {
                "name": str(getattr(submesh, "name", "") or ""),
                "material": str(getattr(submesh, "material", "") or ""),
                "texture": str(getattr(submesh, "texture", "") or ""),
                "vertices": _sequence_payload(getattr(submesh, "vertices", [])),
                "uvs": _sequence_payload(getattr(submesh, "uvs", [])),
                "normals": _sequence_payload(getattr(submesh, "normals", [])),
                "faces": _sequence_payload(getattr(submesh, "faces", [])),
                "bone_indices": _sequence_payload(getattr(submesh, "bone_indices", [])),
                "bone_weights": _sequence_payload(getattr(submesh, "bone_weights", [])),
                "source_vertex_map": list(getattr(submesh, "source_vertex_map", []) or []),
                "source_vertex_offsets": list(getattr(submesh, "source_vertex_offsets", []) or []),
                "source_index_offset": int(getattr(submesh, "source_index_offset", -1) or -1),
                "source_index_count": int(getattr(submesh, "source_index_count", 0) or 0),
                "source_vertex_stride": int(getattr(submesh, "source_vertex_stride", 0) or 0),
                "source_descriptor_offset": int(getattr(submesh, "source_descriptor_offset", -1) or -1),
                "source_bbox_min": list(getattr(submesh, "source_bbox_min", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
                "source_bbox_extent": list(getattr(submesh, "source_bbox_extent", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
                "source_lod_count": int(getattr(submesh, "source_lod_count", 0) or 0),
            }
        )
    return {
        "schema": "cdmw_mesh_payload_v1",
        "path": str(getattr(mesh, "path", "") or ""),
        "format": str(getattr(mesh, "format", "") or "").lower(),
        "bbox_min": list(getattr(mesh, "bbox_min", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
        "bbox_max": list(getattr(mesh, "bbox_max", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)),
        "total_vertices": int(getattr(mesh, "total_vertices", 0) or 0),
        "total_faces": int(getattr(mesh, "total_faces", 0) or 0),
        "has_uvs": bool(getattr(mesh, "has_uvs", False)),
        "has_bones": bool(getattr(mesh, "has_bones", False)),
        "submeshes": submeshes,
    }


def _topology_summary(mesh: ParsedMesh) -> dict[str, Any]:
    submeshes = getattr(mesh, "submeshes", []) or []
    return {
        "format": str(getattr(mesh, "format", "") or "").lower(),
        "submesh_count": len(submeshes),
        "vertex_count": sum(len(getattr(submesh, "vertices", []) or []) for submesh in submeshes),
        "face_count": sum(len(getattr(submesh, "faces", []) or []) for submesh in submeshes),
        "has_uvs": bool(getattr(mesh, "has_uvs", False)),
        "has_bones": bool(getattr(mesh, "has_bones", False)),
    }


def _submesh_counts_match(original: object, edited: object) -> bool:
    return (
        len(getattr(original, "vertices", []) or []) == len(getattr(edited, "vertices", []) or [])
        and len(getattr(original, "faces", []) or []) == len(getattr(edited, "faces", []) or [])
    )


def _faces_match(original: object, edited: object) -> bool:
    return list(getattr(original, "faces", []) or []) == list(getattr(edited, "faces", []) or [])


def _uvs_match(original: object, edited: object, *, eps: float = 1.0e-6) -> bool:
    original_vertices = list(getattr(original, "vertices", []) or [])
    edited_vertices = list(getattr(edited, "vertices", []) or [])
    original_uvs = list(getattr(original, "uvs", []) or [])
    edited_uvs = list(getattr(edited, "uvs", []) or [])
    original_has_uvs = len(original_uvs) == len(original_vertices)
    edited_has_uvs = len(edited_uvs) == len(edited_vertices)
    if original_has_uvs != edited_has_uvs:
        return False
    if not original_has_uvs:
        return True
    return all(
        abs(float(ou) - float(eu)) <= eps and abs(float(ov) - float(ev)) <= eps
        for (ou, ov), (eu, ev) in zip(original_uvs, edited_uvs)
    )


def _static_position_only_rebuild_safe(original: ParsedMesh, edited: ParsedMesh) -> bool:
    original_submeshes = list(getattr(original, "submeshes", []) or [])
    edited_submeshes = list(getattr(edited, "submeshes", []) or [])
    if len(original_submeshes) != len(edited_submeshes):
        return False
    for original_sm, edited_sm in zip(original_submeshes, edited_submeshes):
        if not _submesh_counts_match(original_sm, edited_sm):
            return False
        if not _faces_match(original_sm, edited_sm):
            return False
        if not _uvs_match(original_sm, edited_sm):
            return False
    return True


def _pamlod_position_only_rebuild_safe(original: ParsedMesh, edited: ParsedMesh) -> bool:
    original_levels = [list(level) for level in getattr(original, "lod_levels", []) or []]
    if not original_levels:
        return False
    target_levels = [list(level) for level in original_levels]
    edited_levels = getattr(edited, "lod_levels", None)
    if edited_levels:
        for lod_index, lod_level in enumerate(edited_levels):
            if lod_index < len(target_levels) and lod_level:
                target_levels[lod_index] = list(lod_level)
    elif getattr(edited, "submeshes", None):
        replace_index = next((index for index, lod in enumerate(target_levels) if lod), 0)
        target_levels[replace_index] = list(getattr(edited, "submeshes", []) or [])

    for original_level, target_level in zip(original_levels, target_levels):
        if len(original_level) != len(target_level):
            return False
        for original_sm, edited_sm in zip(original_level, target_level):
            if not _submesh_counts_match(original_sm, edited_sm):
                return False
            if not _faces_match(original_sm, edited_sm):
                return False
            if not _uvs_match(original_sm, edited_sm):
                return False
    return True


def _pac_in_place_rebuild_safe(original: ParsedMesh, edited: ParsedMesh) -> bool:
    original_submeshes = list(getattr(original, "submeshes", []) or [])
    edited_submeshes = list(getattr(edited, "submeshes", []) or [])
    if len(original_submeshes) != len(edited_submeshes):
        return False
    for original_sm, edited_sm in zip(original_submeshes, edited_submeshes):
        if not _submesh_counts_match(original_sm, edited_sm):
            return False
        if int(getattr(original_sm, "source_vertex_stride", 0) or 0) < 12:
            return False
        if len(getattr(original_sm, "source_vertex_offsets", []) or []) != len(getattr(original_sm, "vertices", []) or []):
            return False
        if int(getattr(original_sm, "source_descriptor_offset", -1) or -1) < 0:
            return False
        if not _faces_match(original_sm, edited_sm) and int(getattr(original_sm, "source_index_offset", -1) or -1) < 0:
            return False
    return True


def _native_rebuild_is_in_place_safe(format_name: str, mesh: ParsedMesh, original_data: bytes) -> bool:
    """Return True only for edit shapes the current native C++ rebuilders own.

    PAC native rebuild is an in-place vertex/UV/normal/index patcher. PAM and
    PAMLOD native rebuild are position-only quantized patchers. Full
    topology-changing serializers remain Python-owned until ported and proven.
    """
    try:
        if format_name == "pac":
            from cdmw.modding.mesh_parser import parse_pac

            return _pac_in_place_rebuild_safe(parse_pac(original_data, str(getattr(mesh, "path", "") or "")), mesh)
        if format_name == "pam":
            from cdmw.modding.mesh_parser import parse_pam

            return _static_position_only_rebuild_safe(parse_pam(original_data, str(getattr(mesh, "path", "") or "")), mesh)
        if format_name == "pamlod":
            from cdmw.modding.mesh_parser import parse_pamlod

            return _pamlod_position_only_rebuild_safe(parse_pamlod(original_data, str(getattr(mesh, "path", "") or "")), mesh)
    except Exception:
        return False
    return False


def _native_full_pam_rebuild_safe(mesh: ParsedMesh, original_data: bytes, layout: str) -> bool:
    if layout not in {
        "native_pam_combined",
        "native_pam_local",
        "native_pam_scan_combined",
        "native_pam_backward_scan_combined",
    }:
        return False
    try:
        from cdmw.modding.mesh_parser import parse_pam

        original_mesh = parse_pam(original_data, str(getattr(mesh, "path", "") or ""))
    except Exception:
        return False
    original_submeshes = list(getattr(original_mesh, "submeshes", []) or [])
    edited_submeshes = list(getattr(mesh, "submeshes", []) or [])
    if not original_submeshes or len(original_submeshes) != len(edited_submeshes):
        return False
    for submesh in edited_submeshes:
        if len(getattr(submesh, "vertices", []) or []) > 65535:
            return False
        if any(max(face) >= len(getattr(submesh, "vertices", []) or []) or min(face) < 0 for face in getattr(submesh, "faces", []) or []):
            return False
    return True


def _native_full_pac_rebuild_safe(mesh: ParsedMesh, original_data: bytes, layout: str) -> bool:
    if layout != "native_pac":
        return False
    try:
        from cdmw.modding.mesh_parser import parse_pac

        original_mesh = parse_pac(original_data, str(getattr(mesh, "path", "") or ""))
    except Exception:
        return False
    original_submeshes = list(getattr(original_mesh, "submeshes", []) or [])
    edited_submeshes = list(getattr(mesh, "submeshes", []) or [])
    if not original_submeshes or len(original_submeshes) != len(edited_submeshes):
        return False
    for original_sm, edited_sm in zip(original_submeshes, edited_submeshes):
        if int(getattr(original_sm, "source_vertex_stride", 0) or 0) < 12:
            return False
        if not getattr(original_sm, "source_vertex_offsets", None):
            return False
        if len(getattr(edited_sm, "vertices", []) or []) > 65535:
            return False
        for face in getattr(edited_sm, "faces", []) or []:
            if len(face) != 3:
                return False
            if min(face) < 0 or max(face) >= len(getattr(edited_sm, "vertices", []) or []):
                return False
    return True


def _native_full_pamlod_rebuild_safe(mesh: ParsedMesh, original_data: bytes, layout: str) -> bool:
    if layout != "native_pamlod_lod0":
        return False
    try:
        from cdmw.modding.mesh_importer import _inspect_pamlod_lod0_layout, _pamlod_lod0_original_parts, _split_pamlod_lod0_edit_by_entries
        from cdmw.modding.mesh_parser import parse_pamlod

        original_mesh = parse_pamlod(original_data, str(getattr(mesh, "path", "") or ""))
        pamlod_layout = _inspect_pamlod_lod0_layout(original_data)
        original_parts = _pamlod_lod0_original_parts(original_data, pamlod_layout)
    except Exception:
        return False
    if pamlod_layout.get("kind") not in {"lod0_single", "lod0"}:
        return False
    target_levels = [list(level) for level in getattr(original_mesh, "lod_levels", []) or []]
    if not target_levels:
        return False
    if getattr(mesh, "lod_levels", None):
        if not mesh.lod_levels or not mesh.lod_levels[0]:
            return False
        target_lod0 = list(mesh.lod_levels[0])
    elif getattr(mesh, "submeshes", None):
        target_lod0 = list(getattr(mesh, "submeshes", []) or [])
    else:
        return False
    try:
        split_parts = _split_pamlod_lod0_edit_by_entries(target_lod0, original_parts)
    except Exception:
        return False
    if len(split_parts) != len(original_parts):
        return False
    for submesh in split_parts:
        vertices = list(getattr(submesh, "vertices", []) or [])
        if len(vertices) > 65535:
            return False
        for face in getattr(submesh, "faces", []) or []:
            if len(face) != 3:
                return False
            if min(face) < 0 or max(face) >= len(vertices):
                return False
    return True


def _write_pac_patch_tables(mesh: ParsedMesh, temp_path: Path) -> dict[str, str]:
    submeshes_path = temp_path / "pac_submeshes.tsv"
    vertices_path = temp_path / "pac_vertices.tsv"
    faces_path = temp_path / "pac_faces.tsv"

    def field(value: object) -> str:
        return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")

    with submeshes_path.open("w", encoding="utf-8", newline="\n") as submesh_file, vertices_path.open("w", encoding="utf-8", newline="\n") as vertex_file, faces_path.open("w", encoding="utf-8", newline="\n") as face_file:
        for submesh_index, submesh in enumerate(getattr(mesh, "submeshes", []) or []):
            vertices = list(getattr(submesh, "vertices", []) or [])
            faces = list(getattr(submesh, "faces", []) or [])
            uvs = list(getattr(submesh, "uvs", []) or [])
            normals = list(getattr(submesh, "normals", []) or [])
            offsets = list(getattr(submesh, "source_vertex_offsets", []) or [])
            submesh_file.write(
                "\t".join(
                    (
                        str(submesh_index),
                        field(getattr(submesh, "name", "") or ""),
                        str(len(vertices)),
                        str(len(faces)),
                        str(int(getattr(submesh, "source_vertex_stride", 0) or 0)),
                        str(int(getattr(submesh, "source_descriptor_offset", -1) or -1)),
                        str(int(getattr(submesh, "source_index_offset", -1) or -1)),
                        str(int(getattr(submesh, "source_index_count", 0) or 0)),
                        "1" if bool(getattr(submesh, "clean_donor_shading_records", False) or getattr(mesh, "clean_donor_shading_records", False)) else "0",
                    )
                )
                + "\n"
            )
            for vertex_index, vertex in enumerate(vertices):
                uv = uvs[vertex_index] if vertex_index < len(uvs) else (0.0, 0.0)
                normal = normals[vertex_index] if vertex_index < len(normals) else (0.0, 1.0, 0.0)
                source_offset = offsets[vertex_index] if vertex_index < len(offsets) else -1
                vertex_file.write(
                    "\t".join(
                        (
                            str(submesh_index),
                            str(vertex_index),
                            repr(float(vertex[0])),
                            repr(float(vertex[1])),
                            repr(float(vertex[2])),
                            repr(float(uv[0])),
                            repr(float(uv[1])),
                            repr(float(normal[0])),
                            repr(float(normal[1])),
                            repr(float(normal[2])),
                            str(int(source_offset)),
                        )
                    )
                    + "\n"
                )
            for face_index, face in enumerate(faces):
                face_file.write(
                    "\t".join(
                        (
                            str(submesh_index),
                            str(face_index),
                            str(int(face[0])),
                            str(int(face[1])),
                            str(int(face[2])),
                        )
                    )
                    + "\n"
                )
    return {
        "pac_submeshes_tsv_path": str(submeshes_path),
        "pac_vertices_tsv_path": str(vertices_path),
        "pac_faces_tsv_path": str(faces_path),
    }


def _write_pac_full_rebuild_tables(mesh: ParsedMesh, original_data: bytes, temp_path: Path) -> dict[str, str]:
    from cdmw.modding.mesh_importer import _choose_pac_donor_indices
    from cdmw.modding.mesh_parser import parse_pac

    original_mesh = parse_pac(original_data, str(getattr(mesh, "path", "") or ""))
    if len(original_mesh.submeshes) != len(getattr(mesh, "submeshes", []) or []):
        return {}

    submeshes_path = temp_path / "pac_full_submeshes.tsv"
    vertices_path = temp_path / "pac_full_vertices.tsv"
    faces_path = temp_path / "pac_full_faces.tsv"

    def field(value: object) -> str:
        return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")

    with submeshes_path.open("w", encoding="utf-8", newline="\n") as submesh_file, vertices_path.open("w", encoding="utf-8", newline="\n") as vertex_file, faces_path.open("w", encoding="utf-8", newline="\n") as face_file:
        submesh_file.write("header\tpac_full_rebuild_v1\n")
        for submesh_index, (submesh, original_submesh) in enumerate(zip(getattr(mesh, "submeshes", []) or [], original_mesh.submeshes)):
            vertices = list(getattr(submesh, "vertices", []) or [])
            faces = list(getattr(submesh, "faces", []) or [])
            uvs = list(getattr(submesh, "uvs", []) or [])
            normals = list(getattr(submesh, "normals", []) or [])
            source_offsets = list(getattr(original_submesh, "source_vertex_offsets", []) or [])
            stride = int(getattr(original_submesh, "source_vertex_stride", 0) or 0)
            if stride < 12 or not source_offsets:
                return {}
            donor_indices = _choose_pac_donor_indices(original_submesh, submesh)
            submesh_file.write(
                "\t".join(
                    (
                        "submesh",
                        str(submesh_index),
                        field(getattr(submesh, "name", "") or getattr(original_submesh, "name", "") or ""),
                        str(len(vertices)),
                        str(len(faces)),
                        str(stride),
                        str(int(getattr(original_submesh, "source_lod_count", 0) or 0)),
                        "1" if bool(getattr(submesh, "clean_donor_shading_records", False) or getattr(mesh, "clean_donor_shading_records", False)) else "0",
                    )
                )
                + "\n"
            )
            for vertex_index, vertex in enumerate(vertices):
                donor_index = donor_indices[vertex_index] if vertex_index < len(donor_indices) else vertex_index
                donor_index = max(0, min(int(donor_index), len(source_offsets) - 1))
                source_offset = source_offsets[donor_index]
                uv = uvs[vertex_index] if vertex_index < len(uvs) else (0.0, 0.0)
                normal = normals[vertex_index] if vertex_index < len(normals) else (0.0, 1.0, 0.0)
                vertex_file.write(
                    "\t".join(
                        (
                            "vertex",
                            str(submesh_index),
                            str(vertex_index),
                            str(int(source_offset)),
                            repr(float(vertex[0])),
                            repr(float(vertex[1])),
                            repr(float(vertex[2])),
                            repr(float(uv[0])),
                            repr(float(uv[1])),
                            repr(float(normal[0])),
                            repr(float(normal[1])),
                            repr(float(normal[2])),
                        )
                    )
                    + "\n"
                )
            for face_index, face in enumerate(faces):
                face_file.write(
                    "\t".join(
                        (
                            "face",
                            str(submesh_index),
                            str(face_index),
                            str(int(face[0])),
                            str(int(face[1])),
                            str(int(face[2])),
                        )
                    )
                    + "\n"
                )
    return {
        "pac_full_submeshes_tsv_path": str(submeshes_path),
        "pac_full_vertices_tsv_path": str(vertices_path),
        "pac_full_faces_tsv_path": str(faces_path),
    }


def _write_static_quantized_patch_table(mesh: ParsedMesh, original_data: bytes, temp_path: Path, format_name: str) -> dict[str, str]:
    from cdmw.modding.mesh_importer import (
        _collect_vertex_offset_refs,
        _expand_bbox_to_vertices,
        _make_temp_mesh,
        _resolve_pam_alias_vertex,
    )
    from cdmw.modding.mesh_parser import parse_pam, parse_pamlod
    import struct

    patch_path = temp_path / f"{format_name}_static_vertices.tsv"
    if format_name == "pam":
        if len(original_data) < 0x40:
            return {}
        original_mesh = parse_pam(original_data, str(getattr(mesh, "path", "") or ""))
        if len(original_mesh.submeshes) != len(getattr(mesh, "submeshes", []) or []):
            return {}
        orig_bmin = struct.unpack_from("<fff", original_data, 0x14)
        orig_bmax = struct.unpack_from("<fff", original_data, 0x20)
        all_vertices = [vertex for submesh in getattr(mesh, "submeshes", []) or [] for vertex in getattr(submesh, "vertices", []) or []]
        bmin, bmax = _expand_bbox_to_vertices(orig_bmin, orig_bmax, all_vertices)
        geom_off = struct.unpack_from("<I", original_data, 0x3C)[0]
        offset_refs = _collect_vertex_offset_refs(original_data, original_mesh, mesh, orig_bmin, orig_bmax, search_start=geom_off)
        allow_average_conflicts = False
        header_min_offset = 0x14
        header_max_offset = 0x20
    elif format_name == "pamlod":
        if len(original_data) < 0x20:
            return {}
        original_mesh = parse_pamlod(original_data, str(getattr(mesh, "path", "") or ""))
        if not original_mesh.lod_levels:
            return {}
        orig_bmin = struct.unpack_from("<fff", original_data, 0x10)
        orig_bmax = struct.unpack_from("<fff", original_data, 0x1C)
        target_lod_levels = [list(level) for level in original_mesh.lod_levels]
        if getattr(mesh, "lod_levels", None):
            for lod_index, lod_level in enumerate(getattr(mesh, "lod_levels", []) or []):
                if lod_index < len(target_lod_levels) and lod_level:
                    target_lod_levels[lod_index] = list(lod_level)
        elif getattr(mesh, "submeshes", None):
            replace_index = next((index for index, lod in enumerate(target_lod_levels) if lod), 0)
            target_lod_levels[replace_index] = list(getattr(mesh, "submeshes", []) or [])
        all_vertices = [vertex for lod in target_lod_levels for submesh in lod for vertex in getattr(submesh, "vertices", []) or []]
        bmin, bmax = _expand_bbox_to_vertices(orig_bmin, orig_bmax, all_vertices)
        offset_refs: dict[int, list[tuple[tuple[float, float, float], tuple[float, float, float], int, int]]] = {}
        for lod_index, original_level in enumerate(original_mesh.lod_levels):
            if lod_index >= len(target_lod_levels):
                break
            new_level = target_lod_levels[lod_index]
            if not original_level or not new_level:
                continue
            level_original_mesh = _make_temp_mesh(original_mesh.path, "pamlod", original_level)
            level_new_mesh = _make_temp_mesh(str(getattr(mesh, "path", "") or original_mesh.path), "pamlod", new_level)
            level_refs = _collect_vertex_offset_refs(original_data, level_original_mesh, level_new_mesh, orig_bmin, orig_bmax, search_start=0)
            for byte_offset, refs in level_refs.items():
                offset_refs.setdefault(byte_offset, []).extend(refs)
        allow_average_conflicts = True
        header_min_offset = 0x10
        header_max_offset = 0x1C
    else:
        return {}

    with patch_path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(
            "\t".join(
                (
                    "bbox",
                    repr(float(bmin[0])),
                    repr(float(bmin[1])),
                    repr(float(bmin[2])),
                    repr(float(bmax[0])),
                    repr(float(bmax[1])),
                    repr(float(bmax[2])),
                    str(header_min_offset),
                    str(header_max_offset),
                )
            )
            + "\n"
        )
        for byte_offset in sorted(offset_refs):
            refs = offset_refs[byte_offset]
            if byte_offset < 0 or byte_offset + 6 > len(original_data):
                continue
            x, y, z = _resolve_pam_alias_vertex(byte_offset, refs, allow_average_conflicts=allow_average_conflicts)
            stream.write(
                "\t".join(
                    (
                        "vertex",
                        str(int(byte_offset)),
                        repr(float(x)),
                        repr(float(y)),
                        repr(float(z)),
                    )
                )
                + "\n"
            )
    return {"static_quantized_patch_tsv_path": str(patch_path)}


def _write_static_full_rebuild_table(mesh: ParsedMesh, original_data: bytes, temp_path: Path) -> dict[str, str]:
    from cdmw.modding.mesh_importer import (
        _choose_static_donor_indices,
        _compute_bbox,
        _inspect_pam_layout,
    )
    from cdmw.modding.mesh_parser import parse_pam

    def field(value: object) -> str:
        return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")

    def tight_bbox(vertices: list[tuple[float, float, float]]) -> tuple[float, float, float, float, float, float]:
        if not vertices:
            return (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        xs, ys, zs = zip(*vertices)
        return (float(min(xs)), float(min(ys)), float(min(zs)), float(max(xs)), float(max(ys)), float(max(zs)))

    if not original_data or len(original_data) < 0x40:
        return {}
    original_mesh = parse_pam(original_data, str(getattr(mesh, "path", "") or ""))
    if len(original_mesh.submeshes) != len(getattr(mesh, "submeshes", []) or []):
        return {}
    layout = _inspect_pam_layout(original_data)
    kind = str(layout.get("kind") or "")
    if kind not in {"combined", "local", "scan_combined", "backward_scan_combined"}:
        return {}
    all_vertices = [vertex for submesh in getattr(mesh, "submeshes", []) or [] for vertex in getattr(submesh, "vertices", []) or []]
    bmin, bmax = _compute_bbox(all_vertices)
    table_path = temp_path / "pam_full_rebuild.tsv"
    with table_path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(
            "\t".join(
                (
                    "header",
                    kind,
                    str(int(layout.get("geom_off", 0) or 0)),
                    str(int(layout.get("old_geom_end", 0) or 0)),
                    str(int(layout.get("stride", 0) or 0)),
                    str(int(layout.get("scan_start", -1) or -1)),
                    str(int(layout.get("idx_base", -1) or -1)),
                    str(int(layout.get("vertex_end", -1) or -1)),
                    repr(float(bmin[0])),
                    repr(float(bmin[1])),
                    repr(float(bmin[2])),
                    repr(float(bmax[0])),
                    repr(float(bmax[1])),
                    repr(float(bmax[2])),
                )
            )
            + "\n"
        )
        entries = list(layout.get("entries") or [])
        for submesh_index, (submesh, original_submesh, entry) in enumerate(zip(getattr(mesh, "submeshes", []) or [], original_mesh.submeshes, entries)):
            stride = int(entry.get("stride", layout.get("stride", 0)) or 0)
            if stride <= 0:
                return {}
            if kind == "scan_combined":
                orig_vertex_base = int(layout.get("scan_start", 0) or 0) + int(entry.get("ve", 0) or 0) * stride
            elif kind == "combined" or kind == "backward_scan_combined":
                orig_vertex_base = int(layout.get("geom_off", 0) or 0) + int(entry.get("ve", 0) or 0) * stride
            else:
                orig_vertex_base = int(layout.get("geom_off", 0) or 0) + int(entry.get("ve", 0) or 0)
            vertices = list(getattr(submesh, "vertices", []) or [])
            faces = list(getattr(submesh, "faces", []) or [])
            uvs = list(getattr(submesh, "uvs", []) or [])
            old_bbox = tight_bbox(list(getattr(original_submesh, "vertices", []) or []))
            new_bbox = tight_bbox(vertices)
            stream.write(
                "\t".join(
                    (
                        "submesh",
                        str(submesh_index),
                        str(int(entry.get("desc_off", 0) or 0)),
                        str(len(vertices)),
                        str(len(faces)),
                        str(stride),
                        str(orig_vertex_base),
                        str(int(entry.get("nv", 0) or 0)),
                        field(getattr(original_submesh, "texture", "") or ""),
                        field(getattr(original_submesh, "material", "") or ""),
                        str(len(getattr(original_submesh, "vertices", []) or [])),
                        str(len(getattr(original_submesh, "faces", []) or []) * 3),
                        *(repr(float(value)) for value in old_bbox),
                        *(repr(float(value)) for value in new_bbox),
                    )
                )
                + "\n"
            )
            donor_indices = _choose_static_donor_indices(original_submesh, submesh)
            for vertex_index, vertex in enumerate(vertices):
                donor_index = donor_indices[vertex_index] if vertex_index < len(donor_indices) else vertex_index
                donor_index = max(0, min(int(donor_index), max(0, int(entry.get("nv", 0) or 0) - 1)))
                source_offset = orig_vertex_base + donor_index * stride
                uv = uvs[vertex_index] if vertex_index < len(uvs) else None
                stream.write(
                    "\t".join(
                        (
                            "vertex",
                            str(submesh_index),
                            str(vertex_index),
                            str(source_offset),
                            repr(float(vertex[0])),
                            repr(float(vertex[1])),
                            repr(float(vertex[2])),
                            "1" if uv is not None else "0",
                            repr(float(uv[0])) if uv is not None else "0.0",
                            repr(float(uv[1])) if uv is not None else "0.0",
                        )
                    )
                    + "\n"
                )
            for face_index, face in enumerate(faces):
                stream.write(
                    "\t".join(
                        (
                            "face",
                            str(submesh_index),
                            str(face_index),
                            str(int(face[0])),
                            str(int(face[1])),
                            str(int(face[2])),
                        )
                    )
                    + "\n"
                )
    return {"static_full_rebuild_tsv_path": str(table_path)}


def _write_pamlod_full_rebuild_table(mesh: ParsedMesh, original_data: bytes, temp_path: Path) -> dict[str, str]:
    from cdmw.modding.mesh_importer import (
        _choose_static_donor_indices,
        _compute_bbox,
        _inspect_pamlod_lod0_layout,
        _pamlod_lod0_original_parts,
        _split_pamlod_lod0_edit_by_entries,
    )
    from cdmw.modding.mesh_parser import parse_pamlod

    original_mesh = parse_pamlod(original_data, str(getattr(mesh, "path", "") or ""))
    layout = _inspect_pamlod_lod0_layout(original_data)
    if layout.get("kind") not in {"lod0_single", "lod0"} or not original_mesh.lod_levels:
        return {}
    if getattr(mesh, "lod_levels", None) and mesh.lod_levels and mesh.lod_levels[0]:
        lod0_submeshes = list(mesh.lod_levels[0])
    else:
        lod0_submeshes = list(getattr(mesh, "submeshes", []) or [])
    original_parts = _pamlod_lod0_original_parts(original_data, layout)
    try:
        rebuilt_parts = _split_pamlod_lod0_edit_by_entries(lod0_submeshes, original_parts)
    except Exception:
        return {}
    if len(rebuilt_parts) != len(original_parts):
        return {}
    all_vertices = [
        vertex
        for lod_level in original_mesh.lod_levels[1:]
        for level_submesh in lod_level
        for vertex in getattr(level_submesh, "vertices", []) or []
    ] + [vertex for part in rebuilt_parts for vertex in getattr(part, "vertices", []) or []]
    bmin, bmax = _compute_bbox(all_vertices)
    entries = list(layout.get("entries") or [layout["entry"]])
    stride = int(layout["stride"])
    table_path = temp_path / "pamlod_full_rebuild.tsv"
    with table_path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(
            "\t".join(
                (
                    "header",
                    "pamlod_lod0",
                    str(int(layout["geom_off"])),
                    str(int(layout["old_lod0_end"])),
                    str(stride),
                    str(int(layout["vertex_base"])),
                    repr(float(bmin[0])),
                    repr(float(bmin[1])),
                    repr(float(bmin[2])),
                    repr(float(bmax[0])),
                    repr(float(bmax[1])),
                    repr(float(bmax[2])),
                )
            )
            + "\n"
        )
        for submesh_index, (entry, original_submesh, submesh) in enumerate(zip(entries, original_parts, rebuilt_parts)):
            vertices = list(getattr(submesh, "vertices", []) or [])
            faces = list(getattr(submesh, "faces", []) or [])
            uvs = list(getattr(submesh, "uvs", []) or [])
            stream.write(
                "\t".join(
                    (
                        "submesh",
                        str(submesh_index),
                        str(int(entry["desc_off"])),
                        str(len(vertices)),
                        str(len(faces)),
                        str(int(entry["nv"])),
                    )
                )
                + "\n"
            )
            donor_indices = _choose_static_donor_indices(original_submesh, submesh)
            source_offsets = list(getattr(original_submesh, "source_vertex_offsets", []) or [])
            for vertex_index, vertex in enumerate(vertices):
                donor_index = donor_indices[vertex_index] if vertex_index < len(donor_indices) else vertex_index
                donor_index = max(0, min(int(donor_index), max(0, len(source_offsets) - 1)))
                source_offset = source_offsets[donor_index] if source_offsets else int(layout["vertex_base"])
                uv = uvs[vertex_index] if vertex_index < len(uvs) else None
                stream.write(
                    "\t".join(
                        (
                            "vertex",
                            str(submesh_index),
                            str(vertex_index),
                            str(source_offset),
                            repr(float(vertex[0])),
                            repr(float(vertex[1])),
                            repr(float(vertex[2])),
                            "1" if uv is not None else "0",
                            repr(float(uv[0])) if uv is not None else "0.0",
                            repr(float(uv[1])) if uv is not None else "0.0",
                        )
                    )
                    + "\n"
                )
            for face_index, face in enumerate(faces):
                stream.write(
                    "\t".join(
                        (
                            "face",
                            str(submesh_index),
                            str(face_index),
                            str(int(face[0])),
                            str(int(face[1])),
                            str(int(face[2])),
                        )
                    )
                    + "\n"
                )
    return {"pamlod_full_rebuild_tsv_path": str(table_path)}


def build_mesh_native(mesh: ParsedMesh, original_data: bytes, *, timeout_seconds: float = 30.0) -> Optional[bytes]:
    binary = find_native_preview_core_binary()
    if binary is None:
        return None
    format_name = str(getattr(mesh, "format", "") or "").lower()
    full_rebuild = False
    try:
        from cdmw.core.mesh_native_parity import mesh_native_parity_manifest_path, native_mesh_full_rebuild_parity_enabled, native_mesh_rebuild_parity_enabled

        if mesh_native_parity_manifest_path() is None:
            return None
        audit = audit_mesh_native(original_data, str(getattr(mesh, "path", "") or ""), timeout_seconds=min(timeout_seconds, 10.0))
        if audit.get("status") != "ok":
            return None
        layout = str(audit.get("layout") or audit.get("parser") or "")
        in_place_safe = _native_rebuild_is_in_place_safe(format_name, mesh, original_data)
        if in_place_safe:
            if not native_mesh_rebuild_parity_enabled(format_name, layout):
                return None
        elif format_name == "pam" and _native_full_pam_rebuild_safe(mesh, original_data, layout):
            if not native_mesh_full_rebuild_parity_enabled(format_name, layout):
                return None
            full_rebuild = True
        elif format_name == "pac" and _native_full_pac_rebuild_safe(mesh, original_data, layout):
            if not native_mesh_full_rebuild_parity_enabled(format_name, layout):
                return None
            full_rebuild = True
        elif format_name == "pamlod" and _native_full_pamlod_rebuild_safe(mesh, original_data, layout):
            if not native_mesh_full_rebuild_parity_enabled(format_name, layout):
                return None
            full_rebuild = True
        else:
            return None
    except Exception:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="cdmw_mesh_native_rebuild_") as temp_dir:
            temp_path = Path(temp_dir)
            original_path = temp_path / "original.bin"
            mesh_payload_path = temp_path / "edited_mesh.json"
            job_path = temp_path / "mesh_rebuild_job.json"
            output_path = temp_path / "rebuilt.bin"
            report_path = temp_path / "mesh_rebuild_report.json"
            original_path.write_bytes(bytes(original_data))
            mesh_payload_path.write_text(json.dumps(_mesh_payload(mesh), indent=2), encoding="utf-8")
            if full_rebuild:
                if format_name == "pac":
                    patch_paths = _write_pac_full_rebuild_tables(mesh, original_data, temp_path)
                elif format_name == "pamlod":
                    patch_paths = _write_pamlod_full_rebuild_table(mesh, original_data, temp_path)
                else:
                    patch_paths = _write_static_full_rebuild_table(mesh, original_data, temp_path)
                if not patch_paths:
                    return None
            else:
                patch_paths = _write_pac_patch_tables(mesh, temp_path) if format_name == "pac" else {}
            if not full_rebuild and format_name in {"pam", "pamlod"}:
                patch_paths = _write_static_quantized_patch_table(mesh, original_data, temp_path, format_name)
                if not patch_paths:
                    return None
            job_path.write_text(
                json.dumps(
                    {
                        "schema": "cdmw_mesh_rebuild_job_v1",
                        "original_binary_path": str(original_path),
                        "edited_mesh_json_path": str(mesh_payload_path),
                        **patch_paths,
                        "target_format": format_name,
                        "source_filename": str(getattr(mesh, "path", "") or ""),
                        "layout": layout,
                        "rebuild_mode": "full" if full_rebuild else "in_place",
                        "expected_original_topology": _topology_summary(mesh),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    str(binary),
                    "mesh-rebuild-job",
                    str(job_path),
                    str(output_path),
                    str(report_path),
                    *_native_diagnostic_args(),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=max(1.0, float(timeout_seconds)),
                check=False,
                **hidden_subprocess_kwargs(),
            )
            if completed.returncode != 0 or not report_path.is_file():
                return None
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(report, dict):
                return None
            if (
                report.get("status") != "ok"
                or report.get("supported") is not True
                or report.get("rebuild_supported") is not True
                or report.get("parity_ready") is not True
            ):
                return None
            if not output_path.is_file():
                return None
            data = output_path.read_bytes()
            try:
                if int(report.get("bytes_written", -1)) != len(data):
                    return None
            except (TypeError, ValueError):
                return None
            return data
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return None


__all__ = [
    "NATIVE_MESH_BACKEND_ID",
    "audit_mesh_native",
    "build_mesh_native",
    "_native_rebuild_is_in_place_safe",
    "parse_mesh_native",
]
