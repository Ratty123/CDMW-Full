from __future__ import annotations

import json
import math
import struct
import time
from bisect import bisect_right
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence, TypeVar

from cdmw.core.common import raise_if_cancelled
from cdmw.core.archive_attachment_patches import (
    build_prefab_attachment_profile_patch,
    inspect_prefab_attachment_profile_fields,
)
from cdmw.core.crimson_formats import decode_prefab, rebuild_prefab_no_edit
from cdmw.core.prefab_json import (
    PrefabEditJsonError,
    apply_prefab_edit_document,
    build_prefab_edit_document,
    rebuild_prefab_no_edit_from_edit_document,
)
from cdmw.models import ArchiveEntry
from cdmw.core.prefab_corpus_contracts import (
    EDIT_PROBES_DISABLED_REASON,
    NO_SAFE_PLACEMENT_LENGTH_PROBE_REASON,
    NO_SAFE_RESOURCE_LENGTH_PROBE_REASON,
    OVERLAPPING_OFFSET_CANDIDATES_REASON,
    PREFAB_JSON_IMPORT_CORPUS_FORMAT,
    T,
)


def discover_loose_prefab_corpus_paths(source_paths: Sequence[Path], *, discovery_limit: Optional[int]=None, stop_event: object=None) -> list[Path]:
    limit = int(discovery_limit) if discovery_limit is not None and int(discovery_limit) > 0 else None
    discovered: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        if path.suffix.lower() != '.prefab':
            return
        try:
            key = str(path.expanduser().resolve()).casefold()
        except OSError:
            key = str(path.expanduser()).casefold()
        if key in seen:
            return
        seen.add(key)
        discovered.append(path)
    for raw_source in source_paths:
        raise_if_cancelled(stop_event)
        source = Path(raw_source).expanduser()
        if source.is_file():
            add(source)
            continue
        if not source.is_dir():
            continue
        for path in source.rglob('*.prefab'):
            raise_if_cancelled(stop_event)
            if path.is_file():
                add(path)
                if limit is not None and len(discovered) >= limit:
                    return sorted(discovered, key=lambda item: str(item).casefold())
    return sorted(discovered, key=lambda item: str(item).casefold())


def _path_label(path: Path, source_paths: Sequence[Path]) -> str:
    for raw_source in source_paths:
        source = Path(raw_source).expanduser()
        try:
            if source.is_dir():
                return path.relative_to(source).as_posix()
            if source.is_file() and path.resolve() == source.resolve():
                return path.name
        except (OSError, ValueError):
            continue
    return path.as_posix()


