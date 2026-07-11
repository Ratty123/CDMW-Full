from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals()
def _hkx_type_registry_document(summary: HkxTagfileSummary) -> Dict[str, object]:
    type_infos = [
        {
            "index": type_info.index,
            "name": type_info.name,
            "display_name": type_info.display_name,
            "template_parameters": [
                {"name": name, "value": value}
                for name, value in type_info.template_parameters
            ],
        }
        for type_info in summary.type_infos
    ]
    return {
        "declared_type_name_count": summary.declared_type_name_count,
        "type_infos": type_infos,
        "string_table_names": list(summary.string_table_names),
        "type_names": list(summary.type_names),
    }


@bind_archive_hkx_globals()
def _hkx_havok_template_arguments(type_text: str) -> List[str]:
    text = str(type_text or "").strip()
    start = text.find("<")
    end = text.rfind(">")
    if start < 0 or end <= start:
        return []
    inner = text[start + 1 : end]
    args: List[str] = []
    depth = 0
    current: List[str] = []
    for char in inner:
        if char == "<":
            depth += 1
            current.append(char)
        elif char == ">":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "," and depth == 0:
            arg = "".join(current).strip()
            if arg:
                args.append(arg)
            current = []
        else:
            current.append(char)
    arg = "".join(current).strip()
    if arg:
        args.append(arg)
    return args


@bind_archive_hkx_globals(
    '_hkx_havok_template_arguments',
)
def _hkx_havok_member_type_metadata(member: Mapping[str, object]) -> Dict[str, object]:
    data_type = str(member.get("type") or "")
    reference_status = str(member.get("reference_status") or "none")
    array_status = str(member.get("array_status") or "none")
    template_args = _hkx_havok_template_arguments(data_type)
    element_type = template_args[0] if template_args and data_type.startswith("hkArray<") else ""
    pointer_type = ""
    if data_type.startswith("hkRefPtr<") and template_args:
        pointer_type = template_args[0]
    elif data_type in {"hkStringPtr", "char*", "char[]"}:
        pointer_type = "char"
    elif data_type.endswith("*"):
        pointer_type = data_type[:-1].strip()
    is_array = data_type.startswith("hkArray<") or data_type.endswith("[]") or array_status in {
        "hkArray",
        "row_list",
        "scalar_list",
        "string_data",
        "fixed_rows",
    }
    is_pointer = bool(pointer_type) or data_type.startswith("hkRefPtr<") or data_type in {"hkRefVariant", "hkStringPtr"}
    scalar_map = {
        "hkReal": "TYPE_REAL",
        "float": "TYPE_REAL",
        "int": "TYPE_INT32",
        "hkInt16": "TYPE_INT16",
        "hkUint8": "TYPE_UINT8",
        "hkUint32": "TYPE_UINT32",
        "unsigned int": "TYPE_UINT32",
        "unsigned short": "TYPE_UINT16",
        "unsigned char": "TYPE_UINT8",
        "char": "TYPE_CHAR",
        "char*": "TYPE_CSTRING",
        "char[]": "TYPE_CSTRING",
    }
    if is_array:
        member_type = "TYPE_ARRAY"
    elif data_type.startswith("hkRefPtr<"):
        member_type = "TYPE_POINTER"
    elif data_type in {"hkRefVariant", "void*"}:
        member_type = "TYPE_POINTER"
    elif data_type in {"hkStringPtr", "char*"}:
        member_type = "TYPE_CSTRING"
    elif data_type.endswith("::Enum") or data_type.endswith("FlagsEnum"):
        member_type = "TYPE_ENUM"
    else:
        member_type = scalar_map.get(data_type, "TYPE_STRUCT")
    class_ref = (element_type or pointer_type) if member_type in {"TYPE_ARRAY", "TYPE_POINTER", "TYPE_STRUCT"} else ""
    return {
        "member_type": member_type,
        "subtype": element_type or pointer_type or "",
        "class_ref": class_ref,
        "template_arguments": template_args,
        "is_array": is_array,
        "is_pointer": is_pointer,
        "is_enum": member_type == "TYPE_ENUM",
        "flags": str(member.get("flags") or "FLAGS_NONE"),
        "storage": (
            "hkArray"
            if data_type.startswith("hkArray<")
            else "hkRefPtr"
            if data_type.startswith("hkRefPtr<")
            else "reference"
            if reference_status not in {"", "none"}
            else "value"
        ),
    }


