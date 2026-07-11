from __future__ import annotations
from types import SimpleNamespace
from cdmw.models import ArchiveEntry
from collections import Counter
from collections.abc import Mapping
from collections.abc import Sequence
from cdmw.core.archive_binary_preview import build_binary_sidecar_analysis_document
from cdmw.core.archive_extraction import read_archive_entry_data
from tools.mesh_harness.real_common import _archive_entry_indexes, _entry_by_archive_path, _read_archive_payload

def _papr_process_entry(state: SimpleNamespace, entry: ArchiveEntry) -> None:
    try:
        state.data, state.decompressed, state.note = read_archive_entry_data(entry)
    except Exception as exc:
        state.message = f'{type(exc).__name__}: {exc}'
        state.status = state.message.split(' for ', 1)[0]
        state.status_counts[state.status] += 1
        state.examples.setdefault(state.status, entry.path)
    else:
        state.ok_count += 1
        state.status_counts['ok'] += 1
        state.examples.setdefault('ok', entry.path)
        state.constraint_metadata = _papr_constraint_metadata_summary(state.data, entry, entries_by_path=state.entries_by_path, entries_by_basename=state.entries_by_basename)
        if 'error' in state.constraint_metadata:
            if len(state.analysis_errors) < 4:
                state.analysis_errors.append({'path': entry.path, 'error': str(state.constraint_metadata['error'])})
        else:
            for state.key in ('schema_declarations', 'schema_declared_members', 'field_like_identifiers', 'asset_reference_hints', 'offset_candidates', 'count_offset_pair_candidates', 'float_vector_candidates', 'related_file_rows', 'related_files_resolved', 'constraint_string_evidence', 'constraint_record_candidates', 'constraint_related_physics'):
                state.constraint_metadata_totals[state.key] += int(state.constraint_metadata.get(state.key) or 0)
            _counter_update_ints(state.constraint_expression_role_totals, state.constraint_metadata.get('constraint_expression_role_counts'))
            _counter_update_ints(state.constraint_expression_shape_totals, state.constraint_metadata.get('constraint_expression_shape_counts'))
            _counter_update_ints(state.constraint_expression_syntax_signature_totals, state.constraint_metadata.get('constraint_expression_syntax_signature_counts'))
            _counter_update_ints(state.constraint_expression_numeric_role_totals, state.constraint_metadata.get('constraint_expression_numeric_role_counts'))
            _counter_update_ints(state.constraint_expression_channel_totals, state.constraint_metadata.get('constraint_expression_channel_counts'))
            _counter_update_ints(state.constraint_limit_operator_totals, state.constraint_metadata.get('constraint_limit_operator_counts'))
            _counter_update_ints(state.constraint_offset_field_totals, state.constraint_metadata.get('constraint_offset_field_counts'))
            _papr_candidate_family_update(state.constraint_candidate_family_totals, state.constraint_candidate_solver_status_totals, state.constraint_candidate_family_field_totals, state.constraint_candidate_family_channel_totals, state.constraint_candidate_family_limit_totals, state.constraint_metadata.get('constraint_record_candidate_rows'))
            state.record_layout_evidence = state.constraint_metadata.get('constraint_record_layout_evidence')
            if isinstance(state.record_layout_evidence, Mapping):
                for state.status, state.count in (state.record_layout_evidence.get('layout_status_counts') or {}).items():
                    state.constraint_record_layout_status_totals[str(state.status)] += int(state.count or 0)
                for state.sequence, state.count in (state.record_layout_evidence.get('field_sequence_counts') or {}).items():
                    state.constraint_record_field_sequence_totals[str(state.sequence)] += int(state.count or 0)
                for state.status, state.count in (state.record_layout_evidence.get('gap_status_counts') or {}).items():
                    state.constraint_record_gap_status_totals[str(state.status)] += int(state.count or 0)
                for state.gap_class, state.count in (state.record_layout_evidence.get('gap_class_counts') or {}).items():
                    state.constraint_record_gap_class_totals[str(state.gap_class)] += int(state.count or 0)
                for state.status, state.count in (state.record_layout_evidence.get('gap_scalar_status_counts') or {}).items():
                    state.constraint_record_gap_scalar_status_totals[str(state.status)] += int(state.count or 0)
                for state.scalar_kind, state.count in (state.record_layout_evidence.get('gap_scalar_kind_counts') or {}).items():
                    state.constraint_record_gap_scalar_kind_totals[str(state.scalar_kind)] += int(state.count or 0)
                for state.status, state.count in (state.record_layout_evidence.get('gap_numeric_match_status_counts') or {}).items():
                    state.constraint_record_gap_numeric_match_status_totals[str(state.status)] += int(state.count or 0)
                for state.role, state.count in (state.record_layout_evidence.get('gap_numeric_match_role_counts') or {}).items():
                    state.constraint_record_gap_numeric_match_role_totals[str(state.role)] += int(state.count or 0)
                for state.scalar_kind, state.count in (state.record_layout_evidence.get('gap_numeric_match_scalar_kind_counts') or {}).items():
                    state.constraint_record_gap_numeric_match_scalar_kind_totals[str(state.scalar_kind)] += int(state.count or 0)
                for state.storage, state.count in (state.record_layout_evidence.get('gap_numeric_match_storage_counts') or {}).items():
                    state.constraint_record_gap_numeric_match_storage_totals[str(state.storage)] += int(state.count or 0)
                for state.pair, state.count in (state.record_layout_evidence.get('gap_numeric_match_pair_counts') or {}).items():
                    state.constraint_record_gap_numeric_match_pair_totals[str(state.pair)] += int(state.count or 0)
                for state.confidence, state.count in (state.record_layout_evidence.get('gap_numeric_match_value_confidence_counts') or {}).items():
                    state.constraint_record_gap_numeric_match_value_confidence_totals[str(state.confidence)] += int(state.count or 0)
                for state.family, state.count in (state.record_layout_evidence.get('gap_numeric_match_family_counts') or {}).items():
                    state.constraint_record_gap_numeric_match_family_totals[str(state.family)] += int(state.count or 0)
                for state.family, state.count in (state.record_layout_evidence.get('gap_numeric_match_family_row_counts') or {}).items():
                    state.constraint_record_gap_numeric_match_family_row_totals[str(state.family)] += int(state.count or 0)
                state.family_role_counts = state.record_layout_evidence.get('gap_numeric_match_family_role_counts')
                if isinstance(state.family_role_counts, Mapping):
                    for state.family, state.role_counts in state.family_role_counts.items():
                        if not isinstance(state.role_counts, Mapping):
                            return None
                        state.family_counter = state.constraint_record_gap_numeric_match_family_role_totals.setdefault(str(state.family), Counter())
                        for state.role, state.count in state.role_counts.items():
                            state.family_counter[str(state.role)] += int(state.count or 0)
                state.family_pair_counts = state.record_layout_evidence.get('gap_numeric_match_family_pair_counts')
                if isinstance(state.family_pair_counts, Mapping):
                    for state.family, state.pair_counts in state.family_pair_counts.items():
                        if not isinstance(state.pair_counts, Mapping):
                            return None
                        state.family_counter = state.constraint_record_gap_numeric_match_family_pair_totals.setdefault(str(state.family), Counter())
                        for state.pair, state.count in state.pair_counts.items():
                            state.family_counter[str(state.pair)] += int(state.count or 0)
                state.family_value_confidence_counts = state.record_layout_evidence.get('gap_numeric_match_family_value_confidence_counts')
                if isinstance(state.family_value_confidence_counts, Mapping):
                    for state.family, state.confidence_counts in state.family_value_confidence_counts.items():
                        if not isinstance(state.confidence_counts, Mapping):
                            return None
                        state.family_counter = state.constraint_record_gap_numeric_match_family_value_confidence_totals.setdefault(str(state.family), Counter())
                        for state.confidence, state.count in state.confidence_counts.items():
                            state.family_counter[str(state.confidence)] += int(state.count or 0)
                for state.signature, state.count in (state.record_layout_evidence.get('gap_numeric_match_signature_counts') or {}).items():
                    state.constraint_record_gap_numeric_match_signature_totals[str(state.signature)] += int(state.count or 0)
                for state.signature, state.count in (state.record_layout_evidence.get('gap_numeric_match_candidate_relative_signature_counts') or {}).items():
                    state.constraint_record_gap_numeric_match_candidate_relative_signature_totals[str(state.signature)] += int(state.count or 0)
                for state.delta, state.count in (state.record_layout_evidence.get('gap_numeric_match_previous_delta_counts') or {}).items():
                    state.constraint_record_gap_numeric_match_previous_delta_totals[str(state.delta)] += int(state.count or 0)
                for state.delta, state.count in (state.record_layout_evidence.get('gap_numeric_match_next_delta_counts') or {}).items():
                    state.constraint_record_gap_numeric_match_next_delta_totals[str(state.delta)] += int(state.count or 0)
                for state.relative_offset, state.count in (state.record_layout_evidence.get('gap_numeric_match_candidate_relative_offset_counts') or {}).items():
                    state.constraint_record_gap_numeric_match_candidate_relative_offset_totals[str(state.relative_offset)] += int(state.count or 0)
                state.constraint_record_layout_max_span_size = max(state.constraint_record_layout_max_span_size, int(state.record_layout_evidence.get('max_span_size') or 0))
                state.constraint_record_gap_pair_total += int(state.record_layout_evidence.get('gap_pair_count') or 0)
                state.constraint_record_gap_max_size = max(state.constraint_record_gap_max_size, int(state.record_layout_evidence.get('max_gap_size') or 0))
                state.constraint_record_gap_aligned_word_total += int(state.record_layout_evidence.get('gap_aligned_word_count') or 0)
                state.constraint_record_gap_scalar_candidate_total += int(state.record_layout_evidence.get('gap_scalar_candidate_count') or 0)
                state.constraint_record_gap_scalar_candidate_max = max(state.constraint_record_gap_scalar_candidate_max, int(state.record_layout_evidence.get('max_gap_scalar_candidate_count') or 0))
                state.constraint_record_gap_numeric_match_total += int(state.record_layout_evidence.get('gap_numeric_match_count') or 0)
                state.constraint_record_gap_numeric_match_max = max(state.constraint_record_gap_numeric_match_max, int(state.record_layout_evidence.get('max_gap_numeric_match_count') or 0))
                if int(state.record_layout_evidence.get('gap_numeric_match_count') or 0) > 0:
                    state.match_rows = state.record_layout_evidence.get('gap_numeric_match_rows')
                    if isinstance(state.match_rows, tuple | list):
                        for state.match_row in state.match_rows:
                            if len(state.constraint_record_gap_numeric_match_rows) >= 24:
                                break
                            if not isinstance(state.match_row, Mapping):
                                return None
                            state.sample_row = dict(state.match_row)
                            state.sample_row['path'] = entry.path
                            state.constraint_record_gap_numeric_match_rows.append(state.sample_row)
                    try:
                        state.constraint_record_gap_numeric_match_previous_deltas.extend((int(state.record_layout_evidence.get('min_gap_numeric_match_previous_delta') or 0), int(state.record_layout_evidence.get('max_gap_numeric_match_previous_delta') or 0)))
                        state.constraint_record_gap_numeric_match_next_deltas.extend((int(state.record_layout_evidence.get('min_gap_numeric_match_next_delta') or 0), int(state.record_layout_evidence.get('max_gap_numeric_match_next_delta') or 0)))
                        state.constraint_record_gap_numeric_match_candidate_relative_offsets.extend((int(state.record_layout_evidence.get('min_gap_numeric_match_candidate_relative_offset') or 0), int(state.record_layout_evidence.get('max_gap_numeric_match_candidate_relative_offset') or 0)))
                    except (TypeError, ValueError):
                        pass
                    if state.record_layout_evidence.get('gap_numeric_match_offset_confidence'):
                        state.constraint_record_gap_numeric_match_offset_confidence = str(state.record_layout_evidence.get('gap_numeric_match_offset_confidence'))
                    if state.record_layout_evidence.get('gap_numeric_match_candidate_relative_offset_confidence'):
                        state.constraint_record_gap_numeric_match_candidate_relative_offset_confidence = str(state.record_layout_evidence.get('gap_numeric_match_candidate_relative_offset_confidence'))
            state.constraint_metadata_totals['constraint_expression_numeric_values'] += int(state.constraint_metadata.get('constraint_expression_numeric_values') or 0)
        if not state.sample:
            state.sample = {'path': entry.path, 'size': len(state.data), 'decompressed': bool(state.decompressed), 'note': state.note, 'head4_hex': state.data[:4].hex(), 'head4_ascii': state.data[:4].decode('ascii', 'replace'), 'constraint_metadata': state.constraint_metadata}
    return None

