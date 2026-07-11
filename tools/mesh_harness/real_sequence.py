from __future__ import annotations
from types import SimpleNamespace
from tools.mesh_harness.phase_support import PhaseResult
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from collections.abc import Sequence
from cdmw.core.archive_binary_preview import build_binary_sidecar_analysis_document
from cdmw.modding.mesh_parser import parse_mesh
from cdmw.modding.animation_parser import parse_paa_animation_clip
from cdmw.modding.skeleton_parser import parse_pab
from tools.mesh_harness.constants import _REAL_ARCHIVE_RIGGING_SAMPLES, _REAL_ARCHIVE_SEQUENCE_EXTENSIONS, _REAL_ARCHIVE_SEQUENCE_PTM_PAA, _REAL_ARCHIVE_SEQUENCE_PTM_PAB, _REAL_ARCHIVE_SEQUENCE_SAMPLE
from tools.mesh_harness.evidence import _mesh_editor_advanced_authoring_corpus_manifest
from tools.mesh_harness.papr import _real_archive_papr_read_status
from tools.mesh_harness.real_animation import _sample_real_archive_paa_playback, _sequence_frame_rate_metadata
from tools.mesh_harness.real_common import _archive_entry_indexes, _archive_key, _entry_by_archive_path, _read_archive_payload, _real_archive_all_pamt_entries, _real_archive_extension_counts_by_package
from tools.mesh_harness.sequence_analysis import _binary_timing_probe_counts, _clip_sequence_segments_json, _document_asset_reference_paths, _document_paseq_timing_evidence, _document_related_resolved_paths, _paseq_lane_for_path, _real_archive_sequence_timing_corpus_summary, _sequence_event_marker_overlap, _sequence_lane_pair_summary, _sequence_path_record_context, _sequence_reference_overlap, _sequence_timeline_field_overlap, _sequence_timeline_field_semantic_aliases, _source_sequence_path_for_compiled_sequence

def _real_sequence_papr_gate_1(state: SimpleNamespace) -> bool:
    return int(state.papr_status.get('read_ok_count') or 0) == 20 and int(state.papr_metadata_totals.get('constraint_record_candidates') or 0) == 545 and (sum((int(count or 0) for count in state.papr_expression_shape_totals.values())) == 545) and (int(state.papr_expression_shape_totals.get('linear_channel_transform_candidate') or 0) == 374) and (int(state.papr_expression_shape_totals.get('absolute_channel_transform_candidate') or 0) == 55) and (int(state.papr_expression_shape_totals.get('limit_linear_channel_transform_candidate') or 0) == 96) and (int(state.papr_expression_shape_totals.get('limit_absolute_channel_transform_candidate') or 0) == 15) and (int(state.papr_expression_shape_totals.get('channel_reference_expression_candidate') or 0) == 5)

def _real_sequence_papr_gate_2(state: SimpleNamespace) -> bool:
    return sum((int(count or 0) for count in state.papr_expression_syntax_signature_totals.values())) == 545 and len(state.papr_expression_syntax_signature_totals) == 28 and (int(state.papr_expression_syntax_signature_totals.get('role=driver_expression|shape=linear_channel_transform_candidate|channels=Local_Euler_Z|limits=none|numeric_roles=channel_coefficient>additive_offset') or 0) == 125) and (int(state.papr_expression_syntax_signature_totals.get('role=driver_expression|shape=linear_channel_transform_candidate|channels=Local_Euler_Y|limits=none|numeric_roles=channel_coefficient>additive_offset') or 0) == 109) and (int(state.papr_expression_syntax_signature_totals.get('role=limit_expression|shape=limit_linear_channel_transform_candidate|channels=Local_Euler_Z|limits=amin|numeric_roles=channel_coefficient>additive_offset>limit_argument') or 0) == 38) and (sum((int(count or 0) for count in state.papr_numeric_role_totals.values())) == 1177) and (int(state.papr_numeric_role_totals.get('channel_coefficient') or 0) == 460) and (int(state.papr_numeric_role_totals.get('additive_offset') or 0) == 455)

def _real_sequence_papr_gate_3(state: SimpleNamespace) -> bool:
    return int(state.papr_numeric_role_totals.get('limit_argument') or 0) == 111 and int(state.papr_numeric_role_totals.get('channel_divisor') or 0) == 75 and (int(state.papr_numeric_role_totals.get('numeric_constant') or 0) == 76) and (int(state.papr_family_totals.get('driver_expression_candidate') or 0) == 434) and (int(state.papr_family_totals.get('local_transform_limit_candidate') or 0) == 111) and (int(state.papr_driver_channel_totals.get('Local_Euler_X') or 0) == 9) and (int(state.papr_driver_channel_totals.get('Local_Euler_Y') or 0) == 169) and (int(state.papr_driver_channel_totals.get('Local_Euler_Z') or 0) == 256)

def _real_sequence_papr_gate_4(state: SimpleNamespace) -> bool:
    return int(state.papr_limit_channel_totals.get('Local_Euler_X') or 0) == 15 and int(state.papr_limit_channel_totals.get('Local_Euler_Y') or 0) == 18 and (int(state.papr_limit_channel_totals.get('Local_Euler_Z') or 0) == 78) and (not state.papr_driver_limit_totals) and (int(state.papr_limit_limit_totals.get('amin') or 0) == 91) and (int(state.papr_limit_limit_totals.get('amax') or 0) == 20) and (int(state.papr_solver_totals.get('blocked_record_layout_unproven') or 0) == 545) and (int(state.papr_layout_status_totals.get('nearby_string_span_only_value_layout_unproven') or 0) == 545)

def _real_sequence_papr_gate_5(state: SimpleNamespace) -> bool:
    return sum((int(count or 0) for count in state.papr_field_sequence_totals.values())) == 545 and int(state.papr_field_sequence_totals.get('parent>helper>target>expression') or 0) > 0 and (sum((int(count or 0) for count in state.papr_gap_status_totals.values())) == 545) and (int(state.papr_gap_status_totals.get('binary_like_interfield_gap_bytes_unbound') or 0) == 544) and (int(state.papr_gap_status_totals.get('printable_interfield_gap_bytes_unbound') or 0) == 1) and (sum((int(count or 0) for count in state.papr_gap_class_totals.values())) == 946) and (int(state.papr_gap_class_totals.get('binary_gap') or 0) == 757) and (int(state.papr_gap_class_totals.get('overlap_or_shared_string') or 0) == 179)

def _real_sequence_papr_gate_6(state: SimpleNamespace) -> bool:
    return int(state.papr_gap_class_totals.get('printable_ascii_gap') or 0) == 5 and int(state.papr_gap_class_totals.get('zero_padding') or 0) == 5 and (int(state.papr_status.get('constraint_record_gap_pair_total') or 0) == 946) and (int(state.papr_status.get('constraint_record_gap_max_size') or 0) == 741) and (sum((int(count or 0) for count in state.papr_gap_scalar_status_totals.values())) == 545) and (int(state.papr_gap_scalar_status_totals.get('unbound_interfield_scalar_candidates') or 0) == 498) and (int(state.papr_gap_scalar_status_totals.get('no_interfield_scalar_candidates') or 0) == 47) and (sum((int(count or 0) for count in state.papr_gap_scalar_kind_totals.values())) == 3472)

