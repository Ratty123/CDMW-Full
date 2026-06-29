"""Pure Mesh Editor export validation rules."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePath


SUPPORTED_GAME_MESH_FORMATS = frozenset({"pac", "pam", "pamlod"})


@dataclass(frozen=True, slots=True)
class MeshExportValidationIssue:
    severity: str
    code: str
    message: str
    category: str = "general"
    submesh_index: int = -1
    vertex_index: int = -1
    face_index: int = -1


@dataclass(frozen=True, slots=True)
class MeshExportValidationReport:
    mesh_format: str
    submesh_count: int
    vertex_count: int
    face_count: int
    issues: tuple[MeshExportValidationIssue, ...] = ()

    @property
    def blockers(self) -> tuple[MeshExportValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "blocker")

    @property
    def warnings(self) -> tuple[MeshExportValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.blockers


def validate_mesh_export(
    mesh: object,
    *,
    original_mesh: object | None = None,
    available_textures: Iterable[str] | None = None,
    texture_exists: Callable[[str], bool] | None = None,
    skeleton_bone_count: int | None = None,
) -> MeshExportValidationReport:
    mesh_format = str(getattr(mesh, "format", "") or "").strip().lower()
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    issues: list[MeshExportValidationIssue] = []
    texture_keys = _texture_keys(available_textures) if available_textures is not None else None

    if mesh_format not in SUPPORTED_GAME_MESH_FORMATS:
        _add(issues, "blocker", "unsupported_mesh_format", f"Unsupported game mesh format for export: {mesh_format or 'unknown'}.", "format")
    if not submeshes:
        _add(issues, "blocker", "empty_mesh", "Mesh has no parts to export.", "topology")

    vertex_total = 0
    face_total = 0
    geometry_points: list[tuple[float, float, float]] = []
    skinned = bool(getattr(mesh, "has_bones", False))
    for submesh_index, submesh in enumerate(submeshes):
        vertices = tuple(getattr(submesh, "vertices", ()) or ())
        uvs = tuple(getattr(submesh, "uvs", ()) or ())
        normals = tuple(getattr(submesh, "normals", ()) or ())
        tangents = tuple(getattr(submesh, "tangents", ()) or ())
        faces = tuple(getattr(submesh, "faces", ()) or ())
        vertex_total += len(vertices)
        face_total += len(faces)
        geometry_points.extend(_finite_points(vertices))

        if not vertices:
            _add(issues, "blocker", "empty_part", "Mesh part has no vertices.", "topology", submesh_index=submesh_index)
        for vertex_index, vertex in enumerate(vertices):
            if _vec3(vertex) is None:
                _add(issues, "blocker", "invalid_vertex_position", "Vertex position is missing or non-finite.", "topology", submesh_index=submesh_index, vertex_index=vertex_index)
        if not faces:
            _add(issues, "warning", "part_has_no_faces", "Mesh part has no faces and will not render.", "topology", submesh_index=submesh_index)
        _validate_faces(issues, faces, len(vertices), submesh_index)
        _validate_vertex_channels(issues, len(vertices), uvs, normals, tangents, submesh_index)
        _validate_material(issues, submesh, submesh_index, texture_keys=texture_keys, texture_exists=texture_exists)
        skinned = _validate_skinning(
            issues,
            submesh,
            len(vertices),
            submesh_index,
            skeleton_bone_count=skeleton_bone_count,
        ) or skinned

    if skinned and not skeleton_bone_count:
        _add(
            issues,
            "blocker",
            "missing_skeleton_metadata",
            "Skinned mesh export needs linked skeleton metadata before export.",
            "skeleton",
        )

    _validate_bounds(issues, mesh, geometry_points)
    if original_mesh is not None:
        _validate_original_compatibility(issues, mesh, original_mesh)

    return MeshExportValidationReport(
        mesh_format=mesh_format,
        submesh_count=len(submeshes),
        vertex_count=vertex_total,
        face_count=face_total,
        issues=tuple(issues),
    )


def _add(
    issues: list[MeshExportValidationIssue],
    severity: str,
    code: str,
    message: str,
    category: str,
    *,
    submesh_index: int = -1,
    vertex_index: int = -1,
    face_index: int = -1,
) -> None:
    issues.append(
        MeshExportValidationIssue(
            severity=severity,
            code=code,
            message=message,
            category=category,
            submesh_index=submesh_index,
            vertex_index=vertex_index,
            face_index=face_index,
        )
    )


def _validate_faces(
    issues: list[MeshExportValidationIssue],
    faces: Sequence[object],
    vertex_count: int,
    submesh_index: int,
) -> None:
    seen: set[tuple[int, int, int]] = set()
    for face_index, face in enumerate(faces):
        indices = _face_indices(face)
        if indices is None:
            _add(issues, "blocker", "invalid_face", "Face is not a valid triangle.", "topology", submesh_index=submesh_index, face_index=face_index)
            continue
        if any(index < 0 or index >= vertex_count for index in indices):
            _add(issues, "blocker", "invalid_face_index", "Face references a missing vertex.", "topology", submesh_index=submesh_index, face_index=face_index)
            continue
        if len(set(indices)) < 3:
            _add(issues, "blocker", "degenerate_face", "Face uses the same vertex more than once.", "topology", submesh_index=submesh_index, face_index=face_index)
            continue
        key = tuple(sorted(indices))
        if key in seen:
            _add(issues, "warning", "duplicate_face", "Duplicate triangle found.", "topology", submesh_index=submesh_index, face_index=face_index)
        seen.add(key)


def _validate_vertex_channels(
    issues: list[MeshExportValidationIssue],
    vertex_count: int,
    uvs: Sequence[object],
    normals: Sequence[object],
    tangents: Sequence[object],
    submesh_index: int,
) -> None:
    if len(uvs) != vertex_count:
        _add(issues, "blocker", "uv_count_mismatch", "UV count does not match vertex count.", "uv", submesh_index=submesh_index)
    if len(normals) != vertex_count:
        _add(issues, "blocker", "missing_normals", "Normal count does not match vertex count.", "normals", submesh_index=submesh_index)
    if not tangents:
        _add(issues, "warning", "missing_tangents", "Tangents/bitangents are missing; generate them before final export if the target shader needs them.", "normals", submesh_index=submesh_index)
    elif len(tangents) != vertex_count:
        _add(issues, "warning", "tangent_count_mismatch", "Tangent count does not match vertex count.", "normals", submesh_index=submesh_index)


def _validate_material(
    issues: list[MeshExportValidationIssue],
    submesh: object,
    submesh_index: int,
    *,
    texture_keys: set[str] | None,
    texture_exists: Callable[[str], bool] | None,
) -> None:
    material = str(getattr(submesh, "material", "") or "").strip()
    texture = str(getattr(submesh, "texture", "") or "").strip()
    if not material:
        _add(issues, "blocker", "missing_material_slot", "Mesh part has no material slot.", "material", submesh_index=submesh_index)
    if not texture:
        _add(issues, "warning", "missing_texture_reference", "Mesh part has no referenced texture.", "material", submesh_index=submesh_index)
        return
    if texture_keys is not None and _texture_key(texture) not in texture_keys:
        _add(issues, "blocker", "missing_referenced_texture", f"Referenced texture is not available: {texture}.", "material", submesh_index=submesh_index)
    if texture_exists is not None and not texture_exists(texture):
        _add(issues, "blocker", "missing_referenced_texture", f"Referenced texture is not available: {texture}.", "material", submesh_index=submesh_index)


def _validate_skinning(
    issues: list[MeshExportValidationIssue],
    submesh: object,
    vertex_count: int,
    submesh_index: int,
    *,
    skeleton_bone_count: int | None,
) -> bool:
    bone_indices = tuple(getattr(submesh, "bone_indices", ()) or ())
    bone_weights = tuple(getattr(submesh, "bone_weights", ()) or ())
    has_skinning = bool(bone_indices or bone_weights)
    if not has_skinning:
        return False
    if len(bone_indices) != vertex_count or len(bone_weights) != vertex_count:
        _add(issues, "blocker", "skinning_count_mismatch", "Bone index/weight rows must match vertex count.", "skeleton", submesh_index=submesh_index)
        return True
    for vertex_index, (indices, weights) in enumerate(zip(bone_indices, bone_weights)):
        index_row = tuple(indices or ())
        weight_row = tuple(weights or ())
        if len(index_row) != len(weight_row):
            _add(issues, "blocker", "bone_weight_row_mismatch", "Bone index and weight row lengths differ.", "skeleton", submesh_index=submesh_index, vertex_index=vertex_index)
            continue
        if len(index_row) > 4:
            _add(issues, "blocker", "too_many_bone_influences", "Vertex has more than four bone influences.", "skeleton", submesh_index=submesh_index, vertex_index=vertex_index)
        clean_weights: list[float] = []
        for raw_index, raw_weight in zip(index_row, weight_row):
            bone_index = _coerce_index(raw_index)
            weight = _coerce_float(raw_weight)
            if bone_index is None or bone_index < 0 or (skeleton_bone_count is not None and bone_index >= skeleton_bone_count):
                _add(issues, "blocker", "invalid_bone_index", "Vertex references an invalid or missing bone.", "skeleton", submesh_index=submesh_index, vertex_index=vertex_index)
            if weight is None or weight < 0.0:
                _add(issues, "blocker", "invalid_bone_weight", "Vertex has an invalid bone weight.", "skeleton", submesh_index=submesh_index, vertex_index=vertex_index)
            else:
                clean_weights.append(weight)
        total = sum(clean_weights)
        if clean_weights and not math.isclose(total, 1.0, rel_tol=0.02, abs_tol=0.02):
            _add(issues, "blocker", "unnormalized_bone_weights", "Vertex bone weights are not normalized.", "skeleton", submesh_index=submesh_index, vertex_index=vertex_index)
    return True


def _validate_bounds(issues: list[MeshExportValidationIssue], mesh: object, points: Sequence[tuple[float, float, float]]) -> None:
    if not points:
        return
    mins = tuple(min(point[axis] for point in points) for axis in range(3))
    maxs = tuple(max(point[axis] for point in points) for axis in range(3))
    extents = tuple(maxs[axis] - mins[axis] for axis in range(3))
    max_extent = max(extents)
    if max_extent <= 1e-8:
        _add(issues, "warning", "zero_scale_bounds", "Mesh bounds are effectively zero-sized.", "bounds")
    elif max_extent > 10000.0:
        _add(issues, "warning", "large_scale_bounds", "Mesh bounds are very large; verify scale before export.", "bounds")
    header_min = _vec3(getattr(mesh, "bbox_min", ()))
    header_max = _vec3(getattr(mesh, "bbox_max", ()))
    if header_min is None or header_max is None:
        return
    for axis in range(3):
        if mins[axis] < header_min[axis] - 1e-4 or maxs[axis] > header_max[axis] + 1e-4:
            _add(issues, "warning", "bounds_mismatch", "Geometry extends outside stored mesh bounds; update bounds before export.", "bounds")
            return


def _validate_original_compatibility(issues: list[MeshExportValidationIssue], mesh: object, original_mesh: object) -> None:
    mesh_format = str(getattr(mesh, "format", "") or "").strip().lower()
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    original_submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    if len(submeshes) != len(original_submeshes):
        _add(issues, "warning", "material_slot_count_mismatch", "Edited part count differs from original material slot count.", "material")
    if mesh_format in {"pam", "pamlod"} and _topology_signature(mesh) != _topology_signature(original_mesh):
        _add(issues, "blocker", f"unsupported_{mesh_format}_topology_change", f"{mesh_format.upper()} export cannot use this topology change safely yet.", "format")


def _topology_signature(mesh: object) -> tuple[tuple[int, int], ...]:
    return tuple((len(getattr(submesh, "vertices", ()) or ()), len(getattr(submesh, "faces", ()) or ())) for submesh in tuple(getattr(mesh, "submeshes", ()) or ()))


def _face_indices(face: object) -> tuple[int, int, int] | None:
    if not isinstance(face, (tuple, list)) or len(face) != 3:
        return None
    indices = tuple(_coerce_index(value) for value in face)
    if any(value is None for value in indices):
        return None
    return indices  # type: ignore[return-value]


def _finite_points(vertices: Sequence[object]) -> tuple[tuple[float, float, float], ...]:
    points: list[tuple[float, float, float]] = []
    for vertex in vertices:
        point = _vec3(vertex)
        if point is not None:
            points.append(point)
    return tuple(points)


def _vec3(value: object) -> tuple[float, float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) < 3:
        return None
    numbers = tuple(_coerce_float(component) for component in value[:3])
    if any(component is None for component in numbers):
        return None
    return numbers  # type: ignore[return-value]


def _coerce_index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        return int(value)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _texture_keys(values: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for value in values:
        key = _texture_key(value)
        if key:
            result.add(key)
    return result


def _texture_key(value: object) -> str:
    text = str(value or "").replace("\\", "/").strip().casefold()
    if not text:
        return ""
    return PurePath(text).name.casefold()


__all__ = [
    "MeshExportValidationIssue",
    "MeshExportValidationReport",
    "SUPPORTED_GAME_MESH_FORMATS",
    "validate_mesh_export",
]
