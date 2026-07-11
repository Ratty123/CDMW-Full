from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_havok_xml_named_variants(hkobjects: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
    by_id = {str(obj.get("id") or ""): obj for obj in hkobjects if isinstance(obj, Mapping)}
    variants: List[Dict[str, object]] = []
    for obj in hkobjects:
        if not isinstance(obj, Mapping) or str(obj.get("class") or "") != "hkRootLevelContainer::NamedVariant":
            continue
        fields = obj.get("fields")
        if not isinstance(fields, list):
            continue
        by_name = {
            str(field.get("hkparam_name") or field.get("name") or ""): field
            for field in fields
            if isinstance(field, Mapping)
        }
        target = str(by_name.get("variant", {}).get("reference_target") or "")
        target_obj = by_id.get(target)
        variants.append(
            {
                "record": str(obj.get("id") or ""),
                "name": str(by_name.get("name", {}).get("hkparam_text") or ""),
                "className": str(by_name.get("className", {}).get("hkparam_text") or ""),
                "class_reference_target": str(by_name.get("className", {}).get("reference_target") or ""),
                "variant": target,
                "variant_class": str(target_obj.get("class") or "") if isinstance(target_obj, Mapping) else "",
                "confidence": str(by_name.get("variant", {}).get("confidence") or obj.get("confidence") or "experimental"),
            }
        )
    return variants


@bind_archive_hkx_globals(
    'Counter',
    'Mapping',
    'hashlib',
)
def _hkx_havok_class_metadata(
    type_info: HkxTypeInfo,
    members: Sequence[Mapping[str, object]],
    observed_fields: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    max_member_end = 0
    for field in observed_fields:
        if not isinstance(field, Mapping):
            continue
        offset = field.get("offset")
        size = field.get("size")
        if isinstance(offset, int) and isinstance(size, int) and offset >= 0 and size >= 0:
            max_member_end = max(max_member_end, offset + size)
    for member in members:
        offset = member.get("offset")
        if isinstance(offset, int) and offset >= 0:
            max_member_end = max(max_member_end, offset)
    signature_seed = f"{type_info.display_name}|{len(members)}|{max_member_end}".encode("utf-8", errors="ignore")
    signature = int.from_bytes(hashlib.sha1(signature_seed).digest()[:4], "little")
    confidence_counts = Counter(str(member.get("confidence") or "experimental") for member in members if isinstance(member, Mapping))
    return {
        "parent": "",
        "object_size": max_member_end or None,
        "version": 0,
        "flags": "FLAGS_NONE",
        "signature": f"0x{signature:08X}",
        "member_count": len(members),
        "declared_member_count": len(members),
        "recovered_member_count": sum(1 for member in members if isinstance(member, Mapping) and bool(member.get("cdmw_recovered"))),
        "confidence_counts": dict(sorted(confidence_counts.items())),
        "metadata_status": "synthetic_recovered_hkClass",
        "real_hkclass_metadata_recovered": False,
        "metadata_source": "TNA1_TYPE_NAMES_PLUS_CDMW_LAYOUT_RECOVERY",
        "member_offset_confidence": "observed_layout" if members or observed_fields else "unknown",
        "unresolved_real_metadata": [
            "member_type_codes",
            "member_flags",
            "base_classes",
            "enum_refs",
            "signatures",
            "versions",
            "default_values",
            "template_refs",
        ],
    }


@bind_archive_hkx_globals(
    'Mapping',
)
def _hkx_real_hkclass_member_rows(real_class: Mapping[str, object]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    members = real_class.get("members")
    if not isinstance(members, list):
        return rows
    for member in members:
        if not isinstance(member, Mapping):
            continue
        member_type = str(member.get("type_name") or member.get("member_type_name") or "")
        subtype = str(member.get("subtype_name") or "")
        class_ref = str(member.get("class_ref_name") or "")
        enum_ref = str(member.get("enum_ref_name") or "")
        data_type = class_ref if member_type in {"TYPE_POINTER", "TYPE_ARRAY", "TYPE_STRUCT"} and class_ref else member_type
        rows.append(
            {
                "name": str(member.get("name") or ""),
                "type": data_type,
                "offset": member.get("offset"),
                "size": None,
                "array_status": "hkArray" if member_type in {"TYPE_ARRAY", "TYPE_SIMPLEARRAY", "TYPE_RELARRAY"} else "none",
                "reference_status": "object_reference"
                if member_type == "TYPE_POINTER"
                else "array_data_reference"
                if member_type in {"TYPE_ARRAY", "TYPE_SIMPLEARRAY", "TYPE_RELARRAY"}
                else "type_class_reference"
                if class_ref
                else "none",
                "member_type": member_type,
                "member_type_code": member.get("type_code") if member.get("type_code") is not None else member.get("member_type_code"),
                "subtype": subtype,
                "subtype_code": member.get("subtype_code"),
                "class_ref": class_ref,
                "class_ref_record_index": member.get("class_ref_record_index"),
                "enum_ref": enum_ref,
                "enum_ref_record_index": member.get("enum_ref_record_index"),
                "flags": str(member.get("flags_hex") or ""),
                "member_flags": member.get("flags"),
                "c_array_size": member.get("c_array_size"),
                "template_ref": str(member.get("template_ref") or ""),
                "storage": "real_hkClassMember",
                "is_array": member_type in {"TYPE_ARRAY", "TYPE_SIMPLEARRAY", "TYPE_RELARRAY"},
                "is_pointer": member_type == "TYPE_POINTER",
                "is_enum": member_type in {"TYPE_ENUM", "TYPE_FLAGS"} or bool(enum_ref),
                "confidence": str(member.get("confidence") or "strong inference"),
                "cdmw_recovered": False,
                "real_hkclass_metadata_recovered": True,
                "metadata_source": "HKCLASS_MEMBER_RECORD",
                "source_names": [],
            }
        )
    return rows


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_xml_scalar',
)
def _hkx_real_hkclass_metadata_document(real_class: Mapping[str, object], members: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    recovered_requirements = (
        dict(real_class.get("recovered_requirements") or {})
        if isinstance(real_class.get("recovered_requirements"), Mapping)
        else {}
    )
    unresolved = [
        str(item)
        for item in real_class.get("unresolved_requirements", [])
        if str(item)
    ] if isinstance(real_class.get("unresolved_requirements"), list) else []
    signature_hex = str(real_class.get("signature_hex") or "")
    return {
        "parent": str(real_class.get("parent_name") or real_class.get("base_class") or ""),
        "object_size": real_class.get("object_size"),
        "version": real_class.get("version"),
        "flags": str(real_class.get("flags") if real_class.get("flags") is not None else "FLAGS_NONE"),
        "signature": signature_hex or _hkx_xml_scalar(real_class.get("signature")),
        "member_count": len(members),
        "declared_member_count": real_class.get("declared_member_count"),
        "recovered_member_count": len(members),
        "confidence_counts": {"strong inference": len(members)} if members else {},
        "metadata_status": "real_hkClass_records",
        "real_hkclass_metadata_recovered": True,
        "metadata_source": "HKCLASS_RECORDS_NATIVE",
        "member_offset_confidence": "real_hkClassMember_offsets",
        "unresolved_real_metadata": unresolved,
        "recovered_real_metadata": {
            key: bool(value)
            for key, value in recovered_requirements.items()
        },
        "record_index": real_class.get("record_index"),
        "parent_record_index": real_class.get("parent_record_index"),
        "defaults_record_index": real_class.get("defaults_record_index"),
        "attributes_record_index": real_class.get("attributes_record_index"),
        "declared_enum_count": real_class.get("declared_enum_count"),
        "members_record_index": real_class.get("members_record_index"),
        "enums_record_index": real_class.get("enums_record_index"),
    }


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_havok_class_metadata',
    '_hkx_havok_synthetic_member_rows',
    '_hkx_real_hkclass_member_rows',
    '_hkx_real_hkclass_metadata_by_name',
    '_hkx_real_hkclass_metadata_document',
    'defaultdict',
)
def _hkx_havok_xml_type_classes(
    summary: HkxTagfileSummary,
    objects: Sequence[Mapping[str, object]],
) -> List[Dict[str, object]]:
    observed_fields_by_type: Dict[str, List[Mapping[str, object]]] = defaultdict(list)
    for object_info in objects:
        if not isinstance(object_info, Mapping):
            continue
        type_name = str(object_info.get("type_name") or "")
        layout = object_info.get("layout")
        fields = layout.get("fields") if isinstance(layout, Mapping) else None
        if isinstance(fields, list):
            observed_fields_by_type[type_name].extend(field for field in fields if isinstance(field, Mapping))
    hkclasses: List[Dict[str, object]] = []
    real_hkclass_by_name = _hkx_real_hkclass_metadata_by_name(summary)
    emitted_real_names: set[str] = set()
    for type_info in summary.type_infos:
        display_name = type_info.display_name
        observed_fields = observed_fields_by_type.get(display_name, ())
        real_class = real_hkclass_by_name.get(display_name) or real_hkclass_by_name.get(type_info.name)
        if real_class is not None:
            member_rows = _hkx_real_hkclass_member_rows(real_class)
            class_metadata = _hkx_real_hkclass_metadata_document(real_class, member_rows)
            emitted_real_names.add(str(real_class.get("name") or display_name))
        else:
            member_rows = _hkx_havok_synthetic_member_rows(display_name, observed_fields)
            if not member_rows and display_name != type_info.name:
                member_rows = _hkx_havok_synthetic_member_rows(type_info.name, observed_fields)
            class_metadata = _hkx_havok_class_metadata(type_info, member_rows, observed_fields)
        hkclasses.append(
            {
                "id": f"#type{type_info.index}",
                "name": display_name,
                "base_name": type_info.name,
                "index": type_info.index,
                **class_metadata,
                "template_parameters": [
                    {"name": name, "value": value}
                    for name, value in type_info.template_parameters
                ],
                "members": member_rows,
            }
        )
    for real_name, real_class in sorted(real_hkclass_by_name.items()):
        if real_name in emitted_real_names:
            continue
        member_rows = _hkx_real_hkclass_member_rows(real_class)
        class_metadata = _hkx_real_hkclass_metadata_document(real_class, member_rows)
        hkclasses.append(
            {
                "id": f"#realtype{real_class.get('record_index')}",
                "name": real_name,
                "base_name": real_name,
                "index": real_class.get("record_index"),
                **class_metadata,
                "template_parameters": [],
                "members": member_rows,
            }
        )
    return hkclasses
