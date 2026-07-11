from __future__ import annotations

import re
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_hkx_types import HkxItemRecord, HkxTagItem, HkxTagfileSummary, HkxTypeInfo


_HKX_PRINTABLE_SCAN_LIMIT = 262_144
_HKX_PRINTABLE_STRING_LIMIT = 160
_HKX_KNOWN_TAG_SECTIONS = ("TAG0", "SDKV", "DATA", "TYPE", "TNA1", "TPAD", "INDX", "ITEM", "PTCH")
_HKX_TAG_ITEM_MARKERS = ("SDKV", "DATA", "TYPE", "MTTP", "TST1", "TNA1", "TPAD", "INDX", "ITEM", "PTCH")
_HKX_TYPE_NAME_RE = re.compile(r"hk[a-zA-Z][a-zA-Z0-9_:]*")


def _hkx_sdk_version_label(version: str) -> str:
    if len(version) == 8 and version.isdigit():
        year = int(version[:4])
        major = int(version[4:6])
        patch = int(version[6:8])
        if 1999 <= year <= 2100:
            return f"{year}.{major}.{patch}"
    return version


def _extract_hkx_printable_strings(data: bytes) -> List[str]:
    printable = []
    current = bytearray()
    for value in data[:_HKX_PRINTABLE_SCAN_LIMIT]:
        if 32 <= value <= 126:
            current.append(value)
            continue
        if len(current) >= 4:
            printable.append(current.decode("ascii", errors="ignore"))
            if len(printable) >= _HKX_PRINTABLE_STRING_LIMIT:
                break
        current.clear()
    if len(current) >= 4 and len(printable) < _HKX_PRINTABLE_STRING_LIMIT:
        printable.append(current.decode("ascii", errors="ignore"))
    return printable


def _extract_hkx_type_names(printable: Sequence[str]) -> List[str]:
    names: set[str] = set()
    for text in printable:
        for match in _HKX_TYPE_NAME_RE.finditer(text):
            names.add(match.group(0))
    return sorted(names)


def _detect_hkx_tag_sections(data: bytes) -> List[str]:
    return [section for section in _HKX_KNOWN_TAG_SECTIONS if section.encode("ascii") in data[:_HKX_PRINTABLE_SCAN_LIMIT]]


def _detect_hkx_sdk_version(data: bytes, printable: Sequence[str]) -> str:
    match = re.search(rb"SDKV([0-9]{8})", data[:4096])
    if match:
        return match.group(1).decode("ascii", errors="ignore")
    for text in printable[:16]:
        match_text = re.search(r"SDKV([0-9]{8})", text)
        if match_text:
            return match_text.group(1)
    return ""


def _detect_hkx_declared_size(data: bytes) -> Optional[int]:
    if len(data) < 4:
        return None
    declared_size = int.from_bytes(data[:4], "big", signed=False)
    if declared_size == len(data):
        return declared_size
    return None


def _decode_hkx_length_word(raw_length_word: int) -> Tuple[int, int]:
    return raw_length_word & 0x0FFFFFFF, raw_length_word & 0xF0000000


def _find_hkx_tag_items(data: bytes) -> List[HkxTagItem]:
    items: List[HkxTagItem] = []
    tag0_offset = data[:64].find(b"TAG0")
    if tag0_offset >= 0:
        items.append(HkxTagItem(name="TAG0", offset=tag0_offset))

    seen: set[Tuple[str, int]] = set()
    for marker in _HKX_TAG_ITEM_MARKERS:
        marker_bytes = marker.encode("ascii")
        start = 0
        while True:
            offset = data.find(marker_bytes, start)
            if offset < 0:
                break
            start = offset + 1
            if offset < 4:
                continue
            raw_length_word = int.from_bytes(data[offset - 4 : offset], "big", signed=False)
            declared_length, length_flags = _decode_hkx_length_word(raw_length_word)
            if declared_length <= 0:
                continue
            marker_end = offset + declared_length
            word_end = offset - 4 + declared_length
            if marker_end > len(data) + 4 and word_end > len(data):
                continue
            if (marker, offset) in seen:
                continue
            seen.add((marker, offset))
            items.append(
                HkxTagItem(
                    name=marker,
                    offset=offset,
                    length_word_offset=offset - 4,
                    raw_length_word=raw_length_word,
                    declared_length=declared_length,
                    length_flags=length_flags,
                    marker_end_offset=marker_end,
                    word_end_offset=word_end,
                )
            )
    return sorted(items, key=lambda item: item.offset)


