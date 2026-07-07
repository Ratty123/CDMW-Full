"""Pure Mesh Editor export validation rules."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePath

from .operations import validate_mesh_edit_operation_coverage, validate_mesh_edit_operations


SUPPORTED_GAME_MESH_FORMATS = frozenset({"pac", "pam", "pamlod"})
REBUILDABLE_PARSE_CONFIDENCE = frozenset({"exact", "inferred"})
BLOCKED_PARSE_CONFIDENCE = frozenset({"fallback_scan", "unsupported", "failed"})
DEVELOPER_OVERRIDABLE_REBUILD_BLOCKERS = frozenset(
    {
        "unsafe_parse_confidence",
        "no_op_roundtrip_not_passed",
        "no_op_roundtrip_unexpected_differences",
    }
)


@dataclass(frozen=True, slots=True)
class MeshExportValidationIssue:
    severity: str
    code: str
    message: str
    category: str = "general"
    expected: object | None = None
    actual: object | None = None
    lod_index: int = -1
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
    parse_confidence: str = ""
    source_asset_hash: str = ""
    no_op_roundtrip_status: str = ""
    no_op_byte_identical: bool | None = None
    no_op_unexpected_differences: int = 0

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
    parse_confidence: str = "",
    source_asset_hash: str = "",
    no_op_roundtrip_status: str = "",
    no_op_byte_identical: bool | None = None,
    no_op_unexpected_differences: int = 0,
    sidecar_warnings: Iterable[object] | None = None,
    edit_operations: Iterable[object] | None = None,
    requires_edit_operations: bool | None = None,
) -> MeshExportValidationReport:
    mesh_format = str(getattr(mesh, "format", "") or "").strip().lower()
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    issues: list[MeshExportValidationIssue] = []
    texture_keys = _texture_keys(available_textures) if available_textures is not None else None

    if mesh_format not in SUPPORTED_GAME_MESH_FORMATS:
        _add(
            issues,
            "blocker",
            "unsupported_mesh_format",
            f"Unsupported game mesh format for export: {mesh_format or 'unknown'}.",
            "format",
            expected=tuple(sorted(SUPPORTED_GAME_MESH_FORMATS)),
            actual=mesh_format or "unknown",
        )
    if not submeshes:
        _add(issues, "blocker", "empty_mesh", "Mesh has no parts to export.", "topology", expected=">=1", actual=0)

    vertex_total = 0
    face_total = 0
    geometry_points: list[tuple[float, float, float]] = []
    skinned = bool(getattr(mesh, "has_bones", False))
    original_submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ()) if original_mesh is not None else ()
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
            _add(
                issues,
                "blocker",
                "empty_part",
                "Mesh part has no vertices.",
                "topology",
                submesh_index=submesh_index,
                expected=">=1",
                actual=0,
            )
        for vertex_index, vertex in enumerate(vertices):
            if _vec3(vertex) is None:
                _add(issues, "blocker", "invalid_vertex_position", "Vertex position is missing or non-finite.", "topology", submesh_index=submesh_index, vertex_index=vertex_index)
        if not faces:
            _add(
                issues,
                "warning",
                "part_has_no_faces",
                "Mesh part has no faces and will not render.",
                "topology",
                submesh_index=submesh_index,
                expected=">=1",
                actual=0,
            )
        _validate_faces(issues, faces, len(vertices), submesh_index)
        _validate_vertex_channels(issues, len(vertices), uvs, normals, tangents, submesh_index)
        _validate_material(issues, submesh, submesh_index, texture_keys=texture_keys, texture_exists=texture_exists)
        original_submesh = original_submeshes[submesh_index] if submesh_index < len(original_submeshes) else None
        skinned = _validate_skinning(
            issues,
            submesh,
            len(vertices),
            submesh_index,
            original_submesh=original_submesh,
            skeleton_bone_count=skeleton_bone_count,
        ) or skinned

    if skinned and not skeleton_bone_count:
        inferred_bone_count = _inferred_bone_count(mesh)
        detail = f" Inferred bone count from vertex weights: {inferred_bone_count}." if inferred_bone_count else ""
        _add(
            issues,
            "blocker",
            "missing_skeleton_metadata",
            f"Skinned mesh export needs linked skeleton metadata before export.{detail}",
            "skeleton",
            expected="linked skeleton metadata",
            actual=inferred_bone_count or None,
        )

    _validate_bounds(issues, mesh, geometry_points)
    if original_mesh is not None:
        _validate_original_compatibility(issues, mesh, original_mesh)
    _validate_rebuild_status(
        issues,
        parse_confidence=parse_confidence,
        no_op_roundtrip_status=no_op_roundtrip_status,
        no_op_byte_identical=no_op_byte_identical,
        no_op_unexpected_differences=no_op_unexpected_differences,
    )
    _validate_sidecar_warnings(
        issues,
        sidecar_warnings if sidecar_warnings is not None else getattr(mesh, "_cdmw_sidecar_warnings", ()),
    )
    _validate_edit_operations(
        issues,
        mesh,
        original_mesh,
        edit_operations if edit_operations is not None else getattr(mesh, "_cdmw_edit_operations", ()),
        requires_operations=_mesh_requires_edit_operations(mesh, requires_edit_operations),
    )

    return MeshExportValidationReport(
        mesh_format=mesh_format,
        submesh_count=len(submeshes),
        vertex_count=vertex_total,
        face_count=face_total,
        issues=tuple(issues),
        parse_confidence=str(parse_confidence or ""),
        source_asset_hash=str(source_asset_hash or ""),
        no_op_roundtrip_status=str(no_op_roundtrip_status or ""),
        no_op_byte_identical=no_op_byte_identical,
        no_op_unexpected_differences=max(0, int(no_op_unexpected_differences or 0)),
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
    lod_index: int = -1,
    expected: object | None = None,
    actual: object | None = None,
) -> None:
    if lod_index < 0 and submesh_index >= 0:
        lod_index = 0
    issues.append(
        MeshExportValidationIssue(
            severity=severity,
            code=code,
            message=message,
            category=category,
            expected=expected,
            actual=actual,
            lod_index=lod_index,
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
            actual_count = len(face) if isinstance(face, (tuple, list)) else type(face).__name__
            _add(
                issues,
                "blocker",
                "invalid_face",
                "Face is not a valid triangle.",
                "topology",
                submesh_index=submesh_index,
                face_index=face_index,
                expected=3,
                actual=actual_count,
            )
            continue
        if any(index < 0 or index >= vertex_count for index in indices):
            _add(
                issues,
                "blocker",
                "invalid_face_index",
                "Face references a missing vertex.",
                "topology",
                submesh_index=submesh_index,
                face_index=face_index,
                expected=f"0..{max(0, vertex_count - 1)}",
                actual=indices,
            )
            continue
        if len(set(indices)) < 3:
            _add(
                issues,
                "blocker",
                "degenerate_face",
                "Face uses the same vertex more than once.",
                "topology",
                submesh_index=submesh_index,
                face_index=face_index,
                expected="3 unique indices",
                actual=indices,
            )
            continue
        key = tuple(sorted(indices))
        if key in seen:
            _add(
                issues,
                "warning",
                "duplicate_face",
                "Duplicate triangle found.",
                "topology",
                submesh_index=submesh_index,
                face_index=face_index,
                expected="unique triangle",
                actual=key,
            )
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
        _add(
            issues,
            "blocker",
            "uv_count_mismatch",
            "UV count does not match vertex count.",
            "uv",
            submesh_index=submesh_index,
            expected=vertex_count,
            actual=len(uvs),
        )
    if len(normals) != vertex_count:
        _add(
            issues,
            "blocker",
            "missing_normals",
            "Normal count does not match vertex count.",
            "normals",
            submesh_index=submesh_index,
            expected=vertex_count,
            actual=len(normals),
        )
    if not tangents:
        _add(
            issues,
            "warning",
            "missing_tangents",
            "Tangents/bitangents are missing; generate them before final export if the target shader needs them.",
            "normals",
            submesh_index=submesh_index,
            expected=vertex_count,
            actual=0,
        )
    elif len(tangents) != vertex_count:
        _add(
            issues,
            "warning",
            "tangent_count_mismatch",
            "Tangent count does not match vertex count.",
            "normals",
            submesh_index=submesh_index,
            expected=vertex_count,
            actual=len(tangents),
        )


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
        _add(
            issues,
            "blocker",
            "missing_material_slot",
            "Mesh part has no material slot.",
            "material",
            submesh_index=submesh_index,
            expected="non-empty material slot",
            actual=material,
        )
    if not texture:
        _add(
            issues,
            "warning",
            "missing_texture_reference",
            "Mesh part has no referenced texture.",
            "material",
            submesh_index=submesh_index,
            expected="texture reference",
            actual=texture,
        )
        return
    if texture_keys is not None and _texture_key(texture) not in texture_keys:
        _add(
            issues,
            "blocker",
            "missing_referenced_texture",
            f"Referenced texture is not available: {texture}.",
            "material",
            submesh_index=submesh_index,
            expected="available texture",
            actual=texture,
        )
    if texture_exists is not None and not texture_exists(texture):
        _add(
            issues,
            "blocker",
            "missing_referenced_texture",
            f"Referenced texture is not available: {texture}.",
            "material",
            submesh_index=submesh_index,
            expected="existing texture path",
            actual=texture,
        )


def _validate_skinning(
    issues: list[MeshExportValidationIssue],
    submesh: object,
    vertex_count: int,
    submesh_index: int,
    *,
    original_submesh: object | None,
    skeleton_bone_count: int | None,
) -> bool:
    bone_indices = tuple(getattr(submesh, "bone_indices", ()) or ())
    bone_weights = tuple(getattr(submesh, "bone_weights", ()) or ())
    has_skinning = bool(bone_indices or bone_weights)
    if not has_skinning:
        return False
    if len(bone_indices) != vertex_count or len(bone_weights) != vertex_count:
        _add(
            issues,
            "blocker",
            "skinning_count_mismatch",
            "Bone index/weight rows must match vertex count.",
            "skeleton",
            submesh_index=submesh_index,
            expected=vertex_count,
            actual={"bone_indices": len(bone_indices), "bone_weights": len(bone_weights)},
        )
        return True
    if original_submesh is not None and _skinning_changed_from_original(original_submesh, bone_indices, bone_weights):
        _add(
            issues,
            "blocker",
            "skinning_data_changed",
            "Bone indices and weights must match the original asset unless an explicit safe skinning operation exists.",
            "skeleton",
            submesh_index=submesh_index,
            expected="original bone indices and weights",
            actual="changed",
        )
    preserved_unnormalized = False
    for vertex_index, (indices, weights) in enumerate(zip(bone_indices, bone_weights)):
        index_row = tuple(indices or ())
        weight_row = tuple(weights or ())
        if len(index_row) != len(weight_row):
            _add(
                issues,
                "blocker",
                "bone_weight_row_mismatch",
                "Bone index and weight row lengths differ.",
                "skeleton",
                submesh_index=submesh_index,
                vertex_index=vertex_index,
                expected=len(index_row),
                actual=len(weight_row),
            )
            continue
        if len(index_row) > 4:
            _add(
                issues,
                "blocker",
                "too_many_bone_influences",
                "Vertex has more than four bone influences.",
                "skeleton",
                submesh_index=submesh_index,
                vertex_index=vertex_index,
                expected="<=4",
                actual=len(index_row),
            )
        clean_weights: list[float] = []
        for raw_index, raw_weight in zip(index_row, weight_row):
            bone_index = _coerce_index(raw_index)
            weight = _coerce_float(raw_weight)
            if bone_index is None or bone_index < 0 or (skeleton_bone_count is not None and bone_index >= skeleton_bone_count):
                _add(
                    issues,
                    "blocker",
                    "invalid_bone_index",
                    "Vertex references an invalid or missing bone.",
                    "skeleton",
                    submesh_index=submesh_index,
                    vertex_index=vertex_index,
                    expected=f"0..{max(0, skeleton_bone_count - 1)}" if skeleton_bone_count is not None else ">=0",
                    actual=raw_index,
                )
            if weight is None or weight < 0.0:
                _add(
                    issues,
                    "blocker",
                    "invalid_bone_weight",
                    "Vertex has an invalid bone weight.",
                    "skeleton",
                    submesh_index=submesh_index,
                    vertex_index=vertex_index,
                    expected="finite weight >= 0",
                    actual=raw_weight,
                )
            else:
                clean_weights.append(weight)
        total = sum(clean_weights)
        if clean_weights and not math.isclose(total, 1.0, rel_tol=0.02, abs_tol=0.02):
            if _skinning_row_matches_original(original_submesh, vertex_index, index_row, weight_row):
                preserved_unnormalized = True
            else:
                _add(
                    issues,
                    "blocker",
                    "unnormalized_bone_weights",
                    "Vertex bone weights are not normalized.",
                    "skeleton",
                    submesh_index=submesh_index,
                    vertex_index=vertex_index,
                    expected="sum ~= 1.0",
                    actual=total,
                )
    if preserved_unnormalized:
        _add(
            issues,
            "warning",
            "preserved_unnormalized_bone_weights",
            "Bone weights are not normalized, but they match the original asset and will be preserved.",
            "skeleton",
            submesh_index=submesh_index,
            expected="sum ~= 1.0",
            actual="preserved original values",
        )
    return True


def _skinning_row_matches_original(
    original_submesh: object | None,
    vertex_index: int,
    index_row: tuple[object, ...],
    weight_row: tuple[object, ...],
) -> bool:
    if original_submesh is None:
        return False
    original_indices = tuple(getattr(original_submesh, "bone_indices", ()) or ())
    original_weights = tuple(getattr(original_submesh, "bone_weights", ()) or ())
    if vertex_index >= len(original_indices) or vertex_index >= len(original_weights):
        return False
    return tuple(original_indices[vertex_index] or ()) == index_row and tuple(original_weights[vertex_index] or ()) == weight_row


def _skinning_changed_from_original(
    original_submesh: object,
    bone_indices: Sequence[object],
    bone_weights: Sequence[object],
) -> bool:
    original_indices = tuple(getattr(original_submesh, "bone_indices", ()) or ())
    original_weights = tuple(getattr(original_submesh, "bone_weights", ()) or ())
    return tuple(tuple(row or ()) for row in original_indices) != tuple(tuple(row or ()) for row in bone_indices) or tuple(
        tuple(row or ()) for row in original_weights
    ) != tuple(tuple(row or ()) for row in bone_weights)


def _validate_bounds(issues: list[MeshExportValidationIssue], mesh: object, points: Sequence[tuple[float, float, float]]) -> None:
    if not points:
        return
    mins = tuple(min(point[axis] for point in points) for axis in range(3))
    maxs = tuple(max(point[axis] for point in points) for axis in range(3))
    extents = tuple(maxs[axis] - mins[axis] for axis in range(3))
    max_extent = max(extents)
    if max_extent <= 1e-8:
        _add(issues, "warning", "zero_scale_bounds", "Mesh bounds are effectively zero-sized.", "bounds", expected=">1e-8", actual=max_extent)
    elif max_extent > 10000.0:
        _add(
            issues,
            "warning",
            "large_scale_bounds",
            "Mesh bounds are very large; verify scale before export.",
            "bounds",
            expected="<=10000.0",
            actual=max_extent,
        )
    header_min = _vec3(getattr(mesh, "bbox_min", ()))
    header_max = _vec3(getattr(mesh, "bbox_max", ()))
    if header_min is None or header_max is None:
        return
    for axis in range(3):
        if mins[axis] < header_min[axis] - 1e-4 or maxs[axis] > header_max[axis] + 1e-4:
            _add(
                issues,
                "warning",
                "bounds_mismatch",
                "Geometry extends outside stored mesh bounds; update bounds before export.",
                "bounds",
                expected={"min": header_min, "max": header_max},
                actual={"min": mins, "max": maxs},
            )
            return


def _validate_original_compatibility(issues: list[MeshExportValidationIssue], mesh: object, original_mesh: object) -> None:
    mesh_format = str(getattr(mesh, "format", "") or "").strip().lower()
    edited_lods = _submeshes_by_lod(mesh)
    original_lods = _submeshes_by_lod(original_mesh)
    _validate_unknown_sections_preserved(issues, mesh, original_mesh)
    _validate_lod_identity_preserved(issues, mesh, original_mesh)
    original_material_slot_count = _material_slot_count(original_mesh)
    edited_material_slot_count = _material_slot_count(mesh)
    if original_material_slot_count is not None:
        actual_material_slot_count: object = (
            edited_material_slot_count if edited_material_slot_count is not None else "missing"
        )
        if actual_material_slot_count != original_material_slot_count:
            _add(
                issues,
                "blocker",
                "material_slot_count_changed",
                "Material slot count changed; material replacement is blocked by default.",
                "material",
                expected=original_material_slot_count,
                actual=actual_material_slot_count,
            )
    if len(edited_lods) != len(original_lods):
        _add(
            issues,
            "blocker",
            "lod_count_changed",
            "LOD count changed; LOD replacement is blocked by default.",
            "topology",
            expected=len(original_lods),
            actual=len(edited_lods),
        )
    for lod_index, (edited_lod, original_lod) in enumerate(zip(edited_lods, original_lods)):
        if len(edited_lod) != len(original_lod):
            _add(
                issues,
                "blocker",
                "lod_submesh_count_changed",
                "LOD submesh count changed; topology replacement is blocked by default.",
                "topology",
                lod_index=lod_index,
                expected=len(original_lod),
                actual=len(edited_lod),
            )
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
    original_submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ())
    if len(submeshes) != len(original_submeshes):
        _add(
            issues,
            "warning",
            "material_slot_count_mismatch",
            "Edited part count differs from original material slot count.",
            "material",
            expected=len(original_submeshes),
            actual=len(submeshes),
        )
    for submesh_index, (submesh, original_submesh) in enumerate(zip(submeshes, original_submeshes)):
        vertex_count = len(tuple(getattr(submesh, "vertices", ()) or ()))
        original_vertex_count = len(tuple(getattr(original_submesh, "vertices", ()) or ()))
        if vertex_count != original_vertex_count:
            _add(
                issues,
                "blocker",
                "submesh_vertex_count_changed",
                "Submesh vertex count changed; topology replacement is blocked by default.",
                "topology",
                submesh_index=submesh_index,
                expected=original_vertex_count,
                actual=vertex_count,
            )
        index_count = len(tuple(getattr(submesh, "faces", ()) or ())) * 3
        original_index_count = len(tuple(getattr(original_submesh, "faces", ()) or ())) * 3
        if index_count != original_index_count:
            _add(
                issues,
                "blocker",
                "submesh_index_count_changed",
                "Submesh index count changed; topology replacement is blocked by default.",
                "topology",
                submesh_index=submesh_index,
                expected=original_index_count,
                actual=index_count,
            )
        if _geometry_changed_from_original(submesh, original_submesh):
            _validate_changed_geometry_source_map(issues, submesh, submesh_index, vertex_count)
        _validate_unknown_fields_preserved(issues, submesh, original_submesh, submesh_index)
        _validate_vertex_stride_preserved(issues, submesh, original_submesh, submesh_index)
        _validate_source_offsets_preserved(issues, submesh, original_submesh, submesh_index)
        if str(getattr(submesh, "material", "") or "") != str(getattr(original_submesh, "material", "") or ""):
            _add(
                issues,
                "blocker",
                "material_slot_changed",
                "Material slot changes are blocked by default; preserve the original material unless an explicit safe material operation exists.",
                "material",
                submesh_index=submesh_index,
                expected=str(getattr(original_submesh, "material", "") or ""),
                actual=str(getattr(submesh, "material", "") or ""),
            )
        if str(getattr(submesh, "texture", "") or "") != str(getattr(original_submesh, "texture", "") or ""):
            _add(
                issues,
                "blocker",
                "texture_reference_changed",
                "Texture reference changes are blocked by default; preserve the original texture unless an explicit safe material operation exists.",
                "material",
                submesh_index=submesh_index,
                expected=str(getattr(original_submesh, "texture", "") or ""),
                actual=str(getattr(submesh, "texture", "") or ""),
            )
    if mesh_format in {"pam", "pamlod"} and _topology_signature(mesh) != _topology_signature(original_mesh):
        _add(
            issues,
            "blocker",
            f"unsupported_{mesh_format}_topology_change",
            f"{mesh_format.upper()} export cannot use this topology change safely yet.",
            "format",
            expected=_topology_signature(original_mesh),
            actual=_topology_signature(mesh),
        )


def _submeshes_by_lod(mesh: object) -> tuple[tuple[object, ...], ...]:
    lod_levels = tuple(getattr(mesh, "lod_levels", ()) or ())
    if lod_levels:
        return tuple(tuple(level or ()) for level in lod_levels)
    return (tuple(getattr(mesh, "submeshes", ()) or ()),)


def _material_slot_count(mesh: object) -> int | None:
    for attr in ("_cdmw_mesh_asset_material_slots", "material_slots"):
        if hasattr(mesh, attr):
            return len(tuple(getattr(mesh, attr) or ()))
    return None


def _validate_lod_identity_preserved(
    issues: list[MeshExportValidationIssue],
    mesh: object,
    original_mesh: object,
) -> None:
    original_identity = _mesh_lod_identity(original_mesh)
    if original_identity is None:
        return
    edited_identity = _mesh_lod_identity(mesh)
    if _stable_metadata_value(edited_identity) == _stable_metadata_value(original_identity):
        return
    _add(
        issues,
        "blocker",
        "lod_identity_changed",
        "LOD identity metadata was not preserved.",
        "metadata",
        expected=original_identity,
        actual=edited_identity if edited_identity is not None else "missing",
    )


def _validate_unknown_sections_preserved(
    issues: list[MeshExportValidationIssue],
    mesh: object,
    original_mesh: object,
) -> None:
    original_sections = _mesh_unknown_sections(original_mesh)
    if original_sections is None:
        return
    edited_sections = _mesh_unknown_sections(mesh)
    if _stable_metadata_value(edited_sections) == _stable_metadata_value(original_sections):
        return
    _add(
        issues,
        "blocker",
        "unknown_sections_changed",
        "Unknown binary sections were not preserved.",
        "metadata",
        expected=original_sections,
        actual=edited_sections if edited_sections is not None else "missing",
    )


def _validate_unknown_fields_preserved(
    issues: list[MeshExportValidationIssue],
    submesh: object,
    original_submesh: object,
    submesh_index: int,
) -> None:
    original_fields = _submesh_unknown_fields(original_submesh)
    if original_fields is None:
        return
    edited_fields = _submesh_unknown_fields(submesh)
    if _stable_metadata_value(edited_fields) == _stable_metadata_value(original_fields):
        return
    _add(
        issues,
        "blocker",
        "unknown_fields_changed",
        "Unknown submesh fields were not preserved.",
        "metadata",
        submesh_index=submesh_index,
        expected=original_fields,
        actual=edited_fields if edited_fields is not None else "missing",
    )


def _validate_vertex_stride_preserved(
    issues: list[MeshExportValidationIssue],
    submesh: object,
    original_submesh: object,
    submesh_index: int,
) -> None:
    original_stride = _submesh_vertex_stride(original_submesh)
    if original_stride is None:
        return
    edited_stride = _submesh_vertex_stride(submesh)
    actual: object = edited_stride if edited_stride is not None else "missing"
    if actual == original_stride:
        return
    _add(
        issues,
        "blocker",
        "vertex_stride_changed",
        "Original vertex stride was not preserved.",
        "metadata",
        submesh_index=submesh_index,
        expected=original_stride,
        actual=actual,
    )


def _validate_source_offsets_preserved(
    issues: list[MeshExportValidationIssue],
    submesh: object,
    original_submesh: object,
    submesh_index: int,
) -> None:
    original_vertex_offsets = _submesh_source_vertex_offsets(original_submesh)
    if original_vertex_offsets is not None:
        edited_vertex_offsets = _submesh_source_vertex_offsets(submesh)
        actual_vertex_offsets: object = edited_vertex_offsets if edited_vertex_offsets is not None else "missing"
        if actual_vertex_offsets != original_vertex_offsets:
            _add(
                issues,
                "blocker",
                "source_vertex_offsets_changed",
                "Source vertex offsets were not preserved.",
                "metadata",
                submesh_index=submesh_index,
                expected=original_vertex_offsets,
                actual=actual_vertex_offsets,
            )
    for attr, code, message in (
        ("source_index_offset", "source_index_offset_changed", "Source index offset was not preserved."),
        ("source_descriptor_offset", "source_descriptor_offset_changed", "Source descriptor offset was not preserved."),
    ):
        original_value = _submesh_nonnegative_int(original_submesh, attr)
        if original_value is None:
            continue
        edited_value = _submesh_nonnegative_int(submesh, attr)
        actual_value: object = edited_value if edited_value is not None else "missing"
        if actual_value != original_value:
            _add(
                issues,
                "blocker",
                code,
                message,
                "metadata",
                submesh_index=submesh_index,
                expected=original_value,
                actual=actual_value,
            )
    original_index_count = _submesh_positive_int(original_submesh, "source_index_count")
    if original_index_count is None:
        return
    edited_index_count = _submesh_positive_int(submesh, "source_index_count")
    actual_index_count: object = edited_index_count if edited_index_count is not None else "missing"
    if actual_index_count != original_index_count:
        _add(
            issues,
            "blocker",
            "source_index_count_changed",
            "Source index count was not preserved.",
            "metadata",
            submesh_index=submesh_index,
            expected=original_index_count,
            actual=actual_index_count,
        )


def _mesh_unknown_sections(mesh: object) -> object | None:
    for attr in ("_cdmw_mesh_asset_unknown_sections", "unknown_sections"):
        if hasattr(mesh, attr):
            return getattr(mesh, attr)
    return None


def _mesh_lod_identity(mesh: object) -> object | None:
    if not hasattr(mesh, "_cdmw_mesh_asset_lods"):
        return None
    return tuple(
        {
            "lod_index": _metadata_int(lod, "lod_index", index),
            "name": str(_metadata_get(lod, "name", "") or ""),
            "original_section_offset": _metadata_int(lod, "original_section_offset", -1),
            "original_section_size": _metadata_int(lod, "original_section_size", 0),
            "bounds": _metadata_get(lod, "bounds"),
            "metadata": _metadata_get(lod, "metadata", {}),
            "submeshes": tuple(
                _lod_submesh_identity(submesh, submesh_index)
                for submesh_index, submesh in enumerate(tuple(_metadata_get(lod, "submeshes", ()) or ()))
            ),
        }
        for index, lod in enumerate(tuple(getattr(mesh, "_cdmw_mesh_asset_lods") or ()))
    )


def _lod_submesh_identity(submesh: object, submesh_index: int) -> dict[str, object]:
    return {
        "submesh_index": _metadata_int(submesh, "submesh_index", submesh_index),
        "stable_id": str(_metadata_get(submesh, "stable_id", "") or ""),
        "material_slot_index": _metadata_int(submesh, "material_slot_index", -1),
        "original_descriptor_offset": _metadata_int(submesh, "original_descriptor_offset", -1),
        "original_vertex_offset": _metadata_int(submesh, "original_vertex_offset", -1),
        "original_index_offset": _metadata_int(submesh, "original_index_offset", -1),
        "original_vertex_stride": _metadata_int(submesh, "original_vertex_stride", 0),
    }


def _metadata_get(source: object, key: str, default: object = None) -> object:
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def _metadata_int(source: object, key: str, default: int) -> int:
    parsed = _coerce_index(_metadata_get(source, key, default))
    return parsed if parsed is not None else default


def _submesh_unknown_fields(submesh: object) -> object | None:
    if hasattr(submesh, "unknown_fields"):
        return getattr(submesh, "unknown_fields")
    return None


def _submesh_vertex_stride(submesh: object) -> int | None:
    for attr in ("source_vertex_stride", "original_vertex_stride"):
        if hasattr(submesh, attr):
            stride = _coerce_index(getattr(submesh, attr))
            if stride is not None and stride > 0:
                return stride
    vertex_buffer = getattr(submesh, "vertex_buffer", None)
    if vertex_buffer is not None and hasattr(vertex_buffer, "original_stride"):
        stride = _coerce_index(getattr(vertex_buffer, "original_stride"))
        return stride if stride is not None and stride > 0 else None
    return None


def _submesh_source_vertex_offsets(submesh: object) -> object | None:
    if not hasattr(submesh, "source_vertex_offsets"):
        return None
    values = tuple(getattr(submesh, "source_vertex_offsets") or ())
    if not values:
        return None
    parsed = tuple(_coerce_index(value) for value in values)
    return parsed if all(value is not None for value in parsed) else values


def _submesh_nonnegative_int(submesh: object, attr: str) -> int | None:
    if not hasattr(submesh, attr):
        return None
    value = _coerce_index(getattr(submesh, attr))
    return value if value is not None and value >= 0 else None


def _submesh_positive_int(submesh: object, attr: str) -> int | None:
    if not hasattr(submesh, attr):
        return None
    value = _coerce_index(getattr(submesh, attr))
    return value if value is not None and value > 0 else None


def _stable_metadata_value(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple(sorted((str(key), _stable_metadata_value(item)) for key, item in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_stable_metadata_value(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_stable_metadata_value(item) for item in value), key=repr))
    return value


def _geometry_changed_from_original(submesh: object, original_submesh: object) -> bool:
    return any(
        tuple(getattr(submesh, attr, ()) or ()) != tuple(getattr(original_submesh, attr, ()) or ())
        for attr in ("vertices", "normals", "tangents", "uvs", "faces")
    )


def _validate_changed_geometry_source_map(
    issues: list[MeshExportValidationIssue],
    submesh: object,
    submesh_index: int,
    vertex_count: int,
) -> None:
    source_map = tuple(getattr(submesh, "source_vertex_map", ()) or ())
    if len(source_map) != vertex_count:
        _add(
            issues,
            "blocker",
            "source_vertex_map_missing",
            "Changed geometry requires a source vertex map for every edited vertex.",
            "topology",
            submesh_index=submesh_index,
            expected=vertex_count,
            actual=len(source_map),
        )
        return
    if any((index := _coerce_index(value)) is None or index < 0 for value in source_map):
        _add(
            issues,
            "blocker",
            "source_vertex_map_invalid",
            "Changed geometry source vertex map contains invalid entries.",
            "topology",
            submesh_index=submesh_index,
            expected="non-negative source vertex ids",
            actual=source_map,
        )


def _validate_rebuild_status(
    issues: list[MeshExportValidationIssue],
    *,
    parse_confidence: str,
    no_op_roundtrip_status: str,
    no_op_byte_identical: bool | None,
    no_op_unexpected_differences: int,
) -> None:
    confidence = str(parse_confidence or "").strip().casefold()
    if confidence in BLOCKED_PARSE_CONFIDENCE:
        _add(
            issues,
            "blocker",
            "unsafe_parse_confidence",
            f"Parser confidence is {confidence}; rebuild is blocked until the layout is exact or inferred.",
            "rebuild",
            expected=tuple(sorted(REBUILDABLE_PARSE_CONFIDENCE)),
            actual=confidence,
        )
    elif confidence and confidence not in REBUILDABLE_PARSE_CONFIDENCE:
        _add(
            issues,
            "blocker",
            "unknown_parse_confidence",
            f"Parser confidence is unknown: {confidence}.",
            "rebuild",
            expected=tuple(sorted(REBUILDABLE_PARSE_CONFIDENCE | BLOCKED_PARSE_CONFIDENCE)),
            actual=confidence,
        )
    elif confidence == "inferred":
        _add(
            issues,
            "warning",
            "inferred_parse_confidence",
            "Parser confidence is inferred; verify the no-op round-trip before final rebuild.",
            "rebuild",
            expected="exact",
            actual=confidence,
        )

    status = str(no_op_roundtrip_status or "").strip().casefold()
    if status and status != "pass":
        _add(
            issues,
            "blocker",
            "no_op_roundtrip_not_passed",
            f"No-op round-trip status is {status}; rebuild is blocked.",
            "rebuild",
            expected="pass",
            actual=status,
        )
    unexpected = max(0, int(no_op_unexpected_differences or 0))
    if unexpected:
        _add(
            issues,
            "blocker",
            "no_op_roundtrip_unexpected_differences",
            "No-op round-trip has unexpected byte differences.",
            "rebuild",
            expected=0,
            actual=unexpected,
        )
    elif no_op_byte_identical is False and status == "pass":
        _add(
            issues,
            "warning",
            "no_op_roundtrip_tolerant_differences",
            "No-op round-trip passed with documented non-identical bytes.",
            "rebuild",
            expected=True,
            actual=False,
        )


def _validate_sidecar_warnings(issues: list[MeshExportValidationIssue], warnings: Iterable[object]) -> None:
    for warning in tuple(warnings or ()):
        if not isinstance(warning, dict):
            continue
        code = str(warning.get("code") or "sidecar_warning").strip() or "sidecar_warning"
        message = str(warning.get("message") or "Sidecar import warning.").strip() or "Sidecar import warning."
        submesh_index = _coerce_index(warning.get("submesh_index"))
        _add(
            issues,
            "warning",
            code,
            message,
            "sidecar",
            submesh_index=submesh_index if submesh_index is not None else -1,
            expected=warning.get("expected"),
            actual=warning.get("actual"),
        )
        if bool(warning.get("blocks_rebuild")):
            _add(
                issues,
                "blocker",
                f"{code}_blocks_rebuild",
                f"{message} Rebuild is blocked until the sidecar metadata is restored or an explicit safe material operation exists.",
                "sidecar",
                submesh_index=submesh_index if submesh_index is not None else -1,
                expected=warning.get("expected"),
                actual=warning.get("actual"),
            )


def _validate_edit_operations(
    issues: list[MeshExportValidationIssue],
    mesh: object,
    original_mesh: object | None,
    operations: Iterable[object],
    *,
    requires_operations: bool,
) -> None:
    operation_tuple = tuple(operations or ())
    if requires_operations and not operation_tuple:
        _add(
            issues,
            "blocker",
            "missing_edit_operations",
            "Imported OBJ sidecar rebuild requires explicit Mesh Editor v2 edit operations.",
            "operations",
            expected=">=1",
            actual=0,
        )
        return
    for issue in validate_mesh_edit_operations(operation_tuple, mesh=mesh):
        if issue.severity != "blocker":
            continue
        _add(
            issues,
            "blocker",
            issue.code,
            issue.message,
            "operations",
            submesh_index=issue.submesh_index,
            expected=getattr(issue, "expected", None),
            actual=getattr(issue, "actual", None),
        )
    for issue in validate_mesh_edit_operation_coverage(operation_tuple, mesh=mesh, original_mesh=original_mesh):
        if issue.severity != "blocker":
            continue
        _add(
            issues,
            "blocker",
            issue.code,
            issue.message,
            "operations",
            submesh_index=issue.submesh_index,
            expected=getattr(issue, "expected", None),
            actual=getattr(issue, "actual", None),
        )


def _mesh_requires_edit_operations(mesh: object, explicit: bool | None) -> bool:
    if explicit is not None:
        return bool(explicit)
    if bool(getattr(mesh, "_cdmw_requires_edit_operations", False)):
        return True
    return bool(getattr(mesh, "_cdmw_imported_from_obj", False)) and bool(getattr(mesh, "_cdmw_obj_sidecar_present", False))


def _inferred_bone_count(mesh: object) -> int:
    max_index = -1
    for submesh in tuple(getattr(mesh, "submeshes", ()) or ()):
        for row in tuple(getattr(submesh, "bone_indices", ()) or ()):
            for value in tuple(row or ()):
                bone_index = _coerce_index(value)
                if bone_index is not None and bone_index >= 0:
                    max_index = max(max_index, bone_index)
    return max_index + 1 if max_index >= 0 else 0


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