def _real_sequence_papr_gate_7(state: SimpleNamespace) -> bool:
    return int(state.papr_gap_scalar_kind_totals.get('f32_unit_candidate') or 0) == 1433 and int(state.papr_gap_scalar_kind_totals.get('f32_angle_candidate') or 0) == 1201 and (int(state.papr_gap_scalar_kind_totals.get('u32_u16_candidate') or 0) == 532) and (int(state.papr_gap_scalar_kind_totals.get('zero_word') or 0) == 187) and (int(state.papr_gap_scalar_kind_totals.get('f32_small_candidate') or 0) == 75) and (int(state.papr_gap_scalar_kind_totals.get('u32_u8_candidate') or 0) == 42) and (int(state.papr_gap_scalar_kind_totals.get('u32_bool_candidate') or 0) == 2) and (int(state.papr_status.get('constraint_record_gap_aligned_word_total') or 0) == 26169)

def _real_sequence_papr_gate_8(state: SimpleNamespace) -> bool:
    return int(state.papr_status.get('constraint_record_gap_scalar_candidate_total') or 0) == 3472 and int(state.papr_status.get('constraint_record_gap_scalar_candidate_max') or 0) == 35 and (sum((int(count or 0) for count in state.papr_gap_numeric_match_status_totals.values())) == 545) and (int(state.papr_gap_numeric_match_status_totals.get('unbound_scalar_numeric_constant_matches') or 0) == 26) and (int(state.papr_gap_numeric_match_status_totals.get('no_scalar_numeric_constant_matches') or 0) == 519) and (sum((int(count or 0) for count in state.papr_gap_numeric_match_role_totals.values())) == 60) and (int(state.papr_gap_numeric_match_role_totals.get('limit_argument') or 0) == 31) and (int(state.papr_gap_numeric_match_role_totals.get('channel_coefficient') or 0) == 18)

def _real_sequence_papr_gate_9(state: SimpleNamespace) -> bool:
    return int(state.papr_gap_numeric_match_role_totals.get('additive_offset') or 0) == 11 and sum((int(count or 0) for count in state.papr_gap_numeric_match_scalar_kind_totals.values())) == 60 and (int(state.papr_gap_numeric_match_scalar_kind_totals.get('f32_unit_candidate') or 0) == 27) and (int(state.papr_gap_numeric_match_scalar_kind_totals.get('u32_u16_candidate') or 0) == 26) and (int(state.papr_gap_numeric_match_scalar_kind_totals.get('zero_word') or 0) == 5) and (int(state.papr_gap_numeric_match_scalar_kind_totals.get('f32_small_candidate') or 0) == 2) and (sum((int(count or 0) for count in state.papr_gap_numeric_match_storage_totals.values())) == 60) and (int(state.papr_gap_numeric_match_storage_totals.get('f32') or 0) == 55)

def _real_sequence_papr_gate_10(state: SimpleNamespace) -> bool:
    return int(state.papr_gap_numeric_match_storage_totals.get('u32') or 0) == 5 and int(state.papr_status.get('constraint_record_gap_numeric_match_total') or 0) == 60 and (int(state.papr_status.get('constraint_record_gap_numeric_match_max') or 0) == 5) and (sum((int(count or 0) for count in state.papr_gap_numeric_match_pair_totals.values())) == 60) and (int(state.papr_gap_numeric_match_pair_totals.get('parent>target') or 0) == 29) and (int(state.papr_gap_numeric_match_pair_totals.get('parent>expression') or 0) == 18) and (int(state.papr_gap_numeric_match_pair_totals.get('parent>helper') or 0) == 12) and (int(state.papr_gap_numeric_match_pair_totals.get('target>expression') or 0) == 1)

def _real_sequence_papr_gate_11(state: SimpleNamespace) -> bool:
    return sum((int(count or 0) for count in state.papr_gap_numeric_match_value_confidence_totals.values())) == 60 and int(state.papr_gap_numeric_match_value_confidence_totals.get('approx_float32_numeric_value_match_layout_unproven') or 0) == 35 and (int(state.papr_gap_numeric_match_value_confidence_totals.get('exact_float32_numeric_value_match_layout_unproven') or 0) == 20) and (int(state.papr_gap_numeric_match_value_confidence_totals.get('exact_u32_numeric_value_match_layout_unproven') or 0) == 5) and (sum((int(count or 0) for count in state.papr_gap_numeric_match_family_totals.values())) == 60) and (sum((int(count or 0) for count in state.papr_gap_numeric_match_family_row_totals.values())) == 26) and (int(state.papr_gap_numeric_match_family_totals.get('driver_expression_candidate') or 0) == 18) and (int(state.papr_gap_numeric_match_family_totals.get('local_transform_limit_candidate') or 0) == 42)

def _real_sequence_papr_gate_12(state: SimpleNamespace) -> bool:
    return int(state.papr_gap_numeric_match_family_row_totals.get('driver_expression_candidate') or 0) == 11 and int(state.papr_gap_numeric_match_family_row_totals.get('local_transform_limit_candidate') or 0) == 15 and (sum((int(count or 0) for count in state.papr_driver_role_totals.values())) == 18) and (int(state.papr_driver_role_totals.get('channel_coefficient') or 0) == 18) and (sum((int(count or 0) for count in state.papr_limit_role_totals.values())) == 42) and (int(state.papr_limit_role_totals.get('additive_offset') or 0) == 11) and (int(state.papr_limit_role_totals.get('limit_argument') or 0) == 31) and (sum((int(count or 0) for count in state.papr_driver_pair_totals.values())) == 18)

def _real_sequence_papr_gate_13(state: SimpleNamespace) -> bool:
    return int(state.papr_driver_pair_totals.get('parent>expression') or 0) == 3 and int(state.papr_driver_pair_totals.get('parent>helper') or 0) == 12 and (int(state.papr_driver_pair_totals.get('parent>target') or 0) == 3) and (sum((int(count or 0) for count in state.papr_limit_pair_totals.values())) == 42) and (int(state.papr_limit_pair_totals.get('parent>expression') or 0) == 15) and (int(state.papr_limit_pair_totals.get('parent>target') or 0) == 26) and (int(state.papr_limit_pair_totals.get('target>expression') or 0) == 1) and (sum((int(count or 0) for count in state.papr_driver_value_confidence_totals.values())) == 18)

def _real_sequence_papr_gate_14(state: SimpleNamespace) -> bool:
    return int(state.papr_driver_value_confidence_totals.get('approx_float32_numeric_value_match_layout_unproven') or 0) == 2 and int(state.papr_driver_value_confidence_totals.get('exact_float32_numeric_value_match_layout_unproven') or 0) == 16 and (sum((int(count or 0) for count in state.papr_limit_value_confidence_totals.values())) == 42) and (int(state.papr_limit_value_confidence_totals.get('approx_float32_numeric_value_match_layout_unproven') or 0) == 33) and (int(state.papr_limit_value_confidence_totals.get('exact_float32_numeric_value_match_layout_unproven') or 0) == 4) and (int(state.papr_limit_value_confidence_totals.get('exact_u32_numeric_value_match_layout_unproven') or 0) == 5) and (sum((int(count or 0) for count in state.papr_gap_numeric_match_signature_totals.values())) == 60) and (len(state.papr_gap_numeric_match_signature_totals) == 46)

def _real_sequence_papr_gate_15(state: SimpleNamespace) -> bool:
    return int(state.papr_gap_numeric_match_signature_totals.get(state.papr_top_limit_signature) or 0) == 4 and int(state.papr_gap_numeric_match_signature_totals.get(state.papr_top_driver_signature) or 0) == 2 and (sum((int(count or 0) for count in state.papr_gap_numeric_match_candidate_relative_signature_totals.values())) == 60) and (len(state.papr_gap_numeric_match_candidate_relative_signature_totals) == 55) and (int(state.papr_gap_numeric_match_candidate_relative_signature_totals.get(state.papr_top_limit_relative_signature) or 0) == 2) and (int(state.papr_gap_numeric_match_candidate_relative_signature_totals.get(state.papr_second_limit_relative_signature) or 0) == 2) and (sum((int(count or 0) for count in state.papr_gap_numeric_match_previous_delta_totals.values())) == 60) and (sum((int(count or 0) for count in state.papr_gap_numeric_match_next_delta_totals.values())) == 60)

