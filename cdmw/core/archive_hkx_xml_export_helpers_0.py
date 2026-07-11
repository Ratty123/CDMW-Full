from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_havok_xml_param_text',
    '_hkx_xml_scalar',
    'json',
)
def _hkx_xml_add_havok_param_rows(param_element: ET.Element, field: Mapping[str, object]) -> None:
    value = field.get("value")
    if not isinstance(value, list):
        return
    if not value:
        return
    if not (
        str(field.get("array_status") or "") in {"row_list", "scalar_list", "fixed_rows"}
        or str(field.get("type") or "").startswith("hkArray<")
    ):
        return
    for index, row in enumerate(value[:512]):
        if isinstance(row, Mapping):
            row_element = ET.SubElement(param_element, "row", {"index": _hkx_xml_scalar(index)})
            row_element.text = json.dumps(row, sort_keys=True)
        elif isinstance(row, (list, tuple)):
            row_element = ET.SubElement(param_element, "row", {"index": _hkx_xml_scalar(index)})
            row_element.text = " ".join(_hkx_havok_xml_param_text(component) for component in row)
        else:
            ET.SubElement(
                param_element,
                "row",
                {
                    "index": _hkx_xml_scalar(index),
                    "value": _hkx_xml_scalar(row),
                },
            )
    if len(value) > 512:
        ET.SubElement(param_element, "cdmwTruncatedRows", {"count": _hkx_xml_scalar(len(value) - 512)})


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_modding_readiness(parent: ET.Element, readiness: object) -> Optional[ET.Element]:
    if not isinstance(readiness, Mapping):
        return None
    readiness_element = ET.SubElement(
        parent,
        "hkxModdingReadiness",
        {
            "format": str(readiness.get("format") or ""),
            "native_format": str(readiness.get("native_format") or ""),
            "status": str(readiness.get("status") or ""),
            "source": str(readiness.get("source") or ""),
            "per_file_label": str(readiness.get("per_file_label") or ""),
            "fixed_size_patch_importable": _hkx_xml_scalar(readiness.get("fixed_size_patch_importable")),
            "havok_xml_importable": _hkx_xml_scalar(readiness.get("havok_xml_importable")),
            "new_editable_fields_enabled": _hkx_xml_scalar(readiness.get("new_editable_fields_enabled")),
            "decoded_object_count": _hkx_xml_scalar(readiness.get("decoded_object_count")),
            "patchable_slot_count": _hkx_xml_scalar(readiness.get("patchable_slot_count")),
            "fixup_backed_reference_edge_count": _hkx_xml_scalar(
                readiness.get("fixup_backed_reference_edge_count")
            ),
            "owner_array_count": _hkx_xml_scalar(readiness.get("owner_array_count")),
            "unresolved_or_packed_case_count": _hkx_xml_scalar(
                readiness.get("unresolved_or_packed_case_count")
            ),
            "modding_path": str(readiness.get("modding_path") or ""),
            "havok_xml_policy": str(readiness.get("havok_xml_policy") or ""),
            "read_only": "true",
            "imported": "false",
        },
    )
    _hkx_xml_add_text(readiness_element, "description", readiness.get("description", ""))
    labels = readiness.get("readiness_labels")
    if isinstance(labels, list):
        labels_element = ET.SubElement(readiness_element, "readinessLabels")
        for label in labels:
            _hkx_xml_add_text(labels_element, "label", label)
    gate = readiness.get("semantic_writer_gate")
    if isinstance(gate, Mapping):
        gate_element = ET.SubElement(
            readiness_element,
            "semanticWriterGate",
            {
                "status": str(gate.get("status") or ""),
                "mode": str(gate.get("mode") or ""),
                "enabled": _hkx_xml_scalar(gate.get("enabled")),
                "raw_preserving_no_edit_writer_required": _hkx_xml_scalar(
                    gate.get("raw_preserving_no_edit_writer_required")
                ),
                "semantic_rebuild_supported": _hkx_xml_scalar(gate.get("semantic_rebuild_supported")),
                "fixed_size_value_edits_allowed": _hkx_xml_scalar(gate.get("fixed_size_value_edits_allowed")),
                "havok_xml_import_unblocked": _hkx_xml_scalar(gate.get("havok_xml_import_unblocked")),
                "no_edit_binary_writer_status": str(gate.get("no_edit_binary_writer_status") or ""),
                "byte_identical_no_edit_rebuild_supported": _hkx_xml_scalar(
                    gate.get("byte_identical_no_edit_rebuild_supported")
                ),
                "read_model_write_pipeline": str(gate.get("read_model_write_pipeline") or ""),
            },
        )
        for list_key, tag_name in (
            ("allowed_edits", "allowedEdits"),
            ("blocked_edits", "blockedEdits"),
            ("requirements", "requirements"),
        ):
            values = gate.get(list_key)
            if isinstance(values, list):
                list_element = ET.SubElement(gate_element, tag_name)
                child_name = "edit" if tag_name.endswith("Edits") else "requirement"
                for value in values:
                    _hkx_xml_add_text(list_element, child_name, value)
    task_groups = readiness.get("task_groups")
    if isinstance(task_groups, list):
        groups_element = ET.SubElement(readiness_element, "taskGroups")
        for group in task_groups:
            if not isinstance(group, Mapping):
                continue
            group_element = ET.SubElement(
                groups_element,
                "group",
                {
                    "key": str(group.get("key") or ""),
                    "label": str(group.get("label") or ""),
                    "readiness_label": str(group.get("readiness_label") or ""),
                    "patchable_slot_count": _hkx_xml_scalar(group.get("patchable_slot_count")),
                    "context_record_count": _hkx_xml_scalar(group.get("context_record_count")),
                    "risk": str(group.get("risk") or ""),
                    "import_safe": _hkx_xml_scalar(group.get("import_safe")),
                },
            )
            _hkx_xml_add_text(group_element, "description", group.get("description", ""))
            evidence = group.get("evidence")
            if isinstance(evidence, list):
                evidence_element = ET.SubElement(group_element, "evidence")
                for item in evidence:
                    _hkx_xml_add_text(evidence_element, "item", item)
    external_refs = readiness.get("external_tool_references")
    if isinstance(external_refs, list):
        refs_element = ET.SubElement(readiness_element, "externalToolReferences")
        for tool in external_refs:
            if not isinstance(tool, Mapping):
                continue
            tool_element = ET.SubElement(
                refs_element,
                "tool",
                {
                    "name": str(tool.get("name") or ""),
                    "integration": str(tool.get("integration") or ""),
                },
            )
            _hkx_xml_add_text(tool_element, "use", tool.get("use", ""))
            _hkx_xml_add_text(tool_element, "limitation", tool.get("limitation", ""))
    return readiness_element


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_modding_workspace(parent: ET.Element, workspace: object) -> Optional[ET.Element]:
    if not isinstance(workspace, Mapping):
        return None
    workspace_element = ET.SubElement(
        parent,
        "moddingWorkspaceV1",
        {
            "format": str(workspace.get("format") or ""),
            "read_only": "true",
            "imported": "false",
            "default_view": _hkx_xml_scalar(workspace.get("default_view")),
            "readiness_label": str(workspace.get("readiness_label") or ""),
            "row_count": _hkx_xml_scalar(workspace.get("row_count")),
            "patchable_row_count": _hkx_xml_scalar(workspace.get("patchable_row_count")),
            "candidate_only_row_count": _hkx_xml_scalar(workspace.get("candidate_only_row_count")),
            "blocked_row_count": _hkx_xml_scalar(workspace.get("blocked_row_count")),
            "truncated_row_count": _hkx_xml_scalar(workspace.get("truncated_row_count")),
        },
    )
    _hkx_xml_add_text(workspace_element, "description", workspace.get("description", ""))
    _hkx_xml_add_text(workspace_element, "blockedPolicy", workspace.get("blocked_policy", ""))
    task_filters = workspace.get("task_filters")
    if isinstance(task_filters, list):
        tasks_element = ET.SubElement(workspace_element, "taskFilters")
        for task in task_filters:
            if not isinstance(task, Mapping):
                continue
            ET.SubElement(
                tasks_element,
                "task",
                {
                    "key": str(task.get("key") or ""),
                    "label": str(task.get("label") or ""),
                    "patchable_count": _hkx_xml_scalar(task.get("patchable_count")),
                    "candidate_only_count": _hkx_xml_scalar(task.get("candidate_only_count")),
                    "blocked_count": _hkx_xml_scalar(task.get("blocked_count")),
                },
            )
    rows = workspace.get("rows")
    if isinstance(rows, list):
        rows_element = ET.SubElement(workspace_element, "rows", {"truncated_after": "4096"})
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            ET.SubElement(
                rows_element,
                "row",
                {
                    "task": str(row.get("task") or ""),
                    "task_label": str(row.get("task_label") or ""),
                    "sort_group": str(row.get("sort_group") or ""),
                    "source": str(row.get("source") or ""),
                    "category": str(row.get("category") or ""),
                    "category_label": str(row.get("category_label") or ""),
                    "label": str(row.get("label") or ""),
                    "owner_class": str(row.get("owner_class") or ""),
                    "member": str(row.get("member") or ""),
                    "meaning": str(row.get("meaning") or ""),
                    "import_safety": str(row.get("import_safety") or ""),
                    "structural_kind": str(row.get("structural_kind") or ""),
                    "risk": str(row.get("risk") or ""),
                    "evidence": str(row.get("evidence") or ""),
                    "linked_by": str(row.get("linked_by") or ""),
                    "record": str(row.get("record") or ""),
                    "item": str(row.get("item") or ""),
                    "offset": str(row.get("offset") or ""),
                    "byte_size": str(row.get("byte_size") or ""),
                    "original": str(row.get("original") or ""),
                    "current": str(row.get("current") or ""),
                    "linked_target": str(row.get("linked_target") or ""),
                    "relationship_chain": str(row.get("relationship_chain") or ""),
                    "gate_status": str(row.get("gate_status") or ""),
                    "gate_reason": str(row.get("gate_reason") or ""),
                    "write_enabled": _hkx_xml_scalar(row.get("write_enabled")),
                    "import_behavior": str(row.get("import_behavior") or ""),
                },
            )
    return workspace_element


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_add_vector',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_record_interpretation(parent: ET.Element, interpretation: object) -> None:
    if not isinstance(interpretation, Mapping):
        return
    interpretation_element = ET.SubElement(
        parent,
        "interpretation",
        {"status": str(interpretation.get("field_status") or "partial_reverse_engineering")},
    )
    _hkx_xml_add_text(interpretation_element, "role", interpretation.get("role", ""))
    decoded_string = interpretation.get("decoded_string")
    if isinstance(decoded_string, Mapping):
        ET.SubElement(
            interpretation_element,
            "decodedString",
            {
                "value": str(decoded_string.get("value") or ""),
                "encoding": str(decoded_string.get("encoding") or "utf-8/null-terminated"),
                "description": str(decoded_string.get("description") or ""),
            },
        )
    shape_name_reference = interpretation.get("shape_name_reference")
    if isinstance(shape_name_reference, Mapping):
        ET.SubElement(
            interpretation_element,
            "shapeNameReference",
            {
                "raw_value": _hkx_xml_scalar(shape_name_reference.get("raw_value")),
                "hex_offset": str(shape_name_reference.get("hex_offset") or ""),
                "candidate_char_record_index": _hkx_xml_scalar(shape_name_reference.get("candidate_char_record_index")),
                "confidence": str(shape_name_reference.get("confidence") or "experimental"),
                "description": str(shape_name_reference.get("description") or ""),
            },
        )
    decoded_shape_name = interpretation.get("decoded_shape_name")
    if isinstance(decoded_shape_name, Mapping):
        ET.SubElement(
            interpretation_element,
            "decodedShapeName",
            {
                "name": str(decoded_shape_name.get("name") or ""),
                "name_record_index": _hkx_xml_scalar(decoded_shape_name.get("name_record_index")),
                "raw_name_reference": _hkx_xml_scalar(decoded_shape_name.get("raw_name_reference")),
                "confidence": str(decoded_shape_name.get("confidence") or "experimental"),
                "description": str(decoded_shape_name.get("description") or ""),
            },
        )
    for link in interpretation.get("possible_internal_links", []) if isinstance(interpretation.get("possible_internal_links"), list) else []:
        _hkx_xml_add_text(interpretation_element, "possibleInternalLink", link)
    for reference in interpretation.get("possible_record_references", []) if isinstance(interpretation.get("possible_record_references"), list) else []:
        if not isinstance(reference, Mapping):
            continue
        ET.SubElement(
            interpretation_element,
            "possibleRecordReference",
            {
                "offset": _hkx_xml_scalar(reference.get("offset")),
                "hex_offset": str(reference.get("hex_offset") or ""),
                "kind": str(reference.get("reference_kind") or ""),
                "raw_value": _hkx_xml_scalar(reference.get("raw_value")),
                "raw_value_hex": str(reference.get("raw_value_hex") or ""),
                "target_record_index": _hkx_xml_scalar(reference.get("target_record_index")),
                "target_type_index": _hkx_xml_scalar(reference.get("target_type_index")),
                "target_type_name": str(reference.get("target_type_name") or ""),
                "confidence": str(reference.get("confidence") or "experimental"),
            },
        )
    for slot in interpretation.get("finite_float_slots", []) if isinstance(interpretation.get("finite_float_slots"), list) else []:
        if not isinstance(slot, Mapping):
            continue
        ET.SubElement(
            interpretation_element,
            "finiteFloat",
            {
                "offset": _hkx_xml_scalar(slot.get("offset")),
                "hex_offset": str(slot.get("hex_offset") or ""),
                "value": _hkx_xml_scalar(slot.get("value")),
            },
        )
    for word in interpretation.get("u32_words_sample", []) if isinstance(interpretation.get("u32_words_sample"), list) else []:
        if not isinstance(word, Mapping):
            continue
        ET.SubElement(
            interpretation_element,
            "u32",
            {
                "offset": _hkx_xml_scalar(word.get("offset")),
                "hex_offset": str(word.get("hex_offset") or ""),
                "value": _hkx_xml_scalar(word.get("value")),
            },
        )
    for pair in interpretation.get("offset_count_pairs", []) if isinstance(interpretation.get("offset_count_pairs"), list) else []:
        if not isinstance(pair, Mapping):
            continue
        pair_attrs = {
            "offset": _hkx_xml_scalar(pair.get("offset")),
            "hex_offset": str(pair.get("hex_offset") or ""),
            "data_or_offset": _hkx_xml_scalar(pair.get("data_or_offset")),
            "count_or_flags": _hkx_xml_scalar(pair.get("count_or_flags")),
        }
        description = pair.get("description")
        if description:
            pair_attrs["description"] = str(description)
        ET.SubElement(interpretation_element, "offsetCountPair", pair_attrs)
    for face in interpretation.get("face_records", []) if isinstance(interpretation.get("face_records"), list) else []:
        if not isinstance(face, Mapping):
            continue
        ET.SubElement(
            interpretation_element,
            "faceRecord",
            {
                "index": _hkx_xml_scalar(face.get("index")),
                "index_start": _hkx_xml_scalar(face.get("index_start")),
                "vertex_count": _hkx_xml_scalar(face.get("vertex_count")),
                "meta": _hkx_xml_scalar(face.get("meta")),
            },
        )
    for pair in interpretation.get("uint16_pairs", []) if isinstance(interpretation.get("uint16_pairs"), list) else []:
        if not isinstance(pair, Mapping):
            continue
        ET.SubElement(
            interpretation_element,
            "uint16Pair",
            {
                "index": _hkx_xml_scalar(pair.get("index")),
                "a": _hkx_xml_scalar(pair.get("a")),
                "b": _hkx_xml_scalar(pair.get("b")),
            },
        )
    for vector_key, row_tag in (("float3_rows", "float3"), ("float4_rows", "float4")):
        rows = interpretation.get(vector_key)
        if not isinstance(rows, list):
            continue
        rows_element = ET.SubElement(interpretation_element, vector_key)
        for index, row in enumerate(rows[:128]):
            if not isinstance(row, list):
                continue
            labels = ("x", "y", "z") if vector_key == "float3_rows" else ("x", "y", "z", "w")
            if len(row) == len(labels):
                _hkx_xml_add_vector(rows_element, row_tag, row, labels, index=index)
    byte_sample = interpretation.get("byte_values_sample")
    if isinstance(byte_sample, list):
        _hkx_xml_add_text(
            interpretation_element,
            "byteValuesSample",
            " ".join(str(int(value)) for value in byte_sample if isinstance(value, int)),
            unique_value_count=interpretation.get("unique_value_count"),
        )


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_add_vector',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_advanced_editable_values(parent: ET.Element, editable_values: object) -> None:
    if not isinstance(editable_values, Mapping):
        return
    kind = str(editable_values.get("kind") or "")
    values_element = ET.SubElement(
        parent,
        "editableValues",
        {
            "kind": kind,
            "edit_rule": str(editable_values.get("edit_rule") or "same_count"),
        },
    )
    _hkx_xml_add_text(values_element, "description", editable_values.get("description", ""))
    if kind in {"float3_rows", "float4_rows"}:
        rows = editable_values.get("rows")
        if isinstance(rows, list):
            rows_element = ET.SubElement(values_element, "rows")
            labels = ("x", "y", "z") if kind == "float3_rows" else ("x", "y", "z", "w")
            tag = "v" if kind == "float3_rows" else "row"
            for index, row in enumerate(rows):
                if isinstance(row, list) and len(row) == len(labels):
                    _hkx_xml_add_vector(rows_element, tag, row, labels, index=index)
    elif kind == "face_records":
        records = editable_values.get("records")
        if isinstance(records, list):
            records_element = ET.SubElement(values_element, "records")
            for face in records:
                if not isinstance(face, Mapping):
                    continue
                ET.SubElement(
                    records_element,
                    "face",
                    {
                        "index": _hkx_xml_scalar(face.get("index")),
                        "index_start": _hkx_xml_scalar(face.get("index_start")),
                        "vertex_count": _hkx_xml_scalar(face.get("vertex_count")),
                        "meta": _hkx_xml_scalar(face.get("meta")),
                    },
                )
    elif kind == "byte_values":
        values = editable_values.get("values")
        if isinstance(values, list):
            _hkx_xml_add_text(values_element, "values", " ".join(str(int(value)) for value in values if isinstance(value, int)))
    elif kind == "uint16_pairs":
        pairs = editable_values.get("pairs")
        if isinstance(pairs, list):
            pairs_element = ET.SubElement(values_element, "pairs")
            for pair in pairs:
                if not isinstance(pair, Mapping):
                    continue
                ET.SubElement(
                    pairs_element,
                    "pair",
                    {
                        "index": _hkx_xml_scalar(pair.get("index")),
                        "a": _hkx_xml_scalar(pair.get("a")),
                        "b": _hkx_xml_scalar(pair.get("b")),
                    },
                )
    elif kind == "fixed_float_slots":
        items = editable_values.get("items")
        if isinstance(items, list):
            items_element = ET.SubElement(values_element, "items")
            for item in items:
                if not isinstance(item, Mapping):
                    continue
                item_element = ET.SubElement(
                    items_element,
                    "item",
                    {
                        "index": _hkx_xml_scalar(item.get("index")),
                        "stride": _hkx_xml_scalar(item.get("stride")),
                    },
                )
                slots = item.get("float_slots")
                if isinstance(slots, list):
                    for slot in slots:
                        if not isinstance(slot, Mapping):
                            continue
                        slot_attrs = {
                            "offset": _hkx_xml_scalar(slot.get("offset")),
                            "hex_offset": str(slot.get("hex_offset") or ""),
                            "value": _hkx_xml_scalar(slot.get("value")),
                        }
                        description = slot.get("description")
                        if description:
                            slot_attrs["description"] = str(description)
                        ET.SubElement(item_element, "float", slot_attrs)
