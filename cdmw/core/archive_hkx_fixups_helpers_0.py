from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    '_HKX_SCALAR_ARRAY_TYPES',
)
def _hkx_tagfile_fixup_reference_category(target_type_name: str, *, section_name: str, match_kind: str) -> str:
    target = str(target_type_name or "")
    if match_kind == "null":
        return "null_reference"
    if match_kind == "type_index":
        return "type_reference"
    if match_kind == "string_table_index":
        if target.startswith(("hk", "hknp", "hka", "hkx", "hkcd")) or "::" in target:
            return "type_class_reference"
        return "string_reference"
    if target == "char":
        return "string_reference"
    if target.startswith("hkArray") or target in _HKX_SCALAR_ARRAY_TYPES:
        return "array_data_reference"
    if section_name == "INDX":
        return "object_reference"
    return "data_reference_candidate"


@bind_archive_hkx_globals(
    '_hkx_tagfile_fixup_reference_category',
)
def _hkx_tagfile_fixup_word_match(
    value: int,
    *,
    section_name: str,
    record_by_data_offset: Mapping[int, HkxItemRecord],
    record_by_absolute_offset: Mapping[int, HkxItemRecord],
    type_name_by_index: Mapping[int, str],
    string_table_names: Sequence[str],
) -> Dict[str, object]:
    if value == 0:
        return {
            "match_kind": "null",
            "reference_category": "null_reference",
            "confidence": "strong inference",
            "description": "Zero word in a tagfile fixup/reference-like section; treated as a null reference candidate.",
        }
    target_record = record_by_data_offset.get(value)
    if target_record is not None:
        return {
            "match_kind": "data_offset",
            "reference_category": _hkx_tagfile_fixup_reference_category(
                target_record.type_name,
                section_name=section_name,
                match_kind="data_offset",
            ),
            "target_record_index": target_record.index,
            "target_type_index": target_record.type_index,
            "target_type_name": target_record.type_name,
            "target_data_offset": target_record.data_offset,
            "confidence": "experimental",
            "description": "INDX/section word matches an ITEM DATA-relative offset. Exact Havok fixup semantics are still being recovered.",
        }
    target_record = record_by_absolute_offset.get(value)
    if target_record is not None:
        return {
            "match_kind": "absolute_offset",
            "reference_category": _hkx_tagfile_fixup_reference_category(
                target_record.type_name,
                section_name=section_name,
                match_kind="absolute_offset",
            ),
            "target_record_index": target_record.index,
            "target_type_index": target_record.type_index,
            "target_type_name": target_record.type_name,
            "target_absolute_offset": target_record.absolute_data_offset,
            "confidence": "experimental",
            "description": "INDX/section word matches an absolute ITEM payload offset. Exact Havok fixup semantics are still being recovered.",
        }
    if value in type_name_by_index:
        type_name = str(type_name_by_index.get(value) or "")
        return {
            "match_kind": "type_index",
            "reference_category": _hkx_tagfile_fixup_reference_category(
                type_name,
                section_name=section_name,
                match_kind="type_index",
            ),
            "target_type_index": value,
            "target_type_name": type_name,
            "confidence": "experimental",
            "description": "INDX/section word matches a recovered TNA1 type index.",
        }
    if 0 <= value < len(string_table_names):
        string_value = str(string_table_names[value])
        return {
            "match_kind": "string_table_index",
            "reference_category": _hkx_tagfile_fixup_reference_category(
                string_value,
                section_name=section_name,
                match_kind="string_table_index",
            ),
            "target_string_index": value,
            "target_string": string_value,
            "confidence": "experimental",
            "description": "INDX/section word matches a recovered TST1 string-table index.",
        }
    return {
        "match_kind": "unresolved_word",
        "reference_category": "unresolved_fixup_word",
        "confidence": "raw",
        "description": "No recovered ITEM, type, or string-table target matched this fixup word.",
    }


