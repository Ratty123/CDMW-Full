from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'ET',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_hkclass_readiness_element(parent, readiness):
    readiness_element = ET.SubElement(
        parent,
        "hkclassMetadataReadiness",
        {
            "format": str(readiness.get("format") or ""),
            "status": str(readiness.get("status") or ""),
            "types_section_status": str(readiness.get("types_section_status") or ""),
            "__types_section_status": str(readiness.get("__types_section_status") or readiness.get("types_section_status") or ""),
            "real_hkclass_metadata_recovered": "true"
            if bool(readiness.get("real_hkclass_metadata_recovered"))
            else "false",
            "class_count": _hkx_xml_scalar(readiness.get("class_count")),
            "synthetic_class_count": _hkx_xml_scalar(readiness.get("synthetic_class_count")),
            "real_hkclass_metadata_class_count": _hkx_xml_scalar(
                readiness.get("real_hkclass_metadata_class_count")
            ),
            "real_hkclass_metadata_status": str(readiness.get("real_hkclass_metadata_status") or ""),
            "native_real_hkclass_metadata_class_count": _hkx_xml_scalar(
                readiness.get("native_real_hkclass_metadata_class_count")
            ),
            "native_real_hkclass_metadata_member_count": _hkx_xml_scalar(
                readiness.get("native_real_hkclass_metadata_member_count")
            ),
            "declared_member_count": _hkx_xml_scalar(readiness.get("declared_member_count")),
            "recovered_member_count": _hkx_xml_scalar(readiness.get("recovered_member_count")),
            "imported": "false",
        },
    )
    _hkx_xml_add_text(readiness_element, "description", readiness.get("description", ""))
    return readiness_element


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
)
def _hkx_xml_add_missing_hkclass_metadata(readiness_element, readiness):
    missing = readiness.get("missing_real_hkclass_metadata")
    if isinstance(missing, list):
        missing_element = ET.SubElement(readiness_element, "missingRealHkclassMetadata")
        for requirement in missing:
            if not isinstance(requirement, Mapping):
                continue
            ET.SubElement(
                missing_element,
                "requirement",
                {
                    "key": str(requirement.get("key") or ""),
                    "label": str(requirement.get("label") or ""),
                    "recovered": "true" if bool(requirement.get("recovered")) else "false",
                    "description": str(requirement.get("description") or ""),
                },
            )


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_unresolved_hkclass_counts(readiness_element, readiness):
    unresolved_counts = readiness.get("unresolved_real_metadata_counts")
    if isinstance(unresolved_counts, Mapping):
        counts_element = ET.SubElement(readiness_element, "unresolvedRealMetadataCounts")
        for key, count in unresolved_counts.items():
            ET.SubElement(counts_element, "metadata", {"key": str(key), "count": _hkx_xml_scalar(count)})


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_native_model_graph_readiness(readiness_element, readiness):
    native_model_graph = readiness.get("native_model_graph")
    if isinstance(native_model_graph, Mapping):
        native_element = ET.SubElement(
            readiness_element,
            "nativeModelGraph",
            {
                "status": str(native_model_graph.get("status") or ""),
                "rust_low_level_parse_status": str(native_model_graph.get("rust_low_level_parse_status") or ""),
                "rust_current_scope": str(native_model_graph.get("rust_current_scope") or ""),
                "rust_parses_sections_items_fixups_objects": _hkx_xml_scalar(
                    native_model_graph.get("rust_parses_sections_items_fixups_objects")
                ),
                "python_builds_richer_graph_export": _hkx_xml_scalar(
                    native_model_graph.get("python_builds_richer_graph_export")
                ),
                "native_backend_available": _hkx_xml_scalar(native_model_graph.get("native_backend_available")),
                "native_object_records_available": _hkx_xml_scalar(
                    native_model_graph.get("native_object_records_available")
                ),
                "native_object_record_count": _hkx_xml_scalar(native_model_graph.get("native_object_record_count")),
                "native_fixup_sections_available": _hkx_xml_scalar(
                    native_model_graph.get("native_fixup_sections_available")
                ),
                "native_fixup_section_count": _hkx_xml_scalar(native_model_graph.get("native_fixup_section_count")),
                "native_fixup_semantics_available": _hkx_xml_scalar(
                    native_model_graph.get("native_fixup_semantics_available")
                ),
                "native_object_graph_available": _hkx_xml_scalar(
                    native_model_graph.get("native_object_graph_available")
                ),
                "native_fixup_backed_reference_graph_available": _hkx_xml_scalar(
                    native_model_graph.get("native_fixup_backed_reference_graph_available")
                ),
                "native_relationship_graph_available": _hkx_xml_scalar(
                    native_model_graph.get("native_relationship_graph_available")
                ),
                "native_owner_array_resolution_available": _hkx_xml_scalar(
                    native_model_graph.get("native_owner_array_resolution_available")
                ),
                "native_root_container_semantics_available": _hkx_xml_scalar(
                    native_model_graph.get("native_root_container_semantics_available")
                ),
                "native_model_graph_node_count": _hkx_xml_scalar(
                    native_model_graph.get("native_model_graph_node_count")
                ),
                "native_model_graph_edge_count": _hkx_xml_scalar(
                    native_model_graph.get("native_model_graph_edge_count")
                ),
                "native_model_graph_fixup_backed_reference_edge_count": _hkx_xml_scalar(
                    native_model_graph.get("native_model_graph_fixup_backed_reference_edge_count")
                ),
                "native_model_graph_owner_array_count": _hkx_xml_scalar(
                    native_model_graph.get("native_model_graph_owner_array_count")
                ),
                "native_writer_model_available": _hkx_xml_scalar(
                    native_model_graph.get("native_writer_model_available")
                ),
                "native_no_edit_binary_writer_available": _hkx_xml_scalar(
                    native_model_graph.get("native_no_edit_binary_writer_available")
                ),
                "native_no_edit_byte_identical": _hkx_xml_scalar(
                    native_model_graph.get("native_no_edit_byte_identical")
                ),
                "native_no_edit_roundtrip_mode": str(
                    native_model_graph.get("native_no_edit_roundtrip_mode") or ""
                ),
                "native_havok_xml_export_available": _hkx_xml_scalar(
                    native_model_graph.get("native_havok_xml_export_available")
                ),
                "python_relationship_graph_node_count": _hkx_xml_scalar(
                    native_model_graph.get("python_relationship_graph_node_count")
                ),
                "python_relationship_graph_edge_count": _hkx_xml_scalar(
                    native_model_graph.get("python_relationship_graph_edge_count")
                ),
                "graph_source": str(native_model_graph.get("graph_source") or ""),
            },
        )
        python_scope = native_model_graph.get("python_richer_graph_export_scope")
        if isinstance(python_scope, list):
            scope_element = ET.SubElement(native_element, "pythonRicherGraphExportScope")
            for item in python_scope:
                _hkx_xml_add_text(scope_element, "scope", item)
        capabilities = native_model_graph.get("required_native_graph_capabilities")
        if isinstance(capabilities, list):
            capabilities_element = ET.SubElement(native_element, "requiredNativeGraphCapabilities")
            for capability in capabilities:
                if not isinstance(capability, Mapping):
                    continue
                ET.SubElement(
                    capabilities_element,
                    "capability",
                    {
                        "key": str(capability.get("key") or ""),
                        "label": str(capability.get("label") or ""),
                        "available": _hkx_xml_scalar(capability.get("available")),
                        "status": str(capability.get("status") or ""),
                        "description": str(capability.get("description") or ""),
                    },
                )
        blocked_until = native_model_graph.get("blocked_until")
        if isinstance(blocked_until, list):
            for reason in blocked_until:
                _hkx_xml_add_text(native_element, "blockedUntil", reason)
        native_graph_root = native_model_graph.get("native_model_graph_root")
        if isinstance(native_graph_root, Mapping):
            root_element = ET.SubElement(
                native_element,
                "nativeGraphRoot",
                {
                    "record_index": _hkx_xml_scalar(native_graph_root.get("record_index")),
                    "type_name": str(native_graph_root.get("type_name") or ""),
                    "method": str(native_graph_root.get("method") or ""),
                    "confidence": str(native_graph_root.get("confidence") or ""),
                    "named_variant_count": _hkx_xml_scalar(native_graph_root.get("named_variant_count")),
                },
            )
            named_variants = native_graph_root.get("named_variants")
            if isinstance(named_variants, list):
                for variant in named_variants:
                    if not isinstance(variant, Mapping):
                        continue
                    ET.SubElement(
                        root_element,
                        "namedVariant",
                        {
                            "variant_record_index": _hkx_xml_scalar(variant.get("variant_record_index")),
                            "name": str(variant.get("name") or ""),
                            "class_name": str(variant.get("class_name") or ""),
                            "object_record_index": _hkx_xml_scalar(variant.get("object_record_index")),
                            "object_type_name": str(variant.get("object_type_name") or ""),
                            "confidence": str(variant.get("confidence") or ""),
                        },
                    )


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_biggest_hkclass_gate(readiness_element, readiness):
    biggest_gate = readiness.get("biggest_remaining_gate")
    if isinstance(biggest_gate, Mapping):
        gate_element = ET.SubElement(
            readiness_element,
            "biggestRemainingGate",
            {
                "key": str(biggest_gate.get("key") or ""),
                "priority": str(biggest_gate.get("priority") or ""),
                "status": str(biggest_gate.get("status") or ""),
                "native_read_model_write_available": _hkx_xml_scalar(
                    biggest_gate.get("native_read_model_write_available")
                ),
                "byte_identical_no_edit_rebuild_supported": _hkx_xml_scalar(
                    biggest_gate.get("byte_identical_no_edit_rebuild_supported")
                ),
                "havok_xml_import_blocked": _hkx_xml_scalar(biggest_gate.get("havok_xml_import_blocked")),
            },
        )
        _hkx_xml_add_text(gate_element, "description", biggest_gate.get("description", ""))
        roles = biggest_gate.get("representative_file_roles")
        if isinstance(roles, list):
            roles_element = ET.SubElement(gate_element, "representativeFileRoles")
            for role in roles:
                ET.SubElement(roles_element, "role", {"name": str(role)})
        gate_blockers = biggest_gate.get("blocked_until")
        if isinstance(gate_blockers, list):
            for reason in gate_blockers:
                _hkx_xml_add_text(gate_element, "blockedUntil", reason)


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_no_edit_writer_readiness(readiness_element, readiness):
    no_edit_writer = readiness.get("no_edit_binary_writer")
    if isinstance(no_edit_writer, Mapping):
        writer_element = ET.SubElement(
            readiness_element,
            "noEditBinaryWriter",
            {
                "status": str(no_edit_writer.get("status") or ""),
                "priority": str(no_edit_writer.get("priority") or ""),
                "available": _hkx_xml_scalar(no_edit_writer.get("available")),
                "native_read_model_write_available": _hkx_xml_scalar(
                    no_edit_writer.get("native_read_model_write_available")
                ),
                "read_model_write_pipeline": str(no_edit_writer.get("read_model_write_pipeline") or ""),
                "no_edit_roundtrip_mode": str(no_edit_writer.get("no_edit_roundtrip_mode") or ""),
                "byte_identical_no_edit_rebuild_supported": _hkx_xml_scalar(
                    no_edit_writer.get("byte_identical_no_edit_rebuild_supported")
                ),
            },
        )
        _hkx_xml_add_text(writer_element, "description", no_edit_writer.get("description", ""))
        writer_roles = no_edit_writer.get("representative_file_roles")
        if isinstance(writer_roles, list):
            roles_element = ET.SubElement(writer_element, "representativeFileRoles")
            for role in writer_roles:
                ET.SubElement(roles_element, "role", {"name": str(role)})
        writer_requirements = no_edit_writer.get("requirements")
        if isinstance(writer_requirements, list):
            requirements_element = ET.SubElement(writer_element, "requirements")
            for requirement in writer_requirements:
                if not isinstance(requirement, Mapping):
                    continue
                ET.SubElement(
                    requirements_element,
                    "requirement",
                    {
                        "key": str(requirement.get("key") or ""),
                        "label": str(requirement.get("label") or ""),
                        "passed": _hkx_xml_scalar(requirement.get("passed")),
                        "status": str(requirement.get("status") or ""),
                        "description": str(requirement.get("description") or ""),
                    },
                )
        writer_blockers = no_edit_writer.get("blocked_until")
        if isinstance(writer_blockers, list):
            for reason in writer_blockers:
                _hkx_xml_add_text(writer_element, "blockedUntil", reason)


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_hkclass_internals(readiness_element, readiness):
    class_internals = readiness.get("class_internals")
    if isinstance(class_internals, Mapping):
        internals_element = ET.SubElement(
            readiness_element,
            "classInternals",
            {
                "status": str(class_internals.get("status") or ""),
                "real_class_internals_recovered": _hkx_xml_scalar(
                    class_internals.get("real_class_internals_recovered")
                ),
                "target_count": _hkx_xml_scalar(class_internals.get("target_count")),
                "observed_target_count": _hkx_xml_scalar(class_internals.get("observed_target_count")),
            },
        )
        _hkx_xml_add_text(internals_element, "description", class_internals.get("description", ""))
        targets = class_internals.get("targets")
        if isinstance(targets, list):
            targets_element = ET.SubElement(internals_element, "targets")
            for target in targets:
                if not isinstance(target, Mapping):
                    continue
                target_element = ET.SubElement(
                    targets_element,
                    "target",
                    {
                        "class": str(target.get("class") or ""),
                        "present_in_file": _hkx_xml_scalar(target.get("present_in_file")),
                        "status": str(target.get("status") or ""),
                        "real_internals_recovered": _hkx_xml_scalar(target.get("real_internals_recovered")),
                        "source": str(target.get("source") or ""),
                    },
                )
                _hkx_xml_add_text(target_element, "neededInternals", target.get("needed_internals", ""))
        internals_blockers = class_internals.get("blocked_until")
        if isinstance(internals_blockers, list):
            for reason in internals_blockers:
                _hkx_xml_add_text(internals_element, "blockedUntil", reason)


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_hard_decoder_targets(readiness_element, readiness):
    hard_decoder_targets = readiness.get("hard_decoder_targets")
    if isinstance(hard_decoder_targets, Mapping):
        hard_element = ET.SubElement(
            readiness_element,
            "hardDecoderTargets",
            {
                "status": str(hard_decoder_targets.get("status") or ""),
                "target_count": _hkx_xml_scalar(hard_decoder_targets.get("target_count")),
                "observed_target_count": _hkx_xml_scalar(hard_decoder_targets.get("observed_target_count")),
                "unresolved_target_count": _hkx_xml_scalar(hard_decoder_targets.get("unresolved_target_count")),
                "native_evidence_status": str(hard_decoder_targets.get("native_evidence_status") or ""),
                "native_total_observed_byte_count": _hkx_xml_scalar(
                    hard_decoder_targets.get("native_total_observed_byte_count")
                ),
            },
        )
        _hkx_xml_add_text(hard_element, "description", hard_decoder_targets.get("description", ""))
        targets = hard_decoder_targets.get("targets")
        if isinstance(targets, list):
            targets_element = ET.SubElement(hard_element, "targets")
            for target in targets:
                if not isinstance(target, Mapping):
                    continue
                target_element = ET.SubElement(
                    targets_element,
                    "target",
                    {
                        "key": str(target.get("key") or ""),
                        "label": str(target.get("label") or ""),
                        "present_in_file": _hkx_xml_scalar(target.get("present_in_file")),
                        "status": str(target.get("status") or ""),
                        "proof_status": str(target.get("proof_status") or ""),
                        "resolved": _hkx_xml_scalar(target.get("resolved")),
                        "import_blocking": _hkx_xml_scalar(target.get("import_blocking")),
                        "observed_record_count": _hkx_xml_scalar(target.get("observed_record_count")),
                        "observed_byte_count": _hkx_xml_scalar(target.get("observed_byte_count")),
                        "confidence": str(target.get("confidence") or ""),
                    },
                )
                prefixes = target.get("class_prefixes")
                if isinstance(prefixes, list):
                    prefixes_element = ET.SubElement(target_element, "classPrefixes")
                    for prefix in prefixes:
                        ET.SubElement(prefixes_element, "classPrefix", {"name": str(prefix)})
                observed_types = target.get("observed_types")
                if isinstance(observed_types, list) and observed_types:
                    observed_types_element = ET.SubElement(target_element, "observedTypes")
                    for type_name in observed_types:
                        ET.SubElement(observed_types_element, "type", {"name": str(type_name)})
                observed_fields = target.get("observed_fields")
                if isinstance(observed_fields, list) and observed_fields:
                    observed_fields_element = ET.SubElement(target_element, "observedFields")
                    for field_name in observed_fields[:64]:
                        ET.SubElement(observed_fields_element, "field", {"name": str(field_name)})
                record_indices = target.get("record_indices")
                if isinstance(record_indices, list) and record_indices:
                    record_indices_element = ET.SubElement(target_element, "recordIndices")
                    for record_index in record_indices[:64]:
                        ET.SubElement(record_indices_element, "record", {"index": _hkx_xml_scalar(record_index)})
                unresolved_blockers = target.get("unresolved_blockers")
                if isinstance(unresolved_blockers, list):
                    for blocker in unresolved_blockers:
                        _hkx_xml_add_text(target_element, "unresolvedBlocker", blocker)
                _hkx_xml_add_text(target_element, "description", target.get("description", ""))


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_hkclass_gui_readiness(readiness_element, readiness):
    gui_readiness = readiness.get("gui_readiness")
    if isinstance(gui_readiness, Mapping):
        gui_element = ET.SubElement(
            readiness_element,
            "guiReadiness",
            {
                "status": str(gui_readiness.get("status") or ""),
                "target_count": _hkx_xml_scalar(gui_readiness.get("target_count")),
                "partial_target_count": _hkx_xml_scalar(gui_readiness.get("partial_target_count")),
                "missing_target_count": _hkx_xml_scalar(gui_readiness.get("missing_target_count")),
            },
        )
        _hkx_xml_add_text(gui_element, "description", gui_readiness.get("description", ""))
        targets = gui_readiness.get("targets")
        if isinstance(targets, list):
            targets_element = ET.SubElement(gui_element, "targets")
            for target in targets:
                if not isinstance(target, Mapping):
                    continue
                ET.SubElement(
                    targets_element,
                    "target",
                    {
                        "key": str(target.get("key") or ""),
                        "label": str(target.get("label") or ""),
                        "status": str(target.get("status") or ""),
                        "complete": _hkx_xml_scalar(target.get("complete")),
                        "description": str(target.get("description") or ""),
                    },
                )


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
)
def _hkx_xml_add_hkclass_import_safety(readiness_element, readiness):
    import_safety = readiness.get("import_safety")
    if isinstance(import_safety, Mapping):
        safety_element = ET.SubElement(
            readiness_element,
            "importSafety",
            {
                "havok_xml_types_importable": "true"
                if bool(import_safety.get("havok_xml_types_importable"))
                else "false",
            },
        )
        _hkx_xml_add_text(safety_element, "reason", import_safety.get("reason", ""))


