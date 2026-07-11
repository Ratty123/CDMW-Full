from __future__ import annotations

import hashlib
import math
import re
import struct
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.constants import ARCHIVE_BINARY_HEX_PREVIEW_LIMIT
from cdmw.domain.archives.format import try_decode_text_like_archive_data
from cdmw.models import ArchiveEntry, ArchiveModelTextureReference
from cdmw.core.archive_extraction import format_byte_size
from cdmw.core.archive_filtering import (
    _STRUCTURED_BINARY_ASSET_REFERENCE_EXTENSIONS,
    _STRUCTURED_BINARY_ASSET_SEGMENT_RE,
    _STRUCTURED_BINARY_ASSET_TOKEN_RE,
    _STRUCTURED_BINARY_IDENTIFIER_RE,
)
from cdmw.core.archive_format import (
    _ARCHIVE_ANIMATION_SEQUENCE_EXTENSIONS,
    _PRINTABLE_BINARY_STRING_RE,
)
from cdmw.core.archive_model_references import (
    _BinarySidecarStringRecord,
    _find_archive_model_related_entries,
    _normalize_model_texture_reference,
)
from cdmw.core.upscale_profiles import parse_texture_sidecar_bindings


from cdmw.core.archive_binary_preview_common_0 import (
    format_binary_header_preview,
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
)
from cdmw.core.archive_binary_preview_paa_0 import (
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
)
from cdmw.core.archive_binary_preview_format_0 import (
    _seqmt_analysis_document,
    _paccd_analysis_document,
)
from cdmw.core.archive_binary_preview_sidecar_0 import (
    _binary_sidecar_offset_candidates,
    _binary_sidecar_count_offset_pairs,
    _is_binary_sidecar_plausible_float,
    _binary_sidecar_float_rows,
    _decode_binary_sidecar_half_float,
    _is_binary_sidecar_plausible_half_float,
    _binary_sidecar_animation_keyframe_tables,
    _looks_like_binary_sidecar_declared_type,
    _binary_sidecar_descriptor_likely_kind,
    _binary_sidecar_descriptor_confidence,
    _binary_sidecar_schema_declarations,
    _build_grouped_schema_declaration_lines,
    _binary_sidecar_container_summary,
    _binary_sidecar_kind_label,
    _build_binary_sidecar_related_references,
    _binary_sidecar_reference_document_rows,
)
from cdmw.core.archive_binary_preview_paseq_0 import (
    _paseq_sequence_stem,
    _paseq_reference_role,
    _paseq_timeline_field_role,
    _paseq_timeline_field_rows,
    _paseq_event_marker_rows,
    _paseq_timing_candidate_rows,
    _paseq_fps_candidate_value_rows,
    _paseq_fps_candidate_context,
    _paseq_blend_candidate_value_rows,
    _paseq_length_prefixed_ascii,
    _paseq_timing_evidence,
    _paseq_blend_field_kind,
    _paseq_timeline_lane_rows,
    _paseq_playback_readiness,
    _paseq_analysis_document,
)
from cdmw.core.archive_binary_preview_papr_0 import (
    _papr_constraint_string_role,
    _papr_constraint_expression_evidence,
    _papr_constraint_expression_syntax_signature,
    _papr_constraint_expression_shape,
    _papr_constraint_expression_numeric_roles,
    _papr_limit_tail_start,
    _previous_non_space,
    _papr_constraint_expression_summary,
    _papr_constraint_offset_summary,
    _papr_constraint_analysis_document,
    _papr_constraint_record_candidates,
    _papr_candidate_span,
    _papr_candidate_field_sequence,
    _papr_gap_numeric_match_signature,
    _papr_expression_numeric_entries,
    _papr_gap_numeric_matches,
    _papr_gap_class,
    _papr_gap_status,
    _papr_gap_scalar_kind,
)
from cdmw.core.archive_binary_preview_groups_0 import (
    _group_prefab_field_name,
    _binary_sidecar_group_func_for_extension,
    _group_model_property_header_field_name,
    _group_character_customization_field_name,
    _group_seqmt_field_name,
    _group_world_field_name,
    _group_rig_variant_field_name,
    _build_grouped_structured_section_lines,
)

