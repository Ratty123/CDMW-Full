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


def _build_report_gate_part_0(state) -> dict[str, object]:
    result = {}
    result.update({'same_length_import_ready': state['same_length_import_ready']})
    result.update({'layout_no_edit_rebuild_ready': state['layout_rebuild_ready']})
    result.update({'json_layout_no_edit_rebuild_ready': state['json_layout_rebuild_ready']})
    result.update({'same_length_resource_edit_probe_ready': state['same_length_resource_edit_ready']})
    result.update({'same_length_placement_edit_probe_ready': state['same_length_placement_edit_ready']})
    result.update({'experimental_length_change_rebuild_probe_ready': state['experimental_length_change_rebuild_ready']})
    result.update({'experimental_placement_length_change_rebuild_probe_ready': state['experimental_placement_length_change_rebuild_ready']})
    result.update({'full_corpus_no_edit_rebuild_ready': state['full_corpus_no_edit_rebuild_ready']})
    result.update({'length_changing_import_ready': state['length_changing_import_ready']})
    result.update({'length_changing_failed_subgates': state['length_changing_failed_subgates']})
    result.update({'resource_resize_offset_gate_ready': state['resource_resize_offset_gate_ready']})
    result.update({'placement_resize_offset_gate_ready': state['placement_resize_offset_gate_ready']})
    result.update({'resize_offset_validator_ready': state['resize_offset_validator_ready']})
    result.update({'resource_effective_resize_offset_model_ready': state['resource_effective_resize_offset_model_ready']})
    result.update({'placement_effective_resize_offset_model_ready': state['placement_effective_resize_offset_model_ready']})
    result.update({'effective_resize_offset_model_ready': state['effective_resize_offset_model_ready']})
    result.update({'array_count_hint_semantics_proven': state['array_count_hint_semantics_proven']})
    result.update({'descriptor_word3_semantics_proven': state['descriptor_word3_semantics_proven']})
    result.update({'descriptor_count_semantics_proven': state['descriptor_count_semantics_proven']})
    result.update({'descriptor_count_mutation_proven': state['descriptor_count_mutation_proven']})
    result.update({'descriptor_value_editing_ready': state['descriptor_value_editing_ready']})
    result.update({'transform_payload_layout_proven': state['transform_payload_layout_proven']})
    result.update({'transform_value_semantics_proven': state['transform_value_semantics_proven']})
    result.update({'transform_value_mutation_proven': state['transform_value_mutation_proven']})
    result.update({'transform_value_editing_ready': state['transform_value_editing_ready']})
    result.update({'array_payload_layout_proven': state['array_payload_layout_proven']})
    result.update({'array_count_mutation_proven': state['array_count_mutation_proven']})
    result.update({'array_resizing_ready': state['array_resizing_ready']})
    result.update({'unknown_block_edit_semantics_proven': state['unknown_block_edit_semantics_proven']})
    result.update({'reference_descriptor_edit_semantics_proven': state['reference_descriptor_edit_semantics_proven']})
    result.update({'unknown_reference_preservation_ready': state['unknown_reference_preservation_ready']})
    result.update({'length_changing_blockers': state['length_changing_blockers']})
    result.update({'length_changing_blocker_detail_counts': dict(sorted(state['length_changing_blocker_detail_counts'].items()))})
    result.update({'reason': 'No-edit proof passed; edit probes were disabled for this report.' if state['proof_ready'] and state['layout_rebuild_ready'] and state['json_layout_rebuild_ready'] and (not state['edit_probes_enabled']) else 'Same-length import has corpus no-edit and fixed-size edit proof for scanned files.' if state['proof_ready'] and state['layout_rebuild_ready'] and state['json_layout_rebuild_ready'] and state['same_length_resource_edit_ready'] and (state['placement_probe_failed'] == 0) else 'No corpus proof yet; scan representative real prefabs before enabling UI import.'})
    return result


def _build_report_gate(state) -> dict[str, object]:
    result: dict[str, object] = {}
    result.update(_build_report_gate_part_0(state))
    return result


def _build_report_document(state) -> dict[str, object]:
    from cdmw.core.prefab_corpus_report_output_0 import _build_report_summary
    _prefab_result = {}
    _prefab_result.update({'document': 'Crimson Desert Mod Workbench prefab JSON import corpus report.', 'format': PREFAB_JSON_IMPORT_CORPUS_FORMAT})
    _prefab_result.update({'source_type': state['source_type'], 'source_paths': list(state['source_paths'])})
    _prefab_result.update({'summary': _build_report_summary(state), 'gate': _build_report_gate(state)})
    _prefab_result.update({'rows': list(state['rows'])})
    return _prefab_result
