from __future__ import annotations

from cdmw.core.archive_hkx_compat import bind_archive_hkx_globals


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_converter_report(root, document):
    converter_report = document.get("converter_report")
    if isinstance(converter_report, Mapping):
        report_element = ET.SubElement(
            root,
            "converterReport",
            {
                "format": str(converter_report.get("converter_format") or ""),
                "status": str(converter_report.get("status") or ""),
                "cdmw_hkx_compatibility_status": str(converter_report.get("cdmw_hkx_compatibility_status") or ""),
                "confidence": str(converter_report.get("confidence") or ""),
                "sdk_version": str(converter_report.get("sdk_version") or ""),
                "decoded_coverage": _hkx_xml_scalar(converter_report.get("decoded_coverage")),
                "payload_record_coverage": _hkx_xml_scalar(converter_report.get("payload_record_coverage")),
                "item_record_count": _hkx_xml_scalar(converter_report.get("item_record_count")),
                "payload_record_count": _hkx_xml_scalar(converter_report.get("payload_record_count")),
                "editable_record_count": _hkx_xml_scalar(converter_report.get("editable_record_count")),
                "decoded_field_count": _hkx_xml_scalar(converter_report.get("decoded_field_count")),
                "editable_slot_count": _hkx_xml_scalar(converter_report.get("editable_slot_count")),
                "raw_preserved_byte_count": _hkx_xml_scalar(converter_report.get("raw_preserved_byte_count")),
                "typed_layout_byte_count": _hkx_xml_scalar(converter_report.get("typed_layout_byte_count")),
                "candidate_layout_byte_count": _hkx_xml_scalar(converter_report.get("candidate_layout_byte_count")),
                "unresolved_layout_byte_count": _hkx_xml_scalar(converter_report.get("unresolved_layout_byte_count")),
                "reference_candidate_count": _hkx_xml_scalar(converter_report.get("reference_candidate_count")),
            },
        )
        _hkx_xml_add_text(report_element, "name", converter_report.get("name", ""))
        status_counts = converter_report.get("record_status_counts")
        if isinstance(status_counts, Mapping):
            counts_element = ET.SubElement(report_element, "recordStatusCounts")
            for status, count in status_counts.items():
                ET.SubElement(counts_element, "status", {"name": str(status), "count": _hkx_xml_scalar(count)})
        coverage_rows = converter_report.get("decode_coverage_by_type")
        if isinstance(coverage_rows, list):
            coverage_element = ET.SubElement(report_element, "decodeCoverageByType")
            for coverage in coverage_rows:
                if not isinstance(coverage, Mapping):
                    continue
                coverage_row = ET.SubElement(
                    coverage_element,
                    "type",
                    {
                        "type_name": str(coverage.get("type_name") or ""),
                        "record_count": _hkx_xml_scalar(coverage.get("record_count")),
                        "byte_length": _hkx_xml_scalar(coverage.get("byte_length")),
                        "decoded_field_count": _hkx_xml_scalar(coverage.get("decoded_field_count")),
                        "editable_slot_count": _hkx_xml_scalar(coverage.get("editable_slot_count")),
                        "reference_candidate_count": _hkx_xml_scalar(coverage.get("reference_candidate_count")),
                        "raw_preserved_byte_count": _hkx_xml_scalar(coverage.get("raw_preserved_byte_count")),
                        "typed_layout_byte_count": _hkx_xml_scalar(coverage.get("typed_layout_byte_count")),
                        "candidate_layout_byte_count": _hkx_xml_scalar(coverage.get("candidate_layout_byte_count")),
                        "unresolved_layout_byte_count": _hkx_xml_scalar(coverage.get("unresolved_layout_byte_count")),
                    },
                )
                coverage_status_counts = coverage.get("status_counts")
                if isinstance(coverage_status_counts, Mapping):
                    for status, count in coverage_status_counts.items():
                        ET.SubElement(coverage_row, "status", {"name": str(status), "count": _hkx_xml_scalar(count)})
        schema_targets = converter_report.get("schema_target_coverage")
        if isinstance(schema_targets, list):
            targets_element = ET.SubElement(report_element, "schemaTargetCoverage")
            for target in schema_targets:
                if not isinstance(target, Mapping):
                    continue
                target_element = ET.SubElement(
                    targets_element,
                    "target",
                    {
                        "type_name": str(target.get("type_name") or ""),
                        "present": _hkx_xml_scalar(target.get("present")),
                        "coverage_status": str(target.get("coverage_status") or ""),
                        "record_count": _hkx_xml_scalar(target.get("record_count")),
                        "byte_length": _hkx_xml_scalar(target.get("byte_length")),
                        "decoded_field_count": _hkx_xml_scalar(target.get("decoded_field_count")),
                        "editable_slot_count": _hkx_xml_scalar(target.get("editable_slot_count")),
                        "raw_preserved_byte_count": _hkx_xml_scalar(target.get("raw_preserved_byte_count")),
                        "typed_layout_byte_count": _hkx_xml_scalar(target.get("typed_layout_byte_count")),
                        "candidate_layout_byte_count": _hkx_xml_scalar(target.get("candidate_layout_byte_count")),
                        "unresolved_layout_byte_count": _hkx_xml_scalar(target.get("unresolved_layout_byte_count")),
                    },
                )
                target_status_counts = target.get("status_counts")
                if isinstance(target_status_counts, Mapping):
                    for status, count in target_status_counts.items():
                        ET.SubElement(target_element, "status", {"name": str(status), "count": _hkx_xml_scalar(count)})
        unknown_areas = converter_report.get("failed_or_unknown_schema_areas")
        if isinstance(unknown_areas, list):
            unknown_element = ET.SubElement(report_element, "failedOrUnknownSchemaAreas")
            for area in unknown_areas:
                if not isinstance(area, Mapping):
                    continue
                ET.SubElement(
                    unknown_element,
                    "area",
                    {
                        "priority_rank": _hkx_xml_scalar(area.get("priority_rank")),
                        "type_name": str(area.get("type_name") or ""),
                        "record_count": _hkx_xml_scalar(area.get("record_count")),
                        "raw_preserved_byte_count": _hkx_xml_scalar(area.get("raw_preserved_byte_count")),
                        "unresolved_byte_count": _hkx_xml_scalar(area.get("unresolved_byte_count")),
                        "unresolved_reason": str(area.get("unresolved_reason") or ""),
                        "raw_preserved_byte_share": _hkx_xml_scalar(area.get("raw_preserved_byte_share")),
                        "decode_category": str(area.get("decode_category") or ""),
                        "status_reason": str(area.get("status_reason") or ""),
                        "suggested_next_decoder_step": str(area.get("suggested_next_decoder_step") or ""),
                        "missing_requirements": "; ".join(
                            str(value)
                            for value in area.get("missing_requirements", [])
                            if str(value).strip()
                        )
                        if isinstance(area.get("missing_requirements"), list)
                        else str(area.get("missing_requirements") or ""),
                    },
                )
        warnings = converter_report.get("warnings")
        if isinstance(warnings, list) and warnings:
            warnings_element = ET.SubElement(report_element, "warnings")
            for warning in warnings:
                _hkx_xml_add_text(warnings_element, "warning", warning)
        records = converter_report.get("records")
        if isinstance(records, list):
            records_element = ET.SubElement(report_element, "records")
            for record_info in records:
                if not isinstance(record_info, Mapping):
                    continue
                ET.SubElement(
                    records_element,
                    "record",
                    {
                        "index": _hkx_xml_scalar(record_info.get("record_index")),
                        "type_index": _hkx_xml_scalar(record_info.get("type_index")),
                        "type_name": str(record_info.get("type_name") or ""),
                        "count": _hkx_xml_scalar(record_info.get("count")),
                        "byte_length": _hkx_xml_scalar(record_info.get("byte_length")),
                        "status": str(record_info.get("status") or ""),
                        "status_label": str(record_info.get("status_label") or ""),
                        "decode_category": str(record_info.get("decode_category") or ""),
                        "status_reason": str(record_info.get("status_reason") or ""),
                        "missing_requirements": "; ".join(
                            str(value)
                            for value in record_info.get("missing_requirements", [])
                            if str(value).strip()
                        )
                        if isinstance(record_info.get("missing_requirements"), list)
                        else str(record_info.get("missing_requirements") or ""),
                        "confidence": str(record_info.get("confidence") or ""),
                        "coverage_basis": str(record_info.get("coverage_basis") or ""),
                    },
                )