@bind_archive_hkx_globals(
    '_hkx_havok_schema_base_name',
)
def _hkx_havok_reference_category(
    *,
    source_type_name: str,
    target_type_name: str = "",
    offset: Optional[int] = None,
    field_name: str = "",
) -> str:
    source = _hkx_havok_schema_base_name(str(source_type_name or ""))
    target = str(target_type_name or "")
    name = str(field_name or "")
    name_lower = name.lower()
    if target == "char":
        if "class" in name_lower or (source == "hkRootLevelContainer::NamedVariant" and offset == 8):
            return "type_class_reference"
        return "string_reference"
    if "class_name" in name_lower or "classname" in name_lower:
        return "type_class_reference"
    if "name_reference" in name_lower or source == "hkStringPtr":
        return "string_reference"
    if source == "hkArray" or "array" in name_lower or "data_reference" in name_lower:
        return "array_data_reference"
    if source in {"hkRefPtr", "hkRefVariant"}:
        return "object_reference"
    if source == "hkRootLevelContainer::NamedVariant" and offset == 16:
        return "object_reference"
    if (
        "object_reference" in name_lower
        or "shape_reference" in name_lower
        or "constraint_data_reference" in name_lower
        or "body_" in name_lower
        or name_lower.endswith("_reference_pair")
    ):
        return "object_reference"
    if target:
        return "object_reference"
    return "record_reference_candidate"


@bind_archive_hkx_globals(
    '_hkx_havok_schema_base_name',
)
def _hkx_havok_reference_confidence(
    *,
    source_type_name: str,
    reference_kind: str,
    reference_category: str,
) -> str:
    source = _hkx_havok_schema_base_name(str(source_type_name or ""))
    if reference_kind == "data_offset" and reference_category in {
        "array_data_reference",
        "object_reference",
        "string_reference",
        "type_class_reference",
    }:
        if source in {
            "hkArray",
            "hkRefPtr",
            "hkRefVariant",
            "hkStringPtr",
            "hkRootLevelContainer",
            "hkRootLevelContainer::NamedVariant",
        }:
            return "strong inference"
    return "experimental"


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_havok_array_status_for_field',
    '_hkx_havok_confidence_for_field',
    '_hkx_havok_data_type_for_field',
    '_hkx_havok_enrich_member_row',
    '_hkx_havok_member_rows_for_type',
    '_hkx_havok_param_name_for_field',
    '_hkx_havok_reference_status_for_field',
)
def _hkx_havok_synthetic_member_rows(
    type_name: str,
    observed_fields: Sequence[Mapping[str, object]],
) -> List[Dict[str, object]]:
    rows = _hkx_havok_member_rows_for_type(type_name)
    seen_names = {str(row.get("name") or "") for row in rows}
    for field in observed_fields:
        if not isinstance(field, Mapping):
            continue
        source_name = str(field.get("name") or "")
        member_name = _hkx_havok_param_name_for_field(type_name, field)
        if not member_name or member_name in seen_names:
            continue
        seen_names.add(member_name)
        rows.append(
            {
                "source_names": (source_name,),
                "name": member_name,
                "type": _hkx_havok_data_type_for_field(type_name, field),
                "offset": field.get("offset"),
                "array_status": _hkx_havok_array_status_for_field(type_name, field),
                "reference_status": _hkx_havok_reference_status_for_field(type_name, field),
                "confidence": _hkx_havok_confidence_for_field(type_name, field),
                "cdmw_recovered": True,
            }
        )
    return [_hkx_havok_enrich_member_row(row) for row in rows]