def _real_sequence_papr_gate_16(state: SimpleNamespace) -> bool:
    return len(state.papr_gap_numeric_match_previous_delta_totals) == 30 and len(state.papr_gap_numeric_match_next_delta_totals) == 34 and (int(state.papr_gap_numeric_match_previous_delta_totals.get('9') or 0) == 4) and (int(state.papr_gap_numeric_match_previous_delta_totals.get('20') or 0) == 4) and (int(state.papr_gap_numeric_match_previous_delta_totals.get('387') or 0) == 2) and (int(state.papr_gap_numeric_match_next_delta_totals.get('23') or 0) == 4) and (int(state.papr_gap_numeric_match_next_delta_totals.get('111') or 0) == 4) and (int(state.papr_gap_numeric_match_next_delta_totals.get('611') or 0) == 1)

def _real_sequence_papr_gate_17(state: SimpleNamespace) -> bool:
    return sum((int(count or 0) for count in state.papr_gap_numeric_match_candidate_relative_offset_totals.values())) == 60 and len(state.papr_gap_numeric_match_candidate_relative_offset_totals) == 41 and (int(state.papr_gap_numeric_match_candidate_relative_offset_totals.get('-105') or 0) == 5) and (int(state.papr_gap_numeric_match_candidate_relative_offset_totals.get('-109') or 0) == 4) and (int(state.papr_gap_numeric_match_candidate_relative_offset_totals.get('-81') or 0) == 3) and (int(state.papr_gap_numeric_match_candidate_relative_offset_totals.get('-6') or 0) == 2) and (int(state.papr_status.get('constraint_record_gap_numeric_match_min_previous_delta') or 0) == 1) and (int(state.papr_status.get('constraint_record_gap_numeric_match_max_previous_delta') or 0) == 387)

def _real_sequence_papr_gate_18(state: SimpleNamespace) -> bool:
    return int(state.papr_status.get('constraint_record_gap_numeric_match_min_next_delta') or 0) == 2 and int(state.papr_status.get('constraint_record_gap_numeric_match_max_next_delta') or 0) == 611 and (int(state.papr_status.get('constraint_record_gap_numeric_match_min_candidate_relative_offset') or 0) == -624) and (int(state.papr_status.get('constraint_record_gap_numeric_match_max_candidate_relative_offset') or 0) == -6) and (state.papr_status.get('constraint_record_gap_numeric_match_offset_confidence') == 'observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven') and (state.papr_status.get('constraint_record_gap_numeric_match_candidate_relative_offset_confidence') == 'observed_relative_to_inferred_candidate_offset_value_layout_unproven') and (len(state.papr_gap_numeric_match_rows) == 24) and (state.papr_gap_numeric_match_row_confidences['approx_float32_numeric_value_match_layout_unproven'] == 16)

def _real_sequence_papr_gate_19(state: SimpleNamespace) -> bool:
    return state.papr_gap_numeric_match_row_confidences['exact_float32_numeric_value_match_layout_unproven'] == 7 and state.papr_gap_numeric_match_row_confidences['exact_u32_numeric_value_match_layout_unproven'] == 1 and isinstance(state.papr_gap_numeric_match_rows[0], Mapping) and (state.papr_gap_numeric_match_rows[0].get('path') == 'character/model/1_pc/14_ptm/ptm_01.papr') and (state.papr_gap_numeric_match_rows[0].get('constraint_type') == 'local_transform_limit_candidate') and (state.papr_gap_numeric_match_rows[0].get('numeric_role') == 'limit_argument') and (state.papr_gap_numeric_match_rows[0].get('candidate_relative_offset') == -81) and (state.papr_gap_numeric_match_rows[0].get('candidate_relative_match_signature') == 'family=local_transform_limit_candidate|role=limit_argument|pair=parent>target|storage=f32|scalar=u32_u16_candidate|value=approx_float32_numeric_value_match_layout_unproven|prev=50|next=27|rel=-81')

def _real_sequence_papr_gate_20(state: SimpleNamespace) -> bool:
    return state.papr_gap_numeric_match_rows[0].get('value_confidence') == 'approx_float32_numeric_value_match_layout_unproven'

