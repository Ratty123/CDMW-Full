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


def _summary_mapping(report: Mapping[str, object]) -> Mapping[str, object]:
    summary = report.get('summary')
    return summary if isinstance(summary, Mapping) else {}


def _merge_coverage(reports: Sequence[Mapping[str, object]], *, files_discovered: int) -> tuple[bool, list[dict[str, int]], list[str]]:
    ranges: list[tuple[int, int, int]] = []
    errors: list[str] = []
    for report_index, report in enumerate(reports):
        summary = _summary_mapping(report)
        offset = max(0, int(summary.get('scan_offset') or 0))
        scanned = max(0, int(summary.get('files_scanned') or 0))
        scan_count = summary.get('scan_count')
        if summary.get('discovery_limited') is True:
            errors.append(f'Report {report_index} used discovery_limit and cannot prove full corpus coverage.')
        if scan_count is None and scanned < files_discovered:
            errors.append(f'Report {report_index} is a sample report, not a contiguous shard.')
        if scan_count is not None and scanned > int(scan_count):
            errors.append(f'Report {report_index} scanned more rows than its declared shard count.')
        ranges.append((offset, offset + scanned, report_index))
    cursor = 0
    for start, end, report_index in sorted(ranges):
        if start != cursor:
            errors.append(f'Report {report_index} covers [{start}, {end}); expected start {cursor}.')
            cursor = max(cursor, end)
            continue
        cursor = end
    if cursor != files_discovered:
        errors.append(f'Merged shard coverage ends at {cursor}; expected {files_discovered}.')
    coverage_ranges = [{'start': start, 'end': end, 'report_index': report_index} for start, end, report_index in sorted(ranges)]
    return (not errors and files_discovered > 0, coverage_ranges, errors)


def merge_prefab_json_import_corpus_reports(reports: Sequence[Mapping[str, object]]) -> dict[str, object]:
    valid_reports = [report for report in reports if isinstance(report, Mapping)]
    if not valid_reports:
        return _report_from_rows([], source_type='merged_reports', source_paths=[], files_discovered=0, discovery_limit=None, detail_scan_limit=None, edit_probes_enabled=False)
    first = valid_reports[0]
    source_type = str(first.get('source_type') or 'merged_reports')
    source_paths = [str(path) for path in first.get('source_paths') or []]
    first_summary = _summary_mapping(first)
    files_discovered = int(first_summary.get('files_discovered') or 0)
    edit_probes_enabled = first_summary.get('edit_probes_enabled') is True
    compatibility_errors: list[str] = []
    rows: list[Mapping[str, object]] = []
    for index, report in enumerate(valid_reports):
        if report.get('format') != PREFAB_JSON_IMPORT_CORPUS_FORMAT:
            compatibility_errors.append(f'Report {index} has unsupported format.')
        if str(report.get('source_type') or '') != source_type:
            compatibility_errors.append(f'Report {index} source_type differs.')
        if [str(path) for path in report.get('source_paths') or []] != source_paths:
            compatibility_errors.append(f'Report {index} source_paths differ.')
        summary = _summary_mapping(report)
        if int(summary.get('files_discovered') or 0) != files_discovered:
            compatibility_errors.append(f'Report {index} files_discovered differs.')
        if (summary.get('edit_probes_enabled') is True) != edit_probes_enabled:
            compatibility_errors.append(f'Report {index} edit probe mode differs.')
        report_rows = report.get('rows')
        if isinstance(report_rows, list):
            rows.extend((row for row in report_rows if isinstance(row, Mapping)))
        else:
            compatibility_errors.append(f'Report {index} has no rows array.')
    coverage_complete, coverage_ranges, coverage_errors = _merge_coverage(valid_reports, files_discovered=files_discovered)
    errors = compatibility_errors + coverage_errors
    report = _report_from_rows(rows, source_type=source_type, source_paths=source_paths, files_discovered=files_discovered, discovery_limit=None, detail_scan_limit=None, scan_offset=0, scan_count=files_discovered if coverage_complete else None, edit_probes_enabled=edit_probes_enabled)
    summary = report['summary']
    if isinstance(summary, dict):
        summary['merged_report_count'] = len(valid_reports)
        summary['coverage_complete'] = coverage_complete and (not compatibility_errors)
        summary['coverage_ranges'] = coverage_ranges
        summary['coverage_errors'] = errors
        summary['discovery_limited'] = any((_summary_mapping(report).get('discovery_limited') is True for report in valid_reports))
        summary['all_discovered_files_scanned'] = bool(summary['coverage_complete'])
    gate = report['gate']
    if isinstance(gate, dict):
        gate['full_corpus_no_edit_rebuild_ready'] = (bool(summary.get('coverage_complete')) if isinstance(summary, Mapping) else False) and gate.get('full_corpus_no_edit_rebuild_ready') is True
        if not gate['full_corpus_no_edit_rebuild_ready']:
            blockers = list(gate.get('length_changing_blockers') or [])
            if 'full-corpus no-edit rebuild has not been run' not in blockers:
                blockers.append('full-corpus no-edit rebuild has not been run')
            gate['length_changing_blockers'] = blockers
    return report


def _report_from_rows(rows: Sequence[Mapping[str, object]], *, source_type: str, source_paths: Sequence[str], files_discovered: int, discovery_limit: Optional[int], detail_scan_limit: Optional[int], scan_offset: int=0, scan_count: Optional[int]=None, edit_probes_enabled: bool) -> dict[str, object]:
    from cdmw.core.prefab_corpus_report_output_1 import _build_report_document
    from cdmw.core.prefab_corpus_report_stages_0 import _report_from_rows_stage_0, _report_from_rows_stage_1, _report_from_rows_stage_2, _report_from_rows_stage_3
    from cdmw.core.prefab_corpus_report_stages_0 import _report_from_rows_stage_4, _report_from_rows_stage_5
    from cdmw.core.prefab_corpus_report_stages_1 import _report_from_rows_stage_6, _report_from_rows_stage_7, _report_from_rows_stage_8, _report_from_rows_stage_9
    state = dict(locals())
    state.update(_report_from_rows_stage_0(state))
    state.update(_report_from_rows_stage_1(state))
    state.update(_report_from_rows_stage_2(state))
    state.update(_report_from_rows_stage_3(state))
    state.update(_report_from_rows_stage_4(state))
    state.update(_report_from_rows_stage_5(state))
    state.update(_report_from_rows_stage_6(state))
    state.update(_report_from_rows_stage_7(state))
    state.update(_report_from_rows_stage_8(state))
    state.update(_report_from_rows_stage_9(state))
    return _build_report_document(state)
