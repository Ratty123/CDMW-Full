from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    '_hkx_havok_xml_make_param_field',
    '_hkx_havok_xml_record_ref',
)
def _hkx_havok_specialized_group_0(hint, type_name, link_existing, add_if_missing, add_row_list_from_prefix, specialized_fields, record_by_index, object_info, summary):
    if hint is not None and type_name in {'hknpConvexShape', 'hknpBoxShape'}:
        link_existing("vertices", hint.vertex_record_index)
        link_existing("planes", hint.plane_record_index)
        link_existing("faces", hint.face_record_index)
        link_existing("faceIndices", hint.face_index_record_index)
        for edge_position, param_name in enumerate(("edgeTableA", "edgeTableB")):
            record_index = hint.edge_record_indices[edge_position] if edge_position < len(hint.edge_record_indices) else None
            link_existing(param_name, record_index)
        return True
    elif hint is not None and type_name == 'hknpSphereShape':
        target, target_type = _hkx_havok_xml_record_ref(hint.vertex_record_index, record_by_index)
        if target:
            add_if_missing(
                _hkx_havok_xml_make_param_field(
                    name="center",
                    data_type="hkFloat3",
                    text=target,
                    reference_target=target,
                    reference_kind="decoded_sphere_center",
                    reference_category="array_data_reference",
                    reference_target_type=target_type,
                    array_status="single_row_reference",
                    numelements=1,
                    confidence="strong inference",
                    description="Specialized hknpSphereShape exporter linked the center to the recovered hkFloat3 record.",
                )
            )
        return True
    elif hint is not None and type_name == 'hknpCapsuleShape':
        target, target_type = _hkx_havok_xml_record_ref(hint.vertex_record_index, record_by_index)
        if target:
            add_if_missing(
                _hkx_havok_xml_make_param_field(
                    name="vertices",
                    data_type="hkArray<hkFloat3>",
                    text=target,
                    reference_target=target,
                    reference_kind="decoded_capsule_endpoints",
                    reference_category="array_data_reference",
                    reference_target_type=target_type,
                    array_status="hkArray",
                    numelements=2,
                    confidence="strong inference",
                    description="Specialized hknpCapsuleShape exporter linked endpoint vertices to the recovered hkFloat3 record.",
                )
            )
        return True
    elif type_name == 'hknpMeshShape':
        type_targets = {
            "geometrySections": ("hkArray<hknpMeshShape::GeometrySection>", "hknpMeshShape::GeometrySection"),
            "primitives": ("hkArray<hknpMeshShape::GeometrySection::Primitive>", "hknpMeshShape::GeometrySection::Primitive"),
            "aabbTree": ("hkArray<hknpAabb8TreeNode>", "hknpAabb8TreeNode"),
            "shapeTagTable": ("hkArray<hknpMeshShape::ShapeTagTableEntry>", "hknpMeshShape::ShapeTagTableEntry"),
        }
        for param_name, (data_type, target_type_name) in type_targets.items():
            targets = [record for record in summary.item_records if record.type_name == target_type_name]
            if not targets:
                continue
            target_text = " ".join(f"#record{record.index}" for record in targets[:64])
            shown_count = len(targets[:64])
            add_if_missing(
                _hkx_havok_xml_make_param_field(
                    name=param_name,
                    data_type=data_type,
                    text=target_text,
                    value=target_text,
                    reference_target=target_text,
                    reference_kind="decoded_mesh_shape_table",
                    reference_category="array_data_reference",
                    reference_target_type=target_type_name,
                    array_status="hkArray",
                    numelements=shown_count,
                    confidence="experimental",
                    description=(
                        "Specialized hknpMeshShape exporter linked mesh table records by recovered ITEM type. "
                        "Mesh array rebuilding remains blocked."
                    ),
                )
            )
        if hint is not None:
            for param_name, value in (
                ("numGeometrySections", hint.mesh_section_count),
                ("numPrimitives", hint.mesh_primitive_count),
                ("numAabbTreeNodes", hint.mesh_aabb_node_count),
                ("numShapeTagTableEntries", hint.mesh_shape_tag_count),
            ):
                if value:
                    add_if_missing(
                        _hkx_havok_xml_make_param_field(
                            name=param_name,
                            data_type="int",
                            text=str(int(value)),
                            value=int(value),
                            confidence="strong inference",
                    description="Specialized hknpMeshShape exporter emitted a recovered table count.",
                        )
                    )
        return True
    elif type_name == 'hknpMaterial':
        add_row_list_from_prefix(
            prefix="material[",
            param_name="entries",
            data_type="hkArray<hknpMaterial>",
            confidence="experimental",
            description="Specialized hknpMaterial exporter grouped recovered material rows for browsing. Material rebuilds are not enabled.",
        )
        return True
    return False