@bind_archive_hkx_globals()
def _hkx_tagfile_nested_item_word_match(
    word_index: int,
    offset: int,
    value: int,
    *,
    section_item: HkxTagItem,
    item_item: HkxTagItem,
    records: Sequence[HkxItemRecord],
) -> Optional[Dict[str, object]]:
    word_absolute_offset = int(section_item.offset) + 4 + int(offset)
    if item_item.length_word_offset is not None and int(item_item.length_word_offset) == word_absolute_offset:
        return {
            "match_kind": "item_length_word",
            "reference_category": "item_table_metadata",
            "confidence": "confirmed",
            "description": "INDX contains the nested ITEM section length word.",
        }
    if word_absolute_offset == int(item_item.offset):
        return {
            "match_kind": "item_marker",
            "reference_category": "item_table_metadata",
            "target_type_name": "ITEM",
            "confidence": "confirmed",
            "description": "INDX contains the nested ITEM marker.",
        }
    if int(item_item.offset) < word_absolute_offset < int(item_item.offset) + 16:
        return {
            "match_kind": "item_header_word",
            "reference_category": "item_table_metadata",
            "confidence": "confirmed",
            "description": "Header/padding word before nested ITEM records.",
        }
    record_start = int(item_item.offset) + 16
    item_end = (
        int(item_item.word_end_offset)
        if item_item.word_end_offset is not None
        else int(item_item.marker_end_offset)
        if item_item.marker_end_offset is not None
        else record_start
    )
    if word_absolute_offset < record_start or word_absolute_offset + 4 > item_end:
        return None
    relative = word_absolute_offset - record_start
    record_slot = relative // 12
    if record_slot < 0 or record_slot >= len(records):
        return None
    record = records[record_slot]
    role = relative % 12
    if role == 0:
        return {
            "match_kind": "item_type_flags",
            "reference_category": "type_reference",
            "target_record_index": record.index,
            "target_type_index": record.type_index,
            "target_type_name": record.type_name,
            "confidence": "confirmed" if int(value) == int(record.raw_type_flags) else "experimental",
            "description": "Nested ITEM descriptor raw type/flags word. Low bits are the recovered TNA1 type index; high bits are ITEM flags.",
        }
    if role == 4:
        return {
            "match_kind": "item_data_offset",
            "reference_category": "item_data_offset",
            "target_record_index": record.index,
            "target_type_index": record.type_index,
            "target_type_name": record.type_name,
            "target_data_offset": record.data_offset,
            "target_absolute_offset": record.absolute_data_offset,
            "confidence": "confirmed" if int(value) == int(record.data_offset) else "experimental",
            "description": "Nested ITEM descriptor DATA-relative object payload offset.",
        }
    if role == 8:
        return {
            "match_kind": "item_count",
            "reference_category": "item_count",
            "target_record_index": record.index,
            "target_type_index": record.type_index,
            "target_type_name": record.type_name,
            "confidence": "confirmed" if int(value) == int(record.count) else "experimental",
            "description": "Nested ITEM descriptor element count.",
        }
    return None


@bind_archive_hkx_globals(
    '_hkx_hex',
    '_hkx_tagfile_fixup_reference_category',
    'struct',
)
def _hkx_decode_ptch_patch_site(
    data: bytes,
    patch_site_index: int,
    ptch_word_index: int,
    patch_site_offset: int,
    *,
    section_item: HkxTagItem,
    ptch_item: HkxTagItem,
    records: Sequence[HkxItemRecord],
) -> Dict[str, object]:
    word_absolute_offset = int(ptch_item.offset) + 4 + int(ptch_word_index) * 4
    section_payload_start = int(section_item.offset) + 4
    section_word_offset = word_absolute_offset - section_payload_start
    owner_record = max(
        (record for record in records if int(record.data_offset) <= int(patch_site_offset)),
        key=lambda record: int(record.data_offset),
        default=None,
    )
    owner_local_offset: Optional[int] = None
    patch_value: Optional[int] = None
    if owner_record is not None:
        owner_local_offset = int(patch_site_offset) - int(owner_record.data_offset)
        if owner_record.absolute_data_offset is not None:
            absolute = int(owner_record.absolute_data_offset) + owner_local_offset
            if 0 <= absolute and absolute + 8 <= len(data):
                patch_value = struct.unpack_from("<Q", data, absolute)[0]
    target_record: Optional[HkxItemRecord] = None
    if patch_value is not None and 0 <= patch_value < len(records):
        target_record = records[int(patch_value)]
    if patch_value == 0:
        target_status = "null"
        reference_category = "null_reference"
        confidence = "strong inference"
    elif target_record is not None:
        target_status = "object"
        reference_category = _hkx_tagfile_fixup_reference_category(
            target_record.type_name,
            section_name="INDX",
            match_kind="data_offset",
        )
        confidence = "strong inference"
    else:
        target_status = "unresolved"
        reference_category = "patch_offset_candidate"
        confidence = "experimental"
    row: Dict[str, object] = {
        "index": int(patch_site_index),
        "ptch_word_index": int(ptch_word_index),
        "section_word_index": section_word_offset // 4 if section_word_offset >= 0 else None,
        "section_word_offset": section_word_offset if section_word_offset >= 0 else None,
        "patch_site_offset": int(patch_site_offset),
        "patch_site_hex_offset": _hkx_hex(int(patch_site_offset)),
        "owner_record_index": owner_record.index if owner_record is not None else None,
        "owner_type_index": owner_record.type_index if owner_record is not None else None,
        "owner_type_name": owner_record.type_name if owner_record is not None else None,
        "owner_local_offset": owner_local_offset,
        "patch_value": patch_value,
        "target_status": target_status,
        "reference_category": reference_category,
        "target_record_index": target_record.index if target_record is not None else None,
        "target_type_index": target_record.type_index if target_record is not None else None,
        "target_type_name": target_record.type_name if target_record is not None else None,
        "target_data_offset": target_record.data_offset if target_record is not None else None,
        "target_absolute_offset": target_record.absolute_data_offset if target_record is not None else None,
        "confidence": confidence,
    }
    return {key: value for key, value in row.items() if value is not None}