def _select_corpus_samples(items: Sequence[T], limit: Optional[int]) -> list[T]:
    max_items = int(limit) if limit is not None and int(limit) > 0 else None
    if max_items is None or max_items >= len(items):
        return list(items)
    if max_items == 1:
        return [items[0]]
    last_index = len(items) - 1
    indexes = [index * last_index // (max_items - 1) for index in range(max_items)]
    return [items[index] for index in indexes]


def _select_corpus_scan_items(items: Sequence[T], *, detail_scan_limit: Optional[int], scan_offset: int=0, scan_count: Optional[int]=None) -> list[T]:
    offset = max(0, int(scan_offset or 0))
    count = int(scan_count) if scan_count is not None and int(scan_count) > 0 else None
    if offset or count is not None:
        end = None if count is None else offset + count
        return list(items[offset:end])
    return _select_corpus_samples(items, detail_scan_limit)


def build_prefab_json_import_corpus_report(source_paths: Sequence[Path], *, discovery_limit: Optional[int]=None, detail_scan_limit: Optional[int]=1000, scan_offset: int=0, scan_count: Optional[int]=None, include_edit_probes: bool=True, stop_event: object=None, progress_callback: Optional[Callable[[int, int, str], None]]=None) -> dict[str, object]:
    from cdmw.core.prefab_corpus_audit import audit_prefab_json_import_sample
    from cdmw.core.prefab_corpus_report import _report_from_rows
    normalized_sources = tuple((Path(path).expanduser() for path in source_paths))
    discovered = discover_loose_prefab_corpus_paths(normalized_sources, discovery_limit=discovery_limit, stop_event=stop_event)
    scan_paths = _select_corpus_scan_items(discovered, detail_scan_limit=detail_scan_limit, scan_offset=scan_offset, scan_count=scan_count)
    total = max(len(scan_paths), 1)
    rows: list[Mapping[str, object]] = []
    if progress_callback is not None:
        progress_callback(0, total, f'Discovered {len(discovered):,} loose prefab file(s).')
    for index, path in enumerate(scan_paths, start=1):
        raise_if_cancelled(stop_event)
        label = _path_label(path, normalized_sources)
        if progress_callback is not None:
            progress_callback(index - 1, total, f'Checking prefab JSON no-edit roundtrip: {label}')
        try:
            data = path.read_bytes()
            row = audit_prefab_json_import_sample(data, label, include_edit_probes=include_edit_probes)
        except OSError as exc:
            row = _failed_scan_row(label, exc)
        rows.append(row)
    if progress_callback is not None:
        progress_callback(total, total, 'Prefab JSON import corpus report complete.')
    return _report_from_rows(rows, source_type='loose_files', source_paths=[str(path) for path in normalized_sources], files_discovered=len(discovered), discovery_limit=discovery_limit, detail_scan_limit=detail_scan_limit, scan_offset=scan_offset, scan_count=scan_count, edit_probes_enabled=include_edit_probes)


def build_prefab_json_import_archive_entry_report(entries: Sequence[ArchiveEntry], *, read_entry_data: Optional[Callable[..., tuple[bytes, bool, str]]]=None, source_label: str='archive_entries', discovery_limit: Optional[int]=None, detail_scan_limit: Optional[int]=1000, scan_offset: int=0, scan_count: Optional[int]=None, include_edit_probes: bool=True, stop_event: object=None, progress_callback: Optional[Callable[[int, int, str], None]]=None) -> dict[str, object]:
    from cdmw.core.prefab_corpus_audit import audit_prefab_json_import_sample
    from cdmw.core.prefab_corpus_publication import _read_archive_entry_payload, discover_prefab_archive_entries
    from cdmw.core.prefab_corpus_report import _report_from_rows
    if read_entry_data is None:
        from cdmw.core.archive_extraction import read_archive_entry_data as read_entry_data
    discovered = discover_prefab_archive_entries(entries, discovery_limit=discovery_limit)
    scan_entries = _select_corpus_scan_items(discovered, detail_scan_limit=detail_scan_limit, scan_offset=scan_offset, scan_count=scan_count)
    total = max(len(scan_entries), 1)
    rows: list[Mapping[str, object]] = []
    if progress_callback is not None:
        progress_callback(0, total, f'Discovered {len(discovered):,} prefab archive entry/entries.')
    for index, entry in enumerate(scan_entries, start=1):
        raise_if_cancelled(stop_event)
        label = str(entry.path or '')
        if progress_callback is not None:
            progress_callback(index - 1, total, f'Checking prefab JSON no-edit roundtrip: {label}')
        try:
            data = _read_archive_entry_payload(entry, read_entry_data, stop_event=stop_event)
            row = audit_prefab_json_import_sample(data, label, include_edit_probes=include_edit_probes)
        except (OSError, ValueError, TypeError) as exc:
            row = _failed_scan_row(label, exc)
        rows.append(row)
    if progress_callback is not None:
        progress_callback(total, total, 'Prefab JSON import archive-entry corpus report complete.')
    return _report_from_rows(rows, source_type='archive_entries', source_paths=[source_label], files_discovered=len(discovered), discovery_limit=discovery_limit, detail_scan_limit=detail_scan_limit, scan_offset=scan_offset, scan_count=scan_count, edit_probes_enabled=include_edit_probes)


def _failed_scan_row_part_0(label, exc) -> dict[str, object]:
    result = {}
    result.update({'path': label})
    result.update({'status': 'failed'})
    result.update({'byte_length': 0})
    result.update({'prefab_header': {}})
    result.update({'prefab_layout': {}})
    result.update({'declared_field_count': 0})
    result.update({'member_declaration_count': 0})
    result.update({'member_descriptor_bytes': 0})
    result.update({'descriptor_tail_member_kind_counts': {}})
    result.update({'descriptor_tail_byte_kind_counts': {}})
    result.update({'descriptor_tail_member_detail_counts': {}})
    result.update({'transform_member_count': 0})
    result.update({'decoded_transform_payload_value_rows': 0})
    result.update({'transform_members_without_payload_values': 0})
    result.update({'transform_members_with_descriptor_tail_bytes': 0})
    result.update({'transform_descriptor_tail_bytes': 0})
    result.update({'transform_name_only_member_count': 0})
    result.update({'transform_descriptor_signature_counts': {}})
    result.update({'transform_descriptor_signature_offset_candidate_counts': {}})
    result.update({'transform_nonzero_word3_offset_candidate_status_counts': {'with_offset_candidate': 0, 'without_offset_candidate': 0}})
    result.update({'transform_descriptor_signature_offset_candidate_target_counts': {}})
    result.update({'transform_nonzero_word3_offset_candidate_target_counts': {}})
    result.update({'transform_descriptor_word0_value_counts': {}})
    result.update({'transform_descriptor_word1_value_counts': {}})
    result.update({'transform_descriptor_word2_value_counts': {}})
    result.update({'transform_descriptor_word3_value_counts': {}})
    result.update({'transform_theoretical_payload_shape_counts': {}})
    result.update({'transform_theoretical_payload_member_rows': 0})
    result.update({'transform_theoretical_payload_byte_count': 0})
    result.update({'transform_theoretical_payload_exact_preserved_span_rows': 0})
    result.update({'transform_theoretical_payload_later_preserved_span_fit_rows': 0})
    result.update({'transform_theoretical_payload_no_preserved_span_fit_rows': 0})
    result.update({'transform_theoretical_payload_immediate_window_string_span_overlap_rows': 0})
    result.update({'transform_theoretical_payload_immediate_window_string_span_overlap_count': 0})
    result.update({'transform_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows': 0})
    result.update({'array_member_count': 0})
    result.update({'decoded_array_payload_element_rows': 0})
    result.update({'array_members_without_payload_elements': 0})
    result.update({'array_members_with_descriptor_tail_bytes': 0})
    result.update({'array_descriptor_tail_bytes': 0})
    result.update({'array_member_stride_hint_count': 0})
    result.update({'array_member_count_hint_count': 0})
    result.update({'array_descriptor_signature_counts': {}})
    result.update({'array_descriptor_signature_offset_candidate_counts': {}})
    result.update({'array_descriptor_signature_offset_candidate_target_counts': {}})
    result.update({'array_nonzero_word3_offset_candidate_target_counts': {}})
    result.update({'array_descriptor_word0_value_counts': {}})
    result.update({'array_descriptor_word1_value_counts': {}})
    result.update({'array_descriptor_word2_value_counts': {}})
    result.update({'array_descriptor_word3_value_counts': {}})
    result.update({'array_stride_hint_type_counts': {}})
    result.update({'array_count_hint_type_counts': {}})
    result.update({'array_count_hint_member_counts': {}})
    result.update({'array_word3_relation_counts': {'array_rows': 0, 'with_count_hint_rows': 0, 'with_stride_hint_rows': 0, 'word3_zero_rows': 0, 'word3_nonzero_rows': 0, 'word3_equals_count_hint_rows': 0, 'word3_nonzero_equals_count_hint_rows': 0, 'count_hint_positive_word3_equals_count_hint_rows': 0, 'count_hint_positive_word3_not_count_hint_rows': 0, 'word3_equals_stride_hint_rows': 0, 'word3_equals_word2_delta_rows': 0, 'word3_nonzero_without_count_hint_rows': 0, 'word3_nonzero_without_stride_hint_rows': 0}})
    result.update({'array_theoretical_payload_shape_counts': {}})
    return result


def _failed_scan_row_part_1(label, exc) -> dict[str, object]:
    result = {}
    result.update({'array_theoretical_payload_member_rows': 0})
    result.update({'array_theoretical_payload_byte_count': 0})
    result.update({'array_theoretical_payload_non_tiny_member_rows': 0})
    result.update({'array_theoretical_payload_non_tiny_byte_count': 0})
    result.update({'array_theoretical_payload_exact_preserved_span_rows': 0})
    result.update({'array_theoretical_payload_later_preserved_span_fit_rows': 0})
    result.update({'array_theoretical_payload_no_preserved_span_fit_rows': 0})
    result.update({'array_theoretical_payload_immediate_window_string_span_overlap_rows': 0})
    result.update({'array_theoretical_payload_immediate_window_string_span_overlap_count': 0})
    result.update({'array_theoretical_payload_later_fit_with_intervening_string_or_declaration_rows': 0})
    result.update({'array_word2_delta_member_counts': {}})
    result.update({'array_word2_delta_word3_member_counts': {}})
    result.update({'array_word2_delta_word3_member_offset_candidate_counts': {}})
    result.update({'array_nonzero_word3_offset_candidate_status_counts': {'with_offset_candidate': 0, 'without_offset_candidate': 0}})
    result.update({'array_classification_source_counts': {'type_vector_count': 0, 'type_brackets_count': 0, 'name_list_flag_count': 0}})
    result.update({'array_word3_category_counts': {'zero_count': 0, 'one_count': 0, 'power_of_two_gt_one_count': 0, 'other_nonzero_count': 0, 'nonzero_with_stride_hint_count': 0, 'nonzero_without_stride_hint_count': 0}})
    result.update({'reference_member_count': 0})
    result.update({'reference_members_without_descriptor_semantics': 0})
    result.update({'reference_members_with_descriptor_tail_bytes': 0})
    result.update({'reference_descriptor_tail_bytes': 0})
    result.update({'reference_descriptor_signature_counts': {}})
    result.update({'reference_descriptor_tail_record_shape_counts': {}})
    result.update({'reference_descriptor_tail_offset_candidate_mod_counts': {}})
    result.update({'reference_descriptor_tail_record_profile_counts': {'exact_tail_members': 0, 'record_count_total': 0, 'unique_record_count_total': 0, 'duplicate_record_count_total': 0, 'offset_candidate_record_count_total': 0, 'offset_candidate_free_record_count_total': 0, 'offset_candidate_multi_kind_record_count_total': 0, 'max_offset_candidates_per_record': 0}})
    result.update({'reference_descriptor_tail_numeric_profile_counts': {}})
    result.update({'reference_descriptor_tail_column_profile_counts': {'exact_tail_members': 0, 'record_count_total': 0, 'u32_columns_total': 0, 'constant_u32_columns': 0, 'variable_u32_columns': 0, 'all_zero_u32_columns': 0, 'mostly_zero_u32_columns': 0, 'offset_candidate_u32_columns': 0, 'offset_candidate_free_u32_columns': 0, 'unique_u32_value_total': 0, 'max_unique_u32_values_per_column': 0, 'unaligned_offset_candidate_rows': 0}})
    result.update({'reference_descriptor_signature_offset_candidate_counts': {}})
    result.update({'reference_nonzero_word3_offset_candidate_status_counts': {'with_offset_candidate': 0, 'without_offset_candidate': 0}})
    result.update({'reference_descriptor_signature_offset_candidate_target_counts': {}})
    result.update({'reference_nonzero_word3_offset_candidate_target_counts': {}})
    result.update({'scalar_or_bool_descriptor_signature_counts': {}})
    result.update({'scalar_or_bool_descriptor_signature_offset_candidate_counts': {}})
    result.update({'scalar_or_bool_nonzero_word3_offset_candidate_status_counts': {'with_offset_candidate': 0, 'without_offset_candidate': 0}})
    result.update({'scalar_or_bool_descriptor_signature_offset_candidate_target_counts': {}})
    result.update({'scalar_or_bool_nonzero_word3_offset_candidate_target_counts': {}})
    result.update({'string_descriptor_signature_counts': {}})
    result.update({'string_descriptor_signature_offset_candidate_counts': {}})
    result.update({'string_nonzero_word3_offset_candidate_status_counts': {'with_offset_candidate': 0, 'without_offset_candidate': 0}})
    result.update({'string_descriptor_signature_offset_candidate_target_counts': {}})
    result.update({'string_nonzero_word3_offset_candidate_target_counts': {}})
    result.update({'generic_descriptor_signature_counts': {}})
    result.update({'generic_descriptor_signature_offset_candidate_counts': {}})
    result.update({'generic_nonzero_word3_offset_candidate_status_counts': {'with_offset_candidate': 0, 'without_offset_candidate': 0}})
    result.update({'generic_descriptor_signature_offset_candidate_target_counts': {}})
    result.update({'generic_nonzero_word3_offset_candidate_target_counts': {}})
    result.update({'descriptor_owner_kind_offset_candidate_counts': {}})
    result.update({'descriptor_owner_kind_offset_candidate_target_counts': {}})
    result.update({'offset_candidate_count': 0})
    result.update({'offset_candidate_overlap_count': 0})
    result.update({'offset_candidate_aligned_count': 0})
    result.update({'offset_candidate_unaligned_count': 0})
    result.update({'offset_candidate_overlap_group_count': 0})
    result.update({'offset_candidate_overlapping_window_count': 0})
    result.update({'offset_candidate_isolated_count': 0})
    result.update({'offset_candidate_aligned_isolated_count': 0})
    return result


def _failed_scan_row_part_2(label, exc) -> dict[str, object]:
    result = {}
    result.update({'offset_candidate_unaligned_isolated_count': 0})
    result.update({'offset_candidate_unaligned_or_overlapping_count': 0})
    result.update({'offset_candidate_target_string_length_prefix_count': 0})
    result.update({'offset_candidate_target_string_value_count': 0})
    result.update({'offset_candidate_target_string_end_count': 0})
    result.update({'offset_candidate_in_member_descriptor_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_count': 0})
    result.update({'offset_candidate_in_array_descriptor_count': 0})
    result.update({'offset_candidate_in_transform_descriptor_count': 0})
    result.update({'offset_candidate_in_reference_descriptor_count': 0})
    result.update({'offset_candidate_in_scalar_or_bool_descriptor_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_aligned_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_unaligned_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_overlap_group_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_overlapping_window_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_isolated_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_aligned_isolated_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_unaligned_isolated_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_unaligned_or_overlapping_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_target_string_length_prefix_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_target_string_value_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_target_string_end_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_candidate_offset_mod4_counts': {'0': 0, '1': 0, '2': 0, '3': 0}})
    result.update({'offset_candidate_outside_member_descriptor_target_value_mod4_counts': {'0': 0, '1': 0, '2': 0, '3': 0}})
    result.update({'offset_candidate_outside_member_descriptor_string_value_candidate_offset_mod4_counts': {'0': 0, '1': 0, '2': 0, '3': 0}})
    result.update({'offset_candidate_outside_member_descriptor_string_value_target_value_mod4_counts': {'0': 0, '1': 0, '2': 0, '3': 0}})
    result.update({'offset_candidate_outside_member_descriptor_neighbor_byte_class_counts': {'ascii_like': 0, 'binary_like': 0, 'empty': 0, 'nul_rich': 0}})
    result.update({'offset_candidate_outside_member_descriptor_target_role_counts': {'resource_reference_count': 0, 'member_name_count': 0, 'member_type_count': 0, 'other_string_count': 0}})
    result.update({'offset_candidate_outside_member_descriptor_string_value_target_role_counts': {'resource_reference_count': 0, 'member_name_count': 0, 'member_type_count': 0, 'other_string_count': 0}})
    result.update({'offset_candidate_outside_member_descriptor_aligned_isolated_target_role_kind_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_aligned_isolated_outside_preserved_span_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_exact_4_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_aligned_isolated_preserved_span_le_8_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_start_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_aligned_isolated_at_preserved_span_end_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_aligned_isolated_in_preserved_span_middle_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_aligned_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_unaligned_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_isolated_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_unaligned_or_overlapping_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_target_string_length_prefix_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_target_string_value_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_target_string_end_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_aligned_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_isolated_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_unaligned_or_overlapping_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_length_prefix_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_value_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_string_end_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_counts': {'resource_reference_count': 0, 'member_name_count': 0, 'member_type_count': 0, 'other_string_count': 0}})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_counts': {}})
    return result


def _failed_scan_row_part_3(label, exc) -> dict[str, object]:
    result = {}
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_neighbor_byte_class_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_span_position_neighbor_byte_class_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_target_role_kind_signed_distance_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_span_byte_length_counts': {'le_16': 0, 'le_32': 0, 'le_64': 0, 'le_128': 0, 'gt_128': 0}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_candidate_offset_mod4_counts': {'0': 0, '1': 0, '2': 0, '3': 0}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_target_value_mod4_counts': {'0': 0, '1': 0, '2': 0, '3': 0}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_neighbor_byte_class_counts': {'ascii_like': 0, 'binary_like': 0, 'empty': 0, 'nul_rich': 0}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_extension_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_role_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_bucket_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_alignment_target_kind_span_position_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_target_profile_span_position_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_target_profile_distance_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_target_profile_neighbor_byte_class_counts': {}})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_outside_preserved_span_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_preserved_span_exact_4_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_preserved_span_le_8_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_start_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_at_preserved_span_end_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_in_preserved_span_middle_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_resource_reference_span_byte_length_counts': {'le_16': 0, 'le_32': 0, 'le_64': 0, 'le_128': 0, 'gt_128': 0}})
    result.update({'offset_candidate_in_preserved_span_count': 0})
    result.update({'offset_candidate_outside_preserved_span_count': 0})
    result.update({'offset_candidate_preserved_span_exact_4_count': 0})
    result.update({'offset_candidate_preserved_span_le_8_count': 0})
    result.update({'offset_candidate_at_preserved_span_start_count': 0})
    result.update({'offset_candidate_at_preserved_span_end_count': 0})
    result.update({'offset_candidate_in_preserved_span_middle_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_exact_4_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_le_8_count': 0})
    result.update({'offset_candidate_outside_member_descriptor_preserved_span_middle_count': 0})
    result.update({'largest_preserved_span_byte_count': 0})
    result.update({'preserved_span_with_offset_candidate_count': 0})
    result.update({'preserved_span_without_offset_candidate_count': 0})
    result.update({'member_descriptor_preserved_bytes': 0})
    result.update({'member_descriptor_header_preserved_bytes': 0})
    result.update({'member_descriptor_tail_preserved_bytes': 0})
    result.update({'preserved_unknown_bytes_excluding_member_descriptors': 0})
    result.update({'preserved_unknown_bytes_excluding_member_descriptor_headers': 0})
    result.update({'preserved_unknown_bytes_without_block_semantics': 0})
    result.update({'preserved_span_with_member_descriptor_count': 0})
    result.update({'preserved_span_without_member_descriptor_count': 0})
    result.update({'reference_count': 0})
    result.update({'editable_reference_count': 0})
    result.update({'editable_placement_field_count': 0})
    result.update({'resource_resize_impact_offset_candidate_count': 0})
    result.update({'placement_resize_impact_offset_candidate_count': 0})
    result.update({'resource_resize_impact_target_role_kind_counts': {}})
    result.update({'placement_resize_impact_target_role_kind_counts': {}})
    result.update({'resource_resize_impact_owner_kind_target_counts': {}})
    result.update({'placement_resize_impact_owner_kind_target_counts': {}})
    result.update({'resource_resize_impact_resource_reference_target_profile_distance_counts': {}})
    result.update({'placement_resize_impact_resource_reference_target_profile_distance_counts': {}})
    return result