def _real_sequence_phase_1(state: SimpleNamespace) -> PhaseResult | None:
    assert state.sequence_entry is not None
    assert state.skeleton_entry is not None
    assert state.model_entry is not None
    state.sequence_data = _read_archive_payload(state.sequence_entry)
    state.source_sequence_path = _source_sequence_path_for_compiled_sequence(state.sequence_entry.path)
    state.source_sequence_entry = _entry_by_archive_path(state.entries_by_path, state.source_sequence_path)
    state.source_sequence_data = _read_archive_payload(state.source_sequence_entry) if state.source_sequence_entry is not None else b''
    state.source_sequence_timing_probe = _binary_timing_probe_counts(state.source_sequence_data) if state.source_sequence_data else {}
    state.source_sequence_document = build_binary_sidecar_analysis_document(state.source_sequence_data, state.source_sequence_entry.path, extension=state.source_sequence_entry.extension, source_entry=state.source_sequence_entry, archive_entries_by_normalized_path=state.entries_by_path, archive_entries_by_basename=state.entries_by_basename) if state.source_sequence_entry is not None else {}
    state.source_sequence_timing_evidence = _document_paseq_timing_evidence(state.source_sequence_document)
    state.source_sequence_refs = _document_asset_reference_paths(state.source_sequence_document)
    state.source_paseq = state.source_sequence_document.get('paseq', {}) if isinstance(state.source_sequence_document, Mapping) else {}
    state.source_timeline = state.source_paseq.get('timeline', {}) if isinstance(state.source_paseq, Mapping) else {}
    state.sequence_document = build_binary_sidecar_analysis_document(state.sequence_data, state.sequence_entry.path, extension=state.sequence_entry.extension, source_entry=state.sequence_entry, archive_entries_by_normalized_path=state.entries_by_path, archive_entries_by_basename=state.entries_by_basename)
    state.sequence_refs = _document_asset_reference_paths(state.sequence_document)
    state.resolved_refs = _document_related_resolved_paths(state.sequence_document)
    state.paseq = state.sequence_document.get('paseq', {}) if isinstance(state.sequence_document, dict) else {}
    state.timeline = state.paseq.get('timeline', {}) if isinstance(state.paseq, dict) else {}
    state.playback = state.paseq.get('playback_readiness', {}) if isinstance(state.paseq, dict) else {}
    state.linked_paa_path = _REAL_ARCHIVE_SEQUENCE_PTM_PAA if _archive_key(_REAL_ARCHIVE_SEQUENCE_PTM_PAA) in {_archive_key(path) for path in state.sequence_refs} else next((path for path in state.sequence_refs if path.lower().endswith('.paa') and '/14_ptm/' in path.lower()), '')
    state.linked_paa_entry = _entry_by_archive_path(state.entries_by_path, state.linked_paa_path) if state.linked_paa_path else None
    if state.linked_paa_entry is None:
        state.linked_paa_entry = _entry_by_archive_path(state.entries_by_path, _REAL_ARCHIVE_SEQUENCE_PTM_PAA)
        state.linked_paa_path = state.linked_paa_entry.path if state.linked_paa_entry is not None else state.linked_paa_path
    state.reference_overlap = _sequence_reference_overlap(state.source_sequence_refs, state.sequence_refs, active_path=state.linked_paa_path)
    state.lane_pair_summary = _sequence_lane_pair_summary(state.source_timeline, state.timeline, active_path=state.linked_paa_path)
    state.event_marker_overlap = _sequence_event_marker_overlap(state.source_timeline, state.timeline)
    state.timeline_field_overlap = _sequence_timeline_field_overlap(state.source_timeline, state.timeline)
    state.timeline_field_aliases = _sequence_timeline_field_semantic_aliases(state.source_timeline, state.timeline)
    state.source_active_lane_record_context = _sequence_path_record_context(state.source_sequence_data, state.linked_paa_path)
    state.compiled_active_lane_record_context = _sequence_path_record_context(state.sequence_data, state.linked_paa_path)
    state.sequence_lane = _paseq_lane_for_path(state.timeline, state.linked_paa_path)
    state.skeleton = parse_pab(_read_archive_payload(state.skeleton_entry), state.skeleton_entry.path)
    state.mesh = parse_mesh(_read_archive_payload(state.model_entry), state.model_entry.path)
    state.clip = None
    state.binding = None
    if state.linked_paa_entry is not None:
        state.paa_data = _read_archive_payload(state.linked_paa_entry)
        state.frame_rate_source, state.frame_rate_confidence = _sequence_frame_rate_metadata(state.source_sequence_timing_probe)
        state.clip, state.binding = parse_paa_animation_clip(state.paa_data, state.linked_paa_entry.path, skeleton=state.skeleton, frame_rate_source=state.frame_rate_source, frame_rate_confidence=state.frame_rate_confidence, sequence_path=state.sequence_entry.path, sequence_lane_index=state.sequence_lane.get('index', -1), sequence_lane_source_offset=state.sequence_lane.get('source_offset', 0), sequence_lane_confidence=state.sequence_lane.get('confidence', ''))
        state.paa_timing = _binary_timing_probe_counts(state.paa_data)
    else:
        state.frame_rate_source, state.frame_rate_confidence = _sequence_frame_rate_metadata(state.source_sequence_timing_probe)
        state.paa_timing = {}
    state.ready_binding = bool(state.binding is not None and state.binding.ready and (state.clip is not None))
    state.playback_sample = _sample_real_archive_paa_playback(state.mesh, state.skeleton, state.clip) if state.clip is not None else {'ready': False, 'sampled_bone_count': 0, 'pose_changed': False}
    state.playback_sample_ok = bool(state.playback_sample.get('ready') and state.playback_sample.get('pose_changed') and state.playback_sample.get('export_geometry_unchanged') and state.playback_sample.get('deterministic_repeat_seek') and (int(state.playback_sample.get('sampled_bone_count') or 0) == 46) and (int(state.playback_sample.get('repeat_sampled_bone_count') or 0) == 46) and (int(state.playback_sample.get('active_sequence_lane_index') or -1) == 1))
    state.source_timing_evidence = state.source_sequence_timing_evidence if isinstance(state.source_sequence_timing_evidence, Mapping) else {}
    state.fps_candidate_rows = state.source_timing_evidence.get('fps_candidate_value_rows')
    state.fps_candidate_rows = state.fps_candidate_rows if isinstance(state.fps_candidate_rows, Sequence) else ()
    state.fps_candidate_signature = tuple(((int(row.get('offset') or 0), str(row.get('kind') or ''), int(row.get('value') or 0), str(row.get('status') or ''), str(row.get('value_confidence') or '')) for row in state.fps_candidate_rows if isinstance(row, Mapping)))
    state.blend_candidate_rows = state.source_timing_evidence.get('blend_candidate_value_rows')
    state.blend_candidate_rows = state.blend_candidate_rows if isinstance(state.blend_candidate_rows, Sequence) else ()
    state.blend_candidate_signature = tuple(((int(row.get('offset') or 0), round(float(row.get('value') or 0.0), 6), str(row.get('status') or ''), str(row.get('value_confidence') or '')) for row in tuple(state.blend_candidate_rows)[:4] if isinstance(row, Mapping)))
    state.paseq_timing_ok = bool(int(state.source_timing_evidence.get('fps_field_declaration_count') or 0) == 2 and str(state.source_timing_evidence.get('fps_binding_status') or '') == 'source_paseq_fps_field_declared_value_offset_unmapped' and (int(state.source_timing_evidence.get('fps_candidate_value_region_start') or 0) == 20985) and (state.fps_candidate_signature == ((21976, 'u32_fps_candidate', 30, 'not_bound_length_prefixed_string_context', 'blocked'), (22116, 'u32_fps_candidate', 30, 'not_bound_length_prefixed_string_context', 'blocked'), (24836, 'u32_fps_candidate', 24, 'unbound_binary_scalar_candidate', 'unknown'), (30692, 'u32_fps_candidate', 15, 'unbound_binary_scalar_candidate', 'unknown'))))
    state.paseq_blend_value_ok = bool(int(state.source_timing_evidence.get('blend_field_declaration_count') or 0) == 8 and str(state.source_timing_evidence.get('blend_binding_status') or '') == 'blend_fields_declared_value_offsets_unmapped' and (str(state.source_timing_evidence.get('blend_candidate_value_scan') or '') == 'aligned_4_byte_little_endian_nonzero_float32') and (int(state.source_timing_evidence.get('blend_candidate_value_region_start') or 0) == 20985) and (int(state.source_timing_evidence.get('blend_candidate_value_count') or 0) == 32) and (state.blend_candidate_signature == ((21336, 0.001953, 'unbound_binary_scalar_candidate', 'unknown'), (22304, 0.078125, 'unbound_binary_scalar_candidate', 'unknown'), (22560, 2.0, 'unbound_binary_scalar_candidate', 'unknown'), (22564, 0.001953, 'unbound_binary_scalar_candidate', 'unknown'))))
    state.sequence_reference_ok = bool(state.reference_overlap.get('status') == 'source_compiled_clip_reference_overlap' and int(state.reference_overlap.get('source_reference_count') or 0) == 3 and (int(state.reference_overlap.get('compiled_reference_count') or 0) == 2) and (int(state.reference_overlap.get('overlap_reference_count') or 0) == 2) and (int(state.reference_overlap.get('source_only_reference_count') or 0) == 1) and (int(state.reference_overlap.get('compiled_only_reference_count') or 0) == 0) and bool(state.reference_overlap.get('active_clip_in_overlap')) and (tuple(state.reference_overlap.get('overlap_paths') or ()) == ('character/motion/1_pc/1_phm/01_npc/cd_phm_backpack_00_00_nor_std_idle_02.paa', 'character/motion/1_pc/14_ptm/01_npc/cd_ptm_backpack_00_00_nor_std_idle_ing_03.paa')) and (tuple(state.reference_overlap.get('source_only_paths') or ()) == ('character/motion/1_pc/1_phm/cd_phm_basic_00_00_normal_stand_idle_004.paa',)))
    return None

