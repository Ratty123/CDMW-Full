from __future__ import annotations

import bisect
import dataclasses
import hashlib
import json
import math
import re
import struct
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from cdmw.core import archive_hkx_xml_export_reports as _hkx_xml_export_reports
from cdmw.core import archive_hkx_xml_export_content as _hkx_xml_export_content
from cdmw.core import archive_hkx_xml_export_physics as _hkx_xml_export_physics
from cdmw.core import archive_hkx_xml_export_semantics as _hkx_xml_export_semantics
from cdmw.core.archive_hkx_editing import (
    _patch_hkx_advanced_payloads,
    _patch_hkx_shape_payloads,
    _patch_hkx_shape_scalars,
    _patch_hkx_shape_topology,
    _patch_hkx_shapes,
    apply_hkx_editable_geometry_document,
)

from cdmw.core.archive_hkx_havok_xml import (
    _hkx_havok_xml_add_objects,
    _hkx_havok_xml_add_types,
    _hkx_havok_xml_context,
    _hkx_havok_xml_root,
    build_hkx_havok_xml_view_xml,
)

from cdmw.core.archive_hkx_patch_ops import (
    _require_hkx_vector_list,
    _patch_hkx_float_vectors,
    _patch_hkx_mass_property_rows,
    _require_hkx_shape_payload_float_slots,
    _patch_hkx_shape_payload_float_slots,
    _patch_hkx_record_payload,
    _normalize_hkx_mesh_primitive_bytes,
    _hkx_mesh_primitive_signature,
    _hkx_mesh_primitive_rows_by_record,
    _patch_hkx_mesh_primitive_winding_edits,
    _validate_hkx_same_length_payload_edit,
    _require_hkx_int,
    _patch_hkx_advanced_editable_values,
    _hkx_advanced_editable_values_content,
    _hkx_physics_tuning_slot_map,
    _patch_hkx_physics_tuning_values,
    _hkx_vectors_differ,
    _hkx_compare_optional_scalar,
    _hkx_validate_record_identity,
    _hkx_validate_report_records,
    _hkx_validate_converter_invariants,
)

from cdmw.core.archive_hkx_parser import (
    _HKX_KNOWN_TAG_SECTIONS,
    _HKX_PRINTABLE_SCAN_LIMIT,
    _HKX_PRINTABLE_STRING_LIMIT,
    _HKX_TAG_ITEM_MARKERS,
    _HKX_TYPE_NAME_RE,
    _decode_hkx_length_word,
    _detect_hkx_data_payload_offset,
    _detect_hkx_declared_size,
    _detect_hkx_sdk_version,
    _detect_hkx_tag_sections,
    _extract_hkx_declared_type_name_count,
    _extract_hkx_printable_strings,
    _extract_hkx_tst1_type_names,
    _extract_hkx_type_names,
    _find_hkx_tag_items,
    _hkx_next_tag_item,
    _hkx_sdk_version_label,
    _hkx_tag_item_by_name,
    _parse_hkx_item_records,
    _parse_hkx_tna1_type_infos,
    _read_hkx_var_uint,
    parse_hkx_tagfile_summary,
)
from cdmw.core.archive_hkx_xml_import import (
    _hkx_advanced_editable_values_from_xml,
    _hkx_advanced_payloads_from_editable_xml,
    _hkx_document_from_editable_geometry_xml,
    _hkx_parse_xml_int_list,
    _hkx_shape_base_from_xml,
    _hkx_shape_geometry_from_xml,
    _hkx_shape_mesh_from_xml,
    _hkx_shape_topology_from_xml,
    _hkx_shapes_from_editable_xml,
    _hkx_source_from_editable_xml,
    _hkx_tuning_from_editable_xml,
    _hkx_xml_face_indices,
    _hkx_xml_float_attr,
    _hkx_xml_int_attr,
    _hkx_xml_vector,
    apply_hkx_editable_geometry_json,
    apply_hkx_editable_geometry_xml,
)

from cdmw.core.archive_hkx_types import (
    HkxCollisionGeometryHint,
    HkxGeometryPatchResult,
    HkxItemPayloadSummary,
    HkxItemRecord,
    HkxPreviewResult,
    HkxTagItem,
    HkxTagfileSummary,
    HkxTypeInfo,
)
from cdmw.core.archive_hkx_native_summary import _hkx_native_summary_parts
from cdmw.core.archive_hkx_decoder_requirements import _hkx_missing_decoder_requirements_for_type
from cdmw.core.archive_hkx_editable_catalog import _hkx_editable_field_catalog_document

from cdmw.core.archive_hkx_descriptor import (
    _HKX_DESCRIPTOR_NUMERIC_HINT_DESCRIPTIONS,
    _hkx_descriptor_body_documents,
    _hkx_descriptor_constraint_documents,
    _hkx_descriptor_core_attributes,
    _hkx_descriptor_element_local_name,
    _hkx_descriptor_hint_from_root,
    _hkx_descriptor_material_simulation_documents,
    _hkx_descriptor_numeric_hint_values,
    _hkx_descriptor_shape_type,
    _hkx_descriptor_unique_values,
    build_hkx_descriptor_hint_from_xml_text,
)
from cdmw.core.archive_hkx_collision_parser import (
    _infer_hkx_capsule_hints,
    _infer_hkx_collision_geometry_hints,
    _infer_hkx_convex_and_box_hints,
    _infer_hkx_mesh_hints,
    _infer_hkx_sphere_hints,
)

from cdmw.core.archive_hkx_corpus_evidence import (
    _HKX_CORPUS_PRIORITY_CLASS_TARGETS,
    _hkx_corpus_counter_matching,
    _hkx_corpus_counter_value,
    _hkx_corpus_file_examples_for_ptch_case,
    _hkx_corpus_file_examples_for_target,
    _hkx_corpus_int,
    _hkx_corpus_sorted_count_rows,
    build_hkx_corpus_evidence_from_report,
    load_hkx_corpus_evidence_json,
)
from cdmw.core.archive_hkx_corpus_planning import (
    _HKX_CORPUS_ROLE_LABELS,
    _HKX_PTCH_SEMANTICS_REQUIRED_OBSERVATIONS,
    _HKX_REPRESENTATIVE_REAL_CORPUS_REQUIREMENTS,
    _HKX_REQUIRED_COMPATIBILITY_CORPUS_ROLES,
    _hkx_corpus_role_for_document,
    _hkx_corpus_role_hint_from_path,
    _hkx_enrich_balanced_corpus_content_hints,
    _hkx_hard_decoder_corpus_proof_document,
    _hkx_path_contains_binary_marker,
    _hkx_ptch_semantics_proof_document,
    _hkx_representative_real_corpus_plan_document,
    _hkx_representative_real_role_matches,
    _hkx_row_is_generated_hkx_sample,
    _hkx_select_balanced_corpus_paths,
)
from cdmw.core.archive_hkx_corpus_report import (
    _HKX_CORPUS_DEFAULT_DETAIL_LIMIT,
    _HKX_CORPUS_DEFAULT_ROUNDTRIP_LIMIT,
    build_hkx_converter_corpus_csv,
    build_hkx_converter_corpus_json,
    build_hkx_converter_corpus_report,
)
from cdmw.core.archive_hkx_corpus_scan import _hkx_descriptor_hint_document, _hkx_descriptor_hints_by_stem
from cdmw.core.archive_hkx_record_constants import _HKX_ENUM_RECORD_TYPES, _HKX_SCALAR_ARRAY_TYPES
from cdmw.core.archive_hkx_record_layout_fields_0 import (
    _hkx_record_layout_fields_0,
    _hkx_record_layout_fields_1,
    _hkx_record_layout_fields_2,
    _hkx_record_layout_fields_3,
    _hkx_record_layout_fields_4,
    _hkx_record_layout_fields_5,
)
from cdmw.core.archive_hkx_record_layout_fields_1 import (
    _hkx_record_layout_fields_6,
    _hkx_record_layout_fields_7,
    _hkx_record_layout_fields_8,
    _hkx_record_layout_fields_9,
    _hkx_record_layout_fields_10,
    _hkx_record_layout_fields_11,
)
from cdmw.core.archive_hkx_record_layout_fields_2 import (
    _hkx_record_layout_post_0,
    _hkx_record_layout_post_1,
    _hkx_record_layout_post_2,
    _hkx_record_layout_post_3,
)
from cdmw.core.archive_hkx_record_layout import _hkx_record_layout_document
from cdmw.core.archive_hkx_editor_rows_0 import (
    _hkx_editor_build_context,
    _hkx_editor_context_label,
    _hkx_editor_context_identity_path,
    _hkx_editor_context_kwargs_for_shape,
    _hkx_editor_add_body_rows,
    _hkx_editor_add_shape_summary,
    _hkx_editor_add_shape_field_rows,
    _hkx_editor_add_shape_mesh_rows,
    _hkx_editor_add_shape_rows,
    _hkx_editor_add_constraint_rows,
    _hkx_editor_add_tuning_rows,
    _hkx_editor_add_object_rows,
    _hkx_editor_add_raw_rows,
)
from cdmw.core.archive_hkx_editor_model import _hkx_editor_model_document
from cdmw.core.archive_hkx_relationship_graph_0 import (
    _hkx_graph_text_key,
    _hkx_graph_viewer_id,
    _hkx_graph_record_node,
    _hkx_graph_shape_viewer_id_from_path,
    _hkx_graph_patch_identity_path,
    _hkx_graph_register_body_key,
    _hkx_graph_build_patch_indexes,
    _hkx_graph_add_sections_and_records,
    _hkx_graph_add_native_edges,
    _hkx_graph_add_object_edges,
    _hkx_graph_add_shapes,
    _hkx_graph_add_bodies,
    _hkx_graph_tuning_owner_map,
    _hkx_graph_add_constraints,
    _hkx_graph_add_tuning,
)
from cdmw.core.archive_hkx_relationship_graph_1 import (
    _hkx_graph_add_catalog,
    _hkx_graph_add_descriptors,
)
from cdmw.core.archive_hkx_relationships import _hkx_relationship_graph_document
from cdmw.core.archive_hkx_editable_xml_sections_0 import (
    _hkx_xml_add_converter_report,
    _hkx_xml_fixup_section_element,
    _hkx_xml_add_fixup_ptch_tables,
    _hkx_xml_add_fixup_resolved_references,
    _hkx_xml_add_fixup_words,
    _hkx_xml_add_fixup_varuint_values,
    _hkx_xml_add_fixup_sections,
    _hkx_xml_add_tagfile_reference_fixups,
    _hkx_xml_add_havok_classes,
    _hkx_xml_add_packfile_object,
    _hkx_xml_add_packfile_objects,
    _hkx_xml_add_havok_packfile,
    _hkx_xml_add_flat_havok_object,
    _hkx_xml_add_flat_havok_objects,
)
from cdmw.core.archive_hkx_editable_xml_sections_1 import (
    _hkx_xml_add_havok_view,
    _hkx_xml_add_descriptor_hint,
    _hkx_xml_add_companion_descriptor_hints,
    _hkx_xml_add_shape_metadata,
    _hkx_xml_add_shape_geometry,
    _hkx_xml_add_shape_payload,
    _hkx_xml_add_shape_summaries,
    _hkx_xml_add_shapes,
)
from cdmw.core.archive_hkx_editable_xml import build_hkx_editable_geometry_xml
from cdmw.core.archive_hkx_xml_metadata_sections_0 import (
    _hkx_xml_hkclass_readiness_element,
    _hkx_xml_add_missing_hkclass_metadata,
    _hkx_xml_add_unresolved_hkclass_counts,
    _hkx_xml_add_native_model_graph_readiness,
    _hkx_xml_add_biggest_hkclass_gate,
    _hkx_xml_add_no_edit_writer_readiness,
    _hkx_xml_add_hkclass_internals,
    _hkx_xml_add_hard_decoder_targets,
    _hkx_xml_add_hkclass_gui_readiness,
    _hkx_xml_add_hkclass_import_safety,
    _hkx_xml_mesh_details_element,
    _hkx_xml_add_mesh_detail_summary,
    _hkx_xml_add_mesh_nested_rows,
    _hkx_xml_add_mesh_record,
    _hkx_xml_add_mesh_record_group,
)
from cdmw.core.archive_hkx_xml_metadata import (
    _hkx_xml_add_hkclass_metadata_readiness,
    _hkx_xml_add_mesh_details,
)
from cdmw.core.archive_hkx_edit_gate_helpers_0 import (
    _hkx_add_shape_patch_entries,
    _hkx_add_tuning_patch_entries,
    _hkx_edit_gate_row,
    _hkx_edit_gate_task_row,
    _hkx_edit_gate_task_key_for_source,
    _hkx_edit_gate_mark_task,
    _hkx_workspace_offset_text,
    _hkx_workspace_row_common,
)
from cdmw.core.archive_hkx_edit_gate import (
    _hkx_byte_patch_map_document,
    _hkx_edit_gate_v1_document,
    _hkx_modding_workspace_document,
)
from cdmw.core.archive_hkx_converter_sections_0 import (
    _hkx_mesh_export_shape_rows,
    _hkx_mesh_export_section_rows,
    _hkx_mesh_export_primitive_rows,
    _hkx_mesh_export_aabb_rows,
    _hkx_mesh_export_shape_tag_rows,
    _hkx_mesh_export_byte_rows,
    _hkx_converter_collect_records,
    _hkx_converter_schema_coverage,
    _hkx_interpret_payload_fields_0,
    _hkx_interpret_payload_fields_1,
    _hkx_interpret_payload_fields_2,
)
from cdmw.core.archive_hkx_converter import (
    _hkx_export_mesh_shape_details_document,
    _hkx_converter_report_document,
    _hkx_interpret_record_payload,
)
from cdmw.core.archive_hkx_fixup_sections_0 import (
    _hkx_fixup_section_context,
    _hkx_fixup_section_words,
    _hkx_fixup_section_varuint,
    _hkx_process_fixup_section,
    _hkx_fixup_add_case,
    _hkx_collect_fixup_semantics,
)
from cdmw.core.archive_hkx_fixup_reports import (
    _hkx_tagfile_reference_fixups_document,
    _hkx_fixup_semantics_report_document,
)
from cdmw.core.archive_hkx_havok_view_sections_0 import (
    _hkx_havok_specialized_group_0,
    _hkx_havok_specialized_group_1,
    _hkx_havok_view_add_reference,
    _hkx_havok_view_layout_fields,
    _hkx_havok_view_finish_object,
    _hkx_havok_view_add_object,
    _hkx_havok_parity_collect_objects,
)
from cdmw.core.archive_hkx_havok_view import (
    _hkx_havok_xml_specialized_fields,
    _hkx_havok_xml_view_document,
    _hkx_havok_xml_parity_report_document,
)
from cdmw.core.archive_hkx_readiness_sections_0 import (
    _hkx_hkclass_base_context,
    _hkx_hkclass_native_context,
    _hkx_hkclass_target_context,
    _hkx_hkclass_status_context,
    _hkx_hkclass_readiness_report_0,
    _hkx_hkclass_readiness_report_1,
    _hkx_hkclass_readiness_report_2,
    _hkx_native_backend_report_0,
    _hkx_native_backend_report_1,
    _hkx_native_backend_report_2,
    _hkx_modding_readiness_report_0,
    _hkx_modding_readiness_report_1,
)
from cdmw.core.archive_hkx_readiness import (
    _hkx_hkclass_metadata_readiness_document,
    _hkx_native_backend_document,
    _hkx_modding_readiness_document,
)
from cdmw.core.archive_hkx_summary import (
    _format_hkx_float_bounds,
    _format_hkx_vector,
    _summarize_hkx_float_vectors,
    _decode_hkx_convex_face_vertex_indices,
    _read_hkx_float_vector_payload,
    _hkx_payload_slice,
    _build_hkx_hull_geometry_hint,
    _assign_hkx_mass_property_records,
    _hkx_item_record_spans,
    _hkx_hex,
    _hkx_record_offset_indexes,
    _hkx_offset_index_target,
    _summarize_hkx_possible_record_links,
    _hkx_possible_record_link_documents,
    _summarize_hkx_u32_words,
    _summarize_hkx_float_rows,
    _summarize_hkx_object_payload,
    _summarize_hkx_item_payloads,
)

