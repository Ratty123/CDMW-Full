from __future__ import annotations

import fnmatch
import gc
import hashlib
import html
import json
import math
import os
import pickle
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import bisect
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Iterator, Mapping
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, fields, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, BinaryIO, Callable, Dict, List, Optional, Sequence, Tuple

try:
    import lz4.block as lz4_block
except ImportError:
    lz4_block = None

try:
    import winreg
except ImportError:
    winreg = None

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
except ImportError:
    Cipher = None
    algorithms = None

from cdmw.constants import *
from cdmw.models import *
from cdmw.core.common import *
from cdmw.core.model_preview import (
    build_pam_model_preview,
    build_pamlod_model_preview,
    ensure_model_preview_is_reasonable,
)
from cdmw.core.pat_decoder import build_pat_model_preview
from cdmw.core.pbd_cloth import (
    PbdConfigMaterial,
    build_cloth_preview_from_sidecars,
    collect_pbd_sidecar_hints,
)
from cdmw.core.archive_modding import (
    build_hkx_descriptor_hint_from_xml_text,
    build_hkx_editable_geometry_document,
    build_hkx_model_preview_from_document,
    build_hkx_physics_overlay_from_document,
    build_hkx_preview,
    build_mesh_preview_from_bytes,
    build_pab_preview,
    merge_hkx_physics_overlays,
)
from cdmw.core.texture_pipeline.inspection import inspect_crimson_dds, parse_dds
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.core.temp_cache import app_temp_cache_path, request_app_temp_cache_prune
from cdmw.core.upscale_profiles import (
    classify_texture_type,
    derive_texture_group_key,
    infer_texture_semantics,
    normalize_texture_reference_for_sidecar_lookup,
    parse_material_sidecar_profile,
    parse_texture_sidecar_bindings,
)
from cdmw.core.table_catalog import (
    table_catalog_cache_metadata,
    table_catalog_cache_metadata_matches,
    table_field_label,
)
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.modding.skeleton_parser import iter_pab_candidate_basenames, parse_pab

if TYPE_CHECKING:
    from cdmw.modding.mesh_parser import ParsedMesh

# Archive browser tree/state and PATHC preview helpers live in archive_preview_support.
from cdmw.core.archive_preview_support import (
    _PATHC_COLLECTION_CACHE,
    build_archive_structure_children_map,
    build_archive_tree_index,
    prepare_archive_browser_state,
    PathcCollection,
    load_pathc_collection,
    resolve_archive_meta_root,
    resolve_archive_pathc_path,
    get_archive_partial_dds_header,
    _format_pathc_block_infos,
    _format_pathc_lookup_detail,
    build_archive_pathc_preview,
    build_archive_pathc_lookup_detail_for_entry,
)