def _hkx_tag_item_by_name(items: Sequence[HkxTagItem], name: str) -> Optional[HkxTagItem]:
    return next((item for item in items if item.name == name), None)


def _hkx_next_tag_item(items: Sequence[HkxTagItem], item: HkxTagItem) -> Optional[HkxTagItem]:
    later_items = [candidate for candidate in items if candidate.offset > item.offset]
    return later_items[0] if later_items else None


def _extract_hkx_tst1_type_names(data: bytes, items: Sequence[HkxTagItem]) -> List[str]:
    tst1 = _hkx_tag_item_by_name(items, "TST1")
    if tst1 is None:
        return []
    next_item = _hkx_next_tag_item(items, tst1)
    end_candidates = []
    if tst1.marker_end_offset is not None:
        end_candidates.append(tst1.marker_end_offset)
    if next_item is not None and next_item.length_word_offset is not None:
        end_candidates.append(next_item.length_word_offset)
    elif next_item is not None:
        end_candidates.append(next_item.offset)
    end = min((candidate for candidate in end_candidates if candidate > tst1.offset), default=len(data))
    blob = data[tst1.offset + 4 : max(tst1.offset + 4, min(end, len(data)))]
    names: List[str] = []
    for raw_name in blob.split(b"\0"):
        if not raw_name or raw_name == b"\xff":
            continue
        name = raw_name.decode("ascii", errors="ignore").strip()
        if name and name != "\xff":
            names.append(name)
    return names


def _read_hkx_var_uint(payload: bytes, offset: int) -> Tuple[int, int]:
    if offset >= len(payload):
        raise ValueError("Unexpected end of Havok packed integer stream.")
    byte_1 = payload[offset]
    offset += 1
    if byte_1 & 0b10000000 == 0:
        return byte_1 & 0b01111111, offset
    if byte_1 == 0b11000011:
        if offset + 2 > len(payload):
            raise ValueError("Truncated Havok packed integer.")
        return (payload[offset] << 8) | payload[offset + 1], offset + 2
    marker = byte_1 >> 3
    if 0b00010000 <= marker < 0b00011000:
        if offset >= len(payload):
            raise ValueError("Truncated Havok packed integer.")
        return 0b00111111_11111111 & ((byte_1 << 8) | payload[offset]), offset + 1
    if 0b00011000 <= marker < 0b00011100:
        if offset + 2 > len(payload):
            raise ValueError("Truncated Havok packed integer.")
        return 0b00011111_11111111_11111111 & (
            (byte_1 << 16) | (payload[offset] << 8) | payload[offset + 1]
        ), offset + 2
    if marker == 0b00011100:
        if offset + 3 > len(payload):
            raise ValueError("Truncated Havok packed integer.")
        return int.from_bytes(bytes((byte_1,)) + payload[offset : offset + 3], "little") & 0x07FFFFFF, offset + 3
    if marker == 0b00011101:
        if offset + 4 > len(payload):
            raise ValueError("Truncated Havok packed integer.")
        return (
            0b00000111_11111111_11111111_11111111_11111111
            & (
                (byte_1 << 32)
                | (payload[offset] << 24)
                | (payload[offset + 1] << 16)
                | (payload[offset + 2] << 8)
                | payload[offset + 3]
            ),
            offset + 4,
        )
    if marker == 0b00011110:
        if offset + 7 > len(payload):
            raise ValueError("Truncated Havok packed integer.")
        return int.from_bytes(bytes((byte_1,)) + payload[offset : offset + 7], "little") & 0x07FFFFFFFFFFFFFF, offset + 7
    raise ValueError(f"Unrecognized Havok packed integer marker byte 0x{byte_1:02X}.")