@bind_archive_hkx_globals(
    '_hkx_havok_xml_param_text',
    'json',
)
def _hkx_havok_xml_param_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.9g}"
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        if all(isinstance(item, (int, float, bool, str)) for item in value):
            return " ".join(_hkx_havok_xml_param_text(item) for item in value)
        rows: List[str] = []
        for item in value:
            if isinstance(item, (list, tuple)) and all(isinstance(component, (int, float, bool, str)) for component in item):
                rows.append(" ".join(_hkx_havok_xml_param_text(component) for component in item))
            else:
                rows.append(json.dumps(item, sort_keys=True))
        return "\n".join(rows)
    return json.dumps(value, sort_keys=True)


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_havok_xml_reference_target',
    '_hkx_hex',
    'defaultdict',
)
def _hkx_ptch_reference_documents_by_owner_offset(
    tagfile_reference_fixups: Optional[Mapping[str, object]],
) -> Dict[int, Dict[int, Dict[str, object]]]:
    if not isinstance(tagfile_reference_fixups, Mapping):
        return {}
    refs_by_owner: Dict[int, Dict[int, Dict[str, object]]] = defaultdict(dict)
    sections = tagfile_reference_fixups.get("sections")
    if not isinstance(sections, list):
        return {}
    for section in sections:
        if not isinstance(section, Mapping):
            continue
        section_name = str(section.get("name") or "")
        ptch_tables = section.get("ptch_tables")
        if not isinstance(ptch_tables, list):
            continue
        for table_index, table in enumerate(ptch_tables):
            if not isinstance(table, Mapping):
                continue
            patch_sites = table.get("patch_sites")
            if not isinstance(patch_sites, list):
                continue
            for site in patch_sites:
                if not isinstance(site, Mapping):
                    continue
                owner_record_index = site.get("owner_record_index")
                owner_local_offset = site.get("owner_local_offset")
                if not isinstance(owner_record_index, int) or not isinstance(owner_local_offset, int):
                    continue
                target_status = str(site.get("target_status") or "unresolved")
                target = _hkx_havok_xml_reference_target(site)
                reference_category = str(site.get("reference_category") or "")
                if target_status == "null":
                    reference_category = "null_reference"
                elif not target:
                    reference_category = reference_category or "patch_offset_candidate"
                reference = {
                    "offset": owner_local_offset,
                    "hex_offset": f"0x{owner_local_offset:X}",
                    "reference_kind": (
                        "ptch_object_patch"
                        if target_status == "object"
                        else "ptch_null_patch"
                        if target_status == "null"
                        else "ptch_patch_site"
                    ),
                    "reference_category": reference_category,
                    "raw_value": site.get("patch_value"),
                    "raw_value_hex": _hkx_hex(int(site.get("patch_value"))) if isinstance(site.get("patch_value"), int) else "",
                    "target": target,
                    "target_record_index": site.get("target_record_index"),
                    "target_type_index": site.get("target_type_index"),
                    "target_type_name": str(site.get("target_type_name") or ""),
                    "target_status": target_status,
                    "confidence": str(site.get("confidence") or "strong inference"),
                    "source": "PTCH",
                    "fixup_source": "PTCH",
                    "fixup_backed": True,
                    "section": section_name,
                    "ptch_table_index": table_index,
                    "ptch_word_index": site.get("ptch_word_index"),
                    "ptch_patch_site_index": site.get("index"),
                    "ptch_patch_site_offset": site.get("patch_site_offset"),
                    "ptch_patch_site_hex_offset": str(site.get("patch_site_hex_offset") or ""),
                    "description": (
                        "PTCH-backed reference patch site. The PTCH word identifies this owner-local slot, and "
                        "the patched slot value is interpreted as a target ITEM record index or null."
                    ),
                }
                refs_by_owner[owner_record_index][owner_local_offset] = {
                    key: value for key, value in reference.items() if value not in (None, "")
                }
    return refs_by_owner


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_havok_xml_record_strings(objects: Sequence[Mapping[str, object]]) -> Dict[int, str]:
    strings: Dict[int, str] = {}
    for object_info in objects:
        if not isinstance(object_info, Mapping) or str(object_info.get("type_name") or "") != "char":
            continue
        record_index = object_info.get("record_index")
        if not isinstance(record_index, int):
            continue
        decoded_fields = object_info.get("decoded_fields")
        if isinstance(decoded_fields, Mapping):
            decoded_string = decoded_fields.get("decoded_string")
            if isinstance(decoded_string, Mapping) and isinstance(decoded_string.get("value"), str):
                strings[record_index] = str(decoded_string["value"])
                continue
        layout = object_info.get("layout")
        layout_fields = layout.get("fields") if isinstance(layout, Mapping) else None
        if isinstance(layout_fields, list):
            for field in layout_fields:
                if (
                    isinstance(field, Mapping)
                    and str(field.get("name") or "") == "ascii_or_utf8_text"
                    and isinstance(field.get("value"), str)
                ):
                    strings[record_index] = str(field["value"])
                    break
    return strings


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_havok_xml_pair_low_count(field: Mapping[str, object]) -> Tuple[Optional[int], Optional[int]]:
    value = field.get("value")
    if isinstance(value, int):
        return int(value & 0xFFFFFFFF), None
    if not isinstance(value, Mapping):
        return None, None
    low_value = None
    for key in ("data_or_reference", "data_or_offset", "low_u32", "a", "raw_value"):
        candidate = value.get(key)
        if isinstance(candidate, int):
            low_value = int(candidate)
            break
    if low_value is None and isinstance(value.get("raw_u64"), int):
        low_value = int(value["raw_u64"]) & 0xFFFFFFFF
    count_value = None
    for key in ("count_or_flags", "row_count", "value_count", "record_count", "pair_count", "decoded_value_count", "b", "high_u32"):
        candidate = value.get(key)
        if isinstance(candidate, int):
            count_value = int(candidate)
            break
    return low_value, count_value


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_havok_array_status_for_field',
    '_hkx_havok_member_by_source_name',
    '_hkx_havok_xml_pair_low_count',
)
def _hkx_havok_xml_numelements_for_field(type_name: str, field: Mapping[str, object]) -> Optional[int]:
    member = _hkx_havok_member_by_source_name(type_name, str(field.get("name") or ""))
    array_status = str(member.get("array_status") or "") if isinstance(member, Mapping) else _hkx_havok_array_status_for_field(type_name, field)
    data_type = str(member.get("type") or field.get("data_type") or "") if isinstance(member, Mapping) else str(field.get("data_type") or "")
    value = field.get("value")
    if isinstance(value, Mapping):
        for key in ("count_or_flags", "row_count", "value_count", "record_count", "pair_count", "decoded_value_count"):
            candidate = value.get(key)
            if isinstance(candidate, int) and 0 <= candidate <= 10_000_000:
                return int(candidate)
    if isinstance(value, list):
        return len(value)
    if array_status in {"hkArray", "row_list", "scalar_list", "array_like", "string_data"} or "[]" in data_type or data_type.startswith("hkArray<"):
        _low, count = _hkx_havok_xml_pair_low_count(field)
        if isinstance(count, int) and 0 <= count <= 10_000_000:
            return int(count)
    return None