# Archive scan/cache helpers live in archive_scan_cache.
from cdmw.core.archive_scan_cache import (
    _ARCHIVE_SCAN_CACHE_MAGIC,
    _ARCHIVE_SCAN_CACHE_VERSION,
    _ARCHIVE_SCAN_SHARD_CACHE_MAGIC,
    _ARCHIVE_SCAN_SHARD_CACHE_VERSION,
    _HKX_CONTEXT_MODEL_PREVIEW_CACHE_LIMIT,
    _HKX_CONTEXT_MODEL_PREVIEW_CACHE,
    _ARCHIVE_SCAN_CACHE_LEGACY_DIRNAMES,
    _ARCHIVE_SIDECAR_CACHE_MAGIC,
    _ARCHIVE_SIDECAR_CACHE_VERSION,
    _ARCHIVE_SIDECAR_ENTRY_SIGNATURE_FORMAT,
    _ARCHIVE_DERIVED_INDEX_CACHE_MAGIC,
    _ARCHIVE_DERIVED_INDEX_CACHE_VERSION,
    _ARCHIVE_ITEM_ICON_THUMBNAIL_CACHE_VERSION,
    _ARCHIVE_BASIC_INDEX_CACHE_MAGIC,
    _ARCHIVE_BASIC_INDEX_CACHE_VERSION,
    _ARCHIVE_BASIC_INDEX_SHARD_CACHE_MAGIC,
    _ARCHIVE_BASIC_INDEX_SHARD_CACHE_VERSION,
    _ARCHIVE_NAME_SEARCH_SHARD_META_VERSION,
    _ARCHIVE_ENTRY_METADATA_SIGNATURE_FORMAT,
    _ARCHIVE_DERIVED_INDEX_CACHE_MAX_SAFE_BYTES,
    _ARCHIVE_BASIC_INDEX_CACHE_MAX_SAFE_BYTES,
    _ARCHIVE_CACHE_ROOT_MAX_BYTES,
    _ARCHIVE_CACHE_ROOT_TARGET_BYTES,
    _ARCHIVE_CACHE_ROOT_PREFIXES,
    _ARCHIVE_ITEM_ICON_THUMBNAIL_CACHE_LOCK,
    _ARCHIVE_ITEM_ICON_THUMBNAIL_MANIFEST_CACHE,
    discover_pamt_files,
    resolve_archive_scan_cache_path,
    _archive_cache_root_digest,
    resolve_archive_scan_shard_cache_dir,
    resolve_archive_basic_index_shard_cache_dir,
    resolve_archive_name_search_shard_cache_dir,
    _archive_scan_shard_id,
    resolve_archive_sidecar_cache_path,
    resolve_archive_sidecar_cache_metadata_path,
    resolve_archive_derived_index_cache_path,
    resolve_archive_item_icon_thumbnail_cache_dir,
    resolve_archive_basic_index_cache_path,
    resolve_archive_name_search_index_cache_path,
    resolve_crimson_desert_executable,
    sha256_file,
    invalidate_archive_browser_cache,
    prune_archive_cache_root,
    _candidate_archive_scan_cache_paths,
    _archive_base_dir,
    _archive_relative_source_path,
    _archive_relative_source_path_cached,
    _collect_archive_scan_sources,
    _collect_archive_scan_sources_from_entries,
    _normalize_archive_source_rows,
    _normalize_archive_entry_metadata_signature,
    _archive_source_rows_from_paths,
    _update_archive_entry_metadata_row_hash,
    _archive_entry_metadata_signature_from_components,
    _archive_entry_metadata_from_entries,
    _archive_source_rows_match_files,
    _serialize_cache_payload,
    _deserialize_cache_payload,
    _deserialize_cache_payload_from_path,
    _write_raw_pickle_cache_payload_to_path,
    _serialize_archive_scan_cache_payload,
    _serialize_archive_sidecar_cache_payload,
    _deserialize_archive_scan_cache_payload,
    _deserialize_archive_scan_cache_payload_from_path,
    _deserialize_archive_sidecar_cache_payload,
    _deserialize_archive_derived_index_cache_payload_from_path,
    _deserialize_archive_basic_index_cache_payload_from_path,
    _deserialize_archive_scan_shard_cache_payload_from_path,
    _deserialize_archive_basic_index_shard_cache_payload_from_path,
    _write_archive_sidecar_cache_metadata,
    _read_archive_sidecar_cache_metadata,
    _archive_entry_cache_signature,
    archive_item_icon_thumbnail_cache_key,
    _archive_item_icon_thumbnail_manifest_path,
    _archive_item_icon_thumbnail_manifest_cache_key,
    _read_archive_item_icon_thumbnail_manifest,
    _write_archive_item_icon_thumbnail_manifest,
    load_archive_item_icon_thumbnail_cache,
    save_archive_item_icon_thumbnail_cache,
    _build_archive_entry_cache_signatures,
    _describe_archive_cache_metadata_mismatch,
    _record_timing,
    _archive_cache_row_for_entry,
    _archive_scan_cache_payload_components,
    _decode_archive_scan_cache_rows,
    _ArchiveEntryShardGroup,
    _archive_entry_shard_groups,
    _archive_scan_shard_cache_path,
    archive_scan_shard_cache_health,
    _delete_obsolete_archive_scan_cache_path,
    _write_archive_scan_shard_cache,
    _load_archive_scan_shard_cache,
    _scan_archive_pamt_shard,
    _full_scan_archive_entries_for_shards,
    _partition_entries_by_pamt_relative_path,
    _write_archive_scan_shards_from_entries,
    load_or_update_archive_scan_shards,
    save_archive_scan_cache,
    load_archive_scan_cache,
    scan_archive_entries_cached,
    _scan_archive_entries_cached_legacy,
)