def _real_sequence_phase_2(state: SimpleNamespace) -> PhaseResult | None:
    state.lane_pair_signature = tuple(((str(row.get('path') or ''), int(row.get('source_lane_index') or 0), int(row.get('compiled_lane_index') or 0), int(row.get('source_offset') or 0), int(row.get('compiled_offset') or 0), bool(row.get('active_clip'))) for row in state.lane_pair_summary.get('lane_pairs') or () if isinstance(row, Mapping)))
    state.sequence_lane_pair_ok = bool(state.lane_pair_summary.get('status') == 'source_compiled_lane_pair_overlap' and int(state.lane_pair_summary.get('source_lane_count') or 0) == 3 and (int(state.lane_pair_summary.get('compiled_lane_count') or 0) == 2) and (int(state.lane_pair_summary.get('lane_pair_count') or 0) == 2) and (int(state.lane_pair_summary.get('active_lane_pair_count') or 0) == 1) and (state.lane_pair_signature == (('character/motion/1_pc/1_phm/01_npc/cd_phm_backpack_00_00_nor_std_idle_02.paa', 0, 0, 21702, 11018, False), ('character/motion/1_pc/14_ptm/01_npc/cd_ptm_backpack_00_00_nor_std_idle_ing_03.paa', 2, 1, 22031, 11402, True))))
    state.event_marker_signature = tuple(((str(row.get('text') or ''), int(row.get('source_offset') or 0), int(row.get('compiled_offset') or 0)) for row in state.event_marker_overlap.get('overlap_markers') or () if isinstance(row, Mapping)))
    state.sequence_event_marker_ok = bool(state.event_marker_overlap.get('status') == 'source_compiled_event_marker_overlap' and int(state.event_marker_overlap.get('source_marker_count') or 0) == 64 and (int(state.event_marker_overlap.get('compiled_marker_count') or 0) == 39) and (int(state.event_marker_overlap.get('overlap_marker_count') or 0) == 14) and (int(state.event_marker_overlap.get('source_only_marker_count') or 0) == 50) and (int(state.event_marker_overlap.get('compiled_only_marker_count') or 0) == 25) and (state.event_marker_signature == (('_startTimePiece', 237, 900), ('_endTimePiece', 273, 936), ('_startOffsetTimePiece', 953, 5998), ('_endOffsetTimePiece', 995, 6040), ('_hasSequencerCamera', 1035, 6080), ('_hasSequencerCamera_Jump', 1074, 6119), ('_hasTransformBlend', 1118, 6163), ('GameData_TimelineEvent_BodyAnimation', 4742, 5072), ('SequencerGamePlayDataEventKey', 4792, 815), ('_startOffset', 4990, 5320), ('_isLoop', 5125, 2045), ('_gimmickTriggerCheckTargetDataList', 11257, 4210), ('_connectTrigger', 11635, 3768), ('_triggerTagList', 19760, 6349))))
    state.timeline_field_signature = tuple(((str(row.get('name') or ''), str(row.get('role') or ''), int(row.get('source_offset') or 0), int(row.get('compiled_offset') or 0), str(row.get('source_declared_type') or ''), str(row.get('compiled_declared_type') or '')) for row in state.timeline_field_overlap.get('overlap_fields') or () if isinstance(row, Mapping)))
    state.source_only_timeline_fields = set((str(value) for value in state.timeline_field_overlap.get('source_only_fields') or ()))
    state.compiled_only_timeline_fields = set((str(value) for value in state.timeline_field_overlap.get('compiled_only_fields') or ()))
    state.sequence_timeline_field_ok = bool(state.timeline_field_overlap.get('status') == 'source_compiled_timeline_field_overlap' and int(state.timeline_field_overlap.get('source_unique_field_count') or 0) == 173 and (int(state.timeline_field_overlap.get('compiled_unique_field_count') or 0) == 87) and (int(state.timeline_field_overlap.get('overlap_field_count') or 0) == 45) and (int(state.timeline_field_overlap.get('source_only_field_count') or 0) == 128) and (int(state.timeline_field_overlap.get('compiled_only_field_count') or 0) == 42) and (state.timeline_field_signature[:8] == (('_startTimePiece', 'timing', 237, 900, 'int32', 'int32'), ('_endTimePiece', 'timing', 273, 936, 'int32', 'int32'), ('_timelineName', 'timing', 762, 5807, 'staticstringA', 'staticstringA'), ('_startOffsetTimePiece', 'timing', 953, 5998, 'int32', 'int32'), ('_endOffsetTimePiece', 'timing', 995, 6040, 'int32', 'int32'), ('_hasSequencerCamera', 'scene_context', 1035, 6080, 'bool', 'bool'), ('_hasSequencerCamera_Jump', 'scene_context', 1074, 6119, 'bool', 'bool'), ('_hasTransformBlend', 'timing', 1118, 6163, 'bool', 'bool'))) and {'_framesPerSecond', '_startBlendingTime', '_endBlendingTime', '_translationErrorBlend', '_rotationErrorBlend'}.issubset(state.source_only_timeline_fields) and {'_startBlendTime', '_autoMovingBlend'}.issubset(state.compiled_only_timeline_fields))
    state.timeline_field_alias_signature = tuple(((str(row.get('source_name') or ''), str(row.get('compiled_name') or ''), str(row.get('alias_key') or ''), int(row.get('source_offset') or 0), int(row.get('compiled_offset') or 0), str(row.get('source_declared_type') or ''), str(row.get('compiled_declared_type') or '')) for row in state.timeline_field_aliases.get('alias_rows') or () if isinstance(row, Mapping)))
    state.sequence_timeline_field_alias_ok = bool(state.timeline_field_aliases.get('status') == 'source_compiled_timeline_field_semantic_aliases' and int(state.timeline_field_aliases.get('alias_count') or 0) == 1 and (state.timeline_field_alias_signature == (('_startBlendingTime', '_startBlendTime', 'startblendtime', 15775, 1678, 'float', 'float'),)) and ('_endBlendingTime' in set((str(value) for value in state.timeline_field_aliases.get('unmatched_source_fields') or ()))))
    state.source_record_string_signature = tuple(((int(row.get('offset') or 0), int(row.get('length') or 0), str(row.get('text') or '')) for row in state.source_active_lane_record_context.get('length_prefixed_strings') or () if isinstance(row, Mapping)))
    state.compiled_record_string_signature = tuple(((int(row.get('offset') or 0), int(row.get('length') or 0), str(row.get('text') or '')) for row in state.compiled_active_lane_record_context.get('length_prefixed_strings') or () if isinstance(row, Mapping)))
    state.compiled_record_scalar_signature = tuple(((int(row.get('offset') or 0), int(row.get('u32') or 0)) for row in state.compiled_active_lane_record_context.get('scalar_rows') or () if isinstance(row, Mapping)))
    state.sequence_active_lane_record_context_ok = bool(state.source_active_lane_record_context.get('status') == 'path_record_window_recovered' and int(state.source_active_lane_record_context.get('path_text_offset') or 0) == 22031 and (int(state.source_active_lane_record_context.get('path_length_offset') or 0) == 22027) and (int(state.source_active_lane_record_context.get('length_prefixed_string_count') or 0) == 8) and (int(state.source_active_lane_record_context.get('fps_like_u32_count') or 0) == 2) and (state.source_record_string_signature[:5] == ((21942, 30, 'GameCharacterSubtitleEventData'), (21980, 26, 'NHM_Citizen_BackPack_11229'), (22014, 5, 'UnitY'), (22027, 81, state.linked_paa_path), (22116, 30, 'NTM_Citizen_Peddler_BackPack_1'))) and (state.compiled_active_lane_record_context.get('status') == 'path_record_window_recovered') and (int(state.compiled_active_lane_record_context.get('path_text_offset') or 0) == 11402) and (int(state.compiled_active_lane_record_context.get('path_length_offset') or 0) == 11398) and (int(state.compiled_active_lane_record_context.get('length_prefixed_string_count') or 0) == 1) and (int(state.compiled_active_lane_record_context.get('fps_like_u32_count') or 0) == 0) and (int(state.compiled_active_lane_record_context.get('float32_candidate_count') or 0) == 0) and (state.compiled_record_string_signature == ((11398, 81, state.linked_paa_path),)) and (state.compiled_record_scalar_signature[:9] == ((11340, 1024), (11360, 2048), (11376, 2048), (11484, 111), (11492, 2), (11500, 2304), (11516, 2304), (11540, 257), (11556, 45))))
    return None

