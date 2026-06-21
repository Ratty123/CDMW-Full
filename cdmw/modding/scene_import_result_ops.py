"""Scene import result data and mesh result operations."""

from __future__ import annotations

import copy
import math
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .mesh_parser import ParsedMesh, SubMesh, _compute_smooth_normals
from .scene_geometry_utils import _bbox, _dedupe_paths
from .scene_material_audit import ExternalModelAudit, ImportedMaterialBinding


@dataclass(slots=True)
class SceneImportResult:
    mesh: ParsedMesh
    diagnostics: tuple[str, ...] = ()
    discovered_texture_files: tuple[Path, ...] = ()
    extracted_embedded_files: tuple[Path, ...] = ()
    discovered_supplemental_files: tuple[Path, ...] = ()
    material_bindings: tuple[ImportedMaterialBinding, ...] = ()
    external_audit: Optional[ExternalModelAudit] = None


@dataclass(slots=True, frozen=True)
class SceneMeshAppendResult:
    source_indices: tuple[int, ...]
    texture_files: tuple[Path, ...] = ()
    supplemental_files: tuple[Path, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class SceneMeshQualityReductionReport:
    original_vertices: int
    original_faces: int
    reduced_vertices: int
    reduced_faces: int
    reduced_submeshes: int
    max_faces_per_submesh: int
    max_vertices_per_submesh: int


def _scene_result_context(scene_result: SceneImportResult) -> dict[str, object]:
    return {
        "material_bindings": tuple(getattr(scene_result, "material_bindings", ()) or ()),
        "external_audit": getattr(scene_result, "external_audit", None),
    }


def refresh_parsed_mesh_totals(mesh: ParsedMesh) -> None:
    vertices = [vertex for submesh in mesh.submeshes for vertex in submesh.vertices]
    mesh.bbox_min, mesh.bbox_max = _bbox(vertices)
    mesh.total_vertices = sum(len(submesh.vertices) for submesh in mesh.submeshes)
    mesh.total_faces = sum(len(submesh.faces) for submesh in mesh.submeshes)
    mesh.has_uvs = any(bool(submesh.uvs) for submesh in mesh.submeshes)
    mesh.has_bones = any(bool(getattr(submesh, "bone_indices", None) or getattr(submesh, "bone_weights", None)) for submesh in mesh.submeshes)


def _decimate_submesh_for_import_quality(
    submesh: SubMesh,
    *,
    max_faces: int,
    max_vertices: int,
) -> tuple[SubMesh, bool]:
    faces = list(getattr(submesh, "faces", None) or [])
    vertices = list(getattr(submesh, "vertices", None) or [])
    if not faces or not vertices:
        return copy.deepcopy(submesh), False
    if len(faces) <= max_faces and len(vertices) <= max_vertices:
        return copy.deepcopy(submesh), False

    face_budget = max(1, int(max_faces))
    vertex_budget = max(3, int(max_vertices))
    xs = [float(vertex[0]) for vertex in vertices]
    ys = [float(vertex[1]) for vertex in vertices]
    zs = [float(vertex[2]) for vertex in vertices]
    bmin = (min(xs), min(ys), min(zs))
    bmax = (max(xs), max(ys), max(zs))
    extent = (
        max(bmax[0] - bmin[0], 1e-8),
        max(bmax[1] - bmin[1], 1e-8),
        max(bmax[2] - bmin[2], 1e-8),
    )
    normals = list(getattr(submesh, "normals", None) or [])
    uvs = list(getattr(submesh, "uvs", None) or [])
    has_normals = len(normals) == len(vertices)
    has_uvs = len(uvs) == len(vertices)

    def _triangle_area(face: tuple[int, int, int], reduced_vertices: list[tuple[float, float, float]]) -> float:
        a, b, c = face
        p0, p1, p2 = reduced_vertices[a], reduced_vertices[b], reduced_vertices[c]
        ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
        cx = (uy * vz) - (uz * vy)
        cy = (uz * vx) - (ux * vz)
        cz = (ux * vy) - (uy * vx)
        return (cx * cx + cy * cy + cz * cz) ** 0.5

    def _cluster(decisions: int) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]], list[tuple[float, float, float]], list[tuple[float, float]], list[int]]:
        divisions = max(1, int(decisions))
        cluster_order: list[tuple[int, int, int]] = []
        cluster_accum: dict[tuple[int, int, int], list[float]] = {}
        source_to_cluster: list[tuple[int, int, int]] = []
        scale = max(1, divisions - 1)
        for vertex_index, vertex in enumerate(vertices):
            key = (
                max(0, min(scale, int(((float(vertex[0]) - bmin[0]) / extent[0]) * scale))),
                max(0, min(scale, int(((float(vertex[1]) - bmin[1]) / extent[1]) * scale))),
                max(0, min(scale, int(((float(vertex[2]) - bmin[2]) / extent[2]) * scale))),
            )
            source_to_cluster.append(key)
            accum = cluster_accum.get(key)
            if accum is None:
                accum = [0.0] * 9
                cluster_accum[key] = accum
                cluster_order.append(key)
            accum[0] += 1.0
            accum[1] += float(vertex[0])
            accum[2] += float(vertex[1])
            accum[3] += float(vertex[2])
            if has_normals:
                normal = normals[vertex_index]
                accum[4] += float(normal[0])
                accum[5] += float(normal[1])
                accum[6] += float(normal[2])
            if has_uvs:
                uv = uvs[vertex_index]
                accum[7] += float(uv[0])
                accum[8] += float(uv[1])

        cluster_to_index = {key: index for index, key in enumerate(cluster_order)}
        reduced_vertices: list[tuple[float, float, float]] = []
        reduced_normals: list[tuple[float, float, float]] = []
        reduced_uvs: list[tuple[float, float]] = []
        for key in cluster_order:
            count, sx, sy, sz, nx, ny, nz, su, sv = cluster_accum[key]
            inv = 1.0 / max(count, 1.0)
            reduced_vertices.append((sx * inv, sy * inv, sz * inv))
            if has_normals:
                length = max((nx * nx + ny * ny + nz * nz) ** 0.5, 1e-8)
                reduced_normals.append((nx / length, ny / length, nz / length))
            if has_uvs:
                reduced_uvs.append((su * inv, sv * inv))

        reduced_faces: list[tuple[int, int, int]] = []
        seen_faces: set[tuple[int, int, int]] = set()
        for face in faces:
            remapped: list[int] = []
            for raw_index in face[:3]:
                try:
                    source_index = int(raw_index)
                except (TypeError, ValueError):
                    remapped = []
                    break
                if source_index < 0 or source_index >= len(source_to_cluster):
                    remapped = []
                    break
                remapped.append(cluster_to_index[source_to_cluster[source_index]])
            if len(remapped) != 3 or len(set(remapped)) != 3:
                continue
            normalized_face = tuple(remapped)
            dedupe_key = tuple(sorted(normalized_face))
            if dedupe_key in seen_faces:
                continue
            seen_faces.add(dedupe_key)
            reduced_faces.append(normalized_face)  # type: ignore[arg-type]
        if len(reduced_faces) > face_budget:
            ranked = sorted(
                enumerate(reduced_faces),
                key=lambda item: _triangle_area(item[1], reduced_vertices),
                reverse=True,
            )
            keep_indices = {index for index, _face in ranked[:face_budget]}
            reduced_faces = [face for index, face in enumerate(reduced_faces) if index in keep_indices]
        used_vertices = sorted({index for face in reduced_faces for index in face})
        if not used_vertices:
            return [], [], [], [], []
        remap = {old: new for new, old in enumerate(used_vertices)}
        compact_vertices = [reduced_vertices[index] for index in used_vertices]
        compact_normals = [reduced_normals[index] for index in used_vertices] if has_normals else []
        compact_uvs = [reduced_uvs[index] for index in used_vertices] if has_uvs else []
        compact_faces = [(remap[a], remap[b], remap[c]) for a, b, c in reduced_faces]
        return compact_vertices, compact_faces, compact_normals, compact_uvs, used_vertices

    divisions = max(2, int(math.ceil(vertex_budget ** (1.0 / 3.0))) * 2)
    best: tuple[list[tuple[float, float, float]], list[tuple[int, int, int]], list[tuple[float, float, float]], list[tuple[float, float]], list[int]] | None = None
    for _attempt in range(18):
        candidate = _cluster(divisions)
        candidate_vertices, candidate_faces, _candidate_normals, _candidate_uvs, _candidate_used = candidate
        if candidate_vertices and candidate_faces:
            best = candidate
            if len(candidate_vertices) <= vertex_budget and len(candidate_faces) <= face_budget:
                break
        if divisions <= 1:
            break
        divisions = max(1, int(divisions * 0.75))

    if best is None or not best[0] or not best[1]:
        return copy.deepcopy(submesh), False
    preview_vertices, sampled_faces, reduced_normals, reduced_uvs, used_cluster_indices = best
    reduced = copy.deepcopy(submesh)
    reduced.vertices = preview_vertices
    reduced.faces = sampled_faces
    reduced.uvs = reduced_uvs if len(reduced_uvs) == len(preview_vertices) else []
    reduced.normals = reduced_normals if len(reduced_normals) == len(preview_vertices) else []
    if not reduced.normals or len(reduced.normals) != len(reduced.vertices):
        reduced.normals = _compute_smooth_normals(reduced.vertices, reduced.faces)
    reduced.bone_indices = []
    reduced.bone_weights = []
    reduced.source_vertex_map = [int(index) for index in used_cluster_indices]
    reduced.source_vertex_offsets = []
    reduced.source_index_offset = -1
    reduced.source_index_count = len(reduced.faces) * 3
    reduced.vertex_count = len(reduced.vertices)
    reduced.face_count = len(reduced.faces)
    return reduced, True