from cdmw.core.archive_hkx_roles import (
    _HKX_SIMULATION_ROLE_DESCRIPTIONS,
    _hkx_simulation_role_counts,
    _hkx_simulation_role_description,
    _hkx_simulation_role_from_parts,
)
from cdmw.core.archive_hkx_editable_geometry import build_hkx_editable_geometry_document
from cdmw.core.archive_hkx_overlay import build_hkx_physics_overlay_from_document, merge_hkx_physics_overlays
from cdmw.core.archive_hkx_overlay_support import (
    _hkx_overlay_anchor_match_key,
    _hkx_overlay_average_position,
    _hkx_overlay_body_shape_targets,
    _hkx_overlay_bones_from_skeleton_positions,
    _hkx_overlay_descriptor_vector,
    _hkx_overlay_name_aliases,
    _hkx_overlay_shape_visual_center,
    _hkx_overlay_skeleton_bone_match,
    _hkx_overlay_translate_point,
    _hkx_overlay_tuning_hint_text,
    _hkx_overlay_vector,
)
from cdmw.core.archive_hkx_preview import build_hkx_preview
from cdmw.core.archive_hkx_preview_geometry import (
    _hkx_preview_bounds,
    _hkx_preview_box_mesh,
    _hkx_preview_cylinder_mesh,
    _hkx_preview_dimension,
    _hkx_preview_edges_from_faces,
    _hkx_preview_float,
    _hkx_preview_marker_mesh,
    _hkx_preview_shape_meshes,
    _hkx_preview_skeleton_meshes,
    _hkx_preview_sphere_mesh,
    _hkx_preview_triangulated_indices,
    _hkx_preview_vec_add,
    _hkx_preview_vec_cross,
    _hkx_preview_vec_length,
    _hkx_preview_vec_normalize,
    _hkx_preview_vec_scale,
    _hkx_preview_vec_sub,
    _hkx_preview_vector,
    build_hkx_model_preview_from_document,
)
from cdmw.modding.skeleton_parser import parse_pab

from cdmw.core.archive_hkx_mesh_export_helpers_0 import (
    _hkx_export_box_shape_summary_for_record,
    _hkx_export_shape_payload_float_slots_for_record,
    _hkx_export_hull_topology_document,
    _hkx_scalar_array_values,
    _hkx_enum_record_values,
    _hkx_u32_pair_rows,
    _hkx_finite_float_slots_in_range,
    _hkx_mesh_geometry_section_candidate_fields,
    _hkx_mesh_enrich_geometry_section_layout_targets,
    _hkx_mesh_primitive_tuple_rows,
    _hkx_mesh_aabb8_node_rows,
)
from cdmw.core.archive_hkx_converter_helpers_0 import (
    _hkx_schema_observation_document,
    _hkx_record_role_description,
    _hkx_record_status_from_payload,
    _hkx_decode_state_from_payload,
    _hkx_converter_record_document,
    _hkx_editable_value_count,
    _hkx_compatibility_status_from_counts,
    _hkx_decode_gap_friendly_label,
    _hkx_decode_gap_summary_document,
)
from cdmw.core.archive_hkx_fixups_helpers_0 import (
    _hkx_tagfile_fixup_reference_category,
    _hkx_tagfile_fixup_word_match,
    _hkx_tagfile_nested_item_word_match,
    _hkx_decode_ptch_patch_site,
    _hkx_decode_nested_ptch_table,
    _hkx_tagfile_nested_ptch_word_match,
)
from cdmw.core.archive_hkx_schema_helpers_0 import (
    _hkx_type_registry_document,
    _hkx_havok_template_arguments,
    _hkx_havok_member_type_metadata,
    _hkx_havok_reference_category,
    _hkx_havok_reference_confidence,
    _hkx_havok_synthetic_member_rows,
    _hkx_havok_xml_param_text,
    _hkx_ptch_reference_documents_by_owner_offset,
    _hkx_havok_xml_record_strings,
    _hkx_havok_xml_pair_low_count,
    _hkx_havok_xml_numelements_for_field,
    _hkx_havok_xml_apply_sibling_array_counts,
    _hkx_havok_xml_enrich_reference_field,
    _hkx_havok_xml_array_value_fields,
    _hkx_havok_xml_root_recovery,
)
from cdmw.core.archive_hkx_schema_helpers_1 import (
    _hkx_havok_xml_named_variants,
    _hkx_havok_class_metadata,
    _hkx_real_hkclass_member_rows,
    _hkx_real_hkclass_metadata_document,
    _hkx_havok_xml_type_classes,
)
from cdmw.core.archive_hkx_havok_view_helpers_0 import (
    _hkx_havok_xml_make_param_field,
    _hkx_havok_xml_apply_record_reference_to_field,
    _hkx_havok_xml_stable_object_order,
)
from cdmw.core.archive_hkx_evidence_helpers_0 import (
    _hkx_decoder_evidence_v2_document,
    _hkx_raw_records_document,
)
from cdmw.core.archive_hkx_payloads_helpers_0 import (
    _hkx_layout_field_byte_coverage,
    _hkx_fixed_float_slot_group_description,
    _hkx_fixed_float_slot_description,
    _hkx_export_fixed_float_slot_rows,
    _hkx_advanced_editable_values_document,
    _hkx_advanced_record_payloads_document,
)
from cdmw.core.archive_hkx_physics_helpers_0 import (
    _hkx_char_record_texts_from_payloads,
    _hkx_shape_name_documents,
    _hkx_attach_shape_name_property_interpretations,
    _hkx_physics_system_document,
    _hkx_physics_tuning_slot_name,
    _hkx_physics_tuning_user_guidance,
    _hkx_physics_slot_vector_groups,
    _hkx_physics_tuning_document,
    _hkx_descriptor_hint_rows,
    _hkx_attach_descriptor_context_to_physics_tuning,
    _hkx_shape_context_from_descriptor,
)
from cdmw.core.archive_hkx_physics_helpers_1 import (
    _hkx_physics_body_context_document,
    _hkx_attach_body_contexts_to_shapes,
    _hkx_attach_shape_name_hints_to_shapes,
    _hkx_physics_body_summary_document,
    _hkx_material_simulation_context_document,
    _hkx_descriptor_constraint_contexts,
    _hkx_physics_constraint_summary_document,
    _hkx_editable_shape_field_value_summary,
)
from cdmw.core.archive_hkx_patch_map_helpers_0 import (
    _hkx_editable_shape_subject,
    _hkx_editable_catalog_semantics,
    _hkx_decode_patch_map_original_value,
)
from cdmw.core.archive_hkx_workspace_helpers_0 import (
    _hkx_reimport_policy_document,
    _hkx_user_editing_guide_document,
    _hkx_semantic_record_relation,
)
from cdmw.core.archive_hkx_relationships_helpers_0 import (
    _hkx_editor_model_preview_link_count,
    _hkx_compatibility_document,
)
from cdmw.core.archive_hkx_xml_export_helpers_0 import (
    _hkx_xml_add_havok_param_rows,
    _hkx_xml_add_modding_readiness,
    _hkx_xml_add_modding_workspace,
    _hkx_xml_add_record_interpretation,
    _hkx_xml_add_advanced_editable_values,
)

class SkeletonPreviewResult:
    preview_text: str
    detail_lines: List[str]




def build_pab_preview(data: bytes, virtual_path: str) -> SkeletonPreviewResult:
    skeleton = parse_pab(data, virtual_path)
    lines = [f"PAB skeleton preview for {virtual_path}"]
    parser_mode = str(getattr(skeleton, "parser_mode", "") or "fixed")
    tail_data = bytes(getattr(skeleton, "tail_data", b"") or b"")
    parse_warning = str(getattr(skeleton, "parse_warning", "") or "").strip()
    detail_lines = [
        f"Declared bones: {int(getattr(skeleton, 'bone_count', len(skeleton.bones)) or 0):,}",
        f"Parsed bones: {len(skeleton.bones):,}",
        f"Parser mode: {parser_mode}",
        f"Tail data: {len(tail_data):,} bytes",
    ]
    if parse_warning:
        detail_lines.append(parse_warning)
    if not skeleton.bones:
        lines.append("No bones were recovered.")
        return SkeletonPreviewResult(preview_text="\n".join(lines), detail_lines=detail_lines)

    root_bones = [bone for bone in skeleton.bones if bone.parent_index < 0]
    named_bones = [bone for bone in skeleton.bones if str(bone.name or "").strip()]
    child_map: Dict[int, List[int]] = {}
    for bone in skeleton.bones:
        child_map.setdefault(int(bone.parent_index), []).append(int(bone.index))

    def _depth(index: int) -> int:
        children = child_map.get(index, [])
        if not children:
            return 1
        return 1 + max(_depth(child_index) for child_index in children)

    max_depth = max((_depth(root.index) for root in root_bones), default=0)
    positions = [
        tuple(float(component) for component in bone.position)
        for bone in skeleton.bones
        if len(tuple(bone.position)) >= 3
    ]
    detail_lines.append(f"Root bones: {len(root_bones):,}")
    detail_lines.append(f"Named bones: {len(named_bones):,}")
    detail_lines.append(f"Max hierarchy depth: {max_depth}")
    if positions:
        min_x = min(position[0] for position in positions)
        min_y = min(position[1] for position in positions)
        min_z = min(position[2] for position in positions)
        max_x = max(position[0] for position in positions)
        max_y = max(position[1] for position in positions)
        max_z = max(position[2] for position in positions)
        detail_lines.append(
            "Bone position bounds: "
            f"min=({min_x:.3f}, {min_y:.3f}, {min_z:.3f}) "
            f"max=({max_x:.3f}, {max_y:.3f}, {max_z:.3f})"
        )
    lines.extend(
        [
            "",
            "Summary:",
            f"- Declared bones: {int(getattr(skeleton, 'bone_count', len(skeleton.bones)) or 0):,}",
            f"- Bones: {len(skeleton.bones):,}",
            f"- Root bones: {len(root_bones):,}",
            f"- Named bones: {len(named_bones):,}",
            f"- Max hierarchy depth: {max_depth}",
            f"- Parser mode: {parser_mode}",
            f"- Tail data: {len(tail_data):,} bytes",
        ]
    )
    if parse_warning:
        lines.append(f"- Warning: {parse_warning}")
    if root_bones:
        lines.append("- Root names: " + ", ".join((bone.name or "<unnamed>") for bone in root_bones[:8]))
        if len(root_bones) > 8:
            lines[-1] += " ..."
    lines.append("")
    lines.append("Bone hierarchy:")
    for bone in skeleton.bones[:128]:
        parent_text = "root" if bone.parent_index < 0 else f"parent {bone.parent_index}"
        position_text = ""
        if len(tuple(bone.position)) >= 3:
            position_text = f" pos=({bone.position[0]:.3f}, {bone.position[1]:.3f}, {bone.position[2]:.3f})"
        lines.append(f"[{bone.index:03d}] {bone.name or '<unnamed>'} ({parent_text}){position_text}")
    if len(skeleton.bones) > 128:
        lines.append("")
        lines.append("Preview truncated to the first 128 bones.")
    return SkeletonPreviewResult(preview_text="\n".join(lines), detail_lines=detail_lines)