# Archive model texture preview and reference helpers live in archive_model_textures.
from cdmw.core.archive_model_textures import (
    _INITIAL_MODEL_PREVIEW_RENDER_SETTINGS,
    _MODEL_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION,
    _MODEL_SUPPORT_TEXTURE_DISPLAY_PREVIEW_MAX_DIMENSION,
    _FAST_ARCHIVE_PREVIEW_MAX_FACES,
    _FAST_ARCHIVE_PREVIEW_TEXTURE_NOTE,
    _MODEL_TEXTURE_VISIBLE_FAMILY_SUFFIXES,
    _MODEL_TEXTURE_SUPPORT_FAMILY_SUFFIXES,
    set_model_texture_display_preview_max_dimension,
    _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LIMIT,
    _MODEL_TEXTURE_PREVIEW_PATH_CACHE,
    _MODEL_TEXTURE_PREVIEW_PATH_CACHE_LOCK,
    _collect_archive_model_pbd_sidecar_texts,
    _archive_entry_by_preferred_suffix,
    _read_archive_pbd_config_text,
    _read_archive_pbd_material_text,
    _attach_pbd_cloth_preview_to_model_preview,
    _iter_parsed_model_submeshes,
    _iter_model_submesh_reference_candidates,
    _iter_model_sidecar_binding_submesh_keys,
    _archive_model_component_alias_stems,
    _sidecar_binding_linked_model_path,
    _model_sidecar_binding_matches_source_component,
    _iter_model_texture_family_reference_candidates,
    _iter_model_texture_slot_family_reference_candidates,
    _iter_model_texture_reference_candidates,
    _match_model_texture_slot_family_suffix,
    _looks_like_technical_model_texture,
    _is_placeholder_model_texture,
    _has_explicit_model_texture_reference,
    _is_visible_model_texture_type,
    _resolve_model_texture_semantics,
    _resolve_model_texture_semantic_details,
    _refine_model_texture_semantic_from_hint,
    _infer_model_preview_texture_slot,
    _model_texture_candidate_slot_priority,
    _infer_model_preview_normal_strength,
    _set_model_preview_texture_slot,
    _append_model_preview_material_input,
    _score_model_texture_archive_candidate,
    _collect_model_texture_archive_entry_candidates,
    _model_texture_semantic_priority,
    _resolve_model_texture_archive_entry,
    _ensure_archive_model_texture_preview_path,
    _prefetch_archive_model_texture_preview_paths,
    _model_preview_sidecar_tint,
    _model_preview_sidecar_uv_scale,
    _model_preview_sidecar_material_color,
    _is_low_authority_model_base_texture,
    _model_preview_base_texture_quality,
    _mesh_preview_base_is_low_authority,
    _mesh_existing_base_is_sidecar_identity,
    _apply_model_sidecar_base_preview,
    _attach_model_sidecar_texture_preview_paths,
    _attach_model_texture_preview_paths,
    _attach_model_support_texture_preview_paths,
    _model_preview_texture_slot_label,
    _model_preview_material_decode_label,
    _build_model_preview_texture_slot_detail_text,
    _describe_model_texture_semantic_label,
    _describe_model_related_file_label,
    _merge_model_reference_semantic_label,
    _model_reference_status_rank,
    _texture_reference_relation_metadata,
    build_archive_model_texture_references,
)
# Archive model reference and sidecar binding helpers live in archive_model_references.
from cdmw.core.archive_model_references import (
    _ARCHIVE_TEXTURE_FAMILY_SUFFIXES,
    _ARCHIVE_MODEL_FAMILY_VARIANT_SUFFIXES,
    _ARCHIVE_ITEM_ICON_STEM_PREFIXES,
    _ARCHIVE_ATTACHMENT_SIDE_SUFFIXES,
    _ARCHIVE_ATTACHMENT_SIDE_METADATA_EXTENSIONS,
    _ARCHIVE_NUMBERED_MODEL_FAMILY_VARIANT_RE,
    _ARCHIVE_PREFAB_HELM_DESCRIPTOR_RE,
    _ARCHIVE_PLATE_HELM_MODEL_RE,
    _ARCHIVE_CHARACTER_EQUIPMENT_COMPONENT_RE,
    _ArchiveModelSidecarTextureBinding,
    _StructuredBinaryPreviewBundle,
    _BinarySidecarStringRecord,
    _MODEL_SIDECAR_PARSE_CACHE_LIMIT,
    _MODEL_SIDECAR_PARSE_CACHE,
    _MODEL_SIDECAR_REFERENCE_CACHE_LIMIT,
    _MODEL_SIDECAR_REFERENCE_CACHE,
    _MODEL_SIDECAR_PARSE_CACHE_LOCK,
    _normalize_model_texture_reference,
    _ARCHIVE_TEXTURE_FAMILY_STOP_TOKENS,
    _archive_reference_family_tokens,
    _archive_texture_family_mismatch_summary,
    _archive_texture_family_mismatch_reason,
    _normalize_model_submesh_reference,
    _is_anonymous_model_submesh_reference_key,
    extract_binary_dds_references,
    _humanize_model_texture_hint,
    _model_texture_hint_priority,
    _normalize_model_visible_texture_mode,
    _classify_model_sidecar_visible_binding,
    _allowed_model_sidecar_visible_classes,
    _model_sidecar_visible_class_priority,
    _model_texture_slot_hint_priority,
    _score_model_sidecar_entry_candidate,
    _score_model_related_entry_candidate,
    _extend_archive_related_target_basenames,
    _collect_same_stem_related_target_basenames,
    _strip_archive_model_family_variant_suffix,
    _iter_archive_prefab_equipment_family_stems,
    _iter_archive_attachment_side_family_stems,
    iter_archive_equipment_model_alias_stems,
    iter_archive_character_equipment_root_alias_stems,
    _collect_family_heuristic_target_basenames,
    _relation_group_for_kind,
    _relation_kind_for_entry,
    _build_archive_relation_metadata,
    _find_archive_model_related_entries,
    _find_archive_model_sidecar_entries,
    _parse_archive_model_sidecar_texture_bindings,
    _archive_entry_identity_signature,
    _archive_entry_pathc_identity_signature,
    _texconv_identity_signature,
    _extract_model_sidecar_entry_bindings_cached,
    _extract_archive_model_sidecar_texture_references,
)