@bind_archive_hkx_globals(
    '_hkx_decode_ptch_patch_site',
    '_hkx_hex',
    'struct',
)
def _hkx_decode_nested_ptch_table(
    data: bytes,
    *,
    section_item: HkxTagItem,
    ptch_item: HkxTagItem,
    records: Sequence[HkxItemRecord],
) -> Optional[Dict[str, object]]:
    ptch_end = (
        int(ptch_item.word_end_offset)
        if ptch_item.word_end_offset is not None
        else int(ptch_item.marker_end_offset)
        if ptch_item.marker_end_offset is not None
        else int(ptch_item.offset) + 4
    )
    payload_offset = int(ptch_item.offset) + 4
    if payload_offset + 20 > len(data) or payload_offset > ptch_end:
        return None
    payload_byte_length = max(0, ptch_end - payload_offset)
    word_count = payload_byte_length // 4
    if word_count < 5:
        return None
    ptch_words = [
        struct.unpack_from("<I", data, payload_offset + word_offset)[0]
        for word_offset in range(0, word_count * 4, 4)
        if payload_offset + word_offset + 4 <= len(data)
    ]
    if len(ptch_words) < 5 or tuple(ptch_words[:4]) != (1, 1, 0, 2):
        return None
    patch_site_count = int(ptch_words[4])
    if patch_site_count > max(0, len(ptch_words) - 5):
        return None
    patch_sites = [
        _hkx_decode_ptch_patch_site(
            data,
            patch_site_index,
            5 + patch_site_index,
            int(ptch_words[5 + patch_site_index]),
            section_item=section_item,
            ptch_item=ptch_item,
            records=records,
        )
        for patch_site_index in range(patch_site_count)
    ]
    resolved_patch_site_count = sum(1 for site in patch_sites if site.get("target_status") == "object")
    null_patch_site_count = sum(1 for site in patch_sites if site.get("target_status") == "null")
    unresolved_patch_site_count = sum(1 for site in patch_sites if site.get("target_status") == "unresolved")
    return {
        "offset": int(ptch_item.offset),
        "hex_offset": _hkx_hex(int(ptch_item.offset)),
        "payload_offset": payload_offset,
        "payload_hex_offset": _hkx_hex(payload_offset),
        "payload_byte_length": payload_byte_length,
        "word_count": word_count,
        "header": [1, 1, 0, 2],
        "patch_site_count": patch_site_count,
        "resolved_patch_site_count": resolved_patch_site_count,
        "null_patch_site_count": null_patch_site_count,
        "unresolved_patch_site_count": unresolved_patch_site_count,
        "confidence": "strong inference" if unresolved_patch_site_count == 0 else "experimental",
        "patch_sites": patch_sites,
    }


