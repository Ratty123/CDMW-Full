from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Tuple

from cdmw.core.archive_hkx_types import HkxItemRecord, HkxTagItem, HkxTypeInfo


NativeSummaryParts = Tuple[
    List[HkxTagItem],
    List[str],
    List[HkxTypeInfo],
    Optional[int],
    List[str],
    List[HkxItemRecord],
    List[str],
    List[Dict[str, object]],
    List[Dict[str, object]],
    Dict[str, object],
    Dict[str, object],
    Dict[str, object],
    Dict[str, object],
    Dict[str, object],
    Dict[str, object],
    Dict[str, object],
    Dict[str, object],
    Dict[str, object],
    Dict[str, object],
    Dict[str, object],
    Dict[str, object],
    Dict[str, object],
    Dict[str, object],
    Dict[str, object],
]

_NATIVE_MAPPING_KEYS = (
    "tagfile_reference_fixups",
    "fixup_semantics_report",
    "native_model_graph",
    "hard_internal_evidence",
    "real_hkclass_metadata",
    "real_hkclass_metadata_v2",
    "fixup_semantics_v2",
    "semantic_model_v1",
    "semantic_writer_gate_v1",
    "edit_candidate_map_v1",
    "hkx_edit_gate_v1",
    "class_decoder_evidence_v2",
    "decoder_evidence_v2",
    "modding_readiness",
    "no_edit_binary_writer",
)


def _native_mapping(native: Mapping[str, object], key: str) -> Dict[str, object]:
    value = native.get(key)
    return dict(value or {}) if isinstance(value, Mapping) else {}


def _native_tag_items(native: Mapping[str, object]) -> List[HkxTagItem]:
    return [
        HkxTagItem(
            name=str(item.get("name") or ""),
            offset=int(item.get("offset")),
            length_word_offset=(int(item["length_word_offset"]) if item.get("length_word_offset") is not None else None),
            raw_length_word=(int(item["raw_length_word"]) if item.get("raw_length_word") is not None else None),
            declared_length=(int(item["declared_length"]) if item.get("declared_length") is not None else None),
            length_flags=(int(item["length_flags"]) if item.get("length_flags") is not None else None),
            marker_end_offset=(int(item["marker_end_offset"]) if item.get("marker_end_offset") is not None else None),
            word_end_offset=(int(item["word_end_offset"]) if item.get("word_end_offset") is not None else None),
        )
        for item in native.get("tag_items", [])  # type: ignore[union-attr]
        if isinstance(item, Mapping) and item.get("offset") is not None
    ]


def _native_type_infos(native: Mapping[str, object]) -> List[HkxTypeInfo]:
    return [
        HkxTypeInfo(
            index=int(item.get("index")),
            name=str(item.get("name") or ""),
            template_parameters=[
                (str(parameter.get("name") or ""), int(parameter.get("value") or 0))
                for parameter in item.get("template_parameters", [])
                if isinstance(parameter, Mapping)
            ],
        )
        for item in native.get("type_infos", [])  # type: ignore[union-attr]
        if isinstance(item, Mapping) and item.get("index") is not None
    ]


def _native_item_records(native: Mapping[str, object]) -> List[HkxItemRecord]:
    return [
        HkxItemRecord(
            index=int(item.get("index")),
            raw_type_flags=int(item.get("raw_type_flags") or 0),
            type_index=int(item.get("type_index") or 0),
            flags=int(item.get("flags") or 0),
            data_offset=int(item.get("data_offset") or 0),
            absolute_data_offset=(int(item["absolute_data_offset"]) if item.get("absolute_data_offset") is not None else None),
            count=int(item.get("count") or 0),
            type_name=str(item.get("type_name") or ""),
        )
        for item in native.get("item_records", [])  # type: ignore[union-attr]
        if isinstance(item, Mapping) and item.get("index") is not None
    ]


def _hkx_native_summary_parts(data: bytes) -> Optional[NativeSummaryParts]:
    try:
        from cdmw.core.hkx_native import parse_hkx_summary_with_rust
    except Exception:
        return None
    native = parse_hkx_summary_with_rust(data)
    if not isinstance(native, Mapping):
        return None
    try:
        tag_items = _native_tag_items(native)
        string_table_names = [str(name) for name in native.get("string_table_names", []) if str(name)]  # type: ignore[union-attr]
        type_infos = _native_type_infos(native)
        declared_type_name_count = (
            int(native["declared_type_name_count"])
            if native.get("declared_type_name_count") is not None
            else None
        )
        type_names = [str(name) for name in native.get("type_names", []) if str(name)]  # type: ignore[union-attr]
        item_records = _native_item_records(native)
        warnings = [str(warning) for warning in native.get("warnings", []) if str(warning)]  # type: ignore[union-attr]
        object_records = [dict(item) for item in native.get("object_records", []) if isinstance(item, Mapping)]  # type: ignore[union-attr]
        tuning_groups = [dict(item) for item in native.get("physics_tuning_groups", []) if isinstance(item, Mapping)]  # type: ignore[union-attr]
        mappings = tuple(_native_mapping(native, key) for key in _NATIVE_MAPPING_KEYS)
    except (TypeError, ValueError):
        return None
    if not tag_items:
        return None
    return (
        tag_items,
        string_table_names,
        type_infos,
        declared_type_name_count,
        type_names,
        item_records,
        warnings,
        object_records,
        tuning_groups,
        *mappings,
    )