@bind_archive_hkx_globals(
    'ET',
    '_hkx_xml_scalar',
    'json',
)
def _hkx_xml_fixup_section_element(fixups_element, section):
    section_element = ET.SubElement(
        fixups_element,
        "section",
        {
            "name": str(section.get("name") or ""),
            "offset": _hkx_xml_scalar(section.get("offset")),
            "payload_byte_length": _hkx_xml_scalar(section.get("payload_byte_length")),
            "word_count": _hkx_xml_scalar(section.get("word_count")),
            "shown_word_count": _hkx_xml_scalar(section.get("shown_word_count")),
            "truncated_word_count": _hkx_xml_scalar(section.get("truncated_word_count")),
            "record_offset_match_count": _hkx_xml_scalar(section.get("record_offset_match_count")),
            "null_word_count": _hkx_xml_scalar(section.get("null_word_count")),
            "type_index_match_count": _hkx_xml_scalar(section.get("type_index_match_count")),
            "string_table_index_match_count": _hkx_xml_scalar(section.get("string_table_index_match_count")),
            "ptch_table_count": _hkx_xml_scalar(len(section.get("ptch_tables") or []) if isinstance(section.get("ptch_tables"), list) else 0),
            "varuint_status": str(section.get("varuint_status") or ""),
            "match_kind_counts": json.dumps(section.get("match_kind_counts") or {}, sort_keys=True),
            "reference_category_counts": json.dumps(section.get("reference_category_counts") or {}, sort_keys=True),
        },
    )
    return section_element


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_scalar',
    'json',
)
def _hkx_xml_add_fixup_ptch_tables(section_element, section):
    ptch_tables = section.get("ptch_tables")
    if isinstance(ptch_tables, list) and ptch_tables:
        ptch_tables_element = ET.SubElement(section_element, "ptchTables", {"read_only": "true"})
        for table in ptch_tables:
            if not isinstance(table, Mapping):
                continue
            table_element = ET.SubElement(
                ptch_tables_element,
                "ptchTable",
                {
                    "offset": _hkx_xml_scalar(table.get("offset")),
                    "hex_offset": str(table.get("hex_offset") or ""),
                    "payload_offset": _hkx_xml_scalar(table.get("payload_offset")),
                    "payload_byte_length": _hkx_xml_scalar(table.get("payload_byte_length")),
                    "word_count": _hkx_xml_scalar(table.get("word_count")),
                    "header": json.dumps(table.get("header") or []),
                    "patch_site_count": _hkx_xml_scalar(table.get("patch_site_count")),
                    "resolved_patch_site_count": _hkx_xml_scalar(table.get("resolved_patch_site_count")),
                    "null_patch_site_count": _hkx_xml_scalar(table.get("null_patch_site_count")),
                    "unresolved_patch_site_count": _hkx_xml_scalar(table.get("unresolved_patch_site_count")),
                    "confidence": str(table.get("confidence") or ""),
                },
            )
            patch_sites = table.get("patch_sites")
            if isinstance(patch_sites, list) and patch_sites:
                patch_sites_element = ET.SubElement(table_element, "patchSites", {"read_only": "true"})
                for site in patch_sites:
                    if not isinstance(site, Mapping):
                        continue
                    ET.SubElement(
                        patch_sites_element,
                        "patchSite",
                        {
                            "index": _hkx_xml_scalar(site.get("index")),
                            "ptch_word_index": _hkx_xml_scalar(site.get("ptch_word_index")),
                            "section_word_index": _hkx_xml_scalar(site.get("section_word_index")),
                            "section_word_offset": _hkx_xml_scalar(site.get("section_word_offset")),
                            "patch_site_offset": _hkx_xml_scalar(site.get("patch_site_offset")),
                            "patch_site_hex_offset": str(site.get("patch_site_hex_offset") or ""),
                            "owner_record_index": _hkx_xml_scalar(site.get("owner_record_index")),
                            "owner_type_index": _hkx_xml_scalar(site.get("owner_type_index")),
                            "owner_type_name": str(site.get("owner_type_name") or ""),
                            "owner_local_offset": _hkx_xml_scalar(site.get("owner_local_offset")),
                            "patch_value": _hkx_xml_scalar(site.get("patch_value")),
                            "target_status": str(site.get("target_status") or ""),
                            "reference_category": str(site.get("reference_category") or ""),
                            "target_record_index": _hkx_xml_scalar(site.get("target_record_index")),
                            "target_type_index": _hkx_xml_scalar(site.get("target_type_index")),
                            "target_type_name": str(site.get("target_type_name") or ""),
                            "target_data_offset": _hkx_xml_scalar(site.get("target_data_offset")),
                            "target_absolute_offset": _hkx_xml_scalar(site.get("target_absolute_offset")),
                            "confidence": str(site.get("confidence") or ""),
                        },
                    )


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_fixup_resolved_references(section_element, section):
    resolved_references = section.get("resolved_references")
    if isinstance(resolved_references, list) and resolved_references:
        resolved_element = ET.SubElement(section_element, "resolvedReferences", {"read_only": "true"})
        for reference in resolved_references:
            if not isinstance(reference, Mapping):
                continue
            ET.SubElement(
                resolved_element,
                "reference",
                {
                    "offset": _hkx_xml_scalar(reference.get("offset")),
                    "hex_offset": str(reference.get("hex_offset") or ""),
                    "value": _hkx_xml_scalar(reference.get("value")),
                    "match_kind": str(reference.get("match_kind") or ""),
                    "reference_category": str(reference.get("reference_category") or ""),
                    "target_record_index": _hkx_xml_scalar(reference.get("target_record_index")),
                    "target_type_index": _hkx_xml_scalar(reference.get("target_type_index")),
                    "target_type_name": str(reference.get("target_type_name") or ""),
                    "target_string": str(reference.get("target_string") or ""),
                    "owner_record_index": _hkx_xml_scalar(reference.get("owner_record_index")),
                    "owner_type_index": _hkx_xml_scalar(reference.get("owner_type_index")),
                    "owner_type_name": str(reference.get("owner_type_name") or ""),
                    "owner_local_offset": _hkx_xml_scalar(reference.get("owner_local_offset")),
                    "patch_value": _hkx_xml_scalar(reference.get("patch_value")),
                    "target_status": str(reference.get("target_status") or ""),
                    "confidence": str(reference.get("confidence") or ""),
                },
            )


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_fixup_words(section_element, section):
    words = section.get("words")
    if isinstance(words, list):
        words_element = ET.SubElement(section_element, "words", {"read_only": "true"})
        for word in words:
            if not isinstance(word, Mapping):
                continue
            attrs = {
                "index": _hkx_xml_scalar(word.get("index")),
                "offset": _hkx_xml_scalar(word.get("offset")),
                "hex_offset": str(word.get("hex_offset") or ""),
                "value": _hkx_xml_scalar(word.get("value")),
                "value_hex": str(word.get("value_hex") or ""),
                "match_kind": str(word.get("match_kind") or ""),
                "reference_category": str(word.get("reference_category") or ""),
                "target_record_index": _hkx_xml_scalar(word.get("target_record_index")),
                "target_type_index": _hkx_xml_scalar(word.get("target_type_index")),
                "target_type_name": str(word.get("target_type_name") or ""),
                "target_data_offset": _hkx_xml_scalar(word.get("target_data_offset")),
                "target_absolute_offset": _hkx_xml_scalar(word.get("target_absolute_offset")),
                "target_string_index": _hkx_xml_scalar(word.get("target_string_index")),
                "target_string": str(word.get("target_string") or ""),
                "owner_record_index": _hkx_xml_scalar(word.get("owner_record_index")),
                "owner_type_index": _hkx_xml_scalar(word.get("owner_type_index")),
                "owner_type_name": str(word.get("owner_type_name") or ""),
                "owner_local_offset": _hkx_xml_scalar(word.get("owner_local_offset")),
                "patch_value": _hkx_xml_scalar(word.get("patch_value")),
                "target_status": str(word.get("target_status") or ""),
                "confidence": str(word.get("confidence") or ""),
            }
            ET.SubElement(words_element, "word", attrs)


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_fixup_varuint_values(section_element, section):
    varuint_values = section.get("varuint_values")
    if isinstance(varuint_values, list) and varuint_values:
        varuint_element = ET.SubElement(section_element, "varuintValues", {"read_only": "true"})
        for row in varuint_values:
            if not isinstance(row, Mapping):
                continue
            ET.SubElement(
                varuint_element,
                "value",
                {
                    "index": _hkx_xml_scalar(row.get("index")),
                    "offset": _hkx_xml_scalar(row.get("offset")),
                    "byte_length": _hkx_xml_scalar(row.get("byte_length")),
                    "value": _hkx_xml_scalar(row.get("value")),
                    "match_kind": str(row.get("match_kind") or ""),
                    "reference_category": str(row.get("reference_category") or ""),
                    "target_record_index": _hkx_xml_scalar(row.get("target_record_index")),
                    "target_type_name": str(row.get("target_type_name") or ""),
                    "confidence": str(row.get("confidence") or ""),
                },
            )


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_xml_add_fixup_ptch_tables',
    '_hkx_xml_add_fixup_resolved_references',
    '_hkx_xml_add_fixup_varuint_values',
    '_hkx_xml_add_fixup_words',
    '_hkx_xml_fixup_section_element',
)
def _hkx_xml_add_fixup_sections(fixups_element, fixup_sections):
    for section in fixup_sections:
        if not isinstance(section, Mapping):
            continue
        section_element = _hkx_xml_fixup_section_element(fixups_element, section)
        _hkx_xml_add_fixup_ptch_tables(section_element, section)
        _hkx_xml_add_fixup_resolved_references(section_element, section)
        _hkx_xml_add_fixup_words(section_element, section)
        _hkx_xml_add_fixup_varuint_values(section_element, section)


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_fixup_sections',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
    'json',
)
def _hkx_xml_add_tagfile_reference_fixups(root, document):
    tagfile_reference_fixups = document.get("tagfile_reference_fixups")
    if not isinstance(tagfile_reference_fixups, Mapping):
        return
    fixups_element = ET.SubElement(
        root,
        "tagfileReferenceFixups",
        {
            "format": str(tagfile_reference_fixups.get("format") or ""),
            "status": str(tagfile_reference_fixups.get("status") or ""),
            "imported": "false",
            "section_count": _hkx_xml_scalar(tagfile_reference_fixups.get("section_count")),
            "ptch_table_count": _hkx_xml_scalar(tagfile_reference_fixups.get("ptch_table_count")),
            "ptch_patch_site_count": _hkx_xml_scalar(tagfile_reference_fixups.get("ptch_patch_site_count")),
            "ptch_resolved_patch_site_count": _hkx_xml_scalar(tagfile_reference_fixups.get("ptch_resolved_patch_site_count")),
            "ptch_null_patch_site_count": _hkx_xml_scalar(tagfile_reference_fixups.get("ptch_null_patch_site_count")),
            "ptch_unresolved_patch_site_count": _hkx_xml_scalar(tagfile_reference_fixups.get("ptch_unresolved_patch_site_count")),
            "match_kind_counts": json.dumps(tagfile_reference_fixups.get("match_kind_counts") or {}, sort_keys=True),
            "reference_category_counts": json.dumps(
                tagfile_reference_fixups.get("reference_category_counts") or {},
                sort_keys=True,
            ),
        },
    )
    _hkx_xml_add_text(fixups_element, "description", tagfile_reference_fixups.get("description", ""))
    fixup_sections = tagfile_reference_fixups.get("sections")
    if isinstance(fixup_sections, list):
        _hkx_xml_add_fixup_sections(fixups_element, fixup_sections)


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_havok_classes(packfile_element, hkclasses):
    if isinstance(hkclasses, list) and hkclasses:
        types_section_element = ET.SubElement(packfile_element, "hksection", {"name": "__types__"})
        for hkclass in hkclasses:
            if not isinstance(hkclass, Mapping):
                continue
            class_element = ET.SubElement(
                types_section_element,
                "hkobject",
                {
                    "name": str(hkclass.get("id") or ""),
                    "class": "hkClass",
                    "cdmw_type_index": _hkx_xml_scalar(hkclass.get("index")),
                    "cdmw_object_size": _hkx_xml_scalar(hkclass.get("object_size")),
                    "cdmw_signature": str(hkclass.get("signature") or ""),
                    "cdmw_member_count": _hkx_xml_scalar(hkclass.get("member_count")),
                    "cdmw_metadata_status": str(hkclass.get("metadata_status") or ""),
                    "cdmw_real_hkclass_metadata_recovered": "true"
                    if bool(hkclass.get("real_hkclass_metadata_recovered"))
                    else "false",
                    "cdmw_metadata_source": str(hkclass.get("metadata_source") or ""),
                    "cdmw_member_offset_confidence": str(hkclass.get("member_offset_confidence") or ""),
                },
            )
            ET.SubElement(class_element, "hkparam", {"name": "name"}).text = str(hkclass.get("name") or "")
            ET.SubElement(class_element, "hkparam", {"name": "objectSize"}).text = _hkx_xml_scalar(hkclass.get("object_size"))
            ET.SubElement(class_element, "hkparam", {"name": "version"}).text = _hkx_xml_scalar(hkclass.get("version"))
            ET.SubElement(class_element, "hkparam", {"name": "signature"}).text = str(hkclass.get("signature") or "")
            ET.SubElement(class_element, "hkparam", {"name": "flags"}).text = str(hkclass.get("flags") or "FLAGS_NONE")
            base_name = str(hkclass.get("base_name") or "")
            if base_name and base_name != str(hkclass.get("name") or ""):
                ET.SubElement(class_element, "hkparam", {"name": "cdmwBaseName"}).text = base_name
            unresolved_metadata = hkclass.get("unresolved_real_metadata")
            if isinstance(unresolved_metadata, list) and unresolved_metadata:
                unresolved_param = ET.SubElement(
                    class_element,
                    "hkparam",
                    {"name": "cdmwUnresolvedRealMetadata", "numelements": _hkx_xml_scalar(len(unresolved_metadata))},
                )
                unresolved_param.text = " ".join(str(value) for value in unresolved_metadata)
            template_parameters = hkclass.get("template_parameters")
            if isinstance(template_parameters, list) and template_parameters:
                template_param = ET.SubElement(class_element, "hkparam", {"name": "templateParameters"})
                template_param.text = " ".join(
                    f"{param.get('name')}={param.get('value')}"
                    for param in template_parameters
                    if isinstance(param, Mapping)
                )
            members = hkclass.get("members")
            if isinstance(members, list) and members:
                members_param = ET.SubElement(
                    class_element,
                    "hkparam",
                    {
                        "name": "members",
                        "numelements": _hkx_xml_scalar(len(members)),
                        "cdmw_status": "real_hkClassMember_records"
                        if bool(hkclass.get("real_hkclass_metadata_recovered"))
                        else "synthetic_recovered_members",
                    },
                )
                for member in members:
                    if not isinstance(member, Mapping):
                        continue
                    source_names = member.get("source_names")
                    if isinstance(source_names, (list, tuple)):
                        source_text = " ".join(str(name) for name in source_names)
                    else:
                        source_text = ""
                    ET.SubElement(
                        members_param,
                        "member",
                        {
                            "name": str(member.get("name") or ""),
                            "type": str(member.get("type") or ""),
                            "offset": _hkx_xml_scalar(member.get("offset")),
                            "array_status": str(member.get("array_status") or "none"),
                            "reference_status": str(member.get("reference_status") or "none"),
                            "member_type": str(member.get("member_type") or ""),
                            "member_type_code": _hkx_xml_scalar(member.get("member_type_code")),
                            "subtype": str(member.get("subtype") or ""),
                            "subtype_code": _hkx_xml_scalar(member.get("subtype_code")),
                            "class_ref": str(member.get("class_ref") or ""),
                            "class_ref_record_index": _hkx_xml_scalar(member.get("class_ref_record_index")),
                            "enum_ref": str(member.get("enum_ref") or ""),
                            "enum_ref_record_index": _hkx_xml_scalar(member.get("enum_ref_record_index")),
                            "flags": str(member.get("flags") or "FLAGS_NONE"),
                            "member_flags": _hkx_xml_scalar(member.get("member_flags")),
                            "c_array_size": _hkx_xml_scalar(member.get("c_array_size")),
                            "template_ref": str(member.get("template_ref") or ""),
                            "storage": str(member.get("storage") or ""),
                            "is_array": "true" if bool(member.get("is_array")) else "false",
                            "is_pointer": "true" if bool(member.get("is_pointer")) else "false",
                            "confidence": str(member.get("confidence") or "experimental"),
                            "cdmw_recovered": "true" if bool(member.get("cdmw_recovered")) else "false",
                            "real_hkclass_metadata_recovered": "true"
                            if bool(member.get("real_hkclass_metadata_recovered"))
                            else "false",
                            "cdmw_source_names": source_text,
                        },
                    )


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_havok_param_rows',
    '_hkx_xml_scalar',
)
def _hkx_xml_add_packfile_object(section_element, hkobject):
    object_element = ET.SubElement(
        section_element,
        "hkobject",
        {
            "name": str(hkobject.get("id") or ""),
            "class": str(hkobject.get("class") or ""),
            "record_index": _hkx_xml_scalar(hkobject.get("record_index")),
            "status": str(hkobject.get("status") or ""),
            "stable_order_index": _hkx_xml_scalar(hkobject.get("stable_order_index")),
            "stable_order_key": str(hkobject.get("stable_order_key") or ""),
        },
    )
    fields = hkobject.get("fields")
    if not isinstance(fields, list):
        return
    for field in fields:
        if not isinstance(field, Mapping):
            continue
        param_attrs = {
            "name": str(field.get("hkparam_name") or field.get("name") or ""),
            "data_type": str(field.get("type") or ""),
            "offset": _hkx_xml_scalar(field.get("offset")),
            "confidence": str(field.get("confidence") or ""),
            "editable": "true" if bool(field.get("editable")) else "false",
            "reference_target": str(field.get("reference_target") or ""),
            "reference_kind": str(field.get("reference_kind") or ""),
            "reference_category": str(field.get("reference_category") or ""),
            "reference_status": str(field.get("reference_status") or ""),
            "reference_target_type": str(field.get("reference_target_type") or ""),
            "array_status": str(field.get("array_status") or ""),
            "fixup_backed": "true" if bool(field.get("fixup_backed")) else "false",
            "fixup_source": str(field.get("fixup_source") or ""),
            "reference_resolution_source": str(field.get("reference_resolution_source") or ""),
            "decode_source": str(field.get("decode_source") or ""),
            "decode_strength": str(field.get("decode_strength") or ""),
            "safe_edit_policy": str(field.get("safe_edit_policy") or ""),
            "read_only_reason": str(field.get("read_only_reason") or ""),
            "ptch_patch_site_offset": _hkx_xml_scalar(field.get("ptch_patch_site_offset")),
            "ptch_patch_site_hex_offset": str(field.get("ptch_patch_site_hex_offset") or ""),
            "ptch_word_index": _hkx_xml_scalar(field.get("ptch_word_index")),
            "ptch_target_status": str(field.get("ptch_target_status") or ""),
        }
        if field.get("numelements") is not None:
            param_attrs["numelements"] = _hkx_xml_scalar(field.get("numelements"))
        param_element = ET.SubElement(object_element, "hkparam", param_attrs)
        param_element.text = str(field.get("hkparam_text") or "")
        _hkx_xml_add_havok_param_rows(param_element, field)
    if bool(hkobject.get("raw_preserved")):
        ET.SubElement(
            object_element,
            "hkparam",
            {
                "name": "cdmwRawPayloadPreserved",
                "data_type": "raw-bytes",
                "editable": "false",
                "confidence": "confirmed",
            },
        ).text = "true"


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_xml_add_packfile_object',
)
def _hkx_xml_add_packfile_objects(section_element, hkobjects):
    for hkobject in hkobjects:
        if isinstance(hkobject, Mapping):
            _hkx_xml_add_packfile_object(section_element, hkobject)


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_havok_classes',
    '_hkx_xml_add_packfile_objects',
    '_hkx_xml_add_text',
)
def _hkx_xml_add_havok_packfile(view_element, havok_xml_view, hkobjects, hkpackfile_view):
    if not (isinstance(hkpackfile_view, Mapping) and isinstance(hkobjects, list)):
        return
    packfile_view_element = ET.SubElement(
        view_element,
        "hkpackfileView",
        {
            "status": str(hkpackfile_view.get("status") or "read_only_parity_view"),
            "official_havok_xml": "false",
            "imported": "false",
        },
    )
    _hkx_xml_add_text(packfile_view_element, "description", hkpackfile_view.get("description", ""))
    packfile_element = ET.SubElement(
        packfile_view_element,
        "hkpackfile",
        {
            "classversion": str(hkpackfile_view.get("classversion") or ""),
            "contentsversion": str(hkpackfile_view.get("contentsversion") or ""),
            "toplevelobject": str(hkpackfile_view.get("toplevelobject") or ""),
        },
    )
    hkclasses = havok_xml_view.get("hkclasses")
    _hkx_xml_add_havok_classes(packfile_element, hkclasses)
    section_element = ET.SubElement(
        packfile_element,
        "hksection",
        {
            "name": str(hkpackfile_view.get("section_name") or "__data__"),
        },
    )
    _hkx_xml_add_packfile_objects(section_element, hkobjects)