@bind_archive_hkx_globals(
    'Mapping',
    'MutableMapping',
)
def _hkx_havok_xml_apply_sibling_array_counts(fields: Sequence[MutableMapping[str, object]]) -> None:
    by_name = {str(field.get("hkparam_name") or field.get("name") or ""): field for field in fields if isinstance(field, MutableMapping)}
    for name, field in list(by_name.items()):
        if not name.endswith("Size"):
            continue
        value = field.get("value")
        if not isinstance(value, int) or value < 0:
            continue
        owner_name = name[: -len("Size")]
        owner = by_name.get(owner_name)
        if isinstance(owner, MutableMapping) and str(owner.get("array_status") or "") in {"hkArray", "array_like"}:
            owner.setdefault("numelements", int(value))
    data_field = by_name.get("data")
    size_field = by_name.get("size")
    if isinstance(data_field, MutableMapping) and isinstance(size_field, Mapping) and isinstance(size_field.get("value"), int):
        data_field.setdefault("numelements", int(size_field["value"]))


@bind_archive_hkx_globals(
    '_hkx_havok_xml_array_element_type',
    '_hkx_havok_xml_numelements_for_field',
    '_hkx_havok_xml_pair_low_count',
    '_hkx_havok_xml_reference_record_index',
    '_hkx_havok_xml_target_record_for_offset',
    '_hkx_havok_xml_type_matches_expected',
)
def _hkx_havok_xml_enrich_reference_field(
    field: MutableMapping[str, object],
    *,
    source_type_name: str,
    source_field: Mapping[str, object],
    summary: HkxTagfileSummary,
    char_strings_by_record: Mapping[int, str],
    existing_reference: Optional[Mapping[str, object]],
) -> None:
    numelements = _hkx_havok_xml_numelements_for_field(source_type_name, source_field)
    if numelements is not None:
        field["numelements"] = int(numelements)

    reference_category = str(field.get("reference_category") or field.get("reference_status") or "")
    low_value, count_value = _hkx_havok_xml_pair_low_count(source_field)
    if (
        low_value == 0
        and (count_value in {None, 0})
        and reference_category in {"object_reference", "string_reference", "type_class_reference", "array_data_reference"}
    ):
        field["hkparam_text"] = "null"
        field["value"] = None
        field["reference_target"] = ""
        field["reference_kind"] = "null"
        field["reference_category"] = "null_reference"
        field["reference_status"] = "null_reference"
        field["reference_target_type"] = ""
        field["confidence"] = "strong inference"
        if str(field.get("array_status") or "") == "hkArray":
            field["numelements"] = 0
        field["description"] = (
            str(field.get("description") or "")
            + " Zero reference payload is emitted as null in the Havok XML parity view."
        ).strip()
        return
    target_record_index = _hkx_havok_xml_reference_record_index(existing_reference)
    if target_record_index is not None and reference_category in {"string_reference", "type_class_reference"}:
        target_text = char_strings_by_record.get(target_record_index)
        if target_text:
            field["hkparam_text"] = target_text
            field["value"] = target_text
            field["reference_target"] = f"#record{target_record_index}"
            field["reference_status"] = reference_category
            field["confidence"] = "strong inference"
            field["description"] = (
                str(field.get("description") or "")
                + " Resolved referenced char record to text for Havok XML browsing; string edits remain ignored by CDMW import."
            ).strip()

    array_status = str(field.get("array_status") or "")
    data_type = str(field.get("type") or "")
    if array_status != "hkArray" and not data_type.startswith("hkArray<"):
        return
    target_record = _hkx_havok_xml_target_record_for_offset(low_value, summary)
    if target_record is None:
        return
    expected_type = _hkx_havok_xml_array_element_type(data_type)
    confidence = "strong inference" if _hkx_havok_xml_type_matches_expected(target_record.type_name, expected_type) else "experimental"
    target = f"#record{target_record.index}"
    field["hkparam_text"] = target
    field["value"] = target
    field["reference_target"] = target
    field["reference_kind"] = "owner_array_field"
    field["reference_category"] = "array_data_reference"
    field["reference_status"] = "array_data_reference"
    field["reference_target_type"] = target_record.type_name
    field["confidence"] = confidence
    if isinstance(count_value, int) and 0 <= count_value <= 10_000_000:
        field["numelements"] = int(count_value)
    field["description"] = (
        f"Owner-field array resolution linked {source_type_name}.{field.get('hkparam_name') or field.get('name')} "
        "to a recovered ITEM record. Array count changes remain blocked by CDMW import."
    )