def _prefab_evidence_rows(*args, **kwargs):
    from cdmw.core.archive_structured_preview import _prefab_evidence_rows as owner

    return owner(*args, **kwargs)


def _prefab_material_override_evidence_rows(*args, **kwargs):
    from cdmw.core.archive_structured_preview import _prefab_material_override_evidence_rows as owner

    return owner(*args, **kwargs)


def build_archive_related_file_references(*args, **kwargs):
    from cdmw.core.archive_references import build_archive_related_file_references as owner

    return owner(*args, **kwargs)


def build_archive_relationship_references(*args, **kwargs):
    from cdmw.core.archive_references import build_archive_relationship_references as owner

    return owner(*args, **kwargs)


def merge_archive_reference_rows(*args, **kwargs):
    from cdmw.core.archive_references import merge_archive_reference_rows as owner

    return owner(*args, **kwargs)


_PAA_METABIN_TOKEN_HINTS: Dict[str, Tuple[str, str]] = {
    "nor": ("Motion state", "normal"),
    "abn": ("Motion state", "abnormal / reaction"),
    "dam": ("Action", "damage / hit reaction"),
    "atk": ("Action", "attack"),
    "skill": ("Action", "skill"),
    "move": ("Motion", "movement"),
    "idle": ("Motion", "idle"),
    "std": ("Pose", "standing"),
    "sit": ("Pose", "sitting"),
    "run": ("Motion", "running"),
    "walk": ("Motion", "walking"),
    "jump": ("Motion", "jump"),
    "upper": ("Body region", "upper body"),
    "lower": ("Body region", "lower body"),
    "stt": ("Timeline phase", "start"),
    "ing": ("Timeline phase", "in progress / loop body"),
    "end": ("Timeline phase", "end"),
    "loop": ("Timeline phase", "loop"),
    "f": ("Direction", "forward"),
    "b": ("Direction", "back"),
    "l": ("Direction", "left"),
    "r": ("Direction", "right"),
    "fd": ("Direction", "forward-down"),
    "fu": ("Direction", "forward-up"),
    "cvst": ("Scene use", "conversation / cutscene-style"),
    "quest": ("Scene use", "quest sequence"),
    "camera": ("Scene use", "camera animation"),
}


_BINARY_SIDECAR_DECL_IDENTIFIER_RE = re.compile(rb"[A-Za-z_][A-Za-z0-9_]{2,127}")
_BINARY_SIDECAR_PRIMITIVE_TYPES = {
    "bool",
    "float",
    "float2",
    "float3",
    "float4",
    "int",
    "int16",
    "int32",
    "uint16",
    "uint32",
}
_BINARY_SIDECAR_STRING_TYPES = {"staticstringa", "indexedstringa", "normalizedpatha"}
_BINARY_SIDECAR_KNOWN_TYPE_CODES = {0, 1, 2, 3, 4, 5, 7, 10}


_PASEQ_TIMELINE_FIELD_TOKENS = (
    "animation",
    "clip",
    "duration",
    "end",
    "event",
    "frame",
    "key",
    "loop",
    "phase",
    "sequence",
    "start",
    "time",
    "timeline",
    "track",
    "trigger",
)
_PASEQ_EFFECT_FIELD_TOKENS = ("effect", "emitter", "particle", "sound", "seqmt", "visibility")
_PASEQ_SCENE_FIELD_TOKENS = ("camera", "object", "prefab", "scene", "stage", "target")


_PAPR_EXPRESSION_CHANNEL_RE = re.compile(r"\bLocal_(?:Euler|Quat|Position)_[XYZW]\b", re.IGNORECASE)
_PAPR_LIMIT_OPERATOR_RE = re.compile(r"\b(?:amin|amax)\b", re.IGNORECASE)
_PAPR_EXPRESSION_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.])-?\d+(?:\.\d+)?")
_PAPR_ABS_OPERATOR_RE = re.compile(r"\babs\b", re.IGNORECASE)