@bind_archive_hkx_globals(
    'ET',
    '_hkx_xml_add_text',
)
def _hkx_xml_mesh_details_element(parent, mesh_details):
    mesh_element = ET.SubElement(
        parent,
        "mesh_details",
        {
            "status": str(mesh_details.get("status") or "read_only_schema_recovery"),
            "editable": "false",
            "imported": "false",
        },
    )
    _hkx_xml_add_text(mesh_element, "warning", mesh_details.get("warning", ""))
    return mesh_element


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_mesh_detail_summary(mesh_element, mesh_details):
    editability = mesh_details.get("editability")
    if isinstance(editability, Mapping):
        editability_element = ET.SubElement(
            mesh_element,
            "editability",
            {
                "editable": _hkx_xml_scalar(editability.get("editable")),
                "status": str(editability.get("status") or ""),
                "safe_current_behavior": str(editability.get("safe_current_behavior") or ""),
            },
        )
        blocked_operations = editability.get("blocked_operations")
        if isinstance(blocked_operations, list):
            for operation in blocked_operations:
                _hkx_xml_add_text(editability_element, "blockedOperation", operation)
        supported_operations = editability.get("supported_safe_operations")
        if isinstance(supported_operations, list):
            for operation in supported_operations:
                _hkx_xml_add_text(editability_element, "supportedSafeOperation", operation)
        next_targets = editability.get("next_decoder_targets")
        if isinstance(next_targets, list):
            for target in next_targets:
                _hkx_xml_add_text(editability_element, "nextDecoderTarget", target)
    primitive_analysis = mesh_details.get("primitive_analysis_summary")
    if isinstance(primitive_analysis, list) and primitive_analysis:
        analysis_element = ET.SubElement(mesh_element, "primitiveAnalysisSummary", {"read_only": "true"})
        for row in primitive_analysis:
            if not isinstance(row, Mapping):
                continue
            ET.SubElement(
                analysis_element,
                "record",
                {
                    "record_index": _hkx_xml_scalar(row.get("record_index")),
                    "count": _hkx_xml_scalar(row.get("count")),
                    "low_u16_unique_count": _hkx_xml_scalar(row.get("low_u16_unique_count")),
                    "high_u16_unique_count": _hkx_xml_scalar(row.get("high_u16_unique_count")),
                    "candidate_index_range": _hkx_xml_scalar(row.get("candidate_index_range")),
                    "candidate_index_unique_count": _hkx_xml_scalar(row.get("candidate_index_unique_count")),
                    "candidate_triangle_count": _hkx_xml_scalar(row.get("candidate_triangle_count")),
                    "candidate_quad_count": _hkx_xml_scalar(row.get("candidate_quad_count")),
                    "candidate_degenerate_count": _hkx_xml_scalar(row.get("candidate_degenerate_count")),
                    "topology_candidate_status": str(row.get("topology_candidate_status") or ""),
                },
            )
    descriptions = mesh_details.get("descriptions")
    if isinstance(descriptions, Mapping):
        descriptions_element = ET.SubElement(mesh_element, "descriptions")
        for key, value in descriptions.items():
            _hkx_xml_add_text(descriptions_element, "field", value, name=str(key))


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_int_list',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_mesh_nested_rows(record_element, record_info):
    for nested_key, nested_tag, child_tag in (
        ("rows", "rows", "row"),
        ("primitive_words", "primitive_words", "primitive"),
        ("nodes", "nodes", "node"),
        ("entries", "entries", "entry"),
    ):
        nested_rows = record_info.get(nested_key)
        if not isinstance(nested_rows, list):
            continue
        nested_element = ET.SubElement(
            record_element,
            nested_tag,
            {
                "read_only": "true",
                "shown_count": str(len(nested_rows)),
                "truncated_count": _hkx_xml_scalar(
                    record_info.get(
                        {
                            "rows": "truncated_rows",
                            "primitive_words": "truncated_primitives",
                            "nodes": "truncated_nodes",
                            "entries": "truncated_entries",
                        }[nested_key]
                    )
                ),
            },
        )
        for row in nested_rows:
            if not isinstance(row, Mapping):
                continue
            attrs = {"index": _hkx_xml_scalar(row.get("index"))}
            for key in (
                "packed_u32",
                "hex",
                "low_u16",
                "high_u16",
                "raw_hex",
                "candidate_kind",
                "description",
            ):
                if row.get(key) is not None:
                    attrs[key] = _hkx_xml_scalar(row.get(key))
            row_element = ET.SubElement(nested_element, child_tag, attrs)
            _hkx_xml_add_int_list(row_element, "byte_indices", row.get("byte_indices"))
            _hkx_xml_add_int_list(row_element, "candidate_vertex_indices", row.get("candidate_vertex_indices"))
            _hkx_xml_add_int_list(row_element, "candidate_min_bytes", row.get("candidate_min_bytes"))
            _hkx_xml_add_int_list(row_element, "candidate_max_bytes", row.get("candidate_max_bytes"))
            _hkx_xml_add_int_list(row_element, "child_or_primitive_bytes", row.get("child_or_primitive_bytes"))
            _hkx_xml_add_int_list(row_element, "u32_words", row.get("u32_words"))
            _hkx_xml_add_int_list(row_element, "u32_words_sample", row.get("u32_words_sample"))
            _hkx_xml_add_int_list(row_element, "u16_words_sample", row.get("u16_words_sample"))
            row_candidate_layout = row.get("candidate_layout")
            if isinstance(row_candidate_layout, Mapping):
                row_layout_element = ET.SubElement(
                    row_element,
                    "candidateLayout",
                    {
                        "read_only": "true",
                        "status": str(row_candidate_layout.get("status") or ""),
                        "confidence": str(row_candidate_layout.get("confidence") or ""),
                    },
                )
                layout_fields = row_candidate_layout.get("fields")
                if isinstance(layout_fields, list):
                    for field in layout_fields:
                        if isinstance(field, Mapping):
                            ET.SubElement(
                                row_layout_element,
                                "field",
                                {
                                    "name": str(field.get("name") or ""),
                                    "offset": _hkx_xml_scalar(field.get("offset")),
                                    "value": _hkx_xml_scalar(field.get("value")),
                                    "description": str(field.get("description") or ""),
                                    "target_type_name": str(field.get("target_type_name") or ""),
                                    "target_data_offset": _hkx_xml_scalar(field.get("target_data_offset")),
                                    "target_bias": _hkx_xml_scalar(field.get("target_bias")),
                                    "target_record_index": _hkx_xml_scalar(field.get("target_record_index")),
                                    "target_resolution": str(field.get("target_resolution") or ""),
                                    "target_description": str(field.get("target_description") or ""),
                                },
                            )
            row_slots = row.get("finite_float_slots")
            if isinstance(row_slots, list):
                row_slots_element = ET.SubElement(row_element, "finite_float_slots", {"read_only": "true"})
                for slot in row_slots:
                    if isinstance(slot, Mapping):
                        ET.SubElement(
                            row_slots_element,
                            "float",
                            {
                                "offset": _hkx_xml_scalar(slot.get("offset")),
                                "hex_offset": str(slot.get("hex_offset") or ""),
                                "value": _hkx_xml_scalar(slot.get("value")),
                            },
                        )


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_int_list',
    '_hkx_xml_add_mesh_nested_rows',
    '_hkx_xml_add_mesh_record_attrs',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_mesh_record(group_element, row_tag, record_info):
    record_element = _hkx_xml_add_mesh_record_attrs(group_element, row_tag, record_info)
    raw = record_info.get("raw_preservation")
    if isinstance(raw, Mapping):
        ET.SubElement(
            record_element,
            "raw_preservation",
            {
                "sha1": str(raw.get("sha1") or ""),
                "sample_byte_count": _hkx_xml_scalar(raw.get("sample_byte_count")),
                "sample_hex": str(raw.get("sample_hex") or ""),
            },
        )
    _hkx_xml_add_int_list(record_element, "u32_words_sample", record_info.get("u32_words_sample"))
    candidate_layout = record_info.get("candidate_layout")
    if isinstance(candidate_layout, Mapping):
        layout_element = ET.SubElement(
            record_element,
            "candidateLayout",
            {
                "read_only": "true",
                "status": str(candidate_layout.get("status") or ""),
                "confidence": str(candidate_layout.get("confidence") or ""),
            },
        )
        _hkx_xml_add_text(layout_element, "description", candidate_layout.get("description", ""))
        layout_fields = candidate_layout.get("fields")
        if isinstance(layout_fields, list):
            for field in layout_fields:
                if isinstance(field, Mapping):
                    ET.SubElement(
                        layout_element,
                        "field",
                        {
                            "name": str(field.get("name") or ""),
                            "offset": _hkx_xml_scalar(field.get("offset")),
                            "value": _hkx_xml_scalar(field.get("value")),
                            "description": str(field.get("description") or ""),
                            "target_type_name": str(field.get("target_type_name") or ""),
                            "target_data_offset": _hkx_xml_scalar(field.get("target_data_offset")),
                            "target_bias": _hkx_xml_scalar(field.get("target_bias")),
                            "target_record_index": _hkx_xml_scalar(field.get("target_record_index")),
                            "target_resolution": str(field.get("target_resolution") or ""),
                            "target_description": str(field.get("target_description") or ""),
                        },
                    )
    slots = record_info.get("finite_float_slots")
    if isinstance(slots, list):
        slots_element = ET.SubElement(record_element, "finite_float_slots", {"read_only": "true"})
        for slot in slots:
            if not isinstance(slot, Mapping):
                continue
            ET.SubElement(
                slots_element,
                "float",
                {
                    "offset": _hkx_xml_scalar(slot.get("offset")),
                    "hex_offset": str(slot.get("hex_offset") or ""),
                    "value": _hkx_xml_scalar(slot.get("value")),
                    "description": str(slot.get("description") or ""),
                },
            )
    _hkx_xml_add_mesh_nested_rows(record_element, record_info)
    _hkx_xml_add_int_list(record_element, "values_sample", record_info.get("values_sample"))


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_mesh_record',
)
def _hkx_xml_add_mesh_record_group(mesh_element, mesh_details, source_key, group_tag, row_tag):
    records = mesh_details.get(source_key)
    if not isinstance(records, list):
        return
    group_element = ET.SubElement(mesh_element, group_tag, {"record_count": str(len(records))})
    for record_info in records:
        if isinstance(record_info, Mapping):
            _hkx_xml_add_mesh_record(group_element, row_tag, record_info)