def _papr_status_result(state: SimpleNamespace):
    return {'entry_count': len(state.papr_entries), 'read_ok_count': state.ok_count, 'error_count': len(state.papr_entries) - state.ok_count, 'constraint_solving_supported': False, 'constraint_metadata_totals': dict(state.constraint_metadata_totals), 'constraint_expression_role_totals': dict(state.constraint_expression_role_totals), 'constraint_expression_shape_totals': dict(state.constraint_expression_shape_totals), 'constraint_expression_syntax_signature_totals': dict(state.constraint_expression_syntax_signature_totals), 'constraint_expression_numeric_role_totals': dict(state.constraint_expression_numeric_role_totals), 'constraint_expression_channel_totals': dict(state.constraint_expression_channel_totals), 'constraint_limit_operator_totals': dict(state.constraint_limit_operator_totals), 'constraint_offset_field_totals': dict(state.constraint_offset_field_totals), 'constraint_candidate_family_totals': dict(state.constraint_candidate_family_totals), 'constraint_candidate_solver_status_totals': dict(state.constraint_candidate_solver_status_totals), 'constraint_candidate_family_field_totals': {family: dict(counter) for family, counter in sorted(state.constraint_candidate_family_field_totals.items())}, 'constraint_candidate_family_channel_totals': {family: dict(counter) for family, counter in sorted(state.constraint_candidate_family_channel_totals.items())}, 'constraint_candidate_family_limit_totals': {family: dict(counter) for family, counter in sorted(state.constraint_candidate_family_limit_totals.items())}, 'constraint_record_layout_status_totals': dict(state.constraint_record_layout_status_totals), 'constraint_record_field_sequence_totals': dict(state.constraint_record_field_sequence_totals), 'constraint_record_gap_status_totals': dict(state.constraint_record_gap_status_totals), 'constraint_record_gap_class_totals': dict(state.constraint_record_gap_class_totals), 'constraint_record_gap_scalar_status_totals': dict(state.constraint_record_gap_scalar_status_totals), 'constraint_record_gap_scalar_kind_totals': dict(state.constraint_record_gap_scalar_kind_totals), 'constraint_record_gap_numeric_match_status_totals': dict(state.constraint_record_gap_numeric_match_status_totals), 'constraint_record_gap_numeric_match_role_totals': dict(state.constraint_record_gap_numeric_match_role_totals), 'constraint_record_gap_numeric_match_scalar_kind_totals': dict(state.constraint_record_gap_numeric_match_scalar_kind_totals), 'constraint_record_gap_numeric_match_storage_totals': dict(state.constraint_record_gap_numeric_match_storage_totals), 'constraint_record_gap_numeric_match_pair_totals': dict(state.constraint_record_gap_numeric_match_pair_totals), 'constraint_record_gap_numeric_match_value_confidence_totals': dict(state.constraint_record_gap_numeric_match_value_confidence_totals), 'constraint_record_gap_numeric_match_family_totals': dict(state.constraint_record_gap_numeric_match_family_totals), 'constraint_record_gap_numeric_match_family_row_totals': dict(state.constraint_record_gap_numeric_match_family_row_totals), 'constraint_record_gap_numeric_match_family_role_totals': {family: dict(counter) for family, counter in sorted(state.constraint_record_gap_numeric_match_family_role_totals.items())}, 'constraint_record_gap_numeric_match_family_pair_totals': {family: dict(counter) for family, counter in sorted(state.constraint_record_gap_numeric_match_family_pair_totals.items())}, 'constraint_record_gap_numeric_match_family_value_confidence_totals': {family: dict(counter) for family, counter in sorted(state.constraint_record_gap_numeric_match_family_value_confidence_totals.items())}, 'constraint_record_gap_numeric_match_signature_totals': dict(state.constraint_record_gap_numeric_match_signature_totals), 'constraint_record_gap_numeric_match_candidate_relative_signature_totals': dict(state.constraint_record_gap_numeric_match_candidate_relative_signature_totals), 'constraint_record_gap_numeric_match_previous_delta_totals': dict(state.constraint_record_gap_numeric_match_previous_delta_totals), 'constraint_record_gap_numeric_match_next_delta_totals': dict(state.constraint_record_gap_numeric_match_next_delta_totals), 'constraint_record_gap_numeric_match_candidate_relative_offset_totals': dict(state.constraint_record_gap_numeric_match_candidate_relative_offset_totals), 'constraint_record_layout_max_span_size': state.constraint_record_layout_max_span_size, 'constraint_record_gap_pair_total': state.constraint_record_gap_pair_total, 'constraint_record_gap_max_size': state.constraint_record_gap_max_size, 'constraint_record_gap_aligned_word_total': state.constraint_record_gap_aligned_word_total, 'constraint_record_gap_scalar_candidate_total': state.constraint_record_gap_scalar_candidate_total, 'constraint_record_gap_scalar_candidate_max': state.constraint_record_gap_scalar_candidate_max, 'constraint_record_gap_numeric_match_total': state.constraint_record_gap_numeric_match_total, 'constraint_record_gap_numeric_match_max': state.constraint_record_gap_numeric_match_max, 'constraint_record_gap_numeric_match_rows': tuple(state.constraint_record_gap_numeric_match_rows), 'constraint_record_gap_numeric_match_min_previous_delta': min(state.constraint_record_gap_numeric_match_previous_deltas) if state.constraint_record_gap_numeric_match_previous_deltas else 0, 'constraint_record_gap_numeric_match_max_previous_delta': max(state.constraint_record_gap_numeric_match_previous_deltas) if state.constraint_record_gap_numeric_match_previous_deltas else 0, 'constraint_record_gap_numeric_match_min_next_delta': min(state.constraint_record_gap_numeric_match_next_deltas) if state.constraint_record_gap_numeric_match_next_deltas else 0, 'constraint_record_gap_numeric_match_max_next_delta': max(state.constraint_record_gap_numeric_match_next_deltas) if state.constraint_record_gap_numeric_match_next_deltas else 0, 'constraint_record_gap_numeric_match_min_candidate_relative_offset': min(state.constraint_record_gap_numeric_match_candidate_relative_offsets) if state.constraint_record_gap_numeric_match_candidate_relative_offsets else 0, 'constraint_record_gap_numeric_match_max_candidate_relative_offset': max(state.constraint_record_gap_numeric_match_candidate_relative_offsets) if state.constraint_record_gap_numeric_match_candidate_relative_offsets else 0, 'constraint_record_gap_numeric_match_offset_confidence': state.constraint_record_gap_numeric_match_offset_confidence, 'constraint_record_gap_numeric_match_candidate_relative_offset_confidence': state.constraint_record_gap_numeric_match_candidate_relative_offset_confidence, 'constraint_analysis_errors': tuple(state.analysis_errors), 'status_counts': dict(state.status_counts), 'examples': state.examples, 'sample': state.sample}