def _failed_scan_row_part_4(label, exc) -> dict[str, object]:
    result = {}
    result.update({'resource_resize_impact_resource_reference_target_profile_span_position_counts': {}})
    result.update({'placement_resize_impact_resource_reference_target_profile_span_position_counts': {}})
    result.update({'resource_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts': {}})
    result.update({'placement_resize_impact_resource_reference_target_profile_neighbor_byte_class_counts': {}})
    result.update({'resource_resize_impact_unique_offset_candidate_count': 0})
    result.update({'placement_resize_impact_unique_offset_candidate_count': 0})
    result.update({'resource_resize_impact_unique_target_role_kind_counts': {}})
    result.update({'placement_resize_impact_unique_target_role_kind_counts': {}})
    result.update({'resource_resize_impact_unique_owner_kind_target_counts': {}})
    result.update({'placement_resize_impact_unique_owner_kind_target_counts': {}})
    result.update({'resource_resize_impact_unique_candidate_profile_counts': {}})
    result.update({'placement_resize_impact_unique_candidate_profile_counts': {}})
    result.update({'resource_resize_impact_unique_overlap_profile_counts': {}})
    result.update({'placement_resize_impact_unique_overlap_profile_counts': {}})
    result.update({'resource_resize_impact_unique_overlap_group_profile_counts': {}})
    result.update({'placement_resize_impact_unique_overlap_group_profile_counts': {}})
    result.update({'resource_resize_impact_unique_overlap_group_target_identity_counts': {}})
    result.update({'placement_resize_impact_unique_overlap_group_target_identity_counts': {}})
    result.update({'resource_resize_impact_unique_same_target_overlap_collapse_counts': {'impacted_overlap_group_count': 0, 'impacted_overlap_candidate_count': 0, 'same_target_duplicate_group_count': 0, 'same_target_duplicate_candidate_count': 0, 'mixed_target_group_count': 0, 'mixed_target_candidate_count': 0, 'blocker_group_count_after_same_target_collapse': 0, 'blocker_candidate_count_after_same_target_collapse': 0}})
    result.update({'placement_resize_impact_unique_same_target_overlap_collapse_counts': {'impacted_overlap_group_count': 0, 'impacted_overlap_candidate_count': 0, 'same_target_duplicate_group_count': 0, 'same_target_duplicate_candidate_count': 0, 'mixed_target_group_count': 0, 'mixed_target_candidate_count': 0, 'blocker_group_count_after_same_target_collapse': 0, 'blocker_candidate_count_after_same_target_collapse': 0}})
    result.update({'resource_resize_impact_unique_same_target_overlap_shift_conflict_counts': {'same_target_overlap_group_count': 0, 'same_target_overlap_candidate_count': 0, 'shift_consistent_group_count': 0, 'shift_consistent_candidate_count': 0, 'shift_conflict_group_count': 0, 'shift_conflict_candidate_count': 0}})
    result.update({'placement_resize_impact_unique_same_target_overlap_shift_conflict_counts': {'same_target_overlap_group_count': 0, 'same_target_overlap_candidate_count': 0, 'shift_consistent_group_count': 0, 'shift_consistent_candidate_count': 0, 'shift_conflict_group_count': 0, 'shift_conflict_candidate_count': 0}})
    result.update({'resource_resize_impact_unique_same_target_shift_conflict_group_detail_counts': {}})
    result.update({'placement_resize_impact_unique_same_target_shift_conflict_group_detail_counts': {}})
    result.update({'resource_resize_impact_unique_same_target_resource_alias_counts': {'same_target_conflict_group_count': 0, 'same_target_conflict_candidate_count': 0, 'resource_alias_group_count': 0, 'resource_alias_candidate_count': 0, 'remaining_group_count': 0, 'remaining_candidate_count': 0}})
    result.update({'placement_resize_impact_unique_same_target_resource_alias_counts': {'same_target_conflict_group_count': 0, 'same_target_conflict_candidate_count': 0, 'resource_alias_group_count': 0, 'resource_alias_candidate_count': 0, 'remaining_group_count': 0, 'remaining_candidate_count': 0}})
    result.update({'resource_resize_impact_unique_mixed_target_overlap_shift_conflict_counts': {'mixed_target_overlap_group_count': 0, 'mixed_target_overlap_candidate_count': 0, 'shift_consistent_group_count': 0, 'shift_consistent_candidate_count': 0, 'shift_conflict_group_count': 0, 'shift_conflict_candidate_count': 0}})
    result.update({'placement_resize_impact_unique_mixed_target_overlap_shift_conflict_counts': {'mixed_target_overlap_group_count': 0, 'mixed_target_overlap_candidate_count': 0, 'shift_consistent_group_count': 0, 'shift_consistent_candidate_count': 0, 'shift_conflict_group_count': 0, 'shift_conflict_candidate_count': 0}})
    result.update({'resource_resize_impact_unique_mixed_target_overlap_blocker_profile_counts': {}})
    result.update({'placement_resize_impact_unique_mixed_target_overlap_blocker_profile_counts': {}})
    result.update({'resource_resize_impact_unique_mixed_target_overlap_impacted_identity_counts': {}})
    result.update({'placement_resize_impact_unique_mixed_target_overlap_impacted_identity_counts': {}})
    result.update({'resource_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary': {'candidate_count': 0, 'unique_identity_count': 0, 'repeated_identity_count': 0, 'repeated_candidate_count': 0, 'high_repeat_10_identity_count': 0, 'high_repeat_10_candidate_count': 0, 'max_identity_candidate_count': 0}})
    result.update({'placement_resize_impact_unique_mixed_target_overlap_impacted_identity_repeat_summary': {'candidate_count': 0, 'unique_identity_count': 0, 'repeated_identity_count': 0, 'repeated_candidate_count': 0, 'high_repeat_10_identity_count': 0, 'high_repeat_10_candidate_count': 0, 'max_identity_candidate_count': 0}})
    result.update({'resource_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts': {'mixed_target_group_count': 0, 'mixed_target_candidate_count': 0, 'high_repeat_identity_count': 0, 'high_repeat_candidate_count': 0, 'remaining_group_count_after_high_repeat_collapse': 0, 'remaining_candidate_count_after_high_repeat_collapse': 0}})
    result.update({'placement_resize_impact_unique_mixed_target_high_repeat_identity_collapse_counts': {'mixed_target_group_count': 0, 'mixed_target_candidate_count': 0, 'high_repeat_identity_count': 0, 'high_repeat_candidate_count': 0, 'remaining_group_count_after_high_repeat_collapse': 0, 'remaining_candidate_count_after_high_repeat_collapse': 0}})
    result.update({'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts': {}})
    result.update({'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_profile_counts': {}})
    result.update({'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts': {}})
    result.update({'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_identity_counts': {}})
    result.update({'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts': {'remaining_group_count': 0, 'remaining_candidate_count': 0, 'remaining_resource_reference_candidate_count': 0, 'remaining_metadata_candidate_count': 0, 'remaining_resource_reference_group_count': 0, 'remaining_metadata_only_group_count': 0}})
    result.update({'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_role_counts': {'remaining_group_count': 0, 'remaining_candidate_count': 0, 'remaining_resource_reference_candidate_count': 0, 'remaining_metadata_candidate_count': 0, 'remaining_resource_reference_group_count': 0, 'remaining_metadata_only_group_count': 0}})
    result.update({'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts': {}})
    result.update({'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_group_detail_counts': {}})
    result.update({'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts': {'remaining_resource_reference_group_count': 0, 'remaining_resource_reference_candidate_count': 0, 'metadata_collision_group_count': 0, 'metadata_collision_candidate_count': 0, 'remaining_group_count': 0, 'remaining_candidate_count': 0}})
    result.update({'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_metadata_collision_counts': {'remaining_resource_reference_group_count': 0, 'remaining_resource_reference_candidate_count': 0, 'metadata_collision_group_count': 0, 'metadata_collision_candidate_count': 0, 'remaining_group_count': 0, 'remaining_candidate_count': 0}})
    result.update({'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts': {'remaining_resource_reference_group_count': 0, 'remaining_resource_reference_candidate_count': 0, 'nonimpacted_reference_collision_group_count': 0, 'nonimpacted_reference_collision_candidate_count': 0, 'remaining_group_count': 0, 'remaining_candidate_count': 0}})
    result.update({'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_resource_reference_nonimpacted_reference_collision_counts': {'remaining_resource_reference_group_count': 0, 'remaining_resource_reference_candidate_count': 0, 'nonimpacted_reference_collision_group_count': 0, 'nonimpacted_reference_collision_candidate_count': 0, 'remaining_group_count': 0, 'remaining_candidate_count': 0}})
    result.update({'resource_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts': {}})
    result.update({'placement_resize_impact_unique_mixed_target_high_repeat_identity_remaining_shape_counts': {}})
    result.update({'resource_resize_impact_unique_mixed_target_overlap_impacted_shape_counts': {}})
    result.update({'placement_resize_impact_unique_mixed_target_overlap_impacted_shape_counts': {}})
    result.update({'resource_resize_impact_unique_resource_reference_target_profile_distance_counts': {}})
    result.update({'placement_resize_impact_unique_resource_reference_target_profile_distance_counts': {}})
    result.update({'resource_resize_impact_unique_overlap_counts': {'non_overlapping_count': 0, 'overlapping_count': 0}})
    return result