def _parse_hkx_tna1_type_infos(
    data: bytes,
    items: Sequence[HkxTagItem],
    string_table_names: Sequence[str],
) -> Tuple[Optional[int], List[HkxTypeInfo], List[str]]:
    tna1 = _hkx_tag_item_by_name(items, "TNA1")
    if tna1 is None or tna1.offset + 4 >= len(data):
        return None, [], []
    if tna1.word_end_offset is not None and tna1.word_end_offset <= len(data):
        payload_end = tna1.word_end_offset
    elif tna1.marker_end_offset is not None and tna1.marker_end_offset <= len(data):
        payload_end = tna1.marker_end_offset
    else:
        next_item = _hkx_next_tag_item(items, tna1)
        payload_end = next_item.length_word_offset if next_item and next_item.length_word_offset else len(data)
    payload = data[tna1.offset + 4 : max(tna1.offset + 4, min(payload_end, len(data)))]
    if not payload:
        return None, [], []
    warnings: List[str] = []
    try:
        declared_count, cursor = _read_hkx_var_uint(payload, 0)
    except ValueError as exc:
        return None, [], [f"Could not decode TNA1 type count: {exc}"]
    type_infos: List[HkxTypeInfo] = []
    for index in range(1, declared_count):
        try:
            name_index, cursor = _read_hkx_var_uint(payload, cursor)
            template_count, cursor = _read_hkx_var_uint(payload, cursor)
            name = string_table_names[name_index] if name_index < len(string_table_names) else f"type-string[{name_index}]"
            template_parameters: List[Tuple[str, int]] = []
            for _ in range(template_count):
                template_name_index, cursor = _read_hkx_var_uint(payload, cursor)
                template_value, cursor = _read_hkx_var_uint(payload, cursor)
                template_name = (
                    string_table_names[template_name_index]
                    if template_name_index < len(string_table_names)
                    else f"template-string[{template_name_index}]"
                )
                template_parameters.append((template_name, template_value))
        except ValueError as exc:
            warnings.append(f"Could not fully decode TNA1 type {index}: {exc}")
            break
        type_infos.append(HkxTypeInfo(index=index, name=name, template_parameters=template_parameters))
    if cursor < len(payload) and any(value != 0 for value in payload[cursor:]):
        warnings.append(f"TNA1 has {len(payload) - cursor:,} undecoded non-zero trailing byte(s).")
    return declared_count, type_infos, warnings


def _extract_hkx_declared_type_name_count(data: bytes, items: Sequence[HkxTagItem]) -> Optional[int]:
    tna1 = _hkx_tag_item_by_name(items, "TNA1")
    if tna1 is None or tna1.offset + 4 >= len(data):
        return None
    return int(data[tna1.offset + 4])


def _detect_hkx_data_payload_offset(items: Sequence[HkxTagItem]) -> Optional[int]:
    data_item = _hkx_tag_item_by_name(items, "DATA")
    if data_item is None:
        return None
    return data_item.offset + 4