@bind_archive_hkx_globals()
def _hkx_havok_specialized_group_1(hint, type_name, link_existing, add_if_missing, add_row_list_from_prefix, specialized_fields, record_by_index, object_info, summary):
    if type_name == 'hknpShapeProperties::Entry':
        add_row_list_from_prefix(
            prefix="property_entry[",
            param_name="entries",
            data_type="hkArray<hknpShapeProperties::Entry>",
            confidence="experimental",
            description="Specialized shape-property exporter grouped property entries. Property table rebuilds remain blocked.",
        )
        return True
    elif type_name == 'hkBone':
        add_row_list_from_prefix(
            prefix="bone[",
            param_name="bones",
            data_type="hkArray<hkBone>",
            confidence="experimental",
            description="Specialized hkBone exporter grouped bone rows for skeleton browsing. Skeleton rebuilding is not enabled.",
        )
        return True
    elif type_name == 'hkQsTransform':
        add_row_list_from_prefix(
            prefix="qs_transform[",
            param_name="transforms",
            data_type="hkArray<hkQsTransform>",
            confidence="strong inference",
            description="Specialized hkQsTransform exporter grouped translation/rotation/scale rows.",
        )
        return True
    elif type_name == 'hkaSkeletonMapperData::SimpleMapping':
        add_row_list_from_prefix(
            prefix="simple_mapping[",
            param_name="simpleMappings",
            data_type="hkArray<hkaSkeletonMapperData::SimpleMapping>",
            confidence="experimental",
            description="Specialized skeleton-mapper exporter grouped simple mapping rows for comparison.",
        )
        return True
    elif type_name == 'hknpShapeInstance':
        add_row_list_from_prefix(
            prefix="shape_instance[",
            param_name="instances",
            data_type="hkArray<hknpShapeInstance>",
            confidence="experimental",
            description="Specialized compound-shape exporter grouped child shape-instance rows.",
        )
        return True
    elif type_name == 'hkcdSimdTreeNamespace::Node':
        add_row_list_from_prefix(
            prefix="simd_tree_node[",
            param_name="nodes",
            data_type="hkArray<hkcdSimdTreeNamespace::Node>",
            confidence="experimental",
            description="Specialized tree exporter grouped recovered spatial tree node rows.",
        )
        return True
    return False


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_havok_reference_category',
    '_hkx_havok_reference_confidence',
    '_hkx_havok_xml_reference_target',
)
def _hkx_havok_view_add_reference(references, seen_reference_keys, ptch_references_for_record, object_info, reference: Mapping[str, object], *, prefer: bool = False) -> None:
    offset_value = reference.get("offset")
    if (
        not prefer
        and isinstance(offset_value, int)
        and offset_value in ptch_references_for_record
    ):
        return
    reference_key = (
        offset_value,
        reference.get("target_record_index"),
        reference.get("reference_kind"),
    )
    if reference_key in seen_reference_keys:
        return
    if prefer and isinstance(offset_value, int):
        references[:] = [
            existing
            for existing in references
            if not (isinstance(existing, Mapping) and existing.get("offset") == offset_value)
        ]
        seen_reference_keys.clear()
        for existing in references:
            seen_reference_keys.add(
                (
                    existing.get("offset"),
                    existing.get("target_record_index"),
                    existing.get("kind") or existing.get("reference_kind"),
                )
            )
    seen_reference_keys.add(reference_key)
    reference_target = str(reference.get("target") or "") or _hkx_havok_xml_reference_target(reference)
    reference_kind = str(reference.get("reference_kind") or reference.get("kind") or "")
    reference_category = str(reference.get("reference_category") or reference.get("category") or "") or _hkx_havok_reference_category(
        source_type_name=str(object_info.get("type_name") or ""),
        target_type_name=str(reference.get("target_type_name") or ""),
        offset=offset_value if isinstance(offset_value, int) else None,
    )
    reference_confidence = str(reference.get("confidence") or "") or _hkx_havok_reference_confidence(
        source_type_name=str(object_info.get("type_name") or ""),
        reference_kind=reference_kind,
        reference_category=reference_category,
    )
    references.append(
        {
            "offset": offset_value,
            "hex_offset": str(reference.get("hex_offset") or ""),
            "kind": reference_kind,
            "category": reference_category,
            "raw_value": reference.get("raw_value"),
            "raw_value_hex": str(reference.get("raw_value_hex") or ""),
            "target": reference_target,
            "target_record_index": reference.get("target_record_index"),
            "target_type_index": reference.get("target_type_index"),
            "target_type_name": str(reference.get("target_type_name") or ""),
            "target_status": str(reference.get("target_status") or ("object" if reference_target else "")),
            "confidence": reference_confidence or "experimental",
            "source": str(reference.get("source") or ""),
            "fixup_source": str(reference.get("fixup_source") or ""),
            "fixup_backed": bool(reference.get("fixup_backed")),
            "ptch_table_index": reference.get("ptch_table_index"),
            "ptch_word_index": reference.get("ptch_word_index"),
            "ptch_patch_site_index": reference.get("ptch_patch_site_index"),
            "ptch_patch_site_offset": reference.get("ptch_patch_site_offset"),
            "ptch_patch_site_hex_offset": str(reference.get("ptch_patch_site_hex_offset") or ""),
            "description": str(reference.get("description") or ""),
        }
    )