# Archive filtering, sorting, and basic entry index helpers live in archive_filtering.
from cdmw.core.archive_filtering import (
    _COMMON_TECHNICAL_DDS_EXCLUDE_PATTERNS,
    _STRUCTURED_BINARY_IDENTIFIER_RE,
    _STRUCTURED_BINARY_ASSET_TOKEN_RE,
    _STRUCTURED_BINARY_ASSET_SEGMENT_RE,
    _STRUCTURED_BINARY_ASSET_REFERENCE_EXTENSIONS,
    archive_entry_is_previewable,
    archive_entry_matches_advanced_filters,
    _split_archive_filter_patterns,
    _archive_entry_item_alias_text,
    archive_entry_model_base_key_matches,
    archive_entry_item_name_match,
    archive_entry_role_label,
    archive_entry_role_display_text,
    archive_entry_override_state,
    normalize_archive_browser_sort_column,
    normalize_archive_browser_sort_order,
    archive_browser_sort_is_active,
    _ARCHIVE_BROWSER_NATURAL_SORT_RE,
    _archive_browser_natural_sort_key,
    archive_browser_entry_sort_key,
    sort_archive_entries_for_browser,
    _archive_entry_supports_item_alias_search,
    _archive_entry_has_item_alias_key,
    _archive_entry_item_alias_relevance_rank,
    _archive_item_alias_match_keys_for_patterns,
    _archive_entry_matches_text_pattern,
    _archive_alias_token_prefix_match,
    _archive_entry_matches_size_term,
    _archive_entry_content_text,
    _archive_search_term_matches_entry,
    _archive_search_query_matches_entry,
    _archive_search_query_matches_alias,
    _archive_item_alias_match_keys_for_query,
    _archive_entry_search_relevance_rank,
    _archive_entry_search_query_relevance_rank,
    _archive_entry_is_item_alias_expansion_source,
    _archive_item_alias_related_expansion_needed,
    _read_archive_entry_text_or_binary_for_reference_expansion,
    _expand_archive_filter_item_alias_related_entries,
    filter_archive_entries,
    count_archive_entries_with_extension,
    normalize_archive_structure_filter_value,
    archive_entry_path_parts,
    archive_entry_folder_parts,
    archive_entry_structure_prefixes,
    archive_entry_identity_key,
    archive_entry_is_mod_package,
    archive_entry_load_priority,
    active_archive_entry_for_virtual_path,
    order_archive_entries_by_active_overrides,
    build_archive_entry_path_index,
    build_archive_entry_basename_index,
    build_archive_entry_extension_index,
    build_archive_entry_role_index,
)

# Archive name-search indexes live in archive_name_search.
from cdmw.core.archive_name_search import (
    _ARCHIVE_SEARCH_DEFAULT_FIELD,
    _ARCHIVE_SEARCH_FIELDS,
    _ARCHIVE_SEARCH_SIZE_RE,
    ArchiveNameSearchIndex,
    ArchiveSearchQuery,
    ArchiveSearchTerm,
    _archive_name_search_alias_signature,
    _archive_name_search_aliases_for_token,
    _archive_name_search_embedded_source_tokens,
    _archive_name_search_native_min_entries,
    _archive_name_search_shard_binary_path,
    _archive_name_search_shard_meta_matches,
    _archive_name_search_shard_meta_path,
    _archive_name_search_shards_ready,
    _archive_name_search_text_match,
    _archive_name_search_token_matches,
    _archive_search_size_to_bytes,
    _archive_search_term_from_token,
    _archive_search_text_match,
    _archive_search_token_prefix_match,
    _archive_search_tokens,
    _build_archive_name_search_index_python,
    _load_archive_name_search_shards_trusted,
    _load_native_name_search_index_binary,
    _load_or_update_archive_name_search_shards,
    _read_archive_name_search_shard_meta,
    _sanitize_native_name_search_field,
    _strip_archive_search_quotes,
    _tokenize_archive_search_text,
    _try_build_archive_name_search_index_native,
    _write_archive_name_search_index_shard,
    _write_archive_name_search_shard_caches,
    _write_archive_name_search_shard_meta,
    _write_native_name_search_index_binary,
    archive_item_index_dependency_signature,
    build_archive_name_search_index,
    load_or_update_archive_name_search_shards,
    parse_archive_search_query,
)

