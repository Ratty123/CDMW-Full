"""Compatibility exports for static mesh replacement helpers."""

from __future__ import annotations

from .logging import get_logger
from .mesh_parser import ParsedMesh, SubMesh, _compute_smooth_normals, inspect_mesh_binary_layout
from .static_mesh_analysis import (
    _append_mapping_errors,
    _append_mapping_summary,
    _append_static_warnings,
    _base_report,
    _format_static_report_failure,
    _replacement_mesh_from_options,
    analyze_static_replacement,
    describe_static_placement_context,
    effective_static_replacement_source_mesh,
)
from .static_mesh_build import build_static_mesh_replacement, build_static_replacement_preview_mesh
from .static_mesh_clone import _clone_parsed_mesh_fast, _clone_submesh_fast
from .static_mesh_geometry import (
    _GRIP_MARKER_NAMES,
    _TIP_MARKER_NAMES,
    _append_alignment_summary,
    _apply_alignment_roll,
    _apply_transform,
    _axis_length,
    _axis_vector,
    _bbox,
    _center,
    _compute_anchor_alignment,
    _cross,
    _dims,
    _dominant_axis,
    _dot,
    _find_marker_anchor_any,
    _format_vec,
    _infer_grip_anchor,
    _infer_tip_anchor,
    _is_marker_submesh,
    _mul,
    _normalize,
    _rotate_between,
    _rotate_xyz,
    _sub,
)
from .static_mesh_mapping import (
    _StaticMappingSpatialCache,
    _append_special_runtime_slot_mapping_findings,
    _best_target_index_for_source,
    _best_target_match_for_source,
    _confidence_label,
    _mapping_confidence_score,
    _name_text,
    _normalized_label,
    _normalized_submesh_center,
    _semantic_tokens,
    _source_matches_special_runtime_slot,
    _special_runtime_slot_tokens,
    _submesh_size_similarity_score,
    _submesh_spatial_similarity_score,
    _token_score,
    infer_static_replacement_part_role,
    suggest_static_submesh_mappings,
)
from .static_mesh_output_plan import (
    _STATIC_REPLACEMENT_VERTEX_LIMIT,
    _atlas_rects_for_source_groups,
    _complete_swap_atlas_mode,
    _dense_export_mode,
    _partition_source_indices_for_vertex_limit,
    _source_vertex_count,
    plan_static_output_draw_sections,
)
from .static_mesh_runtime_builder import (
    _build_mapped_replacement_mesh,
    _replacement_mesh_with_original_part_copies,
    _transformed_replacement_sources,
    source_delta_for_transformed_delta,
    source_distance_for_transformed_distance,
    source_point_for_transformed_point,
)
from .static_mesh_source_parts import (
    _apply_source_part_adjustment,
    _apply_texture_uv_transform,
    _independent_parts_for_options,
    _independent_source_indices,
    _source_part_adjustments_by_index,
    _texture_uv_transform_for_submesh,
    _texture_uv_transforms_by_key,
    _uv_pair,
)
from .static_mesh_types import (
    StaticDonorMaterialPlan,
    StaticDonorMaterialTextureBinding,
    StaticIndependentPart,
    StaticMaterialAtlasRect,
    StaticMeshReplacementOptions,
    StaticMeshReplacementReport,
    StaticOriginalPartCopy,
    StaticOutputDrawSection,
    StaticReplacementTransform,
    StaticSourceMaterialTextureOverride,
    StaticSourcePartAdjustment,
    StaticSubmeshMapping,
    StaticTextureSlotOverride,
    StaticTextureUvTransform,
)

logger = get_logger("core.static_mesh_replacer")