@bind_archive_hkx_globals(
    'Dict',
    'Mapping',
    '_hkx_havok_array_status_for_field',
    '_hkx_havok_confidence_for_field',
    '_hkx_havok_data_type_for_field',
    '_hkx_havok_param_name_for_field',
    '_hkx_havok_reference_category',
    '_hkx_havok_reference_confidence',
    '_hkx_havok_reference_status_for_field',
    '_hkx_havok_xml_enrich_reference_field',
    '_hkx_havok_xml_param_text',
)
def _hkx_havok_view_layout_fields(layout, object_info, references_by_offset, ptch_references_for_record, fields, references, seen_reference_keys, summary, char_strings_by_record, field_limit_per_object):
        if isinstance(layout, Mapping):
            layout_fields = layout.get("fields")
            if isinstance(layout_fields, list):
                for field in layout_fields[:field_limit_per_object]:
                    if not isinstance(field, Mapping):
                        continue
                    field_name = str(field.get("name") or "")
                    offset_value = field.get("offset")
                    reference = references_by_offset.get(offset_value) if isinstance(offset_value, int) else None
                    hkparam_text = _hkx_havok_xml_param_text(field.get("value"))
                    reference_target = ""
                    reference_kind = ""
                    reference_target_type = ""
                    reference_category = _hkx_havok_reference_status_for_field(str(object_info.get("type_name") or ""), field)
                    reference_confidence = _hkx_havok_confidence_for_field(str(object_info.get("type_name") or ""), field)
                    if isinstance(reference, Mapping):
                        reference_target = str(reference.get("target") or "")
                        reference_kind = str(reference.get("kind") or "")
                        reference_target_type = str(reference.get("target_type_name") or "")
                        schema_reference_category = _hkx_havok_reference_status_for_field(
                            str(object_info.get("type_name") or ""),
                            field,
                        )
                        if str(reference.get("target_status") or "") == "null":
                            reference_category = "null_reference"
                            reference_confidence = str(reference.get("confidence") or "strong inference")
                        elif schema_reference_category not in {"", "none", "record_reference_candidate"}:
                            reference_category = schema_reference_category
                            reference_confidence = (
                                str(reference.get("confidence") or "")
                                if bool(reference.get("fixup_backed"))
                                else _hkx_havok_reference_confidence(
                                    source_type_name=str(object_info.get("type_name") or ""),
                                    reference_kind=reference_kind,
                                    reference_category=reference_category,
                                )
                            )
                        else:
                            reference_category = str(reference.get("category") or "") or _hkx_havok_reference_category(
                                source_type_name=str(object_info.get("type_name") or ""),
                                target_type_name=reference_target_type,
                                offset=offset_value,
                                field_name=field_name,
                            )
                            reference_confidence = (
                                str(reference.get("confidence") or "")
                                if bool(reference.get("fixup_backed"))
                                else _hkx_havok_reference_confidence(
                                    source_type_name=str(object_info.get("type_name") or ""),
                                    reference_kind=reference_kind,
                                    reference_category=reference_category,
                                )
                            )
                        if str(reference.get("target_status") or "") == "null":
                            hkparam_text = "null"
                        elif reference_target and reference_confidence in {"confirmed", "strong inference"}:
                            hkparam_text = reference_target
                    source_type_name = str(object_info.get("type_name") or "")
                    field_doc: Dict[str, object] = {
                        "name": field_name,
                        "type": _hkx_havok_data_type_for_field(source_type_name, field),
                        "offset": field.get("offset"),
                        "hex_offset": str(field.get("hex_offset") or ""),
                        "size": field.get("size"),
                        "value": field.get("value"),
                        "hkparam_name": _hkx_havok_param_name_for_field(source_type_name, field),
                        "hkparam_text": hkparam_text,
                        "reference_target": reference_target,
                        "reference_kind": reference_kind,
                        "reference_category": reference_category if reference_category != "none" else "",
                        "reference_status": reference_category,
                        "reference_target_type": reference_target_type,
                        "array_status": _hkx_havok_array_status_for_field(source_type_name, field),
                        "editable": bool(field.get("editable")),
                        "confidence": reference_confidence,
                        "description": str(field.get("description") or ""),
                    }
                    if isinstance(reference, Mapping):
                        if str(reference.get("target_status") or "") == "null":
                            field_doc["value"] = None
                            field_doc["reference_target"] = ""
                            field_doc["reference_target_type"] = ""
                        if bool(reference.get("fixup_backed")):
                            field_doc["fixup_backed"] = True
                            field_doc["fixup_source"] = str(reference.get("fixup_source") or "PTCH")
                            field_doc["reference_resolution_source"] = "ptch"
                            field_doc["ptch_patch_site_offset"] = reference.get("ptch_patch_site_offset")
                            field_doc["ptch_patch_site_hex_offset"] = str(reference.get("ptch_patch_site_hex_offset") or "")
                            field_doc["ptch_word_index"] = reference.get("ptch_word_index")
                            field_doc["ptch_table_index"] = reference.get("ptch_table_index")
                            field_doc["ptch_target_status"] = str(reference.get("target_status") or "")
                            field_doc["description"] = (
                                str(field_doc.get("description") or "")
                                + " Reference is backed by a decoded PTCH patch site."
                            ).strip()
                        elif reference_target:
                            field_doc["reference_resolution_source"] = "inferred_offset"
                    _hkx_havok_xml_enrich_reference_field(
                        field_doc,
                        source_type_name=source_type_name,
                        source_field=field,
                        summary=summary,
                        char_strings_by_record=char_strings_by_record,
                        existing_reference=reference,
                    )
                    fields.append(field_doc)


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_havok_xml_apply_sibling_array_counts',
    '_hkx_havok_xml_array_value_fields',
    '_hkx_havok_xml_specialized_fields',
)
def _hkx_havok_view_finish_object(hkobjects, object_info, record_index, raw_ranges, fields, references, summary):
        fields.extend(_hkx_havok_xml_array_value_fields(object_info))
        _hkx_havok_xml_apply_sibling_array_counts(fields)
        fields = _hkx_havok_xml_specialized_fields(object_info, fields, summary)
        _hkx_havok_xml_apply_sibling_array_counts(fields)
        known_reference_offsets = {
            int(field.get("offset"))
            for field in fields
            if isinstance(field.get("offset"), int) and str(field.get("reference_target") or "")
        }
        for reference in references[:64]:
            offset_value = reference.get("offset")
            if not isinstance(offset_value, int) or offset_value in known_reference_offsets:
                continue
            target = str(reference.get("target") or "")
            if not target:
                continue
            fields.append(
                {
                    "name": f"cdmwReferenceCandidate_{reference.get('hex_offset') or f'0x{offset_value:X}'}",
                    "type": "reference-candidate",
                    "offset": offset_value,
                    "hex_offset": str(reference.get("hex_offset") or f"0x{offset_value:X}"),
                    "size": 4,
                    "value": target,
                    "hkparam_name": f"cdmwReferenceCandidate_{reference.get('hex_offset') or f'0x{offset_value:X}'}",
                    "hkparam_text": target,
                    "reference_target": target,
                    "reference_kind": str(reference.get("kind") or ""),
                    "reference_category": str(reference.get("category") or ""),
                    "reference_status": str(reference.get("category") or "record_reference_candidate"),
                    "reference_target_type": str(reference.get("target_type_name") or ""),
                    "array_status": "none",
                    "editable": False,
                    "confidence": str(reference.get("confidence") or "experimental"),
                    "description": str(reference.get("description") or ""),
                    "fixup_backed": bool(reference.get("fixup_backed")),
                    "fixup_source": str(reference.get("fixup_source") or ""),
                    "reference_resolution_source": "ptch" if bool(reference.get("fixup_backed")) else "inferred_offset",
                    "ptch_patch_site_offset": reference.get("ptch_patch_site_offset"),
                    "ptch_patch_site_hex_offset": str(reference.get("ptch_patch_site_hex_offset") or ""),
                    "ptch_word_index": reference.get("ptch_word_index"),
                    "ptch_table_index": reference.get("ptch_table_index"),
                    "ptch_target_status": str(reference.get("target_status") or ""),
                }
            )
        raw_preserved = any(isinstance(raw_range, Mapping) for raw_range in raw_ranges) if isinstance(raw_ranges, list) else False
        hkobjects.append(
            {
                "id": f"#record{record_index}" if record_index is not None else f"#record{len(hkobjects)}",
                "class": str(object_info.get("type_name") or "unknown"),
                "record_index": record_index,
                "type_index": object_info.get("type_index"),
                "count": object_info.get("count"),
                "byte_length": object_info.get("byte_length"),
                "status": object_info.get("status"),
                "confidence": object_info.get("confidence"),
                "raw_preserved": raw_preserved,
                "references": references,
                "reference_count": len(references),
                "field_count": len(fields),
                "truncated_fields": max(
                    0,
                    int(object_info.get("layout", {}).get("field_count") or len(fields)) - len(fields)
                    if isinstance(object_info.get("layout"), Mapping)
                    else 0,
                ),
                "fields": fields,
            }
        )