# Archive format/parsing/decrypt and package discovery helpers live in archive_format.
from cdmw.core.archive_format import (
    _ARCHIVE_STRUCTURED_BINARY_PREVIEW_EXTENSIONS,
    _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS,
    CHACHA20_HASH_INITVAL,
    CHACHA20_IV_XOR,
    CHACHA20_XOR_DELTAS,
    _ARCHIVE_MATERIAL_SIDECAR_EXTENSIONS,
    _ARCHIVE_METADATA_XML_EXTENSIONS,
    _ARCHIVE_XML_LIKE_EXTENSIONS,
    _is_material_sidecar_extension,
    _PRINTABLE_BINARY_STRING_RE,
    _TEXT_DDS_REFERENCE_RE,
    _rot32,
    _add32,
    _sub32,
    _finalize_lookup3,
    calculate_pa_checksum,
    hashlittle,
    derive_chacha20_key_iv,
    crypt_chacha20_filename,
    _looks_like_plain_text_payload,
    _looks_like_paloc_payload,
    _looks_like_structured_binary_payload,
    _looks_like_decrypted_payload,
    try_decrypt_archive_entry_data,
    parse_steam_library_paths,
    parse_steam_appmanifest_installdir,
    _normalize_existing_path,
    discover_steam_roots,
    discover_windows_drive_roots,
    discover_non_steam_base_paths,
    discover_non_steam_archive_package_roots,
    _looks_like_archive_index_container,
    looks_like_archive_package_root,
    autodetect_archive_package_roots,
    VfsPathResolver,
    parse_archive_pamt,
    _parse_archive_pamt,
    scan_archive_entries,
    archive_entry_matches_filter,
    normalize_archive_extension_filter,
    archive_entry_role,
)

_ARCHIVE_SCAN_CACHE_SUPPORTED_VERSIONS = {3}
# Archive basic/derived index cache helpers live in archive_index_cache.
from cdmw.core.archive_index_cache import (
    _ARCHIVE_DERIVED_INDEX_CACHE_SUPPORTED_VERSIONS,
    _encode_archive_entry_index_rows,
    _decode_archive_entry_index_rows,
    _sort_archive_basename_index_values,
    _merge_archive_entry_index_rows,
    _archive_basic_index_shard_cache_path,
    _archive_index_row_mapping_to_rows,
    _build_archive_basic_index_shard_row_payload,
    _write_archive_basic_index_shard_cache,
    _load_archive_basic_index_shard_cache,
    load_or_update_archive_basic_index_shards,
    save_archive_basic_index_cache,
    load_archive_basic_index_cache,
    save_archive_derived_index_cache,
    load_archive_derived_index_cache,
)

# Archive texture sidecar cache helpers live in archive_sidecar_cache.
from cdmw.core.archive_sidecar_cache import (
    _ARCHIVE_SIDECAR_CACHE_SUPPORTED_VERSIONS,
    _ARCHIVE_SCAN_IGNORED_TOP_LEVEL_DIRS,
    _ARCHIVE_SIDECAR_TEXTURE_ATTR_RE,
    _ARCHIVE_TEXTURE_BYTES_RE,
    _extract_archive_sidecar_texture_lookup_paths,
    _build_archive_texture_sidecar_path_rows_for_group,
    build_archive_texture_sidecar_path_rows,
    _build_archive_texture_sidecar_path_rows_for_indices,
    _incremental_archive_texture_sidecar_path_rows,
    _build_archive_sidecar_basename_rows_from_path_rows,
    build_archive_texture_sidecar_basename_rows,
    resolve_archive_texture_sidecar_entry_rows,
    build_lazy_archive_texture_sidecar_entry_index,
    build_archive_texture_sidecar_entry_index,
    _serialize_archive_sidecar_entry_rows,
    _deserialize_archive_sidecar_entry_rows,
    save_archive_texture_sidecar_cache,
    load_archive_texture_sidecar_cache_rows,
    load_archive_texture_sidecar_cache,
    build_archive_texture_sidecar_entry_index_cached,
)













# Archive read/extract/output helpers live in archive_extraction.
from cdmw.core.archive_extraction import (
    _dds_bytes_per_block,
    _dds_uncompressed_surface_size,
    _dds_surface_size,
    reconstruct_partial_dds,
    sanitize_archive_entry_output_path,
    find_available_output_path,
    _read_archive_entry_raw_data_from_handle,
    read_archive_entry_raw_data,
    maybe_reconstruct_sparse_dds,
    _maybe_decompress_partial_par_container,
    _decode_archive_entry_data,
    read_archive_entry_data,
    _read_archive_entry_data_from_handle,
    extract_archive_entry,
    extract_archive_entries,
    directory_has_contents,
    _background_delete_directory,
    clear_directory_contents,
    count_existing_archive_targets,
    format_byte_size,
    sanitize_cache_filename,
    build_archive_entry_metadata_summary,
    build_archive_entry_detail_text,
)



# Archive DDS/detail and loose media preview helpers live in archive_media_preview.
from cdmw.core.archive_media_preview import (
    _decode_dds_fourcc,
    _decode_dds_resource_dimension,
    _decode_dds_alpha_mode,
    _decode_flag_names,
    _format_u32_list,
    _format_hex_dump,
    _sha256_path,
    _dds_resource_type_from_caps,
    build_dds_header_detail_text,
    ensure_archive_preview_source,
    iter_archive_loose_file_candidates,
    build_loose_archive_preview_assets,
    _format_media_duration_millis,
    _runtime_search_roots,
    _resolve_vgmstream_cli_path,
    _decode_wem_with_vgmstream,
    _ensure_media_preview_source_path,
    _iter_riff_chunks,
    _build_wem_media_preview_detail_text,
    _build_mp4_media_preview_detail_text,
    build_loose_archive_media_preview_assets,
    _iter_bnk_chunks,
    build_bnk_soundbank_preview,
)


