"""Pure mesh-domain session and validation rules."""

from __future__ import annotations

from .editing import (
    MESH_EDIT_ACTIONS,
    MESH_EDIT_MODES,
    MeshEditCommand,
    MeshEditResult,
    MeshEditSelection,
    MeshEditSessionView,
)
from .compare import MeshBoundsSummary, MeshCompareSummary, MeshPartCompareSummary, compare_meshes
from .export_validation import (
    SUPPORTED_GAME_MESH_FORMATS,
    MeshExportValidationIssue,
    MeshExportValidationReport,
    validate_mesh_export,
)
from .parts import MeshPartSummary, MeshWorkspaceSummary, summarize_mesh_workspace
from .skeleton import (
    MeshAnimationClip,
    MeshAnimationKeyframe,
    MeshAnimationPlaybackSummary,
    MeshAnimationSequenceSegment,
    MeshAnimationTrack,
    MeshAuthoringStatusRow,
    MeshConstraintEvidenceSummary,
    MeshSkeletonBoneSummary,
    MeshSkeletonPoseSummary,
    MeshSkeletonSummary,
    MeshSkinningPartSummary,
    MeshVertexWeightSummary,
    mesh_animation_clip_from_document,
    mesh_pose_deformed_vertices,
    sample_mesh_animation_pose,
    summarize_mesh_animation_playback,
    summarize_mesh_skinning,
    summarize_skeleton_bones,
)
from .textures import MeshTextureEditTarget, selected_mesh_texture_edit_target
from .uv import MeshUvIslandSummary, MeshUvSummary, mesh_uv_lasso_selection, mesh_uv_region_selection, summarize_mesh_uvs

__all__ = [
    "MESH_EDIT_ACTIONS",
    "MESH_EDIT_MODES",
    "MeshEditCommand",
    "MeshEditResult",
    "MeshEditSelection",
    "MeshEditSessionView",
    "MeshBoundsSummary",
    "MeshCompareSummary",
    "MeshExportValidationIssue",
    "MeshExportValidationReport",
    "MeshPartSummary",
    "MeshPartCompareSummary",
    "MeshAnimationClip",
    "MeshAnimationKeyframe",
    "MeshAnimationPlaybackSummary",
    "MeshAnimationSequenceSegment",
    "MeshAnimationTrack",
    "MeshAuthoringStatusRow",
    "MeshConstraintEvidenceSummary",
    "MeshSkeletonBoneSummary",
    "MeshSkeletonPoseSummary",
    "MeshSkeletonSummary",
    "MeshSkinningPartSummary",
    "MeshVertexWeightSummary",
    "mesh_animation_clip_from_document",
    "mesh_pose_deformed_vertices",
    "MeshTextureEditTarget",
    "MeshUvIslandSummary",
    "MeshUvSummary",
    "MeshWorkspaceSummary",
    "SUPPORTED_GAME_MESH_FORMATS",
    "compare_meshes",
    "selected_mesh_texture_edit_target",
    "mesh_uv_lasso_selection",
    "mesh_uv_region_selection",
    "sample_mesh_animation_pose",
    "summarize_mesh_animation_playback",
    "summarize_mesh_skinning",
    "summarize_skeleton_bones",
    "summarize_mesh_uvs",
    "summarize_mesh_workspace",
    "validate_mesh_export",
]