def reduce_scene_import_result_quality(
    scene_result: SceneImportResult,
    *,
    max_faces_per_submesh: int = 45_000,
    max_vertices_per_submesh: int = 55_000,
) -> tuple[SceneImportResult, SceneMeshQualityReductionReport]:
    """Return a session-only lower-density copy of an imported scene mesh."""
    if not isinstance(scene_result, SceneImportResult):
        raise TypeError("reduce_scene_import_result_quality requires a SceneImportResult.")
    source_mesh = scene_result.mesh
    reduced_mesh = copy.deepcopy(source_mesh)
    reduced_submeshes: list[SubMesh] = []
    changed_count = 0
    for submesh in getattr(source_mesh, "submeshes", ()) or ():
        reduced_submesh, changed = _decimate_submesh_for_import_quality(
            submesh,
            max_faces=max(1, int(max_faces_per_submesh)),
            max_vertices=max(1, int(max_vertices_per_submesh)),
        )
        reduced_submeshes.append(reduced_submesh)
        if changed:
            changed_count += 1
    reduced_mesh.submeshes = reduced_submeshes
    refresh_parsed_mesh_totals(reduced_mesh)
    report = SceneMeshQualityReductionReport(
        original_vertices=sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in getattr(source_mesh, "submeshes", ()) or ()),
        original_faces=sum(len(getattr(submesh, "faces", ()) or ()) for submesh in getattr(source_mesh, "submeshes", ()) or ()),
        reduced_vertices=sum(len(getattr(submesh, "vertices", ()) or ()) for submesh in reduced_submeshes),
        reduced_faces=sum(len(getattr(submesh, "faces", ()) or ()) for submesh in reduced_submeshes),
        reduced_submeshes=changed_count,
        max_faces_per_submesh=max(1, int(max_faces_per_submesh)),
        max_vertices_per_submesh=max(1, int(max_vertices_per_submesh)),
    )
    diagnostics = tuple(scene_result.diagnostics or ())
    if changed_count:
        diagnostics += (
            "Session-only mesh quality reduction: "
            f"{report.original_vertices:,} vertices/{report.original_faces:,} faces -> "
            f"{report.reduced_vertices:,} vertices/{report.reduced_faces:,} faces.",
        )
    return (
        SceneImportResult(
            mesh=reduced_mesh,
            diagnostics=diagnostics,
            discovered_texture_files=tuple(scene_result.discovered_texture_files or ()),
            extracted_embedded_files=tuple(scene_result.extracted_embedded_files or ()),
            discovered_supplemental_files=tuple(scene_result.discovered_supplemental_files or ()),
            **_scene_result_context(scene_result),
        ),
        report,
    )


