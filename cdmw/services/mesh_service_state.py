from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from cdmw.domain.mesh import (
    MeshAnimationClip,
    MeshEditCommand,
    MeshEditSelection,
    MeshExportValidationReport,
)
from cdmw.modding.mesh_parser import ParsedMesh


@dataclass(slots=True)
class _MeshVertexPositionDelta:
    submesh_index: int
    vertex_indices: Sequence[int]
    positions: tuple[tuple[float, float, float], ...]
    native_sparse_snapshot_id: str = ""
    before_positions_binary: Mapping[str, object] | None = None


@dataclass(slots=True)
class _MeshHistorySnapshot:
    mesh: ParsedMesh | None
    mode: str
    selection: MeshEditSelection
    edit_operations: tuple[object, ...] = ()
    vertex_position_deltas: tuple[_MeshVertexPositionDelta, ...] = ()
    native_submesh_snapshot: Mapping[str, object] | None = None
    native_editor_history: bool = False
    native_editor_stroke_id: str = ""
    history_action: str = ""
    history_label: str = ""
    selection_only: bool = False
    material_generation: int | None = None
    committed_texture_resources: tuple[_MeshCommittedTextureResource, ...] | None = None
    retained_bytes: int = 0


@dataclass(slots=True)
class _MeshRestoreOutcome:
    snapshot: _MeshHistorySnapshot
    changed_vertices_by_submesh: dict[int, Sequence[int] | set[int]] = field(default_factory=dict)
    native_preview_vertex_update_groups: tuple[Mapping[str, object], ...] = ()
    native_preview_triangle_groups: tuple[Mapping[str, object], ...] = ()
    topology_changed: bool = False
    affected_submesh_indices: set[int] = field(default_factory=set)
    submesh_count_delta: int = 0
    submesh_counts: tuple[tuple[int, int], ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class _NativeEditorApplyResult:
    affected: set[int]
    changed: dict[int, Sequence[int] | set[int]]
    metrics: dict[str, float] = field(default_factory=dict)
    native_preview_vertex_update_groups: tuple[Mapping[str, object], ...] = ()
    native_preview_triangle_groups: tuple[Mapping[str, object], ...] = ()
    native_stroke_id: str = ""
    native_stroke_phase: str = ""
    native_stroke_cancelled: bool = False
    topology_changed: bool | None = None
    submesh_count_delta: int = 0
    submesh_counts: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class _MeshCommittedTextureResource:
    resource_id: str
    channel: str
    affected_submeshes: tuple[int, ...]
    revision: int
    logical_path: str = ""
    source_dds_path: str = ""
    assigned_source_path: str = ""
    raw_bgra_path: str = ""
    width: int = 0
    height: int = 0
    row_pitch: int = 0


@dataclass(frozen=True, slots=True)
class MeshExportTextureSnapshot:
    resource_id: str
    channel: str
    affected_submeshes: tuple[int, ...]
    revision: int
    logical_path: str = ""
    width: int = 0
    height: int = 0
    row_pitch: int = 0
    dds_data: bytes = b""
    bgra_data: bytes = b""


@dataclass(frozen=True, slots=True)
class MeshExportSnapshot:
    session_id: str
    mesh_revision: int
    native_edit_revision: int
    material_generation: int
    texture_revisions: tuple[tuple[str, str, int], ...]
    mesh: ParsedMesh
    base_mesh: ParsedMesh | None
    original_data: bytes
    mesh_asset_parse_confidence: str = ""
    mesh_asset_source_hash: str = ""
    mesh_asset_source_size: int = 0
    mesh_asset_inferred_bone_count: int = 0
    skeleton_bone_count: int = 0
    no_op_roundtrip_report: Mapping[str, object] | None = None
    sidecar_warnings: tuple[object, ...] = ()
    edit_operations: tuple[object, ...] = ()
    requires_edit_operations: bool = False
    texture_resources: tuple[MeshExportTextureSnapshot, ...] = ()
    material_parameter_groups: tuple[Mapping[str, object], ...] = ()
    material_authority_fingerprint: str = ""
    material_authority_revision: int = 0


@dataclass(frozen=True, slots=True)
class MeshPreparedWorkingMeshReplacement:
    """Fully prepared replacement that can be committed by revision in one lock."""

    session_id: str
    expected_revision: int
    working_mesh: ParsedMesh
    selection: MeshEditSelection
    previous_working_mesh: ParsedMesh
    previous_selection: MeshEditSelection
    validation_report: MeshExportValidationReport
    previous_sidecar_warnings: tuple[object, ...] = ()
    previous_edit_operations: tuple[object, ...] = ()
    previous_requires_edit_operations: bool = False
    sidecar_warnings: tuple[object, ...] = ()
    edit_operations: tuple[object, ...] = ()
    requires_edit_operations: bool = False


@dataclass(slots=True)
class _MeshEditSession:
    session_id: str
    base_mesh: ParsedMesh
    working_mesh: ParsedMesh
    original_data: bytes = b""
    mesh_asset_parse_confidence: str = ""
    mesh_asset_source_hash: str = ""
    mesh_asset_source_size: int = 0
    mesh_asset_inferred_bone_count: int = 0
    no_op_roundtrip_report: Mapping[str, object] | None = None
    sidecar_warnings: tuple[object, ...] = ()
    edit_operations: tuple[object, ...] = ()
    requires_edit_operations: bool = False
    base_mesh_is_original_parse: bool = False
    mode: str = "object"
    selection: MeshEditSelection = field(default_factory=MeshEditSelection)
    skeleton: object | None = None
    skeleton_source: str = ""
    skeleton_descriptor_source: str = ""
    skeleton_variation_source: str = ""
    animation_constraint_source: str = ""
    animation_constraint_evidence: dict[str, object] = field(default_factory=dict)
    socket_source: str = ""
    pose_preview_enabled: bool = False
    selected_bone_index: int = -1
    bone_pose_rotations: dict[int, tuple[float, float, float]] = field(default_factory=dict)
    animation_clip: MeshAnimationClip | None = None
    animation_playback_enabled: bool = False
    animation_time_seconds: float = 0.0
    animation_loop: bool = True
    animation_speed: float = 1.0
    revision: int = 0
    material_generation: int = 0
    committed_texture_resources: dict[tuple[str, str], _MeshCommittedTextureResource] = field(default_factory=dict)
    resident_material_parameters: dict[int, dict[str, object]] = field(default_factory=dict)
    material_authority_fingerprint: str = ""
    material_authority_revision: int = 0
    texture_resource_root: Path | None = None
    export_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    closed: bool = False
    native_editor_session_ready: bool = False
    native_editor_selection_signature: tuple[object, ...] = ()
    native_editor_active_stroke_id: str = ""
    native_editor_mesh_signature: tuple[object, ...] = ()
    native_editor_mesh_dirty: bool = False
    native_editor_mesh_dirty_counts: tuple[tuple[int, int], ...] = ()
    undo_stack: list[_MeshHistorySnapshot] = field(default_factory=list)
    redo_stack: list[_MeshHistorySnapshot] = field(default_factory=list)
    native_history_undo_count: int = 0
    native_history_redo_count: int = 0
    native_history_retained_bytes: int = 0


@dataclass(slots=True)
class _MeshCommandExecution:
    session: _MeshEditSession
    command: MeshEditCommand
    action: str
    selection: MeshEditSelection
    service_started: float
    topology_before: tuple[tuple[int, int], ...] | None
    history_mode: str
    history_selection: MeshEditSelection
    pushed_history: bool
    defer_native_live_history: bool
    history_pushed: bool
    fallback_event_start: int
    result_metrics: dict[str, float]
    affected: set[int] = field(default_factory=set)
    changed: dict[int, Sequence[int] | set[int]] = field(default_factory=dict)
    used_native_editor_session: bool = False
    native_editor_result: _NativeEditorApplyResult | None = None
    native_preview_vertex_update_groups: tuple[Mapping[str, object], ...] = ()
    native_preview_triangle_groups: tuple[Mapping[str, object], ...] = ()
    native_submesh_counts: tuple[tuple[int, int], ...] = ()