def _real_archive_papr_read_status(entries: Sequence[ArchiveEntry]) -> dict[str, object]:
    papr_entries = [entry for entry in entries if str(entry.extension or '').lower() == '.papr']
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    status_counts: Counter[str] = Counter()
    constraint_metadata_totals: Counter[str] = Counter()
    constraint_expression_role_totals: Counter[str] = Counter()
    constraint_expression_shape_totals: Counter[str] = Counter()
    constraint_expression_syntax_signature_totals: Counter[str] = Counter()
    constraint_expression_numeric_role_totals: Counter[str] = Counter()
    constraint_expression_channel_totals: Counter[str] = Counter()
    constraint_limit_operator_totals: Counter[str] = Counter()
    constraint_offset_field_totals: Counter[str] = Counter()
    constraint_candidate_family_totals: Counter[str] = Counter()
    constraint_candidate_solver_status_totals: Counter[str] = Counter()
    constraint_candidate_family_field_totals: dict[str, Counter[str]] = {}
    constraint_candidate_family_channel_totals: dict[str, Counter[str]] = {}
    constraint_candidate_family_limit_totals: dict[str, Counter[str]] = {}
    constraint_record_layout_status_totals: Counter[str] = Counter()
    constraint_record_field_sequence_totals: Counter[str] = Counter()
    constraint_record_gap_status_totals: Counter[str] = Counter()
    constraint_record_gap_class_totals: Counter[str] = Counter()
    constraint_record_gap_scalar_status_totals: Counter[str] = Counter()
    constraint_record_gap_scalar_kind_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_status_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_role_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_scalar_kind_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_storage_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_pair_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_value_confidence_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_family_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_family_row_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_family_role_totals: dict[str, Counter[str]] = {}
    constraint_record_gap_numeric_match_family_pair_totals: dict[str, Counter[str]] = {}
    constraint_record_gap_numeric_match_family_value_confidence_totals: dict[str, Counter[str]] = {}
    constraint_record_gap_numeric_match_signature_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_candidate_relative_signature_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_previous_delta_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_next_delta_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_candidate_relative_offset_totals: Counter[str] = Counter()
    constraint_record_gap_numeric_match_previous_deltas: list[int] = []
    constraint_record_gap_numeric_match_next_deltas: list[int] = []
    constraint_record_gap_numeric_match_candidate_relative_offsets: list[int] = []
    constraint_record_gap_numeric_match_rows: list[dict[str, object]] = []
    constraint_record_gap_numeric_match_offset_confidence = ''
    constraint_record_gap_numeric_match_candidate_relative_offset_confidence = ''
    constraint_record_layout_max_span_size = 0
    constraint_record_gap_pair_total = 0
    constraint_record_gap_max_size = 0
    constraint_record_gap_aligned_word_total = 0
    constraint_record_gap_scalar_candidate_total = 0
    constraint_record_gap_scalar_candidate_max = 0
    constraint_record_gap_numeric_match_total = 0
    constraint_record_gap_numeric_match_max = 0
    examples: dict[str, str] = {}
    sample: dict[str, object] = {}
    analysis_errors: list[dict[str, str]] = []
    ok_count = 0
    state = SimpleNamespace(**locals())
    for entry in papr_entries:
        _papr_process_entry(state, entry)
    return _papr_status_result(state)