def flatten_scene_import_result_parts(
    scene_result: SceneImportResult,
    *,
    part_name: str = "",
    material_name: str = "",
) -> SceneImportResult:
    """Return a session-only copy whose appendable scene submeshes are one source part."""
    if not isinstance(scene_result, SceneImportResult):
        raise TypeError("flatten_scene_import_result_parts requires a SceneImportResult.")
    source_mesh = scene_result.mesh
    imported_submeshes = [
        submesh
        for submesh in tuple(getattr(source_mesh, "submeshes", ()) or ())
        if getattr(submesh, "vertices", None) and getattr(submesh, "faces", None)
    ]
    if len(imported_submeshes) <= 1:
        return SceneImportResult(
            mesh=copy.deepcopy(source_mesh),
            diagnostics=tuple(scene_result.diagnostics or ()),
            discovered_texture_files=tuple(scene_result.discovered_texture_files or ()),
            extracted_embedded_files=tuple(scene_result.extracted_embedded_files or ()),
            discovered_supplemental_files=tuple(scene_result.discovered_supplemental_files or ()),
            **_scene_result_context(scene_result),
        )

    def unique_values(attribute_name: str) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for submesh in imported_submeshes:
            value = str(getattr(submesh, attribute_name, "") or "").strip()
            key = value.lower()
            if value and key not in seen:
                seen.add(key)
                result.append(value)
        return result

    mesh_path = Path(str(getattr(source_mesh, "path", "") or ""))
    fallback_name = str(part_name or mesh_path.stem or "flattened_part").strip() or "flattened_part"
    material_values = unique_values("material")
    texture_values = unique_values("texture")
    flattened_material = str(material_name or "").strip()
    if not flattened_material:
        flattened_material = material_values[0] if len(material_values) == 1 else fallback_name
    flattened_texture = texture_values[0] if len(texture_values) == 1 else ""
    combined = SubMesh(name=fallback_name, material=flattened_material, texture=flattened_texture)

    wants_uvs = any(len(getattr(submesh, "uvs", ()) or ()) == len(getattr(submesh, "vertices", ()) or ()) for submesh in imported_submeshes)
    can_copy_normals = all(
        len(getattr(submesh, "normals", ()) or ()) == len(getattr(submesh, "vertices", ()) or ())
        for submesh in imported_submeshes
    )
    can_copy_bones = all(
        len(getattr(submesh, "bone_indices", ()) or ()) == len(getattr(submesh, "vertices", ()) or ())
        and len(getattr(submesh, "bone_weights", ()) or ()) == len(getattr(submesh, "vertices", ()) or ())
        for submesh in imported_submeshes
    )
    skipped_faces = 0
    for submesh in imported_submeshes:
        vertices = list(getattr(submesh, "vertices", ()) or ())
        base_index = len(combined.vertices)
        combined.vertices.extend(copy.deepcopy(vertices))
        uvs = list(getattr(submesh, "uvs", ()) or ())
        if wants_uvs:
            if len(uvs) == len(vertices):
                combined.uvs.extend(copy.deepcopy(uvs))
            else:
                combined.uvs.extend([(0.0, 0.0)] * len(vertices))
        if can_copy_normals:
            combined.normals.extend(copy.deepcopy(list(getattr(submesh, "normals", ()) or ())))
        if can_copy_bones:
            combined.bone_indices.extend(copy.deepcopy(list(getattr(submesh, "bone_indices", ()) or ())))
            combined.bone_weights.extend(copy.deepcopy(list(getattr(submesh, "bone_weights", ()) or ())))
        for face in getattr(submesh, "faces", ()) or ():
            if len(face) != 3:
                skipped_faces += 1
                continue
            try:
                a, b, c = int(face[0]), int(face[1]), int(face[2])
            except (TypeError, ValueError):
                skipped_faces += 1
                continue
            if min(a, b, c) < 0 or max(a, b, c) >= len(vertices):
                skipped_faces += 1
                continue
            combined.faces.append((a + base_index, b + base_index, c + base_index))

    if not combined.vertices or not combined.faces:
        raise ValueError("Flattened mesh did not contain triangle geometry.")
    if not can_copy_normals:
        combined.normals = _compute_smooth_normals(combined.vertices, combined.faces)
    combined.vertex_count = len(combined.vertices)
    combined.face_count = len(combined.faces)
    combined.source_vertex_offsets = []
    combined.source_vertex_map = []
    combined.source_index_offset = -1
    combined.source_index_count = len(combined.faces) * 3

    flattened_mesh = copy.deepcopy(source_mesh)
    flattened_mesh.submeshes = [combined]
    refresh_parsed_mesh_totals(flattened_mesh)
    diagnostics = list(scene_result.diagnostics or ())
    diagnostics.append(
        f"Flattened {len(imported_submeshes):,} imported part(s) into one source part "
        f"({len(combined.vertices):,} vertices, {len(combined.faces):,} faces)."
    )
    if len(material_values) > 1:
        diagnostics.append(
            "Flattening collapsed multiple source materials into one in-session material. "
            "Use a baked/atlased texture set or route one material in the Textures tab."
        )
    if skipped_faces:
        diagnostics.append(f"Skipped {skipped_faces:,} invalid face(s) while flattening imported parts.")
    return SceneImportResult(
        mesh=flattened_mesh,
        diagnostics=tuple(diagnostics),
        discovered_texture_files=tuple(scene_result.discovered_texture_files or ()),
        extracted_embedded_files=tuple(scene_result.extracted_embedded_files or ()),
        discovered_supplemental_files=tuple(scene_result.discovered_supplemental_files or ()),
        **_scene_result_context(scene_result),
    )