@bind_archive_hkx_globals(
    'Dict',
    'List',
    'Mapping',
    'Tuple',
    '_hkx_havok_view_add_reference',
    '_hkx_havok_view_finish_object',
    '_hkx_havok_view_layout_fields',
)
def _hkx_havok_view_add_object(hkobjects, object_info, summary, char_strings_by_record, ptch_references_by_owner_offset, field_limit_per_object):
    if not isinstance(object_info, Mapping):
        return
    record_index = object_info.get("record_index")
    layout = object_info.get("layout")
    raw_ranges = object_info.get("raw_ranges")
    fields: List[Dict[str, object]] = []
    references: List[Dict[str, object]] = []
    seen_reference_keys: set[Tuple[object, object, object]] = set()
    ptch_references_for_record = (
        ptch_references_by_owner_offset.get(int(record_index), {})
        if isinstance(record_index, int)
        else {}
    )
    for ptch_reference in ptch_references_for_record.values():
        if isinstance(ptch_reference, Mapping):
            _hkx_havok_view_add_reference(
                references, seen_reference_keys, ptch_references_for_record,
                object_info, ptch_reference, prefer=True,
            )
    for reference_source in (
        object_info.get("references"),
        layout.get("references") if isinstance(layout, Mapping) else None,
    ):
        if isinstance(reference_source, list):
            for reference in reference_source:
                if isinstance(reference, Mapping):
                    _hkx_havok_view_add_reference(
                        references, seen_reference_keys, ptch_references_for_record,
                        object_info, reference,
                    )
    references_by_offset: Dict[int, Dict[str, object]] = {}
    for reference in references:
        offset_value = reference.get("offset")
        if isinstance(offset_value, int) and (
            reference.get("target") or str(reference.get("target_status") or "") == "null"
        ):
            references_by_offset.setdefault(offset_value, reference)
    _hkx_havok_view_layout_fields(
        layout, object_info, references_by_offset, ptch_references_for_record,
        fields, references, seen_reference_keys, summary, char_strings_by_record, field_limit_per_object,
    )
    _hkx_havok_view_finish_object(hkobjects, object_info, record_index, raw_ranges, fields, references, summary)