def _failed_scan_row_part_5(label, exc) -> dict[str, object]:
    result = {}
    result.update({'placement_resize_impact_unique_overlap_counts': {'non_overlapping_count': 0, 'overlapping_count': 0}})
    result.update({'resource_resize_impact_unique_resource_reference_overlap_counts': {'non_overlapping_count': 0, 'overlapping_count': 0}})
    result.update({'placement_resize_impact_unique_resource_reference_overlap_counts': {'non_overlapping_count': 0, 'overlapping_count': 0}})
    result.update({'policy_resize_readiness': {}})
    result.update({'length_change_tail_only_candidate_count': 0})
    result.update({'length_change_downstream_rebuild_row_count': 0})
    result.update({'length_change_offset_rebuild_row_count': 0})
    result.update({'layout_rebuild_byte_identical': False})
    result.update({'json_layout_rebuild_byte_identical': False})
    result.update({'no_edit_roundtrip_byte_identical': False})
    result.update({'same_length_resource_edit_probe': {'status': 'failed', 'edited_reference_count': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'error': str(exc)}})
    result.update({'same_length_placement_edit_probe': {'status': 'failed', 'edited_field_count': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'error': str(exc)}})
    result.update({'experimental_length_change_resource_rebuild_probe': {'status': 'failed', 'edited_reference_count': 0, 'byte_delta': 0, 'offset_candidate_count_after_edit': 0, 'offset_candidates_remapped_after_edit': False, 'offset_candidates_effectively_remapped_after_edit': False, 'resized_rebuild_changed_only_expected_bytes': False, 'resized_rebuild_changed_only_effective_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'used_opt_in_import_path': False, 'replacement_reference_found': False, 'error': str(exc)}})
    result.update({'experimental_length_change_placement_rebuild_probe': {'status': 'failed', 'edited_field_count': 0, 'byte_delta': 0, 'offset_candidate_count_after_edit': 0, 'offset_candidates_remapped_after_edit': False, 'offset_candidates_effectively_remapped_after_edit': False, 'resized_rebuild_changed_only_expected_bytes': False, 'resized_rebuild_changed_only_effective_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'used_low_level_profile_patch': False, 'replacement_field_found': False, 'error': str(exc)}})
    result.update({'report_only_array_count_hint_mutation_probe': {'status': 'failed', 'member_name': '', 'member_type': '', 'descriptor_offset': -1, 'old_count_hint': 0, 'new_count_hint': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'decoded_count_hint_changed': False, 'member_identity_preserved': False, 'semantics_proven': False, 'error': str(exc)}})
    result.update({'report_only_transform_word3_mutation_probe': {'status': 'failed', 'member_name': '', 'member_type': '', 'descriptor_offset': -1, 'old_word3': 0, 'new_word3': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'decoded_word3_changed': False, 'member_identity_preserved': False, 'semantics_proven': False, 'error': str(exc)}})
    result.update({'report_only_reference_word3_mutation_probe': {'status': 'failed', 'member_name': '', 'member_type': '', 'descriptor_offset': -1, 'old_word3': 0, 'new_word3': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'decoded_word3_changed': False, 'member_identity_preserved': False, 'semantics_proven': False, 'error': str(exc)}})
    result.update({'report_only_preserved_unknown_byte_mutation_probe': {'status': 'failed', 'span_index': -1, 'span_start': -1, 'span_end': -1, 'mutation_offset': -1, 'old_byte': 0, 'new_byte': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'decoded_byte_changed': False, 'span_identity_preserved': False, 'semantics_proven': False, 'error': str(exc)}})
    result.update({'report_only_descriptor_word3_mutation_probe': {'status': 'failed', 'member_name': '', 'member_type': '', 'descriptor_kind': '', 'descriptor_offset': -1, 'old_word3': 0, 'new_word3': 0, 'changed_only_expected_bytes': False, 'layout_fully_accounted_after_edit': False, 'no_edit_rebuild_after_edit': False, 'json_no_edit_roundtrip_after_edit': False, 'json_layout_rebuild_after_edit': False, 'decoded_word3_changed': False, 'member_identity_preserved': False, 'semantics_proven': False, 'error': str(exc)}})
    result.update({'elapsed_ms': 0.0})
    result.update({'error': str(exc)})
    return result


def _failed_scan_row(label, exc) -> dict[str, object]:
    result: dict[str, object] = {}
    result.update(_failed_scan_row_part_0(label, exc))
    result.update(_failed_scan_row_part_1(label, exc))
    result.update(_failed_scan_row_part_2(label, exc))
    result.update(_failed_scan_row_part_3(label, exc))
    result.update(_failed_scan_row_part_4(label, exc))
    result.update(_failed_scan_row_part_5(label, exc))
    return result