@bind_archive_hkx_globals(
    'ET',
    'Mapping',
    '_hkx_xml_add_text',
    '_hkx_xml_scalar',
    'json',
)
def _hkx_xml_add_flat_havok_object(view_element, hkobject):
    object_element = ET.SubElement(
        view_element,
        "hkobject",
        {
            "id": str(hkobject.get("id") or ""),
            "class": str(hkobject.get("class") or ""),
            "record_index": _hkx_xml_scalar(hkobject.get("record_index")),
            "type_index": _hkx_xml_scalar(hkobject.get("type_index")),
            "count": _hkx_xml_scalar(hkobject.get("count")),
            "byte_length": _hkx_xml_scalar(hkobject.get("byte_length")),
            "status": str(hkobject.get("status") or ""),
            "confidence": str(hkobject.get("confidence") or ""),
            "raw_preserved": "true" if bool(hkobject.get("raw_preserved")) else "false",
            "field_count": _hkx_xml_scalar(hkobject.get("field_count")),
            "reference_count": _hkx_xml_scalar(hkobject.get("reference_count")),
            "truncated_fields": _hkx_xml_scalar(hkobject.get("truncated_fields")),
            "stable_order_index": _hkx_xml_scalar(hkobject.get("stable_order_index")),
            "stable_order_key": str(hkobject.get("stable_order_key") or ""),
        },
    )
    references = hkobject.get("references")
    if isinstance(references, list) and references:
        references_element = ET.SubElement(object_element, "references")
        for reference in references:
            if not isinstance(reference, Mapping):
                continue
            ET.SubElement(
                references_element,
                "reference",
                {
                    "offset": _hkx_xml_scalar(reference.get("offset")),
                    "hex_offset": str(reference.get("hex_offset") or ""),
                    "kind": str(reference.get("kind") or ""),
                    "category": str(reference.get("category") or ""),
                    "raw_value": _hkx_xml_scalar(reference.get("raw_value")),
                    "target": str(reference.get("target") or ""),
                    "target_record_index": _hkx_xml_scalar(reference.get("target_record_index")),
                    "target_type_index": _hkx_xml_scalar(reference.get("target_type_index")),
                    "target_type_name": str(reference.get("target_type_name") or ""),
                    "target_status": str(reference.get("target_status") or ""),
                    "confidence": str(reference.get("confidence") or ""),
                    "source": str(reference.get("source") or ""),
                    "fixup_backed": "true" if bool(reference.get("fixup_backed")) else "false",
                    "fixup_source": str(reference.get("fixup_source") or ""),
                    "ptch_patch_site_offset": _hkx_xml_scalar(reference.get("ptch_patch_site_offset")),
                    "ptch_patch_site_hex_offset": str(reference.get("ptch_patch_site_hex_offset") or ""),
                    "ptch_word_index": _hkx_xml_scalar(reference.get("ptch_word_index")),
                },
            )
    fields = hkobject.get("fields")
    if not isinstance(fields, list):
        return
    for field in fields:
        if not isinstance(field, Mapping):
            continue
        field_attrs = {
            "name": str(field.get("name") or ""),
            "type": str(field.get("type") or ""),
            "offset": _hkx_xml_scalar(field.get("offset")),
            "hex_offset": str(field.get("hex_offset") or ""),
            "size": _hkx_xml_scalar(field.get("size")),
            "editable": "true" if bool(field.get("editable")) else "false",
            "confidence": str(field.get("confidence") or ""),
            "description": str(field.get("description") or ""),
            "reference_target": str(field.get("reference_target") or ""),
            "reference_kind": str(field.get("reference_kind") or ""),
            "reference_category": str(field.get("reference_category") or ""),
            "reference_status": str(field.get("reference_status") or ""),
            "reference_target_type": str(field.get("reference_target_type") or ""),
            "array_status": str(field.get("array_status") or ""),
            "fixup_backed": "true" if bool(field.get("fixup_backed")) else "false",
            "fixup_source": str(field.get("fixup_source") or ""),
            "reference_resolution_source": str(field.get("reference_resolution_source") or ""),
            "decode_source": str(field.get("decode_source") or ""),
            "decode_strength": str(field.get("decode_strength") or ""),
            "safe_edit_policy": str(field.get("safe_edit_policy") or ""),
            "read_only_reason": str(field.get("read_only_reason") or ""),
            "ptch_patch_site_offset": _hkx_xml_scalar(field.get("ptch_patch_site_offset")),
            "ptch_patch_site_hex_offset": str(field.get("ptch_patch_site_hex_offset") or ""),
            "ptch_word_index": _hkx_xml_scalar(field.get("ptch_word_index")),
            "ptch_target_status": str(field.get("ptch_target_status") or ""),
        }
        if field.get("numelements") is not None:
            field_attrs["numelements"] = _hkx_xml_scalar(field.get("numelements"))
        field_element = ET.SubElement(object_element, "field", field_attrs)
        if "value" in field:
            _hkx_xml_add_text(
                field_element,
                "value",
                json.dumps(field.get("value"), sort_keys=True),
                encoding="json",
            )


@bind_archive_hkx_globals(
    'Mapping',
    '_hkx_xml_add_flat_havok_object',
)
def _hkx_xml_add_flat_havok_objects(view_element, hkobjects):
    if not isinstance(hkobjects, list):
        return
    for hkobject in hkobjects:
        if isinstance(hkobject, Mapping):
            _hkx_xml_add_flat_havok_object(view_element, hkobject)