@bind_archive_hkx_globals(
    'Counter',
    'Mapping',
)
def _hkx_havok_parity_collect_objects(object_rows, reference_category_counts, reference_resolution_source_counts, fixup_backed_fields_by_class, class_rows, state):
    for hkobject in object_rows:
        if not isinstance(hkobject, Mapping):
            continue
        class_name = str(hkobject.get('class') or '')
        class_row = class_rows.setdefault(class_name, {'class': class_name, 'object_count': 0, 'emitted_param_count': 0, 'havok_named_param_count': 0, 'raw_metadata_param_count': 0, 'resolved_reference_count': 0, 'unresolved_reference_count': 0, 'fixup_backed_reference_count': 0, 'ptch_resolved_reference_count': 0, 'inferred_reference_count': 0, 'fixup_backed_fields': set(), 'confidence_counts': Counter(), 'raw_preserved_object_count': 0})
        class_row['object_count'] = int(class_row['object_count']) + 1
        if bool(hkobject.get('raw_preserved')):
            class_row['raw_preserved_object_count'] = int(class_row['raw_preserved_object_count']) + 1
        fields = hkobject.get('fields')
        if isinstance(fields, list):
            state['layout_field_count'] += len(fields)
            state['emitted_param_count'] += len(fields)
            class_row['emitted_param_count'] = int(class_row['emitted_param_count']) + len(fields)
            for field in fields:
                if not isinstance(field, Mapping):
                    continue
                hkparam_name = str(field.get('hkparam_name') or field.get('name') or '')
                confidence = str(field.get('confidence') or 'experimental')
                confidence_counter = class_row.get('confidence_counts')
                if isinstance(confidence_counter, Counter):
                    confidence_counter[confidence] += 1
                if hkparam_name.startswith('cdmw'):
                    state['cdmw_raw_metadata_param_count'] += 1
                    class_row['raw_metadata_param_count'] = int(class_row['raw_metadata_param_count']) + 1
                else:
                    state['havok_named_param_count'] += 1
                    class_row['havok_named_param_count'] = int(class_row['havok_named_param_count']) + 1
                category = str(field.get('reference_category') or field.get('reference_status') or '')
                if category and category != 'none':
                    reference_category_counts[category] += 1
                if str(field.get('array_status') or '') not in {'', 'none'} and field.get('numelements') is not None:
                    state['array_params_with_numelements'] += 1
                if str(field.get('reference_target') or ''):
                    state['resolved_reference_count'] += 1
                    class_row['resolved_reference_count'] = int(class_row['resolved_reference_count']) + 1
                if bool(field.get('fixup_backed')):
                    state['ptch_fixup_backed_reference_count'] += 1
                    class_row['fixup_backed_reference_count'] = int(class_row['fixup_backed_reference_count']) + 1
                    class_row['ptch_resolved_reference_count'] = int(class_row['ptch_resolved_reference_count']) + 1
                    field_name = str(field.get('hkparam_name') or field.get('name') or '')
                    if field_name:
                        fixup_backed_fields_by_class[class_name].add(field_name)
                        fixup_fields = class_row.get('fixup_backed_fields')
                        if isinstance(fixup_fields, set):
                            fixup_fields.add(field_name)
                    source = 'ptch'
                elif str(field.get('reference_target') or ''):
                    class_row['inferred_reference_count'] = int(class_row['inferred_reference_count']) + 1
                    source = str(field.get('reference_resolution_source') or 'inferred_offset')
                else:
                    source = str(field.get('reference_resolution_source') or '')
                if source:
                    reference_resolution_source_counts[source] += 1
                    if category == 'object_reference' and source == 'ptch':
                        state['object_references_resolved_by_ptch'] += 1
                    elif category == 'object_reference' and source != 'ptch' and str(field.get('reference_target') or ''):
                        state['object_references_resolved_by_inference'] += 1
        references = hkobject.get('references')
        if isinstance(references, list):
            for reference in references:
                if not isinstance(reference, Mapping):
                    continue
                category = str(reference.get('category') or '')
                if category:
                    reference_category_counts[category] += 1
                source = 'ptch' if bool(reference.get('fixup_backed')) else 'inferred_offset' if str(reference.get('target') or '') else ''
                if source:
                    reference_resolution_source_counts[source] += 1
                if str(reference.get('target') or ''):
                    continue
                state['unresolved_reference_count'] += 1
                class_row['unresolved_reference_count'] = int(class_row['unresolved_reference_count']) + 1
