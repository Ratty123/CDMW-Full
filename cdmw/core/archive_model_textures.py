"""Compatibility surface for archive model texture resolution and preview binding."""

from __future__ import annotations

from cdmw.core.archive_model_texture_base_attach import _attach_model_texture_preview_paths
from cdmw.core.archive_model_texture_config import (
    FAST_ARCHIVE_PREVIEW_MAX_FACES as _FAST_ARCHIVE_PREVIEW_MAX_FACES,
    FAST_ARCHIVE_PREVIEW_TEXTURE_NOTE as _FAST_ARCHIVE_PREVIEW_TEXTURE_NOTE,
    INITIAL_MODEL_PREVIEW_RENDER_SETTINGS as _INITIAL_MODEL_PREVIEW_RENDER_SETTINGS,
    MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION as _MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION,
    MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION as _MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION,
    MODEL_TEXTURE_PREVIEW_PATH_CACHE as _MODEL_TEXTURE_PREVIEW_PATH_CACHE,
    MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT as _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT,
    MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK as _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK,
    MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES as _MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES,
    MODEL_TEXTURE_VISIBLE_FAMILY_SUFFIXES as _MODEL_TEXTURE_VISIBLE_FAMILY_SUFFIXES,
    set_model_texture_display_preview_max_dimension,
)
from cdmw.core.archive_model_texture_pbd import (
    _archive_entry_by_preferred_suffix,
    _attach_pbd_cloth_preview_to_model_preview,
    _collect_archive_model_pbd_sidecar_texts,
    _read_archive_pbd_config_text,
    _read_archive_pbd_material_text,
    _read_archive_text_entry,
    ensure_archive_preview_source,
    try_decode_text_like_archive_data,
)
from cdmw.core.archive_model_texture_reporting import (
    _build_model_preview_texture_slot_detail_text,
    _describe_model_related_file_label,
    _describe_model_texture_semantic_label,
    _merge_model_reference_semantic_label,
    _model_preview_material_decode_label,
    _model_preview_texture_slot_label,
    _model_reference_status_rank,
    _texture_reference_relation_metadata,
    build_archive_model_texture_references,
)
from cdmw.core.archive_model_texture_resolution import (
    _collect_model_texture_archive_entry_candidates,
    _ensure_archive_model_texture_preview_path,
    _model_texture_semantic_priority,
    _prefetch_archive_model_texture_preview_paths,
    _resolve_model_texture_archive_entry,
    _score_model_texture_archive_candidate,
)
from cdmw.core.archive_model_texture_semantics import (
    _append_model_preview_material_input,
    _archive_model_component_alias_stems,
    _has_explicit_model_texture_reference,
    _infer_model_preview_normal_strength,
    _infer_model_preview_texture_slot,
    _is_placeholder_model_texture,
    _is_visible_model_texture_type,
    _iter_model_sidecar_binding_submesh_keys,
    _iter_model_submesh_reference_candidates,
    _iter_model_texture_family_reference_candidates,
    _iter_model_texture_reference_candidates,
    _iter_model_texture_slot_family_reference_candidates,
    _iter_parsed_model_submeshes,
    _looks_like_technical_model_texture,
    _match_model_texture_slot_family_suffix,
    _model_sidecar_binding_matches_source_component,
    _model_texture_candidate_slot_priority,
    _refine_model_texture_semantic_from_hint,
    _resolve_model_texture_semantic_details,
    _resolve_model_texture_semantics,
    _set_model_preview_texture_slot,
    _sidecar_binding_linked_model_path,
)
from cdmw.core.archive_model_texture_sidecar_attach import _attach_model_sidecar_texture_preview_paths
from cdmw.core.archive_model_texture_sidecar_rules import (
    _apply_model_sidecar_base_preview,
    _is_low_authority_model_base_texture,
    _mesh_existing_base_is_sidecar_identity,
    _mesh_preview_base_is_low_authority,
    _model_preview_base_texture_quality,
    _model_preview_sidecar_material_color,
    _model_preview_sidecar_tint,
    _model_preview_sidecar_uv_scale,
)
from cdmw.core.archive_model_texture_support_attach import _attach_model_support_texture_preview_paths