# Archive binary/text preview and binary sidecar analysis helpers live in archive_binary_preview.
from cdmw.core.archive_binary_preview import (
    format_binary_header_preview,
    try_decode_text_like_archive_data,
    extract_binary_strings,
    build_binary_strings_preview,
    _looks_like_structured_field_name,
    _looks_like_structured_asset_reference,
    _clean_structured_binary_asset_token,
    _extract_binary_asset_references,
    _extract_text_asset_references,
    _structured_field_type_hint,
    _group_meshinfo_field_name,
    _group_animation_field_name,
    _PAA_METABIN_TOKEN_HINTS,
    _paa_metabin_animation_stem,
    _paa_metabin_declared_type_name,
    _paa_metabin_filename_hint_rows,
    _paa_metabin_header_rows,
    _paa_metabin_packed_stream_summary,
    _paa_metabin_analysis_document,
    _extract_binary_string_records,
    _read_binary_sidecar_string_at,
    _binary_sidecar_asset_reference_rows,
    _binary_sidecar_header_words,
    _seqmt_filename_grid_hint,
    _seqmt_analysis_document,
    _paccd_analysis_document,
    _binary_sidecar_offset_candidates,
    _binary_sidecar_count_offset_pairs,
    _is_binary_sidecar_plausible_float,
    _binary_sidecar_float_rows,
    _decode_binary_sidecar_half_float,
    _is_binary_sidecar_plausible_half_float,
    _binary_sidecar_animation_keyframe_tables,
    _BINARY_SIDECAR_DECL_IDENTIFIER_RE,
    _BINARY_SIDECAR_PRIMITIVE_TYPES,
    _BINARY_SIDECAR_STRING_TYPES,
    _BINARY_SIDECAR_KNOWN_TYPE_CODES,
    _looks_like_binary_sidecar_declared_type,
    _binary_sidecar_descriptor_likely_kind,
    _binary_sidecar_descriptor_confidence,
    _binary_sidecar_schema_declarations,
    _build_grouped_schema_declaration_lines,
    _binary_sidecar_container_summary,
    _binary_sidecar_kind_label,
    _build_binary_sidecar_related_references,
    _binary_sidecar_reference_document_rows,
    _PASEQ_TIMELINE_FIELD_TOKENS,
    _PASEQ_EFFECT_FIELD_TOKENS,
    _PASEQ_SCENE_FIELD_TOKENS,
    _paseq_sequence_stem,
    _paseq_reference_role,
    _paseq_timeline_field_role,
    _paseq_timeline_field_rows,
    _paseq_event_marker_rows,
    _paseq_timing_candidate_rows,
    _paseq_timeline_lane_rows,
    _paseq_playback_readiness,
    _paseq_analysis_document,
    build_binary_sidecar_analysis_document,
    build_binary_sidecar_analysis_json,
    _BINARY_SIDECAR_CORPUS_EXTENSIONS,
    _discover_binary_sidecar_corpus_paths,
    _binary_sidecar_corpus_path_label,
    _select_balanced_binary_sidecar_detail_paths,
    _binary_sidecar_descriptor_is_unknown,
    _build_binary_sidecar_corpus_extension_report,
    build_binary_sidecar_corpus_report,
    build_binary_sidecar_corpus_json,
    _group_prefab_field_name,
    _binary_sidecar_group_func_for_extension,
    _group_model_property_header_field_name,
    _group_character_customization_field_name,
    _group_seqmt_field_name,
    _group_world_field_name,
    _group_rig_variant_field_name,
    _build_grouped_structured_section_lines,
)


# Archive related-reference and item-icon reference helpers live in archive_references.
from cdmw.core.archive_references import (
    _score_related_reference_candidate,
    _resolve_related_archive_entry,
    _describe_generic_related_reference_label,
    build_archive_related_file_references,
    _archive_relationship_edge_group_label,
    _archive_relationship_edge_semantic_label,
    build_archive_relationship_references,
    merge_archive_reference_rows,
    _archive_item_icon_catalog_row_value,
    _archive_item_icon_catalog_row_values,
    _strip_archive_item_icon_stem_prefix,
    _archive_path_is_probable_item_icon,
    _add_archive_item_icon_match_keys,
    _archive_item_icon_catalog_row_match_keys,
    _resolve_archive_item_icon_catalog_entries,
    build_archive_item_icon_references_from_catalog,
)