def _counter_update_ints(counter: Counter[str], values: object) -> None:
    if not isinstance(values, Mapping):
        return
    for key, value in values.items():
        counter[str(key)] += int(value or 0)

def _papr_candidate_family_update(family_totals: Counter[str], solver_status_totals: Counter[str], family_field_totals: dict[str, Counter[str]], family_channel_totals: dict[str, Counter[str]], family_limit_totals: dict[str, Counter[str]], rows: object) -> None:
    if not isinstance(rows, tuple | list):
        return
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        family = str(row.get('constraint_type') or 'constraint_candidate')
        family_totals[family] += 1
        solver_status_totals[str(row.get('solver_status') or 'blocked')] += 1
        field_totals = family_field_totals.setdefault(family, Counter())
        for field, label in (('target_bone', 'target'), ('helper_bone', 'helper'), ('parent_bone', 'parent'), ('expression', 'expression')):
            if str(row.get(field) or '').strip():
                field_totals[label] += 1
        channel_totals = family_channel_totals.setdefault(family, Counter())
        for channel in row.get('expression_channels') or ():
            channel_totals[str(channel)] += 1
        limit_totals = family_limit_totals.setdefault(family, Counter())
        for operator in row.get('limit_operators') or ():
            limit_totals[str(operator)] += 1