def group_scene_import_result_parts_by_material(
    scene_result: SceneImportResult,
    *,
    part_name: str = "",
) -> SceneImportResult:
    """Return a session-only copy with imported parts flattened per material."""
    if not isinstance(scene_result, SceneImportResult):
        raise TypeError("group_scene_import_result_parts_by_material requires a SceneImportResult.")
    source_mesh = scene_result.mesh
    imported_submeshes = [
        submesh
        for submesh in tuple(getattr(source_mesh, "submeshes", ()) or ())
        if getattr(submesh, "vertices", None) and getattr(submesh, "faces", None)
    ]
    if len(imported_submeshes) <= 1:
        return SceneImportResult(
            mesh=copy.deepcopy(source_mesh),
            diagnostics=tuple(scene_result.diagnostics or ()),
            discovered_texture_files=tuple(scene_result.discovered_texture_files or ()),
            extracted_embedded_files=tuple(scene_result.extracted_embedded_files or ()),
            discovered_supplemental_files=tuple(scene_result.discovered_supplemental_files or ()),
            **_scene_result_context(scene_result),
        )

    grouped: "OrderedDict[str, list[SubMesh]]" = OrderedDict()
    display_names: dict[str, str] = {}
    for submesh in imported_submeshes:
        material = str(getattr(submesh, "material", "") or getattr(submesh, "texture", "") or getattr(submesh, "name", "") or "").strip()
        key = material.lower() or f"group_{len(grouped)}"
        grouped.setdefault(key, []).append(submesh)
        display_names.setdefault(key, material or f"group_{len(grouped)}")

    mesh_path = Path(str(getattr(source_mesh, "path", "") or ""))
    base_name = str(part_name or mesh_path.stem or "grouped_part").strip() or "grouped_part"
    grouped_submeshes: list[SubMesh] = []
    diagnostics = list(scene_result.diagnostics or ())
    for group_key, submeshes in grouped.items():
        material = display_names.get(group_key, group_key) or group_key
        temp_mesh = copy.deepcopy(source_mesh)
        temp_mesh.submeshes = [copy.deepcopy(submesh) for submesh in submeshes]
        refresh_parsed_mesh_totals(temp_mesh)
        temp_result = SceneImportResult(
            mesh=temp_mesh,
            diagnostics=(),
            discovered_texture_files=tuple(scene_result.discovered_texture_files or ()),
            extracted_embedded_files=tuple(scene_result.extracted_embedded_files or ()),
            discovered_supplemental_files=tuple(scene_result.discovered_supplemental_files or ()),
            **_scene_result_context(scene_result),
        )
        grouped_name = f"{base_name}: {material}" if len(grouped) > 1 else base_name
        flattened = flatten_scene_import_result_parts(
            temp_result,
            part_name=grouped_name,
            material_name=material,
        )
        if flattened.mesh.submeshes:
            grouped_submeshes.append(flattened.mesh.submeshes[0])

    grouped_mesh = copy.deepcopy(source_mesh)
    grouped_mesh.submeshes = grouped_submeshes
    refresh_parsed_mesh_totals(grouped_mesh)
    diagnostics.append(
        f"Grouped {len(imported_submeshes):,} imported part(s) into {len(grouped_submeshes):,} material group(s)."
    )
    return SceneImportResult(
        mesh=grouped_mesh,
        diagnostics=tuple(diagnostics),
        discovered_texture_files=tuple(scene_result.discovered_texture_files or ()),
        extracted_embedded_files=tuple(scene_result.extracted_embedded_files or ()),
        discovered_supplemental_files=tuple(scene_result.discovered_supplemental_files or ()),
        **_scene_result_context(scene_result),
    )