_ASSET_FAMILY_GROUP_ORDER: Tuple[str, ...] = (
    "Selected Model",
    "Attachment / Placement",
    "Material",
    "Textures",
    "Item Icons",
    "Physics / HKX",
    "MeshInfo",
    "Prefab / Metadata",
    "Skeleton / Rig",
    "Animation / Motion",
    "Other",
)

_ATTACHMENT_PREFAB_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "_attachedSocketName",
        "_pivotSocketName",
        "_applyPosition",
        "_applyRotation",
        "_applyScale",
        "_worldTransform",
        "_tiledTransform",
        "_offsetTransform",
        "_skinnedMeshFileName",
        "_socketFileName",
        "_skeletonFileName",
    }
)
_ATTACHMENT_CHARACTER_SOCKET_PRIORITY: Tuple[str, ...] = (
    "Pelvis_L_Socket",
    "Pelvis_R_Socket",
    "Spine2_B_MainWeapon_Socket",
    "Spine2_B_SubWeapon_Socket",
    "Spine2_B_Shield_Socket",
    "RHand_Socket",
    "LHand_Socket",
    "UpperWeapon_00_Socket",
    "LowerWeapon_00_Socket",
)
_ATTACHMENT_WEAPON_SOCKET_PRIORITY: Tuple[str, ...] = (
    "Pelvis_L_ChildSocket",
    "Pelvis_R_ChildSocket",
    "Basic_ChildSocket",
    "Store_Pivot_Socket",
    "Stick_Pivot_Socket",
    "InverseB_ChildSocket",
    "InverseF_ChildSocket",
)
_ATTACHMENT_ASSET_REFERENCE_RE = re.compile(
    r"([A-Za-z0-9_./\\-]+?\.(?:"
    r"prefabdata_xml|prefabdata\.xml|pamlod_xml|pac_xml|pam_xml|sockets\.xml|"
    r"paa_metabin|motionblending|paschedulepath|paschedule|paseq|pastage|"
    r"pamlod|meshinfo|prefab|pappt|pamhc|hkx|hkt|pac|pam|pabgb|pabgh|pabc|pabv|papr|pab|paa|pae|paem|seqmt|xml"
    r"))",
    re.IGNORECASE,
)


def _asset_family_group_order() -> Tuple[str, ...]:
    return _ASSET_FAMILY_GROUP_ORDER


# Archive attachment XML/profile patch helpers live in archive_attachment_patches.
from cdmw.core.archive_attachment_patches import (
    _parse_socket_float_tuple,
    _xml_local_tag_name,
    parse_socket_bone_data_xml,
    _PART_IN_OUT_SOCKET_TAG_RE,
    _PART_IN_OUT_ATTR_RE,
    _PART_IN_OUT_PATCH_FIELDS,
    _STACK_EQUIP_DATA_CONTAINER_TAG_RE,
    _parse_part_in_out_attrs,
    parse_part_in_out_socket_info_xml,
    parse_pac_xml_stack_equip_type,
    infer_stack_equip_type_for_socket,
    build_pac_xml_stack_equip_type_patch,
    infer_part_in_out_weapon_class,
    part_in_out_rows_for_weapon_class,
    _ATTACHMENT_BODY_GROUP_LABELS,
    _ATTACHMENT_SOCKET_ROLE_LABELS,
    _ATTACHMENT_BODY_LOCATION_SOCKET_TOKENS,
    _attachment_body_group_label,
    _attachment_socket_role_label,
    infer_attachment_child_socket_name,
    build_attachment_body_location_choices,
    _part_in_out_attr_value,
    _part_in_out_set_attr,
    _part_in_out_has_attr,
    _part_in_out_is_visible_only_row,
    _part_in_out_row_is_patchable_for_fields,
    _part_in_out_patch_state_fields,
    build_part_in_out_socket_profile_patch,
    build_part_in_out_socket_attach_point_patch,
    build_part_in_out_socket_weapon_case_part_patch,
    build_part_in_out_socket_class_copy_patch,
    _SOCKET_BONE_SOCKET_TAG_RE,
    _SOCKET_BONE_PATCH_FIELDS,
    build_socket_bone_data_profile_patch,
    PrefabSocketNameField,
    PrefabSocketNamePatchResult,
    PrefabAttachmentProfilePatchResult,
    _iter_prefab_length_prefixed_ascii_values,
    inspect_prefab_socket_name_fields,
    inspect_prefab_attachment_profile_fields,
    _validate_prefab_socket_name_replacement,
    _validate_prefab_attachment_profile_replacement,
    build_prefab_socket_name_patch,
    build_prefab_attachment_profile_patch,
)


