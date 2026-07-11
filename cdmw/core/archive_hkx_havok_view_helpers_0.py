from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals()
def _hkx_havok_xml_make_param_field(
    *,
    name: str,
    data_type: str,
    text: str,
    value: object = None,
    offset: object = None,
    size: object = None,
    reference_target: str = "",
    reference_kind: str = "",
    reference_category: str = "",
    reference_target_type: str = "",
    array_status: str = "none",
    numelements: Optional[int] = None,
    confidence: str = "experimental",
    description: str = "",
) -> Dict[str, object]:
    field = {
        "name": name,
        "type": data_type,
        "offset": offset,
        "hex_offset": f"0x{offset:X}" if isinstance(offset, int) else "",
        "size": size,
        "value": value if value is not None else text,
        "hkparam_name": name,
        "hkparam_text": text,
        "numelements": numelements,
        "reference_target": reference_target,
        "reference_kind": reference_kind,
        "reference_category": reference_category,
        "reference_status": reference_category or "none",
        "reference_target_type": reference_target_type,
        "array_status": array_status,
        "editable": False,
        "confidence": confidence,
        "description": description,
    }
    return field


@bind_archive_hkx_globals(
    '_hkx_havok_xml_record_ref',
)
def _hkx_havok_xml_apply_record_reference_to_field(
    field: MutableMapping[str, object],
    *,
    record_index: Optional[int],
    record_by_index: Mapping[int, HkxItemRecord],
    reference_kind: str,
    reference_category: str,
    confidence: str,
    description: str,
) -> None:
    target, target_type = _hkx_havok_xml_record_ref(record_index, record_by_index)
    if not target:
        return
    field["hkparam_text"] = target
    field["value"] = target
    field["reference_target"] = target
    field["reference_kind"] = reference_kind
    field["reference_category"] = reference_category
    field["reference_status"] = reference_category
    field["reference_target_type"] = target_type
    field["array_status"] = "hkArray" if reference_category == "array_data_reference" else str(field.get("array_status") or "none")
    field["confidence"] = confidence
    field["description"] = description


@bind_archive_hkx_globals(
    'MutableMapping',
)
def _hkx_havok_xml_stable_object_order(hkobjects: Sequence[MutableMapping[str, object]], root_id: str) -> List[str]:
    def priority(obj: Mapping[str, object]) -> Tuple[int, int, str]:
        object_id = str(obj.get("id") or "")
        class_name = str(obj.get("class") or "")
        record_index = obj.get("record_index")
        record_sort = int(record_index) if isinstance(record_index, int) else 1_000_000
        if object_id == root_id:
            return (0, record_sort, object_id)
        if class_name == "hkRootLevelContainer::NamedVariant":
            return (1, record_sort, object_id)
        if class_name in {"hknpPhysicsSceneData", "hknpPhysicsSystemData", "hknpRagdollData", "hkaAnimationContainer"}:
            return (2, record_sort, object_id)
        if class_name.startswith("hk") or class_name.startswith("hknp") or class_name.startswith("hka"):
            return (3, record_sort, object_id)
        return (4, record_sort, object_id)

    ordered = sorted((obj for obj in hkobjects if isinstance(obj, MutableMapping)), key=priority)
    for index, obj in enumerate(ordered):
        obj["stable_order_index"] = index
        obj["stable_order_key"] = f"{priority(obj)[0]}:{priority(obj)[1]:08d}:{obj.get('id') or ''}"
    return [str(obj.get("id") or "") for obj in ordered]