def _real_sequence_phase_3(state: SimpleNamespace) -> PhaseResult | None:
    state.papr_metadata_totals = state.papr_status.get('constraint_metadata_totals')
    state.papr_metadata_totals = state.papr_metadata_totals if isinstance(state.papr_metadata_totals, Mapping) else {}
    state.papr_expression_shape_totals = state.papr_status.get('constraint_expression_shape_totals')
    state.papr_expression_shape_totals = state.papr_expression_shape_totals if isinstance(state.papr_expression_shape_totals, Mapping) else {}
    state.papr_expression_syntax_signature_totals = state.papr_status.get('constraint_expression_syntax_signature_totals')
    state.papr_expression_syntax_signature_totals = state.papr_expression_syntax_signature_totals if isinstance(state.papr_expression_syntax_signature_totals, Mapping) else {}
    state.papr_numeric_role_totals = state.papr_status.get('constraint_expression_numeric_role_totals')
    state.papr_numeric_role_totals = state.papr_numeric_role_totals if isinstance(state.papr_numeric_role_totals, Mapping) else {}
    state.papr_family_totals = state.papr_status.get('constraint_candidate_family_totals')
    state.papr_family_totals = state.papr_family_totals if isinstance(state.papr_family_totals, Mapping) else {}
    state.papr_solver_totals = state.papr_status.get('constraint_candidate_solver_status_totals')
    state.papr_solver_totals = state.papr_solver_totals if isinstance(state.papr_solver_totals, Mapping) else {}
    state.papr_family_channel_totals = state.papr_status.get('constraint_candidate_family_channel_totals')
    state.papr_family_channel_totals = state.papr_family_channel_totals if isinstance(state.papr_family_channel_totals, Mapping) else {}
    state.papr_driver_channel_totals = state.papr_family_channel_totals.get('driver_expression_candidate')
    state.papr_driver_channel_totals = state.papr_driver_channel_totals if isinstance(state.papr_driver_channel_totals, Mapping) else {}
    state.papr_limit_channel_totals = state.papr_family_channel_totals.get('local_transform_limit_candidate')
    state.papr_limit_channel_totals = state.papr_limit_channel_totals if isinstance(state.papr_limit_channel_totals, Mapping) else {}
    state.papr_family_limit_totals = state.papr_status.get('constraint_candidate_family_limit_totals')
    state.papr_family_limit_totals = state.papr_family_limit_totals if isinstance(state.papr_family_limit_totals, Mapping) else {}
    state.papr_driver_limit_totals = state.papr_family_limit_totals.get('driver_expression_candidate')
    state.papr_driver_limit_totals = state.papr_driver_limit_totals if isinstance(state.papr_driver_limit_totals, Mapping) else {}
    state.papr_limit_limit_totals = state.papr_family_limit_totals.get('local_transform_limit_candidate')
    state.papr_limit_limit_totals = state.papr_limit_limit_totals if isinstance(state.papr_limit_limit_totals, Mapping) else {}
    state.papr_layout_status_totals = state.papr_status.get('constraint_record_layout_status_totals')
    state.papr_layout_status_totals = state.papr_layout_status_totals if isinstance(state.papr_layout_status_totals, Mapping) else {}
    state.papr_field_sequence_totals = state.papr_status.get('constraint_record_field_sequence_totals')
    state.papr_field_sequence_totals = state.papr_field_sequence_totals if isinstance(state.papr_field_sequence_totals, Mapping) else {}
    state.papr_gap_status_totals = state.papr_status.get('constraint_record_gap_status_totals')
    state.papr_gap_status_totals = state.papr_gap_status_totals if isinstance(state.papr_gap_status_totals, Mapping) else {}
    state.papr_gap_class_totals = state.papr_status.get('constraint_record_gap_class_totals')
    state.papr_gap_class_totals = state.papr_gap_class_totals if isinstance(state.papr_gap_class_totals, Mapping) else {}
    state.papr_gap_scalar_status_totals = state.papr_status.get('constraint_record_gap_scalar_status_totals')
    state.papr_gap_scalar_status_totals = state.papr_gap_scalar_status_totals if isinstance(state.papr_gap_scalar_status_totals, Mapping) else {}
    state.papr_gap_scalar_kind_totals = state.papr_status.get('constraint_record_gap_scalar_kind_totals')
    state.papr_gap_scalar_kind_totals = state.papr_gap_scalar_kind_totals if isinstance(state.papr_gap_scalar_kind_totals, Mapping) else {}
    state.papr_gap_numeric_match_status_totals = state.papr_status.get('constraint_record_gap_numeric_match_status_totals')
    state.papr_gap_numeric_match_status_totals = state.papr_gap_numeric_match_status_totals if isinstance(state.papr_gap_numeric_match_status_totals, Mapping) else {}
    state.papr_gap_numeric_match_role_totals = state.papr_status.get('constraint_record_gap_numeric_match_role_totals')
    state.papr_gap_numeric_match_role_totals = state.papr_gap_numeric_match_role_totals if isinstance(state.papr_gap_numeric_match_role_totals, Mapping) else {}
    state.papr_gap_numeric_match_scalar_kind_totals = state.papr_status.get('constraint_record_gap_numeric_match_scalar_kind_totals')
    state.papr_gap_numeric_match_scalar_kind_totals = state.papr_gap_numeric_match_scalar_kind_totals if isinstance(state.papr_gap_numeric_match_scalar_kind_totals, Mapping) else {}
    state.papr_gap_numeric_match_storage_totals = state.papr_status.get('constraint_record_gap_numeric_match_storage_totals')
    state.papr_gap_numeric_match_storage_totals = state.papr_gap_numeric_match_storage_totals if isinstance(state.papr_gap_numeric_match_storage_totals, Mapping) else {}
    state.papr_gap_numeric_match_pair_totals = state.papr_status.get('constraint_record_gap_numeric_match_pair_totals')
    state.papr_gap_numeric_match_pair_totals = state.papr_gap_numeric_match_pair_totals if isinstance(state.papr_gap_numeric_match_pair_totals, Mapping) else {}
    state.papr_gap_numeric_match_value_confidence_totals = state.papr_status.get('constraint_record_gap_numeric_match_value_confidence_totals')
    state.papr_gap_numeric_match_value_confidence_totals = state.papr_gap_numeric_match_value_confidence_totals if isinstance(state.papr_gap_numeric_match_value_confidence_totals, Mapping) else {}
    state.papr_gap_numeric_match_family_totals = state.papr_status.get('constraint_record_gap_numeric_match_family_totals')
    state.papr_gap_numeric_match_family_totals = state.papr_gap_numeric_match_family_totals if isinstance(state.papr_gap_numeric_match_family_totals, Mapping) else {}
    state.papr_gap_numeric_match_family_row_totals = state.papr_status.get('constraint_record_gap_numeric_match_family_row_totals')
    state.papr_gap_numeric_match_family_row_totals = state.papr_gap_numeric_match_family_row_totals if isinstance(state.papr_gap_numeric_match_family_row_totals, Mapping) else {}
    state.papr_gap_numeric_match_family_role_totals = state.papr_status.get('constraint_record_gap_numeric_match_family_role_totals')
    state.papr_gap_numeric_match_family_role_totals = state.papr_gap_numeric_match_family_role_totals if isinstance(state.papr_gap_numeric_match_family_role_totals, Mapping) else {}
    state.papr_driver_role_totals = state.papr_gap_numeric_match_family_role_totals.get('driver_expression_candidate')
    state.papr_driver_role_totals = state.papr_driver_role_totals if isinstance(state.papr_driver_role_totals, Mapping) else {}
    state.papr_limit_role_totals = state.papr_gap_numeric_match_family_role_totals.get('local_transform_limit_candidate')
    state.papr_limit_role_totals = state.papr_limit_role_totals if isinstance(state.papr_limit_role_totals, Mapping) else {}
    state.papr_gap_numeric_match_family_pair_totals = state.papr_status.get('constraint_record_gap_numeric_match_family_pair_totals')
    state.papr_gap_numeric_match_family_pair_totals = state.papr_gap_numeric_match_family_pair_totals if isinstance(state.papr_gap_numeric_match_family_pair_totals, Mapping) else {}
    state.papr_driver_pair_totals = state.papr_gap_numeric_match_family_pair_totals.get('driver_expression_candidate')
    state.papr_driver_pair_totals = state.papr_driver_pair_totals if isinstance(state.papr_driver_pair_totals, Mapping) else {}
    state.papr_limit_pair_totals = state.papr_gap_numeric_match_family_pair_totals.get('local_transform_limit_candidate')
    state.papr_limit_pair_totals = state.papr_limit_pair_totals if isinstance(state.papr_limit_pair_totals, Mapping) else {}
    state.papr_gap_numeric_match_family_value_confidence_totals = state.papr_status.get('constraint_record_gap_numeric_match_family_value_confidence_totals')
    state.papr_gap_numeric_match_family_value_confidence_totals = state.papr_gap_numeric_match_family_value_confidence_totals if isinstance(state.papr_gap_numeric_match_family_value_confidence_totals, Mapping) else {}
    state.papr_driver_value_confidence_totals = state.papr_gap_numeric_match_family_value_confidence_totals.get('driver_expression_candidate')
    state.papr_driver_value_confidence_totals = state.papr_driver_value_confidence_totals if isinstance(state.papr_driver_value_confidence_totals, Mapping) else {}
    state.papr_limit_value_confidence_totals = state.papr_gap_numeric_match_family_value_confidence_totals.get('local_transform_limit_candidate')
    state.papr_limit_value_confidence_totals = state.papr_limit_value_confidence_totals if isinstance(state.papr_limit_value_confidence_totals, Mapping) else {}
    state.papr_gap_numeric_match_signature_totals = state.papr_status.get('constraint_record_gap_numeric_match_signature_totals')
    state.papr_gap_numeric_match_signature_totals = state.papr_gap_numeric_match_signature_totals if isinstance(state.papr_gap_numeric_match_signature_totals, Mapping) else {}
    state.papr_gap_numeric_match_candidate_relative_signature_totals = state.papr_status.get('constraint_record_gap_numeric_match_candidate_relative_signature_totals')
    state.papr_gap_numeric_match_candidate_relative_signature_totals = state.papr_gap_numeric_match_candidate_relative_signature_totals if isinstance(state.papr_gap_numeric_match_candidate_relative_signature_totals, Mapping) else {}
    state.papr_top_limit_signature = 'family=local_transform_limit_candidate|role=limit_argument|pair=parent>target|storage=f32|scalar=u32_u16_candidate|value=approx_float32_numeric_value_match_layout_unproven|prev=13|next=107'
    state.papr_top_driver_signature = 'family=driver_expression_candidate|role=channel_coefficient|pair=parent>helper|storage=f32|scalar=f32_unit_candidate|value=exact_float32_numeric_value_match_layout_unproven|prev=383|next=29'
    state.papr_top_limit_relative_signature = 'family=local_transform_limit_candidate|role=limit_argument|pair=parent>target|storage=f32|scalar=u32_u16_candidate|value=approx_float32_numeric_value_match_layout_unproven|prev=13|next=107|rel=-161'
    state.papr_second_limit_relative_signature = 'family=local_transform_limit_candidate|role=limit_argument|pair=parent>target|storage=f32|scalar=u32_u16_candidate|value=approx_float32_numeric_value_match_layout_unproven|prev=13|next=107|rel=-189'
    state.papr_gap_numeric_match_previous_delta_totals = state.papr_status.get('constraint_record_gap_numeric_match_previous_delta_totals')
    state.papr_gap_numeric_match_previous_delta_totals = state.papr_gap_numeric_match_previous_delta_totals if isinstance(state.papr_gap_numeric_match_previous_delta_totals, Mapping) else {}
    state.papr_gap_numeric_match_next_delta_totals = state.papr_status.get('constraint_record_gap_numeric_match_next_delta_totals')
    state.papr_gap_numeric_match_next_delta_totals = state.papr_gap_numeric_match_next_delta_totals if isinstance(state.papr_gap_numeric_match_next_delta_totals, Mapping) else {}
    state.papr_gap_numeric_match_candidate_relative_offset_totals = state.papr_status.get('constraint_record_gap_numeric_match_candidate_relative_offset_totals')
    state.papr_gap_numeric_match_candidate_relative_offset_totals = state.papr_gap_numeric_match_candidate_relative_offset_totals if isinstance(state.papr_gap_numeric_match_candidate_relative_offset_totals, Mapping) else {}
    return None

