"""Strict mesh asset contract and rebuild validation rules."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


LAYOUT_CONFIDENCE_EXACT = "exact"
LAYOUT_CONFIDENCE_INFERRED = "inferred"
LAYOUT_CONFIDENCE_FALLBACK_SCAN = "fallback_scan"

VALIDATION_SEVERITIES = ("info", "warning", "error", "fatal")


@dataclass(frozen=True, slots=True)
class MeshFileSection:
    name: str
    offset: int
    size: int
    index: int = -1


@dataclass(frozen=True, slots=True)
class BinaryLayout:
    file_sections: tuple[MeshFileSection, ...] = ()
    offsets: dict[str, int] = field(default_factory=dict)
    sizes: dict[str, int] = field(default_factory=dict)
    alignment: int = 1
    endian: str = "little"
    preserved_ranges: tuple[MeshFileSection, ...] = ()
    rebuild_rules: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MeshVertex:
    position: tuple[float, float, float]
    normal: tuple[float, float, float] | None = None
    tangent: tuple[float, float, float] | None = None
    uv0: tuple[float, float] | None = None
    uv1: tuple[float, float] | None = None
    color: tuple[float, float, float, float] | None = None
    bone_indices: tuple[int, ...] = ()
    bone_weights: tuple[float, ...] = ()
    source_offset: int = -1
    raw_bytes_before_edit: bytes = b""


@dataclass(frozen=True, slots=True)
class VertexBuffer:
    vertices: tuple[MeshVertex, ...] = ()
    original_stride: int = 0
    original_format: str = ""
    raw_vertex_records: tuple[bytes, ...] = ()


@dataclass(frozen=True, slots=True)
class IndexBuffer:
    indices: tuple[int, ...] = ()
    index_format: str = "u16"
    original_offset: int = -1
    original_count: int = 0


@dataclass(frozen=True, slots=True)
class MeshAssetSubmesh:
    submesh_index: int
    stable_id: str
    name: str = ""
    material_slot_index: int = -1
    vertex_buffer: VertexBuffer = field(default_factory=VertexBuffer)
    index_buffer: IndexBuffer = field(default_factory=IndexBuffer)
    source_vertex_map: tuple[int, ...] = ()
    source_index_map: tuple[int, ...] = ()
    original_descriptor_offset: int = -1
    original_vertex_offset: int = -1
    original_index_offset: int = -1
    original_vertex_stride: int = 0
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] = (
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
    )
    metadata: dict[str, Any] = field(default_factory=dict)
    unknown_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MeshLod:
    lod_index: int
    name: str
    submeshes: tuple[MeshAssetSubmesh, ...] = ()
    original_section_offset: int = -1
    original_section_size: int = 0
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] = (
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
    )
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MaterialSlot:
    index: int
    name: str = ""
    texture: str = ""


@dataclass(frozen=True, slots=True)
class MeshAsset:
    source_path: str = ""
    source_format: str = ""
    original_file_hash: str = ""
    original_file_size: int = 0
    asset_id: str = ""
    lods: tuple[MeshLod, ...] = ()
    material_slots: tuple[MaterialSlot, ...] = ()
    skeleton_info: dict[str, Any] = field(default_factory=dict)
    binary_layout: BinaryLayout = field(default_factory=BinaryLayout)
    unknown_sections: tuple[MeshFileSection, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    layout_confidence: str = LAYOUT_CONFIDENCE_INFERRED

    @property
    def parse_confidence(self) -> str:
        return self.layout_confidence


@dataclass(frozen=True, slots=True)
class MeshValidationIssue:
    severity: str
    code: str
    message: str
    lod_index: int = -1
    submesh_index: int = -1
    expected: Any = None
    actual: Any = None


@dataclass(frozen=True, slots=True)
class MeshValidationResult:
    issues: tuple[MeshValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.blocking_issues

    @property
    def blocking_issues(self) -> tuple[MeshValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity in {"error", "fatal"})

    @property
    def fatal_issues(self) -> tuple[MeshValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "fatal")


def validate_mesh_asset_rebuild(
    original: MeshAsset,
    edited: MeshAsset,
    *,
    allow_topology_change: bool = False,
) -> MeshValidationResult:
    """Validate that an edited asset can be rebuilt into the original layout."""
    issues: list[MeshValidationIssue] = []
    if original.layout_confidence == LAYOUT_CONFIDENCE_FALLBACK_SCAN:
        _add(
            issues,
            "fatal",
            "FALLBACK_SCAN_REBUILD_BLOCKED",
            "Fallback-scan mesh layouts are preview-only until explicitly overridden.",
            expected=LAYOUT_CONFIDENCE_EXACT,
            actual=original.layout_confidence,
        )
    if not original.lods:
        _add(issues, "fatal", "EMPTY_MESH_ASSET", "MeshAsset has no LODs.")
    if len(original.lods) != len(edited.lods):
        _add(issues, "fatal", "LOD_COUNT_CHANGED", "LOD count changed.", expected=len(original.lods), actual=len(edited.lods))
    if len(original.material_slots) != len(edited.material_slots):
        _add(
            issues,
            "error",
            "MATERIAL_SLOT_COUNT_CHANGED",
            "Material slot count changed.",
            expected=len(original.material_slots),
            actual=len(edited.material_slots),
        )
    if original.unknown_sections != edited.unknown_sections:
        _add(issues, "error", "UNKNOWN_SECTIONS_CHANGED", "Unknown binary sections were not preserved.")

    for lod_index, (original_lod, edited_lod) in enumerate(zip(original.lods, edited.lods)):
        if len(original_lod.submeshes) != len(edited_lod.submeshes):
            _add(
                issues,
                "fatal",
                "SUBMESH_COUNT_CHANGED",
                "Submesh count changed.",
                lod_index=lod_index,
                expected=len(original_lod.submeshes),
                actual=len(edited_lod.submeshes),
            )
            continue
        for submesh_index, (original_submesh, edited_submesh) in enumerate(zip(original_lod.submeshes, edited_lod.submeshes)):
            _validate_submesh(
                issues,
                original_submesh,
                edited_submesh,
                lod_index=lod_index,
                submesh_index=submesh_index,
                allow_topology_change=allow_topology_change,
            )
    return MeshValidationResult(tuple(issues))


def _validate_submesh(
    issues: list[MeshValidationIssue],
    original: MeshAssetSubmesh,
    edited: MeshAssetSubmesh,
    *,
    lod_index: int,
    submesh_index: int,
    allow_topology_change: bool,
) -> None:
    original_vertex_count = len(original.vertex_buffer.vertices)
    edited_vertex_count = len(edited.vertex_buffer.vertices)
    original_index_count = len(original.index_buffer.indices)
    edited_index_count = len(edited.index_buffer.indices)
    original_source_index_count = _source_index_count(original)
    edited_source_index_count = _source_index_count(edited)

    if not allow_topology_change and original_vertex_count != edited_vertex_count:
        _add(
            issues,
            "error",
            "SUBMESH_VERTEX_COUNT_CHANGED",
            "Submesh vertex count changed.",
            lod_index=lod_index,
            submesh_index=submesh_index,
            expected=original_vertex_count,
            actual=edited_vertex_count,
        )
    if not allow_topology_change and original_index_count != edited_index_count:
        _add(
            issues,
            "error",
            "SUBMESH_INDEX_COUNT_CHANGED",
            "Submesh index count changed.",
            lod_index=lod_index,
            submesh_index=submesh_index,
            expected=original_index_count,
            actual=edited_index_count,
        )
    if not allow_topology_change and original_source_index_count != edited_source_index_count:
        _add(
            issues,
            "error",
            "SOURCE_INDEX_COUNT_CHANGED",
            "Submesh source index count changed.",
            lod_index=lod_index,
            submesh_index=submesh_index,
            expected=original_source_index_count,
            actual=edited_source_index_count,
        )
    original_stride = int(original.original_vertex_stride or 0)
    edited_stride = int(edited.original_vertex_stride or 0)
    if original_stride > 0 and edited_stride != original_stride:
        _add(
            issues,
            "error",
            "VERTEX_STRIDE_CHANGED",
            "Original vertex stride changed.",
            lod_index=lod_index,
            submesh_index=submesh_index,
            expected=original_stride,
            actual=edited_stride if edited_stride > 0 else "missing",
        )
    original_raw_records = original.vertex_buffer.raw_vertex_records
    edited_raw_records = edited.vertex_buffer.raw_vertex_records
    if original_raw_records and edited_raw_records != original_raw_records:
        _add(
            issues,
            "error",
            "RAW_VERTEX_RECORDS_CHANGED",
            "Original raw vertex records were not preserved.",
            lod_index=lod_index,
            submesh_index=submesh_index,
            expected=len(original_raw_records),
            actual=len(edited_raw_records) if len(edited_raw_records) != len(original_raw_records) else "changed",
        )
    for attr, code, message in (
        ("original_descriptor_offset", "SOURCE_DESCRIPTOR_OFFSET_CHANGED", "Original descriptor offset changed."),
        ("original_vertex_offset", "SOURCE_VERTEX_OFFSET_CHANGED", "Original vertex offset changed."),
        ("original_index_offset", "SOURCE_INDEX_OFFSET_CHANGED", "Original index offset changed."),
    ):
        original_value = _known_offset(getattr(original, attr))
        if original_value is None:
            continue
        edited_value = _known_offset(getattr(edited, attr))
        if edited_value != original_value:
            _add(
                issues,
                "error",
                code,
                message,
                lod_index=lod_index,
                submesh_index=submesh_index,
                expected=original_value,
                actual=edited_value if edited_value is not None else "missing",
            )

    for vertex in edited.vertex_buffer.vertices:
        if not _finite_vec3(vertex.position):
            _add(issues, "fatal", "INVALID_VERTEX_POSITION", "Vertex position is NaN, infinite, or malformed.", lod_index=lod_index, submesh_index=submesh_index)
            break

    if any(index < 0 or index >= edited_vertex_count for index in edited.index_buffer.indices):
        _add(issues, "fatal", "INVALID_INDEX_RANGE", "Index buffer references a missing vertex.", lod_index=lod_index, submesh_index=submesh_index)

    if _has_uvs(original) and not _has_complete_uvs(edited):
        _add(issues, "error", "UV_DATA_MISSING", "Original UV channel is not preserved.", lod_index=lod_index, submesh_index=submesh_index)
    if _has_normals(original) and not _has_complete_normals(edited):
        _add(issues, "error", "NORMAL_DATA_MISSING", "Original normals are not preserved.", lod_index=lod_index, submesh_index=submesh_index)
    if _has_tangents(original) and not _has_complete_tangents(edited):
        _add(issues, "error", "TANGENT_DATA_MISSING", "Original tangent data is not preserved.", lod_index=lod_index, submesh_index=submesh_index)
    if _has_skinning(original) and _skinning_rows(edited) != _skinning_rows(original):
        _add(issues, "error", "BONE_DATA_CHANGED", "Bone indices or weights changed.", lod_index=lod_index, submesh_index=submesh_index)

    if len(edited.source_vertex_map) != edited_vertex_count or any(value < 0 for value in edited.source_vertex_map):
        _add(issues, "fatal", "SOURCE_VERTEX_MAP_MISSING", "Each edited vertex must map back to an original source vertex.", lod_index=lod_index, submesh_index=submesh_index)
    if (
        len(edited.source_index_map) != edited_source_index_count
        or any(value < 0 or value >= max(edited_source_index_count, 1) for value in edited.source_index_map)
    ):
        _add(issues, "fatal", "SOURCE_INDEX_MAP_MISSING", "Each edited index must map back to an original source index.", lod_index=lod_index, submesh_index=submesh_index)
    if original.unknown_fields != edited.unknown_fields:
        _add(issues, "error", "UNKNOWN_FIELDS_CHANGED", "Unknown submesh fields were not preserved.", lod_index=lod_index, submesh_index=submesh_index)


def _add(
    issues: list[MeshValidationIssue],
    severity: str,
    code: str,
    message: str,
    *,
    lod_index: int = -1,
    submesh_index: int = -1,
    expected: Any = None,
    actual: Any = None,
) -> None:
    issues.append(MeshValidationIssue(severity, code, message, lod_index, submesh_index, expected, actual))


def _finite_vec3(value: object) -> bool:
    return (
        isinstance(value, (tuple, list))
        and len(value) >= 3
        and all(isinstance(component, (int, float)) and math.isfinite(float(component)) for component in value[:3])
    )


def _source_index_count(submesh: MeshAssetSubmesh) -> int:
    return int(submesh.index_buffer.original_count or len(submesh.index_buffer.indices))


def _known_offset(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None


def _has_uvs(submesh: MeshAssetSubmesh) -> bool:
    return any(vertex.uv0 is not None for vertex in submesh.vertex_buffer.vertices)


def _has_complete_uvs(submesh: MeshAssetSubmesh) -> bool:
    return all(vertex.uv0 is not None for vertex in submesh.vertex_buffer.vertices)


def _has_normals(submesh: MeshAssetSubmesh) -> bool:
    return any(vertex.normal is not None for vertex in submesh.vertex_buffer.vertices)


def _has_complete_normals(submesh: MeshAssetSubmesh) -> bool:
    return all(vertex.normal is not None for vertex in submesh.vertex_buffer.vertices)


def _has_tangents(submesh: MeshAssetSubmesh) -> bool:
    return any(vertex.tangent is not None for vertex in submesh.vertex_buffer.vertices)


def _has_complete_tangents(submesh: MeshAssetSubmesh) -> bool:
    return all(vertex.tangent is not None for vertex in submesh.vertex_buffer.vertices)


def _has_skinning(submesh: MeshAssetSubmesh) -> bool:
    return any(vertex.bone_indices or vertex.bone_weights for vertex in submesh.vertex_buffer.vertices)


def _skinning_rows(submesh: MeshAssetSubmesh) -> tuple[tuple[tuple[int, ...], tuple[float, ...]], ...]:
    return tuple((vertex.bone_indices, vertex.bone_weights) for vertex in submesh.vertex_buffer.vertices)


__all__ = [
    "BinaryLayout",
    "IndexBuffer",
    "LAYOUT_CONFIDENCE_EXACT",
    "LAYOUT_CONFIDENCE_FALLBACK_SCAN",
    "LAYOUT_CONFIDENCE_INFERRED",
    "MaterialSlot",
    "MeshAsset",
    "MeshAssetSubmesh",
    "MeshFileSection",
    "MeshLod",
    "MeshValidationIssue",
    "MeshValidationResult",
    "MeshVertex",
    "VALIDATION_SEVERITIES",
    "VertexBuffer",
    "validate_mesh_asset_rebuild",
]