# Archive attachment ItemInfo and universal two-hand alias patch helpers live in archive_attachment_iteminfo.
from cdmw.core.archive_attachment_iteminfo import (
    _ATTACHMENT_ITEMINFO_MODEL_HASH_INIT,
    _attachment_length_prefixed_text_at,
    parse_attachment_equip_type_records,
    _attachment_model_hash_candidate_names,
    _attachment_model_hash_candidates,
    _attachment_pabgb_row_end,
    _attachment_scan_iteminfo_equip_hits,
    _attachment_iteminfo_behavior_records_for_hashes,
    resolve_attachment_iteminfo_behavior_record,
    _attachment_equip_type_name_for_weapon_class,
    _attachment_behavior_family,
    build_iteminfo_behavior_equip_type_patch,
    build_universal_twohand_sword_iteminfo_behavior_patch,
    _UNIVERSAL_TWOHAND_SWORD_ITEMINFO_EQUIP_FAMILY_REL_OFFSET,
    _UNIVERSAL_TWOHAND_SWORD_ITEMINFO_FAMILY_SIGNATURES_BY_SOURCE,
    _UNIVERSAL_ONEHAND_SWORD_ITEMINFO_FAMILY_SIGNATURE,
    _UNIVERSAL_TWOHAND_SWORD_ITEMINFO_ITEM_TYPES_BY_SOURCE,
    _UNIVERSAL_ONEHAND_SWORD_ITEMINFO_ITEM_TYPE,
    _UNIVERSAL_TWOHAND_SWORD_ITEMINFO_ITEM_TYPE_SEARCH_REL_END,
    build_universal_twohand_sword_true_onehand_iteminfo_patch,
    _ACTIONCHART_ASSET_REFERENCE_PATH_BYTES,
    _actionchart_asset_references_from_bytes,
    _normalize_actionchart_motion_reference_to_virtual_path,
    _universal_twohand_sword_motion_metadata_path,
    _is_universal_twohand_sword_alias_target,
    _is_universal_twohand_sword_combat_alias_target,
    _is_universal_twohand_sword_passive_graph_reference,
    _universal_twohand_sword_candidate_paths_for_target,
    build_universal_twohand_sword_animation_alias_plan,
)




# Archive asset-family graph and related-reference helpers live in archive_asset_family.
from cdmw.core.archive_asset_family import (
    _asset_family_group_for_entry,
    _asset_family_role_for_entry,
    _asset_family_status_for_reference,
    _asset_family_storage_warning,
    _asset_family_evidence_chip,
    _asset_family_include_policy,
    _asset_family_expected_missing_rows,
    _asset_family_summary,
    _attachment_paths_from_string_records,
    _choose_attachment_socket_name,
    _path_with_extension,
    _attachment_prefab_evidence_from_entry,
    _socket_document_from_entry,
    _socket_document_evidence_from_entry,
    _find_socket_info,
    _enrich_attachment_evidence_with_socket_documents,
    _asset_family_attachment_evidence,
    _attachment_evidence_display_name,
    build_archive_asset_family_graph,
    _find_archive_texture_family_entries,
    _find_archive_texture_referencing_sidecar_entries,
    _collect_archive_texture_sidecar_texts_from_entries,
    build_archive_entry_related_references,
)


# Archive structured asset preview/detail helpers live in archive_structured_preview.
from cdmw.core.archive_structured_preview import (
    build_meshinfo_preview,
    build_par_structured_preview,
    _structured_asset_profile,
    _iteminfo_internal_name_candidates,
    _prefab_capability_lines,
    _prefab_evidence_rows,
    _PREFAB_MATERIAL_FIELD_TOKENS,
    _prefab_material_reference_role,
    _normalize_prefab_material_token_text,
    _prefab_material_override_evidence_rows,
    _seqmt_preview_lines,
    _paccd_preview_lines,
    build_structured_asset_preview,
    _parse_xmlish_preview_root,
    _humanize_xml_field_name,
    _xml_field_value_hint,
    _summarize_physics_attachment_xml,
    build_simplified_text_asset_summary,
    describe_archive_binary_content,
    build_archive_binary_preview_payload,
)


# Archive HKX/model preview fallback helpers live in archive_model_preview.
from cdmw.core.archive_model_preview import (
    parse_archive_note_flags,
    summarize_obj_text,
    _build_model_preview_summary_text,
    _build_hkx_preview_context_from_related_references,
    _attach_hkx_physics_overlay_to_model_preview,
    resolve_hkx_preview_context_model_entry,
    _path_mtime_fingerprint,
    _hkx_context_model_preview_cache_key,
    _clone_hkx_context_model_preview,
    _get_hkx_context_model_preview_cache,
    _remember_hkx_context_model_preview_cache,
    _clear_hkx_context_model_preview_cache,
    _retarget_model_preview,
    _inspect_pam_declared_geometry,
    _pam_preview_looks_incomplete,
    _normalize_archive_preview_quality_tier,
    _archive_preview_fast_lod_index,
    _reduce_archive_preview_model_geometry,
    _build_pam_model_preview_with_fallback,
    _build_pamlod_model_preview_with_fallback,
    _build_pac_model_preview_with_fallback,
)


# Archive preview result assembly lives in archive_preview_result_builder.
from cdmw.core.archive_preview_result_builder import build_archive_preview_result