def _real_sequence_phase_4(state: SimpleNamespace) -> PhaseResult | None:
    state.papr_gap_numeric_match_rows = state.papr_status.get('constraint_record_gap_numeric_match_rows')
    state.papr_gap_numeric_match_rows = state.papr_gap_numeric_match_rows if isinstance(state.papr_gap_numeric_match_rows, tuple | list) else ()
    state.papr_gap_numeric_match_row_confidences = Counter((str(row.get('value_confidence') or '') for row in state.papr_gap_numeric_match_rows if isinstance(row, Mapping)))
    state.papr_corpus_ok = all((_real_sequence_papr_gate_1(state), _real_sequence_papr_gate_2(state), _real_sequence_papr_gate_3(state), _real_sequence_papr_gate_4(state), _real_sequence_papr_gate_5(state), _real_sequence_papr_gate_6(state), _real_sequence_papr_gate_7(state), _real_sequence_papr_gate_8(state), _real_sequence_papr_gate_9(state), _real_sequence_papr_gate_10(state), _real_sequence_papr_gate_11(state), _real_sequence_papr_gate_12(state), _real_sequence_papr_gate_13(state), _real_sequence_papr_gate_14(state), _real_sequence_papr_gate_15(state), _real_sequence_papr_gate_16(state), _real_sequence_papr_gate_17(state), _real_sequence_papr_gate_18(state), _real_sequence_papr_gate_19(state), _real_sequence_papr_gate_20(state)))
    return None