@bind_archive_hkx_globals(
    'Mapping',
    '_HKX_SCALAR_ARRAY_TYPES',
    '_hkx_havok_xml_param_text',
)
def _hkx_havok_xml_array_value_fields(object_info: Mapping[str, object]) -> List[Dict[str, object]]:
    type_name = str(object_info.get("type_name") or "")
    decoded_fields = object_info.get("decoded_fields")
    if not isinstance(decoded_fields, Mapping):
        return []
    fields: List[Dict[str, object]] = []
    if type_name == "hkFloat3" and isinstance(decoded_fields.get("float3_rows"), list):
        rows = decoded_fields["float3_rows"]
        fields.append(
            {
                "name": "values",
                "type": "hkArray<hkFloat3>",
                "offset": 0,
                "hex_offset": "0x0",
                "size": object_info.get("byte_length"),
                "value": rows,
                "hkparam_name": "values",
                "hkparam_text": _hkx_havok_xml_param_text(rows),
                "numelements": len(rows),
                "reference_target": "",
                "reference_kind": "",
                "reference_category": "",
                "reference_target_type": "",
                "array_status": "row_list",
                "reference_status": "none",
                "editable": False,
                "confidence": "strong inference",
                "description": "Havok-style row list for decoded hkFloat3 array data. Row count changes remain blocked by CDMW import.",
            }
        )
    elif type_name == "hkVector4" and isinstance(decoded_fields.get("float4_rows"), list):
        rows = decoded_fields["float4_rows"]
        fields.append(
            {
                "name": "values",
                "type": "hkArray<hkVector4>",
                "offset": 0,
                "hex_offset": "0x0",
                "size": object_info.get("byte_length"),
                "value": rows,
                "hkparam_name": "values",
                "hkparam_text": _hkx_havok_xml_param_text(rows),
                "numelements": len(rows),
                "reference_target": "",
                "reference_kind": "",
                "reference_category": "",
                "reference_target_type": "",
                "array_status": "row_list",
                "reference_status": "none",
                "editable": False,
                "confidence": "strong inference",
                "description": "Havok-style row list for decoded hkVector4 array data. Row count changes remain blocked by CDMW import.",
            }
        )
    elif type_name in _HKX_SCALAR_ARRAY_TYPES:
        scalar_values = decoded_fields.get("scalar_values")
        values = scalar_values.get("values") if isinstance(scalar_values, Mapping) else None
        if isinstance(values, list):
            member_type = _HKX_SCALAR_ARRAY_TYPES[type_name][1].replace("[]", "")
            fields.append(
                {
                    "name": "values",
                    "type": f"hkArray<{member_type}>",
                    "offset": 0,
                    "hex_offset": "0x0",
                    "size": object_info.get("byte_length"),
                    "value": values,
                    "hkparam_name": "values",
                    "hkparam_text": _hkx_havok_xml_param_text(values),
                    "numelements": len(values),
                    "reference_target": "",
                    "reference_kind": "",
                    "reference_category": "",
                    "reference_target_type": "",
                    "array_status": "scalar_list",
                    "reference_status": "none",
                    "editable": False,
                    "confidence": "strong inference",
                    "description": "Havok-style scalar list for decoded array data. Count changes remain blocked by CDMW import.",
                }
            )
    elif type_name == "char" and isinstance(decoded_fields.get("decoded_string"), Mapping):
        string_value = decoded_fields["decoded_string"].get("value")
        if isinstance(string_value, str):
            fields.append(
                {
                    "name": "string",
                    "type": "char[]",
                    "offset": 0,
                    "hex_offset": "0x0",
                    "size": object_info.get("byte_length"),
                    "value": string_value,
                    "hkparam_name": "string",
                    "hkparam_text": string_value,
                    "numelements": len(string_value),
                    "reference_target": "",
                    "reference_kind": "",
                    "reference_category": "",
                    "reference_target_type": "",
                    "array_status": "string_data",
                    "reference_status": "none",
                    "editable": False,
                    "confidence": "confirmed",
                    "description": "Decoded string data. String length edits remain blocked because they would change record size and references.",
                }
            )
    return fields


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_havok_xml_named_variants',
)
def _hkx_havok_xml_root_recovery(hkobjects: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    by_id = {str(obj.get("id") or ""): obj for obj in hkobjects if isinstance(obj, Mapping)}
    named_variants = _hkx_havok_xml_named_variants(hkobjects)
    preferred_classes = (
        "hkRootLevelContainer",
        "hknpPhysicsSceneData",
        "hknpPhysicsSystemData",
        "hknpRagdollData",
        "hkaAnimationContainer",
    )
    for class_name in preferred_classes:
        for obj in hkobjects:
            if not isinstance(obj, Mapping) or str(obj.get("class") or "") != class_name:
                continue
            return {
                "toplevelobject": str(obj.get("id") or ""),
                "class": class_name,
                "method": "preferred_root_class",
                "confidence": "strong inference" if class_name == "hkRootLevelContainer" else "experimental",
                "description": "Root selected from known Havok root/container classes instead of record order.",
                "named_variant_count": len(named_variants),
                "named_variants": named_variants,
            }
    for obj in hkobjects:
        if not isinstance(obj, Mapping) or str(obj.get("class") or "") != "hkRootLevelContainer::NamedVariant":
            continue
        fields = obj.get("fields")
        if not isinstance(fields, list):
            continue
        for field in fields:
            if not isinstance(field, Mapping) or str(field.get("hkparam_name") or "") != "variant":
                continue
            target = str(field.get("reference_target") or "")
            target_obj = by_id.get(target)
            if isinstance(target_obj, Mapping):
                return {
                    "toplevelobject": target,
                    "class": str(target_obj.get("class") or ""),
                    "method": "named_variant_object_reference",
                    "confidence": str(field.get("confidence") or "experimental"),
                    "description": "Root selected from hkRootLevelContainer::NamedVariant.variant reference.",
                    "named_variant_count": len(named_variants),
                    "named_variants": named_variants,
                }
    fallback = str(hkobjects[0].get("id") or "") if hkobjects and isinstance(hkobjects[0], Mapping) else ""
    return {
        "toplevelobject": fallback,
        "class": str(hkobjects[0].get("class") or "") if hkobjects and isinstance(hkobjects[0], Mapping) else "",
        "method": "first_record_fallback",
        "confidence": "raw" if fallback else "none",
        "description": "No known root class or named-variant root reference was recovered; using first exported record.",
        "named_variant_count": len(named_variants),
        "named_variants": named_variants,
    }