def append_scene_import_to_mesh(
    target_mesh: ParsedMesh,
    base_mesh: ParsedMesh,
    scene_result: SceneImportResult,
    *,
    source_path: str | Path | None = None,
    label_prefix: str = "",
) -> SceneMeshAppendResult:
    """Append imported scene submeshes to the active and reset/base meshes."""
    if not isinstance(target_mesh, ParsedMesh) or not isinstance(base_mesh, ParsedMesh):
        raise TypeError("append_scene_import_to_mesh requires active and base ParsedMesh instances.")
    if not isinstance(scene_result, SceneImportResult):
        raise TypeError("append_scene_import_to_mesh requires a SceneImportResult.")
    imported_mesh = scene_result.mesh
    imported_submeshes = list(getattr(imported_mesh, "submeshes", ()) or ())
    if not imported_submeshes:
        raise ValueError("The selected mesh did not contain appendable submeshes.")
    path_label = ""
    if source_path is not None:
        path_label = Path(source_path).expanduser().stem
    if not path_label:
        path_label = Path(str(getattr(imported_mesh, "path", "") or "")).stem
    prefix = str(label_prefix or path_label or "appended").strip()
    start_index = len(target_mesh.submeshes)
    added_indices: list[int] = []
    for imported_index, source_submesh in enumerate(imported_submeshes):
        if not getattr(source_submesh, "vertices", None) or not getattr(source_submesh, "faces", None):
            continue
        active_submesh = copy.deepcopy(source_submesh)
        base_submesh = copy.deepcopy(source_submesh)
        base_name = str(getattr(source_submesh, "name", "") or getattr(source_submesh, "material", "") or f"part_{imported_index}")
        display_name = f"{prefix}: {base_name}" if prefix and not base_name.lower().startswith(prefix.lower()) else base_name
        active_submesh.name = display_name
        base_submesh.name = display_name
        if not str(getattr(active_submesh, "material", "") or "").strip():
            active_submesh.material = display_name
            base_submesh.material = display_name
        target_mesh.submeshes.append(active_submesh)
        base_mesh.submeshes.append(base_submesh)
        added_indices.append(start_index + len(added_indices))
    if not added_indices:
        raise ValueError("The selected mesh did not contain triangle geometry that can be appended.")
    refresh_parsed_mesh_totals(target_mesh)
    refresh_parsed_mesh_totals(base_mesh)
    texture_files = tuple(_dedupe_paths(list(scene_result.discovered_texture_files) + list(scene_result.extracted_embedded_files)))
    supplemental_files = tuple(
        _dedupe_paths(
            list(texture_files)
            + list(getattr(scene_result, "discovered_supplemental_files", ()) or ())
        )
    )
    diagnostics = tuple(scene_result.diagnostics) + (
        f"Appended {len(added_indices):,} source part(s) from {Path(source_path).name if source_path else prefix}.",
    )
    return SceneMeshAppendResult(
        source_indices=tuple(added_indices),
        texture_files=texture_files,
        supplemental_files=supplemental_files,
        diagnostics=diagnostics,
    )

__all__ = [
    "SceneImportResult",
    "SceneMeshAppendResult",
    "SceneMeshQualityReductionReport",
    "_decimate_submesh_for_import_quality",
    "_scene_result_context",
    "append_scene_import_to_mesh",
    "flatten_scene_import_result_parts",
    "group_scene_import_result_parts_by_material",
    "reduce_scene_import_result_quality",
    "refresh_parsed_mesh_totals",
]
