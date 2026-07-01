"""Typed mesh workflow requests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Tuple


@dataclass(frozen=True, slots=True)
class MeshSessionPlan:
    source_path: Path
    mode: str = "preview"
    archive_member: str = ""


@dataclass(slots=True)
class MeshImportSetupSelection:
    scene_path: Path
    import_mode: str
    supplemental_files: Tuple[Path, ...] = ()
    scene_import_result: Optional[SceneImportResult] = None
    original_mesh: Optional[ParsedMesh] = None
    preflight: Optional[MeshImportPreflight] = None
    source_label: str = ""
    preferred_rebuild_material_sidecar: Optional[bool] = None
    extra_supplemental_specs: Tuple[MeshImportSupplementalFileSpec, ...] = ()
    placement_review_title: str = ""
    placement_context_note: str = ""
    source_texture_evidence: Tuple[Mapping[str, object], ...] = ()
    defer_original_texture_preview: bool = False
    runtime_target_entry: Optional[ArchiveEntry] = None
    source_skeleton: object | None = None
    preferred_complete_source_swap: bool = False
    full_import_model_replacement: bool = False


@dataclass(slots=True, frozen=True)
class InGameMeshSwapScopeSelection:
    complete_swap: bool = False
    prefer_generated_sidecar: bool = True
    use_source_model_payload_directly: bool = False
    retarget_source_family_files: bool = False
    replace_target_sidecar_with_source: bool = False
    replace_target_appearance_with_source: bool = False
    use_character_swap_plan: bool = False
    include_physics: bool = False
    companion_entries: Tuple[ArchiveEntry, ...] = ()


@dataclass(slots=True, frozen=True)
class ModifyOriginalWorkflowSelection:
    create_workspace: bool = False
    workspace_parent: Optional[Path] = None
    include_family_files: bool = True
    open_workspace_after_create: bool = False


@dataclass(slots=True)
class PlacementWorkspacePreparation:
    target_entry: ArchiveEntry
    donor_entry: Optional[ArchiveEntry] = None
    target_graph: Optional[AssetFamilyGraph] = None
    target_references: Tuple[ArchiveModelTextureReference, ...] = ()
    donor_graph: Optional[AssetFamilyGraph] = None
    donor_references: Tuple[ArchiveModelTextureReference, ...] = ()


__all__ = [
    "InGameMeshSwapScopeSelection",
    "MeshImportSetupSelection",
    "MeshSessionPlan",
    "ModifyOriginalWorkflowSelection",
    "PlacementWorkspacePreparation",
]
