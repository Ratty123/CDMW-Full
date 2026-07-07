"""Pure Mesh Editor v2 edit operation contracts."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field


SAFE_MESH_EDIT_OPERATIONS = frozenset(
    {
        "replace_positions_same_count",
        "replace_normals_same_count",
        "replace_tangents_same_count",
        "replace_uv0_same_count",
        "scale_vertices",
        "translate_vertices",
        "rotate_vertices",
        "recompute_bounds",
        "preview_submesh_visibility",
    }
)
BLOCKED_MESH_EDIT_OPERATIONS = frozenset(
    {
        "vertex_count_change",
        "index_count_change",
        "submesh_count_change",
        "lod_count_change",
        "material_reassignment",
        "bone_remapping",
        "skeleton_change",
        "automatic_lod_regeneration",
        "topology_replacement",
    }
)
_SAME_COUNT_OPERATIONS = frozenset(
    {
        "replace_positions_same_count",
        "replace_normals_same_count",
        "replace_tangents_same_count",
        "replace_uv0_same_count",
    }
)
_SOURCE_MAPPED_OPERATIONS = _SAME_COUNT_OPERATIONS | frozenset(
    {
        "scale_vertices",
        "translate_vertices",
        "rotate_vertices",
    }
)
_OPERATION_CHANGED_CHANNELS = {
    "replace_positions_same_count": "positions",
    "scale_vertices": "positions",
    "translate_vertices": "positions",
    "rotate_vertices": "positions",
    "replace_normals_same_count": "normals",
    "replace_tangents_same_count": "tangents",
    "replace_uv0_same_count": "uv0",
    "recompute_bounds": "bounds",
    "preview_submesh_visibility": "visibility",
}


@dataclass(frozen=True, slots=True)
class MeshEditOperation:
    operation: str
    lod_index: int = 0
    submesh_index: int = -1
    vertex_count: int = 0
    source: str = ""
    created_by: str = "Mesh Editor v2"
    metadata: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "MeshEditOperation":
        return cls(
            operation=str(payload.get("operation", "") or "").strip(),
            lod_index=_coerce_index(payload.get("lod_index"), default=0),
            submesh_index=_coerce_index(payload.get("submesh_index"), default=-1),
            vertex_count=_coerce_index(payload.get("vertex_count"), default=0),
            source=str(payload.get("source", "") or "").strip(),
            created_by=str(payload.get("created_by", "") or "Mesh Editor v2").strip() or "Mesh Editor v2",
            metadata=dict(payload.get("metadata") or {}) if isinstance(payload.get("metadata"), Mapping) else {},
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "operation": self.operation,
            "lod_index": self.lod_index,
            "submesh_index": self.submesh_index,
            "vertex_count": self.vertex_count,
            "source": self.source,
            "created_by": self.created_by,
        }
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class MeshEditOperationIssue:
    severity: str
    code: str
    message: str
    operation_index: int = -1
    submesh_index: int = -1


def mesh_edit_operations_from_dicts(values: Iterable[object]) -> tuple[MeshEditOperation, ...]:
    result: list[MeshEditOperation] = []
    for value in values or ():
        if isinstance(value, MeshEditOperation):
            result.append(value)
        elif isinstance(value, Mapping):
            result.append(MeshEditOperation.from_dict(value))
    return tuple(result)


def mesh_edit_operations_to_dicts(values: Iterable[MeshEditOperation]) -> tuple[dict[str, object], ...]:
    return tuple(operation.to_dict() for operation in values)


def validate_mesh_edit_operations(
    operations: Iterable[object],
    *,
    mesh: object | None = None,
    allowed_operations: Iterable[object] | None = None,
) -> tuple[MeshEditOperationIssue, ...]:
    normalized = mesh_edit_operations_from_dicts(operations)
    allowed = _operation_set(allowed_operations) if allowed_operations is not None else None
    submeshes = tuple(getattr(mesh, "submeshes", ()) or ()) if mesh is not None else ()
    issues: list[MeshEditOperationIssue] = []
    for operation_index, operation in enumerate(normalized):
        name = _operation_name(operation.operation)
        if not name:
            _add(issues, "blocker", "missing_edit_operation", "Edit operation is missing.", operation_index, operation.submesh_index)
            continue
        if name in BLOCKED_MESH_EDIT_OPERATIONS:
            _add(
                issues,
                "blocker",
                "blocked_edit_operation",
                f"Edit operation is blocked by default: {name}.",
                operation_index,
                operation.submesh_index,
            )
        elif name not in SAFE_MESH_EDIT_OPERATIONS:
            _add(
                issues,
                "blocker",
                "unsupported_edit_operation",
                f"Edit operation is not supported for safe rebuild: {name}.",
                operation_index,
                operation.submesh_index,
            )
        if allowed is not None and name not in allowed:
            _add(
                issues,
                "blocker",
                "disallowed_edit_operation",
                f"Edit operation is not allowed by sidecar rules: {name}.",
                operation_index,
                operation.submesh_index,
            )
        if mesh is not None:
            _validate_operation_target(issues, operation, operation_index, name, submeshes)
    return tuple(issues)


def validate_mesh_edit_operation_coverage(
    operations: Iterable[object],
    *,
    mesh: object | None,
    original_mesh: object | None,
) -> tuple[MeshEditOperationIssue, ...]:
    normalized = mesh_edit_operations_from_dicts(operations)
    if not normalized or mesh is None or original_mesh is None:
        return ()
    allowed_by_target: dict[tuple[int, int], set[str]] = {}
    for operation in normalized:
        channel = mesh_edit_operation_changed_channel(operation.operation)
        if not channel:
            continue
        allowed_by_target.setdefault((operation.lod_index, operation.submesh_index), set()).add(channel)

    issues: list[MeshEditOperationIssue] = []
    original_lods = _submeshes_by_lod(original_mesh)
    edited_lods = _submeshes_by_lod(mesh)
    for lod_index in range(max(len(original_lods), len(edited_lods))):
        before_submeshes = original_lods[lod_index] if lod_index < len(original_lods) else ()
        after_submeshes = edited_lods[lod_index] if lod_index < len(edited_lods) else ()
        if len(before_submeshes) != len(after_submeshes):
            _add(
                issues,
                "blocker",
                "untracked_edit_channel",
                "Mesh submesh count changed without a matching safe edit operation.",
                -1,
                -1,
            )
        for submesh_index in range(max(len(before_submeshes), len(after_submeshes))):
            before = before_submeshes[submesh_index] if submesh_index < len(before_submeshes) else None
            after = after_submeshes[submesh_index] if submesh_index < len(after_submeshes) else None
            allowed = allowed_by_target.get((lod_index, submesh_index), set())
            for channel in _changed_submesh_channels(before, after):
                if channel in allowed:
                    continue
                _add(
                    issues,
                    "blocker",
                    "untracked_edit_channel",
                    f"Mesh channel changed without a matching safe edit operation: {channel}.",
                    -1,
                    submesh_index,
                )
    return tuple(issues)


def mesh_edit_operation_changed_channel(operation: object) -> str:
    return _OPERATION_CHANGED_CHANNELS.get(_operation_name(operation), "")


def _validate_operation_target(
    issues: list[MeshEditOperationIssue],
    operation: MeshEditOperation,
    operation_index: int,
    name: str,
    submeshes: Sequence[object],
) -> None:
    if operation.lod_index != 0:
        _add(
            issues,
            "blocker",
            "unsupported_operation_lod",
            "Only LOD 0 edit operations are supported by the current rebuild path.",
            operation_index,
            operation.submesh_index,
        )
    if operation.submesh_index < 0 or operation.submesh_index >= len(submeshes):
        _add(
            issues,
            "blocker",
            "invalid_operation_submesh",
            "Edit operation targets a missing submesh.",
            operation_index,
            operation.submesh_index,
        )
        return
    if name in _SOURCE_MAPPED_OPERATIONS:
        submesh = submeshes[operation.submesh_index]
        actual = len(tuple(getattr(submesh, "vertices", ()) or ()))
        if operation.vertex_count != actual:
            _add(
                issues,
                "blocker",
                "operation_vertex_count_mismatch",
                f"Edit operation expected {operation.vertex_count} vertices but submesh has {actual}.",
                operation_index,
                operation.submesh_index,
            )
        source_map = tuple(getattr(submesh, "source_vertex_map", ()) or ())
        if len(source_map) != actual:
            _add(
                issues,
                "blocker",
                "operation_source_map_missing",
                "Safe edit operation requires a source vertex map for every edited vertex.",
                operation_index,
                operation.submesh_index,
            )
        elif any(_coerce_index(value, default=-1) < 0 for value in source_map):
            _add(
                issues,
                "blocker",
                "operation_source_map_invalid",
                "Same-count edit operation source vertex map contains invalid entries.",
                operation_index,
                operation.submesh_index,
            )


def _operation_set(values: Iterable[object] | None) -> frozenset[str]:
    return frozenset(name for name in (_operation_name(value) for value in values or ()) if name)


def _operation_name(value: object) -> str:
    return str(value or "").strip().casefold()


def _submeshes_by_lod(mesh: object) -> tuple[tuple[object, ...], ...]:
    lod_levels = tuple(getattr(mesh, "lod_levels", ()) or ())
    if lod_levels:
        return tuple(tuple(level or ()) for level in lod_levels)
    return (tuple(getattr(mesh, "submeshes", ()) or ()),)


def _changed_submesh_channels(before: object | None, after: object | None) -> tuple[str, ...]:
    if before is None or after is None:
        return ("topology",)
    fields = (
        ("vertices", "positions"),
        ("normals", "normals"),
        ("tangents", "tangents"),
        ("uvs", "uv0"),
        ("faces", "indices"),
        ("bone_indices", "bone_indices"),
        ("bone_weights", "bone_weights"),
    )
    changed = [
        channel
        for attr, channel in fields
        if tuple(getattr(before, attr, ()) or ()) != tuple(getattr(after, attr, ()) or ())
    ]
    if str(getattr(before, "material", "") or "") != str(getattr(after, "material", "") or ""):
        changed.append("material")
    if str(getattr(before, "texture", "") or "") != str(getattr(after, "texture", "") or ""):
        changed.append("texture")
    if int(getattr(before, "vertex_count", 0) or 0) != int(getattr(after, "vertex_count", 0) or 0):
        changed.append("vertex_count")
    if int(getattr(before, "face_count", 0) or 0) != int(getattr(after, "face_count", 0) or 0):
        changed.append("index_count")
    return tuple(changed)


def _coerce_index(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return default
        return int(value)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default


def _add(
    issues: list[MeshEditOperationIssue],
    severity: str,
    code: str,
    message: str,
    operation_index: int,
    submesh_index: int,
) -> None:
    issues.append(
        MeshEditOperationIssue(
            severity=severity,
            code=code,
            message=message,
            operation_index=operation_index,
            submesh_index=submesh_index,
        )
    )


__all__ = [
    "BLOCKED_MESH_EDIT_OPERATIONS",
    "SAFE_MESH_EDIT_OPERATIONS",
    "MeshEditOperation",
    "MeshEditOperationIssue",
    "mesh_edit_operation_changed_channel",
    "mesh_edit_operations_from_dicts",
    "mesh_edit_operations_to_dicts",
    "validate_mesh_edit_operation_coverage",
    "validate_mesh_edit_operations",
]
