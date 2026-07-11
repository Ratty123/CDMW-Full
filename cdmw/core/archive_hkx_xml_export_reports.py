from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Mapping


def _hkx_xml_add_source(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    source = document.get("source")
    if isinstance(source, Mapping):
        source_attrs = {
            "path": source.get("path"),
            "sdk_version": source.get("sdk_version"),
            "declared_size": source.get("declared_size"),
            "payload_size": source.get("payload_size"),
            "size_matches": source.get("size_matches"),
        }
        ET.SubElement(root, "source", {key: hkx._hkx_xml_scalar(value) for key, value in source_attrs.items() if value is not None})


def _hkx_xml_add_compatibility(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    compatibility = document.get("cdmw_hkx_compatibility")
    if isinstance(compatibility, Mapping):
        compatibility_element = ET.SubElement(
            root,
            "cdmwHkxCompatibility",
            {
                "status": str(compatibility.get("status") or "unsupported"),
            },
        )
        hkx._hkx_xml_add_text(compatibility_element, "description", compatibility.get("description", ""))
        gates = compatibility.get("gates")
        if isinstance(gates, Mapping):
            gates_element = ET.SubElement(compatibility_element, "gates")
            for gate_name, gate_value in gates.items():
                ET.SubElement(
                    gates_element,
                    "gate",
                    {
                        "name": str(gate_name),
                        "value": hkx._hkx_xml_scalar(gate_value),
                    },
                )
        status_scale = compatibility.get("status_scale")
        if isinstance(status_scale, list):
            scale_element = ET.SubElement(compatibility_element, "statusScale")
            for index, status in enumerate(status_scale):
                ET.SubElement(scale_element, "status", {"index": hkx._hkx_xml_scalar(index), "name": str(status)})
        unsupported_edits = compatibility.get("unsupported_edits")
        if isinstance(unsupported_edits, list):
            unsupported_element = ET.SubElement(compatibility_element, "unsupportedEdits")
            for edit in unsupported_edits:
                hkx._hkx_xml_add_text(unsupported_element, "unsupportedEdit", edit)


def _hkx_xml_add_user_guide(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    user_guide = document.get("user_editing_guide")
    if isinstance(user_guide, Mapping):
        guide_element = ET.SubElement(root, "userEditingGuide", {"status": str(user_guide.get("status") or "")})
        hkx._hkx_xml_add_text(guide_element, "summary", user_guide.get("summary", ""))
        legend = user_guide.get("confidence_legend")
        if isinstance(legend, list):
            legend_element = ET.SubElement(guide_element, "confidenceLegend")
            for row in legend:
                if isinstance(row, Mapping):
                    ET.SubElement(
                        legend_element,
                        "confidence",
                        {
                            "label": str(row.get("label") or ""),
                            "meaning": str(row.get("meaning") or ""),
                            "suggested_action": str(row.get("suggested_action") or ""),
                        },
                    )
        for source_key, group_name, row_name in (
            ("safe_first_edits", "safeFirstEdits", "edit"),
            ("avoid_until_decoded", "avoidUntilDecoded", "avoid"),
            ("workflow", "workflow", "step"),
        ):
            values = user_guide.get(source_key)
            if isinstance(values, list):
                group_element = ET.SubElement(guide_element, group_name)
                for value in values:
                    hkx._hkx_xml_add_text(group_element, row_name, value)


def _hkx_xml_add_decode_gap_summary(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    decode_gap_summary = document.get("decode_gap_summary")
    if isinstance(decode_gap_summary, Mapping):
        gaps_element = ET.SubElement(
            root,
            "decodeGapSummary",
            {
                "format": str(decode_gap_summary.get("format") or ""),
                "status": str(decode_gap_summary.get("status") or ""),
                "gap_count": hkx._hkx_xml_scalar(decode_gap_summary.get("gap_count")),
                "partial_record_count": hkx._hkx_xml_scalar(decode_gap_summary.get("partial_record_count")),
                "raw_preserved_record_count": hkx._hkx_xml_scalar(decode_gap_summary.get("raw_preserved_record_count")),
                "total_unresolved_byte_count": hkx._hkx_xml_scalar(decode_gap_summary.get("total_unresolved_byte_count")),
                "truncated_gap_count": hkx._hkx_xml_scalar(decode_gap_summary.get("truncated_gap_count")),
                "imported": "false",
            },
        )
        hkx._hkx_xml_add_text(gaps_element, "description", decode_gap_summary.get("description", ""))
        gaps = decode_gap_summary.get("gaps")
        if isinstance(gaps, list):
            gap_rows_element = ET.SubElement(gaps_element, "gaps")
            for gap in gaps:
                if not isinstance(gap, Mapping):
                    continue
                gap_element = ET.SubElement(
                    gap_rows_element,
                    "gap",
                    {
                        "priority_rank": hkx._hkx_xml_scalar(gap.get("priority_rank")),
                        "type_name": str(gap.get("type_name") or ""),
                        "record_count": hkx._hkx_xml_scalar(gap.get("record_count")),
                        "partial_record_count": hkx._hkx_xml_scalar(gap.get("partial_record_count")),
                        "raw_preserved_record_count": hkx._hkx_xml_scalar(gap.get("raw_preserved_record_count")),
                        "byte_length": hkx._hkx_xml_scalar(gap.get("byte_length")),
                        "typed_layout_byte_count": hkx._hkx_xml_scalar(gap.get("typed_layout_byte_count")),
                        "candidate_layout_byte_count": hkx._hkx_xml_scalar(gap.get("candidate_layout_byte_count")),
                        "unresolved_byte_count": hkx._hkx_xml_scalar(gap.get("unresolved_byte_count")),
                        "unresolved_byte_share": hkx._hkx_xml_scalar(gap.get("unresolved_byte_share")),
                        "decoded_field_count": hkx._hkx_xml_scalar(gap.get("decoded_field_count")),
                        "reference_candidate_count": hkx._hkx_xml_scalar(gap.get("reference_candidate_count")),
                        "decode_category": str(gap.get("decode_category") or ""),
                        "status": str(gap.get("status") or ""),
                        "friendly_status_label": str(gap.get("friendly_status_label") or ""),
                        "suggested_next_decoder_step": str(gap.get("suggested_next_decoder_step") or ""),
                        "safe_edit_policy": str(gap.get("safe_edit_policy") or ""),
                    },
                )
                hkx._hkx_xml_add_text(gap_element, "whatThisMeans", gap.get("what_this_means", ""))
                hkx._hkx_xml_add_text(gap_element, "whatIsMissing", gap.get("what_is_missing", ""))
                missing = gap.get("missing_requirements")
                if isinstance(missing, list) and missing:
                    missing_element = ET.SubElement(gap_element, "missingRequirements")
                    for requirement in missing:
                        hkx._hkx_xml_add_text(missing_element, "requirement", requirement)


def _hkx_xml_add_decoder_evidence_v2(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    decoder_evidence_v2 = document.get("decoder_evidence_v2")
    if isinstance(decoder_evidence_v2, Mapping):
        evidence_element = ET.SubElement(
            root,
            "decoderEvidence",
            {
                "format": str(decoder_evidence_v2.get("format") or ""),
                "native_format": str(decoder_evidence_v2.get("native_format") or ""),
                "status": str(decoder_evidence_v2.get("status") or ""),
                "source": str(decoder_evidence_v2.get("source") or ""),
                "read_only": "true",
                "class_status_count": hkx._hkx_xml_scalar(decoder_evidence_v2.get("class_status_count")),
                "priority_class_count": hkx._hkx_xml_scalar(decoder_evidence_v2.get("priority_class_count")),
                "total_partial_byte_count": hkx._hkx_xml_scalar(decoder_evidence_v2.get("total_partial_byte_count")),
                "unresolved_or_packed_case_count": hkx._hkx_xml_scalar(
                    decoder_evidence_v2.get("unresolved_or_packed_case_count")
                ),
                "owner_array_count": hkx._hkx_xml_scalar(decoder_evidence_v2.get("owner_array_count")),
                "imported": "false",
            },
        )
        hkx._hkx_xml_add_text(evidence_element, "description", decoder_evidence_v2.get("description", ""))
        semantics = decoder_evidence_v2.get("reference_semantic_counts")
        if isinstance(semantics, Mapping):
            semantics_element = ET.SubElement(evidence_element, "referenceSemantics")
            for semantic, count in sorted(semantics.items()):
                ET.SubElement(
                    semantics_element,
                    "semantic",
                    {"name": str(semantic), "count": hkx._hkx_xml_scalar(count)},
                )
        link_counts = decoder_evidence_v2.get("link_evidence_counts")
        if isinstance(link_counts, Mapping):
            link_element = ET.SubElement(evidence_element, "linkEvidence")
            for evidence_name, count in sorted(link_counts.items()):
                ET.SubElement(
                    link_element,
                    "evidence",
                    {"name": str(evidence_name), "count": hkx._hkx_xml_scalar(count)},
                )
        class_statuses = decoder_evidence_v2.get("class_statuses")
        if isinstance(class_statuses, list):
            class_rows_element = ET.SubElement(evidence_element, "classStatuses")
            for row in class_statuses:
                if not isinstance(row, Mapping):
                    continue
                row_element = ET.SubElement(
                    class_rows_element,
                    "class",
                    {
                        "type_name": str(row.get("type_name") or ""),
                        "record_count": hkx._hkx_xml_scalar(row.get("record_count")),
                        "byte_count": hkx._hkx_xml_scalar(row.get("byte_count")),
                        "decoded_field_count": hkx._hkx_xml_scalar(row.get("decoded_field_count")),
                        "reference_count": hkx._hkx_xml_scalar(row.get("reference_count")),
                        "editable_field_count": hkx._hkx_xml_scalar(row.get("editable_field_count")),
                        "status": str(row.get("status") or ""),
                        "friendly_status": str(row.get("friendly_status") or ""),
                        "corpus_priority_score": hkx._hkx_xml_scalar(row.get("corpus_priority_score")),
                        "read_only": "true",
                    },
                )
                missing = row.get("missing_requirements")
                if isinstance(missing, list) and missing:
                    missing_element = ET.SubElement(row_element, "missingRequirements")
                    for requirement in missing:
                        hkx._hkx_xml_add_text(missing_element, "requirement", requirement)
                link_evidence = row.get("link_evidence")
                if isinstance(link_evidence, list) and link_evidence:
                    link_row_element = ET.SubElement(row_element, "linkEvidence")
                    for evidence_name in link_evidence:
                        ET.SubElement(link_row_element, "evidence", {"name": str(evidence_name)})
        fixup_backed_fields = decoder_evidence_v2.get("fixup_backed_fields")
        if isinstance(fixup_backed_fields, list) and fixup_backed_fields:
            fields_element = ET.SubElement(evidence_element, "fixupBackedFields")
            for field in fixup_backed_fields:
                if not isinstance(field, Mapping):
                    continue
                ET.SubElement(
                    fields_element,
                    "field",
                    {
                        "class_name": str(field.get("class_name") or ""),
                        "field_name": str(field.get("field_name") or ""),
                        "reference_category": str(field.get("reference_category") or ""),
                        "count": hkx._hkx_xml_scalar(field.get("count")),
                        "confidence": str(field.get("confidence") or ""),
                    },
                )


def _hkx_xml_add_tag_sections(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    tag_sections = document.get("tag_sections")
    if isinstance(tag_sections, list):
        sections_element = ET.SubElement(root, "tagSections")
        for section in tag_sections:
            if not isinstance(section, Mapping):
                continue
            ET.SubElement(
                sections_element,
                "section",
                {
                    "name": str(section.get("name") or ""),
                    "offset": hkx._hkx_xml_scalar(section.get("offset")),
                    "declared_length": hkx._hkx_xml_scalar(section.get("declared_length")),
                    "flags": hkx._hkx_xml_scalar(section.get("length_flags")),
                    "data_end": hkx._hkx_xml_scalar(section.get("data_end")),
                },
            )


def _hkx_xml_add_fixup_semantics_report(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    fixup_semantics_report = document.get("fixup_semantics_report")
    if isinstance(fixup_semantics_report, Mapping):
        semantics_element = ET.SubElement(
            root,
            "fixupSemanticsReport",
            {
                "format": str(fixup_semantics_report.get("format") or ""),
                "status": str(fixup_semantics_report.get("status") or ""),
                "imported": "false",
                "ptch_table_count": hkx._hkx_xml_scalar(fixup_semantics_report.get("ptch_table_count")),
                "ptch_patch_site_count": hkx._hkx_xml_scalar(fixup_semantics_report.get("ptch_patch_site_count")),
                "ptch_object_patch_site_count": hkx._hkx_xml_scalar(
                    fixup_semantics_report.get("ptch_object_patch_site_count")
                ),
                "ptch_null_patch_site_count": hkx._hkx_xml_scalar(
                    fixup_semantics_report.get("ptch_null_patch_site_count")
                ),
                "ptch_unresolved_patch_site_count": hkx._hkx_xml_scalar(
                    fixup_semantics_report.get("ptch_unresolved_patch_site_count")
                ),
            },
        )
        hkx._hkx_xml_add_text(semantics_element, "description", fixup_semantics_report.get("description", ""))
        for report_key, group_name, row_name, name_attr in (
            ("ptch_tuple_shape_counts", "ptchTupleShapes", "ptchTupleShape", "shape"),
            ("ptch_payload_match_kind_counts", "ptchPayloadMatchKinds", "ptchPayloadMatchKind", "kind"),
            ("ptch_reference_category_counts", "ptchReferenceCategories", "ptchReferenceCategory", "category"),
            ("ptch_target_status_counts", "ptchTargetStatuses", "ptchTargetStatus", "status"),
            ("varuint_status_counts", "varuintStatuses", "varuintStatus", "status"),
        ):
            counts = fixup_semantics_report.get(report_key)
            if not isinstance(counts, Mapping):
                continue
            group_element = ET.SubElement(semantics_element, group_name)
            for name, count in counts.items():
                ET.SubElement(group_element, row_name, {name_attr: str(name), "count": hkx._hkx_xml_scalar(count)})
        remaining_cases = fixup_semantics_report.get("ptch_remaining_case_priorities")
        if isinstance(remaining_cases, list):
            cases_element = ET.SubElement(semantics_element, "remainingCases")
            for case in remaining_cases:
                if not isinstance(case, Mapping):
                    continue
                ET.SubElement(
                    cases_element,
                    "remainingCase",
                    {
                        "priority_rank": hkx._hkx_xml_scalar(case.get("priority_rank")),
                        "case": str(case.get("case") or ""),
                        "count": hkx._hkx_xml_scalar(case.get("count")),
                        "description": str(case.get("description") or ""),
                    },
                )
        section_summaries = fixup_semantics_report.get("section_summaries")
        if isinstance(section_summaries, list):
            sections_element = ET.SubElement(semantics_element, "sections")
            for section in section_summaries:
                if not isinstance(section, Mapping):
                    continue
                ET.SubElement(
                    sections_element,
                    "section",
                    {
                        "name": str(section.get("name") or ""),
                        "payload_byte_length": hkx._hkx_xml_scalar(section.get("payload_byte_length")),
                        "word_count": hkx._hkx_xml_scalar(section.get("word_count")),
                        "ptch_table_count": hkx._hkx_xml_scalar(section.get("ptch_table_count")),
                        "ptch_patch_site_count": hkx._hkx_xml_scalar(section.get("ptch_patch_site_count")),
                        "ptch_patch_site_resolved_count": hkx._hkx_xml_scalar(
                            section.get("ptch_patch_site_resolved_count")
                        ),
                        "ptch_patch_site_unresolved_count": hkx._hkx_xml_scalar(
                            section.get("ptch_patch_site_unresolved_count")
                        ),
                        "varuint_status": str(section.get("varuint_status") or ""),
                        "match_kind_counts": json.dumps(section.get("match_kind_counts") or {}, sort_keys=True),
                        "reference_category_counts": json.dumps(
                            section.get("reference_category_counts") or {},
                            sort_keys=True,
                        ),
                    },
                )


def _hkx_xml_add_type_registry(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    type_registry = document.get("type_registry")
    if isinstance(type_registry, Mapping):
        registry_element = ET.SubElement(
            root,
            "typeRegistry",
            {"declared_type_name_count": hkx._hkx_xml_scalar(type_registry.get("declared_type_name_count"))},
        )
        type_infos = type_registry.get("type_infos")
        if isinstance(type_infos, list):
            for type_info in type_infos:
                if not isinstance(type_info, Mapping):
                    continue
                type_element = ET.SubElement(
                    registry_element,
                    "type",
                    {
                        "index": hkx._hkx_xml_scalar(type_info.get("index")),
                        "name": str(type_info.get("name") or ""),
                        "display_name": str(type_info.get("display_name") or ""),
                    },
                )
                parameters = type_info.get("template_parameters")
                if isinstance(parameters, list):
                    for parameter in parameters:
                        if isinstance(parameter, Mapping):
                            ET.SubElement(
                                type_element,
                                "templateParameter",
                                {
                                    "name": str(parameter.get("name") or ""),
                                    "value": hkx._hkx_xml_scalar(parameter.get("value")),
                                },
                            )


def _hkx_xml_add_parity_report(root: ET.Element, document: Mapping[str, object]) -> None:
    from cdmw.core import archive_hkx as hkx

    parity_report = document.get("hkx_xml_parity_report")
    if isinstance(parity_report, Mapping):
        parity_element = ET.SubElement(
            root,
            "hkxXmlParityReport",
            {
                "format": str(parity_report.get("format") or ""),
                "status": str(parity_report.get("status") or ""),
                "imported": "false",
                "exact_fields_decoded": hkx._hkx_xml_scalar(parity_report.get("exact_fields_decoded")),
                "layout_fields_available": hkx._hkx_xml_scalar(parity_report.get("layout_fields_available")),
                "havok_like_params_emitted": hkx._hkx_xml_scalar(parity_report.get("havok_like_params_emitted")),
                "havok_named_params_emitted": hkx._hkx_xml_scalar(parity_report.get("havok_named_params_emitted")),
                "unknown_fields_preserved_as_cdmw_raw_metadata": hkx._hkx_xml_scalar(
                    parity_report.get("unknown_fields_preserved_as_cdmw_raw_metadata")
                ),
                "array_params_with_numelements": hkx._hkx_xml_scalar(parity_report.get("array_params_with_numelements")),
                "references_resolved": hkx._hkx_xml_scalar(parity_report.get("references_resolved")),
                "references_unresolved": hkx._hkx_xml_scalar(parity_report.get("references_unresolved")),
                "ptch_patch_sites_found": hkx._hkx_xml_scalar(parity_report.get("ptch_patch_sites_found")),
                "ptch_patch_sites_resolved": hkx._hkx_xml_scalar(parity_report.get("ptch_patch_sites_resolved")),
                "ptch_patch_sites_object_resolved": hkx._hkx_xml_scalar(parity_report.get("ptch_patch_sites_object_resolved")),
                "ptch_patch_sites_null": hkx._hkx_xml_scalar(parity_report.get("ptch_patch_sites_null")),
                "ptch_patch_sites_unresolved": hkx._hkx_xml_scalar(parity_report.get("ptch_patch_sites_unresolved")),
                "ptch_fixup_backed_references": hkx._hkx_xml_scalar(parity_report.get("ptch_fixup_backed_references")),
                "object_references_resolved_by_ptch": hkx._hkx_xml_scalar(parity_report.get("object_references_resolved_by_ptch")),
                "object_references_resolved_by_inference": hkx._hkx_xml_scalar(
                    parity_report.get("object_references_resolved_by_inference")
                ),
            },
        )
        hkx._hkx_xml_add_text(parity_element, "description", parity_report.get("description", ""))
        root_object = parity_report.get("root_object")
        if isinstance(root_object, Mapping):
            root_element = ET.SubElement(
                parity_element,
                "rootObject",
                {
                    "toplevelobject": str(root_object.get("toplevelobject") or ""),
                    "class": str(root_object.get("class") or ""),
                    "method": str(root_object.get("method") or ""),
                    "confidence": str(root_object.get("confidence") or ""),
                    "named_variant_count": hkx._hkx_xml_scalar(root_object.get("named_variant_count")),
                },
            )
            named_variants = root_object.get("named_variants")
            if isinstance(named_variants, list):
                for variant in named_variants:
                    if isinstance(variant, Mapping):
                        ET.SubElement(
                            root_element,
                            "namedVariant",
                            {
                                "record": str(variant.get("record") or ""),
                                "name": str(variant.get("name") or ""),
                                "className": str(variant.get("className") or ""),
                                "variant": str(variant.get("variant") or ""),
                                "variant_class": str(variant.get("variant_class") or ""),
                            },
                        )
        category_counts = parity_report.get("reference_category_counts")
        if isinstance(category_counts, Mapping):
            categories_element = ET.SubElement(parity_element, "referenceCategoryCounts")
            for category, count in category_counts.items():
                ET.SubElement(categories_element, "category", {"name": str(category), "count": hkx._hkx_xml_scalar(count)})
        source_counts = parity_report.get("reference_resolution_source_counts")
        if isinstance(source_counts, Mapping):
            sources_element = ET.SubElement(parity_element, "referenceResolutionSourceCounts")
            for source, count in source_counts.items():
                ET.SubElement(sources_element, "source", {"name": str(source), "count": hkx._hkx_xml_scalar(count)})
        ptch_status_counts = parity_report.get("ptch_target_status_counts")
        if isinstance(ptch_status_counts, Mapping):
            statuses_element = ET.SubElement(parity_element, "ptchTargetStatusCounts")
            for status, count in ptch_status_counts.items():
                ET.SubElement(statuses_element, "status", {"name": str(status), "count": hkx._hkx_xml_scalar(count)})
        fixup_fields = parity_report.get("fixup_backed_fields_by_class")
        if isinstance(fixup_fields, Mapping):
            fixup_fields_element = ET.SubElement(parity_element, "fixupBackedFieldsByClass")
            for class_name, fields in fixup_fields.items():
                class_element = ET.SubElement(fixup_fields_element, "class", {"name": str(class_name)})
                if isinstance(fields, list):
                    for field_name in fields:
                        ET.SubElement(class_element, "field", {"name": str(field_name), "fixup_source": "PTCH"})
        class_parity = parity_report.get("class_parity")
        if isinstance(class_parity, list):
            classes_element = ET.SubElement(parity_element, "classParity")
            for class_row in class_parity:
                if not isinstance(class_row, Mapping):
                    continue
                class_element = ET.SubElement(
                    classes_element,
                    "class",
                    {
                        "name": str(class_row.get("class") or ""),
                        "object_count": hkx._hkx_xml_scalar(class_row.get("object_count")),
                        "emitted_param_count": hkx._hkx_xml_scalar(class_row.get("emitted_param_count")),
                        "havok_named_param_count": hkx._hkx_xml_scalar(class_row.get("havok_named_param_count")),
                        "raw_metadata_param_count": hkx._hkx_xml_scalar(class_row.get("raw_metadata_param_count")),
                        "resolved_reference_count": hkx._hkx_xml_scalar(class_row.get("resolved_reference_count")),
                        "unresolved_reference_count": hkx._hkx_xml_scalar(class_row.get("unresolved_reference_count")),
                        "fixup_backed_reference_count": hkx._hkx_xml_scalar(class_row.get("fixup_backed_reference_count")),
                        "ptch_resolved_reference_count": hkx._hkx_xml_scalar(class_row.get("ptch_resolved_reference_count")),
                        "inferred_reference_count": hkx._hkx_xml_scalar(class_row.get("inferred_reference_count")),
                        "raw_preserved_object_count": hkx._hkx_xml_scalar(class_row.get("raw_preserved_object_count")),
                        "parity_confidence": str(class_row.get("parity_confidence") or ""),
                    },
                )
                fixup_field_names = class_row.get("fixup_backed_fields")
                if isinstance(fixup_field_names, list) and fixup_field_names:
                    fields_element = ET.SubElement(class_element, "fixupBackedFields")
                    for field_name in fixup_field_names:
                        ET.SubElement(fields_element, "field", {"name": str(field_name), "fixup_source": "PTCH"})
                confidence_counts = class_row.get("confidence_counts")
                if isinstance(confidence_counts, Mapping):
                    for confidence, count in confidence_counts.items():
                        ET.SubElement(class_element, "confidence", {"name": str(confidence), "count": hkx._hkx_xml_scalar(count)})
        import_safety = parity_report.get("import_safety")
        if isinstance(import_safety, Mapping):
            safety_element = ET.SubElement(
                parity_element,
                "importSafety",
                {
                    "havok_xml_view_importable": "true" if bool(import_safety.get("havok_xml_view_importable")) else "false",
                    "safe_modding_path": str(import_safety.get("safe_modding_path") or ""),
                },
            )
            blocked_until = import_safety.get("blocked_until")
            if isinstance(blocked_until, list):
                for reason in blocked_until:
                    hkx._hkx_xml_add_text(safety_element, "blockedUntil", reason)