def _real_sequence_result(state: SimpleNamespace):
    return {'ok': bool(state.sequence_refs and state.linked_paa_entry is not None and state.ready_binding and state.paseq_timing_ok and state.paseq_blend_value_ok and state.sequence_reference_ok and state.sequence_lane_pair_ok and state.sequence_event_marker_ok and state.sequence_timeline_field_ok and state.sequence_timeline_field_alias_ok and state.sequence_active_lane_record_context_ok and state.playback_sample_ok and state.papr_corpus_ok), 'read_only': True, 'game_root': str(state.game_root), 'pamt_count': len(state.pamt_paths), 'pamt_errors': state.pamt_errors, 'entry_count': len(state.entries), 'sequence_entry_counts_by_package': state.sequence_counts, 'sequence_timing_corpus': state.sequence_timing_corpus, 'sequence_path': state.sequence_entry.path, 'sequence_package': state.sequence_entry.pamt_path.parent.name, 'sequence_size': len(state.sequence_data), 'source_sequence_path': state.source_sequence_path, 'source_sequence_found': state.source_sequence_entry is not None, 'source_sequence_timing_probe': state.source_sequence_timing_probe, 'source_sequence_timing_evidence': state.source_sequence_timing_evidence, 'source_sequence_blend_value_ok': state.paseq_blend_value_ok, 'source_sequence_asset_reference_count': len(state.source_sequence_refs), 'source_sequence_paa_reference_count': sum((1 for path in state.source_sequence_refs if path.lower().endswith('.paa'))), 'source_sequence_ptm_paa_references': [path for path in state.source_sequence_refs if path.lower().endswith('.paa') and '/14_ptm/' in path.lower()], 'source_compiled_reference_overlap': state.reference_overlap, 'source_compiled_lane_pair_summary': state.lane_pair_summary, 'source_compiled_event_marker_overlap': state.event_marker_overlap, 'source_compiled_timeline_field_overlap': state.timeline_field_overlap, 'source_compiled_timeline_field_semantic_aliases': state.timeline_field_aliases, 'source_active_lane_record_context': state.source_active_lane_record_context, 'compiled_active_lane_record_context': state.compiled_active_lane_record_context, 'sequence_active_lane_record_context_ok': state.sequence_active_lane_record_context_ok, 'sequence_asset_reference_count': len(state.sequence_refs), 'sequence_paa_reference_count': sum((1 for path in state.sequence_refs if path.lower().endswith('.paa'))), 'sequence_ptm_paa_references': [path for path in state.sequence_refs if path.lower().endswith('.paa') and '/14_ptm/' in path.lower()], 'sequence_resolved_reference_count': len(state.resolved_refs), 'sequence_timeline_lane_count': int(state.timeline.get('lane_count') or 0) if isinstance(state.timeline, dict) else 0, 'sequence_animation_lane_count': int((state.timeline.get('lane_kind_counts') or {}).get('animation') or 0) if isinstance(state.timeline, dict) and isinstance(state.timeline.get('lane_kind_counts'), dict) else 0, 'sequence_timeline_field_count': int(state.timeline.get('timeline_field_count') or 0) if isinstance(state.timeline, dict) else 0, 'sequence_playback_status': str(state.playback.get('status') or '') if isinstance(state.playback, dict) else '', 'sequence_playback_gaps': tuple((str(value) for value in state.playback.get('blocking_gaps') or ())) if isinstance(state.playback, dict) else (), 'sequence_timing_probe': _binary_timing_probe_counts(state.sequence_data), 'linked_paa_path': state.linked_paa_path, 'linked_paa_found': state.linked_paa_entry is not None, 'model_path': state.model_entry.path, 'skeleton_path': state.skeleton_entry.path, 'paa_binding': {'ready': state.ready_binding, 'frame_rate': float(getattr(state.binding, 'frame_rate', 0.0) or 0.0) if state.binding is not None else 0.0, 'frame_rate_source': str(getattr(state.binding, 'frame_rate_source', state.frame_rate_source) or '') if state.binding is not None else state.frame_rate_source, 'frame_rate_confidence': str(getattr(state.binding, 'frame_rate_confidence', state.frame_rate_confidence) or '') if state.binding is not None else state.frame_rate_confidence, 'timing_status': str(getattr(state.binding, 'timing_status', '') or '') if state.binding is not None else 'timing_unproven', 'game_accurate_timing': bool(getattr(state.clip, 'game_accurate_timing', False)) if state.clip is not None else False, 'quaternion_order': str(getattr(state.binding, 'quaternion_order', '') or '') if state.binding is not None else '', 'exact_bone_hash_track_count': int(getattr(state.binding, 'exact_bone_hash_track_count', 0) or 0) if state.binding is not None else 0, 'bound_bone_count': int(getattr(state.binding, 'bound_bone_count', 0) or 0) if state.binding is not None else 0, 'keyframe_count': int(getattr(state.binding, 'keyframe_count', 0) or 0) if state.binding is not None else 0, 'frame_start': int(getattr(state.binding, 'frame_start', 0) or 0) if state.binding is not None else 0, 'frame_end': int(getattr(state.binding, 'frame_end', 0) or 0) if state.binding is not None else 0, 'duration_seconds': float(getattr(state.clip, 'duration_seconds', 0.0) or 0.0) if state.clip is not None else 0.0, 'parser_mode': str(getattr(state.binding, 'parser_mode', '') or '') if state.binding is not None else '', 'sequence_segment_count': len(tuple(getattr(state.clip, 'sequence_segments', ()) or ())) if state.clip is not None else 0, 'sequence_segments': _clip_sequence_segments_json(state.clip)}, 'playback_sample_ok': state.playback_sample_ok, 'playback_sample': state.playback_sample, 'paa_timing_probe': state.paa_timing, 'timing_status': str(state.sequence_timing_corpus.get('fps_evidence_status') or 'sequence_fields_found_but_runtime_fps_not_explicit'), 'quaternion_status': 'paa_rows_decode_as_normalized_xyzw_half_float_quaternions_bound_by_pab_hash', 'papr_read_status': state.papr_status, 'corpus_manifest': state.corpus_manifest}

def run_real_archive_sequence_binding_smoke(game_root: Path) -> dict[str, object]:
    entries, pamt_paths, pamt_errors = _real_archive_all_pamt_entries(game_root)
    if not pamt_paths:
        return {'ok': False, 'read_only': True, 'skipped': f'missing PAMT files under: {game_root}', 'game_root': str(game_root)}
    if not entries:
        return {'ok': False, 'read_only': True, 'game_root': str(game_root), 'pamt_count': len(pamt_paths), 'pamt_errors': pamt_errors, 'error': 'no archive index entries parsed'}
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    corpus_manifest = _mesh_editor_advanced_authoring_corpus_manifest(entries, entries_by_path)
    sequence_entry = _entry_by_archive_path(entries_by_path, _REAL_ARCHIVE_SEQUENCE_SAMPLE)
    skeleton_entry = _entry_by_archive_path(entries_by_path, _REAL_ARCHIVE_SEQUENCE_PTM_PAB)
    model_entry = _entry_by_archive_path(entries_by_path, _REAL_ARCHIVE_RIGGING_SAMPLES[0])
    missing_required = [label for label, entry in ((_REAL_ARCHIVE_SEQUENCE_SAMPLE, sequence_entry), (_REAL_ARCHIVE_SEQUENCE_PTM_PAB, skeleton_entry), (_REAL_ARCHIVE_RIGGING_SAMPLES[0], model_entry)) if entry is None]
    sequence_counts = _real_archive_extension_counts_by_package(entries, _REAL_ARCHIVE_SEQUENCE_EXTENSIONS)
    papr_status = _real_archive_papr_read_status(entries)
    sequence_timing_corpus = _real_archive_sequence_timing_corpus_summary(entries)
    if missing_required:
        return {'ok': False, 'read_only': True, 'game_root': str(game_root), 'pamt_count': len(pamt_paths), 'entry_count': len(entries), 'sequence_entry_counts_by_package': sequence_counts, 'sequence_timing_corpus': sequence_timing_corpus, 'papr_read_status': papr_status, 'corpus_manifest': corpus_manifest, 'missing_required': missing_required}
    state = SimpleNamespace(**locals())
    try:
        outcome = _real_sequence_phase_1(state)
        if outcome is not None:
            return outcome.value
        outcome = _real_sequence_phase_2(state)
        if outcome is not None:
            return outcome.value
        outcome = _real_sequence_phase_3(state)
        if outcome is not None:
            return outcome.value
        outcome = _real_sequence_phase_4(state)
        if outcome is not None:
            return outcome.value
        return _real_sequence_result(state)
    except Exception as exc:
        return {'ok': False, 'read_only': True, 'game_root': str(state.game_root), 'sequence_path': getattr(state.sequence_entry, 'path', _REAL_ARCHIVE_SEQUENCE_SAMPLE), 'corpus_manifest': state.corpus_manifest, 'error': f'{type(exc).__name__}: {exc}'}