@bind_archive_hkx_globals(
    '_hkx_decode_ptch_patch_site',
    '_hkx_tagfile_fixup_word_match',
    'struct',
)
def _hkx_tagfile_nested_ptch_word_match(
    data: bytes,
    word_index: int,
    offset: int,
    value: int,
    *,
    section_item: HkxTagItem,
    ptch_item: HkxTagItem,
    ptch_payload: bytes,
    records: Sequence[HkxItemRecord],
    record_by_data_offset: Mapping[int, HkxItemRecord],
    record_by_absolute_offset: Mapping[int, HkxItemRecord],
    type_name_by_index: Mapping[int, str],
    string_table_names: Sequence[str],
) -> Optional[Dict[str, object]]:
    word_absolute_offset = int(section_item.offset) + 4 + int(offset)
    if ptch_item.length_word_offset is not None and int(ptch_item.length_word_offset) == word_absolute_offset:
        return {
            "match_kind": "ptch_length_word",
            "reference_category": "ptch_table_metadata",
            "confidence": "confirmed",
            "description": "INDX contains the nested PTCH section length word.",
        }
    if word_absolute_offset == int(ptch_item.offset):
        return {
            "match_kind": "ptch_marker",
            "reference_category": "ptch_table_metadata",
            "target_type_name": "PTCH",
            "confidence": "confirmed",
            "description": "INDX contains the nested PTCH marker.",
        }
    ptch_end = (
        int(ptch_item.word_end_offset)
        if ptch_item.word_end_offset is not None
        else int(ptch_item.marker_end_offset)
        if ptch_item.marker_end_offset is not None
        else int(ptch_item.offset) + 4
    )
    if word_absolute_offset < int(ptch_item.offset) + 4 or word_absolute_offset + 4 > ptch_end:
        return None
    ptch_payload_start = int(ptch_item.offset) + 4
    ptch_word_offset = word_absolute_offset - ptch_payload_start
    if ptch_word_offset < 0 or ptch_word_offset % 4:
        return None
    ptch_word_index = ptch_word_offset // 4
    ptch_words = [
        struct.unpack_from("<I", ptch_payload, word_offset)[0]
        for word_offset in range(0, (len(ptch_payload) // 4) * 4, 4)
    ]
    if len(ptch_words) >= 5 and tuple(ptch_words[:4]) == (1, 1, 0, 2) and int(ptch_words[4]) <= max(0, len(ptch_words) - 5):
        if ptch_word_index < 4:
            return {
                "match_kind": "ptch_header_word",
                "reference_category": "ptch_table_metadata",
                "confidence": "confirmed",
                "description": "Nested PTCH fixed header word. Corpus samples use [1, 1, 0, 2] before the patch-site count.",
            }
        if ptch_word_index == 4:
            return {
                "match_kind": "ptch_patch_site_count",
                "reference_category": "ptch_table_metadata",
                "patch_site_count": int(value),
                "confidence": "confirmed",
                "description": "Number of DATA-relative patch-site offsets following the PTCH header.",
            }
        patch_site_count = int(ptch_words[4])
        if 5 <= ptch_word_index < 5 + patch_site_count:
            site = _hkx_decode_ptch_patch_site(
                data,
                ptch_word_index - 5,
                ptch_word_index,
                int(value),
                section_item=section_item,
                ptch_item=ptch_item,
                records=records,
            )
            target_status = str(site.get("target_status") or "unresolved")
            row: Dict[str, object] = {
                **site,
                "match_kind": (
                    "ptch_object_patch_offset"
                    if target_status == "object"
                    else "ptch_null_patch_offset"
                    if target_status == "null"
                    else "ptch_patch_site_offset"
                ),
                "description": (
                    "Nested PTCH object-reference patch site. The PTCH word is a DATA-relative offset; "
                    "the slot value is interpreted as a target ITEM record index when it is in range."
                ),
            }
            return {key: value for key, value in row.items() if value is not None}
    match = _hkx_tagfile_fixup_word_match(
        int(value),
        section_name="PTCH",
        record_by_data_offset=record_by_data_offset,
        record_by_absolute_offset=record_by_absolute_offset,
        type_name_by_index=type_name_by_index,
        string_table_names=string_table_names,
    )
    match_kind = str(match.get("match_kind") or "unresolved_word")
    match["match_kind"] = {
        "null": "ptch_null",
        "data_offset": "ptch_data_offset",
        "absolute_offset": "ptch_absolute_offset",
        "type_index": "ptch_type_index",
        "string_table_index": "ptch_string_table_index",
        "unresolved_word": "ptch_payload_word",
    }.get(match_kind, f"ptch_{match_kind}")
    if str(match.get("reference_category") or "") == "unresolved_fixup_word":
        match["reference_category"] = "patch_offset_candidate"
        match["confidence"] = "experimental"
        match["description"] = (
            "Nested PTCH payload word that did not match a recovered ITEM/type/string target. "
            "Kept as a patch/fixup offset candidate until PTCH tuple semantics are fully mapped."
        )
    return match