def _parse_hkx_item_records(
    data: bytes,
    items: Sequence[HkxTagItem],
    type_names_by_index: Mapping[int, str],
) -> List[HkxItemRecord]:
    item = _hkx_tag_item_by_name(items, "ITEM")
    if item is None:
        return []
    data_payload_offset = _detect_hkx_data_payload_offset(items)
    record_start = item.offset + 16
    if item.word_end_offset is not None and item.word_end_offset <= len(data):
        record_end = item.word_end_offset
    elif item.marker_end_offset is not None and item.marker_end_offset <= len(data):
        record_end = item.marker_end_offset
    else:
        record_end = len(data)
    if record_start >= record_end:
        return []
    usable_length = record_end - record_start
    records: List[HkxItemRecord] = []
    for index in range(usable_length // 12):
        offset = record_start + index * 12
        raw_type_flags = int.from_bytes(data[offset : offset + 4], "little", signed=False)
        data_offset = int.from_bytes(data[offset + 4 : offset + 8], "little", signed=False)
        count = int.from_bytes(data[offset + 8 : offset + 12], "little", signed=False)
        type_index = raw_type_flags & 0x0FFFFFFF
        flags = raw_type_flags & 0xF0000000
        type_name = type_names_by_index.get(type_index, "")
        records.append(
            HkxItemRecord(
                index=index,
                raw_type_flags=raw_type_flags,
                type_index=type_index,
                flags=flags,
                data_offset=data_offset,
                absolute_data_offset=(data_payload_offset + data_offset if data_payload_offset is not None else None),
                count=count,
                type_name=type_name,
            )
        )
    return records


def parse_hkx_tagfile_summary(data: bytes) -> HkxTagfileSummary:
    from cdmw.core import archive_hkx as hkx

    printable = _extract_hkx_printable_strings(data)
    native_parts = hkx._hkx_native_summary_parts(data)
    native_object_records: List[Dict[str, object]] = []
    native_physics_tuning_groups: List[Dict[str, object]] = []
    native_tagfile_reference_fixups: Dict[str, object] = {}
    native_fixup_semantics_report: Dict[str, object] = {}
    native_model_graph: Dict[str, object] = {}
    native_hard_internal_evidence: Dict[str, object] = {}
    native_real_hkclass_metadata: Dict[str, object] = {}
    native_real_hkclass_metadata_v2: Dict[str, object] = {}
    native_fixup_semantics_v2: Dict[str, object] = {}
    native_semantic_model_v1: Dict[str, object] = {}
    native_semantic_writer_gate_v1: Dict[str, object] = {}
    native_edit_candidate_map_v1: Dict[str, object] = {}
    native_hkx_edit_gate_v1: Dict[str, object] = {}
    native_class_decoder_evidence_v2: Dict[str, object] = {}
    native_decoder_evidence_v2: Dict[str, object] = {}
    native_modding_readiness: Dict[str, object] = {}
    native_no_edit_binary_writer: Dict[str, object] = {}
    if native_parts is not None:
        (
            tag_items,
            string_table_names,
            type_infos,
            declared_type_name_count,
            type_names,
            item_records,
            type_warnings,
            native_object_records,
            native_physics_tuning_groups,
            native_tagfile_reference_fixups,
            native_fixup_semantics_report,
            native_model_graph,
            native_hard_internal_evidence,
            native_real_hkclass_metadata,
            native_real_hkclass_metadata_v2,
            native_fixup_semantics_v2,
            native_semantic_model_v1,
            native_semantic_writer_gate_v1,
            native_edit_candidate_map_v1,
            native_hkx_edit_gate_v1,
            native_class_decoder_evidence_v2,
            native_decoder_evidence_v2,
            native_modding_readiness,
            native_no_edit_binary_writer,
        ) = native_parts
        if not type_names:
            type_names = [type_info.display_name for type_info in type_infos] or string_table_names or _extract_hkx_type_names(printable)
    else:
        tag_items = _find_hkx_tag_items(data)
        string_table_names = _extract_hkx_tst1_type_names(data, tag_items)
        declared_type_name_count, type_infos, type_warnings = _parse_hkx_tna1_type_infos(data, tag_items, string_table_names)
        tna_type_names = [type_info.display_name for type_info in type_infos]
        fallback_type_names = _extract_hkx_type_names(printable)
        type_names = tna_type_names or string_table_names or fallback_type_names
        type_names_by_index = {type_info.index: type_info.display_name for type_info in type_infos}
        if not type_names_by_index:
            type_names_by_index = {index: name for index, name in enumerate(type_names)}
        item_records = _parse_hkx_item_records(data, tag_items, type_names_by_index)
    declared_size = int.from_bytes(data[:4], "big", signed=False) if len(data) >= 4 else None
    sdk_version = _detect_hkx_sdk_version(data, printable)
    item_payload_summaries = hkx._summarize_hkx_item_payloads(data, tag_items, item_records)
    collision_geometry_hints = hkx._infer_hkx_collision_geometry_hints(data, tag_items, item_records)
    warnings: List[str] = []
    warnings.extend(type_warnings)
    if declared_size is not None and declared_size != len(data):
        warnings.append(f"Declared size {declared_size:,} does not match payload size {len(data):,}.")
    return HkxTagfileSummary(
        declared_size=declared_size,
        size_matches=declared_size == len(data) if declared_size is not None else False,
        sdk_version=sdk_version,
        tag0_offset=data[:64].find(b"TAG0"),
        tag_items=tag_items,
        type_names=type_names,
        string_table_names=string_table_names,
        type_infos=type_infos,
        declared_type_name_count=declared_type_name_count,
        item_records=item_records,
        item_payload_summaries=item_payload_summaries,
        collision_geometry_hints=collision_geometry_hints,
        native_object_records=native_object_records,
        native_physics_tuning_groups=native_physics_tuning_groups,
        native_tagfile_reference_fixups=native_tagfile_reference_fixups,
        native_fixup_semantics_report=native_fixup_semantics_report,
        native_model_graph=native_model_graph,
        native_hard_internal_evidence=native_hard_internal_evidence,
        native_real_hkclass_metadata=native_real_hkclass_metadata,
        native_real_hkclass_metadata_v2=native_real_hkclass_metadata_v2,
        native_fixup_semantics_v2=native_fixup_semantics_v2,
        native_semantic_model_v1=native_semantic_model_v1,
        native_semantic_writer_gate_v1=native_semantic_writer_gate_v1,
        native_edit_candidate_map_v1=native_edit_candidate_map_v1,
        native_hkx_edit_gate_v1=native_hkx_edit_gate_v1,
        native_class_decoder_evidence_v2=native_class_decoder_evidence_v2,
        native_decoder_evidence_v2=native_decoder_evidence_v2,
        native_modding_readiness=native_modding_readiness,
        native_no_edit_binary_writer=native_no_edit_binary_writer,
        warnings=warnings,
    )