def _papr_constraint_metadata_summary(data: bytes, entry: ArchiveEntry, *, entries_by_path: Mapping[str, Sequence[ArchiveEntry]] | None=None, entries_by_basename: Mapping[str, Sequence[ArchiveEntry]] | None=None) -> dict[str, object]:
    try:
        document = build_binary_sidecar_analysis_document(data, entry.path, extension='.papr', source_entry=entry, archive_entries_by_normalized_path=entries_by_path if entries_by_path is not None else None, archive_entries_by_basename=entries_by_basename if entries_by_basename is not None else None)
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}
    summary = document.get('summary', {}) if isinstance(document.get('summary'), Mapping) else {}
    container = document.get('container', {}) if isinstance(document.get('container'), Mapping) else {}
    editing = document.get('editing', {}) if isinstance(document.get('editing'), Mapping) else {}
    papr = document.get('papr', {}) if isinstance(document.get('papr'), Mapping) else {}
    expression_evidence = papr.get('expression_evidence') if isinstance(papr.get('expression_evidence'), Mapping) else {}
    offset_evidence = papr.get('offset_evidence') if isinstance(papr.get('offset_evidence'), Mapping) else {}
    record_layout_evidence = papr.get('record_layout_evidence') if isinstance(papr.get('record_layout_evidence'), Mapping) else {}
    return {'container_family': str(container.get('recognized_family') or 'unknown'), 'schema_declarations': int(summary.get('schema_declarations') or 0), 'schema_declared_members': int(summary.get('schema_declared_members') or 0), 'field_like_identifiers': int(summary.get('field_like_identifiers') or 0), 'asset_reference_hints': int(summary.get('asset_reference_hints') or 0), 'offset_candidates': int(summary.get('offset_candidates') or 0), 'count_offset_pair_candidates': int(summary.get('count_offset_pair_candidates') or 0), 'float_vector_candidates': int(summary.get('float_vector_candidates') or 0), 'related_file_rows': int(summary.get('related_file_rows') or 0), 'related_files_resolved': int(summary.get('related_files_resolved') or 0), 'constraint_string_evidence': int(papr.get('string_evidence_count') or 0), 'constraint_record_candidates': int(papr.get('record_candidate_count') or 0), 'constraint_record_candidate_rows': tuple(papr.get('record_candidates') or ()), 'constraint_record_layout_evidence': dict(record_layout_evidence), 'constraint_record_gap_status_counts': dict(record_layout_evidence.get('gap_status_counts') or {}) if isinstance(record_layout_evidence.get('gap_status_counts'), Mapping) else {}, 'constraint_record_gap_class_counts': dict(record_layout_evidence.get('gap_class_counts') or {}) if isinstance(record_layout_evidence.get('gap_class_counts'), Mapping) else {}, 'constraint_record_gap_scalar_status_counts': dict(record_layout_evidence.get('gap_scalar_status_counts') or {}) if isinstance(record_layout_evidence.get('gap_scalar_status_counts'), Mapping) else {}, 'constraint_record_gap_scalar_kind_counts': dict(record_layout_evidence.get('gap_scalar_kind_counts') or {}) if isinstance(record_layout_evidence.get('gap_scalar_kind_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_status_counts': dict(record_layout_evidence.get('gap_numeric_match_status_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_status_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_role_counts': dict(record_layout_evidence.get('gap_numeric_match_role_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_role_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_scalar_kind_counts': dict(record_layout_evidence.get('gap_numeric_match_scalar_kind_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_scalar_kind_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_storage_counts': dict(record_layout_evidence.get('gap_numeric_match_storage_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_storage_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_pair_counts': dict(record_layout_evidence.get('gap_numeric_match_pair_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_pair_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_value_confidence_counts': dict(record_layout_evidence.get('gap_numeric_match_value_confidence_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_value_confidence_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_family_counts': dict(record_layout_evidence.get('gap_numeric_match_family_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_family_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_family_row_counts': dict(record_layout_evidence.get('gap_numeric_match_family_row_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_family_row_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_family_role_counts': dict(record_layout_evidence.get('gap_numeric_match_family_role_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_family_role_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_family_pair_counts': dict(record_layout_evidence.get('gap_numeric_match_family_pair_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_family_pair_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_family_value_confidence_counts': dict(record_layout_evidence.get('gap_numeric_match_family_value_confidence_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_family_value_confidence_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_signature_counts': dict(record_layout_evidence.get('gap_numeric_match_signature_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_signature_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_candidate_relative_signature_counts': dict(record_layout_evidence.get('gap_numeric_match_candidate_relative_signature_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_candidate_relative_signature_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_previous_delta_counts': dict(record_layout_evidence.get('gap_numeric_match_previous_delta_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_previous_delta_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_next_delta_counts': dict(record_layout_evidence.get('gap_numeric_match_next_delta_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_next_delta_counts'), Mapping) else {}, 'constraint_record_gap_numeric_match_candidate_relative_offset_counts': dict(record_layout_evidence.get('gap_numeric_match_candidate_relative_offset_counts') or {}) if isinstance(record_layout_evidence.get('gap_numeric_match_candidate_relative_offset_counts'), Mapping) else {}, 'constraint_record_gap_pair_count': int(record_layout_evidence.get('gap_pair_count') or 0), 'constraint_record_gap_max_size': int(record_layout_evidence.get('max_gap_size') or 0), 'constraint_record_gap_aligned_word_count': int(record_layout_evidence.get('gap_aligned_word_count') or 0), 'constraint_record_gap_scalar_candidate_count': int(record_layout_evidence.get('gap_scalar_candidate_count') or 0), 'constraint_record_gap_scalar_candidate_max': int(record_layout_evidence.get('max_gap_scalar_candidate_count') or 0), 'constraint_record_gap_numeric_match_count': int(record_layout_evidence.get('gap_numeric_match_count') or 0), 'constraint_record_gap_numeric_match_max': int(record_layout_evidence.get('max_gap_numeric_match_count') or 0), 'constraint_record_gap_numeric_match_rows': tuple(record_layout_evidence.get('gap_numeric_match_rows') or ()), 'constraint_record_gap_numeric_match_min_previous_delta': int(record_layout_evidence.get('min_gap_numeric_match_previous_delta') or 0), 'constraint_record_gap_numeric_match_max_previous_delta': int(record_layout_evidence.get('max_gap_numeric_match_previous_delta') or 0), 'constraint_record_gap_numeric_match_min_next_delta': int(record_layout_evidence.get('min_gap_numeric_match_next_delta') or 0), 'constraint_record_gap_numeric_match_max_next_delta': int(record_layout_evidence.get('max_gap_numeric_match_next_delta') or 0), 'constraint_record_gap_numeric_match_min_candidate_relative_offset': int(record_layout_evidence.get('min_gap_numeric_match_candidate_relative_offset') or 0), 'constraint_record_gap_numeric_match_max_candidate_relative_offset': int(record_layout_evidence.get('max_gap_numeric_match_candidate_relative_offset') or 0), 'constraint_record_gap_numeric_match_offset_confidence': str(record_layout_evidence.get('gap_numeric_match_offset_confidence') or ''), 'constraint_record_gap_numeric_match_candidate_relative_offset_confidence': str(record_layout_evidence.get('gap_numeric_match_candidate_relative_offset_confidence') or ''), 'constraint_expression_evidence': dict(expression_evidence), 'constraint_expression_role_counts': dict(expression_evidence.get('expression_role_counts') or {}) if isinstance(expression_evidence.get('expression_role_counts'), Mapping) else {}, 'constraint_expression_shape_counts': dict(expression_evidence.get('shape_counts') or {}) if isinstance(expression_evidence.get('shape_counts'), Mapping) else {}, 'constraint_expression_syntax_signature_counts': dict(expression_evidence.get('syntax_signature_counts') or {}) if isinstance(expression_evidence.get('syntax_signature_counts'), Mapping) else {}, 'constraint_expression_numeric_role_counts': dict(expression_evidence.get('numeric_role_counts') or {}) if isinstance(expression_evidence.get('numeric_role_counts'), Mapping) else {}, 'constraint_expression_channel_counts': dict(expression_evidence.get('channel_counts') or {}) if isinstance(expression_evidence.get('channel_counts'), Mapping) else {}, 'constraint_limit_operator_counts': dict(expression_evidence.get('limit_operator_counts') or {}) if isinstance(expression_evidence.get('limit_operator_counts'), Mapping) else {}, 'constraint_expression_numeric_values': int(expression_evidence.get('numeric_value_count') or 0), 'constraint_offset_evidence': dict(offset_evidence), 'constraint_offset_field_counts': {'target': int(offset_evidence.get('target_offset_count') or 0), 'helper': int(offset_evidence.get('helper_offset_count') or 0), 'parent': int(offset_evidence.get('parent_offset_count') or 0)}, 'constraint_role_counts': dict(papr.get('role_counts') or {}) if isinstance(papr.get('role_counts'), Mapping) else {}, 'constraint_related_physics': len(papr.get('related_physics_rows') or ()), 'constraint_evidence_status': str(papr.get('status') or 'no_constraint_evidence_recovered'), 'editing_supported': bool(editing.get('supported')), 'constraint_solving_supported': False, 'status': 'read_only_schema_recovery'}

def _papr_constraint_evidence_for_path(entries_by_path: Mapping[str, Sequence[ArchiveEntry]], entries_by_basename: Mapping[str, Sequence[ArchiveEntry]], path: object) -> dict[str, object]:
    entry = _entry_by_archive_path(entries_by_path, path)
    if entry is None:
        return {}
    try:
        return _papr_constraint_metadata_summary(_read_archive_payload(entry), entry, entries_by_path=entries_by_path, entries_by_basename=entries_by_basename)
    except Exception:
        return {}