def _papr_constraint_record_layout_summary(candidates: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    if not candidates:
        return {}
    layout_counts: Counter[str] = Counter()
    field_sequence_counts: Counter[str] = Counter()
    gap_status_counts: Counter[str] = Counter()
    gap_class_counts: Counter[str] = Counter()
    gap_scalar_status_counts: Counter[str] = Counter()
    gap_scalar_kind_counts: Counter[str] = Counter()
    gap_numeric_match_status_counts: Counter[str] = Counter()
    gap_numeric_match_role_counts: Counter[str] = Counter()
    gap_numeric_match_scalar_kind_counts: Counter[str] = Counter()
    gap_numeric_match_storage_counts: Counter[str] = Counter()
    gap_numeric_match_pair_counts: Counter[str] = Counter()
    gap_numeric_match_value_confidence_counts: Counter[str] = Counter()
    gap_numeric_match_family_counts: Counter[str] = Counter()
    gap_numeric_match_family_row_counts: Counter[str] = Counter()
    gap_numeric_match_family_role_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    gap_numeric_match_family_pair_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    gap_numeric_match_family_value_confidence_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    gap_numeric_match_signature_counts: Counter[str] = Counter()
    gap_numeric_match_candidate_relative_signature_counts: Counter[str] = Counter()
    gap_numeric_match_previous_delta_counts: Counter[str] = Counter()
    gap_numeric_match_next_delta_counts: Counter[str] = Counter()
    gap_numeric_match_candidate_relative_offset_counts: Counter[str] = Counter()
    gap_numeric_match_previous_deltas: List[int] = []
    gap_numeric_match_next_deltas: List[int] = []
    gap_numeric_match_candidate_relative_offsets: List[int] = []
    gap_numeric_match_rows: List[Dict[str, object]] = []
    span_sizes: List[int] = []
    gap_pair_count = 0
    max_gap_size = 0
    gap_aligned_word_count = 0
    gap_scalar_candidate_count = 0
    max_gap_scalar_candidate_count = 0
    gap_numeric_match_count = 0
    max_gap_numeric_match_count = 0
    for row in candidates:
        layout_status = str(row.get("record_layout_status") or "unknown")
        layout_counts[layout_status] += 1
        field_sequence = tuple(str(value) for value in row.get("record_field_sequence") or () if str(value))
        if field_sequence:
            field_sequence_counts[">".join(field_sequence)] += 1
        gap_status = str(row.get("record_gap_status") or "")
        if gap_status:
            gap_status_counts[gap_status] += 1
        for gap_class in row.get("record_gap_classes") or ():
            gap_class_counts[str(gap_class)] += 1
        gap_pair_count += int(row.get("record_gap_count") or 0)
        max_gap_size = max(max_gap_size, int(row.get("record_gap_max_size") or 0))
        gap_scalar_status = str(row.get("record_gap_scalar_status") or "")
        if gap_scalar_status:
            gap_scalar_status_counts[gap_scalar_status] += 1
        scalar_kind_counts = row.get("record_gap_scalar_kind_counts")
        if isinstance(scalar_kind_counts, Mapping):
            for scalar_kind, count in scalar_kind_counts.items():
                gap_scalar_kind_counts[str(scalar_kind)] += int(count or 0)
        gap_aligned_word_count += int(row.get("record_gap_aligned_word_count") or 0)
        candidate_scalar_count = int(row.get("record_gap_scalar_candidate_count") or 0)
        gap_scalar_candidate_count += candidate_scalar_count
        max_gap_scalar_candidate_count = max(max_gap_scalar_candidate_count, candidate_scalar_count)
        match_status = str(row.get("record_gap_numeric_match_status") or "")
        if match_status:
            gap_numeric_match_status_counts[match_status] += 1
        match_role_counts = row.get("record_gap_numeric_match_role_counts")
        if isinstance(match_role_counts, Mapping):
            for role, count in match_role_counts.items():
                gap_numeric_match_role_counts[str(role)] += int(count or 0)
        match_scalar_kind_counts = row.get("record_gap_numeric_match_scalar_kind_counts")
        if isinstance(match_scalar_kind_counts, Mapping):
            for scalar_kind, count in match_scalar_kind_counts.items():
                gap_numeric_match_scalar_kind_counts[str(scalar_kind)] += int(count or 0)
        match_storage_counts = row.get("record_gap_numeric_match_storage_counts")
        if isinstance(match_storage_counts, Mapping):
            for storage, count in match_storage_counts.items():
                gap_numeric_match_storage_counts[str(storage)] += int(count or 0)
        match_pair_counts = row.get("record_gap_numeric_match_pair_counts")
        if isinstance(match_pair_counts, Mapping):
            for pair, count in match_pair_counts.items():
                gap_numeric_match_pair_counts[str(pair)] += int(count or 0)
        match_value_confidence_counts = row.get("record_gap_numeric_match_value_confidence_counts")
        if isinstance(match_value_confidence_counts, Mapping):
            for confidence, count in match_value_confidence_counts.items():
                gap_numeric_match_value_confidence_counts[str(confidence)] += int(count or 0)
        match_previous_delta_counts = row.get("record_gap_numeric_match_previous_delta_counts")
        if isinstance(match_previous_delta_counts, Mapping):
            for delta, count in match_previous_delta_counts.items():
                gap_numeric_match_previous_delta_counts[str(delta)] += int(count or 0)
        match_next_delta_counts = row.get("record_gap_numeric_match_next_delta_counts")
        if isinstance(match_next_delta_counts, Mapping):
            for delta, count in match_next_delta_counts.items():
                gap_numeric_match_next_delta_counts[str(delta)] += int(count or 0)
        match_candidate_relative_offset_counts = row.get(
            "record_gap_numeric_match_candidate_relative_offset_counts"
        )
        if isinstance(match_candidate_relative_offset_counts, Mapping):
            for offset, count in match_candidate_relative_offset_counts.items():
                gap_numeric_match_candidate_relative_offset_counts[str(offset)] += int(count or 0)
        candidate_match_count = int(row.get("record_gap_numeric_match_count") or 0)
        gap_numeric_match_count += candidate_match_count
        max_gap_numeric_match_count = max(max_gap_numeric_match_count, candidate_match_count)
        if candidate_match_count > 0:
            family = str(row.get("constraint_type") or "constraint_candidate")
            gap_numeric_match_family_counts[family] += candidate_match_count
            gap_numeric_match_family_row_counts[family] += 1
            if isinstance(match_role_counts, Mapping):
                for role, count in match_role_counts.items():
                    gap_numeric_match_family_role_counts[family][str(role)] += int(count or 0)
            if isinstance(match_pair_counts, Mapping):
                for pair, count in match_pair_counts.items():
                    gap_numeric_match_family_pair_counts[family][str(pair)] += int(count or 0)
            if isinstance(match_value_confidence_counts, Mapping):
                for confidence, count in match_value_confidence_counts.items():
                    gap_numeric_match_family_value_confidence_counts[family][str(confidence)] += int(count or 0)
            match_signature_counts = row.get("record_gap_numeric_match_signature_counts")
            if isinstance(match_signature_counts, Mapping):
                for signature, count in match_signature_counts.items():
                    gap_numeric_match_signature_counts[f"family={family}|{signature}"] += int(count or 0)
            match_candidate_relative_signature_counts = row.get(
                "record_gap_numeric_match_candidate_relative_signature_counts"
            )
            if isinstance(match_candidate_relative_signature_counts, Mapping):
                for signature, count in match_candidate_relative_signature_counts.items():
                    gap_numeric_match_candidate_relative_signature_counts[
                        f"family={family}|{signature}"
                    ] += int(count or 0)
            match_rows = row.get("record_gap_numeric_match_rows")
            if isinstance(match_rows, tuple | list):
                for match_row in match_rows:
                    if len(gap_numeric_match_rows) >= 16:
                        break
                    if not isinstance(match_row, Mapping):
                        continue
                    candidate_offset = int(row.get("offset") or 0)
                    match_offset = int(match_row.get("offset") or 0)
                    candidate_relative_offset = match_row.get("candidate_relative_offset")
                    if candidate_relative_offset is None and candidate_offset > 0 and match_offset > 0:
                        candidate_relative_offset = match_offset - candidate_offset
                    gap_numeric_match_rows.append(
                        {
                            "candidate_offset": candidate_offset,
                            "constraint_type": family,
                            "expression": str(row.get("expression") or ""),
                            "match_offset": match_offset,
                            "candidate_relative_offset": int(candidate_relative_offset or 0),
                            "between_fields": str(match_row.get("between_fields") or ""),
                            "numeric_value": str(match_row.get("numeric_value") or ""),
                            "numeric_role": str(match_row.get("numeric_role") or ""),
                            "storage": str(match_row.get("storage") or ""),
                            "scalar_kind": str(match_row.get("scalar_kind") or ""),
                            "scalar_value": match_row.get("scalar_value"),
                            "previous_field_end_delta": int(match_row.get("previous_field_end_delta") or 0),
                            "next_field_start_delta": int(match_row.get("next_field_start_delta") or 0),
                            "value_confidence": str(match_row.get("value_confidence") or ""),
                            "match_signature": f"family={family}|{str(match_row.get('match_signature') or '')}",
                            "candidate_relative_match_signature": (
                                f"family={family}|{str(match_row.get('candidate_relative_match_signature') or '')}"
                                if match_row.get("candidate_relative_match_signature")
                                else ""
                            ),
                        }
                    )
            try:
                gap_numeric_match_previous_deltas.append(int(row.get("record_gap_numeric_match_min_previous_delta") or 0))
                gap_numeric_match_previous_deltas.append(int(row.get("record_gap_numeric_match_max_previous_delta") or 0))
                gap_numeric_match_next_deltas.append(int(row.get("record_gap_numeric_match_min_next_delta") or 0))
                gap_numeric_match_next_deltas.append(int(row.get("record_gap_numeric_match_max_next_delta") or 0))
                gap_numeric_match_candidate_relative_offsets.append(
                    int(row.get("record_gap_numeric_match_min_candidate_relative_offset") or 0)
                )
                gap_numeric_match_candidate_relative_offsets.append(
                    int(row.get("record_gap_numeric_match_max_candidate_relative_offset") or 0)
                )
            except (TypeError, ValueError):
                pass
        span_size = int(row.get("record_span_size") or 0)
        if span_size > 0:
            span_sizes.append(span_size)
    return {
        "status": "nearby_string_span_layout_evidence",
        "confidence": "inferred_nearby_string_order",
        "field_sequence_confidence": "proven_decoded_string_offset_order",
        "field_sequence_counts": dict(sorted(field_sequence_counts.items())),
        "layout_status_counts": dict(sorted(layout_counts.items())),
        "gap_status_counts": dict(sorted(gap_status_counts.items())),
        "gap_class_counts": dict(sorted(gap_class_counts.items())),
        "gap_scalar_status_counts": dict(sorted(gap_scalar_status_counts.items())),
        "gap_scalar_kind_counts": dict(sorted(gap_scalar_kind_counts.items())),
        "gap_numeric_match_status_counts": dict(sorted(gap_numeric_match_status_counts.items())),
        "gap_numeric_match_role_counts": dict(sorted(gap_numeric_match_role_counts.items())),
        "gap_numeric_match_scalar_kind_counts": dict(sorted(gap_numeric_match_scalar_kind_counts.items())),
        "gap_numeric_match_storage_counts": dict(sorted(gap_numeric_match_storage_counts.items())),
        "gap_numeric_match_pair_counts": dict(sorted(gap_numeric_match_pair_counts.items())),
        "gap_numeric_match_value_confidence_counts": dict(sorted(gap_numeric_match_value_confidence_counts.items())),
        "gap_numeric_match_family_counts": dict(sorted(gap_numeric_match_family_counts.items())),
        "gap_numeric_match_family_row_counts": dict(sorted(gap_numeric_match_family_row_counts.items())),
        "gap_numeric_match_family_role_counts": {
            family: dict(sorted(counts.items()))
            for family, counts in sorted(gap_numeric_match_family_role_counts.items())
        },
        "gap_numeric_match_family_pair_counts": {
            family: dict(sorted(counts.items()))
            for family, counts in sorted(gap_numeric_match_family_pair_counts.items())
        },
        "gap_numeric_match_family_value_confidence_counts": {
            family: dict(sorted(counts.items()))
            for family, counts in sorted(gap_numeric_match_family_value_confidence_counts.items())
        },
        "gap_numeric_match_signature_counts": dict(sorted(gap_numeric_match_signature_counts.items())),
        "gap_numeric_match_candidate_relative_signature_counts": dict(
            sorted(gap_numeric_match_candidate_relative_signature_counts.items())
        ),
        "gap_numeric_match_previous_delta_counts": dict(sorted(gap_numeric_match_previous_delta_counts.items())),
        "gap_numeric_match_next_delta_counts": dict(sorted(gap_numeric_match_next_delta_counts.items())),
        "gap_numeric_match_candidate_relative_offset_counts": dict(
            sorted(gap_numeric_match_candidate_relative_offset_counts.items())
        ),
        "gap_numeric_match_offset_confidence": (
            "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven"
            if gap_numeric_match_count
            else ""
        ),
        "gap_numeric_match_candidate_relative_offset_confidence": (
            "observed_relative_to_inferred_candidate_offset_value_layout_unproven"
            if gap_numeric_match_candidate_relative_offset_counts
            else ""
        ),
        "gap_pair_count": int(gap_pair_count),
        "max_gap_size": int(max_gap_size),
        "gap_aligned_word_count": int(gap_aligned_word_count),
        "gap_scalar_candidate_count": int(gap_scalar_candidate_count),
        "max_gap_scalar_candidate_count": int(max_gap_scalar_candidate_count),
        "gap_numeric_match_count": int(gap_numeric_match_count),
        "max_gap_numeric_match_count": int(max_gap_numeric_match_count),
        "gap_numeric_match_rows": tuple(gap_numeric_match_rows),
        "min_gap_numeric_match_previous_delta": min(gap_numeric_match_previous_deltas) if gap_numeric_match_previous_deltas else 0,
        "max_gap_numeric_match_previous_delta": max(gap_numeric_match_previous_deltas) if gap_numeric_match_previous_deltas else 0,
        "min_gap_numeric_match_next_delta": min(gap_numeric_match_next_deltas) if gap_numeric_match_next_deltas else 0,
        "max_gap_numeric_match_next_delta": max(gap_numeric_match_next_deltas) if gap_numeric_match_next_deltas else 0,
        "min_gap_numeric_match_candidate_relative_offset": (
            min(gap_numeric_match_candidate_relative_offsets) if gap_numeric_match_candidate_relative_offsets else 0
        ),
        "max_gap_numeric_match_candidate_relative_offset": (
            max(gap_numeric_match_candidate_relative_offsets) if gap_numeric_match_candidate_relative_offsets else 0
        ),
        "candidate_count": len(candidates),
        "min_span_size": min(span_sizes) if span_sizes else 0,
        "max_span_size": max(span_sizes) if span_sizes else 0,
    }


def _papr_candidate_gap_evidence(
    data: bytes,
    *fields: Tuple[str, Mapping[str, object] | None],
    candidate_offset: int = 0,
    expression_numeric_values: Sequence[object] = (),
    expression_numeric_roles: Sequence[object] = (),
) -> Dict[str, object]:
    ordered: List[Tuple[int, int, str, str]] = []
    for index, (label, row) in enumerate(fields):
        if row is None:
            continue
        offset = int(row.get("offset") or 0)
        text = str(row.get("text") or "")
        if offset <= 0 or not text:
            continue
        ordered.append((offset, index, label, text))
    ordered.sort()
    gap_classes: List[str] = []
    gap_sizes: List[int] = []
    scalar_kind_counts: Counter[str] = Counter()
    numeric_match_role_counts: Counter[str] = Counter()
    numeric_match_scalar_kind_counts: Counter[str] = Counter()
    numeric_match_storage_counts: Counter[str] = Counter()
    numeric_match_pair_counts: Counter[str] = Counter()
    numeric_match_value_confidence_counts: Counter[str] = Counter()
    numeric_match_signature_counts: Counter[str] = Counter()
    numeric_match_candidate_relative_signature_counts: Counter[str] = Counter()
    numeric_match_previous_delta_counts: Counter[str] = Counter()
    numeric_match_next_delta_counts: Counter[str] = Counter()
    numeric_match_candidate_relative_offset_counts: Counter[str] = Counter()
    numeric_match_previous_deltas: List[int] = []
    numeric_match_next_deltas: List[int] = []
    numeric_match_candidate_relative_offsets: List[int] = []
    numeric_match_rows: List[Dict[str, object]] = []
    numeric_entries = _papr_expression_numeric_entries(expression_numeric_values, expression_numeric_roles)
    aligned_word_count = 0
    scalar_candidate_count = 0
    for current, following in zip(ordered, ordered[1:]):
        offset, _index, label, text = current
        next_offset, _next_index, next_label, _next_text = following
        end = offset + len(text.encode("ascii", errors="ignore")) + 1
        raw_gap_size = next_offset - end
        if raw_gap_size < 0:
            gap_class = "overlap_or_shared_string"
            gap_size = 0
        elif raw_gap_size == 0:
            gap_class = "contiguous_strings"
            gap_size = 0
        else:
            chunk = data[end:next_offset] if data else b""
            gap_class = _papr_gap_class(chunk)
            gap_size = raw_gap_size
            aligned_offset = (end + 3) & ~3
            while aligned_offset + 4 <= next_offset and aligned_offset + 4 <= len(data):
                word = struct.unpack_from("<I", data, aligned_offset)[0]
                float_value = struct.unpack_from("<f", data, aligned_offset)[0]
                scalar_kind = _papr_gap_scalar_kind(word, float_value)
                aligned_word_count += 1
                if scalar_kind != "opaque_word":
                    scalar_kind_counts[scalar_kind] += 1
                    scalar_candidate_count += 1
                    for numeric_match in _papr_gap_numeric_matches(
                        word,
                        float_value,
                        numeric_entries,
                        scalar_kind=scalar_kind,
                    ):
                        pair = f"{label}>{next_label}"
                        previous_delta = int(aligned_offset - end)
                        next_delta = int(next_offset - (aligned_offset + 4))
                        candidate_relative_offset = int(aligned_offset - candidate_offset) if candidate_offset > 0 else 0
                        numeric_role = str(numeric_match["numeric_role"])
                        value_confidence = str(
                            numeric_match.get("value_confidence")
                            or "numeric_match_value_layout_unproven"
                        )
                        match_signature = _papr_gap_numeric_match_signature(
                            numeric_role=numeric_role,
                            pair=pair,
                            storage=str(numeric_match["storage"]),
                            scalar_kind=scalar_kind,
                            value_confidence=value_confidence,
                            previous_delta=previous_delta,
                            next_delta=next_delta,
                        )
                        candidate_relative_match_signature = (
                            f"{match_signature}|rel={candidate_relative_offset}"
                            if candidate_offset > 0
                            else ""
                        )
                        numeric_match_role_counts[numeric_role] += 1
                        numeric_match_scalar_kind_counts[scalar_kind] += 1
                        numeric_match_storage_counts[str(numeric_match["storage"])] += 1
                        numeric_match_pair_counts[pair] += 1
                        numeric_match_value_confidence_counts[value_confidence] += 1
                        numeric_match_signature_counts[match_signature] += 1
                        if candidate_relative_match_signature:
                            numeric_match_candidate_relative_signature_counts[
                                candidate_relative_match_signature
                            ] += 1
                        numeric_match_previous_delta_counts[str(previous_delta)] += 1
                        numeric_match_next_delta_counts[str(next_delta)] += 1
                        if candidate_offset > 0:
                            numeric_match_candidate_relative_offset_counts[str(candidate_relative_offset)] += 1
                            numeric_match_candidate_relative_offsets.append(candidate_relative_offset)
                        numeric_match_previous_deltas.append(previous_delta)
                        numeric_match_next_deltas.append(next_delta)
                        if len(numeric_match_rows) < 8:
                            numeric_match_rows.append(
                                {
                                    "offset": int(aligned_offset),
                                    "between_fields": pair,
                                    "previous_field_end_delta": previous_delta,
                                    "next_field_start_delta": next_delta,
                                    "candidate_relative_offset": candidate_relative_offset,
                                    **numeric_match,
                                    "value_confidence": value_confidence,
                                    "match_signature": match_signature,
                                    "candidate_relative_match_signature": candidate_relative_match_signature,
                                }
                            )
                aligned_offset += 4
        gap_classes.append(gap_class)
        gap_sizes.append(gap_size)
    gap_class_counts = dict(sorted(Counter(gap_classes).items()))
    numeric_match_count = int(sum(numeric_match_role_counts.values()))
    return {
        "record_gap_status": _papr_gap_status(gap_classes),
        "record_gap_classes": tuple(gap_classes),
        "record_gap_class_counts": gap_class_counts,
        "record_gap_count": len(gap_classes),
        "record_gap_total_size": int(sum(gap_sizes)),
        "record_gap_max_size": max(gap_sizes) if gap_sizes else 0,
        "record_gap_confidence": "observed_between_decoded_string_offsets" if gap_classes else "",
        "record_gap_scalar_status": "unbound_interfield_scalar_candidates" if scalar_candidate_count else "no_interfield_scalar_candidates",
        "record_gap_scalar_kind_counts": dict(sorted(scalar_kind_counts.items())),
        "record_gap_aligned_word_count": int(aligned_word_count),
        "record_gap_scalar_candidate_count": int(scalar_candidate_count),
        "record_gap_scalar_confidence": "unbound_aligned_interfield_gap_scan" if aligned_word_count else "",
        "record_gap_numeric_match_status": "unbound_scalar_numeric_constant_matches" if numeric_match_count else "no_scalar_numeric_constant_matches",
        "record_gap_numeric_match_role_counts": dict(sorted(numeric_match_role_counts.items())),
        "record_gap_numeric_match_scalar_kind_counts": dict(sorted(numeric_match_scalar_kind_counts.items())),
        "record_gap_numeric_match_storage_counts": dict(sorted(numeric_match_storage_counts.items())),
        "record_gap_numeric_match_pair_counts": dict(sorted(numeric_match_pair_counts.items())),
        "record_gap_numeric_match_value_confidence_counts": dict(sorted(numeric_match_value_confidence_counts.items())),
        "record_gap_numeric_match_signature_counts": dict(sorted(numeric_match_signature_counts.items())),
        "record_gap_numeric_match_candidate_relative_signature_counts": dict(
            sorted(numeric_match_candidate_relative_signature_counts.items())
        ),
        "record_gap_numeric_match_previous_delta_counts": dict(sorted(numeric_match_previous_delta_counts.items())),
        "record_gap_numeric_match_next_delta_counts": dict(sorted(numeric_match_next_delta_counts.items())),
        "record_gap_numeric_match_candidate_relative_offset_counts": dict(
            sorted(numeric_match_candidate_relative_offset_counts.items())
        ),
        "record_gap_numeric_match_count": numeric_match_count,
        "record_gap_numeric_match_rows": tuple(numeric_match_rows),
        "record_gap_numeric_match_min_previous_delta": min(numeric_match_previous_deltas) if numeric_match_previous_deltas else 0,
        "record_gap_numeric_match_max_previous_delta": max(numeric_match_previous_deltas) if numeric_match_previous_deltas else 0,
        "record_gap_numeric_match_min_next_delta": min(numeric_match_next_deltas) if numeric_match_next_deltas else 0,
        "record_gap_numeric_match_max_next_delta": max(numeric_match_next_deltas) if numeric_match_next_deltas else 0,
        "record_gap_numeric_match_min_candidate_relative_offset": (
            min(numeric_match_candidate_relative_offsets) if numeric_match_candidate_relative_offsets else 0
        ),
        "record_gap_numeric_match_max_candidate_relative_offset": (
            max(numeric_match_candidate_relative_offsets) if numeric_match_candidate_relative_offsets else 0
        ),
        "record_gap_numeric_match_offset_confidence": (
            "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven"
            if numeric_match_count
            else ""
        ),
        "record_gap_numeric_match_candidate_relative_offset_confidence": (
            "observed_relative_to_inferred_candidate_offset_value_layout_unproven"
            if numeric_match_count and candidate_offset > 0
            else ""
        ),
        "record_gap_numeric_match_confidence": "exact_numeric_text_vs_interfield_scalar_match_value_layout_unproven" if numeric_match_count else "",
    }


from cdmw.core.archive_binary_preview_analysis import (
    build_binary_sidecar_analysis_document,
    build_binary_sidecar_analysis_json,
)


from cdmw.core.archive_binary_preview_corpus import (
    _BINARY_SIDECAR_CORPUS_EXTENSIONS,
    _binary_sidecar_corpus_path_label,
    _binary_sidecar_descriptor_is_unknown,
    _build_binary_sidecar_corpus_extension_report,
    _discover_binary_sidecar_corpus_paths,
    _select_balanced_binary_sidecar_detail_paths,
    build_binary_sidecar_corpus_json,
    build_binary_sidecar_corpus_report,
)