_HKX_COMPATIBILITY_TARGET_TYPES = (
    "hkRootLevelContainer",
    "hkRootLevelContainer::NamedVariant",
    "hkRefVariant",
    "hkStringPtr",
    "hkMemoryResourceContainer",
    "hknpPhysicsSceneData",
    "hknpPhysicsSystemData",
    "hknpRagdollData",
    "hknpPhysicsSystemData::ExtendedBodyCinfo",
    "hknpConstraintCinfo",
    "hknpConstraintData",
    "hknpBallAndSocketConstraintData",
    "hknpHingeConstraintData",
    "hknpRagdollConstraintData",
    "hknpLimitedHingeConstraintData",
    "hknpWheelConstraintData",
    "hknpFixedConstraintData",
    "hknpBreakableConstraintData",
    "hknpPositionConstraintMotor",
    "hknpVelocityConstraintMotor",
    "hknpSharedMotionProperties",
    "hknpRefDragProperties",
    "hknpRefMassDistribution",
    "hknpCapsuleShape",
    "hknpCylinderShape",
    "hknpSphereShape",
    "hknpBoxShape",
    "hknpConvexShape",
    "hknpTriangleShape",
    "hknpLodShape",
    "hknpMeshShape",
    "hknpMeshShape::GeometrySection",
    "hknpMeshShape::GeometrySection::Primitive",
    "hknpMeshShape::ShapeTagTableEntry",
    "hknpCompoundShape",
    "hknpShapeInstance",
    "hknpAabb8TreeNode",
    "hkcdSimdTreeNamespace::Node",
    "hknpShapeProperties::Entry",
    "hknpShapeMassProperties",
    "hkCompressedMassProperties",
    "hkPackedVector3",
    "hkFreeListArrayElement<tVALUE_TYPE=7>",
    "HavokShapeNameProperty",
    "hknpMaterial",
    "hkSkeleton",
    "hkBone",
    "hkInt16",
    "hkUint16",
    "hkInt32",
    "hkUint32",
    "hkBool",
    "hkMatrix4",
    "hkQsTransform",
    "hkaSkeletonMapper",
    "hkaSkeletonMapperData::SimpleMapping",
    "hkaSkeletonMapperData::ChainMapping",
    "hkaAnimationContainer",
    "hkxAnimatedFloat",
    "hkxAnimatedQuaternion",
    "hkxAnimatedVector",
    "hkxAttribute",
    "hkxAttributeGroup",
    "hkxEdgeSelectionChannel",
    "hkxIndexBuffer",
    "hkxMaterial",
    "hkxMaterial::TextureStage",
    "hkxMesh",
    "hkxMesh::UserChannelInfo",
    "hkxMeshSection",
    "hkxNode",
    "hkxScene",
    "hkxSkinBinding",
    "hkxSparselyAnimatedBool",
    "hkxSparselyAnimatedInt",
    "hkxSparselyAnimatedString",
    "hkxTextureFile",
    "hkxVertexBuffer",
    "hkxVertexDescription::ElementDecl",
    "hkxVertexIntDataChannel",
    "hkxVertexSelectionChannel",
    "hknpShapeType::Enum",
    "hknpCollisionDispatchType::Enum",
    "hknpShape::FlagsEnum",
    "hkcdSimdTreeNamespace::Node::FlagsEnum",
    "unsigned char",
    "unsigned short",
    "unsigned int",
    "unsigned long long",
    "long long",
    "int",
    "float",
    "char",
)
_HKX_FAMILY_LABELS = (
    ("hknp", "Modern Havok Physics"),
    ("hkp", "Legacy Havok Physics"),
    ("hka", "Animation"),
    ("hkb", "Behavior"),
    ("hkai", "AI / navigation"),
    ("hkcd", "Collision detection"),
    ("hkx", "Container"),
)
_HKX_HAVOK_MEMBER_SCHEMA: Mapping[str, Tuple[Dict[str, object], ...]] = {
    "hkArray": (
        {
            "source_names": ("data_reference_or_offset",),
            "name": "data",
            "type": "void*",
            "offset": 0,
            "array_status": "array_data_reference",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("size",),
            "name": "size",
            "type": "int",
            "offset": 8,
            "array_status": "array_size",
            "reference_status": "none",
            "confidence": "experimental",
        },
        {
            "source_names": ("capacity_and_flags",),
            "name": "capacityAndFlags",
            "type": "int",
            "offset": 12,
            "array_status": "array_capacity_flags",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hkRefPtr": (
        {
            "source_names": ("referenced_object",),
            "name": "ptr",
            "type": "hkReferencedObject*",
            "offset": 0,
            "array_status": "none",
            "reference_status": "object_reference",
            "confidence": "experimental",
        },
    ),
    "hkRefVariant": (
        {
            "source_names": ("referenced_value",),
            "name": "variant",
            "type": "void*",
            "offset": 0,
            "array_status": "none",
            "reference_status": "object_reference",
            "confidence": "experimental",
        },
    ),
    "hkStringPtr": (
        {
            "source_names": ("referenced_value",),
            "name": "string",
            "type": "char*",
            "offset": 0,
            "array_status": "none",
            "reference_status": "string_reference",
            "confidence": "experimental",
        },
    ),
    "hkRootLevelContainer": (
        {
            "source_names": ("named_variants_data_reference",),
            "name": "namedVariants",
            "type": "hkArray<hkRootLevelContainer::NamedVariant>",
            "offset": 0,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("named_variants_size",),
            "name": "namedVariantsSize",
            "type": "int",
            "offset": 8,
            "array_status": "array_size",
            "reference_status": "none",
            "confidence": "experimental",
        },
        {
            "source_names": ("named_variants_capacity_and_flags",),
            "name": "namedVariantsCapacityAndFlags",
            "type": "int",
            "offset": 12,
            "array_status": "array_capacity_flags",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hkRootLevelContainer::NamedVariant": (
        {
            "source_names": ("name_reference",),
            "name": "name",
            "type": "hkStringPtr",
            "offset": 0,
            "array_status": "none",
            "reference_status": "string_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("class_name_reference",),
            "name": "className",
            "type": "hkStringPtr",
            "offset": 8,
            "array_status": "none",
            "reference_status": "type_class_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("object_reference",),
            "name": "variant",
            "type": "hkRefVariant",
            "offset": 16,
            "array_status": "none",
            "reference_status": "object_reference",
            "confidence": "experimental",
        },
    ),
    "hknpPhysicsSceneData": (
        {
            "source_names": ("u32_pair_0x0",),
            "name": "systems",
            "type": "hkArray<hknpPhysicsSystemData>",
            "offset": 0,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
    ),
    "hknpPhysicsSystemData": (
        {
            "source_names": ("materials_array_or_reference_pair",),
            "name": "materials",
            "type": "hkArray<hknpMaterial>",
            "offset": 0x00,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("motion_properties_array_or_reference_pair",),
            "name": "motionProperties",
            "type": "hkArray<hknpSharedMotionProperties>",
            "offset": 0x08,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("body_cinfo_array_or_reference_pair",),
            "name": "bodyCinfos",
            "type": "hkArray<hknpPhysicsSystemData::ExtendedBodyCinfo>",
            "offset": 0x10,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("constraint_cinfo_array_or_reference_pair",),
            "name": "constraintCinfos",
            "type": "hkArray<hknpConstraintCinfo>",
            "offset": 0x18,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("shape_reference_array_or_pair",),
            "name": "shapeReferences",
            "type": "hkArray<hkRefPtr<hknpShape>>",
            "offset": 0x20,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
    ),
    "hknpPhysicsSystemData::ExtendedBodyCinfo": (
        {
            "source_names": ("shape_reference_or_key_pair",),
            "name": "shape",
            "type": "hkRefPtr<hknpShape>",
            "offset": 0x08,
            "array_status": "none",
            "reference_status": "object_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("motion_properties_reference_pair",),
            "name": "motionPropertiesId",
            "type": "hknpMotionPropertiesId",
            "offset": 0x10,
            "array_status": "none",
            "reference_status": "object_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("material_or_collision_filter_pair",),
            "name": "materialId",
            "type": "hknpMaterialId",
            "offset": 0x18,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "experimental",
        },
        {
            "source_names": ("body_transform_or_orientation_row0_x",),
            "name": "transform",
            "type": "hkTransform",
            "offset": 0x30,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hknpConstraintCinfo": (
        {
            "source_names": ("body_a_reference_or_index_pair",),
            "name": "bodyA",
            "type": "hknpBodyId",
            "offset": 0x00,
            "array_status": "none",
            "reference_status": "object_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("body_b_reference_or_index_pair",),
            "name": "bodyB",
            "type": "hknpBodyId",
            "offset": 0x08,
            "array_status": "none",
            "reference_status": "object_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("constraint_data_reference_pair",),
            "name": "constraintData",
            "type": "hkRefPtr<hknpConstraintData>",
            "offset": 0x10,
            "array_status": "none",
            "reference_status": "object_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("constraint_priority_flags_pair",),
            "name": "priority",
            "type": "int",
            "offset": 0x18,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hknpConvexShape": (
        {
            "source_names": ("vertices_offset_count",),
            "name": "vertices",
            "type": "hkArray<hkFloat3>",
            "offset": 0x30,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "strong inference",
        },
        {
            "source_names": ("planes_offset_count",),
            "name": "planes",
            "type": "hkArray<hkVector4>",
            "offset": 0x40,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "strong inference",
        },
        {
            "source_names": ("faces_offset_count",),
            "name": "faces",
            "type": "hkArray<hknpConvexHull::Face>",
            "offset": 0x48,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "strong inference",
        },
        {
            "source_names": ("face_indices_offset_count",),
            "name": "faceIndices",
            "type": "hkArray<hkUint8>",
            "offset": 0x50,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "strong inference",
        },
        {
            "source_names": ("edge_table_a_offset_count",),
            "name": "edgeTableA",
            "type": "hkArray<hknpConvexHull::Edge>",
            "offset": 0x58,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "strong inference",
        },
        {
            "source_names": ("edge_table_b_offset_count",),
            "name": "edgeTableB",
            "type": "hkArray<hknpConvexHull::Edge>",
            "offset": 0x60,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "strong inference",
        },
        {
            "source_names": ("convex_radius_or_collision_margin",),
            "name": "convexRadius",
            "type": "hkReal",
            "offset": 0x68,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hknpBoxShape": (
        {
            "source_names": ("box_vertices_offset_count",),
            "name": "vertices",
            "type": "hkArray<hkFloat3>",
            "offset": 0x38,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "strong inference",
        },
        {
            "source_names": ("box_planes_offset_count",),
            "name": "planes",
            "type": "hkArray<hkVector4>",
            "offset": 0x40,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "strong inference",
        },
        {
            "source_names": ("box_faces_offset_count",),
            "name": "faces",
            "type": "hkArray<hknpConvexHull::Face>",
            "offset": 0x48,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "strong inference",
        },
        {
            "source_names": ("box_face_indices_offset_count",),
            "name": "faceIndices",
            "type": "hkArray<hkUint8>",
            "offset": 0x50,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "strong inference",
        },
        {
            "source_names": ("box_edge_table_a_offset_count",),
            "name": "edgeTableA",
            "type": "hkArray<hknpConvexHull::Edge>",
            "offset": 0x58,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "strong inference",
        },
        {
            "source_names": ("box_edge_table_b_offset_count",),
            "name": "edgeTableB",
            "type": "hkArray<hknpConvexHull::Edge>",
            "offset": 0x60,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "strong inference",
        },
        {
            "source_names": ("convex_radius_or_collision_margin",),
            "name": "convexRadius",
            "type": "hkReal",
            "offset": 0x68,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "strong inference",
        },
    ),
    "hknpSphereShape": (
        {
            "source_names": ("sphere_radius", "finite_float_0x68"),
            "name": "radius",
            "type": "hkReal",
            "offset": 0x68,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "strong inference",
        },
    ),
    "hknpCapsuleShape": (
        {
            "source_names": ("capsule_radius", "finite_float_0x68"),
            "name": "radius",
            "type": "hkReal",
            "offset": 0x68,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "strong inference",
        },
        {
            "source_names": ("capsule_endpoints",),
            "name": "vertices",
            "type": "hkArray<hkFloat3>",
            "offset": 0,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "strong inference",
        },
    ),
    "hknpMeshShape": (
        {
            "source_names": ("geometry_sections",),
            "name": "geometrySections",
            "type": "hkArray<hknpMeshShape::GeometrySection>",
            "offset": 0,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("aabb_tree_nodes",),
            "name": "aabbTree",
            "type": "hkArray<hknpAabb8TreeNode>",
            "offset": 0,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
    ),
    "hknpRagdollConstraintData": (
        {
            "source_names": ("constraint_strength_or_tau",),
            "name": "tau",
            "type": "hkReal",
            "offset": 0x18,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "experimental",
        },
        {
            "source_names": ("joint_frame_a_row0_x",),
            "name": "atoms",
            "type": "hknpConstraintAtom[]",
            "offset": 0x40,
            "array_status": "fixed_payload",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hknpLimitedHingeConstraintData": (
        {
            "source_names": ("constraint_strength_or_tau",),
            "name": "tau",
            "type": "hkReal",
            "offset": 0x18,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hknpPositionConstraintMotor": (
        {
            "source_names": ("min_force",),
            "name": "minForce",
            "type": "hkReal",
            "offset": 0x20,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "strong inference",
        },
        {
            "source_names": ("max_force",),
            "name": "maxForce",
            "type": "hkReal",
            "offset": 0x24,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "strong inference",
        },
        {
            "source_names": ("stiffness_or_strength",),
            "name": "stiffness",
            "type": "hkReal",
            "offset": 0x28,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "experimental",
        },
        {
            "source_names": ("damping_or_tau",),
            "name": "damping",
            "type": "hkReal",
            "offset": 0x2C,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hknpSharedMotionProperties": (
        {
            "source_names": ("motion_scale",),
            "name": "motionScale",
            "type": "hkReal",
            "offset": 0x04,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "experimental",
        },
        {
            "source_names": ("damping_or_solver_a",),
            "name": "linearDamping",
            "type": "hkReal",
            "offset": 0x10,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "experimental",
        },
        {
            "source_names": ("damping_or_solver_b",),
            "name": "angularDamping",
            "type": "hkReal",
            "offset": 0x14,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "experimental",
        },
        {
            "source_names": ("gravity_or_response_factor",),
            "name": "gravityFactor",
            "type": "hkReal",
            "offset": 0x18,
            "array_status": "none",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hknpMaterial": (
        {
            "source_names": ("material[0]",),
            "name": "entries",
            "type": "hkArray<hknpMaterial>",
            "offset": 0,
            "array_status": "row_list",
            "reference_status": "none",
            "confidence": "experimental",
        },
        {
            "source_names": ("material_name_reference",),
            "name": "name",
            "type": "hkStringPtr",
            "offset": 0,
            "array_status": "none",
            "reference_status": "string_reference",
            "confidence": "experimental",
        },
    ),
    "hknpMeshShape::GeometrySection": (
        {
            "source_names": ("aabb_tree_relative_offset",),
            "name": "aabbTree",
            "type": "hkArray<hknpAabb8TreeNode>",
            "offset": 0x00,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("primitive_relative_offset",),
            "name": "primitives",
            "type": "hkArray<hknpMeshShape::GeometrySection::Primitive>",
            "offset": 0x08,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("mesh_byte_buffer_relative_offset",),
            "name": "meshData",
            "type": "hkArray<hkUint8>",
            "offset": 0x10,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("secondary_buffer_relative_offset",),
            "name": "secondaryData",
            "type": "hkArray<hkUint8>",
            "offset": 0x18,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
    ),
    "hknpMeshShape::GeometrySection::Primitive": (
        {
            "source_names": ("primitive_words",),
            "name": "primitiveData",
            "type": "hkArray<hkUint32>",
            "offset": 0,
            "array_status": "scalar_list",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hknpMeshShape::ShapeTagTableEntry": (
        {
            "source_names": ("shape_tag_entry[0]",),
            "name": "entries",
            "type": "hkArray<hknpMeshShape::ShapeTagTableEntry>",
            "offset": 0,
            "array_status": "row_list",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hknpShapeProperties::Entry": (
        {
            "source_names": ("property_entry[0]",),
            "name": "entries",
            "type": "hkArray<hknpShapeProperties::Entry>",
            "offset": 0,
            "array_status": "row_list",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hknpShapeMassProperties": (
        {
            "source_names": ("mass_property_float4_rows",),
            "name": "properties",
            "type": "hkMatrix4",
            "offset": 0,
            "array_status": "fixed_rows",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hkCompressedMassProperties": (
        {
            "source_names": ("compressed_mass_properties_sample",),
            "name": "compressedProperties",
            "type": "hkCompressedMassProperties",
            "offset": 0,
            "array_status": "fixed_payload",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hknpCompoundShape": (
        {
            "source_names": ("shape_instances_or_storage_pair",),
            "name": "shapeInstances",
            "type": "hkArray<hknpShapeInstance>",
            "offset": 0x20,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("simd_tree_or_bounds_pair",),
            "name": "tree",
            "type": "hkArray<hkcdSimdTreeNamespace::Node>",
            "offset": 0x30,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
    ),
    "hknpShapeInstance": (
        {
            "source_names": ("shape_instance[0]",),
            "name": "instances",
            "type": "hkArray<hknpShapeInstance>",
            "offset": 0,
            "array_status": "row_list",
            "reference_status": "object_reference",
            "confidence": "experimental",
        },
    ),
    "hkcdSimdTreeNamespace::Node": (
        {
            "source_names": ("simd_tree_node[0]",),
            "name": "nodes",
            "type": "hkArray<hkcdSimdTreeNamespace::Node>",
            "offset": 0,
            "array_status": "row_list",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hknpAabb8TreeNode": (
        {
            "source_names": ("simd_tree_node[0]",),
            "name": "nodes",
            "type": "hkArray<hknpAabb8TreeNode>",
            "offset": 0,
            "array_status": "row_list",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hkSkeleton": (
        {
            "source_names": ("bones_reference_or_count_pair",),
            "name": "bones",
            "type": "hkArray<hkBone>",
            "offset": 0x18,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("parent_indices_reference_or_count_pair",),
            "name": "parentIndices",
            "type": "hkArray<hkInt16>",
            "offset": 0x28,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("reference_pose_reference_or_count_pair",),
            "name": "referencePose",
            "type": "hkArray<hkQsTransform>",
            "offset": 0x38,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("float_slots_or_metadata_pair",),
            "name": "floatSlots",
            "type": "hkArray<hkReal>",
            "offset": 0x48,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
    ),
    "hkBone": (
        {
            "source_names": ("bone[0]",),
            "name": "bones",
            "type": "hkArray<hkBone>",
            "offset": 0,
            "array_status": "row_list",
            "reference_status": "string_reference",
            "confidence": "experimental",
        },
    ),
    "hkQsTransform": (
        {
            "source_names": ("qs_transform[0]",),
            "name": "transforms",
            "type": "hkArray<hkQsTransform>",
            "offset": 0,
            "array_status": "row_list",
            "reference_status": "none",
            "confidence": "strong inference",
        },
    ),
    "hkaSkeletonMapper": (
        {
            "source_names": ("source_skeleton_or_root_reference",),
            "name": "source",
            "type": "hkRefPtr<hkSkeleton>",
            "offset": 0x20,
            "array_status": "none",
            "reference_status": "object_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("target_skeleton_or_root_reference",),
            "name": "target",
            "type": "hkRefPtr<hkSkeleton>",
            "offset": 0x28,
            "array_status": "none",
            "reference_status": "object_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("mapper_data_or_mapping_reference",),
            "name": "mapping",
            "type": "hkArray<hkaSkeletonMapperData::SimpleMapping>",
            "offset": 0x60,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
    ),
    "hkaSkeletonMapperData::SimpleMapping": (
        {
            "source_names": ("simple_mapping[0]",),
            "name": "simpleMappings",
            "type": "hkArray<hkaSkeletonMapperData::SimpleMapping>",
            "offset": 0,
            "array_status": "row_list",
            "reference_status": "none",
            "confidence": "experimental",
        },
    ),
    "hkaAnimationContainer": (
        {
            "source_names": ("animation_container_pair_0x0",),
            "name": "animations",
            "type": "hkArray<hkaAnimation>",
            "offset": 0x00,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("animation_container_pair_0x8",),
            "name": "bindings",
            "type": "hkArray<hkaAnimationBinding>",
            "offset": 0x08,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
        {
            "source_names": ("animation_container_pair_0x10",),
            "name": "skeletons",
            "type": "hkArray<hkSkeleton>",
            "offset": 0x10,
            "array_status": "hkArray",
            "reference_status": "array_data_reference",
            "confidence": "experimental",
        },
    ),
}










































































def _hkx_record_by_index(records: Sequence[HkxItemRecord], record_index: Optional[int]) -> Optional[HkxItemRecord]:
    if record_index is None:
        return None
    return next((record for record in records if record.index == record_index), None)




def _hkx_json_number_vector(values: Sequence[float]) -> List[float]:
    return [float(value) for value in values]


_HKX_EDITABLE_GEOMETRY_FIELD_DESCRIPTIONS: Dict[str, str] = {
    "vertices": (
        "Editable. Local-space convex hull vertex positions as [x, y, z] floats. "
        "You may move existing vertices, but do not add, remove, reorder, or change the row count."
    ),
    "planes": (
        "Editable with care. Convex hull plane equations as [normal_x, normal_y, normal_z, distance] floats. "
        "These should remain consistent with the vertices; incorrect planes can make collision behave badly."
    ),
    "faces": (
        "Read-only. Face loops decoded from the hull face index buffer. They are included to help identify the "
        "shape, but the importer will not rebuild face or edge topology from edits."
    ),
    "sphere_center": (
        "Editable. Local-space sphere center as [x, y, z] floats. This is stored in an hkFloat3 record."
    ),
    "sphere_radius": (
        "Editable. Sphere radius as a positive float. The importer patches the known radius slot in the "
        "hknpSphereShape payload."
    ),
    "capsule_radius": (
        "Editable. Capsule radius as a positive float. The importer patches the inferred radius slot in the "
        "hknpCapsuleShape payload at offset 0x68."
    ),
    "capsule_endpoints": (
        "Editable. Capsule segment endpoints as exactly two [x, y, z] hkFloat3 rows. "
        "The capsule radius expands around this segment."
    ),
    "mass_properties": (
        "Experimental editable. Four rows of four float values from the hknpShapeMassProperties payload. "
        "The exact Havok 2024.2 field names are not fully recovered yet, so only fixed-size numeric edits are supported."
    ),
    "shape_payload": (
        "Experimental editable. Non-zero float slots found inside the fixed-size hknp shape object payload. "
        "Offsets are preserved on import; integer-looking offsets, counts, and references remain read-only."
    ),
    "hull_topology": (
        "Experimental editable. Convex hull face table, face index buffer, and edge/support pair tables. "
        "Counts must stay unchanged and indices must continue to reference existing vertices."
    ),
    "bounds_min": (
        "Informational. Minimum decoded geometry bounds as [x, y, z]. This is recomputed by the exporter and "
        "is not imported."
    ),
    "bounds_max": (
        "Informational. Maximum decoded geometry bounds as [x, y, z]. This is recomputed by the exporter and "
        "is not imported."
    ),
    "center": "Informational. Approximate center of decoded bounds. This is recomputed by the exporter and is not imported.",
    "extent": "Informational. Approximate decoded bounds size. This is recomputed by the exporter and is not imported.",
    "mesh_summary": (
        "Informational. hknpMeshShape table counts. Mesh primitive/index buffers are not editable yet."
    ),
    "mesh_details": (
        "Read-only. Structured hknpMeshShape sub-record dump for geometry sections, primitive words, AABB tree "
        "nodes, shape tags, and related byte buffers. Raw bytes are preserved; topology edits are not supported yet."
    ),
    "capsule_summary": (
        "Informational. hknpCapsuleShape endpoints/radius inferred for inspection. Use capsule_radius and "
        "capsule_endpoints for fixed-size edits where records are available."
    ),
    "box_summary": (
        "Read-only. hknpBoxShape local-frame/extent candidates inferred from fixed payload slots. "
        "This makes box collision records visible in the browser and 3D overlay, but exact Havok field names "
        "are still experimental."
    ),
}


_HKX_EDITABLE_GEOMETRY_VALUE_LAYOUTS: Dict[str, object] = {
    "vertices": {
        "row": "[x, y, z]",
        "components": {
            "x": "Local-space X position.",
            "y": "Local-space Y position.",
            "z": "Local-space Z position.",
        },
    },
    "planes": {
        "row": "[normal_x, normal_y, normal_z, distance]",
        "components": {
            "normal_x": "Plane normal X component.",
            "normal_y": "Plane normal Y component.",
            "normal_z": "Plane normal Z component.",
            "distance": "Plane equation distance term. Keep this consistent with the edited hull vertices.",
        },
    },
    "sphere_center": {
        "value": "[x, y, z]",
        "components": {
            "x": "Local-space sphere center X position.",
            "y": "Local-space sphere center Y position.",
            "z": "Local-space sphere center Z position.",
        },
    },
    "sphere_radius": {
        "value": "positive float",
        "components": {
            "radius": "Local-space sphere radius. Must stay greater than zero.",
        },
    },
    "capsule_radius": {
        "value": "positive float",
        "components": {
            "radius": "Local-space capsule radius. Must stay greater than zero.",
        },
    },
    "capsule_endpoints": {
        "rows": "2 rows of [x, y, z]",
        "components": {
            "start": "Local-space capsule segment start point.",
            "end": "Local-space capsule segment end point.",
        },
    },
    "mass_properties": {
        "rows": "4 rows of [x, y, z, w] float values",
        "components": {
            "row0": "Unverified hknpShapeMassProperties float row 0.",
            "row1": "Unverified hknpShapeMassProperties float row 1.",
            "row2": "Unverified hknpShapeMassProperties float row 2.",
            "row3": "Unverified hknpShapeMassProperties float row 3.",
        },
    },
    "shape_payload": {
        "rows": "fixed-offset float slots: {offset, value}",
        "components": {
            "offset": "Byte offset inside the hknp shape object payload. This must not change.",
            "value": "Float value to patch at the same payload offset.",
        },
    },
    "hull_topology": {
        "value": "{face_records, face_indices, edge_tables}",
        "components": {
            "face_records": "Fixed-count records with index_start, vertex_count, and meta.",
            "face_indices": "Fixed-count byte index buffer used by face records.",
            "edge_tables": "Fixed-count uint16 pair tables. Exact hknp meaning is still unverified.",
        },
    },
}


def _hkx_export_float_vectors_for_record(
    data: bytes,
    spans: Mapping[int, Tuple[int, int]],
    record: Optional[HkxItemRecord],
    components: int,
    stride: int,
) -> List[List[float]]:
    return [_hkx_json_number_vector(value) for value in _read_hkx_float_vector_payload(data, spans, record, components, stride)]


def _hkx_export_mass_property_rows_for_record(
    data: bytes,
    spans: Mapping[int, Tuple[int, int]],
    record: Optional[HkxItemRecord],
) -> List[List[float]]:
    if record is None or record.type_name != "hknpShapeMassProperties":
        return []
    span = spans.get(record.index)
    if span is None:
        return []
    start, end = span
    if end - start < 64:
        return []
    rows = _summarize_hkx_float_rows(data[start : start + 64], row_count=4, components=4)
    return [_hkx_json_number_vector(row) for row in rows] if len(rows) == 4 else []




def _hkx_shape_payload_float_description(type_name: str, offset: int) -> str:
    if type_name == "hknpConvexShape" and offset in {0x68, 0x6C}:
        return (
            "Unverified hknpConvexShape float slot observed across Crimson Desert samples. "
            "The importer can patch this fixed offset, but the exact Havok field name is not recovered yet."
        )
    return (
        f"Unverified {type_name or 'hknp shape'} float slot. "
        "Patch only if you are intentionally experimenting with this fixed payload offset."
    )






def _hkx_mesh_payload_digest(payload: bytes) -> Dict[str, object]:
    return {
        "sha1": hashlib.sha1(payload).hexdigest(),
        "sample_hex": _hkx_payload_hex(payload[:64]),
        "sample_byte_count": min(len(payload), 64),
    }


def _hkx_mesh_record_base(record: HkxItemRecord, payload: bytes, role: str) -> Dict[str, object]:
    stride = len(payload) // record.count if record.count and len(payload) % record.count == 0 else None
    return {
        "record_index": int(record.index),
        "type_name": record.type_name,
        "role": role,
        "count": int(record.count),
        "data_offset": int(record.data_offset),
        "absolute_data_offset": int(record.absolute_data_offset) if record.absolute_data_offset is not None else None,
        "byte_length": len(payload),
        "stride": stride,
        "status": "read_only_schema_recovery",
        "confidence": "experimental",
        "raw_preservation": _hkx_mesh_payload_digest(payload),
    }


def _hkx_first_u32_words(payload: bytes, count: int) -> List[int]:
    return [struct.unpack_from("<I", payload, offset * 4)[0] for offset in range(min(count, len(payload) // 4))]








def _hkx_finite_float_slots(payload: bytes, *, limit_bytes: int = 192, limit: int = 32) -> List[Dict[str, object]]:
    values: List[Dict[str, object]] = []
    for offset in range(0, min(len(payload), limit_bytes) - 3, 4):
        value = struct.unpack_from("<f", payload, offset)[0]
        if not math.isfinite(value) or abs(value) < 1e-8 or abs(value) > 1_000_000.0:
            continue
        values.append({"offset": offset, "hex_offset": f"0x{offset:X}", "value": float(value)})
        if len(values) >= limit:
            break
    return values






def _hkx_mesh_record_index_at_data_offset(records: Sequence[HkxItemRecord], data_offset: int, type_name: str) -> Optional[int]:
    for record in records:
        if int(record.data_offset) == int(data_offset) and record.type_name == type_name:
            return int(record.index)
    return None














def _hkx_payload_hex(payload: bytes) -> str:
    return payload.hex(" ")


def _hkx_decode_char_payload_text(payload: bytes, count: int) -> str:
    sample = payload[: max(0, min(len(payload), int(count) if count > 0 else len(payload)))]
    if b"\0" in sample:
        sample = sample.split(b"\0", 1)[0]
    try:
        text = sample.decode("utf-8", errors="replace").strip()
    except Exception:
        text = ""
    if not text:
        return ""
    printable_count = sum(1 for char in text if char.isprintable())
    if printable_count < max(1, len(text) * 3 // 4):
        return ""
    return text


def _hkx_parse_payload_hex(value: object, *, name: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a hex string.")
    compact = re.sub(r"[^0-9A-Fa-f]", "", value)
    if len(compact) % 2:
        raise ValueError(f"{name} must contain an even number of hex digits.")
    try:
        return bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError(f"{name} contains invalid hex.") from exc














def _hkx_is_known_generic_container_type(type_name: str) -> bool:
    return (
        type_name.startswith("hkArray")
        or type_name.startswith("hkRefPtr")
        or type_name.startswith("hkFreeListArrayElement")
    )








def _hkx_tag_sections_document(summary: HkxTagfileSummary) -> List[Dict[str, object]]:
    return [
        {
            "name": item.name,
            "offset": item.offset,
            "length_word_offset": item.length_word_offset,
            "raw_length_word": item.raw_length_word,
            "declared_length": item.declared_length,
            "length_flags": item.length_flags,
            "data_end": item.word_end_offset,
        }
        for item in summary.tag_items
    ]


def _hkx_tag_item_payload(data: bytes, items: Sequence[HkxTagItem], name: str) -> bytes:
    item = _hkx_tag_item_by_name(items, name)
    if item is None or item.offset + 4 > len(data):
        return b""
    if item.word_end_offset is not None and item.word_end_offset <= len(data):
        payload_end = item.word_end_offset
    elif item.marker_end_offset is not None and item.marker_end_offset <= len(data):
        payload_end = item.marker_end_offset
    else:
        next_item = _hkx_next_tag_item(items, item)
        payload_end = next_item.length_word_offset if next_item and next_item.length_word_offset else len(data)
    payload_start = item.offset + 4
    return data[payload_start : max(payload_start, min(payload_end, len(data)))]




















def _hkx_havok_schema_base_name(type_name: str) -> str:
    if type_name.startswith("hkArray"):
        return "hkArray"
    if type_name.startswith("hkRefPtr"):
        return "hkRefPtr"
    return type_name


def _hkx_havok_member_rows_for_type(type_name: str) -> List[Dict[str, object]]:
    rows = _HKX_HAVOK_MEMBER_SCHEMA.get(type_name)
    if rows is None:
        rows = _HKX_HAVOK_MEMBER_SCHEMA.get(_hkx_havok_schema_base_name(type_name), ())
    return [_hkx_havok_enrich_member_row(row) for row in rows]


def _hkx_havok_member_by_source_name(type_name: str, field_name: str) -> Optional[Dict[str, object]]:
    for member in _hkx_havok_member_rows_for_type(type_name):
        source_names = member.get("source_names")
        if isinstance(source_names, tuple) and field_name in source_names:
            return member
        if isinstance(source_names, list) and field_name in source_names:
            return member
    return None






def _hkx_havok_enrich_member_row(member: Mapping[str, object]) -> Dict[str, object]:
    row = dict(member)
    for key, value in _hkx_havok_member_type_metadata(row).items():
        row.setdefault(key, value)
    row.setdefault("flags", "FLAGS_NONE")
    row.setdefault("cdmw_recovered", False)
    return row






def _hkx_havok_param_name_for_field(type_name: str, field: Mapping[str, object]) -> str:
    field_name = str(field.get("name") or "")
    member = _hkx_havok_member_by_source_name(type_name, field_name)
    if isinstance(member, Mapping):
        return str(member.get("name") or field_name)
    if field_name.startswith("finite_float_") or field_name.startswith("u32_") or "candidate" in field_name:
        return f"cdmwRecovered_{field_name}"
    return field_name


def _hkx_havok_data_type_for_field(type_name: str, field: Mapping[str, object]) -> str:
    member = _hkx_havok_member_by_source_name(type_name, str(field.get("name") or ""))
    if isinstance(member, Mapping) and str(member.get("type") or ""):
        return str(member["type"])
    return str(field.get("data_type") or "unknown")


def _hkx_havok_array_status_for_field(type_name: str, field: Mapping[str, object]) -> str:
    member = _hkx_havok_member_by_source_name(type_name, str(field.get("name") or ""))
    if isinstance(member, Mapping):
        return str(member.get("array_status") or "none")
    data_type = str(field.get("data_type") or "")
    if "[]" in data_type or "array" in data_type.lower():
        return "array_like"
    return "none"


def _hkx_havok_reference_status_for_field(type_name: str, field: Mapping[str, object]) -> str:
    member = _hkx_havok_member_by_source_name(type_name, str(field.get("name") or ""))
    if isinstance(member, Mapping):
        return str(member.get("reference_status") or "none")
    data_type = str(field.get("data_type") or "").lower()
    if "reference" in data_type:
        return _hkx_havok_reference_category(
            source_type_name=type_name,
            field_name=str(field.get("name") or ""),
            offset=field.get("offset") if isinstance(field.get("offset"), int) else None,
        )
    return "none"


def _hkx_havok_confidence_for_field(type_name: str, field: Mapping[str, object]) -> str:
    member = _hkx_havok_member_by_source_name(type_name, str(field.get("name") or ""))
    if isinstance(member, Mapping) and str(member.get("confidence") or ""):
        return str(member["confidence"])
    return str(field.get("confidence") or "experimental")






def _hkx_havok_xml_reference_target(reference: Mapping[str, object]) -> str:
    target_record_index = reference.get("target_record_index")
    if isinstance(target_record_index, int):
        return f"#record{target_record_index}"
    if isinstance(target_record_index, str) and target_record_index.strip().lstrip("-").isdigit():
        return f"#record{int(target_record_index)}"
    return ""






def _hkx_havok_xml_reference_record_index(reference: Optional[Mapping[str, object]]) -> Optional[int]:
    if not isinstance(reference, Mapping):
        return None
    target_record_index = reference.get("target_record_index")
    if isinstance(target_record_index, int):
        return target_record_index
    if isinstance(target_record_index, str) and target_record_index.strip().lstrip("-").isdigit():
        return int(target_record_index)
    return None






def _hkx_havok_xml_array_element_type(data_type: str) -> str:
    text = str(data_type or "").strip()
    if text.startswith("hkArray<") and text.endswith(">"):
        text = text[len("hkArray<") : -1].strip()
    while text.startswith("hkRefPtr<") and text.endswith(">"):
        text = text[len("hkRefPtr<") : -1].strip()
    return text


def _hkx_havok_xml_type_matches_expected(record_type_name: str, expected_type_name: str) -> bool:
    record_type = str(record_type_name or "")
    raw_expected = str(expected_type_name or "")
    if raw_expected.startswith("hkRefPtr<") and record_type.startswith("hkRefPtr<"):
        return True
    expected = _hkx_havok_xml_array_element_type(raw_expected)
    if not expected or expected in {"void", "void*", "hkReferencedObject*", "hkRefVariant"}:
        return True
    if record_type == expected:
        return True
    if expected == "hknpShape" and record_type.startswith("hknp") and record_type.endswith("Shape"):
        return True
    return False


def _hkx_havok_xml_target_record_for_offset(value: Optional[int], summary: HkxTagfileSummary) -> Optional[HkxItemRecord]:
    if not isinstance(value, int) or value <= 0:
        return None
    for record in summary.item_records:
        if int(record.data_offset) == value:
            return record
    for record in summary.item_records:
        if record.absolute_data_offset is not None and int(record.absolute_data_offset) == value:
            return record
    return None














def _hkx_real_hkclass_metadata_by_name(summary: HkxTagfileSummary) -> Dict[str, Dict[str, object]]:
    report = summary.native_real_hkclass_metadata_v2 if isinstance(summary.native_real_hkclass_metadata_v2, Mapping) and summary.native_real_hkclass_metadata_v2 else summary.native_real_hkclass_metadata
    if not isinstance(report, Mapping):
        return {}
    classes = report.get("classes")
    if not isinstance(classes, list):
        return {}
    by_name: Dict[str, Dict[str, object]] = {}
    for row in classes:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("class_name") or row.get("name") or "")
        if name:
            by_name[name] = dict(row)
    return by_name








_HKX_REAL_HKCLASS_METADATA_REQUIREMENTS: Tuple[Tuple[str, str, str], ...] = (
    ("member_type_codes", "member type codes", "True hkClass member type/subtype codes instead of CDMW inferred strings."),
    ("member_flags", "member flags", "Real Havok member flags and storage flags."),
    ("base_classes", "base classes", "Base class references and inheritance metadata."),
    ("enum_refs", "enum refs", "Enum class references for enum/flags members."),
    ("signatures", "signatures", "Real Havok class signatures instead of synthetic comparison hashes."),
    ("versions", "versions", "Real class version semantics."),
    ("default_values", "default values", "Default member values where Havok stores or implies them."),
    ("template_refs", "template refs", "Resolved template parameters and referenced type/class objects."),
)


_HKX_NATIVE_MODEL_GRAPH_REQUIREMENTS: Tuple[Tuple[str, str, str], ...] = (
    (
        "fixup_backed_object_refs",
        "fixup-backed object refs",
        "Native object graph edges built from PTCH/INDX fixup semantics instead of Python offset inference.",
    ),
    (
        "owner_arrays",
        "owner arrays",
        "Native owner/context mapping for hkArray fields such as materials, bodies, constraints, skeleton, animation, and mesh arrays.",
    ),
    (
        "root_container_semantics",
        "root/container semantics",
        "Native hkRootLevelContainer::NamedVariant and nested scene/system/ragdoll/animation root interpretation.",
    ),
    (
        "native_export_graph",
        "native export graph",
        "Native graph model that can feed Havok-style XML, CDMW patch exports, and eventually the binary writer.",
    ),
)


_HKX_NO_EDIT_BINARY_WRITER_REQUIREMENTS: Tuple[Tuple[str, str, str], ...] = (
    (
        "section_table_roundtrip",
        "section table roundtrip",
        "Preserve original TAG0 sections, section lengths, flags, ordering, and alignment exactly.",
    ),
    (
        "item_table_roundtrip",
        "item table roundtrip",
        "Preserve ITEM records, type flags, counts, offsets, and data spans exactly for no-edit output.",
    ),
    (
        "fixup_table_roundtrip",
        "fixup table roundtrip",
        "Preserve PTCH/INDX/TPAD fixup payloads, tuple encoding, null refs, and unresolved variants exactly.",
    ),
    (
        "unknown_payload_roundtrip",
        "unknown payload roundtrip",
        "Preserve unknown object bytes and padding without normalization or schema-driven rewriting.",
    ),
    (
        "representative_byte_identity",
        "representative byte identity",
        "Pass native read -> model -> write byte-identical no-edit rebuilds across object, meshphysics, character, ragdoll, mesh-heavy, and animation samples.",
    ),
)


_HKX_REPRESENTATIVE_BINARY_WRITER_ROLES: Tuple[str, ...] = (
    "object_hkx",
    "cloak_or_meshphysics_hkx",
    "character_havokphysics_hkx",
    "ragdoll_or_body_hkx",
    "mesh_shape_heavy_hkx",
    "animation_or_metadata_hkx",
)


_HKX_CLASS_INTERNAL_TARGETS: Tuple[Tuple[str, str], ...] = (
    (
        "hknpPhysicsSystemData",
        "System arrays, material/motion/body/constraint ownership, shape references, and stable object ordering.",
    ),
    (
        "hknpPhysicsSystemData::ExtendedBodyCinfo",
        "Body transform, shape pointer, material id, motion properties, collision/filter flags, mass and activation fields.",
    ),
    (
        "hknpConstraintCinfo",
        "Body pair references, constraint data reference, priority/flags, pivot frames, and solver/motor ownership.",
    ),
    (
        "hknpRagdollConstraintData",
        "Cone/twist limits, local frames, friction torque, motor references, angular basis, and solver parameters.",
    ),
    (
        "hknpSharedMotionProperties",
        "Damping, gravity factor, inertia/mass factors, solver stabilization, quality and motion flags.",
    ),
    (
        "hknpMaterial",
        "Friction/restitution, combine policies, collision flags, material ids, and game-side material mapping.",
    ),
    (
        "hknpMeshShape",
        "Geometry sections, primitive bit layout, AABB tree nodes, shape tags, buffers, materials, and property entries.",
    ),
    (
        "skeleton_animation_containers",
        "hkSkeleton, bones, transforms, animation containers, mapper arrays, clips, and binding/reference ownership.",
    ),
)


_HKX_HARD_DECODER_TARGETS: Tuple[Tuple[str, str, str, Tuple[str, ...]], ...] = (
    (
        "hknp_mesh_primitive_bit_layout",
        "hknpMeshShape primitive bit layout",
        "Decode exact mesh primitive tuple packing, winding, index references, shape-key bits, and material/section ownership.",
        ("hknpMeshShape",),
    ),
    (
        "hknp_mesh_aabb_tree",
        "hknpMeshShape AABB tree",
        "Decode hkcdSimdTreeNamespace::Node encoding, bounds quantization, child/leaf flags, and mesh section linkage.",
        ("hknpMeshShape", "hkcdSimdTreeNamespace::Node"),
    ),
    (
        "hknp_mesh_shape_tags",
        "hknpMeshShape shape tags",
        "Decode shape tag ranges, table ownership, tag/material mapping, and per-primitive tag resolution.",
        ("hknpMeshShape",),
    ),
    (
        "compound_child_transforms",
        "compound child transforms",
        "Decode hknpCompoundShape child instances, local transforms, child shape refs, tree nodes, and instance/property ownership.",
        ("hknpCompoundShape", "hknpShapeInstance"),
    ),
    (
        "compressed_mass_properties",
        "compressed mass properties",
        "Decode hkCompressedMassProperties and hknpShapeMassProperties fields, compressed inertia, center of mass, and mass factors.",
        ("hkCompressedMassProperties", "hknpShapeMassProperties"),
    ),
    (
        "material_property_entries",
        "material/property entries",
        "Decode hknpMaterial internals, shape material/property entries, free-list entries, ids, flags, and game material mapping.",
        ("hknpMaterial", "hknpShapeProperties::Entry", "hkFreeListArrayElement<tVALUE_TYPE=7>"),
    ),
    (
        "skeleton_animation_containers",
        "skeleton/animation containers",
        "Decode hkSkeleton, hkaAnimationContainer, skeleton mapper arrays, clips, bindings, transforms, and animation references.",
        ("hkSkeleton", "hkaAnimationContainer", "hkaSkeletonMapper"),
    ),
)


_HKX_GUI_USABILITY_TARGETS: Tuple[Tuple[str, str, str, str], ...] = (
    (
        "visual_object_value_linking",
        "visual object-to-value linking",
        "partial",
        "Click/select physics shapes, bodies, and constraints in 3D and show all linked records, rows, offsets, confidence, and editable values.",
    ),
    (
        "connected_physics_panel",
        "connected physics panel",
        "partial",
        "Present selected mesh/shape -> body -> constraints -> motors -> materials -> editable values in one coherent relationship pane.",
    ),
    (
        "coherent_browser_editor_flow",
        "coherent browser/editor flow",
        "partial",
        "Make HKX Browser, Structured Editor, raw XML, guide, and preview feel like one workflow instead of separate tools.",
    ),
    (
        "confidence_first_editing",
        "confidence-first editing",
        "partial",
        "Prioritize safe patchable values visually, quiet experimental rows, and expose Safe/Inferred/Experimental filters.",
    ),
    (
        "value_formatting_and_color",
        "value formatting and color",
        "partial",
        "Improve numeric/vector/reference formatting, confidence colors, row density, and readability across the Edit HKX function.",
    ),
    (
        "before_after_preview",
        "before/after preview",
        "missing",
        "When a value changes, highlight affected 3D objects and show original/current values side by side.",
    ),
    (
        "preset_workflows",
        "preset workflows",
        "missing",
        "Add task filters such as make capsule bigger, adjust joint stiffness, reduce damping, inspect ragdoll body, and inspect mesh shape.",
    ),
)






def _hkx_havok_xml_record_ref(
    record_index: Optional[int],
    record_by_index: Mapping[int, HkxItemRecord],
) -> Tuple[str, str]:
    if not isinstance(record_index, int):
        return "", ""
    record = record_by_index.get(record_index)
    return f"#record{record_index}", record.type_name if record is not None else ""


def _hkx_havok_xml_shape_hint_for_object(
    object_info: Mapping[str, object],
    summary: HkxTagfileSummary,
) -> Optional[HkxCollisionGeometryHint]:
    record_index = object_info.get("record_index")
    if not isinstance(record_index, int):
        return None
    return next((hint for hint in summary.collision_geometry_hints if hint.shape_record_index == record_index), None)


















def _hkx_converter_objects_document(advanced_payloads: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    return [_hkx_converter_record_document(payload_info) for payload_info in advanced_payloads]




def _hkx_layout_field(
    *,
    name: str,
    offset: int,
    size: int,
    data_type: str,
    value: object = None,
    description: str = "",
    confidence: str = "experimental",
    editable: bool = False,
    decode_source: str = "",
    decode_strength: str = "",
    read_only_reason: str = "",
    safe_edit_policy: str = "",
) -> Dict[str, object]:
    confidence_key = str(confidence or "").strip().casefold()
    if not decode_strength:
        if confidence_key in {"confirmed", "strong inference", "strong_inference"}:
            decode_strength = confidence
        elif confidence_key in {"raw", "raw_preserved"}:
            decode_strength = "raw"
        else:
            decode_strength = "candidate_only" if not editable else "experimental"
    if not decode_source:
        if editable or confidence_key in {"confirmed", "strong inference", "strong_inference"}:
            decode_source = "typed_layout"
        elif confidence_key in {"raw", "raw_preserved"}:
            decode_source = "raw_sample"
        else:
            decode_source = "generic_candidate_scan"
    if not safe_edit_policy:
        safe_edit_policy = "fixed_size_patch_only" if editable else "read_only"
    if not read_only_reason and not editable:
        read_only_reason = "Read-only evidence. Editing is disabled until exact Havok member semantics and rebuild rules are proven."
    field = {
        "name": name,
        "offset": offset,
        "hex_offset": f"0x{offset:X}",
        "size": size,
        "data_type": data_type,
        "confidence": confidence,
        "editable": bool(editable),
        "description": description,
        "decode_source": decode_source,
        "decode_strength": decode_strength,
        "safe_edit_policy": safe_edit_policy,
    }
    if read_only_reason:
        field["read_only_reason"] = read_only_reason
    if value is not None:
        field["value"] = value
    return field




def _hkx_uncovered_ranges(covered_ranges: Sequence[Tuple[int, int]], payload_size: int) -> List[Tuple[int, int]]:
    ranges: List[Tuple[int, int]] = []
    cursor = 0
    for start, end in covered_ranges:
        if cursor < start:
            ranges.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < payload_size:
        ranges.append((cursor, payload_size))
    return ranges
























def _hkx_physics_tuning_category(type_name: str) -> str:
    if type_name == "hknpPositionConstraintMotor":
        return "motor_force_response"
    if type_name == "hknpSharedMotionProperties":
        return "motion_damping_solver"
    if type_name == "hknpPhysicsSystemData::ExtendedBodyCinfo":
        return "body_transform_mass"
    if type_name in {"hknpRagdollConstraintData", "hknpLimitedHingeConstraintData"}:
        return "joint_limits_strength"
    return "advanced_physics"


def _hkx_vector_component_slot_name(prefix: str, start_offset: int, offset: int) -> str:
    components = ("x", "y", "z", "w")
    relative = max(0, offset - start_offset)
    row_index = relative // 16
    component_index = (relative % 16) // 4
    component = components[component_index] if component_index < len(components) else str(component_index)
    return f"{prefix}_row{row_index}_{component}"




def _hkx_physics_tuning_confidence(type_name: str, offset: int) -> str:
    if type_name == "hknpPositionConstraintMotor" and offset in {0x20, 0x24}:
        return "strong inference"
    if type_name in {
        "hknpPositionConstraintMotor",
        "hknpSharedMotionProperties",
        "hknpPhysicsSystemData::ExtendedBodyCinfo",
        "hknpRagdollConstraintData",
        "hknpLimitedHingeConstraintData",
    }:
        return "experimental"
    return "raw"












def _hkx_descriptor_numeric_hint_lookup(hints: object, name: str) -> Optional[str]:
    if not isinstance(hints, list):
        return None
    for hint in hints:
        if not isinstance(hint, Mapping):
            continue
        if str(hint.get("name") or "") != name:
            continue
        value = str(hint.get("value") or "").strip()
        if value:
            return value
        values = hint.get("values")
        if isinstance(values, list) and values:
            return str(values[0])
    return None


def _hkx_descriptor_float_hint(hints: object, name: str) -> Optional[float]:
    value = _hkx_descriptor_numeric_hint_lookup(hints, name)
    if value is None:
        return None
    try:
        return float(str(value).split()[0])
    except (TypeError, ValueError):
        return None


def _hkx_descriptor_shape_kind_matches_hkx(descriptor_kind: str, shape_type: str) -> bool:
    descriptor_kind = descriptor_kind.casefold()
    shape_type = shape_type.casefold()
    if descriptor_kind == "capsule":
        return "capsule" in shape_type
    if descriptor_kind == "sphere":
        return "sphere" in shape_type
    if descriptor_kind in {"box", "convex"}:
        return "convex" in shape_type or "box" in shape_type
    if descriptor_kind == "mesh":
        return "mesh" in shape_type
    return True














def _hkx_payload_fixed_float_slots(payload_info: Mapping[str, object]) -> List[Dict[str, object]]:
    editable_values = payload_info.get("editable_values")
    if not isinstance(editable_values, Mapping) or editable_values.get("kind") != "fixed_float_slots":
        return []
    slots: List[Dict[str, object]] = []
    items = editable_values.get("items")
    if not isinstance(items, list):
        return slots
    type_name = str(payload_info.get("type_name") or "")
    for item in items:
        if not isinstance(item, Mapping):
            continue
        item_index = item.get("index")
        for slot in item.get("float_slots", []) if isinstance(item.get("float_slots"), list) else []:
            if not isinstance(slot, Mapping) or not isinstance(slot.get("offset"), int):
                continue
            offset = int(slot["offset"])
            slots.append(
                {
                    "item_index": item_index,
                    "offset": offset,
                    "hex_offset": f"0x{offset:X}",
                    "name": _hkx_physics_tuning_slot_name(type_name, offset),
                    "value": slot.get("value"),
                    "confidence": _hkx_physics_tuning_confidence(type_name, offset),
                    "description": slot.get("description") or _hkx_fixed_float_slot_description(type_name, offset),
                }
            )
    return slots




def _hkx_constraint_name_matches_type(name: str, type_name: str) -> bool:
    lowered = name.casefold()
    if "hinge" in lowered:
        return type_name == "hknpLimitedHingeConstraintData"
    if "ragdoll" in lowered:
        return type_name == "hknpRagdollConstraintData"
    return "constraint" in lowered




def _hkx_editable_shape_field_description(shape: Mapping[str, object], field_name: str) -> str:
    descriptions = shape.get("descriptions")
    if isinstance(descriptions, Mapping) and str(descriptions.get(field_name) or "").strip():
        return str(descriptions.get(field_name) or "")
    if field_name == "hull_topology":
        return "Convex hull topology values with fixed row/value counts. Do not add/remove faces, indices, or edge pairs."
    if field_name == "shape_payload":
        return "Fixed-offset hknp shape payload floats. Exact Havok 2024.2 field names are still experimental."
    if field_name == "mass_properties":
        return "Fixed-size mass-property float rows. Field meaning is still experimental; values are patched in place."
    return f"Editable {field_name} value group. Keep the original row/count structure."








def _hkx_append_editable_catalog_field(fields: List[Dict[str, object]], field: Dict[str, object]) -> None:
    field.update(_hkx_editable_catalog_semantics(field))
    type_name = str(field.get("source_type_name") or field.get("type_name") or "")
    offset = field.get("offset")
    name = str(field.get("name") or "")
    if isinstance(offset, int) and type_name.startswith("hknp"):
        field.update(_hkx_physics_tuning_user_guidance(type_name, offset, name))
    elif str(field.get("category") or "") == "collision_shape":
        field.setdefault("plain_language_effect", str(field.get("effect") or "collision shape"))
        field.setdefault("if_increased", "The collision volume or value usually becomes larger or stronger when this numeric value is increased.")
        field.setdefault("if_decreased", "The collision volume or value usually becomes smaller or looser when this numeric value is decreased.")
        field.setdefault("safe_edit_hint", str(field.get("suggested_edit_step") or "Use small changes and test in game."))
        field.setdefault("edit_risk", "medium" if field.get("confidence") == "strong inference" else "high")
    fields.append(field)




def _hkx_record_absolute_offset(records_by_index: Mapping[int, HkxItemRecord], record_index: object) -> Optional[int]:
    if not isinstance(record_index, int):
        return None
    record = records_by_index.get(record_index)
    if record is None or record.absolute_data_offset is None:
        return None
    return int(record.absolute_data_offset)




def _hkx_patch_map_risk_label(confidence: str, category: str, name: str) -> str:
    confidence_key = str(confidence or "").strip().lower()
    haystack = f"{category} {name}".casefold()
    if confidence_key in {"confirmed", "strong inference", "strong_inference"}:
        if any(token in haystack for token in ("transform", "orientation", "mass", "inertia", "shape_payload")):
            return "high"
        return "medium"
    if confidence_key in {"descriptor_context", "descriptor-context"}:
        return "medium"
    return "high"


def _hkx_patch_map_structural_kind(value_type: str, category: str, name: str) -> str:
    haystack = f"{category} {name} {value_type}".casefold()
    if any(token in haystack for token in ("topology", "primitive_count", "shape_tag", "aabb", "array", "ref", "string", "count")):
        return "structural_blocked"
    if "float" in haystack or "f32" in haystack:
        return "fixed_size_numeric"
    if "uint" in haystack or "int" in haystack or "byte" in haystack:
        return "fixed_size_integer"
    return "fixed_size_value"


def _hkx_patch_map_link_evidence(category: str, name: str, confidence: str) -> str:
    haystack = f"{category} {name}".casefold()
    if "physics_tuning" in haystack or "motor" in haystack or "constraint" in haystack or "body" in haystack:
        return "typed_layout"
    if "collision_shape" in haystack or "shape" in haystack or "radius" in haystack or "capsule" in haystack:
        return "typed_layout"
    if str(confidence or "").strip().lower() in {"confirmed", "strong inference", "strong_inference"}:
        return "inferred"
    return "context"


def _hkx_patch_map_task_key(category: str, name: str, owner_class: str = "", member: str = "", description: str = "") -> str:
    haystack = f"{category} {name} {owner_class} {member} {description}".casefold()
    if any(token in haystack for token in ("material", "friction", "restitution", "surface")):
        return "material_friction"
    if any(token in haystack for token in ("damping", "motion", "velocity", "sharedmotion")):
        return "damping_motion"
    if any(token in haystack for token in ("constraint", "motor", "stiffness", "strength", "force", "torque", "limit", "hinge", "ragdoll")):
        return "joint_strength"
    if any(token in haystack for token in ("body", "transform", "orientation", "mass")):
        return "body_transform"
    if any(token in haystack for token in ("primitive", "winding", "aabb", "topology")):
        return "mesh_winding"
    if any(token in haystack for token in ("collision", "shape", "radius", "capsule", "sphere", "extent", "vertex", "plane")):
        return "collision_size"
    return "inspect_only"


def _hkx_patch_map_task_label(task_key: object) -> str:
    return {
        "collision_size": "Collision Size",
        "body_transform": "Body Transform",
        "joint_strength": "Joint Strength",
        "damping_motion": "Damping / Motion",
        "material_friction": "Material / Friction",
        "mesh_winding": "Mesh Winding",
        "inspect_only": "Inspect Only",
    }.get(str(task_key or ""), "Inspect Only")


def _hkx_add_patch_map_entry(
    entries: List[Dict[str, object]],
    *,
    data: bytes,
    path: str,
    category: str,
    name: str,
    record_index: object,
    absolute_data_offset: Optional[int],
    relative_offset: int,
    byte_size: int,
    value_type: str,
    confidence: str,
    description: str,
    subject: str = "",
    item_index: Optional[int] = None,
    row_index: Optional[int] = None,
    component: str = "",
    effect: str = "",
    value_constraints: str = "",
    edit_rule: str = "fixed_size_value_only",
    decoded_value: object = None,
    owner_class: str = "",
    member: str = "",
    linked_target: str = "",
    linked_by: str = "",
    local_offset: Optional[int] = None,
) -> None:
    if not isinstance(record_index, int) or absolute_data_offset is None:
        return
    absolute_patch_offset = absolute_data_offset + relative_offset
    original_bytes = b""
    if 0 <= absolute_patch_offset <= len(data):
        original_bytes = data[absolute_patch_offset:absolute_patch_offset + byte_size]
    if decoded_value is None:
        decoded_value = _hkx_decode_patch_map_original_value(original_bytes, value_type)
    local_offset_value = relative_offset if local_offset is None else int(local_offset)
    risk_label = _hkx_patch_map_risk_label(confidence, category, name)
    structural_kind = _hkx_patch_map_structural_kind(value_type, category, name)
    link_evidence = linked_by or _hkx_patch_map_link_evidence(category, name, confidence)
    task_key = _hkx_patch_map_task_key(category, name, owner_class or subject or category, member or name, description)
    task_label = _hkx_patch_map_task_label(task_key)
    entry: Dict[str, object] = {
        "index": len(entries),
        "path": path,
        "category": category,
        "category_label": task_label,
        "task_category": task_key,
        "task_label": task_label,
        "owner_class": owner_class or subject or category,
        "member": member or name,
        "field": member or name,
        "name": name,
        "subject": subject,
        "record_index": record_index,
        "local_offset": local_offset_value,
        "relative_offset": relative_offset,
        "hex_relative_offset": f"0x{relative_offset:X}",
        "absolute_offset": absolute_patch_offset,
        "absolute_offset_hex": f"0x{absolute_patch_offset:X}",
        "absolute_data_offset": absolute_patch_offset,
        "hex_absolute_data_offset": f"0x{absolute_patch_offset:X}",
        "byte_size": byte_size,
        "value_type": value_type,
        "write_type": "f32" if value_type == "float32" else value_type,
        "supported_write_type": "f32" if value_type == "float32" else value_type,
        "value_kind": "fixed_size_numeric" if "float" in value_type else "fixed_size_value",
        "structural_kind": structural_kind,
        "import_safety": "import_safe" if structural_kind != "structural_blocked" else "read_only",
        "risk_label": risk_label,
        "risk": risk_label,
        "original_bytes_hex": original_bytes.hex(" ").upper(),
        "decoded_value": decoded_value,
        "edit_rule": edit_rule,
        "confidence": confidence,
        "evidence": "current CDMW byte patch map",
        "link_evidence": link_evidence,
        "linked_by": link_evidence,
        "linked_target": linked_target or subject,
        "import_behavior": "CDMW fixed-size patch into original HKX bytes",
        "gate_status": "enabled" if structural_kind != "structural_blocked" else "blocked",
        "gate_reason": "exact record offset and value size recovered" if structural_kind != "structural_blocked" else "structural edits require semantic rebuild proof",
        "fixed_edit_test_status": "existing_route",
        "effect": effect,
        "value_constraints": value_constraints,
        "description": description,
    }
    if item_index is not None:
        entry["item_index"] = item_index
    if row_index is not None:
        entry["row_index"] = row_index
    if component:
        entry["component"] = component
    entries.append(entry)






_HKX_MODDING_WORKSPACE_TASKS: Tuple[Dict[str, object], ...] = (
    {
        "key": "collision_size",
        "label": "Collision Size",
        "terms": ("collision", "shape", "radius", "capsule", "sphere", "convex", "box", "extent", "vertex", "plane"),
    },
    {
        "key": "body_transform",
        "label": "Body Transform",
        "terms": ("body", "transform", "orientation", "position", "quaternion", "extendedbodycinfo", "mass"),
    },
    {
        "key": "joint_strength",
        "label": "Joint Strength",
        "terms": ("constraint", "motor", "stiffness", "strength", "force", "torque", "limit", "hinge", "ragdoll"),
    },
    {
        "key": "damping_motion",
        "label": "Damping / Motion",
        "terms": ("damping", "drag", "motion", "velocity", "angular", "linear", "solver", "sharedmotion"),
    },
    {
        "key": "material_friction",
        "label": "Material / Friction",
        "terms": ("material", "friction", "restitution", "surface", "filter"),
    },
    {
        "key": "mesh_winding",
        "label": "Mesh Winding",
        "terms": ("mesh", "primitive", "winding", "triangle", "quad", "aabb", "tag", "topology", "face", "edge"),
    },
    {
        "key": "inspect_only",
        "label": "Inspect Only",
        "terms": (),
    },
)


def _hkx_workspace_task_key_for_text(*parts: object) -> str:
    text = " ".join(str(part or "") for part in parts).casefold()
    for task in _HKX_MODDING_WORKSPACE_TASKS:
        key = str(task.get("key") or "")
        if key == "inspect_only":
            continue
        terms = task.get("terms")
        if isinstance(terms, tuple) and any(str(term).casefold() in text for term in terms):
            return key
    return "inspect_only"


def _hkx_workspace_task_label(key: object) -> str:
    key_text = str(key or "")
    for task in _HKX_MODDING_WORKSPACE_TASKS:
        if task.get("key") == key_text:
            return str(task.get("label") or key_text)
    return "Inspect Only"


def _hkx_workspace_label_for_safety(value: object, *, write_enabled: bool = False, structural_kind: object = "") -> str:
    safety = str(value or "").strip().casefold()
    structural = str(structural_kind or "").strip().casefold()
    if structural in {"structural_blocked", "topology", "count", "reference", "string", "array"}:
        return "Structural blocked"
    if write_enabled or safety in {"import_safe", "import-safe", "enabled"}:
        return "Import-safe"
    if safety in {"blocked", "structural_blocked"}:
        return "Structural blocked"
    return "Read-only candidate"


def _hkx_workspace_label_for_value_kind(value: object) -> str:
    key = str(value or "").strip().casefold()
    if "fixed_size_numeric" in key or key in {"float32", "f32"}:
        return "Fixed numeric"
    if key in {"structural_blocked", "topology", "count", "reference", "string", "array"}:
        return "Structural blocked"
    return "Fixed numeric" if "fixed" in key else "Context only"


def _hkx_workspace_label_for_link(value: object) -> str:
    key = str(value or "").strip().casefold().replace("-", "_")
    if key in {"fixup_backed", "ptch", "ptch_object", "exact", "exact_link"}:
        return "Fixup-backed"
    if key in {"owner_array", "declared_owner_array"}:
        return "Owner-array"
    if key in {"inferred", "typed_layout", "fixup_backed_or_inferred"}:
        return "Inferred"
    if key in {"spatial_fallback", "nearest"}:
        return "Spatial fallback only"
    return "Context only"








def _hkx_editor_group_title(group_key: str) -> str:
    return {
        "bodies": "Bodies",
        "collision_shapes": "Collision Shapes",
        "constraints": "Constraints",
        "motors": "Motors",
        "motion_damping": "Motion / Damping",
        "object_records": "Object Records",
        "raw_preserved_data": "Raw Preserved Data",
    }.get(group_key, group_key.replace("_", " ").title())


def _hkx_editor_selection_id(*parts: object) -> str:
    normalized = [
        re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(part)).strip("_")
        for part in parts
        if part is not None and str(part) != ""
    ]
    return "/".join(normalized)


def _hkx_editor_add_row(
    rows_by_group: Dict[str, List[Dict[str, object]]],
    group: str,
    *,
    label: str,
    value: object = "",
    value_type: str = "",
    importable: bool = False,
    patch_path: str = "",
    editor_tab: str = "",
    record_index: object = None,
    item_index: object = None,
    offset: object = None,
    byte_offset: object = None,
    subject: str = "",
    field: str = "",
    confidence: str = "experimental",
    edit_risk: str = "",
    effect: str = "",
    explanation: str = "",
    if_increased: str = "",
    if_decreased: str = "",
    safe_edit_hint: str = "",
    value_constraints: str = "",
    source: str = "",
    viewer_selection_id: str = "",
    context_label: str = "",
    display_label: str = "",
    body_name: object = "",
    socket_name: object = "",
    fixed_socket_name: object = "",
    physics_material_name: object = "",
    shape_index: object = None,
    shape_type: object = "",
    context_source: object = "",
    context_confidence: object = "",
    identity_path: object = "",
) -> None:
    row: Dict[str, object] = {
        "id": _hkx_editor_selection_id(group, record_index, item_index, offset, field or label, len(rows_by_group[group])),
        "group": group,
        "label": label,
        "display_label": display_label or label,
        "subject": subject,
        "field": field or label,
        "value": value,
        "original_value": value,
        "value_type": value_type,
        "importable": bool(importable),
        "patch_path": patch_path,
        "editor_tab": editor_tab,
        "confidence": confidence,
        "edit_risk": edit_risk,
        "effect": effect,
        "explanation": explanation,
        "if_increased": if_increased,
        "if_decreased": if_decreased,
        "safe_edit_hint": safe_edit_hint,
        "value_constraints": value_constraints,
        "source": source,
        "viewer_selection_id": viewer_selection_id,
    }
    for key, row_value in (
        ("record_index", record_index),
        ("item_index", item_index),
        ("offset", offset),
        ("hex_offset", f"0x{int(offset):X}" if isinstance(offset, int) else None),
        ("absolute_byte_offset", byte_offset),
        ("hex_absolute_byte_offset", f"0x{int(byte_offset):X}" if isinstance(byte_offset, int) else None),
        ("context_label", context_label),
        ("body_name", body_name),
        ("socket_name", socket_name),
        ("fixed_socket_name", fixed_socket_name),
        ("physics_material_name", physics_material_name),
        ("shape_index", shape_index),
        ("shape_type", shape_type),
        ("context_source", context_source),
        ("context_confidence", context_confidence),
        ("identity_path", identity_path),
    ):
        if row_value not in (None, ""):
            row[key] = row_value
    rows_by_group[group].append(row)




def _hkx_graph_add_node(nodes: List[Dict[str, object]], seen: set[str], node_id: str, kind: str, label: str, **extra: object) -> None:
    if not node_id or node_id in seen:
        return
    seen.add(node_id)
    node = {"id": node_id, "kind": kind, "label": label}
    node.update({key: value for key, value in extra.items() if value is not None})
    nodes.append(node)


def _hkx_graph_add_edge(edges: List[Dict[str, object]], seen: set[Tuple[str, str, str]], source: str, target: str, relation: str, **extra: object) -> None:
    if not source or not target:
        return
    key = (source, target, relation)
    if key in seen:
        return
    seen.add(key)
    edge = {"source": source, "target": target, "relation": relation}
    edge.update({key: value for key, value in extra.items() if value is not None})
    edges.append(edge)




def _hkx_relationship_link_evidence(reference: Mapping[str, object], relation: str = "") -> str:
    source = str(reference.get("reference_source") or reference.get("reference_category") or reference.get("source") or "").casefold()
    category = str(reference.get("reference_category") or reference.get("category") or "").casefold()
    confidence = str(reference.get("confidence") or "").casefold()
    if source.startswith(("ptch", "fixup")) or category.startswith(("ptch", "fixup")) or bool(reference.get("fixup_backed")):
        return "fixup_backed"
    if category == "array_data_reference" or source in {"native_owner_array", "owner_array"}:
        return "declared_owner_array"
    if source == "typed_layout":
        return "typed_layout"
    if confidence == "confirmed" or str(relation or "").casefold() in {"has_editable_value", "writes_byte_offset", "decoded_from"}:
        return "exact"
    if category in {"object_reference", "data_reference", "type_reference", "string_reference"}:
        return "inferred"
    return "inferred"








def build_hkx_editable_geometry_json(
    data: bytes,
    virtual_path: str = "",
    companion_descriptor_hints: Optional[Sequence[Mapping[str, object]]] = None,
) -> str:
    return json.dumps(
        build_hkx_editable_geometry_document(data, virtual_path, companion_descriptor_hints),
        indent=2,
        sort_keys=True,
    )


_HKX_XML_INVALID_CHAR_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\uD800-\uDFFF\uFFFE\uFFFF]")


def _hkx_xml_clean_text(value: object) -> str:
    return _HKX_XML_INVALID_CHAR_RE.sub("", str(value))


def _hkx_xml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.17g}"
    return _hkx_xml_clean_text(value)




def _hkx_compact_float(value: object, *, digits: int = 6) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return _hkx_xml_scalar(value)
    if not math.isfinite(number):
        return _hkx_xml_scalar(value)
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    if text == "-0":
        return "0"
    return text or "0"


def _hkx_compact_vector(value: object, *, digits: int = 6) -> str:
    if not isinstance(value, (list, tuple)):
        return _hkx_xml_scalar(value)
    return ",".join(_hkx_compact_float(component, digits=digits) for component in value)


def _hkx_xml_add_text(parent: ET.Element, tag: str, text: object, **attrs: object) -> ET.Element:
    element = ET.SubElement(parent, tag, {key: _hkx_xml_scalar(value) for key, value in attrs.items() if value is not None})
    element.text = _hkx_xml_clean_text(text or "")
    return element








def _hkx_xml_add_vector(parent: ET.Element, tag: str, values: Sequence[object], labels: Sequence[str], **attrs: object) -> ET.Element:
    element_attrs = {key: _hkx_xml_scalar(value) for key, value in attrs.items() if value is not None}
    for label, value in zip(labels, values):
        element_attrs[label] = _hkx_xml_scalar(float(value))
    return ET.SubElement(parent, tag, element_attrs)


def _hkx_xml_add_int_list(parent: ET.Element, tag: str, values: object, **attrs: object) -> Optional[ET.Element]:
    if not isinstance(values, list):
        return None
    element = ET.SubElement(parent, tag, {key: _hkx_xml_scalar(value) for key, value in attrs.items() if value is not None})
    element.text = " ".join(str(int(value)) for value in values if isinstance(value, int))
    return element


def _hkx_xml_add_mesh_record_attrs(parent: ET.Element, tag: str, record_info: Mapping[str, object]) -> ET.Element:
    attrs = {
        "record_index": _hkx_xml_scalar(record_info.get("record_index")),
        "type_name": str(record_info.get("type_name") or ""),
        "role": str(record_info.get("role") or ""),
        "count": _hkx_xml_scalar(record_info.get("count")),
        "byte_length": _hkx_xml_scalar(record_info.get("byte_length")),
        "stride": _hkx_xml_scalar(record_info.get("stride")),
        "data_offset": _hkx_xml_scalar(record_info.get("data_offset")),
        "absolute_data_offset": _hkx_xml_scalar(record_info.get("absolute_data_offset")),
        "status": str(record_info.get("status") or "read_only_schema_recovery"),
        "confidence": str(record_info.get("confidence") or "experimental"),
    }
    return ET.SubElement(parent, tag, {key: value for key, value in attrs.items() if value not in {"", "None"}})




def _hkx_xml_add_value_layout(parent: ET.Element, field_name: str, layout: object) -> None:
    field_element = ET.SubElement(parent, "field", {"name": field_name})
    if not isinstance(layout, Mapping):
        field_element.text = _hkx_xml_clean_text(layout or "")
        return
    row_text = str(layout.get("row") or layout.get("value") or "").strip()
    if row_text:
        field_element.set("layout", _hkx_xml_clean_text(row_text))
    components = layout.get("components")
    if isinstance(components, Mapping):
        for component_name, description in components.items():
            _hkx_xml_add_text(field_element, "component", description, name=str(component_name))








































































def _summarize_hkx_type_families(class_names: Sequence[str]) -> List[str]:
    counts: Counter[str] = Counter()
    for name in class_names:
        for prefix, label in _HKX_FAMILY_LABELS:
            if name.startswith(prefix):
                counts[label] += 1
                break
    return [f"{label}: {count:,}" for label, count in counts.most_common()]
